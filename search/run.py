#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402


def main(params: dict) -> dict:
    query = params.get("query") or "in:inbox"
    if not isinstance(query, str):
        raise gm.ToolError("query must be a string.")
    listing = gm.api(
        "GET",
        "messages",
        params={
            "q": query,
            "maxResults": gm.int_param(params, "max_results", 20, 1, 50),
            "includeSpamTrash": bool(params.get("include_spam_trash")),
        },
    )
    all_labels = gm.labels()

    def fetch(item):
        return gm.api(
            "GET",
            f"messages/{gm.quote_id(item['id'])}",
            params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject"]},
        )

    messages = gm.parallel(fetch, listing.get("messages", []))
    return {
        "query": query,
        "messages": [gm.summary(message, all_labels) for message in messages],
        "more": bool(listing.get("nextPageToken")),
    }


if __name__ == "__main__":
    gm.run(main)
