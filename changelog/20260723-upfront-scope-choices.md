# Upfront scope choices (has_pv, simulate_cost)

## Task Specification

**User's original prompt (2026-07-23):**

> here's a change to propagate to the spec/wireframes and code prototype.
>
> UX flow for users: currently they enter data first, then parameters. however the
> shape of the data depends on a choice they need to make in the parameters: whether
> they use PV and whether the cost simulation is enabled. let's pull this choice
> upfront (before the first panel) and conditionalize the rest on what the user
> inputs there.

**Scope:** Propagate a UX-flow change across three surfaces — the spec/wireframes
(`specs/`), and the code prototype (templates + sample view-model). Move the two
shape-determining choices — *do you have solar PV?* (`has_pv`) and *simulate cost
savings?* (`simulate_cost`) — out of panel ② (Parameters), where they currently live
and are mirrored back into panel ①, and into a new step that runs **before** panel ①
(Data). Everything downstream (which series panel ① asks for, which boxes panel ②
shows, which sections panel ③ renders) is conditionalized on the answers given there.

## Current state (before change)

- `has_pv` and `simulate_cost` are set in **panel ②**:
  - `simulate_cost` — the "What to simulate" box at the top of §2.3.
  - `has_pv` — the "Solar PV" box in §2.3.
- Because the natural order of use is ① then ②, §2.2 says both toggles are **mirrored**
  at the head of panel ①'s series-mapping box as read-only-ish one-line questions, and
  "changing either in one place changes it in both."
- Panel ① renders the solar row / spot-price requirements conditioned on these.
- State machine §3.2 notes these two fields "change which other fields exist" and emit an
  ordinary `PARAMS_CHANGED`.

## High-Level Decisions (from user, 2026-07-23)

1. **Form of the upfront step:** a *lightweight pre-panel band* above panel ①, not a
   fourth collapsing stepper panel and not a first-launch modal. The stepper stays at
   three panels (①/②/③). The band reads as a scope selector — two questions —
   rather than a data-entry step. Header/title: "Before you start".
2. **Editability after data load:** the two choices stay **editable** at all times.
   Changing them re-conditionalizes panels ①–③ *in place* (show/hide rows and boxes),
   retaining already-entered values, and marks results stale → recalc. This is the same
   behaviour the mirrored toggles had; no lock, no confirm dialog.
3. **Old control locations:** *remove the controls, no read-only reminder.* Delete the
   mirrored one-line questions atop panel ①'s mapping box, delete panel ②'s
   "What to simulate" box, and delete panel ②'s "Solar PV" box. The upfront band is the
   single source of truth; downstream panels conditionalize silently on the answers.

## Requirements refinement (mid-task)

After the plan was approved, the user added: *"which data slots are needed/enabled/requested
should also be made to depend on the selection."* This made the slot-roster dependency an
explicit deliverable rather than an implied downstream effect. Concretely:

- **`has_pv`** governs the `solar_production` slot (present/required only with PV).
- **`simulate_cost`** governs the `price_spot_min` / `price_spot_max` slots — cost-only
  intra-interval price series (§4.1, feeding the §6.16 bracketing diagnostic). These are the
  one place the cost choice *adds* a data slot rather than only hiding downstream boxes. They
  were in the §4.1 vocabulary but not previously surfaced in the §2.2 slot list; now they are,
  gated on `simulate_cost`. `price_spot` itself stays required in both cost modes.

## Files Modified

**Spec / wireframes:**
- `specs/02-ux-wireframes.md` — §2.1: added the "setup band" to the layout diagram and a new
  "The setup band" subsection (scope selector, not a stepper panel; single source of truth;
  editable, re-derives in place). §2.2: removed the mirrored toggles from both the HA mapping
  box and the CSV checklist; added the `◒` cost-only `Spot price (min/max)` rows to both;
  rewrote the "decides what panel ① asks for" prose to name the band; updated legends.
  §2.3: removed the "What to simulate" and "Solar PV" boxes; updated the "Without PV" /
  "Without cost simulation" openers to note the choices come from the band. §2.4: repointed
  the "Enable cost simulation" affordance at the band.
- `specs/04-state-machine.md` — §3.2: rewrote the `has_pv`/`simulate_cost` paragraph to place
  them in the band, available from EMPTY, with explicit slot-roster re-derivation rules on
  edit. §3.4: added a note that the band is not a panel and has no focus state.
- `specs/05-data-formats.md` — footnote ² repointed to the band; added footnote ⁵ for the
  `price_spot_min`/`price_spot_max` slots being offered only under cost simulation.
- `specs/01-product-brief.md` — `simulate_cost` location updated to the band.
- `specs/implementation-progress.md` — moved the `simulate_cost` pending-control row to
  `_setup_band.html`.

**Code prototype:**
- `app/templates/_setup_band.html` — NEW. The band: two radio-pair questions bound to
  `cfg.has_pv` / `cfg.simulate_cost`. The cost "Yes" answer is pending (`[?]`, key
  `simulate_cost`), matching the prior scaffold's treatment of that unbuilt feature.
- `app/templates/index.html` — include the band above the data panel; docstring updated.
- `app/templates/_panel_data.html` — removed the mirrored toggle block; mapping loop now also
  gates `cost_only` rows on `cfg.simulate_cost`; added `◒` marker; legend updated.
- `app/templates/_panel_params.html` — removed the "What to simulate" and "Solar PV" boxes;
  Grid connection promoted out of the former two-card column; docstrings updated.
- `app/sample_data.py` — added the two `cost_only` price rows to the mapping; docstrings note
  the choices now live in the band.
- i18n: extracted + updated + compiled EN/NL catalogs; added Dutch translations for the new
  band strings and the extended legend; fixed the fuzzy-matched `Spot price (min/max)`.
- `app/static/app.css` — rebuilt (new `w-56` utility used by the band).

## Obstacles and Solutions

- The granularity table in the data-quality box also lists "Solar production" unconditionally;
  a first grep suggested the solar row wasn't hiding. Confirmed via the mapping-row entity ID
  that the *mapping* row does respect `has_pv`; the granularity table's PV-conditionality is a
  pre-existing scaffold question, out of scope here.

## Verification

- App renders (HTTP 200) in EN and NL; band strings present and translated.
- Old boxes ("What to simulate", "Also simulate cost savings", "Solar PV" box) absent.
- Slot conditional exercised across all four (has_pv × simulate_cost) combinations: solar row
  present iff has_pv; min/max rows present iff simulate_cost.

## Current Status

Complete. Spec, wireframes and code prototype all updated and verified. Not yet committed
(awaiting user's go-ahead per git-workflow rule).
</content>
</invoke>
