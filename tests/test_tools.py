"""Offline tests against a fake Gmail.

Run with: uv run --with pytest --with requests pytest tests
"""

import base64
import email
import email.policy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gmail_client as gm  # noqa: E402

LABELS = [
    {"id": "INBOX", "name": "INBOX", "type": "system"},
    {"id": "UNREAD", "name": "UNREAD", "type": "system"},
    {"id": "Label_1", "name": "Receipts", "type": "user"},
]


class Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def b64(text: str | bytes) -> str:
    data = text.encode() if isinstance(text, str) else text
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def message(message_id="m1", parts=None, headers=None, labels=("INBOX", "UNREAD")):
    headers = headers or {"From": "Anna <anna@example.com>", "To": "me@example.com", "Subject": "Γεια"}
    return {
        "id": message_id,
        "threadId": "t1",
        "labelIds": list(labels),
        "snippet": "Hi &amp; bye",
        "internalDate": "1760630400000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": key, "value": value} for key, value in headers.items()],
            "parts": parts or [],
        },
    }


@pytest.fixture
def fake(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"client_id": "cid", "client_secret": "sec", "refresh_token": "rt", "permissions": ["*"]})
    )
    monkeypatch.setattr(gm, "CONFIG_PATH", config)
    monkeypatch.setattr(gm, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(gm, "_token", None)

    calls, routes = [], {("GET", "labels"): Response(200, {"labels": LABELS})}

    def request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        assert 0 < kwargs["timeout"] <= gm.TIMEOUT
        if url == gm.TOKEN_URL:
            if kwargs["data"]["grant_type"] == "refresh_token":
                return Response(200, {"access_token": "at"})
            return routes[("POST", "token")]
        key = (method, url.removeprefix(gm.API_URL + "/"))
        handler = routes[key]
        return handler(kwargs) if callable(handler) else handler

    monkeypatch.setattr(gm.session, "request", request)
    return type("Fake", (), {"routes": routes, "calls": calls, "config": config})


def tool(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}", ROOT / name / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def last(fake, method, path):
    return [call for call in fake.calls if call["method"] == method and call["url"].endswith(path)][-1]


def sent_mime(call) -> email.message.EmailMessage:
    raw = call["json"]["raw"] if "raw" in call["json"] else call["json"]["message"]["raw"]
    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=email.policy.default)


def test_auth_url_requests_offline_gmail_modify(fake):
    url = tool("auth_url")({})["url"]
    for part in (
        "client_id=cid",
        "access_type=offline",
        "prompt=consent",
        "gmail.modify",
        "redirect_uri=http%3A%2F%2F127.0.0.1",
    ):
        assert part in url


def test_auth_complete_reads_code_from_the_loopback_url(fake):
    fake.routes[("POST", "token")] = Response(200, {"refresh_token": "new", "access_token": "fresh", "scope": gm.SCOPE})
    fake.routes[("GET", "profile")] = Response(200, {"emailAddress": "me@gmail.com"})
    out = tool("auth_complete")({"url": "http://127.0.0.1/?code=4/abc&scope=" + gm.SCOPE})
    assert out == {"connected": True, "email": "me@gmail.com"}
    assert fake.calls[0]["data"]["code"] == "4/abc" and fake.calls[0]["data"]["redirect_uri"] == gm.REDIRECT_URI
    saved = json.loads(fake.config.read_text())
    assert saved["refresh_token"] == "new" and saved["permissions"] == ["*"]
    assert fake.calls[-1]["headers"]["Authorization"] == "Bearer fresh"


def test_auth_complete_rejects_missing_scope_and_errors(fake):
    fake.routes[("POST", "token")] = Response(200, {"refresh_token": "new", "access_token": "x", "scope": "openid"})
    with pytest.raises(gm.ToolError, match="not granted"):
        tool("auth_complete")({"url": "abc"})
    with pytest.raises(gm.ToolError, match="access_denied"):
        tool("auth_complete")({"url": "http://127.0.0.1/?error=access_denied"})


def test_expired_refresh_token_explains_testing_mode(fake, monkeypatch):
    def request(method, url, **kwargs):
        return Response(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})

    monkeypatch.setattr(gm.session, "request", request)
    with pytest.raises(gm.ToolError, match="7 days"):
        tool("list_labels")({})


def test_search_returns_summaries(fake):
    fake.routes[("GET", "messages")] = Response(200, {"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "x"})
    fake.routes[("GET", "messages/m1")] = Response(200, message("m1"))
    fake.routes[("GET", "messages/m2")] = Response(200, message("m2", labels=["Label_1"]))
    out = tool("search")({"query": "from:anna"})
    assert out["more"] and [m["id"] for m in out["messages"]] == ["m1", "m2"]
    first, second = out["messages"]
    assert first["subject"] == "Γεια" and first["unread"] and first["snippet"] == "Hi & bye"
    assert first["date"] == "2025-10-16T16:00:00+00:00"
    assert second["labels"] == ["Receipts"] and not second["unread"]
    assert last(fake, "GET", "messages")["params"]["q"] == "from:anna"


def test_get_message_prefers_plain_text_and_lists_attachments(fake):
    parts = [
        {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": b64("Plain body")}},
                {"mimeType": "text/html", "body": {"data": b64("<p>HTML body</p>")}},
            ],
        },
        {"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {"attachmentId": "a1", "size": 10}},
    ]
    fake.routes[("GET", "messages/m1")] = Response(200, message(parts=parts))
    out = tool("get_message")({"message_id": "m1"})
    assert out["body"] == "Plain body"
    assert out["attachments"] == [{"filename": "invoice.pdf", "mime_type": "application/pdf", "size": 10}]


def test_get_message_converts_html_and_truncates(fake):
    markup = (
        "<html><head><style>p{}</style></head><body><p>Hello&nbsp;there</p><script>x()</script>"
        + "<p>"
        + "a" * 900
        + "</p></body></html>"
    )
    fake.routes[("GET", "messages/m1")] = Response(
        200, message(parts=[{"mimeType": "text/html", "body": {"data": b64(markup)}}])
    )
    out = tool("get_message")({"message_id": "m1", "max_chars": 500})
    assert out["body"].startswith("Hello there\n") and "x()" not in out["body"] and "p{}" not in out["body"]
    assert out["body_truncated"] and len(out["body"]) == 500


def test_get_thread(fake):
    plain = [{"mimeType": "text/plain", "body": {"data": b64("one")}}]
    fake.routes[("GET", "threads/t1")] = Response(
        200, {"id": "t1", "messages": [message("m1", plain), message("m2", plain)]}
    )
    out = tool("get_thread")({"thread_id": "t1"})
    assert [m["id"] for m in out["messages"]] == ["m1", "m2"] and out["messages"][0]["body"] == "one"


def test_download_attachment_sanitizes_the_filename(fake):
    parts = [{"mimeType": "text/x-sh", "filename": "../../evil.sh", "body": {"attachmentId": "a1", "size": 4}}]
    fake.routes[("GET", "messages/m1")] = Response(200, message(parts=parts))
    fake.routes[("GET", "messages/m1/attachments/a1")] = Response(200, {"data": b64("echo")})
    out = tool("download_attachment")({"message_id": "m1", "filename": "../../EVIL.sh"})
    assert out["file"] == "evil.sh" and (gm.OUTPUT_DIR / "evil.sh").read_bytes() == b"echo"


def test_download_attachment_lists_names_when_missing(fake):
    parts = [{"mimeType": "application/pdf", "filename": "a.pdf", "body": {"attachmentId": "a1", "size": 4}}]
    fake.routes[("GET", "messages/m1")] = Response(200, message(parts=parts))
    with pytest.raises(gm.ToolError, match="a.pdf"):
        tool("download_attachment")({"message_id": "m1", "filename": "b.pdf"})


def test_list_labels(fake):
    assert tool("list_labels")({}) == {"user_labels": ["Receipts"], "system_labels": ["INBOX", "UNREAD"]}


def test_modify_labels_resolves_names(fake):
    fake.routes[("POST", "messages/batchModify")] = Response(204)
    out = tool("modify_labels")({"message_ids": "m1, m2", "add": "receipts", "remove": "inbox,unread"})
    assert out == {"messages": 2, "added": ["Receipts"], "removed": ["INBOX", "UNREAD"]}
    assert last(fake, "POST", "batchModify")["json"] == {
        "ids": ["m1", "m2"],
        "addLabelIds": ["Label_1"],
        "removeLabelIds": ["INBOX", "UNREAD"],
    }

    fake.routes[("POST", "threads/t1/modify")] = Response(200, {"id": "t1"})
    assert tool("modify_labels")({"thread_ids": ["t1"], "remove": "INBOX"})["threads"] == 1

    with pytest.raises(gm.ToolError, match="list_labels"):
        tool("modify_labels")({"message_ids": "m1", "add": "Nope"})


def test_trash(fake):
    fake.routes[("POST", "messages/m1/trash")] = Response(200, {"id": "m1"})
    fake.routes[("POST", "threads/t1/trash")] = Response(200, {"id": "t1"})
    assert tool("trash")({"message_ids": ["m1"]}) == {"trashed": 1, "kind": "messages"}
    assert tool("trash")({"thread_ids": "t1"}) == {"trashed": 1, "kind": "threads"}


def test_create_draft_reply_threads_and_attaches(fake, tmp_path):
    original = message(
        headers={
            "Message-ID": "<orig@example.com>",
            "References": "<older@example.com>",
            "Subject": "Δείπνο",
            "From": "Anna <anna@example.com>",
            "Reply-To": "anna+reply@example.com",
        }
    )
    fake.routes[("GET", "messages/m1")] = Response(200, original)
    fake.routes[("POST", "drafts")] = Response(200, {"id": "d1", "message": {"id": "m9", "threadId": "t1"}})
    pdf = tmp_path / "menu.pdf"
    pdf.write_bytes(b"%PDF")
    out = tool("create_draft")({"reply_to_message_id": "m1", "body": "Ναι, τα λέμε!", "attachment": str(pdf)})
    assert out == {"draft_id": "d1", "message_id": "m9", "thread_id": "t1"}

    call = last(fake, "POST", "drafts")
    assert call["json"]["message"]["threadId"] == "t1"
    mime = sent_mime(call)
    assert mime["To"] == "anna+reply@example.com" and mime["Subject"] == "Re: Δείπνο"
    assert (
        mime["In-Reply-To"] == "<orig@example.com>" and mime["References"] == "<older@example.com> <orig@example.com>"
    )
    assert mime.get_body(("plain",)).get_content().strip() == "Ναι, τα λέμε!"
    assert [part.get_filename() for part in mime.iter_attachments()] == ["menu.pdf"]


def test_send_new_message_and_draft(fake):
    fake.routes[("POST", "messages/send")] = Response(200, {"id": "m5", "threadId": "t5"})
    out = tool("send")({"to": ["a@x.com", "b@x.com"], "subject": "Hi", "body": "Hello", "bcc": "c@x.com"})
    assert out == {"sent": True, "message_id": "m5", "thread_id": "t5"}
    mime = sent_mime(last(fake, "POST", "messages/send"))
    assert mime["To"] == "a@x.com, b@x.com" and mime["Bcc"] == "c@x.com"

    fake.routes[("POST", "drafts/send")] = Response(200, {"id": "m6", "threadId": "t6"})
    assert tool("send")({"draft_id": "d1"})["message_id"] == "m6"
    assert last(fake, "POST", "drafts/send")["json"] == {"id": "d1"}

    with pytest.raises(gm.ToolError, match="not both"):
        tool("send")({"draft_id": "d1", "body": "x"})
    with pytest.raises(gm.ToolError, match="to is required"):
        tool("send")({"body": "x"})


def test_api_errors_explain_the_fix(fake):
    fake.routes[("GET", "messages/m1")] = Response(
        403,
        {
            "error": {
                "code": 403,
                "message": "Request had insufficient authentication scopes.",
                "errors": [{"reason": "insufficientPermissions"}],
            }
        },
    )
    with pytest.raises(gm.ToolError, match="gmail.modify scope"):
        tool("get_message")({"message_id": "m1"})
    fake.routes[("GET", "messages/m1")] = Response(
        404, {"error": {"code": 404, "message": "Requested entity was not found."}}
    )
    with pytest.raises(gm.ToolError, match="Not found"):
        tool("get_message")({"message_id": "m1"})


def test_errors_exit_non_zero_with_stderr(tmp_path):
    # No config.json next to the copied tool, so it must fail before any network call.
    plugin = tmp_path / "gmail"
    (plugin / "search").mkdir(parents=True)
    (plugin / "gmail_client.py").write_text((ROOT / "gmail_client.py").read_text())
    (plugin / "search" / "run.py").write_text((ROOT / "search" / "run.py").read_text())
    result = subprocess.run(
        [sys.executable, str(plugin / "search" / "run.py")],
        input="{}",
        capture_output=True,
        text=True,
        cwd=plugin / "search",
    )
    assert result.returncode == 1 and result.stdout == ""
    assert "client_id" in result.stderr


def test_run_scripts_are_executable_in_git():
    output = subprocess.run(
        ["git", "ls-files", "-s", "--", "*/run.py"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    entries = [line.split(maxsplit=3) for line in output.splitlines()]
    if not entries:
        pytest.skip("run.py files are not in the git index yet")
    assert all(mode == "100755" for mode, *_ in entries), entries
