---
name: muse-cli
description: Use the pinned wyshmily/muse-cli fork for Muse native OTP login, safe read discovery, and explicitly authorized personal-agent tasks.
---

# Muse CLI fork entry point

## 1. Verify the installed fork

Read `docs/LOCAL-RECOVERY.md` and `docs/NATIVE-LOGIN.md`. Use the pinned
`wyshmily/muse-cli` delivery commit and its source manifest. Do not assume a
bare machine or overwrite an existing installation/session. Upstream PyPI,
the upstream curl installer, and `muse-cli update` do not deliver this fork.
Run `muse-login --help`, `muse-read --help`, and offline `muse-read discover`.
Use `muse-read describe COMMAND` for verified parameters and side effects.

## 2. Native OTP first; respect existing sessions

`muse-login` implements Muse's native existing-account OTP flow. A browser
cookie export is not a prerequisite. Select only the owner's approved backend,
profile and vault. Do not scan for credentials or silently switch backends.

- `preflight`: storage metadata only, no secret access, OTP, network auth or
  local state writes. It does not prove login or a usable interactive channel.
- `status`: loads stored secrets and reports the saved local phase, not live
  validity; encrypted storage requires its hidden passphrase prompt.
- `check`: makes auth-only network requests and checkpoints local state/cookies.
  It never resends OTP or connects to the Gateway. `--wait 120` only polls
  `WAITING_SESSION`; it does not retry rejection, timeout or rate limiting.
- If a saved session/attempt exists, inspect `status`, then authorized `check`
  before proposing a new OTP. `authenticated` plus a successful auth-only check
  is login success even if the Gateway is unavailable. Never delete it merely
  because a Gateway read fails. `forget` is an explicitly authorized local
  deletion, not a remote revocation or automatic repair.
- For a new authorized attempt: `start` then `confirm`, using the same explicit
  backend/profile/vault. Both require private hidden-input TTY prompts. After
  uncertainty, use `status`/`check`, not repeated `start` or OTP submission.
- `session` is a private persistent terminal and stores nothing. Quit/EOF
  closes its memory session. It is not an unattended machine login interface.

## 3. Machine invocation and interaction boundary

Lack of PTY support in one MCP execution tool is a limitation of that channel,
not evidence that Muse lacks native OTP login. Use an already authorized
private interactive terminal on the account's approved runtime, or ask for the
needed interaction. Do not improvise a less-safe transport. Hidden input must
not be captured by a terminal recorder, tool-call transcript, or debug log.
Never put account details, OTPs, passwords, cookies or tokens in argv, environment
variables, shell pipelines/here-documents, logs, source files or chat. Do not
add a stdin/env/argv secret fallback to automate around the TTY guard.

Noninteractive calls may use only approved preconfigured storage that does not
need a secret prompt (for example an existing unlocked Secret Service). A
plaintext file requires explicit owner selection; never choose it as a fallback.
Code delivery/recovery does not authorize credential transfer or new storage.
See the native-login document for full examples and storage requirements.

Auth and Gateway are separate checks: auth/check failure, Gateway transport
failure, VM availability, rate limiting and permission errors are not all
expired cookies. Report the layer and sanitized code; do not export cookies,
re-login, resend tasks or change identities automatically.

The legacy `muse-cli` commands below use their separately configured legacy
session; native `muse-login` stores are consumed by `muse-read`, not automatically
exported into legacy cookies.txt. Do not bridge these stores by copying secrets.

## Everyday commands

```bash
muse-cli threads                                        # main chat + side chats (session_ids)
muse-cli history --limit 5                              # recent main-chat messages
muse-cli history --thread <session-id> --limit 5        # one side chat
muse-cli send "message" --wait 120                      # send + wait for the reply
muse-cli send "message" --thread <session-id> --wait 0  # fire and forget to a side chat
muse-cli watch --timeout 60                             # tail live agent events
muse-cli feed --limit 5
muse-cli goals
muse-cli ideas
muse-cli unread
muse-cli seen <thread-id>
```

Management (visible side effects, confirm with the user first when destructive):

```bash
muse-cli feed-react <unit-id> love
muse-cli idea-exec <idea-id>          # the agent acts on the idea (real work)
muse-cli session-start --title "x"    # new side chat
muse-cli session-rename <id> "title"  # also: pin, unpin, archive, unarchive, delete
muse-cli wake
```

## Raw routes are not an authorization shortcut

`muse-cli raw <method> --body '{...}' [--param k=v]` calls any of the 258
gateway methods in `routes.json`. This catalog is not an execution allowlist.
Use only a verified route within the explicit task authorization; never guess a
write, bypass rejection, or retry an uncertain operation before checking state.

## Gotchas

- `send` returns `{"sent": true, "reply": {...}}`, polling history until the
  reply lands (up to `--wait`). If `reply` is missing, the agent was slower
  than the wait: the message still landed, confirm with `history`. The reply
  is matched as a genuine answer, not background chatter.
- `send --wait 0` is fire-and-forget (no polling).
- `history` without `--thread` reads the main chat only.
- The gateway API is unversioned. Whole classes of calls failing at once means
  the protocol drifted: see `docs/PROTOCOL.md` for the re-derivation notes,
  don't guess at crypto or framing.
- Respect rate limits. Writes (send, react, execute, session ops) act as the
  user in their agent: announce them before running, never loop them.
- Do not use `muse-cli update` on this fork: it installs upstream PyPI and can
  remove native login/read features. Update the pinned fork checkout explicitly.
