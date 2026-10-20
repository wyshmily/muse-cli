# Muse read-only subscription query evidence

Verified 2026-10-20 by static inspection of official public JavaScript assets referenced by the authenticated homepage. No JavaScript bundle was executed. Runtime outcomes below were checked separately using the existing authorized identity. Byte offsets below are UTF-8, zero-based.

## Runtime outcome and implementation boundary

One authorized attempt was made through the original server identity, using the authenticated initial Flight tree and `includeAgreement:false`. The request returned HTTP 403. It was stopped without retries, alternate actions, or routing workarounds.

Consequently, the source establishes the client schema and request shape, not a functioning realtime CLI quota query. A non-networked `UNVERIFIED` result is appropriate until access is explicitly resolved through the supported path. The independent VM inventory reader was successfully tested with HTTP 200; that does not establish quota access.

Do not infer that HTTP 403 means exhausted credits. Do not infer that the action succeeded, that subscription data was read, or that quota reset was learned. No alternative quota action is sought after this denial.

## Read-only action and response fields

- `0nx_bajvf6zgq.js`, byte 20448: `e.A(862035)` loads `HatchSettingsDialogContent`.
- `0id24ziqkc-v9.js`, byte 4918: lazy module 862035 references `42t7iubel_7xb.js` and `2dl4_s2qy9opi.js`, among its actual dependencies.
- `42t7iubel_7xb.js`, byte 812: `createServerReference("4029ac5c4bd03136487d91ebde5de39c64b35229b4", ..., "fetchSubscriptionAction")`.
- Same file, byte 4717: `fetchSubscriptionAction({includeAgreement:r})`. The reader requires `success` and non-null `subscription`; `error` is its reported failure text. Use `includeAgreement:false` for this narrow quota query.
- Same file exposes `subscription.usage`, `tier`, `statusSubtitle`, `usageRowLabel`, `usageRowValueLabel`, `usageRowFooter`, `billingSubtitle`, `topupRowLabel`, and `topupRowValueLabel`.
- `2dl4_s2qy9opi.js`, byte 26584: `usage.state` falls back to `UNKNOWN`; rendered branches distinguish `METERED` and `UNLIMITED`.
- Same file, byte 40399: monthly meter uses `usage.percentUsed`.
- Same file, byte 24096: top-up values are `subscription.topupBalance` and `subscription.topupTotal`.
- No machine-readable quota reset timestamp was found in these client sources. `agreement.currentPeriodEndTime` exists (`42t7iubel_7xb.js`, byte 9057), but is an agreement/billing-period boundary, not proven to be the quota reset time. Do not relabel it as reset time.
- Preserve server-provided `statusSubtitle` / `usageRowFooter` as display text when useful; do not parse them into a guessed timezone/date.

## Wire format

`3qboj8_74hu5g.js`, bytes 36258–36600, constructs:

- POST to the current router canonical URL (the same authorized page, not a guessed REST endpoint).
- `Accept: text/x-component`
- `next-action: <discovered fetchSubscriptionAction ID>`
- `next-router-state-tree: encodeURIComponent(JSON.stringify(trimmedTree))`
- `x-deployment-id` if the app has a deployment ID; `next-url` only for the app's intercepted-route context.
- Body: `encodeReply(actionArgs)`.

`1-gj2rmtigpe9.js`, bytes 26260 and 26330, uses `JSON.stringify` and returns the string directly when there are no multipart values. Therefore this simple argument list encodes as `[{"includeAgreement":false}]`.

The wrapper in `3qboj8_74hu5g.js`, byte 70731, is only `return fetch(e,t)`. It adds no bearer or CSRF token. Browser same-origin cookies provide the existing session; no new credential mechanism should be invented. The action request itself does not specify Content-Type; fetch sends a string body using its normal string-body behavior. An implementation may match `text/plain;charset=UTF-8`; it must not assume the body is a JSON REST request merely because its bytes are JSON text.

Responses are React Flight (`text/x-component`), not ordinary JSON. The app decodes the Flight response and selects its root `.a` action result (`3qboj8_74hu5g.js`, roughly bytes 37600–38100). Do not parse a single JSON-looking line and silently discard references or error records. Unknown encodings should fail closed.

`37f8c3_ff4ryh.js`, byte 1099, wraps the reader in `runHatchActionWithSessionRecovery`: after the action, a `sessionRecovery` object with scope `hatch` and reason `authentication` or `checkpoint` can trigger recovery. Do not copy that recovery behavior into a strictly read-only query. Return a blocked/auth-expired result instead.

## Router state extraction, without evaluating JavaScript

The initial page embeds JSON arguments in `self.__next_f.push(...)`. A Python `JSONDecoder.raw_decode` can parse each argument directly after the opening parenthesis. Concatenate the second element of every `[1, <string>]` push. Find the plain JSON Flight record `0:` and decode its payload. In the observed initial payload, its router tree is `payload["f"][0][0]`.

This was tested against the saved public `index.html`, which yields an `oidc/logged-out` tree. Do not reuse that logged-out tree for authenticated calls. Apply the parser independently to the original authenticated page in its original environment, keeping that HTML and any account data in memory.

`3qboj8_74hu5g.js`, byte 104209, defines the exact tree trimming logic:

1. Read `[segment, parallelRoutes, unused, refresh, flags]`.
2. A string segment starting with `__PAGE__?` becomes `__PAGE__`.
3. A dynamic segment array is normalized to `[name, value, type, null]`.
4. Recursively trim every value in `parallelRoutes`.
5. Start output at `[segment, children]`. Preserve truthy `refresh` at index 3 with null index 2. Preserve `flags` at index 4 unless undefined.
6. Encode the compact JSON with JavaScript encodeURIComponent-equivalent escaping.

Flight's literal `"$undefined"` means JavaScript undefined. Treat it as missing before evaluating refresh or flags. Reject unresolved Flight references or unexpected tree structures rather than guessing.

## Exhausted versus unavailable

- `05-ka1sp3k_nk.js`, byte 85325, consumes `agent_status` event payload `activity_code` into the agent activity state.
- `1h_67546_mo7l.js`, byte 5370, maps `activity_code === "out_of_credits"` to `Out of usage`.
- That explicit event state is evidence of an out-of-usage condition for the relevant agent; an arbitrary HTTP 429 is not.
- `percentUsed >= 100` means the monthly metered component is used. It does not by itself prove total exhaustion because top-up balance is separate.
- An unknown `usage.state`, failed query, missing field, or auth failure must remain unknown, not become exhausted or healthy.

## Operations excluded from the reader

Do not call lease/reset/wake, session reset/check, token-minting, payment portal, purchase, subscription modification, credential, or recovery operations as probes or fallback reads. This note intentionally contains no subscription-modification action IDs.
