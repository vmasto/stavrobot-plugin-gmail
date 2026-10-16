#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    if params.get("thread_ids"):
        ids, kind = gm.id_list(params["thread_ids"], "thread_ids"), "threads"
    else:
        ids, kind = gm.id_list(params.get("message_ids"), "message_ids"), "messages"
    gm.parallel(lambda item_id: gm.api("POST", f"{kind}/{gm.quote_id(item_id)}/trash"), ids)
    return {"trashed": len(ids), "kind": kind}


if __name__ == "__main__":
    gm.run(main)
