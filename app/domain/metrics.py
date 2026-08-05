"""The §6.11 energy metrics — the headline figures derived from the §6.9 runs.

Phase 3 (`app/domain/simulate.py`) produces the per-interval flow arrays for runs A, B and C.
This module is the summary of those arrays that panel ③ actually shows: how much grid import the
battery avoided, how hard it was cycled, how much energy the conversion cost, and the two ratios
(self-consumption, self-sufficiency) in each scenario.

It is pure: a `RunSet`, a `SimulationFrame` and a `SimulationConfig` in, a bare-numbers
`EnergyMetrics` out. No formatting, no translation, no I/O — `app/results_view.py` does the
presentation, exactly as `app/summary_view.py` does for `app/domain/reconcile.py`.

## The four things this module has to get right, and why each is easy to get wrong

**1. `saved_pct` divides by the SIMULATED baseline (run A), never by observed import.**
§6.11 states it and §7.1 gives the reason: `A.imp` and `frame.import_obs` come from different
information sets — run A is the reconstructed load resimulated on the grid, `import_obs` is what
the meter recorded — and resolution damage makes them differ. Mixing them produces a percentage
whose error has no sign anyone can reason about. `import_obs` is not read anywhere here.

**2. Equivalent full cycles are counted on the STORAGE side.** `efc = Σ withdrawn / usable
capacity`, not `Σ (dis_home + dis_grid) / capacity`. §6.11 flags the convention explicitly: AC-side
throughput has already paid the discharge conversion, so it gives a figure roughly 5% lower at a
90% round trip. Both quantities are reported (`efc` and `throughput_kwh`) precisely because they
are different numbers with different meanings, and the KPI tile shows them side by side.

**3. Self-consumption is `None` without PV, never 0 and never 1.** Its denominator is Σ PV;
with no PV there is nothing generated to consume and both 0 and 1 would assert something the data
cannot support (§6.11). The same discipline is applied SYMMETRICALLY to self-sufficiency: when the
household load is ~0 both scenarios report None, even though the battery scenario's denominator is
nonzero from standby alone. A household that consumed nothing is not 100% self-sufficient, and a
"0% → 100%" tile would assert exactly that. Both ratios are returned UNCLAMPED — the §2.3a display
clamp to `max(0, ·)` is a presentation decision and belongs to the view, which also has to raise
the caveat that goes with it; clamping here would hide from the view the fact that it clamped.

**3b. Self-consumption is measured over the PV series' OWN coverage, on BOTH sides.** §2.3a is
explicit: "Self-consumption compares PV against export over the PV's window, not the whole window —
comparing six months of production against two years of export would be meaningless." `frame.pv` is
zero-filled outside the PV series' coverage (§4.4 makes it unconditionally an array), so summing it
over the whole window silently widens the export denominator's window while leaving the PV
numerator unchanged, and the ratio drifts by the amount of export that happened before the panels
existed. `energy_metrics` therefore takes an optional `pv_mask` — the grid intervals the PV series
actually covers — and restricts BOTH self-consumption ratios and `pv_kwh` to it. Without a mask the
whole window is used, which is correct for a frame whose PV covers it. The mask does NOT touch
self-sufficiency or any flow total: those are window quantities and restricting them would change
what the headline saving measures.

**4. Conservation does NOT cover any of this.** The fixture-3 identity in `tests/test_simulate.py`
is §6.8 step 5 algebraically rearranged, so on the unconstrained path it closes by construction —
its own docstring demonstrates a genuinely energy-creating mutation (dropping `eta_d` from
`withdrawn`) that leaves it closing perfectly. No metric here may be justified by "conservation
still holds"; every one has a hand-computed fixture in `tests/test_metrics.py`.

## What is deliberately NOT here

    §6.12 benchmarks             runs D and E — Phase 5.
    §6.10 cost accounting        no euro touches this module.
    soc_delta_value_eur          needs a median import price, i.e. a cost model. §6.11 says it is
                                 null without one, so it is absent rather than 0.0 — see
                                 `EnergyMetrics.soc_delta_kwh`.
    intervals_at_max/min_soc     the §4.5 `battery` block carries them; §2.4's secondary row is a
                                 later increment and they need a SoC-bound comparison this module
                                 has no reason to own yet.

Main items:
    SOC_DRIFT_WARN_FRAC   the §6.11 threshold (2%) above which residual SoC is surfaced.
    EnergyMetrics         the §6.11 figures, as bare numbers.
    energy_metrics(runs, frame, cfg) -> EnergyMetrics
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.reconcile import DIV_GUARD_EPS
from app.domain.simconfig import SimulationConfig
from app.domain.simframe import SimulationFrame
from app.domain.simulate import Flows, RunSet

# §6.11 SoC drift correction: "surface the drift when it exceeds `SOC_DRIFT_WARN_FRAC` (2%) of the
# energy saving". The euro-basis twin (`SOC_DRIFT_WARN_FRAC_EUR`, same default, independent
# decision) is not defined here — there is no euro saving to measure against without a cost model,
# and defining a constant nothing can use would invite a later increment to read it as already
# wired. The two tests are a union per §6.11, so adding the euro one can only widen the warning.
SOC_DRIFT_WARN_FRAC = 0.02


def _ratio_or_none(numerator: float, denominator: float) -> float | None:
    """`1 − numerator/denominator`, or None when the denominator is ~0 (§6.11's DIV_GUARD_EPS).

    The shape both §6.11 ratios take. `None` means "not computable for this household", which the
    §4.5 result object distinguishes from a zero measurement and the UI must render as absence.
    """
    if denominator <= DIV_GUARD_EPS:
        return None
    return 1.0 - numerator / denominator


@dataclass(frozen=True)
class EnergyMetrics:
    """The §6.11 energy metrics over one window. Bare numbers; the view formats them.

    Savings (§6.11's first two lines):
        baseline_import_kwh   Σ A.imp — the SIMULATED no-battery import, and the denominator of
                      `saved_pct`. Not the meter's `import_obs`; see the module comment.
        baseline_export_kwh   Σ A.exp.
        battery_import_kwh / battery_export_kwh   Σ C.imp / Σ C.exp — the headline scenario.
        saved_kwh     `A.imp − C.imp`. **May legitimately be NEGATIVE** (§7.2 item 9): a no-PV
                      battery run under an energy-only objective spends kWh on round-trip losses
                      and standby to buy a price spread that this run does not price. Reporting it
                      as a negative saving is correct output, not a fault, and the view must
                      present it as such rather than assuming a positive number.
        saved_pct     `100 × saved_kwh / baseline_import_kwh`, or None when the baseline imported
                      ~nothing. Carries the sign of `saved_kwh`.

    Battery (the §4.5 `battery` block, minus what needs a cost model):
        efc           `Σ C.withdrawn / usable_capacity_kwh` — STORAGE side (§6.11). None when the
                      configured capacity is ~0, which is a broken config rather than a household
                      fact, so a number would be worse than an absence.
        cycles_per_day  `efc / window days`, None when the window has no length.
        throughput_kwh  `Σ (C.dis_home + C.dis_grid)` — the AC side, what the KPI tile calls
                      "N kWh throughput". Deliberately a different number from the `efc`
                      numerator; see the module comment.
        charge_ac_kwh / discharge_ac_kwh   Σ (chg_pv + chg_grid) / Σ (dis_home + dis_grid), run C.
        conversion_loss_kwh   `charge_ac − discharge_ac − (soc_end − soc_start)` (§6.11): AC in,
                      minus AC out, minus the energy still sitting in the battery.
        soc_start_kwh / soc_end_kwh / soc_delta_kwh   the drift correction's inputs and result.
                      `soc_delta_kwh` is ALWAYS reported (§6.11). Its valuation
                      (`soc_delta_value_eur`) is null without a cost model and is therefore not a
                      field here at all — an absent field cannot be misread as a computed zero.
        soc_drift_significant   True when `|soc_delta_kwh|` exceeds SOC_DRIFT_WARN_FRAC of
                      `|saved_kwh|` — the §6.11 surfacing rule. True as well when there is a drift
                      and no saving to measure it against, since a 2% test on a zero base cannot be
                      passed and silence would be the wrong default.
        standby_kwh   `RunSet.standby_kwh` — the EXACT C − B run difference (§6.9), not
                      `standby_w × hours`. The two differ whenever standby was served by PV or by
                      the battery rather than by the grid.
        curtailed_kwh  Σ C.curtailed — PV generated and discarded under the export cap.

    Ratios (§6.11, per scenario). UNCLAMPED — the §2.3a `max(0, ·)` clamp is presentation:
        self_consumption_baseline / self_consumption_battery   `1 − export/pv`, or None without PV.
                      Both are measured over the PV series' OWN coverage when a `pv_mask` is given
                      (§2.3a), so the two sides of the panel-③ row compare like with like.
        self_sufficiency_baseline / self_sufficiency_battery   `1 − import/load`. Defined when the
                      household consumed anything; BOTH are None when load is ~0 — the battery
                      side's denominator is nonzero from standby alone, but reporting 1.0 there
                      would assert a household with no consumption was fully self-sufficient.
                      **The battery-side load is the STANDBY-INCLUSIVE load**, because that is what
                      the household would actually have had to serve with the battery installed;
                      using the bare load there would credit the battery with self-supplying a draw
                      it created.

    Inputs echoed for the view (so it does not re-sum arrays and risk disagreeing):
        pv_kwh        Σ frame.pv over the non-gap intervals, restricted to `pv_mask` when given —
                      the self-consumption denominator, so it is the PV total that ratio divides by.
        load_kwh      Σ frame.load over the non-gap intervals (the whole window; no PV mask).
        window_days   the SIMULATED span in days (`intervals × dt_hours / 24`), the divisor of
                      `cycles_per_day`. Taken from the grid rather than from `frame.window` —
                      see `energy_metrics`.
    """

    baseline_import_kwh: float
    baseline_export_kwh: float
    battery_import_kwh: float
    battery_export_kwh: float
    saved_kwh: float
    saved_pct: float | None

    efc: float | None
    cycles_per_day: float | None
    throughput_kwh: float
    charge_ac_kwh: float
    discharge_ac_kwh: float
    conversion_loss_kwh: float
    soc_start_kwh: float
    soc_end_kwh: float
    soc_delta_kwh: float
    soc_drift_significant: bool
    standby_kwh: float
    curtailed_kwh: float

    self_consumption_baseline: float | None
    self_consumption_battery: float | None
    self_sufficiency_baseline: float | None
    self_sufficiency_battery: float | None

    pv_kwh: float
    load_kwh: float
    window_days: float


def _non_gap_sum(values: np.ndarray, gap: np.ndarray) -> float:
    """Σ `values` over the intervals a run did NOT skip (§7.3 check 3: gaps are excluded).

    `Flows.totals()` already does this for the flow arrays via `nansum`. The FRAME arrays
    (`load`, `pv`) need the same treatment for the ratio denominators, and they need it against the
    run's own gap mask rather than against their own NaNs: run C skips an interval when EITHER
    `load` or `pv` is NaN, so a `nansum` of `load` alone would include intervals whose flows were
    never computed and put the ratios' numerator and denominator on different interval sets.
    """
    return float(np.nansum(values[~gap]))


def energy_metrics(
    runs: RunSet,
    frame: SimulationFrame,
    cfg: SimulationConfig,
    *,
    pv_mask: np.ndarray | None = None,
) -> EnergyMetrics:
    """Compute the §6.11 metrics from runs A/B/C over `frame` under `cfg`.

    Reads the flows through `Flows.totals()` (which decides `nansum` once, in Phase 3) and the
    frame arrays through `_non_gap_sum` against run C's gap mask, so every sum here is over the
    same set of intervals. Runs A and C mark the same gaps — `simulate_baseline` propagates them
    deliberately, so that `saved_kwh` compares like with like — but C's mask is the one used, since
    C is the run whose ratios are computed against the frame arrays.

    `pv_mask` is a per-interval boolean of the grid intervals the PV SERIES actually covers (§2.3a).
    When given, the self-consumption ratios and `pv_kwh` are restricted to it on BOTH sides, so a
    household whose panels were installed part-way through the meter history does not have six
    months of production compared against a year of export. When omitted the whole window is used.
    Nothing else is masked: the flow totals, the saving and self-sufficiency are window quantities.

    Nothing here writes to a frame or flow array.
    """
    a: Flows = runs.a
    c: Flows = runs.c
    ta = a.totals()
    tc = c.totals()

    baseline_import = ta["imp"]
    baseline_export = ta["exp"]
    battery_import = tc["imp"]
    battery_export = tc["exp"]

    # §6.11: saved_kwh = A.imp.sum() − C.imp.sum(); the denominator of saved_pct is the SIMULATED
    # baseline. Guarded so a household that imported ~nothing over the window reports None rather
    # than a percentage of noise — and note the guard is on the DENOMINATOR only: a negative
    # numerator is a legitimate result (§7.2 item 9) and must pass through with its sign.
    saved_kwh = baseline_import - battery_import
    saved_pct = (
        100.0 * saved_kwh / baseline_import if baseline_import > DIV_GUARD_EPS else None
    )

    # §6.11: efc counts on the STORAGE side. `usable_capacity_kwh` is the config's full 0–100%
    # window, NOT the soc_min..soc_max operating window — §6.8 is explicit that the user's SoC
    # limits sit inside usable capacity, and §6.11 divides by the capacity, so a battery held
    # between 10% and 100% reports fewer than one "full cycle" per full traverse of its window.
    capacity = cfg.battery.usable_capacity_kwh
    efc = tc["withdrawn"] / capacity if capacity > DIV_GUARD_EPS else None

    # The window's length, taken from the GRID rather than from `frame.window`. The two agree by
    # construction for a frame built by `simulation_frame` (n intervals × grid_s IS the effective
    # window), and this form additionally works for a frame assembled straight from arrays, where
    # `window` is not populated because the §6.6–§6.9 core never reads it. Using the grid also
    # means `cycles_per_day` divides by the span actually simulated, not by a requested window that
    # reconciliation may have narrowed.
    window_days = frame.intervals * frame.dt_hours / 24.0
    cycles_per_day = efc / window_days if (efc is not None and window_days > 0) else None

    charge_ac = tc["chg_pv"] + tc["chg_grid"]
    discharge_ac = tc["dis_home"] + tc["dis_grid"]
    soc_start = c.soc_start
    soc_end = c.soc_end
    soc_delta = soc_end - soc_start
    # §6.11: "conversion loss = AC in − AC out − energy still sitting in the battery."
    conversion_loss = charge_ac - discharge_ac - soc_delta

    # §6.11's surfacing rule. `abs()` on both sides: drift in either direction distorts the saving,
    # and a negative saving is a legitimate base to measure 2% of. With no saving at all any drift
    # is significant — there is nothing for it to be small relative to.
    drift_base = abs(saved_kwh)
    soc_drift_significant = (
        abs(soc_delta) > SOC_DRIFT_WARN_FRAC * drift_base
        if drift_base > DIV_GUARD_EPS
        else abs(soc_delta) > DIV_GUARD_EPS
    )

    # Frame totals over the intervals run C actually evaluated.
    load_total = _non_gap_sum(frame.load, c.gap)

    # §2.3a: self-consumption is measured over the PV series' OWN coverage. `pv_mask` selects those
    # intervals; the ratio's numerator (export) is restricted to exactly the same ones, so both
    # sides of the fraction — and both scenarios — span one window. `frame.pv` is zero outside PV
    # coverage, so masking the numerator only would leave the export of the pre-PV months in the
    # ratio and bias self-consumption downward.
    sc_gap = c.gap if pv_mask is None else (c.gap | ~pv_mask)
    pv_total = _non_gap_sum(frame.pv, sc_gap)
    baseline_export_pv_window = _non_gap_sum(a.exp, sc_gap)
    battery_export_pv_window = _non_gap_sum(c.exp, sc_gap)
    # `standby_kwh` — the REPORTED figure — is the exact `C.imp − B.imp` run difference §6.9
    # defines: the standby draw as the METER saw it, which is smaller than the parameter-derived
    # figure whenever standby was served by PV or by the battery instead of by the grid.
    standby_kwh = runs.standby_kwh

    # The battery scenario's self-sufficiency denominator is a DIFFERENT quantity, and the two must
    # not be conflated. Self-sufficiency is `1 − import/load`, so its denominator is the load the
    # household had to SERVE — and §6.9 adds the full `standby_kw × dt` to the load in every
    # evaluated interval, regardless of where that energy came from. So this term is the
    # parameter-derived draw (what run C actually simulated as load), not the metered difference
    # `standby_kwh` (what crossed the meter). Using `standby_kwh` here would understate the load a
    # battery-owning household carried and thereby overstate its self-sufficiency, by exactly the
    # standby that PV or the battery covered. Gap intervals are excluded on both sides, matching
    # `load_total`.
    standby_in_load = (
        cfg.battery.standby_w / 1000.0
        * frame.dt_hours
        * float(np.count_nonzero(~c.gap))
    )
    load_total_battery = load_total + standby_in_load

    return EnergyMetrics(
        baseline_import_kwh=baseline_import,
        baseline_export_kwh=baseline_export,
        battery_import_kwh=battery_import,
        battery_export_kwh=battery_export,
        saved_kwh=saved_kwh,
        saved_pct=saved_pct,
        efc=efc,
        cycles_per_day=cycles_per_day,
        throughput_kwh=discharge_ac,
        charge_ac_kwh=charge_ac,
        discharge_ac_kwh=discharge_ac,
        conversion_loss_kwh=conversion_loss,
        soc_start_kwh=soc_start,
        soc_end_kwh=soc_end,
        soc_delta_kwh=soc_delta,
        soc_drift_significant=soc_drift_significant,
        standby_kwh=standby_kwh,
        curtailed_kwh=tc["curtailed"],
        # §6.11: null, never 0 or 1, when there is nothing generated to consume. Both scenarios use
        # the PV-coverage window (§2.3a), numerator and denominator alike.
        self_consumption_baseline=_ratio_or_none(baseline_export_pv_window, pv_total),
        self_consumption_battery=_ratio_or_none(battery_export_pv_window, pv_total),
        # Symmetric null guard: a household with ~no load is not self-sufficient in either
        # scenario. The battery side's denominator (`load_total_battery`) is nonzero from standby
        # alone, so left to itself it would return 1.0 and the tile would read "n/a → 100%". The
        # gate is the BARE load in both cases — the same quantity §6.11 calls the denominator —
        # so the two sides appear and disappear together.
        self_sufficiency_baseline=_ratio_or_none(baseline_import, load_total),
        self_sufficiency_battery=(
            _ratio_or_none(battery_import, load_total_battery)
            if load_total > DIV_GUARD_EPS
            else None
        ),
        pv_kwh=pv_total,
        load_kwh=load_total,
        window_days=window_days,
    )
