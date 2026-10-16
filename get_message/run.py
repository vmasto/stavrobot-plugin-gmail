#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    message = gm.api("GET", f"messages/{gm.quote_id(params.get('message_id'))}", params={"format": "full"})
    return gm.full_message(message, gm.labels(), gm.int_param(params, "max_chars", 8000, 500, 50000))


if __name__ == "__main__":
    gm.run(main)
