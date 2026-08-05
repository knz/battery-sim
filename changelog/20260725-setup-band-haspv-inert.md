# Setup band: the "Do you have solar PV?" toggle is inert

## Task Specification

User report: the "do you have solar panels" toggle at the top of the page "doesn't seem to be
effective". Investigate. Scope as given is investigation only — no code change without a plan
and approval.

## Findings

The toggle is a static scaffold. Clicking it changes nothing beyond the radio's own visual
state, and the change is lost on the next render.

Evidence, all confirmed by reading the code:

1. `app/templates/_setup_band.html` — the two radios are named `setup_haspv` (and
   `setup_cost`). They sit inside a bare `<section>`: no enclosing `<form>`, no `hx-post`, no
   `hx-trigger`, no `data-*` hook.
2. `grep -rn "setup_haspv\|setup_cost"` over the whole repo (excluding `node_modules`) matches
   **only** that template. No JS reads the name, no route accepts it, no test covers it.
3. There is no route that writes `has_pv`. The POST routes are `/params`, `/results`,
   `/results/benchmark`, `/feature-interest/{key}`, `/data/slot/{slot}/load`.
   `params_view.parse_form` (app/params_view.py:251) enumerates the fields it accepts;
   `has_pv` is not among them, and panel ② never renders an input for it — it only *reads*
   `cfg.has_pv` to decide gating (`_panel_params.html:125,176,183`; `params_view.py:617,714`).
4. The template's own header comment already states this: *"In this static scaffold the radios
   reflect cfg.* and re-derivation is not wired (matching the rest of the scaffold — no HTMX
   round-trips yet)."*

So on every page render `app/main.py:116` sets `ctx["cfg"]` from the persisted
`simconfig_store.load()`, and the radio snaps back to the stored value (appendix-A default
`has_pv=True`, per `app/domain/simconfig.py:591`).

This is a gap in the scaffold, not a regression: the wiring was never built.

## What the toggle is supposed to drive

`has_pv` is load-bearing downstream, which is why the inertness is visible:

- `SimulationConfig._force_invariants` (simconfig.py:658, 720, 733) forces
  `topology.pv_coupling → None` and battery coupling → AC when `has_pv` is false (§2.5).
- Panel ② hides the PV-coupling and phase controls when false.
- Discharge-policy D1 is filtered out without PV (params_view.py:617).
- Charge policies P1/P3 become degenerate without PV (simconfig.py:800-803).

The persistence side is already complete: `simconfig_store` serializes and reads `has_pv`
(lines 167, 337, 472). Only the request path from the radio to the store is missing.

## Options (not decided — for the user to choose)

- **A. Wire it as its own POST.** A small `POST /setup` that reads `has_pv` / `simulate_cost`,
  applies it on top of the stored config, persists, and returns the re-rendered panels ② and ③.
  Matches the `/params` pattern. Cost: a new route plus a decision about how many fragments a
  single toggle has to swap.
- **B. Fold it into the existing `/params` submission.** Add `has_pv` to the panel-② form as a
  hidden/extra field and let `parse_form` handle it. Cheapest, but it contradicts §2.1's
  "single source of truth, appears nowhere else as controls" framing and couples the scope
  choice to a panel-② save.
- **C. Leave inert, mark it visibly pending.** Same treatment `simulate_cost` already gets
  (disabled radio + `[?]` affordance), so the UI stops implying an effect it does not have.

Trade-off summary: A is the honest implementation and the most work; C is honest and nearly
free but defers the feature; B is fast but puts the control's semantics in the wrong panel.

## Files Modified

- `changelog/20260725-setup-band-haspv-inert.md` (this file) — created.

No source files changed.

## Current Status

Investigation complete, cause identified. Awaiting the user's choice among A/B/C before any
code change.

---

# Follow-up: wire has_pv (option B) + add has_battery

## Requirements Change (user, 2026-07-25)

User chose **option B**, with an expanded scope beyond the original toggle fix:

1. Move the "do you already have PV" choice to just below the title (top of page).
2. Show/hide the **solar data slot** in panel ① based on the toggle.
3. Commit the selection when the **fetch button** is clicked (which already commits all data
   configuration) — not on toggle change.
4. Data quality + "your data at a glance" must hide PV-related information when disabled.
5. Panel ②: alternate topology SVGs for the PV-disabled case.
6. Panel ②: charge/discharge options requiring PV are **disabled, not hidden**, each with an
   info button + popup explaining they need PV.
7. Panel ③: hide PV-related data.

Side note, new feature: a **"do you already have a battery"** choice in panel ①, which
disables/hides the battery charge/discharge data slots. Info button + popup explaining the
option exists only to compute house load, and that the battery simulator below assumes the
existing battery will be replaced.

Note this reinterprets "option B" from the investigation above: the commit point is the
panel-① fetch action, not the panel-② params form.

## Status

Investigating the seven touchpoints before presenting an implementation plan.

## Plan approved (user, 2026-07-25)

User confirmed reading (a): P1/P3 are DISABLED, not hidden, when has_pv is false — overturning
spec §2.3's "the charge box collapses to P2 alone, rendered as a single labelled option". The
spec text is updated as part of this change.

Additionally: D1's no-PV label is reworded to "Discharge battery to cover house load" (from the
existing `_D1_LABEL_NO_PV` = "Serve house load"), so it names the action without mentioning PV
production.

## Investigation results — what already exists

Three touchpoints needed less work than the request implied:

- `SlotSpec.pv_only` already exists and `_panel_data.html:116` already gates the solar row on
  `cfg.has_pv`. Requirement 2 works as soon as has_pv is settable.
- The glance band (`_data_glance.html`) and panel ③ (`results_view._pv_present`) are
  DATA-driven, not flag-driven: solar blocks render only when a solar series is present. With
  the slot hidden nothing is fetched, so requirements 4 and 7 mostly follow — they need
  verification tests, not new gating. Exception: `_panel_data.html:188`'s legend mentions PV
  unconditionally.
- The no-PV topology SVG (`topology/battery-ac-only.svg`, §2.5a′) already exists and is already
  wired at `_panel_params.html:210-222`. Requirement 5 is effectively done; it never rendered
  because has_pv could not be turned off.

## Design decisions

1. **Commit point.** has_pv / has_battery ride along in the WS ingest `header` message and are
   persisted in the `done` handler, next to the dataset save and the source-generation bump —
   the existing all-or-nothing reify point. Rationale: the user asked for the fetch button to
   commit the choice, and that is where every other data-configuration commit already lands.
2. **Client-side preview.** The radios re-render the slot roster immediately (show/hide rows)
   so the effect is visible before fetching; only the persistence waits for the fetch.
3. **Policy gating split in two.** `offerable_charge_policies()` keeps its current meaning as
   the SIMULATION-side gate and is left alone; panel ②'s roster gains a separate view-level
   list that emits all three policies with `disabled` + `info` flags. Rationale: §6.6 insists
   dispatch acquires no has_pv branch, and inverting `offerable_*` would have leaked the UI
   decision into config semantics.
4. **has_battery gating reuses the slot mechanism.** A new `battery_only` flag on `SlotSpec`
   mirrors `pv_only`, extending the existing `_panel_data.html` gate rather than adding a
   parallel path.
5. **Info popups reuse `.slot-info-btn` / `#slot-info-dialog`** — the delegated handler in
   ha_fetch.js needs no new JS for either the has_battery blurb or the disabled-policy blurbs.

## Status

Plan approved. Implementation starting.

## Requirements Change 2 (user, mid-implementation)

The has_pv / has_battery toggles move from the setup band into **panel ①, directly below its
title**. Rationale (recorded in specs §2.1): both answers exist to decide which SLOTS panel ①
asks for and are committed by that panel's own fetch button, so the question belongs next to the
roster it governs. `simulate_cost` stays in the setup band — it shapes panels ② and ③ too — which
leaves the band a one-question strip.

## Defects found by eyeballing a rendered no-PV page

The screenshot pass caught four things no unit test did. Two were real bugs in this change:

1. **Panel ②'s summary line read `charge P3` while the box showed P3 greyed and P2 selected.**
   The stored policy is deliberately preserved (§6.6 — dispatch already computes the right
   answer, and keeping it means turning PV back on restores the user's choice), but echoing the
   raw field made the summary contradict the panel it summarises. Fixed with a new
   `SimulationConfig.effective_charge_policy` property, used by BOTH the summary line and the
   radio group's `selected` flag — without the latter, a disabled radio rendered as checked,
   leaving the box with no enabled selection.
2. **The `load_unreliable` caveat blamed "a solar sensor" on a page declaring no PV.** Now two
   diagnoses selected by `has_pv_series` (whether a solar slot was actually mapped), not by
   `cfg.has_pv`: with a series present the sensor diagnosis stands; with none, the note says a
   meter does not export what the house did not generate, so the answer is likely wrong or an
   unmapped battery is feeding the grid. Same suppression either way — only the advice changes.
3. The popup text said "at the top of the page"; the toggle now lives in panel ①. Reworded to
   "at the top of the Data panel" in both locales.
4. Panels ②/③ showing stale PV content over a previously-fetched dataset is NOT a defect — it is
   the committed design (they describe data that has actually been loaded).

## Dutch register correction

The first translation pass used the formal "u/uw"; the catalog is predominantly informal ("Heb je
zonnepanelen?", "Je bestaande batterij"). All new strings were rewritten into the house register,
reusing the catalog's own wording for UI labels quoted inside blurbs.

## Files Modified

Domain/backend: `app/domain/simconfig.py` (has_battery field, effective_charge_policy),
`app/domain/series_vocab.py` (battery_only flag + the two info blurbs), `app/simconfig_store.py`
(three sites: serialise, load, clone), `app/ingest_ws.py` (header carries the answers),
`app/main.py` (_persist_setup_answers, cfg context), `app/params_view.py` (all-three policy
roster, disabled+info, D1 relabel, effective policy in the summary), `app/data_view.py`,
`app/summary_view.py` (has_pv_series on the note), `app/sample_data.py`.

Templates/JS: `_panel_data.html` (scope questions, rendered-and-hidden rows), `_setup_band.html`
(reduced to simulate_cost), `_panel_params.html` (disabled radios + ⓘ), `_data_glance.html`
(two-branch note), `app/static/ha_fetch.js` (setup answers, live re-gating, hidden-slot filter).

Specs: `02-ux-wireframes.md` (§2.1 placement + commit point, the Blocked-vs-Inapplicable
exception, §2.3 "Without PV" rewritten), `05-data-formats.md` (footnote 6),
`06-home-assistant-ingestion.md` (header fields + persistence ordering).

Tests: +16 across `test_params_view.py`, `test_simconfig.py`, `test_ingest_ws.py`,
`test_data_summary.py`, `test_smoke.py`. Suite: 574 passed, 2 skipped.

## Current Status

All seven requirements plus has_battery implemented, specs updated, translations complete in
both locales. Verified in a live browser: live re-gating, the commit-on-fetch round-trip, the
disabled-policy popup, and the corrected summary line.

Not done (out of the requested scope, flagged for the user):
- Panels ② and ③ still render the STORED answers until the next fetch. Intended per the design
  above, but it means a user who toggles PV off and does not re-fetch sees PV content below.
