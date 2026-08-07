# Assembled fixes branch

## Task Specification

Collect independent fixes onto a single branch (`worktree-fixes`, worktree
`.claude/worktrees/fixes`, branched fresh from `origin/master`) so they can be
reviewed and merged together, separately from the feature branches where they
were originally written.

The user names the commits to pick; this file records what landed and why.

## Contents

### 1. Rebuild app.css (cherry-picked from 735371c)

`app/static/app.css` is a committed Tailwind build artefact and CI has a
freshness job that regenerates it and fails on any difference. Three commits
inside the already-merged PR #16 (d212314, 9bb3f4d, 2effe3f) changed template
classes without regenerating it, so the job failed for every branch built on top
of master. The regenerated output is additive: daisyUI's `.tooltip` rules and one
`.h-48` utility.

### 2. Ship tzdata (cherry-picked from 90cd91c)

`app/i18n.py` resolves `ZoneInfo("Europe/Amsterdam")` at import, and the
PyInstaller spec imports `app.i18n` at build time. Windows ships no system tz
database and the `tzdata` PyPI package was undeclared, so the Windows Release job
died with `ZoneInfoNotFoundError` before PyInstaller started. Broken since
bf562f5 (PR #16). Adds `tzdata>=2026.3` to `[project.dependencies]`
unconditionally, with `uv.lock` and `THIRD-PARTY-NOTICES.md` following, plus two
tests in `tests/test_packaging_metadata.py`.

Full detail is in the commit's own changelog,
[20260806-windows-tzdata.md](20260806-windows-tzdata.md), which came across with
the pick.

## Obstacles and Solutions

- 735371c also appended a note to `changelog/20260806-backend-tls-system-trust.md`,
  a changelog belonging to the TLS branch it was written on and absent here, which
  surfaced as a modify/delete conflict. Dropped that file from the pick and
  recorded the app.css rebuild in this changelog instead.
- 90cd91c was written on top of that same TLS branch, so all four of its files
  conflicted against master. Resolved by keeping only the tzdata half and dropping
  the `truststore` dependency, its notices row, and its hidden-import test, none of
  which were requested here. `uv.lock` was regenerated with `uv lock` (it added
  tzdata alone) and `THIRD-PARTY-NOTICES.md` with its generator script rather than
  hand-merged; the generator's `--check` gate passes and the packaging-metadata
  suite is green (32 passed).
- Two in-tree references pointed at the TLS branch's changelog filename; both now
  point at this branch's files.

## Files Modified

- `app/static/app.css` — regenerated Tailwind output.
- `pyproject.toml`, `uv.lock`, `THIRD-PARTY-NOTICES.md` — `tzdata` dependency.
- `tests/test_packaging_metadata.py` — dependency-declaration and zone-resolution tests.
- `changelog/20260807-assembled-fixes.md` — this file.

### 3. Assert the release-only properties on every push (3372fbb, c1ceffa)

The packaged test files are gated on env vars only the Release workflow's Linux job
sets, so ordinary CI collects 23 tests and skips them all — and Release is
dispatch-only. Four properties were therefore asserted nowhere else. Seven tests
added (all additions), and one page-rendering CLDR probe removed once its two
halves were covered separately. Detail in
[20260807-packaged-test-coverage-implementation.md](20260807-packaged-test-coverage-implementation.md),
with the analysis and review it followed from in the two files beside it.

## Current Status

Five commits on `worktree-fixes`, pushed, PR #17 open against master.

**Release run 31187584989 (on c1ceffa) is fully green** — Linux AppImage, Windows,
macOS arm64 and macOS x86_64 all succeeded, with the Linux verification step at
28 passed / 0 failed. This is the first green Release run since PR #16 merged;
the three regressions that branch introduced (stale app.css, missing tzdata, and
the babel probe) are each addressed here.

Two claims moved from reasoned to observed by that run and its predecessor
(31186803969): the Windows build succeeds with `tzdata` declared, and the
in-bundle path `_internal/babel/locale-data` is what the new packaged test
expects. Both had been flagged as inferred-from-hook-sources.

Still open, and out of scope throughout: the packaging jobs remain dispatch-only,
so a packaging regression still surfaces at release time rather than on the push
that causes it. That is CI policy.
