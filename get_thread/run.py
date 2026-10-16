#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    thread = gm.api("GET", f"threads/{gm.quote_id(params.get('thread_id'))}", params={"format": "full"})
    all_labels = gm.labels()
    max_chars = gm.int_param(params, "max_chars", 3000, 500, 20000)
    return {
        "thread_id": thread.get("id"),
        "messages": [gm.full_message(message, all_labels, max_chars) for message in thread.get("messages", [])],
    }


if __name__ == "__main__":
    gm.run(main)
