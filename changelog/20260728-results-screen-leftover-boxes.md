# 20260728 — Grid connection and Pricing left behind on the results screen

Follow-up defect found after Phase 5 of the workspaces restructure
(`changelog/20260726-workspaces-implementation-plan.md`, spec `specs/20-workspaces-ux.md`).

## Task specification

User's report, verbatim:

> after phase 5 I see the pricing panel still in the results page (alongside the battery
> parameters, under charge/discharge) although we've "moved" it to the separate "update
> workspace" screen.

## What was found

Confirmed, and it is not limited to Pricing. `app/templates/_panel_params.html` still renders
**two** boxes that §2′.1's ownership table assigns to the edit-workspace screen:

| Box | Where it is drawn now | Where §2′.1 (spec lines 39–40) puts it |
|---|---|---|
| Grid connection (`grid.phases`, `grid.fuse_a`, the two limit overrides) | Results → advanced pane → **Battery** tab | Edit workspace |
| Pricing (`pricing.contract`, markup, tax, VAT, feed-in α/β, TLK, dal window, degradation) | Results → advanced pane → **Charge & discharge** tab, below the overlap warning | Edit workspace |

Both are genuine duplicates rather than divergent copies: `workspace_edit.html` already draws
the connection as a single `grid.connection` preset dropdown (§2′.4) plus an advanced pane, and
already draws the full Contract box with the same `pricing.*` paths. So the same stored fields
are editable from two screens, and the results screen's copy is the one the spec removed.

§2′.6's wireframe corroborates: its Battery tab lists SoC, charge/discharge power, round-trip
efficiency, standby draw, initial SoC and the coupling readout — no connection box — and its
Charge & discharge tab is named as §2.3 boxes 4 and 5 with the overlap warning below, with no
sixth box.

**Why it survived phases 3–5.** Phase 4.2 reshaped this file from a five-box panel into
capacity-first + three tabs, and the reshape moved the boxes it kept into tabs without removing
the two the spec had reassigned. The file's own header comment says "Everything below the
capacity field is UNCHANGED IN CONTENT", which describes what happened accurately — the
omission is that two of those contents should not have been kept at all.

## What the codebase already has in place for the removal

The section-marker machinery was split during phases 3–4 in anticipation of exactly this
split, so the destructive-clear hazard the file warns about is already handled:

- `params_view._sections_for` emits `grid`, `pricing` and `pricing_advanced` from a config,
  and `_section(form, …)` gates each checkbox read on the submitting screen having drawn it.
- `pricing` names the economic-guard checkbox specifically; `pricing_advanced` names
  `dal_weekends`. The edit screen already claims only the latter. This split exists because
  one marker over both checkboxes made a truthful edit-screen submission clear the guard.
- `guard_was_submitted` additionally requires the server's own `stored.simulate_cost`, so an
  over-claiming `sections` field cannot clear a retained guard.

The economic guard is the one control that complicates a clean cut: it is a `policy.*` field
(so it belongs on the results screen by §2′.1's row "Battery, topology, policies") but it is
drawn today inside the Charge & discharge tab's discharge box and gated on `cfg.simulate_cost`
— it is *not* part of the Pricing box being removed. Verified by reading the template: the
guard sits at `_panel_params.html` ~line 506, inside the discharge card, above the Pricing
box's comment block at ~line 532. So removing the Pricing box does not touch it, but the
`pricing` marker that gates its parse must therefore **stay** on the results screen even after
the Pricing box goes.

## Files inspected

- `app/templates/_panel_params.html` — the two leftover boxes, lines ~264–305 (Grid connection)
  and ~532–~700 (Pricing, including the feed-in preset `<select>` and its JS at ~661–671).
- `app/templates/workspace_edit.html` — confirms both destinations already exist.
- `app/params_view.py` — `_sections_for` (~1047), `parse_form`'s section gates (~360–400),
  `guard_was_submitted` (~425), `_pricing_view`, the `grid` view block (~851) and
  `_FIELD_TABS`.
- `app/templates/workspace_results.html` — the feed-in preset JS lives here (~661), not in the
  partial, so it is orphaned by the removal.
- Tests referencing the affected paths: `tests/test_smoke.py:487-488,849`,
  `tests/test_workspace_results.py:258-269`, `tests/test_params_view.py` (many — most exercise
  `parse_form` directly and are unaffected by a template change).

## Current status

**Investigation complete; nothing changed yet.** Per AGENTS.md the implementation plan is
presented for approval before any code change. Open decisions to settle with the user are
listed in the plan message: whether the capacity-first Battery tab keeps a read-only
connection/contract readout with a link to the edit screen, and what happens to the feed-in
preset JS and the `_pricing_view` view-model code that no template would then consume.

## Decisions taken (user, 2026-07-28)

1. **Remove both boxes entirely** — no read-only connection/contract readout on the results
   screen. Cleanest reading of §2′.6, whose wireframe shows neither. The home-screen card
   badges (§2′.2) and the edit screen already report contract and connection.
2. **Delete the now-unused view code**, with the user's caveat "double check they are not used
   by the update workspace screen". Checked: `workspace_edit_view.py` builds its own view model
   and imports only `_fmt`, `field_messages`, `issue_message`, `_PCT_FIELDS`, `_frac_to_pct`
   from `params_view`. Its single mention of `_pricing_view` is a prose comment citing it as
   precedent for pending-affordance keys, not a call. So `_pricing_view` and the `grid` view
   block are results-screen-only and safe to delete.
3. **Add a link from the Cost savings section to the edit screen**, with an ⓘ explaining that
   is where contract and pricing parameters are updated.

### The gap decision 3 fills

`/w/{id}/edit#contract` was already linked from two places — the blocked cost toggle's ⓘ
dialog and §2.4's invitation box — but **both render only when cost simulation is OFF**
(`{% if cost_blocked %}` inside `{% if not results.cost %}`). With cost ON, which is exactly
when euro figures are on screen and the removed Pricing box used to be the way to adjust the
rates behind them, nothing on the results screen led to the contract. Removing the box without
this would have left that state with no route to the rates at all.

The existing comment in `_panel_results.html` argues that two buttons to one destination are
"two answers to one question". That reasoning is preserved rather than broken: the three call
sites are **mutually exclusive by cost state** — invitation box and toggle dialog when cost is
off, this button when it is on. Recorded in the template comment so a later reader does not
"fix" the apparent duplication.

Judgement call on which ⓘ: the **shared `.slot-info-btn`** title-and-body dialog, not the
blocked-toggle's bespoke one. The bespoke dialog exists because it carries an action button;
here the action is the adjacent link, so a second dialog carrying the same link would be the
duplication the comment warns about.

## Current status

Plan approved by the user. Implementation in progress.

## Obstacle: two controls were lost, not moved

The removal exposed that the edit-workspace screen's Contract box (§2′.4) is not a complete
superset of the Pricing box it replaces. Two affordances existed ONLY in the deleted box:

1. **The terugleverkosten mode selector** (`pricing.tlk_mode`: flat / tiered). The edit screen
   renders `pricing.tlk_eur_per_kwh` with a hardcoded "flat, per fed-in kWh" label and no
   selector at all. The TIERED radio was a PENDING control carrying `data-feature-key=
   "pricing_tlk_tiered"` — a key still registered in `app/features.py` and still accepted by
   the interest route, but now rendered by nothing. Two tests in `test_params_route.py`
   asserted that pairing.
2. **The feed-in (α, β) preset select** (§6.5's three-row table). The edit screen exposes α and
   β as bare numeric fields. The select was only ever a way of TYPING the two fields — no
   stored value — so nothing persisted is affected, but a user who recognised "Legal minimum —
   50 percent of the bare price" now has to know the numbers.

Neither is a consequence the user asked for: the instruction was to remove a duplicate, and
these were not duplicated anywhere. Both are surfaced rather than silently dropped.

**Decision: rebuild `tlk_mode` on the edit screen, leave the α/β presets as a follow-up.**
The reasoning differs between the two. The tlk selector's absence leaves a registered feature
key with no control — the pending-affordance contract in §2.1 is that an unbuilt feature is
VISIBLE and disabled, and a key nothing renders breaks it in the direction the spec explicitly
argues against ("a vanished option leaves the user unable to tell whether the app has the
feature at all"). The presets are a typing convenience over two fields that both still render
and both still round-trip; their absence costs discoverability, not capability, and rebuilding
the select is an edit-screen design question rather than part of undoing this duplication.

## Files modified

**Templates**
- `app/templates/_panel_params.html` — deleted the Grid connection box and the Pricing box;
  dropped `num_field`'s now-callerless `cost=` tint parameter; rewrote the header comment,
  which claimed "everything below the capacity field is unchanged in content".
- `app/templates/_panel_results.html` — added the `[ Edit contract & rates → ]` link plus its
  shared-dialog ⓘ under the Cost savings divider.
- `app/templates/workspace_edit.html` — rebuilt the terugleverkosten mode radios (flat /
  tiered-pending) above the rate field, which is relabelled "Flat rate".
- `app/templates/workspace_results.html` — removed the orphaned feed-in preset JS; corrected
  three comments that named the Pricing box as a user of the shared ⓘ dialog on this screen.

**View models**
- `app/params_view.py` — deleted `_pricing_view`, the `grid` view block, `_g`, and the four
  now-unused label/preset tables (`_CONTRACT_LABELS`, `_CONTRACT_FEATURE_KEYS`,
  `_FEEDIN_PRESETS`, `_TLK_LABELS`, `_TLK_FEATURE_KEYS`). `_sections_for` stops emitting `grid`
  and `pricing_advanced`. `parse_form` is UNCHANGED — it is shared by both screens.
- `app/workspace_edit_view.py` — added `_TLK_LABELS` / `_TLK_FEATURE_KEYS` and the `tlk_modes`
  view entry; corrected two comments that referred to panel ②'s copy of moved controls.

**Catalogs** — re-extracted. Five new msgids translated into Dutch; 16 msgids belonging to the
deleted controls dropped. No existing translation was lost in place (verified by diffing the
old and new catalogs entry by entry).

**Tests** — 16 tests updated or replaced, none deleted outright except the feed-in preset one,
which covered a control that no longer exists; it was replaced by a test that α and β still
round-trip. Tests asserting the moved boxes' RENDERING were retargeted at the edit screen;
tests asserting `parse_form`'s coercion stayed where they were, since that half is shared.
Three new tests: the moved boxes' absence from the results screen, and the new link's presence
with cost on / absence with cost off.

## Obstacles and solutions

- **`pricing_advanced` was over-claimed after the removal** — caught by the project's own
  `test_the_sections_marker_names_exactly_the_checkboxes_this_render_draws`. The plan had said
  "the section markers stay"; that was wrong for `pricing_advanced` (its checkbox went to the
  edit screen) and needlessly true for `grid`. Both dropped; `pricing` stays because it names
  the economic guard, which is still drawn here.
- **`tlk_mode` and the feed-in presets existed only in the deleted box** — see the section
  above. `tlk_mode` rebuilt on the edit screen; presets left as a follow-up.
- **Four `test_i18n.py` tests used a deleted msgid as their sample string** —
  `"A → max import %(kw)s kW"` was the Grid connection box's fuse line, so re-extraction removed
  it from the catalog and the tests lost their Dutch/English divergence. Repointed at
  `"%(n)s / day"`, a live msgid with the same shape.
- **A first pass filled all 77 empty `msgstr`s in the English catalog.** Reverted: `en` carries
  identity translations only where they exist and otherwise falls back to the msgid — 72 were
  already empty before this change, so filling them was noise, not a fix.

## Verification

- Full suite: **1182 passed, 2 skipped** (the two skips are the live-HA tests, skipped by
  design — see the test-suite memory).
- Driven in a browser on a seeded priced dataset, in both locales. Confirmed on the rendered
  page: zero `input[name^="grid."]` and zero `input[name^="pricing."]` on the results screen;
  the Battery tab showing exactly §2′.6's wireframe list; the `[ Edit contract & rates → ]`
  button under the COST SAVINGS divider; both `pricing.tlk_mode` radios on the edit screen with
  TIERED disabled; and the Dutch render showing "Contract en tarieven aanpassen →".

## Current status

**Complete.** The duplication is gone, the lost tlk control is rebuilt, and the results screen
has a route back to the rates behind its euro figures.

Open follow-up, not blocking: the feed-in (α, β) preset select (§6.5's three-row table) has no
home on the edit screen. Rebuilding it there is an edit-screen design question — the fields it
would fill are both present and both editable, so this costs discoverability rather than
capability.
