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
- **Dynamic caveat strings render in English under NL.** The panel-③ caveats and the annualisation
  message are built in `results_view.py` as f-strings with interpolated kWh values, so their gettext
  msgid is the whole runtime string — it cannot be a static catalog entry, and `_(c)` in the
  template falls back to the English source. Fixing this properly means restructuring those strings
  as `_N`-marked templates with `%(...)s` placeholders (as the sample's caveats already are). The
  static UI chrome ("last N", From/To, Apply, recalculating…) IS translated. Deferred.

### Phase 3 — i18n + route tests (done)
- **Modified `app/locales/{nl,en}/LC_MESSAGES/messages.{po,mo}`** — extracted the new template
  msgids; translated the static chrome to NL ("last 1 week" → "laatste week", … , From/To → Van/Tot,
  Apply → Toepassen, recalculating… → opnieuw berekenen…), cleared the fuzzy flags pybabel raised
  from the old preset labels, filled the EN source catalog, and recompiled the committed `.mo`s.
  Verified both locales render the new strings.
- **New `tests/test_results_route.py`** — 9 tests over `POST /results` through the FastAPI app
  against a seeded temp-data-dir dataset: preset + default + explicit-range → 200 HTML fragment; the
  zero-battery headline (equal import both sides); and the clean-4xx/409 error paths.

## Current status

**All three phases complete, each reviewed, committed per phase.** Full suite green: **122 passed,
2 skipped** (Phase 1 added 16 view-model tests; Phase 3 added 9 route tests). The panel-③ increment
is functional end-to-end:

- GET / renders computed panel-③ energy figures from the persisted dataset (sample fallback when
  empty or no simulatable grid);
- the period presets ("last 1 week" … "last 1 year", coverage-anchored) and the explicit From/To
  date range POST to `/results` and swap the panel in place via a delegated fetch handler, with the
  monthly chart redrawn from the swapped fragment;
- every savings figure is honestly 0 (zero-battery), every measured figure is real, and a caveat
  states the battery is not configured yet;
- the benchmark box is absent (its DP is unbuilt) and the §7.4 short-window guard shows for ranges
  under 90 days;
- the static UI chrome is translated EN/NL.

Reviews: Phase 1 MINOR ISSUES (presentation-only, no correctness defect); Phase 2 CLEAN. The
follow-ups above (shared-env locale race, dynamic-caveat translation, month-label disambiguation,
`_period_selected_for` clamp quirk) are deferred and non-blocking.

Natural next increments: panel ② (battery parameters) — once it lands, the zero-battery caveat and
the `benchmark`-absent guard retire and run C diverges from A; the §6.12 perfect-foresight DP for the
benchmark box; and the debounce/SSE run-identity machinery (§3.3) for continuous re-parameterisation.

## Addition: repeat the "Your data at a glance" band inside panel ③ (window-clamped)

**Request.** Repeat the §2.3a "Your data at a glance" summary band inside panel ③ (Results), above
the ENERGY SAVINGS section, but computed over the SELECTED date range rather than the dataset's full
coverage — so it re-renders on every range change and reflects exactly the window the results are
for.

### Decisions

- **Everything clamps to the selected range in the panel-③ copy — INCLUDING the spot price.** The
  interstitial band prices over the price series' OWN full coverage (honest even when the price
  series is bridged past the meter window). The panel-③ copy instead clamps avg/min/max to the
  reconcile effective window (`rec.window`), so every figure in that copy matches the selected range
  consistently. This is a deliberate divergence between the two copies, confirmed with the user.
- **One shared macro, no duplicated markup.** The band body was extracted verbatim into a
  `data_glance(data_summary)` Jinja macro so both places render byte-identical markup (every `_()`,
  every ⓘ `.slot-info-btn`, every omit-don't-zero guard). The macro argument shadows the context var
  of the same name, so the body text is unchanged.
- **The band lives INSIDE `#panel-results`**, so it is part of the fragment swapped on every range
  change (POST /results), not a separate region.

### Implementation

- `app/summary_view.py` — `data_summary_from` gains an optional window + a window-clamped price
  option: `data_summary_from(dataset, window=None, *, clamp_price_to_window=False)`. `window=None`
  keeps the UNCHANGED full-coverage behaviour (reconcile over `dataset.window`, price over the
  series' own coverage) that the interstitial band and all existing callers/tests rely on. A given
  window is threaded to `reconcile_grid`; `coverage`/`days` and all figures come from the effective
  reconciled window (`rec.window`). New helper `_price_stats_in_window(frame, window)` masks the
  price frame's UTC-naive index to `[window[0], window[1])` (tz dropped, same convention as
  `reconcile._resample_sum`), drops NaNs, reuses `_fmt_eur`, and returns None when no price points
  fall in the window. Used only when `clamp_price_to_window=True`.
- `app/results_view.py` — `results_from` now calls `data_summary_from(dataset, window=eff,
  clamp_price_to_window=True)` (eff = the effective reconcile window) and attaches it as
  `result["data_summary"]`. Import is top-level: `summary_view` imports from `reconcile`/`dataset`/
  `frames`, never from `results_view`, so there is NO import cycle.
- `app/templates/_data_glance.html` — NEW. Holds the `data_glance` macro (the full band body).
- `app/templates/_panel_summary.html` — reduced to its comment block plus
  `{% from "_data_glance.html" import data_glance %}{{ data_glance(data_summary) }}`.
- `app/templates/_panel_results.html` — imports the macro and renders
  `{% if results.data_summary %}{{ data_glance(results.data_summary, title=...) }}{% endif %}` above
  the ENERGY SAVINGS divider. The macro import resolves in the standalone POST /results `render()`
  path too (verified by a route test).

### Distinct band headings (user refinement)

The two bands carry DIFFERENT titles: the interstitial band keeps **"Your data at a glance"**; panel
③'s copy reads **"Your energy use during the selected period"**, since it is scoped to the selected
date range rather than the whole dataset. The `data_glance` macro gained a `title=None` parameter
(defaulting to the original, so `_panel_summary.html` needs no change); `_panel_results.html` passes
the new, already-`_()`-translated title, used for both the `<h2>` and the `aria-label`.

### ⓘ affordance after a fragment swap

The `.slot-info-btn` click handler in `app/static/ha_fetch.js` is delegated from `document`
(`document.addEventListener("click", ...)`, line 134), and the shared `#slot-info-dialog` lives in
the never-swapped `_panel_data.html`. So the ⓘ buttons in panel ③'s band keep working after a
`#panel-results` fragment swap with NO re-binding — no JS change was needed.

### Tests

- `tests/test_data_summary.py` — `test_computed_window_restricts_totals_to_subwindow` (a 24 h
  sub-window over 48 h coverage halves the import total; the no-arg call is unchanged) and
  `test_computed_clamp_price_to_window_restricts_price_stats` (prices differ per half; clamped stats
  see only the sub-window, default full-coverage sees both, window-without-clamp still uses full
  coverage).
- `tests/test_results_view.py` — `test_results_includes_window_clamped_data_summary` (the
  view-model carries `data_summary`, matching `data_summary_from(ds, window=rec.window,
  clamp_price_to_window=True)` exactly) and `test_results_data_summary_window_clamped_totals` (a
  sub-window through `results_from` clamps the band totals).
- `tests/test_results_route.py` — `test_results_fragment_includes_data_glance_band` (the standalone
  POST /results fragment contains the band heading + a group heading, proving the macro import
  resolves in the standalone render path).

**i18n:** the band body reuses existing markup (no new msgids there), but the distinct panel-③
heading is one new string — **"Your energy use during the selected period"**. It was extracted,
translated to NL ("Uw energieverbruik in de geselecteerde periode"), the EN source catalog filled,
and both `.mo` files recompiled; no fuzzy or untranslated entries remain. Both titles verified to
render in both locales (interstitial keeps the original; the fragment carries the new one).

### Review outcome — data-glance-in-panel-③

Adversarial review verdict: **MINOR ISSUES, no functional defect.** No-window equivalence confirmed
(the interstitial band and all existing tests unchanged); the price-window clamp uses the correct
tz convention and the effective reconciled window, agreeing with the grid figures; the macro body is
byte-identical to the original save the intended heading swap; both render paths (initial + fragment
swap) work; the ⓘ buttons survive the swap (document-delegated handler, shared dialog in the
never-swapped panel ①); no duplicate DOM ids from rendering the band twice. The single issue was a
stale changelog sentence (now corrected here) that claimed no new msgids / no pybabel run.

**Status:** full suite green — **127 passed, 2 skipped** (was 122; +5 new tests). No follow-ups
introduced beyond the pre-existing deferred items (the shared-env locale race still applies to the
new macro exactly as to the rest of the templates).
