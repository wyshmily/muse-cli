# Read-only account and VM queries

Commands use an explicitly selected, already configured login store. They do not
create an account, send a task, wake/lease/reset a VM, or change a subscription.
No release or production deployment is implied by this branch.

- `muse-read vm-status`: website VM inventory and current state. Uses the observed
  `GET https://muse.ai/api/session?vm_state=live` with the restored in-memory
  login HTTP session. No auth-check, gateway connection, or saved-login write.
  Output is limited to status, VM IDs, state/source, type and preferred flag.
  Endpoint URLs, notary data, avatar text and unexpected fields are omitted.
- `muse-read vm-health`: gateway health summary, not a quota or balance check.
- `muse-read vm-enrollment-health`: gateway CVM enrollment state.
  Both health commands use existing gateway authentication/transport, including
  the normal auth-check and short-lived hatch-token handshake before their GET
  (`/health` or `/health/enrollment`). They are not an entirely GET-only network
  flow. Login state is restored only in memory and is never saved by these
  commands. They never call account recovery, wake, reset or lease operations.
- `muse-read quota`: the website's read-only subscription query contract was
  verified at 06:53 UTC and is implemented in this branch, but not deployed.
  It reads the current homepage and reviewed asset chain, verifies the pinned
  read-action ID, then sends one `includeAgreement:false` Server Action request.
  It restores login state only in memory, does not save it or connect to the
  gateway, and never performs recovery or an automatic retry. Output is limited
  to usage state, percentage, quota status, Unix-seconds reset time and its UTC
  representation, plus independent top-up balance and total.

Select the existing store using `--profile` and `--store`; file-backed stores
also need the previously configured `--vault`. These commands do not configure
or migrate credentials. Invalid credentials, HTTP permission rejection and rate
limiting are reported separately as `AUTH_INVALID`, `FORBIDDEN`, `RATE_LIMITED`.
HTTP 429 does not mean quota exhaustion. Response text is not echoed in errors.

## Evidence and validation (2026-10-20 UTC)

- Fork base: `343c31ba2400fc2605ff689c563e0467470f9552`.
- Website source `https://muse.ai/_next/static/chunks/08zja04kl3tkw.js`
  explicitly fetches `/api/session?vm_state=live`. At 06:35 UTC the existing
  identity returned HTTP 200 with `status=assigned` and VM state fields.
- Existing `routes.json` defines GET `vm.health` and `vm.enrollment_health`.
  Both returned structured objects through the existing gateway at 06:39 UTC.
  Only schema was captured, not diagnostic bodies or credentials.
- At 06:53 UTC, an explicitly approved, limited correction to the subscription
  read returned HTTP 200 through the original server identity. It used the same
  homepage, read action and `includeAgreement:false`, adding the current
  homepage deployment ID and the existing login's request headers. This verifies
  the response contract, not a deployed CLI implementation. No actual account
  usage values, balances or reset timestamps are retained in this document.
- Local unit tests use synthetic data/mocks and do not use a live account.
  Live checks verified service contracts, not a production installation of
  these new commands. No deployment was performed.

## Quota and reset semantics

Official settings assets reference a read-only `fetchSubscriptionAction`
(Next Server Action, not a gateway route). An initial authorized read using
`includeAgreement:false` returned HTTP 403 at 06:38 UTC and was stopped.
The separately approved correction succeeded at 06:53 UTC without changing
the action, page, identity or requested data. Because more than one request
header changed, the result does not establish which header caused the earlier
403. Future 403 responses must stop the query: no automatic retry, alternate
action, recovery or routing workaround. The action ID is deployment-dependent;
the implementation pins the reviewed ID and verifies it against the current
homepage's referenced asset chain before every request. A changed or missing
reference fails closed as `READ_CONTRACT_CHANGED`; it does not automatically
adopt or call a newly discovered action ID.
See [source evidence](QUOTA-CONTRACT-EVIDENCE.md).

The successful response includes `usage.state`, `usage.percentUsed`,
`usage.resetsAt` (Unix seconds), and `usage.quotaStatus`. The subscription's
`topupBalance` and `topupTotal` are independent fields. A metered percentage of
100 does not prove total exhaustion when top-ups may exist. Unknown quota status
values must remain unknown, not be inferred from a percentage. An explicit
agent activity `out_of_credits` is distinct from authentication failure or HTTP
rate limiting.

`usage.resetsAt` is the machine-readable usage reset field observed in the
successful response. It is not `agreement.currentPeriodEndTime`, which is a
billing-period boundary. The query excludes agreement details. Missing or
invalid reset data remains unknown; a reset timestamp is not a guarantee that
an unrelated account, authentication or VM problem will recover then.
