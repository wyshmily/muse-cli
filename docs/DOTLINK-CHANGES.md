# Local integration changes

This branch retains the upstream gateway and commands. No upstream release or publication is implied.

- `MUSE_COOKIES_FILE` selects an explicit cookie file. A `.dpapi` file can contain a UTF-8 JSON cookie list protected by Windows CryptProtectData for the current user; plaintext is not written to disk.
- `watch --thread SESSION_ID` subscribes to a side chat. Main chat remains the default.
- `--after-stream-seq` and `--after-chat-event-seq` pass separate replay cursors. Both default to zero, so initial output may contain history.
- `watch --raw` writes complete events as NDJSON, one flushed line per arriving record. Output can contain private chat content; do not publish raw captures.
- Subscriptions advertise the web client's delta/chat-cancel/reaction capabilities. Receiving an event does not by itself prove a task is complete.
- `iter_subscription_raw/json` yield incrementally. List-returning helpers remain, but subscriptions own and close their connection on completion; do not multiplex another reader on that gateway.

Verified against the Muse web client on 2026-10-08 and a read-only side-chat subscription. New-message latency, replay recovery and Executor commands have not been verified. Native OTP login currently lives in the host's login helper; it is not yet a portable CLI login command.
