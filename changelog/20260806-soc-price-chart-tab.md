# Build the "SoC + price" chart tab

Retires the last pending affordance in the Charts box (`chart_soc_price`), following
`20260806-energy-flows-chart-tab.md` which retired its sibling. Followup C2.

## Task specification

Verbatim, from the user:

> let's add this tab now.
> it's going to contain two charts.
> the first chart is pure SoC (no pricing). x axis is days, y axis is hours of day. each cell
> represents one hour (SoC reached at that hour). Coloring from blank (no charge) to opaque (full
> charge).
> graph contains as many columns as days in period (capped at 365 or current width in pixels,
> whichever is smaller). each column should be at least one pixel wide.
>
> i'm not sure if we should use plotly for this, and which chart type? maybe a canvas draw might
> be better.

So: TWO charts in the tab, of which only the first is specified. The second is not yet described —
presumably the price half, given the tab's name, but that is not stated and must not be assumed.

Note this DEPARTS from what the spec recorded for the tab (`docs/specs/02-ux-wireframes.md:1204`,
followup C2): a time-series of SoC against bare `spot_eur_kwh` on a secondary axis. A day×hour
heatmap answers a different question — daily/seasonal RHYTHM rather than instantaneous dispatch —
and it also resolves C2's open "whole range or zoomable window" question by bucketing to the hour,
which a raw series could not do at 35k points. The user's instruction supersedes the spec here;
the spec text needs updating to match.

## Questions asked, and the answers

Recorded so the answers are traceable to the decisions they drove.

**1. Renderer — Plotly heatmap, not canvas.** I leaned canvas, on the grounds that the original
"at least 1px per column, capped at pixel width" rule is a statement about the DEVICE pixel grid
and Plotly lays out in data coordinates. Two findings from the investigation weakened that:
the committed `plotly.min.js` is the full 4.56 MB build and already contains the `heatmap` trace
module, so Plotly costs no new asset; and every other plot in this panel is Plotly SVG, with the
browser tests asserting on `svg` presence (`tests/test_smoke.py:674`). A `<canvas>` renders nothing
a Playwright selector can see, which is a real step down in testability.

The user chose Plotly and **explicitly dropped the conflicting sizing requirements** rather than
asking to reconcile them. So the per-column pixel rule is OUT: Plotly sizes the cells. The 365-day
cap likewise loses its original motivation, though it may return as a payload-size measure.

**2. Cell granularity — 15-minute, not hourly.** "If we can do 15-minute cells instead of hourly,
that's fine, no need to average. Display what the data has available." This is a simplification,
not an extra: the y axis becomes the interval within the day at the grid's own resolution, so
there is no bucketing step and no aggregation question — no end-of-hour-vs-mean choice, no
day-count denominator, and none of `_hourly_flow`/`_hourly_stock`'s resolution-invariance
machinery applies. The cell IS an interval. At a 15-minute grid that is 96 rows; at hourly, 24.

**3. The spec departure is accepted.** Acknowledged as a departure and approved: "we're going to
use something that looks & feels like a heatmap anyway." `docs/specs/02-ux-wireframes.md:1204` and
followup C2 need updating to match.

**4. The second chart stays a placeholder.** Not specified, and deliberately not invented here.

**5. NEW: lazy loading.** Raised by the user — "maybe this chart would benefit from being loaded
lazily so the data transfer is only paid when the user wants it. we have precedent on lazy load."
This is a payload-size concern and a real one: unlike the other tabs' aggregates (12 months, or
24 hourly buckets), this chart's data is one value PER INTERVAL — a year at 15 minutes is ~35k
numbers, which would ride on every recompute whether or not the tab is ever opened.

**Resolved: inline, quantised to one byte per cell — NOT a lazy route.** The investigation found
exactly one lazy-load precedent (the §6.12 benchmark box, `POST /w/{id}/results/benchmark`,
`app/main.py:1240`) and, more usefully, a comment that had already made this same call for the
neighbouring tab (`app/results_view.py:2766-2770`): energy flows are emitted inline "rather than
behind a lazy endpoint like the benchmark box" because "a separate route would re-run `run_all`
(nothing is cached) to save a few KB of JSON."

The asymmetry that justifies the benchmark's route does not hold here. Timings recorded in the
code (`app/main.py:1249-1254`): the §6.12 DP is ~2.3 s per pass on a year of hourly data, ~4.6 s
for both export baselines, and inline it made `GET /` take 4.72 s against 0.13 s. Panel ③ minus
the benchmark is ~0.12 s. So the benchmark's lazy route buys back SECONDS; a lazy SoC route would
buy back ~0.12 s and then spend it again on every tab open, with no cache to amortise it.

What DOES differ from that comment is payload size, and only that: flows is a few KB, whereas a
year of 15-minute cells is ~35k values, ~200 KB of JSON on every recompute plus Plotly parse cost
for cells nobody asked to see.

Quantising resolves the payload concern without the route. The colour is a ramp, so the cell only
ever needs a display value: SoC normalised to the operating window, quantised to 256 levels,
base64'd. ~47 KB of base64 for a year of 15-minute cells, sent inline like every sibling tab — no
second route, no duplicate `run_all`, and none of `loadBenchmark`'s stale-response token, error
path or loading state. The accepted cost is that the payload carries display values rather than
kWh, so a hover in kWh reconstructs from the published min/max — to ~0.04 kWh at 10 kWh capacity,
finer than the chart can draw.

Rejected alongside it: inline raw floats (simplest, but ~200 KB always).

## Plan (approved)

Verified against the Plotly docs before proposing, rather than assumed: `z` takes a plain 2-D
array, `x`/`y` take category-label arrays, `zmin`/`zmax` pin the ramp (still `z*` on heatmap —
only `surface` renamed them to `c*` in Plotly 3), `hoverongaps: false` suppresses hover on `null`
cells, and colorscale stops accept any CSS colour string, so `rgba` gives real transparency rather
than white.

1. `_soc_heatmap(runs, rec, frame, cfg)` in `app/results_view.py` → `results["soc_heatmap"]`,
   computed inside the existing `if frame is not None` block from arrays already in hand.
   Grid is days × intervals-per-day at the data's own resolution (`86400 // rec.grid_s`).
   Quantise `q = round(255 × (soc − soc_min) / (soc_max − soc_min))`, clamped, base64'd; publish
   `soc_min_kwh`/`soc_max_kwh` so the browser reconstructs kWh for hover.
2. `drawSocHeatmap()` in `workspace_results.html`: base64 → `Uint8Array` → 2-D array, one
   `type: 'heatmap'` trace, rgba ramp from transparent to `FLOW_COLORS.soc` (#570df8).
3. Tab wiring: strip the pending attributes, add `data-chart-tab="socprice"` under
   `{% if results.soc_heatmap %}`, new `#socprice-charts` container, extend `selectChartTab`.
4. `chart_soc_price`: `FEATURE_KEYS` → `RETIRED_KEYS`; flip the census assertion in
   `tests/test_smoke.py:638`.
5. Tests, server-side and browser. Spec update.

Two details flagged in the plan and accepted: normalisation is against the OPERATING window
(`cfg.soc_max_kwh`/`soc_min_kwh`), not nameplate, so a battery with a reserve floor still reaches
opaque; and the second chart appears as a heading-only placeholder.

## Obstacles

**The sentinel did not fit in a byte.** The first draft used 256 levels for the ramp plus 256 as
the "no data" sentinel, which does not fit in `uint8`. numpy raised rather than wrapping, so it
would have failed loudly on the first run — but the design was still wrong. Resolved by giving up
one level: 0..254 is the ramp, 255 is the sentinel. The distinction has to be kept because a cell
with no data and a cell at the floor of the operating window both draw as blank, and conflating
them would render a data gap as a flat empty battery.

**A gap cannot be produced from a dataset — followup C11.** The first version of the gap test
wrote NaN into the source frames and asserted the cells came back blank. It failed, and the reason
was not the code under test: `reconcile._resample_sum` applies `np.nan_to_num` (`reconcile.py:93`),
so `isnan(frame.load).sum() == 0` and `gap.sum() == 0` — verified directly. This is exactly C11,
already recorded and deliberately unfixed because changing zero-filling is an ingest question that
would move figures on every panel. Resolved by following the precedent the energy-flows tab set
for the same problem: monkeypatch `simulation_frame` to punch the hole after reconciliation, so
the rule is verified and starts working the moment a hole can reach the frame.

**A `.po` edit script aborted mid-way and lost its earlier edits.** Five of six translations were
applied in memory, then an assertion on the sixth (a long msgid that pybabel had line-wrapped)
raised before the file was written. The compile and test run afterwards looked partially
successful, which is what surfaced it. Re-applied; the wrapped msgid needs its `msgstr` wrapped
the same way.

## Files modified

- `app/results_view.py` — new `_soc_heatmap()` plus `SOC_HEATMAP_LEVELS`/`SOC_HEATMAP_ABSENT`;
  computed in the existing `if frame is not None` block and emitted as `results["soc_heatmap"]`.
  `base64` added to the imports.
- `app/templates/_panel_results.html` — the pending button becomes a real `data-chart-tab`
  button under `{% if results.soc_heatmap %}`; new `#socprice-charts` container with the heatmap
  and the placeholder heading; new `#socprice-data` JSON node. The tab-strip comment rewritten
  (it described a pending tab that no longer exists).
- `app/templates/workspace_results.html` — new `drawSocHeatmap()`; `selectChartTab` generalised
  from two hardcoded containers to a `CHART_TABS` map, so a third tab is a row rather than
  another branch; the draw added to the post-swap path. Deliberately NOT added to the eager
  initial draw — it is the one plot whose cost scales with the window rather than with a fixed
  bucket count.
- `app/features.py` — `chart_soc_price` moved from `FEATURE_KEYS` to `RETIRED_KEYS`.
- `tests/test_results_view.py` — five tests plus a `_decode_heatmap` helper.
- `tests/test_smoke.py` — one browser test; the pending-control census updated to expect zero.
- `app/locales/{nl,en}/LC_MESSAGES/messages.po`, `.mo`, `app/locales/messages.pot` — six new
  msgids, extracted with the documented `pybabel` invocation and translated into Dutch.
- `docs/specs/02-ux-wireframes.md` — §2.4 gains a bullet specifying the tab as built, replacing
  the secondary-axis description; the cost-toggle bullet corrected.
- `docs/specs/followups.md` — C2 closed, C2a opened for the unbuilt price chart.
- `docs/specs/implementation-progress.md` — key moved from the pending table to the retired one.

## Verification

**Measured, not estimated.** A year of 15-minute data: 35,136 cells, **45.8 KB of base64 against
205.9 KB as JSON floats — 4.5×**. That ratio is what made the lazy route unnecessary.

**Every server-side test was checked against a sabotaged implementation**, because a passing test
proves nothing until it is known to be able to fail:

| Sabotage | Caught by |
|---|---|
| Normalise against nameplate instead of the operating window | `..._spans_the_operating_window_not_nameplate_capacity` |
| Bucket rows by interval index (`i % rows`) instead of wall clock | `..._marks_absent_cells_distinctly...` AND `..._columns_are_local_days_including_across_dst` (the DST hole moves from row 2 to row 22) |
| Drop the gap mask, letting carried-forward SoC fill gap cells | `..._blanks_a_data_gap_rather_than_carrying_charge_into_it` |
| Tab shows but never draws (browser) | `..._tab_draws_and_survives_a_recompute` |

The gap sabotage is worth recording: it was NOT caught by the first version of the test suite. The
window-edge test reaches the sentinel through the local-time axis on gap-free data, so it exercises
the encoding but not the rule. That is why the patched-frame test exists as a separate test rather
than as another assertion in the same one.

**The DST behaviour was observed, not argued.** On a 120-day window spanning 29 March 2026, that
column has exactly one absent cell and it is at row 2 — local 02:00, the hour that does not exist
on the spring-forward day. Every other cell of that column is real.

**The browser path was driven before it was written as a test**: tab present, pending affordance
gone, container visible, monthly hidden, one `<image>` element drawn at 876×256, exactly one tab
active, placeholder present once, no page errors — and all of it still true after a period-change
swap, which the existing `restoreChartTab` mechanism handled with no extra wiring.

Full run: **1392 passed, 25 skipped**. `tests/test_benchmark.py` was not run, per the standing
instruction that the benchmark suite is too long.

## Current status

Complete.

Not covered, and flagged rather than silently deferred:
- The second chart (followup C2a). A placeholder by instruction.
- Hover shows date, local time and kWh reconstructed from the quantised level. It was not checked
  against a screen reader, and the colourbar is the only legend.
- Whether the heatmap should overlay or difference against the perfect-foresight benchmark — the
  second of C2's two original open questions, still open.
