#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    message_id = gm.quote_id(params.get("message_id"))
    filename = params.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise gm.ToolError("filename is required.")
    message = gm.api("GET", f"messages/{message_id}", params={"format": "full"})
    found = gm.attachments(message.get("payload") or {})
    match = next((item for item in found if item["filename"] == filename), None) or next(
        (item for item in found if item["filename"].lower() == filename.strip().lower()), None
    )
    if match is None:
        names = ", ".join(item["filename"] for item in found) or "none"
        raise gm.ToolError(f"No attachment named {filename!r}. Attachments: {names}.")
    if (match["size"] or 0) > gm.MAX_TRANSFER_BYTES:
        raise gm.ToolError(f"{match['filename']} is over the 25 MB limit.")
    data = gm.api("GET", f"messages/{message_id}/attachments/{gm.quote_id(match['attachment_id'])}")["data"]
    # The filename comes from the sender, so keep only its last path component.
    safe_name = Path(match["filename"].replace("\\", "/")).name
    if safe_name in ("", ".", ".."):
        safe_name = "attachment"
    gm.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (gm.OUTPUT_DIR / safe_name).write_bytes(gm.decode(data))
    return {"file": safe_name, "mime_type": match["mime_type"], "size": match["size"]}


if __name__ == "__main__":
    gm.run(main)
