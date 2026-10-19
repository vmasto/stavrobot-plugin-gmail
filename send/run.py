#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    draft_id = params.get("draft_id")
    if draft_id:
        if any(params.get(key) for key in ("to", "subject", "body", "cc", "bcc", *gm.ATTACHMENT_PARAMS)):
            raise gm.ToolError("Give either draft_id or a new message, not both.")
        sent = gm.api("POST", "drafts/send", body={"id": str(draft_id).strip()})
    else:
        mime, thread_id = gm.compose(params)
        sent = gm.upload_message("POST", "messages/send", {"threadId": thread_id} if thread_id else {}, mime)
    return {"sent": True, "message_id": sent.get("id"), "thread_id": sent.get("threadId")}


if __name__ == "__main__":
    gm.run(main)
