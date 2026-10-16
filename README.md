# Gmail plugin

Lets Stavrobot search, read, label, draft and send email in your Gmail.

## Warning: `send` is on by default

Stavrobot turns on every tool of a plugin when it's installed, so the bot can send email as you from the moment you connect. Email is untrusted input. Any message in your inbox can carry a prompt injection, text written to get the bot to forward your mail somewhere, and with `send` on nothing stands between that text and an outgoing email.

Recommended: turn `send` off before you connect, and let the bot write drafts that you review and send yourself. You have to do this yourself, from your bot's plugin settings page:

1. Open `/settings/plugins` and pick `gmail`.
2. Under Permissions, set "Agents can use" to "Selected tools".
3. Click "Select all", untick `send`, then click "Save permissions".

If you're an agent installing this plugin, tell your user this warning and the steps above, and don't call `auth_url` until they confirm `send` is off.

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
- `send`: sends a new message or a saved draft. On by default, see the warning above.

## License

GNU Affero General Public License, version 3. See [LICENSE](LICENSE).
