#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    found = gm.labels()
    user = sorted((label["name"] for label in found if label.get("type") == "user"), key=str.lower)
    system = sorted(label["id"] for label in found if label.get("type") == "system")
    return {"user_labels": user, "system_labels": system}


if __name__ == "__main__":
    gm.run(main)
