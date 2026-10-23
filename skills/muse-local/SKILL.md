---
name: muse-local
description: Discover and use the pinned DotLink Muse read CLI in an ephemeral execution environment.
---

# Muse local entry point

1. Read `docs/LOCAL-RECOVERY.md`. Resolve the verified `wyshmily/muse-cli`
   delivery commit, verify its source manifest, and use the isolated installation.
   Never replace this fork with the upstream PyPI version or an unreviewed script.
2. Run `muse-read discover`; choose a group with `--group account|conversations|library|metadata`.
   Run `muse-read describe COMMAND` for the current parameters, example,
   read/privacy/storage effects and verification notes. Both are offline.
3. For login, read `docs/NATIVE-LOGIN.md`: native OTP uses `muse-login`
   preflight/start/confirm/check. Check the approved existing store before a new
   attempt. `preflight` is metadata-only; `check` performs auth requests and
   local state writes. Auth success does not prove Gateway availability, and
   Gateway failure does not by itself invalidate login. No PTY in an MCP tool
   means that channel cannot supply hidden interaction, not that native login
   is unavailable. Never put secrets into argv/env/logs or bypass the TTY guard.
4. Use this request's user intent, IDs and authorized attachment references.
   Check existing state before acting or recovering an uncertain operation.
5. Code recovery never authorizes secret recovery. Environment refresh does not
   renew an old one-time credential-transfer approval. Use the existing formal
   original-server channel or obtain any required specific transfer approval;
   never persist secrets in skills, command lines or source control.
   After bootstrap/doctor, use `python3 tools/recovery_plan.py describe` and
   `inspect-status --credential-file PATH` for metadata-only recovery discovery.
   Missing credentials (`needs_recovery`) may justify a task-bound `create`
   request; `present_unverified` must first be checked within the existing
   authorized workflow, not treated as expired or used to trigger another ask.
   Only missing or independently confirmed invalid credentials need recovery.
   See [recovery plans](../../docs/LOCAL-RECOVERY.md#task-bound-recovery-request-plans-offline-v1)
   for exact task/environment/key/scope binding. Plans and `validate` never grant
   approval or transfer credentials; owner approval and one-use server claim
   remain separate, and no automatic recovery/notification is implemented here.
6. `capabilities` is only an observed-route catalog, not an execution allowlist.
   Do not invoke writes, raw routes, purchases, reset/wake, uploads or permission
   changes from catalog discovery alone. Stop on rejection; do not change identity
   or paths to bypass it. Never automatically resend a task after an uncertain result.

This is a repository skill document, not an installed production MCP skill.
