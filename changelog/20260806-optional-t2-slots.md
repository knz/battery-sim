# 2026-08-06 — Make T2 consumption/production slots optional

## Task Specification

The data slots for T2 (consumption / production) are currently marked as
"mandatory". Some household setups do not have these signals available, so the
requirement is too strict. The request is a UI tweak: stop treating these T2
slots as mandatory.

Working in git worktree `.claude/worktrees/ui-tweaks`, branch
`worktree-ui-tweaks`, branched fresh from `origin/master`.

Note: the branch name coincides with an earlier merged PR branch
(`knz/worktree-ui-tweaks`, merged in 9c1b1d4). This is a new branch off
`origin/master` and does not carry that earlier work.

## User prompts (verbatim)

Recorded per `docs/specs/AGENTS.md`, since spec files may be touched.

1. "create a worktree for ui tweaks"
2. "the data slots for T2 (consumption/production) are currently marked as
   'mandatory'. however some setups may not have them."

Clarification asked and answered: the slots meant are `grid_import_t2` /
`grid_export_t2` (night-tariff registers). Depth of change: investigate first,
then propose.

## Investigation findings

The runtime already treats T2 as optional. The "mandatory" appearance comes
from two stale artefacts, not from live behaviour.

Already correct — no change needed:

- `app/domain/series_vocab.py:73,75` — both T2 slots are `"optional"`, with the
  comment `# "expected" — see §4.1 note 4`.
- `app/data_screen_view.py:88-95,130-135` — the wizard's Next gate requires only
  `grid_import_t1` / `grid_export_t1` (plus PV/battery slots when declared). A
  15-line comment already records that the spec's "both T1/T2 register pairs"
  parenthetical is wrong and the code is right.
- `app/workspaces.py:49-52,341-344` — card completeness keys off T1 only.
- `app/ingest_ws.py:173-188,228-250` — ingest validates name + kind only; it
  never reads `requirement`.
- `app/domain/reconcile.py:104-116,189-198` — T1/T2 are folded together; an
  unmapped register contributes nothing. Only an entirely absent pair fails.
- `tests/test_workspace_data.py:1218-1239` —
  `test_an_absent_t2_register_pair_does_NOT_block` already asserts the opposite
  of "mandatory", and is framed as a regression guard against a well-meaning
  "the spec says both" edit.

`SlotSpec.requirement` is presentation-only: its sole consumers are
`app/data_view.py:196` and the marker in `app/templates/_data_roster.html:90-92`.

The two genuine defects:

1. `app/sample_data.py:195,197` hard-codes `"req": "required"` for the two T2
   rows in the static demo roster, so the sample screen paints `●` where the
   live screen paints `○`. The demo dict is hand-built rather than derived from
   `SERIES_SLOTS` (it does single-source `info` via `_info_for`, but not `req`).
2. `docs/specs/02-ux-wireframes.md:246,248` and `:558,560` draw T2 with the
   filled `●` (required) marker, contradicting §4.1 note 4 in
   `docs/specs/05-data-formats.md:52-57`, which states T2 is *expected* rather
   than *required* precisely "because the app runs without them".

The wireframe and the sample data agree with each other, so the sample roster
is plausibly a faithful copy of the stale wireframe rather than an independent
typo.

Also noted: code has no `"expected"` requirement level; the spec's *expected*
collapses to `"optional"`, and the roster renders only three markers
(`●` / `◐` / `○`).

## High-Level Decisions

- Treat this as correcting two stale copies to match the already-correct
  runtime, not as loosening a live constraint. No validation or gating changes,
  and `series_vocab.py` is untouched.
- Derive the demo roster's `req` from `SlotSpec` rather than editing the two
  literals. Hand-copying is what allowed the drift, and `info` was already
  single-sourced the same way via `_info_for`; a parallel `_req_for` closes the
  remaining hand-copied field.
- Leave the non-blocking T2 diagnostic (`data_view.py:340-358`, "import T1
  mapped, active · T2 not mapped") alone. §4.1 note 4 explicitly wants a missing
  second register reported rather than silently accepted, and it does not gate
  the run.
- Do not add an "expected" requirement level. The roster renders three markers;
  spec-*expected* maps to `optional`, which is what the code already does.

## Rationales and Alternatives

- Alternative considered: change the two `"req": "required"` literals in
  `sample_data.py` to `"optional"`. Rejected as the primary fix — it corrects
  today's symptom but leaves the field hand-copied and free to drift again.
- Alternative considered: relax `grid_import_t1` / `grid_export_t1` as well.
  Not done — nothing in the request pointed at T1, and §4.1 note 1 has
  single-tariff households filling the `_t1` slots and leaving `_t2` empty, so
  T1 is the slot such setups do have.

## Obstacles and Solutions

- The word "mandatory" appears nowhere in the app; the only hit in the repo was
  about timestamp offsets in §4.1's column rules. Located the real mechanism by
  the `required`/`conditional`/`optional` vocabulary instead.
- "T2 (consumption/production)" did not match the code, where T1/T2 are
  day/night tariff tiers of the grid registers, and consumption/production are
  workspace-card roles that collapse each pair to its T1 slot. Confirmed with
  the user that the T2 registers were meant.

## Files Modified

- `changelog/20260806-optional-t2-slots.md` — created; this file.
- `app/sample_data.py` — added `_req_for()` next to `_info_for()`; all ten demo
  mapping rows now take `req` from it instead of a literal; updated the roster
  comment to record why the field is derived.
- `docs/specs/02-ux-wireframes.md` — four T2 marker cells `●` → `○` (HA roster
  and CSV variant); reworded §2.2's `has_pv` bullet, which described Solar
  production as carrying "the same ● as the grid registers" — true only of the
  T1 registers now.
- `tests/test_data_summary.py` — added
  `test_sample_roster_requirement_matches_the_vocabulary`, asserting the demo
  roster covers exactly `SLOT_BY_NAME` and that every row's `req` equals its
  `SlotSpec.requirement`, plus explicit pins on the four grid registers.

## Verification

- `tests/test_data_summary.py` + `tests/test_workspace_data.py`: 138 passed.
  The latter includes `test_an_absent_t2_register_pair_does_NOT_block`, the
  pre-existing guard on the runtime behaviour.
- A full-suite run passed (1423 passed, 25 skipped) before the test was added;
  subsequent runs were narrowed at the user's request, since the full suite
  includes long benchmarks.
- Rendered markers confirmed directly: the demo roster now paints
  `● T1 / ○ T2` for both import and export.

## Current Status

Complete. Not committed — the worktree branch `worktree-ui-tweaks` holds the
changes uncommitted, pending review.
