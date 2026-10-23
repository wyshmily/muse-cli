# Local execution and recovery

This is the DotLink fork at **wyshmily/muse-cli**, not a new hosted service.
The target delivery layout is `main` plus `release`; see [migration status](BRANCHES.md). A branch moves;
use the full 40-character commit SHA in the verified delivery message as the
immutable source version. The latest branch is not an automatic upgrade source.
These changes are not deployed, released on PyPI, or installed on the original
server merely because they are committed. The upstream package version alone
cannot identify this fork's code.

## Three layers

- Short skill: where to obtain the approved code and how to choose a workflow.
- This request's message: user intent, task ID and authorized attachment references.
- CLI: `discover` for groups, `describe COMMAND` for parameters, examples,
  privacy/storage effects and validation level; live reads for actual state.

The 342-route `capabilities` catalog is evidence, not execution permission or
342 implemented safe commands. Existing legacy `muse-cli raw` remains outside
this curated surface. Do not fall back to it merely because a read fails.

## Recover code, separately from authentication

1. Resolve the user's verified repository and **full approved commit SHA** from
   the handover. No installation token or Muse secret belongs in the URL.
2. Fetch that commit into an isolated local directory, not an unrelated project.
   For example, after assigning `COMMIT` to that verified full SHA:

   ```sh
   git clone --no-checkout https://github.com/wyshmily/muse-cli.git muse-local
   cd muse-local
   git checkout --detach "$COMMIT"
   test "$(git rev-parse HEAD)" = "$COMMIT"
   python3 tools/verify_source.py
   ```

   Use the existing authorized GitHub connector if git access is unavailable;
   preserve the same commit and paths. A private repository may require an
   existing authorized connection. Do not invent a signed download URL or set
   up new persistent access. A failed fetch is not permission to change sources.
3. `SOURCE-MANIFEST.json` checks SHA-256 of the curated delivered source files.
   Trust comes from independently verifying the repository + commit, not from
   trusting an unverified manifest beside an unverified download. It is not a
   signature, dependency lock, or a full upstream-tree integrity audit. Extra
   files are not authorized for execution. The manifest excludes itself to
   avoid a circular hash. Do not overwrite existing source before comparison.
4. Inspect `pyproject.toml`; use a fresh Python 3.10+ virtual environment and
   the normal approved package registry. Example installation, only after
   source verification and applicable installation approval:

   ```sh
   python3 -m venv .venv
   .venv/bin/python -m pip install .
   .venv/bin/muse-read discover
   .venv/bin/muse-read describe quota
   ```

   Dependencies currently use upstream minimum ranges, not a reproducible
   transitive hash lock. Installation may resolve newer dependencies. This
   delivery does **not** claim byte-for-byte reproducible installed environments.
   Existing local tests used the already validated environment; a clean install
   on another OS is not yet verified. Do not run upstream `install.sh`, `update`
   or `pip install muse-cli` as a substitute for this pinned fork.
5. Discovery and description are offline and need no login. Check these before
   attempting any account query.

## Authentication boundary

Code recovery is automatable; it does not grant permission to recover secrets.
The earlier experiment moved a specifically approved temporary login into the
assistant's execution environment, restored it in memory, and removed the
local temporary secret material. That approval is not a standing credential
migration grant. When the environment is refreshed, request the specific
approval needed for a new credential transfer before doing it. Never put
cookies/tokens in skills, manifests, CLI examples, shell history, logs or GitHub.
Do not configure persistent access or new credentials as part of bootstrap.

Alternatively, use the existing authorized original-server formal channel for
permitted reads, without migrating secrets. A locally installed CLI can only
use an explicitly selected, already authorized login store. The new read
commands do not write it; legacy identity/session/history/space reads can use
`SavedLogin.resume` and update selected login storage, as `describe` discloses.
Normal gateway reads can perform transient authentication handshakes. That is
not a new persistent credential grant. No automatic login recovery on rejection.

## Resume a task without replaying it

Recover code, discover its current capabilities, then read the existing task or
session state using the confirmed ID. A timeout or unknown result is not proof
of failure. Query before replay; never resend a successful task. This delivery
does not add asynchronous generation orchestration. A quota exhaustion result
is not an auth error, and neither authorizes switching accounts/paths. Stop on
401/403; preserve only safe diagnostic status, not private response bodies.

## Verification levels

`live-contract-verified` means the protocol was checked on the original server
and account on 2026-10-20, not that this new package has been deployed everywhere.
Library `artifacts` was tested live; `media` and `recents` were static-confirmed.
Computer task entry fields were static-confirmed because the live list was
empty. Legacy commands are labeled separately. Read per-command notes and
[coverage](WEB-FEATURE-COVERAGE.md) before interpreting a result.

## Automated Linux bootstrap and doctor

`tools/bootstrap_local.py` makes the code-only steps above repeatable on Linux
with Python 3.12+. This tool's minimum is separate from the library's Python
3.10+ requirement. First independently verify this tool and the repository's
full commit SHA; then run:

```sh
python3 tools/bootstrap_local.py bootstrap --source "$TRUSTED_CHECKOUT" \
  --commit "$COMMIT" --runtime "$NEW_RUNTIME"
python3 tools/bootstrap_local.py doctor --commit "$COMMIT" --runtime "$NEW_RUNTIME"
```

Bootstrap requires a nonexistent runtime directory. It archives the selected
committed tree (ignoring working-tree edits), verifies its manifest before
installation, installs the fork plus `linux-login` in a fresh venv, and runs
doctor. It does not fetch arbitrary repositories, recover authentication, or
replace the original server. Registry access is required for installation;
dependency ranges are not a reproducible hash lock. Failed runtimes are retained
for inspection, not silently deleted or retried.

Doctor checks the source manifest, compares the installed package's file
inventory and SHA-256 hashes to the source snapshot, exercises installed CLI
entrypoints and offline discovery, checks missing-store failure behavior, and
runs the snapshot's mocked tests against the installed package. It isolates
HOME/DBus/Muse/Python configuration and disables update checks. This is
process-configuration isolation, **not an OS network sandbox**. The source-commit
marker is not a signature; trust still comes from the independently verified
repository and commit. Success reports `live_gateway_verified: false`.

Do not import real credentials into these credential-free doctor runtimes.
Any separately approved temporary live verification must use a separate
in-memory session, report its actual calls/results, and clean up its temporary
secret material. A standing instruction to operate Muse is not permission to
silently copy login keys into every refreshed environment.

A separate, explicitly authorized read-only live probe is documented in
[LOCAL-LIVE-PROBE.md](LOCAL-LIVE-PROBE.md). It is not run by bootstrap or doctor;
it neither obtains credentials nor grants permission to transmit them.

## Task-bound recovery request plans (offline v1)

`tools/recovery_plan.py` is a standard-library-only planning/validation tool.
It does **not** implement automatic recovery, send an approval message, generate
keys, export/import a credential, or issue a persistent login. It can run before
package installation. Bootstrap/doctor remain credential-free and do not invoke
this tool automatically. No real-account transfer is covered by its tests.

1. Finish the pinned code bootstrap/doctor above.
2. Explicitly select the intended credential file and inspect **metadata only**:

   ```sh
   python3 tools/recovery_plan.py inspect-status --credential-file "$SESSION_FILE"
   ```

   `needs_recovery` means the selected path is missing, not that the tool searched
   all possible login stores. `present_unverified` means a private, owner-owned,
   single-link regular file is present; no credential content was opened and no
   authentication was checked. First verify that existing session through the
   already authorized formal workflow. Do not send a new recovery request merely
   because a file is present but unverified. Unsafe permissions, symlinks (including
   parent components), `..` path components, nonregular files or unreadable metadata
   block the workflow.
   This deliberately narrow check is not an OS sandbox or race-proof file opener;
   a future credential consumer must independently revalidate before reading.
3. Only for missing or independently confirmed invalid credentials, prepare a
   request using independently verified current task/runtime identity, the SHA-256
   of the **recipient's public key** (never its private key), allowed operation scope,
   approved source commit and non-secret account/vault aliases. This tool does not
   create the recipient key or attest environment identity; the trusted server must
   match them against its configured runtime policy. Example (all inputs non-secret):

   ```sh
   python3 tools/recovery_plan.py create --credential-file "$SESSION_FILE" \
     --task-id task-example-1 --environment-instance-id env-example-1 \
     --recipient-public-key-sha256 "$PUBLIC_KEY_SHA256" --cli-commit "$COMMIT" \
     --account-ref owner-muse --vault-ref muse-primary \
     --actions auth_check read_history read_sessions \
     --hosts hatch.metaaivm.com muse.ai --ttl-seconds 300 > recovery-plan.json
   ```

   Standard output is the plan; standard error contains only metadata status.
   For `present_unverified`, creation produces a **draft pending session
   verification**, not a finding that recovery is necessary and not permission
   to send a notification. No command accepts raw credentials, callbacks, an
   owner `approved` flag or an approval receipt. Never supply secrets as aliases.
4. A trusted owner-facing adapter may ask about this exact plan after verifying
   recovery is actually necessary. A native owner reply or a verified bound
   WeChat owner event must be resolved by that adapter—not fabricated in model
   input. Approval must bind the exact digest, task, environment, public key,
   scope, source commit and lifetime; a server-generated challenge and atomic
   one-use claim are additionally required. The CLI never treats a valid digest
   as approval and never calls that server itself. A changed binding, expired
   plan or environment reset requires a new plan and new specific approval.
5. To check an incoming non-secret plan, run `validate --plan recovery-plan.json`
   with the same binding flags shown above (omit `--credential-file` and
   `--ttl-seconds`). Obtain these expected values from independently trusted
   current intent/runtime policy, **not by copying the incoming plan**. Success
   is only `valid_non_authorizing_plan`; it grants nothing. Validation does not
   detect reused request IDs or perform a claim; the trusted server must do both.
6. The older [live probe](LOCAL-LIVE-PROBE.md) remains a separate, specifically
   approved diagnostic. Neither this plan nor its validation silently wires the
   probe to a vault, authorizes a transfer, or changes its cleanup requirements.

### Wire contract

`describe` reports the offline contract. Exact fields:
`schema_version` (integer 1), `request_id` (lowercase canonical UUID4), `task_id`,
`environment_instance_id`, `recipient_public_key_sha256` (64 lowercase hex),
`scope`, `cli_commit` (40 lowercase hex), `created_at`, `expires_at` (safe integer
UTC epoch seconds), and `request_digest` (64 lowercase hex).

`scope` has exactly `actions`, `hosts`, `account_ref`, `vault_ref`.
Nonempty arrays are already sorted and unique; they are **not** silently sorted.
Actions are limited to `auth_check`, `read_identity`, `read_sessions`,
`read_history`. Hosts are limited to `hatch.metaaivm.com` and `muse.ai` (hostnames,
not URLs). IDs and aliases match `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`; no emails,
Unicode, slashes or secret values. Unknown fields are rejected at both levels.
The lifetime is 1–600 seconds, creation cannot be in the future, and the exact
expiry instant is already expired. Booleans are not integers.

Canonical bytes omit only `request_digest`, sort object keys recursively, retain
array order, and encode compact ASCII JSON with no whitespace or newline.
All permitted string values are ASCII tokens; JSON escaping differences cannot
occur. Digest is SHA-256 of those bytes. The shared synthetic fixture is
`tests/fixtures/muse-recovery-plan-v1.json`; its digest is
`7914362042ffc603932d5496860800389cb42a3f68fc25d7ca9babc51ef7ac9b`.
It is intentionally historical and must fail current-time expiry validation.
The fixture tests use a fixed synthetic clock, never an expiry bypass CLI flag.
