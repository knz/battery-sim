# 2026-08-06 — Reproducible release builds

## Task Specification

Review feedback on publication readiness:

> `build-appimage.sh:466` fetches appimagetool from the rolling `continuous` tag, and
> PyInstaller is unpinned in both build paths. Neither blocks publication, but both make
> release builds non-reproducible.

Both points confirmed by reading the scripts. Scope: pin both build-tool inputs so a
release can be rebuilt from its tag. Not in scope: any change to shipped application code.

## High-Level Decisions

- **Pins stay confined to the packaging scripts** (user's explicit call). PyInstaller is
  not added to `pyproject.toml` — consistent with the existing rationale in
  `build-linux.sh`, which documents that PyInstaller is deliberately absent from the
  project metadata because it is a build tool, not an application dependency.
- **appimagetool pinned to release tag `1.9.1`** rather than `continuous`. `continuous` is
  re-published in place by upstream, so two builds weeks apart can silently get different
  binaries.
- **SHA256 recorded and verified after download.** Scoped claim: upstream publishes no
  digest or signature file for this release (checked — the release carries only the four
  per-architecture binaries), so the recorded hash pins the build to the exact bytes
  fetched on 2026-08-06. It detects drift and truncated downloads; it is *not* an
  independent verification against a publisher-signed manifest.
- **There are three install sites, not one.** An initial reading concluded that pinning
  `build-linux.sh:64` covered everything, on the grounds that `build-appimage.sh` reuses the
  onedir bundle rather than invoking PyInstaller itself. That holds for the two local build
  scripts but missed `.github/workflows/release.yml`, whose `desktop-bundle` matrix
  (macOS ×2, Windows) runs `uv pip install pyinstaller` directly — and whose comment
  documented the unpinned behaviour as pre-existing, cross-referencing `build-linux.sh`.
  Pinning only the shell script would have half-fixed the reported issue and left that
  comment pointing at a rationale no longer true. The workflow is pinned via a
  workflow-level `env: PYINSTALLER_VERSION`.
- **Two pin values, deliberately not one.** The workflow env var does not reach
  `build-linux.sh` (the Linux job shells out to it, and the script defaults its own
  variable), so the version appears in both files with comments in each pointing at the
  other. A single source would mean the workflow exporting into the script's environment,
  which makes the script's behaviour depend on its caller.

## Requirements Changes

- Initial request left the changelog target and the pin location open; user chose a new
  changelog file and packaging-script-confined pinning.

## Files Modified

- `changelog/20260806-reproducible-builds.md` (new) — this file.
- `packaging/build-linux.sh` — pinned the PyInstaller version at the build-venv install
  step, with the version in one overridable variable near the top.
- `packaging/build-appimage.sh` — replaced the `continuous` download URL with the `1.9.1`
  release tag, added a recorded SHA256 and a verification step after the fetch.
- `.github/workflows/release.yml` — added a workflow-level `PYINSTALLER_VERSION` and pinned
  the `desktop-bundle` install step to it; rewrote the comment that had recorded the
  unpinned behaviour as a known limitation.

## Rationales and Alternatives

- *PyInstaller in `pyproject.toml` (rejected, user's call):* would have let `uv.lock` carry
  the pin and kept one update site. Rejected to keep build tooling out of application
  metadata, preserving the separation the existing comment already argues for.
- *Vendoring appimagetool (rejected):* a 15MB binary in git for a tool used only at release
  time. The existing `APPIMAGETOOL=` override already covers the offline case.
- *Verifying by signature (not available):* would be preferable to a recorded hash, but
  upstream ships no signature or digest asset for this release.

## Obstacles and Solutions

- Upstream publishes no checksum file → recorded the hash of the fetched artifact and
  documented in the script comment exactly what that does and does not guarantee, so the
  guarantee is not overstated at the next reading.
- A third PyInstaller install site in `release.yml` was missed on the first pass → found by
  grepping the workflows before committing rather than after.
- The `desktop-bundle` matrix includes `windows-latest`, where `run:` defaults to PowerShell
  and a `"pyinstaller==$PYINSTALLER_VERSION"` shell expansion would have silently produced a
  bare `pyinstaller==` → used `${{ env.PYINSTALLER_VERSION }}`, which Actions expands before
  the shell runs, so it is shell-independent.

## Current Status

Both pins applied.

Verified:
- `bash -n` passes on both scripts.
- `pyinstaller==6.21.0` resolves on PyPI and accepts Python 3.12 (`>=3.8,<3.16`), which is
  the interpreter `build-linux.sh` creates the build venv with.
- The fetch/verify block was extracted and driven with a stubbed `curl` across four cases:
  cold fetch, valid cache (no re-download), stale pre-pin cache (re-fetches), and a
  corrupted download (exits 1, leaves nothing cached). All behaved as intended.

Verified end-to-end by CI run 31093496577 (`workflow_dispatch` on `worktree-packaging`),
which completed with conclusion `success`:

- `Linux AppImage`: success. The log shows `==> fetching appimagetool 1.9.1`, so the pinned
  tag was used rather than `continuous`, the checksum verification passed, and the resulting
  image built and ran (`28 passed` in the verification step).
- `macOS arm64`, `macOS x86_64`, `Windows`: all success. These invoke PyInstaller directly,
  so 6.21.0 is confirmed to build `battery-sim.spec` on all four platforms — the spec
  incompatibility this section previously flagged as an open risk did not materialise.
- The Windows pass also exercises the `${{ env.PYINSTALLER_VERSION }}` expansion: a shell
  variable would have produced a bare `pyinstaller==` and failed the install step.
- `Draft the GitHub release`: skipped, as intended on a non-tag ref.

An earlier dispatch (run 31085457462) failed in the `linux` job's verification step on a
stale `config.toml` assertion unrelated to these pins; that is fixed in the preceding commit
and traced in `changelog/20260806-appimage-state-assertion.md`.

Open, not decided: whether to also pin the `uv venv --python 3.12` interpreter to a patch
version, and whether the container-based build (noted as not-done in `build-appimage.sh`'s
portability comment) should land before publication. Both affect reproducibility; neither
was in this request's scope.
