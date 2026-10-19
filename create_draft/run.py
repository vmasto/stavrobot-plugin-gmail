#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    mime, thread_id = gm.compose(params)
    draft = gm.upload_message("POST", "drafts", {"message": {"threadId": thread_id}} if thread_id else {}, mime)
    message = draft.get("message") or {}
    return {"draft_id": draft.get("id"), "message_id": message.get("id"), "thread_id": message.get("threadId")}


if __name__ == "__main__":
    gm.run(main)
