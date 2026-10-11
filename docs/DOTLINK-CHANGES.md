# Local integration changes

This branch retains the upstream gateway and commands. No upstream release or publication is implied.

- `MUSE_COOKIES_FILE` selects an explicit cookie file. A `.dpapi` file can contain a UTF-8 JSON cookie list protected by Windows CryptProtectData for the current user; plaintext is not written to disk.
- `watch --thread SESSION_ID` subscribes to a side chat. Main chat remains the default.
- `--after-stream-seq` and `--after-chat-event-seq` pass separate replay cursors. Both default to zero, so initial output may contain history.
- `watch --raw` writes complete events as NDJSON, one flushed line per arriving record. Output can contain private chat content; do not publish raw captures.
- Subscriptions advertise the web client's delta/chat-cancel/reaction capabilities. Receiving an event does not by itself prove a task is complete.
- `iter_subscription_raw/json` yield incrementally. List-returning helpers remain, but subscriptions own and close their connection on completion; do not multiplex another reader on that gateway.

The streaming changes were verified against the Muse web client, read-only subscriptions, and one newly created side chat with a fresh message. Live message_start/text_append/message_done events matched independently read assistant history. Replay recovery and long-running reliability remain unverified. This branch does not expose a direct Muse Executor command.

The fork also adds `muse-login` for staged native OTP authentication with explicitly selected Linux storage, and `muse-read` for a small GET-only surface. Authentication checks do not automatically open the Gateway. HTTP error text and diagnostics suppress credential values. See [native login](NATIVE-LOGIN.md) and [protocol evidence](CONTRACT-EVIDENCE.md) for installation, storage requirements, recovery and unsupported media-library queries.
