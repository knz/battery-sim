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

## Obstacles and Solutions

- 735371c also appended a note to `changelog/20260806-backend-tls-system-trust.md`,
  a changelog belonging to the TLS branch it was written on and absent here, which
  surfaced as a modify/delete conflict. Dropped that file from the pick and
  recorded the app.css rebuild in this changelog instead.

## Files Modified

- `app/static/app.css` — regenerated Tailwind output.
- `pyproject.toml`, `uv.lock`, `THIRD-PARTY-NOTICES.md` — `tzdata` dependency.
- `tests/test_packaging_metadata.py` — dependency-declaration and zone-resolution tests.
- `changelog/20260807-assembled-fixes.md` — this file.

## Current Status

Both commits cherry-picked. Awaiting further fixes from the user; not yet pushed
and no PR opened.
