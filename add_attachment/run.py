#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402
import email  # noqa: E402
import email.policy  # noqa: E402


def main(params: dict) -> dict:
    draft_id = gm.quote_id(params.get("draft_id"))
    # Read the file before any network call, see compose.
    filename, data = gm.read_input(params.get("file"), "file")
    draft = gm.api("GET", f"drafts/{draft_id}", params={"format": "raw"})
    original = draft.get("message") or {}
    if not original.get("raw"):
        raise gm.ToolError("Gmail returned the draft without its content.")
    message = email.message_from_bytes(gm.decode(original["raw"]), policy=email.policy.default)

    existing = list(message.iter_attachments())
    gm.check_attachment_size(sum(len(part.get_payload(decode=True) or b"") for part in existing) + len(data))
    gm.attach(message, filename, data)

    metadata = {"id": draft.get("id"), "message": {}}
    # Without the thread id, the updated draft drops out of the conversation it replies to.
    if original.get("threadId"):
        metadata["message"]["threadId"] = original["threadId"]
    updated = gm.upload_message("PUT", f"drafts/{draft_id}", metadata, message.as_bytes())
    new_message = updated.get("message") or {}
    return {
        "draft_id": updated.get("id"),
        "message_id": new_message.get("id"),
        "thread_id": new_message.get("threadId"),
        "attachments": [part.get_filename() for part in existing] + [filename],
    }


if __name__ == "__main__":
    gm.run(main)
