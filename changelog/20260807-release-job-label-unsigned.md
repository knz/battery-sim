# Renaming the desktop job labels from "(unfinished)" to "(unsigned)"

## Task specification

The user asked what "(unfinished)" means on the desktop release job labels, then asked to change
the label to "(unsigned)". Separately, the user asked about the pin status of PyInstaller.

Scope: the three matrix labels in `.github/workflows/release.yml`, plus the surrounding comments
that explain the old wording. No behavioural change to any job.

## Background — what "(unfinished)" was tracking

The workflow header and `changelog/20260806-desktop-jobs-blocking.md` (D4) both record that the
label tracked *packaging* gaps, not job reliability. At the time it was written those gaps were:

- macOS: no Developer ID signature and no notarization (`codesign_identity=None` in the spec);
  PyInstaller applies an ad-hoc signature only, which is what lets the binary run on arm64 at all.
- Windows: unsigned, and shipped as a ZIP of an onedir tree with no installer.

The jobs stopped being `continue-on-error` on 2026-08-06, so "unfinished" already did not mean
"unreliable" — the workflow says so directly at line 315.

## High-level decisions

### D1 — "(unsigned)" over "(unfinished)"

"Unfinished" is vague enough that a reader plausibly takes it to mean the job itself is flaky,
which the 2026-08-06 change made false. "Unsigned" names the actual gap. The workflow's own
explanatory comment already glossed the old label as "unsigned, and on Windows without an
installer", so the new label states what the comment had to explain.

### D2 — Accept that the label no longer covers the Windows installer gap

"(unsigned)" is narrower than "(unfinished)": it does not signal the missing Windows installer.
That gap is still recorded in the header and in `docs/*/security-warnings.md`; a matrix label is a
poor place to carry two independent facts, and signing is the one that affects every platform in
the matrix. Recorded here so a later reader does not conclude the installer gap was closed.

### D3 — Past changelogs are left alone

`changelog/20260806-desktop-jobs-blocking.md` D4 argues for keeping "(unfinished)" and lists
PyInstaller as unpinned. Both statements were true when written. Changelogs are a record of their
moment, so they are not rewritten; this file supersedes them.

## PyInstaller pin status — answering the side question

Pinned at `6.21.0`, in two places, deliberately duplicated:

- `.github/workflows/release.yml:141` — `PYINSTALLER_VERSION: "6.21.0"`, consumed at line 366.
- `packaging/build-linux.sh:45` — `PYINSTALLER_VERSION="${PYINSTALLER_VERSION:-6.21.0}"`, used at
  line 72.

The desktop-bundle jobs invoke PyInstaller directly rather than through `build-linux.sh`, which is
why the pin is repeated rather than shared. The workflow header (line 95) is accurate;
`changelog/20260806-desktop-jobs-blocking.md:86-88`, which lists PyInstaller as an open unpinned
risk, is stale — the pin was added after that file was written.

**Open, not addressed here:** the two pins are kept in agreement only by a comment
(`release.yml:358`). Bumping one without the other would give Linux and the desktop platforms
different PyInstaller versions with nothing to catch it.

## Files modified

- `changelog/20260807-release-job-label-unsigned.md` — this file (new).
- `.github/workflows/release.yml` — three matrix labels renamed; header section title, the
  paragraph glossing the old label, and the section divider comment reworded to match.

## Current status

Complete. Labels and comments changed; no step, condition or runner touched. The rename changes
the job names GitHub displays, so in-flight runs started before the change keep the old names and
any saved links to a job by name will not resolve.
