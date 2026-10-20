# Muse web feature/API audit

Date: 2026-10-20 UTC. The matrix below began as an independent static review. The implementation/validation section records subsequent read-only verification separately. The packaged web_route_catalog.json inventories 342 observed route definitions, metadata and risk classifications. It is NOT an execution allowlist.

## Findings that affect implementation

1. 342 observed methods versus 258 legacy methods means 86 additions and 2 old methods not observed (`feed.unit.share`, `feed.ingest`), not 86 verified usable APIs. Unobserved does not prove removed. Routes and UI availability differ.
2. The baseline `muse-read` before this expansion exposes identity, sessions, session, history, spaces, VM health/enrollment/status and quota. `media` deliberately fails as unverified. Do not equate the legacy route registry or generic CLI with audited commands.
3. Highest-value media gap is `fs.library`, a POST used as a pure listing query by the web library. The present library does not rely only on `artifacts.list`. A verb-only GET restriction excludes legitimate reads.
4. Conversely GET does not prove safe: debug access, voice media endpoints, credential catalogs, SAS codes, wallet and permissions require field-level review. No generic GET escape hatch should be introduced.
5. Website `/api/session?vm_state=live` and `fetchSubscriptionAction` are separate from Hatch gateway routes. Quota is a read-only server action despite HTTP POST; continue the writer's deployment/action validation, no blind retries on 403. See project `docs/QUOTA-CONTRACT-EVIDENCE.md` for actual execution evidence.
6. Route metadata matters: `fs.raw` is binary, media channel, unbounded maxResponseBytes in web; it must not flow through JSON CLI/redaction or unbounded automatic download. `computer.preview` likewise binary/media. Preserve service/noiseOnly metadata before enabling routes.

## Feature matrix

| Feature | Actual method / contract | Inputs established | Auth / risk | Coverage and next step |
|---|---|---|---|---|
| Identity and sessions | identity; sessions.list; sessions.get | get uses id path | Existing gateway, private metadata | Existing read commands |
| Chat history | chat.history; chat.history_window | existing CLI session_id,limit; window anchor_seq,before_limit,after_limit plus session wrapper | Noise gateway; transcript content | Basic history covered; window response chat_events,has_older,has_newer,newest_seq,transcript_revision observed; full wrapper validation before expansion |
| Conversation search / message lookup | chat.search GET /chat/search; chat.message_get GET /chat/message | Route definitions only, query contract not found in inspected callsites | noiseOnly | Catalog only; do not invent q/id fields |
| Library artifacts/media/recents | fs.library POST /fs/library | preset artifacts/media/recents, limit,offset | Existing Noise gateway read query; metadata only | Priority P1. Explicit semantic-read allowlist; no automatic downloads |
| Directory listing / stats | fs.list,fs.stat,fs.stats POST | list/stat path; stats paths[] | Existing Noise transport; arbitrary paths can expose private metadata | Contract observed; restrict requested scope rather than root recursive listing |
| File reads | fs.read,fs.reads POST | read path,offset,len; reads entries with normalized path | Private content, explicit selection and bounded bytes needed | Later; web chunks read at 1MiB; len/eof/base64 validation important |
| File search | fs.search POST | helper forwards object; exact search fields not established | Private content discovery | Response entries,total,has_more known; do not guess request fields |
| Raw/download | fs.raw GET /fs/raw/{*path}; fs.export POST /fs/export | raw path, optional Range; export path,format:pdf | Binary/media, authenticated, potentially large; export may incur compute | Separate binary download pipeline with byte cap; no URL/secret dump |
| Legacy artifact routes | artifacts.list GET /api/artifacts; artifacts.fetch_url GET /artifacts/fetch_url | Only route registry in inspected evidence | fetch_url semantics/URL safety not established | Do not substitute guessed parameters for current library |
| Cloud desktop summary | computer.context GET /api/computer/context | Dedicated worker validating | Existing gateway, summary vs screenshot distinction | P1 summary-only; no preview download |
| Desktop task/lease | browser_task.get; browser_task.lease_info | task_id path | Private task/access details | Field allowlist before enabling |
| Desktop previews | computer.preview GET /api/computer/previews/{task_id}/{sha256} | task_id,sha256 | binary/media, screen privacy | Catalog only, task-specific later |
| Desktop controls | browser.lease; browser_task.refresh_environment/end_and_release/takeover/present/viewer/heartbeat/close/release/stop; ssh.operator.* | Route definitions; some task_id path | Writes, allocation, control/security changes | Record only; do not exercise for discovery |
| Voice/model catalog | voice.catalog/catalog_filters; model.get | Dedicated worker validating | Gateway; safe summary candidate | P1 typed response allowlist |
| Voice calls/custom voices | voice.calls.media_endpoint; custom_voices.*; start/end/dictation/avatar prepare | Route metadata only | Call access/creation, user content, write side effects | Catalog only, no live call probing |
| Connector marketplace | connectors.homepage/list/get | Dedicated worker validating | Catalog vs connected account data distinction | P1 homepage summary; no connect callbacks |
| Accounts/credentials | connectors.accounts; credentials.*; OAuth callbacks; custom_connectors.* | Route metadata only | Secret/access configuration | No blanket read enablement; never include credentials/raw auth context in diagnostics |
| Usage/quota | website fetchSubscriptionAction | Writer's confirmed server-action contract | Existing same-origin session; read-only POST | Implemented separately; not gateway /subscription callback |
| Tasks/activity | tasks.list/runs; activity.list/get; subagents.list/status | id path where present; filters not audited | Private execution history | P2 validate typed filters; tasks.run/delete are writes |
| Goals/spaces | goals.list/get; spaces.list; spaces share status/review/settings | id/slug path | Private pages and sharing metadata | spaces.list existing; share/export separate from read summaries |
| Email | email.mailbox.get/setup; threads.list/get; messages.get/attachment.get | setup {}; paths message_id/thread_id/index | daemon + noiseOnly; private emails | Setup is proven metadata response, not mailbox creation; no need to enable in this CLI batch |
| Permissions/grants | permissions.inventory/settings; egress.permissions.*; grants.list | scoped paths scope_type/scope_id | Security metadata, consent records | Summaries only after schema audit; edits/reset/revoke never discovery actions |
| Peers | peers.status/list/invites/requests/photo/avatar | path IDs where present | Relationship and approval codes | No SAS display; no invite/accept/open/confirm/disconnect |
| Feed/podcasts/shopping/hotels | registered routes in JSON | query contracts not audited | Feature-/user-specific | Catalog only; events/reactions/engagement are writes |
| Debug/export | bug_report_logs.create/download; dyi.export; home_link_bug_reports.collect | file_id only for log download | Private logs, export side effects | Do not collect just to discover API; no automatic diagnostics upload |

## Strong evidence anchors

- `04q1aiszeeyua.js`: route definitions; `current-routes-observed.json` provides per-method offsets. Definitions distinguish service, noiseOnly, streamMode, responseType, channel and timeout. Added route metadata is not automatically compatible with legacy gateway code.
- `0nx_bajvf6zgq.js`, offsets 72344 / 72549 / 72747: `bindLibraryArtifactsGatewayQuery`, `bindLibraryMediaGatewayQuery`, `bindLibraryRecentFilesGatewayQuery` use `fs.library`. Artifacts/media PAGE_SIZE=20, recents limit48, all offset0. Queries have separate cache keys and refresh periods; no mutation invoked.
- `3m2yhlmbziny2.js`: exported `normalizeFsLibraryResponse` requires entries array, produces name/path/type:file/size/modifiedAt and optional media; root total/hasMore from total/has_more. Thus safe CLI whitelist: entry name,path,size,modified_ms; root total,has_more. Omit media resource structures/URLs.
- Same file `useHatchGatewayFs`: list/stat/stats/read/reads/search/library/rawFetch/exportPdf separate from write/mkdir/del/rename/uploadFile. `fs.read` uses offset,len and checks declared payload lengths; raw read optional Range validates nonnegative safe integers. `fs.export` uses `{path,format:"pdf"}`.
- `05-ka1sp3k_nk.js` offset111726: `chat.history_window` with anchor_seq,before_limit,after_limit via wrapper aj; response transcript revision guard prevents stale history replacement. This wrapper's session context needs preservation, not guessed globals.
- `3rs4zwf_ncs19.js` offset3193: `email.mailbox.setup` called with `{}` via target-bound gateway. Validates domain,name,handle,email_address consistency; distinct from mailbox.create. Its name alone does not make it a write.

## Delivery constraints

The matrix itself is static evidence; see the live validation section below. Keep static-discovered, request-contract-verified, and runtime-verified statuses separate in CLI capabilities. Fail closed for unknown schema; whitelist output fields and enforce bounds. Return FORBIDDEN once on explicit denial, never retry a different transport to bypass it. Preserve target identity binding for all requests, and do not include cookies/session values in evidence files.


## Implemented and runtime-verified read contracts

On 2026-10-20 at 07:01–07:02 UTC, the existing original account/gateway returned
structured responses for `model.get`, `computer.context`, `voice.catalog_filters`,
`voice.catalog`, `connectors.homepage`, and `fs.library` with preset `artifacts`.
Only schema was retained; no private task text, filenames, URLs or credentials
were included in repository evidence. Media/recents library presets are confirmed
by frontend query code but were not separately executed. New CLI implementations
were tested locally with synthetic fixtures, not installed into production.

New commands:
- `muse-read model`: selection and available model metadata. Hidden visibility
  suppresses model information; never changes selection.
- `muse-read computer-context`: task IDs/state/count only. No page text, browser
  URLs, screenshots, lease, wake, input or control actions.
- `muse-read voice-catalog --limit 20 --offset 0`: bounded library voice listing;
  no audio generation/playback/download. Custom pinned voices omit free text.
- `muse-read voice-filters`: public filter metadata, not selection changes.
- `muse-read connector-marketplace`: catalog/state summary; no consent URLs,
  custom descriptions, account contents or connection/permission actions.
- `muse-read library --preset artifacts --limit 20 --offset 0`: bounded library
  metadata. `media` and `recents` are also explicitly supported static presets.
  No arbitrary path input, file contents, download, export, upload or deletion.
- `muse-read capabilities --id voice. --limit 100`: offline prefix-filtered
  catalog. It does not access credentials, connect to Muse or authorize execution.

Only four new GET routes are added to the executable legacy route table. The
342-entry catalog is separate and never loaded as an execution allowlist. Existing
legacy writes are not extended. `fs.library` is the sole additional semantic-read
POST supported here; the website uses it as a list query, with no mutation body.

Gateway metadata commands restore the already configured login only in memory,
then use the existing temporary gateway authentication handshake. They do not
persist a refreshed login or fall back to recovery. A failure is not evidence of
quota exhaustion and is not retried through another transport.

### Remaining gaps / stopping boundary

All other new routes remain catalog-only, including email private content,
peers/SAS, debug access, security credentials, permissions changes, payments,
VM lifecycle/control, binary preview/download and write operations. Some GETs
may expose credentials; some POSTs are reads. HTTP verb alone never grants access.
Chat search parameters and file-search input remain unverified. The 342 count
excludes website Server Actions and potentially unobserved/dynamic routes; this
is not a claim to have captured all Muse APIs or all browser features.

No deployment, release, tag or PR was created. Tests run locally. The existing
workflow triggers on main pushes, version tags and PRs, not this isolated branch.
