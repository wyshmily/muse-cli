# Native login protocol evidence

The protocol review was performed on 2026-10-09. These are implementation
observations for a private web API, not a guarantee of future compatibility.

An authorized operator observed native/restart HTTP 201, send-otp HTTP 201 with
`flow=login` and `registration_state=otp_sent`, and confirm-otp HTTP 200 without a
success-state enum. The implementation does not invent a success enum. It checks
authentication independently through auth/check and a valid session cookie.

Public login JavaScript at `https://muse.ai/_next/static/chunks/2ifheeo1e8vq3.js`
had SHA256 `b37228fdc114ac0b88efdb28d06fc9a4605d5cf93b11ea513145e87b8e11ad18`.
The reviewed handler included account selection, completion, second-factor and
upsell branches. It did not establish save-account semantics, so this fork
omits that endpoint. No downloaded bundle is distributed with the fork.

The repository's route table establishes GET identity, sessions.list,
sessions.get, chat.history and spaces.list. Existing history calls supply
session_id and limit. POST fs.library is listed but its payload schema is not
known, so media querying is not implemented or guessed.

SecretStorage 3.5.0 was reviewed for implicit collection creation and unlock.
The implementation uses existing Collection/Item objects and pins a running
D-Bus service owner. It does not call Unlock, Prompt or CreateCollection.
Synthetic transport tests cover absent/locked collections/items, lock races,
optional prompts, storage failures and redaction.

Tests of authentication state, restart recovery and encrypted/plaintext files
use fixtures. Their success does not verify any user's actual runtime storage,
account login, Gateway connection or media library.
