#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    name = params.get("name")
    if not isinstance(name, str) or not name.strip():
        raise gm.ToolError("name is required.")
    label = gm.api(
        "POST",
        "labels",
        body={"name": name.strip(), "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    )
    return {"id": label["id"], "name": label["name"]}


if __name__ == "__main__":
    gm.run(main)
