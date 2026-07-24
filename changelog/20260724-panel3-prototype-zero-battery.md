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

### Phase 2 — route wiring + template/JS (done)
- **Modified `app/main.py`** — imported `results_view`; `index()` now sets `ctx["results"]` from
  `results_view.results_from(loaded, resolve_window(loaded))` (default `last_1_year`) in the same
  dataset branch that sets `data`/`data_summary`, falling back to the sample when it returns None
  (mirrors `data_summary`), inside the existing try/except. Added **`POST /results`**: parses
  `{"period"}` XOR `{"start","end"}` (ISO → tz-aware UTC via `_as_utc`), calls `resolve_window`
  (ValueError → 400) and `results_from` (None → 409), installs the request locale on the Jinja env
  and renders `_panel_results.html` standalone via `templates.env.get_template(...).render(...)`,
  returning it as `HTMLResponse`. No dataset → 409. Docstring Routes list updated.
- **Modified `app/templates/_panel_results.html`** — root `<section>` now `id="panel-results"`
  (swap target). Guarded the benchmark card with `{% if results.benchmark %}` (computed view-model
  has no key; sample still does). Relabelled the period presets to "last 1 week … last 1 year" with
  `data-period` tokens and `btn-active` keyed off `results.period_selected`. Added an explicit
  From/To `<input type="date">` + Apply picker, a hidden `⟳ recalculating…` span, and the §2.4
  short-window `alert alert-info` guard box gated on `results.annualisation_disabled`. Removed the
  inline Plotly load + draw; kept only `#monthly-data` (moved inside `#panel-results` so it swaps
  with the panel) and `#monthly-chart`.
- **Modified `app/templates/index.html`** — moved the Plotly `<script src>` here (outside the
  swappable panel) and added a `window.drawMonthlyChart()` that reads `#monthly-data` and draws.
  Added DELEGATED `document` click listeners (keyed off `data-period` / `#results-apply-range`)
  that POST to `/results`, swap `#panel-results` by `outerHTML`, toggle the recalculating spinner,
  and redraw the chart — bound once, so the swapped-in fragment needs no re-binding.

### Fragment-swap + chart-redraw approach (rationale)
The route returns the whole `_panel_results.html` output; the browser replaces `#panel-results`
by `outerHTML`. A swapped-in inline `<script>` re-inserts but does NOT re-execute, so all of panel
③'s behaviour lives in `index.html` (never swapped) and reaches the panel via delegated listeners
+ a named `window.drawMonthlyChart()`. The chart data rides in a `<script type="application/json">`
inside the swapped fragment; after each swap the handler calls `drawMonthlyChart()` to redraw from
the fresh node. This matches the app's existing HTML-fragment style (no client framework, delegated
listeners like the pending dialog). Date convention: From→00:00:00Z, To→23:59:59Z (inclusive of
both chosen days); `resolve_window` clamps to coverage so out-of-range dates are clamped, not errors.

## Review outcome — Phase 1

Adversarial review verdict: **MINOR ISSUES, no correctness defect.** Refactor confirmed equivalent;
`resolve_window` anchor agrees with the reconciled grid; zero-battery invariant holds; omit-don't-zero
correct. The one hard-failure path (unguarded `results.benchmark` in the template) is dead until
Phase 2 wires the view-model in — Phase 2 adds that guard.

## Review outcome — Phase 2

Adversarial review verdict: **CLEAN — no defect introduced by Phase 2.** All documented route paths
verified in a REPL against the persisted dataset, including error cases (400/409/422, no 500s); the
fragment-swap + delegated-listener + chart-redraw model is sound (listeners live outside the swapped
node; `#monthly-data` swaps with the panel and is re-read); template guards render both the computed
(benchmark-less) and sample (benchmark) dicts; the date-picker window convention has no off-by-one.

Cleanup applied after review: dropped the misleading unused `cfg=CONFIG` from the fragment render
(wrong `Config` type, and the template reads only `results.*`).

## Follow-ups (deferred, not blocking)

- **Shared-Jinja-env locale race (pre-existing, app-wide).** `index()` and now `POST /results`
  install the request's gettext catalog onto the *module-level shared* `templates.env` before
  rendering; install-then-render is not atomic and sync routes run in a threadpool, so under
  concurrent mixed-locale load a render can pick up another request's catalog. This predates this
  task (`index()` already did it) and Phase 2 mirrors it rather than worsening the bug class, but it
  is a genuine latent bug — fix app-wide later (per-render env overlay, or pass translations
  explicitly instead of mutating the shared env).
- `_period_selected_for` maps a *clamped* window's span to the nearest preset, so a "1 year" request
  over <1 year of coverage highlights a shorter button. Inherent to passing a resolved window rather
  than the origin preset; revisit if it reads wrong once wired.
- `_monthly_import` repeats month labels across a multi-year window (two "Jan" bars); values are
  correct. Add year disambiguation if multi-year ranges become common.
- Coverage line pluralisation ("1 intervals"). Cosmetic.
- No route tests for `POST /results` yet (deferred with the i18n phase).

## Current status

Phase 1 (backend) complete, reviewed, tests green. **Phase 2 (route wiring + template/JS) complete:**
`POST /results` and `index()` wiring in `main.py`, period + date-range pickers and benchmark /
short-window guards in `_panel_results.html`, delegated fetch/swap + chart-redraw JS in
`index.html`. Full suite green (113 passed, 2 skipped — unchanged from Phase 1); smoke test's
`test_chart_rendered` still passes with the moved chart-draw. Manual render checks pass: GET /
(empty state = sample, with-dataset = computed), POST /results for presets + explicit range (200,
fragment rooted at `#panel-results`), error paths (unknown preset / both / bad date → 400; no
dataset → 409), short-window guard box shown for `last_1_week`, benchmark card absent for the
computed (benchmark-less) view-model and present for the sample. Not committed — awaiting review.

Follow-ups deferred to a later phase: no route tests added (per Phase 2 scope); new UI strings
(`last 1 week`…, `From`/`To`, `Apply`, `recalculating…`, the guard message) are marked `_()` but
not extracted/compiled, so they degrade to English until a later i18n phase.
