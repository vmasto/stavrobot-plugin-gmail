"""Shared Gmail API client for the plugin's tools."""

import base64
import html
import json
import mimetypes
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import requests

PLUGIN_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PLUGIN_ROOT / "config.json"
OUTPUT_DIR = Path("/tmp/gmail")

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = "https://www.googleapis.com/auth/gmail.modify"
# Desktop OAuth clients accept a loopback redirect without registering it. Nothing
# listens there: the user copies the URL from the address bar instead.
REDIRECT_URI = "http://127.0.0.1"

# The plugin-runner kills a tool after 30 seconds, so give up a bit earlier
# with a readable error instead.
DEADLINE_SECONDS = 25
TIMEOUT = 15
# The plugin-runner refuses to move more than 25 MB per run.
MAX_TRANSFER_BYTES = 25 * 1024 * 1024

SYSTEM_LABELS = {"INBOX", "UNREAD", "STARRED", "IMPORTANT", "SPAM", "TRASH", "SENT", "DRAFT"}

_started = time.monotonic()
session = requests.Session()


class ToolError(Exception):
    pass


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except FileNotFoundError:
        return {}
    except ValueError:
        raise ToolError("config.json is not valid JSON.")


def save_config(updates: dict) -> None:
    # Read again right before writing so keys set elsewhere, like permissions, survive.
    config = load_config()
    config.update(updates)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def client_credentials(config: dict) -> tuple[str, str]:
    client_id = str(config.get("client_id") or "").strip()
    client_secret = str(config.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ToolError("Set client_id and client_secret from your Google Cloud OAuth client first.")
    return client_id, client_secret


def send(method: str, url: str, **kwargs) -> requests.Response:
    remaining = DEADLINE_SECONDS - (time.monotonic() - _started)
    if remaining < 1:
        raise ToolError("Ran out of time talking to Gmail, try a smaller request.")
    try:
        return session.request(method, url, timeout=min(TIMEOUT, remaining), **kwargs)
    except requests.Timeout:
        raise ToolError("Gmail did not respond in time.")
    except requests.RequestException as error:
        raise ToolError(f"Network error talking to Gmail ({type(error).__name__}).")


def token_error(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    return body.get("error_description") or body.get("error") or f"HTTP {response.status_code}"


_token = None


def access_token() -> str:
    global _token
    if _token:
        return _token
    config = load_config()
    client_id, client_secret = client_credentials(config)
    refresh_token = str(config.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ToolError("Gmail is not connected yet. Run auth_url, then auth_complete.")
    response = send(
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    if not response.ok:
        reason = token_error(response)
        hint = ""
        if "invalid_grant" in reason or "expired" in reason.lower():
            hint = (
                " Tokens from an OAuth app in Testing status expire after 7 days, publish the app to production first."
            )
        raise ToolError(f"Google refused the refresh token ({reason}).{hint} Run auth_url and auth_complete again.")
    _token = response.json()["access_token"]
    return _token


def api_error(response: requests.Response) -> ToolError:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    message = error.get("message") or response.text.strip()[:300]
    reasons = {item.get("reason") for item in error.get("errors") or [] if isinstance(item, dict)}

    if response.status_code == 401:
        return ToolError("Google rejected the access token. Run auth_url and auth_complete again.")
    if response.status_code == 403 and ("insufficientPermissions" in reasons or "scope" in message.lower()):
        return ToolError(f"The token lacks the {SCOPE} scope. Run auth_url and auth_complete again.")
    if response.status_code == 429 or reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
        return ToolError("Gmail is rate limiting, retry in a minute.")
    if response.status_code == 404:
        return ToolError("Not found. Check the id, it may have been deleted.")
    return ToolError(f"Gmail API error {response.status_code}: {message}")


def api(method: str, path: str, params=None, body=None) -> dict:
    response = send(
        method,
        f"{API_URL}/{path}",
        headers={"Authorization": f"Bearer {access_token()}"},
        params=params,
        json=body,
    )
    if not response.ok:
        raise api_error(response)
    return response.json() if response.content else {}


def parallel(function, items: list) -> list:
    access_token()  # fetch once before fanning out
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        return list(pool.map(function, items))


def quote_id(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("An id is required.")
    return quote(value.strip(), safe="")


# --------------------------------------------------------------------------- labels


def labels() -> list:
    return api("GET", "labels").get("labels", [])


def resolve_labels(names, all_labels: list) -> list:
    """Map label names (case-insensitive) or ids to ids."""
    if names is None:
        return []
    if isinstance(names, str):
        names = [part for part in names.split(",")]
    if not isinstance(names, list):
        raise ToolError("Labels must be a list or a comma-separated string.")
    by_name = {label["name"].lower(): label["id"] for label in all_labels}
    ids = {label["id"] for label in all_labels}
    resolved = []
    for name in names:
        name = str(name).strip()
        if not name:
            continue
        if name in ids:
            resolved.append(name)
        elif name.upper() in SYSTEM_LABELS:
            resolved.append(name.upper())
        elif name.lower() in by_name:
            resolved.append(by_name[name.lower()])
        else:
            raise ToolError(f"No label named {name!r}. Use list_labels, or create_label first.")
    return resolved


def label_names(label_ids: list, all_labels: list) -> list:
    by_id = {label["id"]: label["name"] for label in all_labels}
    return [by_id.get(label_id, label_id) for label_id in label_ids or []]


# --------------------------------------------------------------------------- messages


def header(payload: dict, name: str) -> str:
    for item in payload.get("headers") or []:
        if item.get("name", "").lower() == name.lower():
            return item.get("value", "")
    return ""


def received_at(message: dict) -> str | None:
    millis = message.get("internalDate")
    if not millis:
        return None
    return datetime.fromtimestamp(int(millis) / 1000, timezone.utc).isoformat(timespec="seconds")


def summary(message: dict, all_labels: list) -> dict:
    payload = message.get("payload") or {}
    label_ids = message.get("labelIds") or []
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "from": header(payload, "From"),
        "to": header(payload, "To"),
        "subject": header(payload, "Subject"),
        "date": received_at(message),
        "snippet": html.unescape(message.get("snippet", "")),
        "unread": "UNREAD" in label_ids,
        "labels": label_names(label_ids, all_labels),
    }


def decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class _TextExtractor(HTMLParser):
    BREAKS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    text = "".join(parser.parts)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def walk(part: dict):
    yield part
    for child in part.get("parts") or []:
        yield from walk(child)


def body_text(payload: dict) -> str:
    plain, markup = None, None
    for part in walk(payload):
        if part.get("filename"):
            continue
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        mime = part.get("mimeType", "")
        text = decode(data).decode("utf-8", errors="replace")
        if mime == "text/plain" and plain is None:
            plain = text
        elif mime == "text/html" and markup is None:
            markup = text
    if plain is not None and plain.strip():
        return plain.strip()
    if markup is not None:
        return html_to_text(markup)
    return ""


def attachments(payload: dict) -> list:
    found = []
    for part in walk(payload):
        body = part.get("body") or {}
        if part.get("filename") and body.get("attachmentId"):
            found.append(
                {
                    "filename": part["filename"],
                    "mime_type": part.get("mimeType"),
                    "size": body.get("size"),
                    "attachment_id": body["attachmentId"],
                }
            )
    return found


def full_message(message: dict, all_labels: list, max_chars: int) -> dict:
    payload = message.get("payload") or {}
    out = summary(message, all_labels)
    del out["snippet"]
    cc = header(payload, "Cc")
    if cc:
        out["cc"] = cc
    text = body_text(payload)
    out["body"] = text[:max_chars]
    if len(text) > max_chars:
        out["body_truncated"] = True
        out["body_length"] = len(text)
    out["attachments"] = [
        {key: value for key, value in item.items() if key != "attachment_id"} for item in attachments(payload)
    ]
    return out


# --------------------------------------------------------------------------- outgoing


def addresses(value, name: str) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item).strip() for item in value if str(item).strip())
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{name} must be an address or a list of addresses.")
    return value.strip()


def compose(params: dict) -> dict:
    """Build the Gmail API message resource shared by create_draft and send."""
    body = params.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ToolError("body is required.")
    message = EmailMessage()
    subject, to, thread_id = params.get("subject"), params.get("to"), None

    reply_id = params.get("reply_to_message_id")
    if reply_id:
        original = api(
            "GET",
            f"messages/{quote_id(reply_id)}",
            params={
                "format": "metadata",
                "metadataHeaders": ["Message-ID", "References", "Subject", "From", "Reply-To"],
            },
        )
        payload = original.get("payload") or {}
        message_id = header(payload, "Message-ID")
        if message_id:
            message["In-Reply-To"] = message_id
            message["References"] = f"{header(payload, 'References')} {message_id}".strip()
        thread_id = original.get("threadId")
        if not subject:
            original_subject = header(payload, "Subject")
            subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"
        if not to:
            to = header(payload, "Reply-To") or header(payload, "From")

    if not to:
        raise ToolError("to is required unless replying.")
    message["To"] = addresses(to, "to")
    for key in ("cc", "bcc"):
        if params.get(key):
            message[key.capitalize()] = addresses(params[key], key)
    message["Subject"] = subject or ""
    message.set_content(body)

    attachment = params.get("attachment")
    if attachment:
        path = Path(attachment)
        if not path.is_file():
            raise ToolError("attachment was not found.")
        data = path.read_bytes()
        if len(data) > MAX_TRANSFER_BYTES:
            raise ToolError("attachment is over the 25 MB limit.")
        maintype, subtype = (mimetypes.guess_type(path.name)[0] or "application/octet-stream").split("/", 1)
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)

    resource = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
    if thread_id:
        resource["threadId"] = thread_id
    return resource


# --------------------------------------------------------------------------- params


def int_param(params: dict, name: str, default: int, low: int, high: int) -> int:
    value = params.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{name} must be a whole number.")
    return max(low, min(high, value))


def id_list(value, name: str) -> list:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolError(f"{name} must be a list of ids or a comma-separated string.")
    ids = [item.strip() for item in value if item.strip()]
    if not ids:
        raise ToolError(f"{name} is required.")
    if len(ids) > 100:
        raise ToolError(f"At most 100 {name} at once.")
    return ids


def run(main) -> None:
    try:
        raw = sys.stdin.read()
        params = json.loads(raw) if raw.strip() else {}
        if not isinstance(params, dict):
            raise ToolError("Input must be a JSON object.")
        result = main(params)
    except ToolError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print("Input is not valid JSON.", file=sys.stderr)
        sys.exit(1)
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
