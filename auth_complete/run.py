#!/usr/bin/env -S uv run
# /// script
# dependencies = ["requests"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client as gm  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402


def main(params: dict) -> dict:
    value = params.get("url")
    if not isinstance(value, str) or not value.strip():
        raise gm.ToolError("url is required.")
    value = value.strip()
    if value.startswith("http"):
        query = parse_qs(urlparse(value).query)
        if "error" in query:
            raise gm.ToolError(f"Google returned an error: {query['error'][0]}. Run auth_url again.")
        if "code" not in query:
            raise gm.ToolError("That address has no code in it. Copy the full address after allowing access.")
        code = query["code"][0]
    else:
        code = value

    client_id, client_secret = gm.client_credentials(gm.load_config())
    response = gm.send(
        "POST",
        gm.TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": gm.REDIRECT_URI,
        },
    )
    if not response.ok:
        raise gm.ToolError(
            f"Google refused the code ({gm.token_error(response)}). Codes work once and expire fast, run auth_url again."
        )
    body = response.json()
    if gm.SCOPE not in body.get("scope", "").split():
        raise gm.ToolError("Access to Gmail was not granted. Run auth_url again and tick the Gmail permission.")
    if not body.get("refresh_token"):
        raise gm.ToolError("Google returned no refresh token, run auth_url again.")
    gm.save_config({"refresh_token": body["refresh_token"]})
    gm._token = body["access_token"]
    return {"connected": True, "email": gm.api("GET", "profile").get("emailAddress")}


if __name__ == "__main__":
    gm.run(main)
