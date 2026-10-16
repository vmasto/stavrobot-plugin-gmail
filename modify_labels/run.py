#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    all_labels = gm.labels()
    add = gm.resolve_labels(params.get("add"), all_labels)
    remove = gm.resolve_labels(params.get("remove"), all_labels)
    if not add and not remove:
        raise gm.ToolError("Give add and/or remove.")
    body = {"addLabelIds": add, "removeLabelIds": remove}

    if params.get("thread_ids"):
        ids = gm.id_list(params["thread_ids"], "thread_ids")
        gm.parallel(lambda thread_id: gm.api("POST", f"threads/{gm.quote_id(thread_id)}/modify", body=body), ids)
        kind = "threads"
    else:
        ids = gm.id_list(params.get("message_ids"), "message_ids")
        gm.api("POST", "messages/batchModify", body={"ids": ids, **body})
        kind = "messages"
    return {
        kind: len(ids),
        "added": gm.label_names(add, all_labels),
        "removed": gm.label_names(remove, all_labels),
    }


if __name__ == "__main__":
    gm.run(main)
