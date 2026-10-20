# Branch consolidation and manual release handover

## Target and preserved history

Target layout: `main` for maintained development, `release` for deliberately
prepared release snapshots. No new feature branch is needed for this migration.
The migration commit is prepared on the existing development branch, then
fast-forwarded (never forced) to `main`; `release` is created at that same commit.
Verify remote refs after executing this plan; this document alone is not evidence
that a ref update succeeded.

Original refs verified 2026-10-20:

- `main`: `ebcb6310432ad2d39927bcb59e686330b0538310`
- `dotlink-native-stream` (current GitHub default): `343c31ba2400fc2605ff689c563e0467470f9552`
- `dotlink-readonly-vm-status-20261020`: `4f89aea54bfbc395f51578574f7e487ba6ebea64`

The last ref contains all commits from both other refs: 7 commits ahead of old
main, 0 behind; 4 ahead of old default, 0 behind. Fast-forward preserves them all.
Do not delete any ref until its commits are verified contained in main.

## Pending administrative cleanup

Changing the GitHub default branch to `main` and deleting the two old dotlink
branch refs are **pending**, not completed by this migration. The available
connector has no default-branch update or delete-ref method, and the browser is
not signed in. Do not obtain tokens or bypass these limits. An authorized owner
or their later Codex session can finish those steps after verifying ancestry.
The old default still has the historical workflow until it is retired. Do not
create a tag from old commits expecting the new manual-only policy.

## Exact workflow behavior

`.github/workflows/publish.yml` now has only `workflow_dispatch`. Pushes to main,
release, other branches, tags, and PR events do not automatically build or publish
when they point to this revised workflow. No workflow was dispatched as part of
consolidation. GitHub uses workflows in the event's associated SHA/ref:
https://docs.github.com/en/actions/concepts/workflows-and-actions/workflows#workflow-triggers

- Explicit manual dispatch with default `publish=false`: build sdist/wheel,
  twine checks, wheel smoke tests, and upload Actions build artifacts only.
- Explicit manual dispatch with `publish=true` **on a matching v* tag**:
  build/version check, then existing PyPI publish job, then GitHub Release.
- `publish=true` on a branch does not publish because both publish jobs require
  a v* tag. Prefer a build-only run first; no automatic branch-to-tag creation.
- Job permission blocks, trusted-publisher environment name and credentials
  configuration are unchanged. No permission expansion is part of this change.

Manual dispatch availability may require switching the repository default to
main first, because the old default does not declare this manual trigger.
Publishing is reserved for the user's later Codex work, not this consolidation.
PyPI trusted-publisher authorization for this fork is unverified; configured jobs
are not proof it can publish. Do not change permissions or credentials to make
publication work without the necessary approval. No release/version bump/tag
was created during this migration.

## Fixed-source recovery

Pin the verified delivery commit, not a moving branch, and follow
[LOCAL-RECOVERY.md](LOCAL-RECOVERY.md). `SOURCE-MANIFEST.json` is regenerated for
changed source/docs and includes this workflow and handover. Source integrity
is separate from credential recovery and dependency reproducibility.
