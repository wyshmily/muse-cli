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
- `muse-read quota`: currently unsupported. Exits 2 with
  `QUOTA_QUERY_UNVERIFIED` **before accessing credentials or sending requests**.

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
- Local unit tests use synthetic data/mocks and do not use a live account.
  Live checks verified service contracts, not a production installation of
  these new commands. No deployment was performed.

## Quota and reset limitations

Official settings assets reference a read-only `fetchSubscriptionAction`
(Next Server Action, not a gateway route). The exact deployed action reference
was statically observed, but one authorized read using `includeAgreement:false`
returned HTTP 403 at 06:38 UTC. No retry or alternate route was attempted.
The action ID is deployment-dependent and is deliberately not hardcoded in this
CLI. See [source evidence](QUOTA-CONTRACT-EVIDENCE.md).

The frontend consumes `usage.state`, `usage.percentUsed`, separate
`topupBalance`/`topupTotal`, and display labels/footer. No live quota value was
retrieved. A metered percentage of 100 does not prove total exhaustion when
top-ups may exist. An explicit agent activity `out_of_credits` is distinct from
authentication failure or HTTP rate limiting.

No machine-readable quota reset timestamp was established. The agreement field
`currentPeriodEndTime` is a billing-period boundary, not a verified quota reset.
Missing data remains unknown; the commands never invent remaining credits or
an expected recovery time.
