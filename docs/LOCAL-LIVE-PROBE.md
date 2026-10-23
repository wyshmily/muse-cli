# One-time local read probe

`tools/probe_local.py` is a bounded diagnostic for a specifically authorized
cloud runtime. It does **not** transfer credentials, recover a persistent login,
request an OTP, or establish permission. Obtain current authorization for the
source login, destination runtime, temporary handling, and actual gateway
`hatch.metaaivm.com` before invoking it. Gateway domain ownership is not proved by
this tool. Authentication material sent there can expose account access.
Historical approval or success is not standing authorization for a new runtime.

The caller supplies a separately approved encrypted envelope in an owned,
private (`0700`) `/tmp/muse-live-*` directory. Input files are owned regular files
with mode `0600`, not symlinks or hard links:

- `ephemeral.key`: 32 raw bytes of the one-time X25519 receiver private key.
- `sealed.json`: JSON containing `ephemeral_public` (sender's raw public key,
  hex), `nonce` (12-byte nonce, hex), and `ciphertext` (base64 AES-GCM including
  its authentication tag).
- Optional `public.hex`: the corresponding non-secret receiver public key.

Key derivation is X25519 plus HKDF-SHA256, 32-byte output, no salt. Both HKDF info
and AES-GCM AAD equal the explicitly supplied non-secret ASCII `--aad` context.
Decrypted plaintext is a `login_state.restore` snapshot and exists only in
memory. No credential value belongs in arguments, examples, logs, or source.

Run with the already validated fork's virtual environment:

```sh
.venv/bin/python tools/probe_local.py \
  --envelope-dir /tmp/muse-live-APPROVED-ONE-TIME \
  --aad APPROVED-NONSECRET-CONTEXT
```

The probe checks existing auth, reads the identity endpoint and session list,
then reads at most two history events for one valid session. It never submits a
task, uploads, generates, mutates a persistent login store, or retries failures.
`identity_read` and `identity_response_valid` mean the endpoint was read and
returned a valid nonempty object; **they do not prove binding to the approved
account owner**. No personal identifier is printed or persisted. Sessions use
`sessions[].session_id`; history uses `chat_events`. Unknown schemas produce an
explicit partial result rather than a false success. Error output is restricted
to a fixed allowlist; unknown exception text or codes are never emitted.

The known one-time envelope files are deleted and in-memory clients closed in
`finally`. Python does not guarantee physical memory zeroization. A platform
refusal or forced termination can prevent `finally`; the orchestrator must then
verify and complete authorized local cleanup separately. Do not retry or change
routes after a rejection. Unknown outcomes require inspection before replay.

Offline fixtures in `tests/test_probe_local.py` exercise schema selection,
malicious diagnostic codes, and cleanup using synthetic ciphertext and mocked
transport. Passing these tests is not a live gateway or account-owner proof.
