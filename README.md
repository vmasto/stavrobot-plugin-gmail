# Gmail plugin

Lets Stavrobot search, read, label, draft and send email in your Gmail.

## Before installing

You need your own Google Cloud OAuth client, it's free:

1. In https://console.cloud.google.com create a project and enable the Gmail API.
2. Under Google Auth Platform, set up the consent screen as External. Then on Audience click Publish app. Apps left in Testing get refresh tokens that expire after 7 days, so you'd have to reconnect every week.
3. Under Clients, create an OAuth client of type Desktop app.

The app stays unverified, which is fine for personal use. Google shows a warning when you connect and caps unverified apps at 100 users.

## Installation

Tell Stavrobot to install `https://github.com/vmasto/stavrobot-plugin-gmail`.

## Configuration

- `client_id` and `client_secret`: from the Desktop app client.
- `refresh_token`: leave it empty. Ask Stavrobot to connect Gmail and it sends you a link. Google warns the app is unverified, click Advanced and continue. After you allow access the browser shows an error page on `127.0.0.1`, that's expected. Copy the full address and send it back, the plugin saves the token itself.

The plugin asks for the `gmail.modify` scope only. It can't permanently delete mail, trashed mail stays in the trash for 30 days.

## Tools

- `auth_url`, `auth_complete`: connect your account.
- `search`: Gmail search syntax, like `from:anna is:unread newer_than:7d`.
- `get_message`, `get_thread`: read a message or a whole conversation as plain text.
- `download_attachment`: sends an attachment to the bot as a file, up to 25 MB.
- `list_labels`, `create_label`.
- `modify_labels`: archive, mark read or unread, star, or apply your own labels.
- `trash`.
- `create_draft`: a new message or a reply, with an optional attachment.
- `send`: sends a new message or a saved draft.

Email is untrusted input. A message can contain text written to trick the bot into forwarding your mail somewhere. If you'd rather review everything before it goes out, turn off `send` on the plugins settings page and use drafts.

## License

GNU Affero General Public License, version 3. See [LICENSE](LICENSE).
