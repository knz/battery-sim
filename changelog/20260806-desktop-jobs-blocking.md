# Making the macOS and Windows release jobs blocking

## Task specification

The user asked what benefit `continue-on-error: true` provides on the `desktop-bundle` matrix in
`.github/workflows/release.yml`, given that release packaging has since been confirmed to work.
After a terse summary of the options, the user chose **option 1: remove the flag outright**.

Scope: remove `continue-on-error: true` from the `desktop-bundle` job and update the surrounding
comments. No changes to signing, the spec, or the release-drafting logic.

## Background — what the flag was and was not doing

The flag governs one thing: whether a failed build reddens the workflow run. It does **not** gate
publishing. Verified by reading the pipeline:

- Nothing runs `codesign --verify`, `spctl`, `notarytool` or `signtool`. Signature state is never
  consulted, so unsigned artifacts publish today and continue to.
- `codesign_identity=None` / `entitlements_file=None` (`packaging/battery-sim.spec:275-276`) tell
  PyInstaller not to sign with a Developer ID. That is a no-op, not a failure path.
- The `release` job's condition is `always() && needs.linux.result == 'success' &&
  startsWith(github.ref, 'refs/tags/v')` — independent of the flag.

So the flag's stated protection (a broken macOS build must not withhold a working Linux release)
was already provided by the `always()` guard. It was redundant.

## High-level decisions

### D1 — Remove the flag rather than tighten per-platform or add an artifact check

Options presented were: (1) remove outright, (2) remove per-platform starting with Windows, (3)
keep the flag but fail the release job on a missing artifact, (4) leave as-is. **User chose (1).**

This matches the intent already written into the workflow header, which said each platform should
become blocking "once it has gone green once and its output has been looked at", and that jobs
left amber indefinitely "carry no information".

### D2 — Verified against real runs before flipping, not against the header's claim

The header cited run 31032747998 (2026-08-05) as evidence all three passed. That run predates the
macOS `BUNDLE(...)` block and the Windows VERSIONINFO work, so it was stale evidence for the
current configuration.

Checked per-job conclusions, because a top-level `success` is exactly what `continue-on-error`
manufactures and would have masked an amber job:

| run | date | Linux | macOS arm64 | macOS x86_64 | Windows |
|---|---|---|---|---|---|
| 31094839305 | 2026-08-06 | success | success | success | success |
| 31093496577 | 2026-08-06 | success | success | success | success |

Both `workflow_dispatch` runs, so `Draft the GitHub release` shows `skipped` — its condition
requires a `v*` tag ref. That is expected and not a failure.

### D3 — `fail-fast: false` is kept

Independent of `continue-on-error`. It ensures one platform's failure does not cancel the other
two mid-build, so a single release run still reports the state of all three. Removing it would
mean the first failure hides the others' status.

### D4 — The "(unfinished)" job labels are kept

The matrix labels read `macOS arm64 (unfinished)` and so on. They stay accurate: signing and a
Windows installer are still missing. Blocking-on-build-failure and finished-packaging are separate
properties, and the label tracks the latter.

## What this does and does not change

**Changes:** a broken macOS or Windows build now fails the workflow run. A tag push shows red
instead of green. That is the visibility being bought.

**Does not change:**

- Releases still draft. The `always() && needs.linux.result == 'success'` guard is untouched, so a
  Linux-only release still goes out if a desktop job dies.
- Signing. macOS ships an ad-hoc-signed `.app` with no Developer ID or notarization; Windows ships
  an unsigned ZIP. First-run Gatekeeper and SmartScreen warnings remain expected and are
  documented in `docs/*/security-warnings.md`.
- Releases remain drafts, requiring a human to publish.

## Residual risks, recorded rather than discovered later

- **Runner-label retirement now breaks the run.** `macos-26-intel` has a scheduled end of life
  when `macos-15` retires in Fall 2027. Previously that would have failed amber; now it fails red.
  That is the intended trade, but it means an external deprecation can redden a release.
- **PyInstaller is unpinned** in both this workflow and `build-linux.sh`, so a bad upstream release
  can now break a tag run rather than being absorbed. Pre-existing and listed as open in
  `changelog/20260805-ci-setup.md`; this change raises its visibility.
- **Nothing checks that a release carries every expected asset.** `fail_on_unmatched_files: false`
  means a release can still arrive with fewer downloads than the README promises. Option (3) from
  the discussion would address this and was not taken.

## Files modified

- `changelog/20260806-desktop-jobs-blocking.md` — this file (new).
- `.github/workflows/release.yml` — removed `continue-on-error: true` from `desktop-bundle`;
  rewrote the header section and the two comments that described the jobs as amber.

## Current status

Complete. Flag removed, comments updated to match. Verified green on runs 31094839305 and
31093496577 before the change; the change itself is not yet exercised by a run.
