# Closing A9: the glibc 2.39 floor is an accepted position, not open work

## Task specification

The user opened a worktree to work on packaging, recalling a leftover item about the AppImage
linking against the host glibc. On reviewing the record, the user decided they are **happy with
`ubuntu-24.04` and its glibc 2.39 floor for now**, and asked to "close the books".

Scope: update the changelog records so they stop advertising open portability work. **No code,
build script, or CI changes.** The engineering work (decoupling PyGObject from the host Python,
then lowering the floor) is explicitly not being done.

## Background — what A9 actually was

- **A9** (`20260805-desktop-decisions.md`) recorded that phase 4 built the AppImage natively
  rather than in Docker, to vary one thing at a time. Consequence: the artifact links against the
  host's glibc, so it requires 2.39 and will not run on Debian 12 or older.
- **U12** proposed building on `ubuntu-22.04` for a 2.35 floor. **Withdrawn the same day**, before
  any YAML was written, on two independent findings: `build-appimage.sh:105-116` hard-fails when
  the frozen interpreter's minor version differs from the system PyGObject's compiled `_gi`
  extension (22.04 ships Python 3.10, the bundle pins 3.12), and the 22.04 image deprecates
  2026-09-17.
- **U14** accepted `ubuntu-24.04` and the 2.39 floor, but deliberately kept A9 open, because
  lowering the floor was the whole purpose U12 had been chosen for.

So the blocker was never glibc — it was the `_gi` ABI coupling between the bundle's pinned Python
and the host's `python3-gi`.

## High-level decisions

### D1 — A9 is closed as accepted, not as fixed

Nothing about the artifact changes. The floor stays at 2.39. What changes is the record: A9 was
written when the floor was an accident of where the build ran, and its language ("portability is
the top follow-up", "not yet shippable to arbitrary users") reflects that. With the floor now a
deliberate product decision, that language overstates the urgency and misleads the next reader.

Rejected: leaving it as-is. Defensible — U14 already documents the acceptance — but it leaves two
records disagreeing about whether portability is open work.

### D2 — The PyGObject decoupling is recorded as dormant, not deleted

Option 3 from the CI changelog (install PyGObject into the build venv instead of copying the
host's) was the way out of the floor. With no floor to lower it buys nothing today, so it is not
being done. It is **not** struck from the record, because it remains the fix for a *different*
problem that will recur: every runner-label bump re-triggers the same ABI coupling, in the
opposite direction. 24.04 → 26.04 means glibc 2.43 and a newer system Python against the bundle's
pinned 3.12. Decoupling is what would make such bumps routine.

Stated as a hypothesis rather than a finding: that a 26.04 bump would trip the gate follows from
the same mechanism U12 tripped over, but no 26.04 build has been attempted here.

### D3 — The script headers are left untouched

`packaging/build-appimage.sh:46-49` and `.github/workflows/release.yml:42-44` already describe the
host-glibc behaviour accurately, and `release.yml` already says the floor "is accepted for now".
Both point at the changelog for current status, which is exactly where the change belongs. Editing
them would add churn without adding accuracy.

### D4 — The user-facing docs are already correct

`docs/en/install.md:91` and `docs/nl/installatie.md:94` both state the glibc 2.39 requirement.
They were written against the accepted position and need no change.

## What stays true and open

Recorded so closing A9 does not quietly absorb things it never covered:

- **Users on Debian 12 and older cannot run the Linux artifact.** This is now a product decision
  rather than an unresolved defect, but it is still a real limit, and the docs say so.
- **The runner label is GitHub's to retire.** When 24.04 goes, the replacement moves the floor up
  and re-raises the ABI pairing. See D2.
- **The other items in `20260805-ci-setup.md` §"Not addressed by this work"** — `dlopen`
  blindness in `check-appdir-closure.py`, the missing icon assets, PyInstaller unpinned — are
  untouched by this and stay open.

## Files modified

- `changelog/20260806-glibc-floor-accepted.md` — this file (new).
- `changelog/20260805-desktop-decisions.md` — A9 retitled and given a closing note; U14's heading
  corrected from "A9 stays open".
- `changelog/20260805-ci-setup.md` — the "Not addressed by this work" entry and the recommendation
  paragraph updated to point at this decision.
- `changelog/20260805-desktop-packaging.md` — §13.11 and §13.12 entries that called the container
  build the top follow-up, annotated with the outcome.

## Current status

Record updates complete. No code changes. A9 is closed as accepted; the decoupling work is
dormant with its trigger condition written down.
