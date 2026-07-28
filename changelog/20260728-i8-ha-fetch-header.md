# I8 — `ha_fetch.js` file header audit

## Task specification

From `followups.md` finding **I8**: the file header comment at the top of
`app/static/ha_fetch.js` had drifted from the code, independently of the workspace
restructure. Phase 1 corrected only the two lines that directly named the re-rooted
path; the surrounding narrative was left largely untouched. A full pass over the
header against the current code is still owed.

Scope: read the header (lines 1–117), read the code it claims to describe (the whole
1143-line file plus the templates it contracts with), list every divergence, then
correct the header. No behaviour change.

## Divergences found (audit, before any edit)

Verified against `app/static/ha_fetch.js` @ 1143 lines, `app/templates/*.html`,
`app/main.py`.

**A. `_panel_data.html` no longer exists.** The header names it twice — as the file
carrying the slot rows (line 20) and as the renderer of `data-ingest-ws` (line 100).
`ls app/templates/` shows no such file; the roster and its `data-*` contract live in
`_data_roster.html`, included by `workspace_data.html`. Confirmed also by
`_panel_results.html:57` and `workspace_results.html:31`, which both refer to it in the
past tense.

**B. "panel ①" is now a screen.** The header says a successful fetch reloads "so panel
① re-renders" (line 57) and that the drawer lives "in workspace_data.html" (line 22) —
the second is right, the first keeps the pre-split vocabulary.
`workspace_data.html`'s own header records the change: "Panel ① of §2.2, promoted to a
screen of its own." Same for the setup-band comment further down the file (line 559),
which says "panels ② and ③ keep showing the STORED answers" — those are now the params
and results screens.

**C. `_setup_band.html` is deleted.** The mid-file setup-band comment (line 553) says
the two answers "live as radio groups in `_setup_band.html`". They live in
`_data_household.html`; `_panel_params.html:70` and `workspace_results.html:30` both
record the band's deletion.

**D. The connection-modal reference is correct but the section header above it is
stale.** Line 106 introduces the last block as "User actions on the connection card"
— the card was removed and its controls moved into `#ha-config-dialog`, which the
header itself explains at lines 11–14 and again at 159–161. Two names for one thing,
one of them the removed one.

**E. The `POST …/slot/{slot}/load` parenthetical is accurate and worth keeping.**
Checked: the route still exists (`app/main.py:1388`), and no browser code path calls
it — `grep` finds no reference in `app/static/`. The header's claim (lines 30–32) holds.

**F. Two phase-1 "this used to say X" apologies are now noise.** Lines 30–32 and
49–51 explain what an earlier version of the comment said and why it was corrected.
That is changelog content, not header content; once the header is right, a reader does
not need the history of the header. (The route note in E is different — it documents a
live route the browser deliberately does not call, which is a real fact about the code.)

**G. `updateSlotButton`'s doc mentions a "[change] hint" the code does not touch.**
Line 1052 says "The [change] hint is kept if present" — the function only rewrites
`.slot-source-label`, so the claim is true but describes an absence. Minor; not part of
the file header proper.

**H. An orphaned comment inside the file** (not the header, found while reading):
`mappedSlots`'s docstring at lines 548–549 is separated from `mappedSlots` (line 615)
by the whole setup-band block, which was spliced in between. The comment reads as if it
described `setupAnswer`.

Not divergences (checked and correct): the localStorage generation-reconcile narrative,
the global-connection vs per-workspace-slot-store split, the discard of the
pre-workspaces `ha.slots` key, the Test/Fetch descriptions, the transactional draft
model, and the shared `#slot-info-dialog` / `#pending-dialog` pattern.

## Files modified

- `app/static/ha_fetch.js` — comments only, 20 lines changed. No executable statement
  was touched (`node --check` passes; the diff is entirely inside comment blocks).
- `changelog/20260728-i8-ha-fetch-header.md` — this file.
- `followups.md` — I8 marked DONE.

## What was changed

1. Stale names corrected: `_panel_data.html` → `_data_roster.html` (both sites, A);
   "panel ①" → "the configure-data screen" / "the slot roster" (four sites, B — two of
   them mid-file, found by a grep sweep after the header pass); `_setup_band.html` →
   `_data_household.html` (C); "User actions on the connection card" → a heading that
   names the modal and the roster button (D).
2. The two self-referential "this used to say X" paragraphs dropped (F). The route
   parenthetical inside the first was KEPT and reworded (E): that
   `POST /w/{id}/data/slot/{slot}/load` exists and the browser deliberately never calls
   it is a live fact about the code, not a fact about the comment's history.
3. `mappedSlots`'s orphaned docstring moved back onto `mappedSlots` (H). It had been
   separated from its function by the setup-band block and read as if it documented
   `setupAnswer`.
4. G (the `[change]` hint clause) left as-is — re-read in context, it is accurate and
   tells a reader why the function rewrites only `.slot-source-label`.

Two comments still name removed things — `#ha-connection` (line 130) and
`_setup_band.html` (line 549) — deliberately: both name them AS removed, which is the
information a reader needs when the surrounding code still carries their shape.

## Verification

- `node --check app/static/ha_fetch.js` passes.
- grep sweep for `_panel_data|_setup_band|panel ①|connection card` returns only the two
  intentional as-removed mentions above.
- `uv run pytest -q`: 1210 passed, 2 skipped (the known live-HA suite), 88s.

## Status

Done.
