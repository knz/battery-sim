# Panel ③ prototype with real values (zero-battery, no panel ②)

## Task specification (user's original prompts)

> i'd like to start prototyping panel 3 in the UI with real values
> but we'd do this _without_ implementing panel 2; i.e. not having battery parameters available yet
>
> so what this means is wiring up the UI to the backend (including, in particular, the date
> range picker), then setting up the computations, then displaying what comes out. we can
> assume battery charge/discharge remain zero at this stage

**Scope:** bring panel ③ (Results, specs §2.4) to life from the *persisted dataset* — the same
frames the data-summary band already reads — without building panel ② (battery parameters). The
simulated battery does nothing at this stage (charge = discharge = 0), so the "with battery"
scenario equals the baseline. What is genuinely new is the wiring: the panel-③ **date-range /
period picker** must drive a backend recomputation over a sub-window of the data, and the panel
must render the computed figures rather than the static sample.

## Context established from the specs + code (pre-plan reading)

- Panel ③ renders the result object (specs §4.5) field-for-field: `energy` breakdown, the two
  benchmark boxes, `ratios`, `battery`, `warnings`. Cost section is gated on `simulate_cost`
  (default off) — out of scope here.
- With charge/discharge ≡ 0: run C (with battery) == run A (baseline). So `saved_kwh = 0`,
  `saved_pct = 0`, self-sufficiency baseline == battery, efc = 0, throughput = 0, conversion
  loss = 0, standby = 0. The energy breakdown collapses to "import with/without battery equal".
- The battery-free energy figures already exist in `app/summary_view.py` (§6.11 slice over the
  §6.3 load reconstruction): Σimport, Σexport, Σpv, reconstructed load, self-sufficiency,
  self-consumption. Panel ③'s ENERGY section needs the same inputs plus the (currently zero)
  battery deltas.
- The period picker is currently static markup in `_panel_results.html` (buttons, no wiring).
  State machine: `RANGE_CHANGED` (§3.2) → recompute over the sub-window. Windows are anchored
  per §7.4 (short-window guard under `min_annualisation_days`, default 90).
- The perfect-foresight benchmark (§6.12, runs D/E) is a DP — NOT yet built. Deciding whether to
  stub or build it is an open question for the plan (see below).

## High-level decisions (from user answers, plan approved)

1. **Benchmark box omitted** this increment — the §6.12 perfect-foresight DP (runs D/E) is not
   built, and inventing numbers would be dishonest. `results_from` emits no `benchmark` key; the
   template guards it in Phase 2.
2. **Recompute path = JSON/HTML-fragment endpoint + `fetch()`** (`POST /results`), not a full page
   reload — keeps the "watch results while editing" feel (§3.4) without the full SSE/debounce
   machinery, which can land with panel ②.
3. **Window anchor = end of data coverage** (§7.4). Presets relabelled **"last 1 week / last 30
   days / last 3 months / last 6 months / last 1 year"**, anchored to the last timestamp in the
   meter data. **Plus a separate explicit date-range picker** over an arbitrary sub-window.
4. **Zero-battery assumption:** charge ≡ discharge ≡ 0, so run C == run A. All savings figures are
   structurally 0; every measured figure is real.

## Working method

Implemented with implementation + adversarial-review sub-agents, iterating per phase until the
review is clean; minor review issues addressed inline or flagged as follow-ups here; committed per
phase. On branch `feat/pending-affordance-backend` (the branch handed to this session).

## Files modified / created

### Phase 1 — backend (done, reviewed, committed)
- **New `app/domain/reconcile.py`** — shared per-interval reconciliation + §6.3 load reconstruction
  extracted from `summary_view.py`. `reconcile_grid(dataset, window) -> ReconciledGrid | None`.
- **New `app/results_view.py`** — `results_from(dataset, window) -> dict | None` (panel-③ ENERGY
  view-model, zero-battery) and `resolve_window(dataset, *, period, start, end)` (coverage-anchored
  window resolver, §7.4).
- **Modified `app/summary_view.py`** — now calls `reconcile_grid`; behaviour bit-identical
  (`tests/test_data_summary.py` unchanged and green).
- **New `tests/test_results_view.py`** — 16 tests (zero-battery invariant, no-PV omit discipline,
  None guard, preset anchoring/clamping).

## Review outcome — Phase 1

Adversarial review verdict: **MINOR ISSUES, no correctness defect.** Refactor confirmed equivalent;
`resolve_window` anchor agrees with the reconciled grid; zero-battery invariant holds; omit-don't-zero
correct. The one hard-failure path (unguarded `results.benchmark` in the template) is dead until
Phase 2 wires the view-model in — Phase 2 adds that guard.

## Follow-ups (deferred, presentation-only — not blocking)

- `_period_selected_for` maps a *clamped* window's span to the nearest preset, so a "1 year" request
  over <1 year of coverage highlights a shorter button. Inherent to passing a resolved window rather
  than the origin preset; revisit if it reads wrong once wired.
- `_monthly_import` repeats month labels across a multi-year window (two "Jan" bars); values are
  correct. Add year disambiguation if multi-year ranges become common.
- Coverage line pluralisation ("1 intervals"). Cosmetic.

## Current status

Phase 1 (backend) complete, reviewed, tests green (113 passed, 2 skipped). Next: Phase 2 — wire
`POST /results` + `index()` in `main.py`, and the period + date-range pickers in
`_panel_results.html` (with the benchmark/secondary/cost guards).
