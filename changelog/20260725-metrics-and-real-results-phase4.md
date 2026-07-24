# Phase 4 — §6.11 metrics and panel ③ showing real simulated results

## Task specification

Implement the §6.11 energy metrics and rewire `app/results_view.py` so panel ③ shows REAL
simulated battery figures instead of the structural zeros the previous increment emitted.
Scope boundaries given by the orchestrator:

* No §6.12 DP, no `benchmark` key (Phase 5).
* No panel ② / `_panel_params.html` changes (Phase 6).
* No euro figure anywhere (`simulate_cost` stays false).
* `simulate.py` / `simconfig.py` / `simframe.py` are read-only; a genuine defect is reported,
  not fixed silently.
* Frame arrays must not be modified in place (shared with `app/summary_view.py`).

## High-level decisions

* **New module `app/domain/metrics.py`.** The §6.11 arithmetic is domain logic over `Flows`
  arrays, not presentation, so it sits beside `simulate.py` and returns a bare-numbers
  `EnergyMetrics` object. `results_view.py` keeps only formatting and copy, matching the
  split that already exists between `reconcile.py` and `summary_view.py`.
* **Every metric gets its own hand-computed fixture.** The Phase-3 review established that
  the fixture-3 conservation identity is §6.8 step 5 rearranged and cannot catch metric
  arithmetic defects. Expected numbers in `tests/test_metrics.py` are derived on paper from
  the spec's efficiency convention, never from the implementation.
* **`saved_pct`'s denominator is run A**, not `import_obs`. Pinned by a fixture where the two
  differ, so a future "simplification" to observed import fails.
* **`self_consumption` is `None` without PV**, never 0 or 1 (§6.11: both assert something the
  data cannot support). Both scenarios (baseline, battery) computed.
* **Self-sufficiency is display-clamped to ≥ 0 on BOTH sides** (§2.3a), with a caveat when
  either clamp fires. The metric object keeps the unclamped value; only presentation clamps.
* **A negative `saved_kwh` is reported honestly** (§7.2 item 9): the KPI tile shows a signed
  value, `saved_pct` keeps its sign, the breakdown row is relabelled "Extra grid import" so
  "avoided" never reads as a positive number, and a caveat explains that without PV the value
  is in the price spread (a euro quantity an energy-only run cannot answer).
* **SoC drift** is always computed; a caveat fires when `|soc_end − soc_start|` exceeds
  `SOC_DRIFT_WARN_FRAC` (2%) of the energy saving. `soc_delta_value_eur` is not computed —
  there is no cost model.
* **Standby comes from `RunSet.standby_kwh`** (the exact C − B difference), not `standby_w × h`.
* **No caching layer.** Measured on the real persisted dataset (8,760 hourly intervals):
  `run_all` = 0.115 s, frame build = 0.004 s. That is acceptable per request; a cache would be
  speculative complexity with a staleness problem the spec has not yet framed.

## Requirements changes

None mid-task.

## Files modified

* `app/domain/metrics.py` — NEW. `EnergyMetrics`, `SOC_DRIFT_WARN_FRAC`, `energy_metrics()`.
* `app/results_view.py` — rewired: builds a `SimulationFrame` + appendix-A `SimulationConfig`,
  runs `run_all`, computes metrics, populates KPI tiles / breakdown / secondary / caveats.
  The "No battery is configured yet…" caveat is deleted.
* `tests/test_metrics.py` — NEW. Hand-computed fixtures for every metric.
* `tests/test_results_view.py` — the zero-battery invariants rewritten to assert real behaviour.
* `tests/test_results_route.py` — the zero-battery headline assertion updated.

## Rationales and alternatives

* *Metrics in `results_view` vs a domain module.* Keeping them in the view would have made
  them untestable without a `LoadedDataset` and would have put §6.11 arithmetic behind a
  formatting layer. The domain module takes `RunSet` + `SimulationFrame` + `SimulationConfig`
  and returns floats, so the fixtures are arrays-in/numbers-out like `test_simulate.py`.
* *Config source.* Appendix-A defaults (`SimulationConfig()`) for now; Phase 6 wires the panel-②
  form. Documented in the view so the figures are not mistaken for user-configured ones.

## Obstacles and solutions

* Panel ③'s previous copy asserted zeros throughout — rewrote the affected assertions to pin
  the real hand-derived numbers rather than deleting the tests.
* `_frame` in tests/test_simulate.py leaves `SimulationFrame.window` as `(None, None)` (the
  core never reads it), which broke a `window_days` computed from it — switched
  `cycles_per_day`'s divisor to `intervals × dt_hours / 24`, which is the simulated span and
  works for both frame constructions.
* **A literal `%` in a caveat is silently eaten by the template.** `_panel_results.html`
  renders caveats through `_()`, and `app/i18n.install_for` uses `newstyle=True`, which applies
  %-formatting to the result: "90% round-trip" rendered as "90{}ound-trip". Caveats are now
  worded without the sign (escaping as `%%` would push the escape onto every translator), and
  `test_no_caveat_contains_a_literal_percent_sign` guards it. Found by looking at the live page,
  not by a test.
* Two arithmetic slips in my own first-draft fixtures (an efc/AC ratio written as `1/0.9`
  instead of `1/η`, and a mis-summed gap scenario) — corrected, and both now assert the wrong
  answer explicitly alongside the right one.

## Findings

* **Simulation cost, measured on the real persisted dataset** (8,760 hourly intervals,
  2025-07-24 → 2026-07-24): frame build 0.004 s, `run_all` 0.115 s, `results_from` 0.131 s,
  full `GET /` 0.136 s, `POST /results` 0.130 s. No caching added — the cost is acceptable and
  a cache would introduce a staleness question (config, window, dataset id) the spec has not
  framed. Revisit if Phase 5's DP (a few seconds per §6.12) lands on the same request path.
* **The metered standby and the load-side standby are different numbers**, and both are needed:
  `RunSet.standby_kwh` (= `C.imp − B.imp`) is what crossed the meter and is what the breakdown
  row reports; `standby_w × dt × intervals` is what §6.9 added to the load and is what the
  battery-side self-sufficiency denominator must use. Pinned by its own fixture.

## Review round: §7.1 information-set defects in the view

An adversarial review of the above returned DEFECT FOUND. The §6.11 arithmetic in
`app/domain/metrics.py` was verified correct on every point; the defects were all in
`app/results_view.py`, which mixed OBSERVED and SIMULATED figures inside single comparisons.

### The governing rule

`specs/14-diagnostics.md` §7.1: "Use the *simulated* baseline (run A), so that both scenarios see
identical information. Report the observed import alongside it, with the difference labelled as
resolution loss. Using observed import as the denominator while computing the battery case from
reconstructed data would mix two information sets and produce a number that is wrong in a
direction nobody can reason about."

The mixing is not neutral. The meter's import exceeds run A's by the energy that reversed
direction *within* a grid interval — the §6.3 reconstruction nets it out and no simulated battery
can recover it — so a measured baseline against a simulated battery case is biased in one
direction, and that direction flatters the battery.

### What was fixed

1. **The self-sufficiency tile compared the meter against run C.** The left half was
   `1 − rec.imp_total/rec.load_total` (observed), the right half `self_sufficiency_battery`
   (simulated). `metrics.self_sufficiency_baseline` was already computed, correct, and never read.
   Both halves now come from `EnergyMetrics`. A code comment claimed the mixing was a deliberate
   trade so the tile would agree with the data-glance band above it; §7.1 rules the other way, and
   the band is separately labelled as measured instead.

2. **The self-consumption row compared the meter against run C**, same defect on the export side.
   Both halves now come from `EnergyMetrics`.

3. **Two unexplained grid-import figures on one panel.** The band shows the meter's; the savings
   section shows run A's. The band's Grid group gained an "as your meter recorded them" caption
   (in the shared macro, so panel ① gets it too — correct there, those figures are measured in
   both places), and a caveat names the gap in kWh per §7.1's own instruction.

4. **MINOR — zero-load household reported "0% → 100%".** `self_sufficiency_battery`'s denominator
   is the standby-inclusive load, nonzero from standby alone, so with `load == 0` the ratio
   computed successfully and asserted a measurement. The §6.11 "null, never 0 or 1" discipline is
   now symmetric: both sides gate on the bare load and the tile omits both halves.

5. **MINOR — "Extra grid import" had no Dutch msgid.** Every other breakdown label reaches the
   catalog via `app/sample_data.py`'s parallel copy; this one has no sample counterpart (the
   sample shows a positive saving), so it is tagged with `_N` at its own site.

6. **NITPICK — `_fmt_kwh` emitted ASCII `-`** where `_fmt_signed_kwh` emits U+2212. Aligned.

### The self-consumption windowing, and a correction to the review's diagnosis

The review attributed roughly 2 points of the apparent 34% → 60% jump to a window change: the
measured half is computed over the PV series' own coverage (162 days on the real dataset) and the
simulated half over the whole 365-day window with `frame.pv` zero-filled outside PV coverage.
§2.3a's own-coverage rule is unambiguous ("comparing six months of production against two years of
export would be meaningless"), so `energy_metrics` gained a `pv_mask` parameter and
`results_view` builds the mask once and passes it, putting both scenarios on one window.

**Measured on the real dataset, the mask changes nothing, and the reason is structural.** §6.9
computes export as `max(0, pv − load)` over a §6.3-clamped (non-negative) load, so a run cannot
export in an interval where `pv` is zero — and `frame.pv` is zero outside PV coverage. Simulated
export is therefore *already* confined to the PV window by construction: run A's export is
2030.0337 kWh masked and unmasked, to ten significant figures.

The 34% → 36% shift in the displayed baseline is entirely the §7.1 information-set switch, the
same defect as items 1 and 2 — measured export 2,095.53 kWh over the PV window gives 33.7%, run
A's 2,030.03 kWh over the same window gives 35.8%. So the real fix was the view reading
`self_consumption_baseline`, not the windowing.

The mask is kept anyway, and the reasoning is recorded rather than the conclusion: it converts an
agreement that currently holds *because of how §6.9 happens to define export* into one the metrics
layer states for itself. If a later increment gives a run another way to export — grid arbitrage
under a D3 discharge policy, say — the ratio stays on the PV window instead of silently acquiring
the pre-PV months. `test_self_consumption_uses_the_pv_series_own_coverage_window` pins both the
no-op and the structural reason for it, so the next reader is not left to rediscover this.

### Displayed figures on the real dataset, before → after

Self-sufficiency tile (measured baseline → simulated baseline), all five presets:

| Preset | Before | After |
|---|---|---|
| 1 week | 57% → 86% (+29 pp) | 61% → 86% (+25 pp) |
| 1 month | 59% → 87% (+28 pp) | 61% → 87% (+26 pp) |
| 3 months | 58% → 89% (+31 pp) | 61% → 89% (+28 pp) |
| 6 months | 43% → 69% (+26 pp) | 46% → 69% (+23 pp) |
| 1 year | 21% → 33% (+12 pp) | 23% → 33% (+10 pp) |

Self-consumption row, 1 year: 34% → 60% became 36% → 60%. The band's own figures are unchanged
(they are measured, and now say so): imported 3,924 kWh, exported 2,096 kWh, self-sufficiency 21%,
self-consumption 34%.

The bias was flattering in every preset, by 2–4 pp on the delta.

### Files modified in this round

* `app/domain/metrics.py` — `pv_mask` parameter; self-consumption over the PV window on both
  sides; symmetric null guard on self-sufficiency. No other arithmetic touched.
* `app/results_view.py` — the tile and the self-consumption row read `EnergyMetrics` on both
  halves; `_pv_self_consumption` split into `_pv_coverage_mask` + `_pv_present`; the
  resolution-loss caveat; the clamp caveat reworded to cover either half; `_fmt_kwh` minus glyph;
  `_N` on "Extra grid import".
* `app/templates/_data_glance.html` — "as your meter recorded them" caption on the Grid group.
* `app/locales/{en,nl}/…/messages.{po,mo}`, `app/locales/messages.pot` — two new msgids.
  Extracted with `--no-location` to match the committed catalogs' style and
  `--no-fuzzy-matching` (fuzzy matching mistranslated "Extra grid import" as "Netafname T2").
* `tests/test_results_view.py`, `tests/test_metrics.py`, `tests/test_results_route.py`.

### Obstacles

* **The existing fixtures could not have caught any of this.** Every panel-③ scenario had
  `export = 0` in all intervals, so the meter's import and run A's coincided and the defective
  view passed. The new tests use an overlap fixture (import 2 kWh/h *and* export 1 kWh/h in the
  same hour) where the two information sets differ by a factor of two: measured
  self-sufficiency 50%, simulated 75%. Each assertion pins both candidates.
* `pybabel update` without `--no-fuzzy-matching` gave "Extra grid import" the msgstr
  "Netafname T2" from an unrelated entry; without `--no-location` it added `#:` comments the
  committed catalogs do not carry, turning a 2-msgid change into a 716-line diff.

## Current status

Complete. 328 passed, 2 skipped (was 320 passed, 2 skipped; +8 tests).
