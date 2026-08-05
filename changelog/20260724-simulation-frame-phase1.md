# Simulation frame — Phase 1 (per-interval arrays for the §6.6–§6.9 core)

## Task specification

Build the `SimulationFrame` of specs/07-internal-representation.md §4.4: the per-interval
arrays the simulation core will consume, over a resolved window. `reconcile_grid` already
produces the energy arrays and the §6.3 reconstructed load; what was missing is the spot
price resampled onto the SAME simulation grid, plus the frame-shaped container.

Scope of this increment:

1. A per-interval `spot` array resampled from the `price_spot` SeriesFrame onto the grid.
2. A `SimulationFrame` dataclass per §4.4 (index, dt_hours, pv, load, spot, import_obs,
   export_obs).
3. `CLOSURE_TOL = 1e-6` as a shared domain constant (specs §6.14).
4. `simulation_frame(dataset, window) -> SimulationFrame | None`, None on the same
   no-simulatable-grid condition `reconcile_grid` uses.
5. Spec fixtures 21 (mixed native resolutions) and 7 (DST) plus edge-case tests.

Out of scope, deliberately: `spot_min`/`spot_max` (§6.16 bracket), `epoch_id` (§6.15),
`tariff_zone` (§6.4), `quality` (needs the ingest-side per-interval bitfield reconciled
onto the grid). Omitted rather than faked — see below.

## High-level decisions

**New module `app/domain/simframe.py` rather than extending `reconcile.py`.** `reconcile.py`
scopes itself, in its own top comment, to energy reconciliation + §6.3 load reconstruction,
and it is shared with the data-summary band (app/summary_view.py), which has no use for
`spot`. Price resampling has different semantics (mean / forward-fill / NaN, not sum) and a
different consumer (the simulation core, not the band). Keeping them apart means the band
does not import price-resampling code it never calls, and `reconcile_grid` stays exactly
what its docstring says it is. `simframe` builds ON `reconcile_grid` — one reconciliation
path, not two, so the energy arrays cannot diverge between the band and the simulation.

**Price resampling semantics.**

* Finer-than-grid price → arithmetic MEAN of the native prices whose interval-start falls
  in the grid interval (specs §6.2 `resample_price`: `.mean()`). A price is an intensive
  quantity; summing it would be 4× wrong on 15-min→hourly and would still look plausible.
  The mean is energy-UNWEIGHTED, as §6.2 states explicitly.
* Coarser-than-grid price → forward-fill (§6.2 `reindex().ffill()`, reconciliation `held`).
  This is a real case: §6.2's `choose_grid` only lets ENERGY series vote on the grid, so an
  hourly price on a 15-minute grid is reachable.
* No price data for an interval → NaN, never 0. §4.4 is explicit that `spot` has no neutral
  value; an all-zero spot would read as "prices are zero everywhere" and every band
  comparison would take a definite, wrong branch. The frame reports `spot_complete` and
  `spot_missing_intervals` so a caller can refuse to run rather than silently simulate on
  NaN.

**Irregular price series (`resolution_s is None`).** The grid selector already refuses to
let such a series vote (§6.2, open question §8.20), and there is no native spacing to bucket
by. Resolved by treating each price point as valid from its timestamp until the next one —
i.e. the same forward-fill rule as the coarse case, which needs no resolution. This is the
one behaviour §6.2 does not spell out for irregular price; chosen because it follows from
§4.4's "EUR/kWh valid from" definition and degrades to the regular case when spacing happens
to be uniform. Recorded as a resolved ambiguity, not as spec text.

**No `price_spot` slot at all.** The slot is `required` in series_vocab, but the frame
builder must not crash on a dataset assembled before the price arrived (slot-first sources
fill slots one at a time). Resolved: build the frame with an all-NaN `spot` and
`spot_complete = False`. The gate belongs to the run precondition, not to frame
construction.

## Files modified

* `app/domain/simframe.py` (new) — `CLOSURE_TOL`, `SimulationFrame`, `simulation_frame()`,
  the price resampling helpers.
* `tests/test_simframe.py` (new) — fixtures 21 and 7 plus the edge cases.

Nothing else changed; `app/summary_view.py` and `app/results_view.py` are untouched and
their tests stay green unchanged.

## Obstacles and solutions

* Baseline test count in the task brief was 127 passed / 2 skipped; the actual baseline on
  this branch is 133 / 2. Verified before and after so the delta is attributable.
* `reconcile_grid` returns the EFFECTIVE window (grid-meter coverage clipped to the
  requested one), which may differ from what was asked for. `simulation_frame` carries that
  effective window forward and builds `index` from it, so `index`, `spot` and the energy
  arrays are guaranteed the same length.
* An asymmetry surfaced between the two price paths: past the END of price coverage, the
  bucket-mean path left NaN while the forward-fill path held the last price forever. It was
  first documented as a property of the input rather than a policy choice. Review showed
  that framing was wrong and the behaviour with it — see the review fixes below.

## Review fixes (adversarial review, same day)

The review found no arithmetic defect (`_resample_price_mean`, and the ffill boundary rule
`searchsorted(side="right") - 1`, were both verified correct). Three minor issues, all fixed.

### Fix 1 — bound the forward-fill hold, and stop over-claiming completeness

**The defect.** The unbounded hold plus a `spot_complete` defined as "no NaN" made a bad
input look perfect. Verified scenario: a year of 15-minute meters (35,040 intervals) with an
hourly `price_spot` covering only the first 24 hours produced a uniformly-0.42 `spot` across
the whole year, reported as `spot_complete = True`, `spot_missing_intervals = 0`. 99.7% of
the dispatch signal was one stale extrapolated price, and the flag a run precondition gates
on could not see it.

**Decision, in two parts.**

* **Coarse-REGULAR path (`resolution_s is not None`): the hold is BOUNDED** to one
  `resolution_s` past the last good price point; beyond that, NaN. §6.2's `held` semantics
  support exactly this — a price point covers its own declared interval and makes no
  statement past it — and the frame DOES know the declared spacing here. It also makes the
  coarse path symmetric with the bucket-mean path. This is stated in the code as a POLICY
  CHOICE, correcting the earlier "property of the input, not a policy choice" claim, which
  the review rightly called overstated. It is a policy choice, and a different one is now
  being made.
* **Irregular path (`resolution_s is None`): the hold stays UNBOUNDED**, because there is
  genuinely no interval length to bound it by. Inferring one from observed gaps would invent
  a resolution the source never declared, and NaN-ing everything past the last point would
  discard the only statement such a series supports ("valid from"). Instead it is REPORTED.

**New field `spot_extrapolated_intervals`** counts intervals priced by holding the last
point past its own declared interval. After the bounding above, the irregular path is the
only remaining source, so the count is normally 0.

**`spot_complete` redefined** to mean "every interval has an OBSERVED price":
`spot_missing_intervals == 0 and spot_extrapolated_intervals == 0`. Extrapolated intervals
carry a real number that is indistinguishable from an observation in the array, so a run
gating on the flag must not be able to proceed on them. The definition is stated explicitly
in the dataclass docstring, since that flag is the precondition's contract.

The test that pinned the old behaviour, `test_forward_fill_holds_past_the_end_of_price_coverage`,
was rewritten rather than deleted (the case was good; its expectation was wrong) as
`test_forward_fill_is_bounded_to_the_last_price_points_own_interval`.

### Fix 2 — strengthen fixture 21's price test

The old `_QUARTER_PRICES = [0.10, 0.20, 0.30, 0.40]` separated mean from sum, first and
last, but not from two other plausible-but-wrong implementations: the set is SYMMETRIC, so
median == mean == 0.25, and the fixture's energy was UNIFORM (2.0 kWh/hour), so an
energy-weighted mean was numerically identical to the unweighted one. §6.2's
"energy-unweighted" is an explicit spec choice the test could not see violated.

Fixed on both axes:

* Prices are now asymmetric: `[0.10, 0.10, 0.10, 0.50]` → mean 0.20, median 0.10, sum 0.80,
  first 0.10, last 0.50.
* Energy now varies WITHIN the hour, via a 15-minute `solar_production` series of
  `[3.0, 1.0, 1.0, 1.0]` kWh per quarter. It does not move the grid — `choose_grid` takes
  the max resolution over covering energy series and the hourly grid meters are coarser —
  which the test still asserts. Energy-weighted mean ≈ 0.1667 vs unweighted 0.20.

Both numbers are named in a comment at the assertion so a future reader sees which
convention is pinned and that the other was considered rather than overlooked. The
test-module docstring's completeness claim was corrected to match.

### Fix 3 — correct the tz docstring in `_grid_starts`

The docstring asserted the convention was safe: "never `astimezone()`, which would shift by
the local UTC offset". That is backwards for non-UTC-aware input — `.replace(tzinfo=None)`
is the one that shifts, reading a tz-aware non-UTC datetime's wall clock as UTC. Verified: a
requested window of `(2026-01-01 12:00+02:00, 20:00+02:00)` yields `index[0] ==
2026-01-01T12:00:00`, two hours off the true instant.

**Behaviour deliberately unchanged.** The bug is pre-existing and latent: it matches
`reconcile._resample_sum` exactly, and all current callers pass UTC windows. Diverging from
reconcile.py here would be worse than the shared latent bug, because the two would then
disagree about bucket alignment. Only the docstring changed — it now states the actual
precondition (correct GIVEN a UTC window), that the convention matches
`reconcile._resample_sum` deliberately, that the safe general form is
`.astimezone(timezone.utc).replace(tzinfo=None)`, and that this is a known latent issue
shared with reconcile.py. Fixing it belongs in reconcile.py, for both call sites at once.

### Noted and deferred

Adding the `series`-block `reconciliation` assertions to fixture 21 — a real gap, out of
scope for these fixes.

## Current status

Phase 1 implemented, reviewed, and the three review fixes applied. Full suite: 145 passed,
2 skipped — the same counts as before the fixes, with no test outside `test_simframe.py`
touched. Not committed (the orchestrator commits).
