# 2026-08-06 — Fix the AppImage state assertion

## Task Specification

The `linux` job of `release.yml` failed on run 31085457462 (dispatched from
`worktree-packaging` to check the build-tool pins). The build itself succeeded; the failure
was in the verification step, 1 failed / 27 passed:

```
FAILED tests/test_appimage.py::test_the_appimage_serves_over_http
AssertionError: the AppImage did not write its state to .../xdg/battery-sim
```

Fix the test. Ordering requirement from the user: this fix goes FIRST in history, with the
packaging change rebased on top.

## High-Level Decisions

- **The failure is a stale assertion, not a packaging regression.** Traced before changing
  anything:
  - `tests/test_appimage.py:338` asserted `config.toml` exists under the data dir.
  - `app/config.py` states the app "no longer reads or writes `config.toml` at all" — the
    `Config`/`load()` limb went when feature requests moved to GitHub issues.
  - The removal is commit `fb4a10c`, which is NOT an ancestor of `2ad56de` (the last green
    release run). So run 31085457462 was the first release build to execute this assertion
    against code that no longer writes the file.
  - The same assertion is present on `master` at the same line; the packaging branch touched
    neither `tests/` nor `app/`.
- **Mirror the existing precedent rather than invent a marker.** `tests/test_packaged.py:188`
  hit exactly this and moved to `desktop.lock`, with a comment recording why. That sweep
  missed `test_appimage.py`. Using the same file keeps the two packaging tests consistent.
- **`desktop.lock` is a defensible marker:** `app/desktop.py:778` writes it unconditionally
  in the launcher path, which is what the AppImage runs, so its presence proves real state
  landed in the directory rather than the directory merely having been created.
- **Added the stronger check too.** `test_packaged.py` pairs its lock assertion with a
  "no state under the bundle" rglob; the AppImage test asserted only the positive case. Added
  the negative, since the AppImage mount is read-only and writing there is the failure the
  docstring says this test exists to catch.

## Requirements Changes

- Original plan offered fixing the test on `master` or in a separate PR. User chose: commit
  on this branch, then reorder via rebase so the test fix precedes the packaging change.

## Files Modified

- `tests/test_appimage.py` — `config.toml` → `desktop.lock`; added the bundle-stray check;
  comment recording why the marker changed.
- `changelog/20260806-appimage-state-assertion.md` (new) — this file.

## Rationales and Alternatives

- *Drop the state check entirely (rejected):* the docstring names state placement as one of
  two things this test adds over the others. Removing it would silently narrow coverage.
- *Assert only that the directory exists (rejected):* `data_dir()` calls `mkdir` itself, so
  the directory exists whether or not anything was written. That assertion could not fail.
- *Fix on `master` first, then rebase (offered, not chosen):* user opted to keep it on this
  branch, ordered first.

## Obstacles and Solutions

- Three prior release runs passed, which argued against "pre-existing" → resolved with
  `git merge-base --is-ancestor`, showing the `config.toml` removal landed after the last
  green run.

## Current Status

Test fixed and committed; history reordered so this precedes the packaging commit.

Verified by CI run 31093496577 (`workflow_dispatch` on `worktree-packaging`): the `linux`
job reports `28 passed`, up from `27 passed, 1 failed`, and the log shows
`test_the_appimage_serves_over_http PASSED` rather than a skip — confirming the assertion
executed against a real built image rather than being skipped for want of one. The added
bundle-stray check passed in the same run.
