# Native login and read-only access

This fork adds separate `muse-login` and `muse-read` commands. Authentication
uses Muse's private web protocol, not a supported public account API. No
credentials or personal runtime configuration are distributed with the code.

## Install

Python 3.10+ is required. Install this fork from its pinned source checkout:

```sh
python -m pip install .
# Optional Linux Secret Service backend:
python -m pip install '.[linux-login]'
muse-login --help
muse-read --help
```

The upstream `muse-cli update` command installs the upstream package and would
overwrite fork changes. Update this checkout explicitly instead.

## Memory-only login

```sh
muse-login session
```

Use a private interactive terminal. Account and OTP are entered through hidden
TTY prompts, never through command arguments or environment variables. EOF or
Ctrl+C closes the in-memory session; it does not survive process exit. The
terminal accepts `check`, `identity`, `sessions`, `session ID`, `history ID`,
`spaces`, and `quit` after login.

`auth/check` establishes authentication. It does not automatically connect to
the Gateway. Explicit read commands verify that additional path separately.
An HTTP 200 from OTP confirmation alone does not prove authentication.

## Linux persistent storage

Choose a backend explicitly; there is no discovery or fallback to another
backend. The runtime owner prepares storage and decides its retention.

| Backend | Requirements and behavior |
| --- | --- |
| `secretservice` | An existing running, unlocked Secret Service with a configured collection and private `XDG_RUNTIME_DIR`. No service activation, collection creation, unlock or prompt is performed automatically. |
| `encrypted-file` | An absolute file path in an existing owner-only private directory. AES-256-GCM with scrypt; passphrase entered in a private terminal, never saved. Restart requires the passphrase again. |
| `plaintext-file` | Explicitly selected absolute path, existing directory 0700, file 0600. No keyring/passphrase, encryption or automatic backend fallback. File permissions do not protect against the same user or an administrator. |

File backends reject symlinks, hardlinks, insecure permissions and corrupted
state. Writes use private temporary files, atomic replacement and fsync. They
do not create directories, repair permissions or scan for credentials.

Example with a path chosen and prepared by the runtime owner:

```sh
P=/path/to/private/session.json
muse-login preflight --store plaintext-file --vault "$P"
muse-login start --store plaintext-file --vault "$P"
muse-login confirm --store plaintext-file --vault "$P"
muse-login check --store plaintext-file --vault "$P" --wait 120
muse-login status --store plaintext-file --vault "$P"
muse-read --store plaintext-file --vault "$P" identity
muse-read --store plaintext-file --vault "$P" sessions
muse-read --store plaintext-file --vault "$P" session --id SESSION_ID
muse-read --store plaintext-file --vault "$P" history --id SESSION_ID --limit 20
muse-read --store plaintext-file --vault "$P" spaces
```

For encrypted storage, select `--store encrypted-file` and a ciphertext path.
For Secret Service, select `--store secretservice --profile PROFILE` without
`--vault`. Its item service is `dotlink.muse-cli.linux.v1`; its nonsecret lock
is `$XDG_RUNTIME_DIR/dotlink-muse-PROFILE.lock`.

`preflight` only checks metadata; it does not access stored secrets. `start`
creates one recoverable OTP attempt; `confirm` submits its code once. After a
timeout, cancellation or process restart, use `status` and `check` on the same
store before any new attempt. They do not resend OTP. `--wait` is accepted only
for read-only authentication checks, up to 300 seconds, at five-second intervals.

`AUTHENTICATED` means auth/check succeeded and the selected state was saved;
it does not prove Gateway readiness. `status` reports the saved phase, not
current authentication validity. `forget` removes only the selected local
session and does not revoke the remote session.

## Read commands and limits

`muse-read` exposes identity, session listing/details/history and spaces through
GET routes. It does not expose arbitrary writes. Credential-named fields and
URL query strings are redacted; conversation content can still be private.
Failures distinguish authentication, forbidden, missing, rate-limit, timeout
and transport/API errors without printing raw error bodies.

`muse-read media` fails with `MEDIA_SCHEMA_UNVERIFIED` before credential access:
`fs.library` exists in the route table but its request/response schema is not
implemented. Space/session content is not a substitute for the media library.
Registration, password flow, account completion/selection and additional
checkpoints stop rather than bypassing the official client. The unverified
save-account endpoint is not called. See [protocol evidence](CONTRACT-EVIDENCE.md).

## Offline checks

```sh
python -m unittest discover -s tests -v
```

Tests inject synthetic HTTP, cookies and D-Bus transports. Linux-only file
permission/locking checks and optional SecretStorage tests may skip elsewhere.
They do not establish real login, runtime persistence, Gateway availability or
account media access. Packaging smoke checks should use an installed wheel and
only `--version` / `--help`, not real account operations.
