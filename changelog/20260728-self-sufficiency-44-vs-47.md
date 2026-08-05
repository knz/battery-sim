# Self-sufficiency: 44% in the household card vs 47% in the energy-savings tile

## Task specification

User question (investigation only, no code change requested): with the data/config in
`data/local/`, viewing the results page over the "last 6 months" interval, the household
card shows a self-sufficiency of 44% while the self-sufficiency tile under "energy
savings" shows a left-hand (before-battery) figure of 47%. What causes the discrepancy?

## Finding

The two figures are **different quantities by design**, not the same quantity computed
twice. They share a denominator and differ in the numerator.

* Household card (`app/summary_view.py:241`) — **measured** self-sufficiency:
  `1 − rec.imp_total / rec.load_total`, using the import as the METER reported it.
* Energy-savings tile, left half (`app/results_view.py:1406`) — **simulated run A**
  baseline: `1 − a.imp.sum() / load_total`, from `metrics.self_sufficiency_baseline`
  (`app/domain/metrics.py:342`), using the import that the battery-free simulation
  reproduces on the hourly grid.

Measured on the local dataset over the resolved 6-month window
(2026-01-25 14:00Z → 2026-07-26 14:00Z):

| quantity | value |
| --- | --- |
| load (identical on both sides) | 2452.27 kWh |
| measured import | 1366.16 kWh |
| run A import | 1304.37 kWh |
| import difference | 61.80 kWh (4.5 %) |
| measured self-sufficiency | 0.4429 → **44 %** |
| run A self-sufficiency | 0.4681 → **47 %** |

The whole gap is the 61.8 kWh import difference; the denominator is byte-identical
(`simulation_frame`'s load sums to the same 2452.273139 as `reconcile_grid`'s).

The import difference is the §7.1 **resolution loss**: within an interval the household
can import and export at different moments, and the hourly grid nets those against each
other, so the simulated import is systematically *lower* than the meter's. Export shows
the same signature (measured 2118.76 vs run A 2050.98 — a 67.8 kWh difference, i.e. the
same netting seen from the other side).

This is deliberate and documented in place. `results_view.py:1393-1402` records the
decision: the tile is a COMPARISON, so both halves must come from the same information
set (§7.1). Using the measured import for the left half while the right half comes from
run C would mix information sets and inflate the delta — the comment notes it showed
+12 pp where like-for-like is +10 pp on the earlier dataset. The measured figures keep
their place in the data-glance band, which is separately labelled as measured.

So on the current build the tile's delta reads +23 pp (47 % → 70 %). Had the measured
44 % been used on the left, it would have read +26 pp — the flattering-arrow effect the
comment describes.

## Confidence and confounds

The numeric decomposition above is directly measured, not inferred: same denominator,
numerator differs by exactly the reported amount. The *attribution* of the 61.8 kWh to
within-interval import/export netting is well-supported (export moves in the same
direction by a comparable amount, and it matches the §7.1 mechanism the code cites) but
was not independently isolated — e.g. per-interval overlap was not summed directly to
confirm it accounts for the full 61.8 kWh rather than most of it. Other reconstruction
effects (§6.3 clamping) could contribute a share.

The run used `SimulationConfig()` defaults rather than the workspace's persisted
parameter set. That affects runs B/C and hence the tile's RIGHT half (70 %), but not run
A's import or either self-sufficiency figure under discussion — run A is the battery-free
baseline.

## Follow-up request: surface the explanation in the UI

After the investigation the user asked for three additions, in two messages:

1. An ⓘ info icon next to the "Self-sufficiency" title under Energy savings, explaining
   the left (baseline) figure.
2. The same explanation as a caveat, alongside the existing import-discrepancy caveat.
3. The import-discrepancy caveat also as an ⓘ next to "Grid import, no battery" under
   "Where the energy comes from".

### Decisions

**Reused the existing `.slot-info-btn` affordance rather than inventing one.** The
codebase already has a shared ⓘ pattern: one page-level `#slot-info-dialog`, one
delegated click handler in `ha_fetch.js`, and per-button `data-info-title` /
`data-info-body`. The data glance's derived metrics (including the household card's own
self-sufficiency) already use it. It survives fragment swaps, which matters because the
results panel is replaced wholesale on every period change.

**Optional `info_title` / `info_body` keys on the view-model, not template-side
conditionals keyed on the tile name.** The KPI tiles and breakdown rows render from
generic loops shared with `sample_data`. Keying the prose off a title string in the
template would put user-facing text where the reasoning that produces the figure is not.
Tiles and rows without the keys render exactly as before.

**One msgid shared between the import caveat and the row's ⓘ.** The resolution-loss
message is built once and referenced twice (asserted with `is` in the tests). Two copies
would drift apart under editing and cost the translator twice.

**Two units, two caveats.** The existing caveat reconciles the two grid-import figures in
kWh; the new one reconciles the two self-sufficiency percentages. They are one
discrepancy, but the percentages are the pair a reader actually compares — that is what
prompted the original question — and the kWh caveat never names them. The new caveat is
emitted immediately after the existing one, gated on the same resolution-loss threshold
AND on the two percentages actually rounding differently, so it stays silent when there is
no visible difference to explain.

**Register:** `_N` markers translated by the template's `_()` for the tile blurb (no
runtime figures), `_msg` pairs for the caveats and the row ⓘ (they quote kWh/percent
figures). The tile blurb is one paragraph because `ha_fetch.js` sets the dialog body with
`textContent` into a single `<p>` — an embedded newline would render as a space.

### Obstacle: the no-literal-% caveat invariant

`test_no_caveat_contains_a_literal_percent_sign` failed on the new caveat. Its own
docstring records that the original reason (a `newstyle=True` %-formatting corruption
trap) is gone and the rule is now house style — caveats say "0.90 round-trip" where tiles
say "34.2 %". A caveat whose entire purpose is explaining why two percentages differ has
to quote them as percentages; restating them as fractions would describe neither figure as
the page shows it. Narrowed the assertion to exempt that one caveat by prefix, with the
reasoning recorded at both the docstring and the assertion, so any *other* caveat growing
a "%" still fails.

### Files modified

* `app/results_view.py` — `info_title`/`info_body` on the self-sufficiency tile; the
  resolution-loss message hoisted to a variable used by both the row ⓘ and the caveat;
  new self-sufficiency reconciliation caveat.
* `app/templates/_panel_results.html` — ⓘ rendering in the KPI-tile loop (`_()`, plain
  msgid) and in the breakdown-row loop (`msg()`, `_msg` pair).
* `app/locales/{messages.pot,nl/…,en/…}` — extracted, updated with
  `--no-fuzzy-matching`, Dutch translations written by hand, compiled.
* `tests/test_results_view.py` — 4 new tests; narrowed the %-sign invariant.
* `tests/test_results_route.py` — 2 new tests (both the full-page GET and the fragment
  POST; the breakdown-row one builds its own overlap dataset because the shared `client`
  fixture exports nothing and would make the test vacuous).

### Verification

* Full suite: 1188 passed (1182 before this work, 6 added). No test was weakened except
  the documented %-sign exemption.
* Rendered both locales: the Dutch page carries none of the four new English strings and
  all four Dutch ones; the tile blurb, the row ⓘ and both caveats render with figures
  substituted.
* Screenshotted the tile, the breakdown card and both dialogs under headless Chromium.
  The ⓘ glyph shows as a tofu box there — confirmed environmental (a missing font), since
  the pre-existing household-card ⓘ renders identically in the same screenshot.

## Status

Both the investigation and the three requested UI additions are complete and verified.

One thing left open deliberately: the figures differ per period and per config (the
6-month window shows 44% vs 47% under the persisted config, ~22% vs 23% under defaults
over the full year), so the caveat's own threshold — fire whenever the two rounded
percentages differ at all — will sometimes raise it for a 1-point gap. That seemed the
right default, since a 1-point difference between two same-named figures is exactly as
confusing as a 3-point one, but it is a presentation choice that could reasonably be
raised to 2 points if the caveat list feels crowded.
