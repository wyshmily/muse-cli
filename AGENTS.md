# muse-cli agent notes

## Current branch/release policy (2026-10-20)

The workflow is now manual-only. Read `docs/BRANCHES.md` before release work.
Pushes, PRs and tags do not start Actions. A manual run defaults to build-only;
publication requires explicitly selecting `publish=true` on a matching `v*`
tag. The historical release steps below must not be interpreted as permission
to run Actions, publish, or expect an automatic tag-triggered upload.


## Layout

- `src/muse_cli/` is the package: `cli.py` (commands), `gateway.py` (auth,
  Noise transport), plus `routes.json` and `desc0.bin`/`desc1.bin` data files.
- `pyproject.toml` holds all packaging metadata (hatchling). The version is
  read from `__version__` in `src/muse_cli/__init__.py`; that is the only
  place it lives.
- `.github/workflows/publish.yml` builds and smoke-tests only on explicit manual dispatch; publication also
  requires `publish=true` on a matching `v*` tag.

## Cutting a release

When asked to "cut a release", "publish a new version", or similar, follow
these steps in order. Stop and report if any step fails.

1. **Pick the version.** Use the version the user gave. If they didn't give
   one, propose one using semantic versioning (patch for fixes, minor for
   new features or behavior changes, major for breaking CLI changes) and
   confirm it with them. Check it is unused:

   ```bash
   git fetch --tags origin
   git tag -l 'v*'
   curl -s https://pypi.org/pypi/muse-cli/json | python3 -c 'import sys,json;print(sorted(json.load(sys.stdin)["releases"]))'
   ```

   Never reuse a version. `v0.1.0` exists as a GitHub-only tag from before
   PyPI publishing; PyPI releases start at 0.2.0.

2. **Check the working tree.** Be on `main`, up to date with `origin/main`,
   with no uncommitted changes (`git status -sb`). Git author identity must
   already be configured; never set it yourself.

3. **Bump the version** in `src/muse_cli/__init__.py`, nothing else.

4. **Build and smoke-test locally:**

   ```bash
   rm -rf dist /tmp/muse-release && python3 -m venv /tmp/muse-release
   /tmp/muse-release/bin/pip install -q build twine
   /tmp/muse-release/bin/python -m build
   /tmp/muse-release/bin/twine check --strict dist/*
   /tmp/muse-release/bin/pip install -q dist/*.whl
   /tmp/muse-release/bin/muse-cli --version   # must print the new version
   rm -rf dist
   ```

5. **Commit and push the bump.** This does not start Actions. Only when
   explicitly authorized, manually dispatch a build-only run and wait for it:

   ```bash
   git commit -am "Bump version to X.Y.Z"
   git push origin main
   gh workflow run publish.yml --ref main -f publish=false
   gh run list --workflow publish.yml --limit 1   # verify exact requested ref/run
   gh run watch <run-id> --exit-status
   ```

6. **Tag and push the tag.** Tags alone no longer publish. After explicit
   publication approval, dispatch on that exact tag with publish=true:

   ```bash
   git tag -a vX.Y.Z -m "muse-cli X.Y.Z"
   git push origin vX.Y.Z
   gh workflow run publish.yml --ref vX.Y.Z -f publish=true
   gh run list --workflow publish.yml --limit 1
   gh run watch <run-id> --exit-status
   ```

   The workflow checks the tag matches `__version__`, builds, uploads to
   PyPI via trusted publishing (no token needed), and creates the GitHub
   release with auto-generated notes and the built files attached. Do not
   create the GitHub release by hand.

7. **Verify it is live:**

   ```bash
   curl -s https://pypi.org/pypi/muse-cli/json | python3 -c 'import sys,json;print(json.load(sys.stdin)["info"]["version"])'
   rm -rf /tmp/muse-verify && python3 -m venv /tmp/muse-verify
   /tmp/muse-verify/bin/pip install -q --no-cache-dir muse-cli==X.Y.Z
   /tmp/muse-verify/bin/muse-cli --version
   ```

   PyPI can take a minute to show a new version; retry before assuming
   failure. Report the PyPI and GitHub release links when done.

### If something goes wrong

- **Failed before the PyPI upload step** (tag check, build, smoke test):
  nothing was published. Fix the problem, then ask the user before deleting
  and re-pushing the tag (`git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`).
- **Failed after the PyPI upload succeeded** (for example the GitHub release
  step): the version is live. Don't delete the tag. Fix the workflow, and
  create the missing GitHub release by hand if the user wants it.
- **A bad version reached PyPI:** PyPI never allows re-uploading the same
  version. Fix forward with a new patch version. The user can "yank" the bad
  one on pypi.org; don't try to delete it.

### Don't change without the user's say-so

PyPI trusts this repo through a trusted publisher tied to the workflow file
name `publish.yml` and the GitHub environment `pypi`. Renaming either breaks
publishing until the PyPI settings are updated to match.
