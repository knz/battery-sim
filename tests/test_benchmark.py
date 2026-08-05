"""Unit tests for the §6.12 perfect-foresight benchmarks (app/domain/benchmark.py).

Two blocks, in two halves of this file: the ENERGY benchmark (run D) first, then the COST one
(run E) below the banner near the end. The cost half has its own section note covering fixture 20,
the euro drift question and the runtime budget it works to; read it before adding to it.

§6.14's fixture 6 — the BOUND — is the centre of both:

    perfect-foresight saving ≥ every policy saving, for every configuration.

§6.14 calls it "a strong invariant [that] catches most policy and pricing errors", and §6.12 is
specific about how to assert it: **within** each block, in that block's own units — kWh of grid
import avoided for the energy block, euros for the cost one. **Never across blocks**: the
cost-optimal dispatch routinely avoids LESS import than the import-optimal one (measured at
+1.7 kWh on this file's square-wave fixture — see
`test_the_cost_objective_imports_more_than_the_energy_one`), so a cross-block assertion would fail
correctly-built code. Nothing in this file compares a euro figure against a kWh one.

## Two things fixture 6 needs before it can be asserted literally, both discovered by measurement

**1. A liquidating policy run beats the bound on the RAW numbers, and it is not the DP's fault.**
§6.12's terminal constraint forbids the DP from ending below its starting SoC — "without it the DP
simply liquidates the battery and inflates the bound". Nothing imposes the same discipline on the
POLICY run, and §6.11 deliberately does not net the drift out: it reports `soc_end − soc_start` and
surfaces it as a caveat. So a D1 policy that empties a 10 kWh battery over a short window books
~4 kWh of import avoided that it funded by consuming its opening charge, while the DP has to give
that charge back. Measured on a 48-interval square-wave fixture: policy +0.88 kWh against a DP
bound of −1.69 kWh, with the policy's SoC drift at −4.0 kWh. Corrected for drift the ordering is
restored (−3.12 against −1.69).

The raw comparison is therefore between a drift-funded figure and a drift-neutral one, and it is
the SPEC that leaves this open: §6.12 states the terminal constraint against `initial_soc_kwh` and
says nothing about the policy run's endpoint. `_saving_drift_corrected` values each run's residual
SoC at its AC-out worth (`soc_delta × eta_d`) and the fixture is asserted on that, with
`test_fixture_6_raw_bound_holds_when_the_policy_does_not_liquidate` covering the literal form on
the windows where the question does not arise. Flagged in the phase-5 changelog as a spec gap
rather than resolved silently.

**2. A discretised DP has a small, bounded shortfall, and the tolerance is measured not guessed.**
The DP optimises over 101 SoC levels and 41 actions (+2, see `_interval_actions`), and interpolates
`V` between levels. Over 216 configurations — 12 random load draws × 3 charge × 3 discharge
policies × with/without PV — the largest amount by which a policy beat the drift-corrected bound
was **0.025 kWh**, and it never exceeded that. `_DP_SLACK_KWH` is that measured figure, stated as a
constant so a regression that widens it fails rather than being absorbed.

Everything else here targets the four properties §6.12 says the DP must have, one test each,
because Phase 3's review established that the conservation identity cannot validate this kind of
arithmetic — it is §6.8 step 5 rearranged and closes for genuinely energy-creating mutations. Every
claim gets its own fixture.

Frames are built from arrays through `tests/test_simulate._frame`, for the same reason that module
gives: the DP is arrays-in/numbers-out and going through ingest would make each fixture depend on
reconciliation behaviour these tests are not about.
"""

import numpy as np
import pytest

from app.domain.benchmark import (
    ENERGY_OBJECTIVE,
    CostBenchmark,
    CostObjective,
    DispatchResult,
    EnergyBenchmark,
    _DpLimits,
    _dispatch_flows,
    _interval_actions,
    _transition,
    cost_benchmark,
    energy_benchmark,
    perfect_foresight,
)
from app.domain.costs import compute_costs
from app.domain.pricing import price_curves
from app.domain.simconfig import (
    ChargePolicy,
    DischargePolicy,
    FeedinFloorMode,
    PricingConfig,
    SimulationConfig,
)
from app.domain.simulate import SOC_COMPARE_EPS_KWH, _StepLimits, battery_step, run_all
from tests.test_simulate import _cfg, _frame

# The measured worst-case amount by which a policy run beat the drift-corrected bound across 216
# configurations — see the module docstring. This is the DP's discretisation floor at appendix A's
# 101 × 41 grids, NOT a fudge factor: it does not grow with the window, and refining either grid
# shrinks it. A regression that makes the DP genuinely suboptimal will exceed it.
_DP_SLACK_KWH = 0.03


def _saving_drift_corrected(saved_kwh: float, soc_delta_kwh: float, cfg: SimulationConfig) -> float:
    """A run's saving with its residual SoC valued at what the inverter could still deliver.

    §6.11 reports `soc_end − soc_start` precisely because "without it, a policy that simply ends the
    year empty looks better than it is". This applies exactly that correction, so the policy run and
    the DP — which the §6.12 terminal constraint holds to a non-negative drift — are compared on
    the same basis. `× eta_d` because the residual is STORED energy and only `eta_d` of it would
    ever have reached the AC bus, which is the side `saved_kwh` is measured on.
    """
    return saved_kwh + soc_delta_kwh * cfg.eta_d


def _bench(frame, cfg) -> tuple[EnergyBenchmark, float]:
    """Run A/B/C and the §6.12 DP over one frame+config. Returns (block, run C's SoC drift)."""
    runs = run_all(frame, cfg)
    return energy_benchmark(runs.a, runs.c, frame, cfg), runs.c.soc_end - runs.c.soc_start


# ── §6.14 fixture 6: the bound ───────────────────────────────────────────────────────────────


def _fixture_6_configs():
    """Fixture 6's "for every configuration": all 9 policy pairs × with/without PV × 3 capacities.

    §6.14 says the bound holds for EVERY configuration, so the sweep is over the axes that change
    dispatch: the charge policy, the discharge policy, whether there is PV to capture, and how much
    storage there is to move energy with. The bands are set so both a charge band and a discharge
    band actually open over the price series — a fixture in which no band ever fires would exercise
    P2/P3 and D2/D3 as if they were P1/D1 and quietly test one policy nine times.
    """
    n = 96
    hours = np.arange(n)
    for seed in (1, 2, 3):
        rng = np.random.default_rng(seed)
        load = 0.8 + 0.6 * rng.random(n)
        pv_series = 2.2 * np.maximum(0.0, np.sin(hours * np.pi / 12.0))
        spot = 0.05 + 0.25 * np.maximum(0.0, np.sin(hours * np.pi / 12.0 + 1.0))
        for charge in ChargePolicy:
            for discharge in DischargePolicy:
                for has_pv in (False, True):
                    for capacity in (5.0, 10.0, 20.0):
                        frame = _frame(load, pv=pv_series if has_pv else None, spot=spot)
                        cfg = _cfg(
                            charge_policy=charge,
                            discharge_policy=discharge,
                            usable_capacity_kwh=capacity,
                            has_pv=has_pv,
                            band_a=-1.0,
                            band_b=0.10,
                            band_c=0.20,
                            band_d=9.999,
                        )
                        yield frame, cfg


_FIXTURE_6_BENCHED = None


def _fixture_6_benched():
    """The fixture-6 sweep with its benchmark already run — computed once, reused by every test.

    The sweep itself is cheap (~0.01s to build 162 frame/config pairs); the expense is the DP
    inside `_bench`, at ~52 ms per configuration, or ~8.5s for one full pass. Three tests below
    assert three different properties over this same sweep, so recomputing it per test cost ~17s
    of the suite's runtime to arrive at identical numbers three times.

    Sharing the results between tests is safe here rather than merely convenient: `run_all` and
    `energy_benchmark` are pure over the frame and config (neither is mutated by a run, and a
    re-run returns an equal block), and `EnergyBenchmark` is a frozen dataclass, so a consumer
    cannot mutate what the next test will read. The float drift alongside it is immutable too.
    The tests keep one property each — the reason this is a cache and not a merged test.
    """
    global _FIXTURE_6_BENCHED
    if _FIXTURE_6_BENCHED is None:
        _FIXTURE_6_BENCHED = [
            (frame, cfg, *_bench(frame, cfg)) for frame, cfg in _fixture_6_configs()
        ]
    return _FIXTURE_6_BENCHED


def test_fixture_6_perfect_foresight_bounds_every_policy():
    """§6.14 fixture 6, over 162 configurations, in the ENERGY block's own units.

    Asserted on the DRIFT-CORRECTED saving on both sides — see the module docstring for the
    measurement that showed why, and for why `_DP_SLACK_KWH` is 0.03 rather than 0. Both sides go
    through the same `_saving_drift_corrected`, so neither run is being given a correction the
    other is denied.
    """
    checked = 0
    for _frame_, cfg, bench, policy_drift in _fixture_6_benched():
        policy = _saving_drift_corrected(bench.policy_saved_kwh, policy_drift, cfg)
        bound = _saving_drift_corrected(
            bench.perfect_foresight_saved_kwh, bench.soc_end_kwh - bench.soc_start_kwh, cfg
        )
        assert bound >= policy - _DP_SLACK_KWH, (
            f"fixture 6 violated: policy {policy:.4f} kWh beat the bound {bound:.4f} kWh "
            f"under {cfg.policy.charge_policy.value}/{cfg.policy.discharge_policy.value}, "
            f"has_pv={cfg.has_pv}, capacity={cfg.battery.usable_capacity_kwh}"
        )
        checked += 1
    assert checked == 162, f"the sweep shrank to {checked} configurations"


def test_fixture_6_raw_bound_holds_when_the_policy_does_not_liquidate():
    """The LITERAL fixture-6 form — no drift correction — on a window where drift is not the issue.

    This is the form §6.14 actually writes, and it must hold whenever the comparison is fair. The
    fixture is a PV household on P1/D1 over four days with a capacity small enough that the battery
    cycles daily and ends near where it began, so neither run is funded by its opening charge.
    """
    n = 96
    hours = np.arange(n)
    frame = _frame(
        0.8 + 0.2 * np.sin(hours * np.pi / 6.0),
        pv=2.5 * np.maximum(0.0, np.sin(hours * np.pi / 12.0)),
    )
    cfg = _cfg(
        charge_policy=ChargePolicy.P1,
        discharge_policy=DischargePolicy.D1,
        usable_capacity_kwh=5.0,
        initial_soc_pct=10.0,  # start at the floor: there is no opening charge to liquidate
    )
    bench, policy_drift = _bench(frame, cfg)
    assert policy_drift >= -SOC_COMPARE_EPS_KWH, "fixture precondition: the policy must not liquidate"
    assert bench.perfect_foresight_saved_kwh >= bench.policy_saved_kwh - _DP_SLACK_KWH
    assert bench.capture_ratio is not None
    assert bench.capture_ratio <= 1.0 + 1e-6, "a capture ratio above 1 means the bound was beaten"


def test_capture_ratio_is_never_above_one_across_the_sweep():
    """A ratio above 1.0 is impossible and means a defect — asserted across fixture 6's sweep.

    Separate from the bound test because it is the form the VIEW shows: the panel prints a percent,
    and "captures 112 percent" is the shape a defect takes on screen. The ratio is unclamped on
    purpose (see `EnergyBenchmark`), so this is a real check and not a tautology.

    Restricted twice, and both restrictions are about what the ratio MEANS rather than about making
    the test pass:

      * to configurations where the policy did not liquidate, for the same reason the bound test
        corrects for drift — a raw ratio computed against a drift-funded numerator is not the
        quantity this invariant is about; and
      * to configurations where the BOUND is positive. When even perfect foresight loses energy over
        the window (a no-PV battery paying standby and round-trip losses with no PV to capture —
        §7.2 item 9's case), the ratio is a quotient of two negative numbers and "captures 296
        percent" is arithmetic, not a capture. The "≤ 1" invariant is a statement about a positive
        ceiling; on a negative one the meaningful assertion is the BOUND itself, which
        `test_fixture_6_perfect_foresight_bounds_every_policy` already makes over the same sweep.
        The view is unaffected — the gloss prints the ratio only through that same path — but this
        is a real edge the panel can reach, and it is recorded here rather than hidden by a clamp.
    """
    checked = 0
    for _frame_, cfg, bench, policy_drift in _fixture_6_benched():
        if policy_drift < -SOC_COMPARE_EPS_KWH or bench.capture_ratio is None:
            continue
        if bench.perfect_foresight_saved_kwh <= 0.0:
            continue
        assert bench.capture_ratio <= 1.0 + 1e-6
        checked += 1
    assert checked > 0, "the sweep no longer contains a positive-bound configuration"


# ── §6.12's second invariant: the two export baselines ───────────────────────────────────────


def test_unconstrained_bound_is_at_least_the_inheriting_one():
    """§6.12/fixture 6: `unconstrained ≥ inheriting`, because it optimises over a SUPERSET.

    Note what this does NOT claim. On the ENERGY objective the two are usually EQUAL even with
    export off, and that is correct rather than a missed opportunity: exporting battery energy earns
    revenue but avoids no grid import, so the export permission cannot change an import-minimising
    dispatch. The invariant is `≥`, and the interesting divergence belongs to the §6.12 cost
    benchmark. Asserted across the sweep so a future change that makes the unconstrained DP somehow
    do WORSE — the only way this can fail — is caught.
    """
    for _frame_, cfg, bench, _drift_ in _fixture_6_benched():
        assert bench.perfect_foresight_saved_kwh_unconstrained is not None
        assert (
            bench.perfect_foresight_saved_kwh_unconstrained
            >= bench.perfect_foresight_saved_kwh - 1e-9
        )


def test_unconstrained_fields_are_null_when_export_is_allowed():
    """§6.12: with `allow_grid_export` ON the second DP is SKIPPED and the fields are None.

    "Provably identical, not merely similar" — so the fields must be None and never
    equal-and-present. An equal-and-present pair would tell a reader that two DPs ran and agreed,
    which is a different (and unearned) claim from "one DP ran because the second could not differ".
    """
    frame = _frame(np.full(48, 1.0), spot=np.full(48, 0.10))
    cfg = _cfg(allow_grid_export=True)
    bench, _ = _bench(frame, cfg)
    assert bench.perfect_foresight_saved_kwh_unconstrained is None
    assert bench.capture_ratio_unconstrained is None
    assert bench.bound_import_kwh_unconstrained is None
    # …and the inheriting figure IS present: skipping the second pass must not skip the first.
    assert bench.perfect_foresight_saved_kwh == pytest.approx(
        bench.baseline_import_kwh - bench.bound_import_kwh
    )


def test_both_baselines_are_present_when_export_is_forbidden():
    """The default (export off) runs BOTH DPs — the mirror of the test above."""
    frame = _frame(np.full(48, 1.0), spot=np.full(48, 0.10))
    cfg = _cfg(allow_grid_export=False)
    bench, _ = _bench(frame, cfg)
    assert bench.perfect_foresight_saved_kwh_unconstrained is not None
    assert bench.bound_import_kwh_unconstrained is not None


# ── §6.12's terminal constraint ──────────────────────────────────────────────────────────────


def test_terminal_constraint_binds_and_the_dp_does_not_liquidate():
    """§6.12: "Without it the DP simply liquidates the battery and inflates the bound."

    The fixture is built so liquidation is exactly what an unconstrained DP would do: a household
    with no PV, a flat price (so there is no arbitrage to reward holding charge), and a battery that
    starts FULL. Every kWh of the opening 9 kWh could be discharged into the load for a free 9 kWh
    of avoided import, and a DP without the terminal constraint takes all of it.

    Asserted three ways, because "the constraint is present" and "the constraint bound" are
    different claims: the DP's final SoC is at or above its starting SoC; the bound is finite and
    sane (it cannot exceed the baseline import, which is what avoiding ALL import would give); and
    the bound is far below the liquidation figure the unconstrained DP would have produced.
    """
    n = 48
    frame = _frame(np.full(n, 1.0), spot=np.full(n, 0.10))
    cfg = _cfg(initial_soc_pct=100.0, usable_capacity_kwh=10.0, min_soc_pct=10.0)

    result = perfect_foresight(frame, cfg)

    # 1. The constraint held: the battery ended at or above where it started.
    assert result.soc_end >= result.soc_start - SOC_COMPARE_EPS_KWH
    assert result.soc_start == pytest.approx(10.0)  # 100% of 10 kWh, clamped into [1, 10]

    # 2. The bound is finite and sane. The ceiling is the baseline PLUS the standby draw, not the
    #    baseline alone: run A has no battery and therefore no parasitic load (§6.9), while the DP
    #    is running a battery and pays standby in every interval it cannot avoid. Comparing against
    #    the bare baseline would assert that the DP must beat a run that has a cost it does not.
    baseline_import = float(np.nansum(run_all(frame, cfg).a.imp))
    standby_over_window = cfg.standby_kw * frame.dt_hours * n
    assert np.isfinite(result.import_kwh)
    assert 0.0 <= result.import_kwh <= baseline_import + standby_over_window + _DP_SLACK_KWH

    # 3. It is nowhere near the liquidation figure. With no PV and a flat price the constrained DP
    #    can do nothing useful, so its import is the load plus standby — it does NOT get to spend
    #    the 9 kWh sitting above the floor. Asserted as an inequality against that 9 kWh rather than
    #    by re-running a mutated DP, which would be testing a second implementation.
    liquidation_credit = (cfg.soc_max_kwh - cfg.soc_min_kwh) * cfg.eta_d
    assert liquidation_credit > 8.0  # fixture sanity: there IS a large credit to be tempted by
    assert (
        result.import_kwh
        > baseline_import + standby_over_window - liquidation_credit + 1.0
    )


def test_terminal_constraint_is_measured_against_the_clamped_initial_soc():
    """An `initial_soc_pct` below the floor is clamped (§6.9), and the constraint follows it there.

    Phase 2 WARNS about an initial SoC outside the operating window rather than blocking it, and
    §6.9 clamps it before the first interval. The DP has to clamp identically, or its terminal
    constraint would be stated against an SoC the battery can never be in and every trajectory would
    be infeasible.
    """
    frame = _frame(np.full(24, 1.0))
    cfg = _cfg(usable_capacity_kwh=10.0, min_soc_pct=20.0, initial_soc_pct=5.0)
    result = perfect_foresight(frame, cfg)
    assert result.soc_start == pytest.approx(cfg.soc_min_kwh)  # clamped up to 2.0, not left at 0.5
    assert np.isfinite(result.import_kwh)
    assert result.soc_end >= result.soc_start - SOC_COMPARE_EPS_KWH


def test_the_starting_soc_is_an_exact_state_grid_level():
    """The SoC grid carries `initial_soc_kwh` exactly — the property the terminal constraint needs.

    On a plain `linspace` the starting SoC almost never lands on a level, and then EVERY level below
    it is terminal-infeasible while the nearest level above is strictly more charged than the run
    actually starts. The DP is forced to charge before it may do anything, and its "bound" comes out
    worse than standing still — measured at 123.05 kWh against 122.80 on a 96-interval no-PV
    fixture, i.e. not an upper bound at all. `_DpLimits.of` therefore moves the nearest level onto
    the starting SoC.

    Also asserts the two properties the move must not break: the level COUNT is unchanged, and the
    grid stays sorted (`np.interp` requires it).
    """
    # 2.5 kWh sits between levels 2.48 and 2.525 on the default 101-level grid over [1, 10].
    cfg = _cfg(usable_capacity_kwh=10.0, min_soc_pct=10.0, initial_soc_pct=25.0)
    lim = _DpLimits.of(cfg, 1.0, allow_grid_export=False)
    assert cfg.initial_soc_kwh == pytest.approx(2.5)
    assert np.any(np.isclose(lim.soc_levels, 2.5, atol=1e-12))
    assert len(lim.soc_levels) == cfg.dp_soc_levels
    assert np.all(np.diff(lim.soc_levels) > 0), "np.interp needs a strictly increasing grid"


def test_the_dp_never_does_worse_than_standing_still():
    """The bound must be at most the import of doing nothing — the trivially available trajectory.

    "Hold the starting SoC and take no action" is always feasible under the terminal constraint, and
    it imports exactly `load + standby`. A DP that returns more than that is not optimising; this is
    the assertion that caught the off-grid starting-SoC defect above, and it is kept because it is
    the cheapest possible detector for a whole class of DP breakage.
    """
    n = 96
    rng = np.random.default_rng(11)
    load = 1.0 + 0.5 * rng.random(n)
    frame = _frame(load)
    cfg = _cfg(charge_policy=ChargePolicy.P1, discharge_policy=DischargePolicy.D1, has_pv=False)
    do_nothing_import = float(load.sum()) + cfg.standby_kw * frame.dt_hours * n
    assert perfect_foresight(frame, cfg).import_kwh <= do_nothing_import + 1e-9


# ── §6.12's interpolation requirement ────────────────────────────────────────────────────────


def _backward_value_at_start(frame, cfg, *, snap: bool) -> float:
    """The DP's own VALUE ESTIMATE at the starting SoC — with `interp(V)` or with nearest snapping.

    Written out here rather than parameterised into the production module on purpose: a flag that
    selects the wrong algorithm is a flag someone can leave set. This is a TEST-only twin.

    **It returns the backward pass's estimate, not a realised dispatch's import**, and both variants
    are read the same way. That is the only comparison that isolates the interpolation: the
    interpolating DP's realised import comes from a forward pass the snapping variant does not have,
    so comparing an estimate against a realisation would measure the two passes' disagreement rather
    than the approximation §6.12 is talking about.
    """
    from app.domain.benchmark import DP_INF, _interval_actions, _transition

    lim = _DpLimits.of(cfg, frame.dt_hours, allow_grid_export=cfg.allow_grid_export)
    n = frame.intervals
    gap = np.isnan(frame.load) | np.isnan(frame.pv)
    load = frame.load + lim.standby_kwh
    soc_col = lim.soc_levels[:, None]
    n_soc = len(lim.soc_levels)

    V = np.zeros(n_soc)
    V[lim.soc_levels < lim.soc_start_kwh - SOC_COMPARE_EPS_KWH] = DP_INF
    values = np.empty((n + 1, n_soc))
    values[n] = V
    for i in range(n - 1, -1, -1):
        if gap[i]:
            values[i] = V
            continue
        acts = _interval_actions(float(load[i]), float(frame.pv[i]), lim)[None, :]
        tr = _transition(soc_col, acts, float(load[i]), float(frame.pv[i]), lim)
        # THE difference: snap to the nearest level instead of interpolating.
        if snap:
            vn = V[np.abs(tr.soc_next[..., None] - lim.soc_levels).argmin(axis=-1)]
        else:
            vn = np.interp(tr.soc_next, lim.soc_levels, V)
        V = np.where(tr.feasible, tr.imp + vn, DP_INF).min(axis=1)
        values[i] = V
    # The starting SoC IS a grid level by construction (`_DpLimits.of`), so this lookup is exact.
    return float(values[0][int(np.abs(lim.soc_levels - lim.soc_start_kwh).argmin())])


def test_interpolating_v_differs_measurably_from_nearest_snapping():
    """§6.12 requires `interp(V)` and forbids nearest-SoC snapping; this pins that interp is used.

    The test §6.12's own wording suggests — snapping is "a systematic pessimism bias of several
    percent", so the snapped figure should come out HIGHER — does not reproduce. Measured on a
    96-interval PV fixture at 21 SoC levels, snapping gives 17.41 kWh against interpolation's 27.59,
    and it converges UPWARD toward the interpolated value as the grid refines (9.41 at 11 levels,
    22.72 at 51, 27.13 at 401, against a stable ~27.56 for interpolation from 11 levels onward).

    So on this DP nearest-snapping is **optimistic, not pessimistic**, and that is the more serious
    of the two failure modes. Snapping rounds a landing SoC to whichever level is nearest, including
    upward, which credits the battery with energy it does not have — a small energy leak at every
    transition, compounding over 8,760 of them. The resulting figure is not merely biased, it is
    UNATTAINABLE: 17.41 kWh sits below the 27.64 kWh the realised dispatch actually achieves, so a
    bound built on it could not be reached by any dispatch and would be no bound at all. §6.12's
    conclusion — use interpolation — is right; its stated reason appears to understate the problem.
    Recorded rather than reconciled: the phase-5 changelog flags the wording.

    The assertion is therefore on the two properties that are demonstrable: the two variants differ
    far beyond float noise (so `np.interp` cannot have been quietly replaced by a lookup), and the
    interpolating variant's estimate is consistent with a realisable dispatch while the snapping
    one's is not.
    """
    n = 96
    hours = np.arange(n)
    frame = _frame(
        1.0 + 0.4 * np.sin(hours * np.pi / 6.0),
        pv=2.5 * np.maximum(0.0, np.sin(hours * np.pi / 12.0)),
        spot=0.05 + 0.25 * np.maximum(0.0, np.sin(hours * np.pi / 12.0 + 1.0)),
    )
    cfg = _cfg(usable_capacity_kwh=10.0, dp_soc_levels=21)  # coarse grid: the divergence is visible

    lim = _DpLimits.of(cfg, frame.dt_hours, allow_grid_export=False)
    assert lim.soc_levels[1] - lim.soc_levels[0] > 0.3  # the grid really is coarse enough to bite

    interpolated = _backward_value_at_start(frame, cfg, snap=False)
    snapped = _backward_value_at_start(frame, cfg, snap=True)
    realised = perfect_foresight(frame, cfg).import_kwh

    assert abs(snapped - interpolated) > 1.0, (
        f"nearest-snapping ({snapped:.4f} kWh) and interpolation ({interpolated:.4f} kWh) should "
        f"differ measurably on this grid; if they agree, `np.interp` is not being used"
    )
    # The interpolating estimate is consistent with the dispatch the forward pass actually achieves…
    assert interpolated == pytest.approx(realised, abs=0.5)
    # …and the snapping one is not: it claims an import total no dispatch reaches.
    assert snapped < realised - 1.0


def test_interpolation_is_stable_under_soc_grid_refinement():
    """Interpolation's estimate barely moves as the SoC grid refines — snapping's moves a lot.

    The companion to the test above, and the sharper statement of why §6.12 requires interpolation:
    a correct DP's answer should be insensitive to a discretisation parameter, because the
    discretisation is an implementation detail and not a modelling choice. Across 11 → 201 SoC
    levels the interpolating estimate moves by well under a kWh while the snapping twin moves by
    almost twenty.
    """
    n = 96
    hours = np.arange(n)
    frame = _frame(
        1.0 + 0.4 * np.sin(hours * np.pi / 6.0),
        pv=2.5 * np.maximum(0.0, np.sin(hours * np.pi / 12.0)),
        spot=0.05 + 0.25 * np.maximum(0.0, np.sin(hours * np.pi / 12.0 + 1.0)),
    )
    interp_values, snap_values = [], []
    for levels in (11, 51, 201):
        cfg = _cfg(usable_capacity_kwh=10.0, dp_soc_levels=levels)
        interp_values.append(_backward_value_at_start(frame, cfg, snap=False))
        snap_values.append(_backward_value_at_start(frame, cfg, snap=True))

    assert max(interp_values) - min(interp_values) < 1.0, (
        f"interpolation should be near-insensitive to the SoC grid, but moved by "
        f"{max(interp_values) - min(interp_values):.4f} kWh"
    )
    assert max(snap_values) - min(snap_values) > 5.0, (
        "the snapping twin should be strongly grid-dependent; if it is not, the twin is broken "
        "and the comparison above proves nothing"
    )


# ── Like-for-like with run C: the DP obeys the same physics ──────────────────────────────────


def test_dp_transition_agrees_with_battery_step():
    """The DP's vectorised transition reproduces §6.8's scalar `battery_step`, action for action.

    This is the test that manages the one real risk in this module: `_transition` is a second
    implementation of §6.8's steps, written for arrays, and two implementations of one step function
    can drift. Driving both over a grid of SoC states and signed actions — charging, discharging and
    idle, with and without PV — pins them together.

    The actions are translated into `battery_step`'s REQUEST form the way §6.6/§6.7 would state
    them: a charge action asks for grid charging (PV surplus is offered separately and PV-first
    ordering does the rest), a discharge action asks to serve the house first. That translation is
    the point of contact, and it is where a divergence would show.

    **The grid is run under TWO configs, and the second one is why.** `_transition` has four clamp
    paths — SoC headroom (step 3), available energy (step 4), the import cap and the export cap
    (step 6) — and the original single config gave `max_import_kw = max_export_kw = 5.75`, which no
    combination in the grid ever reached. Instrumented across all 140 combinations: headroom 16
    hits, available-energy 24 hits, import cap **0**, export cap **0**. So the test named itself
    the manager of "the one real risk in this module" while leaving half the risk untested. The
    second config adds a binding 2 kW fuse and a tight 0.5 kW export cap, which puts every path in
    scope. This is about test POWER, not a suspected bug: an independent 16,000-pair fuzz of the
    two implementations found zero divergence.
    """
    configs = (
        _cfg(usable_capacity_kwh=10.0, min_soc_pct=10.0),
        # A binding fuse and a tight export cap, so §6.8 step 6's two branches are actually taken.
        # 2.0 kW import against charge actions up to 5 kW forces the grid-charging shed; 0.5 kW
        # export against 5 kW discharge actions into a small deficit forces the battery-to-grid
        # shed and then the PV curtailment behind it.
        _cfg(
            usable_capacity_kwh=10.0,
            min_soc_pct=10.0,
            max_import_kw_override=2.0,
            max_export_kw=0.5,
        ),
    )
    for cfg in configs:
        lim_dp = _DpLimits.of(cfg, 1.0, allow_grid_export=True)
        lim_step = _StepLimits.of(cfg, 1.0)

        for load_kwh, pv_kwh in ((2.0, 0.0), (0.5, 3.0), (3.0, 1.0), (0.0, 0.0)):
            for soc in (1.0, 2.5, 5.0, 8.0, 10.0):
                for action in (-5.0, -2.0, -0.25, 0.0, 0.25, 2.0, 5.0):
                    tr = _transition(
                        np.array([[soc]]), np.array([[action]]), load_kwh, pv_kwh, lim_dp
                    )
                    # The same action expressed as §6.6/§6.7 requests.
                    pv_surplus = max(0.0, pv_kwh - load_kwh)
                    chg = max(0.0, -action)
                    req_pv = min(pv_surplus, chg)
                    req_grid_chg = chg - req_pv
                    dis = max(0.0, action)
                    req_home = min(dis, max(0.0, load_kwh - pv_kwh))
                    req_grid_dis = dis - req_home
                    soc_step, flows, _ = battery_step(
                        soc, req_pv, req_grid_chg, req_home, req_grid_dis,
                        load_kwh, pv_kwh, lim_step,
                    )
                    where = (
                        f"soc={soc}, action={action}, load={load_kwh}, pv={pv_kwh}, "
                        f"imp_cap={lim_dp.imp_cap_kwh}, exp_cap={lim_dp.exp_cap_kwh}"
                    )
                    assert tr.soc_next[0, 0] == pytest.approx(soc_step, abs=1e-9), (
                        f"SoC diverged at {where}"
                    )
                    assert tr.imp[0, 0] == pytest.approx(flows.imp, abs=1e-9), (
                        f"import diverged at {where}"
                    )


def test_dp_respects_the_import_connection_limit():
    """§6.8 step 6: the DP cannot draw more than the connection passes, same as run C.

    A 1×25 A connection is 5.75 kW, so on hourly data no interval may import more than 5.75 kWh. The
    fixture gives the DP every incentive to breach it — a big battery, a large charge rate and a
    price that begs for grid charging — and the assertion is on the realised per-interval import.
    """
    n = 48
    frame = _frame(np.full(n, 1.0), spot=np.full(n, 0.01))
    cfg = _cfg(
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        usable_capacity_kwh=40.0,
        max_charge_kw=20.0,
        max_discharge_kw=20.0,
        phases=1,
        fuse_a=25.0,
    )
    result = perfect_foresight(frame, cfg)
    cap = cfg.max_import_kw * frame.dt_hours
    assert cap == pytest.approx(5.75)
    assert np.nanmax(result.imp) <= cap + 1e-9


def test_dp_respects_the_export_connection_limit():
    """§6.8 step 6, export side: PV beyond the cap is curtailed for the DP as for run C.

    Asserted through the SoC trace and the import series rather than an export array (the DP does
    not build one, since it minimises import): with a hard 1 kW export cap and 5 kW of PV, the DP
    must still not import, and must still respect its SoC window — a DP that ignored the cap would
    show no difference here, so the real assertion is the companion below on the bound moving.
    """
    n = 48
    hours = np.arange(n)
    pv = 5.0 * np.maximum(0.0, np.sin(hours * np.pi / 12.0))
    frame = _frame(np.full(n, 0.2), pv=pv)
    tight = _cfg(usable_capacity_kwh=5.0, max_export_kw=1.0)
    loose = _cfg(usable_capacity_kwh=5.0, max_export_kw=100.0)
    # The export cap is a household constraint, not a battery one, so it changes the BASELINE too
    # (§7.2 item 1) — which is why the comparison is on the raw import totals, not on the saving.
    assert perfect_foresight(frame, tight).import_kwh == pytest.approx(
        perfect_foresight(frame, loose).import_kwh, abs=1e-9
    ), "an export cap should not change the import-minimising dispatch's import total"
    assert np.all(perfect_foresight(frame, tight).soc <= tight.soc_max_kwh + SOC_COMPARE_EPS_KWH)


def test_dp_carries_the_standby_draw_like_run_c():
    """§6.9: standby is added to the LOAD, and the DP pays it exactly as run C does.

    Two runs differing only in `standby_w`; the DP's import must rise by the full standby draw over
    the window, because a parasitic load is served from somewhere in every evaluated interval and no
    dispatch can avoid it. A DP that omitted standby would report a lower bound than the policy
    could ever reach and would flatter every capture ratio.
    """
    n = 48
    frame = _frame(np.full(n, 1.0))
    without = _cfg(standby_w=0.0)
    with_standby = _cfg(standby_w=50.0)
    delta = (
        perfect_foresight(frame, with_standby).import_kwh
        - perfect_foresight(frame, without).import_kwh
    )
    assert delta == pytest.approx(0.050 * frame.dt_hours * n, abs=1e-6)


def test_dp_ignores_the_users_price_bands():
    """§6.12: the DP "does **not** obey the user's price bands — that is the point."

    Two configurations differing ONLY in the bands, which change run C's dispatch substantially. The
    DP's answer must be bit-identical, because the bands are the decision rule perfect foresight
    replaces. If this fails, the benchmark is measuring the user's bands against themselves and the
    capture ratio means nothing.
    """
    n = 96
    hours = np.arange(n)
    frame = _frame(
        np.full(n, 1.0), spot=0.05 + 0.25 * np.maximum(0.0, np.sin(hours * np.pi / 12.0))
    )
    narrow = _cfg(charge_policy=ChargePolicy.P2, discharge_policy=DischargePolicy.D2,
                  band_a=-1.0, band_b=0.06, band_c=0.28, band_d=9.999)
    wide = _cfg(charge_policy=ChargePolicy.P2, discharge_policy=DischargePolicy.D2,
                band_a=-1.0, band_b=0.20, band_c=0.10, band_d=9.999)
    a, b = perfect_foresight(frame, narrow), perfect_foresight(frame, wide)
    assert a.import_kwh == pytest.approx(b.import_kwh, abs=1e-12)
    # …and the bands really did change the POLICY run, so the test above is not vacuous.
    assert float(np.nansum(run_all(frame, narrow).c.imp)) != pytest.approx(
        float(np.nansum(run_all(frame, wide).c.imp)), abs=1e-6
    )


def test_gaps_are_skipped_exactly_as_run_c_skips_them():
    """§6.9's gap rule: NaN load or pv → no energy moves, SoC carries forward, import is NaN.

    The DP and run C must exclude the SAME intervals, or `A.imp − D.imp` and `A.imp − C.imp` would
    be sums over different interval sets and fixture 6 would compare unlike things.
    """
    load = np.array([1.0, 1.0, np.nan, 1.0, 1.0, np.nan])
    frame = _frame(load)
    cfg = _cfg()
    result = perfect_foresight(frame, cfg)
    runs = run_all(frame, cfg)
    assert list(result.gap) == list(runs.c.gap)
    assert np.isnan(result.imp[2]) and np.isnan(result.imp[5])
    assert result.imp[2:3].size == 1  # sanity: indexing is what it looks like
    # The SoC is CARRIED across the gap, not reset or left undefined.
    assert result.soc[2] == pytest.approx(result.soc[1])
    assert result.soc[5] == pytest.approx(result.soc[4])
    # And the total excludes them (nansum), matching Flows.totals().
    assert result.import_kwh == pytest.approx(float(np.nansum(result.imp)))


def test_the_dp_never_modifies_the_frame_arrays():
    """The frame's arrays are shared with app/summary_view.py and must not be written to (§6.9).

    `frame.load + standby` REBINDS; an `+=` would change numbers already published elsewhere in the
    app, silently and for the life of the process.
    """
    frame = _frame(np.array([1.0, 2.0, 1.5, 0.5]), pv=np.array([0.0, 1.0, 3.0, 0.0]))
    before = (frame.load.copy(), frame.pv.copy(), frame.spot.copy())
    energy_benchmark(*[getattr(run_all(frame, _cfg()), k) for k in ("a", "c")], frame, _cfg())
    assert np.array_equal(frame.load, before[0])
    assert np.array_equal(frame.pv, before[1])
    assert np.array_equal(frame.spot, before[2], equal_nan=True)


# ── Hand-computed scenarios ──────────────────────────────────────────────────────────────────
#
# §6.14's discipline, and Phase 3's review conclusion restated: the conservation identity CANNOT
# validate this arithmetic — it is §6.8 step 5 rearranged and closes even for energy-creating
# mutations. Every claim here is a number derived from the spec by hand, not from the code.


def test_hand_computed_two_interval_dispatch():
    """A scenario whose import-minimising dispatch is obvious by inspection, asserted as literals.

    Two hourly intervals, a lossless battery (RTE 1.0, so eta_c = eta_d = 1), no standby, no PV:

        interval 0:  load 0 kWh
        interval 1:  load 4 kWh

    The battery is 10 kWh usable with a 0–100 percent window, starting at 50 percent = 5.0 kWh, and
    can charge or discharge 5 kW. The terminal constraint requires ending at or above 5.0 kWh.

    By inspection: interval 1's 4 kWh of load can be served entirely from the battery, taking the
    SoC from 5.0 to 1.0 — but the terminal constraint forbids ending below 5.0. So the battery must
    first import the energy it will later discharge. In interval 0 it charges 4 kWh from the grid
    (within the 5 kW rating), importing 4 kWh and reaching 9.0 kWh; in interval 1 it discharges
    4 kWh into the load, importing 0 and returning to 5.0 kWh.

        total import = 4 + 0 = 4 kWh,  final SoC = 5.0 kWh

    which is exactly what doing nothing costs (0 + 4 = 4 kWh) — the battery is lossless, so shifting
    the import is free but buys nothing on an ENERGY objective. The number to pin is therefore 4.0:
    a DP that reported LESS has broken the terminal constraint, and one that reported MORE has paid
    a loss a lossless battery does not have.
    """
    frame = _frame([0.0, 4.0])
    cfg = _cfg(
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=50.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        roundtrip_efficiency=1.0,
        standby_w=0.0,
        has_pv=False,
    )
    result = perfect_foresight(frame, cfg)
    assert result.import_kwh == pytest.approx(4.0, abs=1e-9)
    assert result.soc_end == pytest.approx(5.0, abs=1e-9)


def test_hand_computed_pv_shifting_saves_exactly_the_shifted_kwh():
    """PV surplus stored now and served later — the saving is computable to the kWh.

    Two hourly intervals, a LOSSLESS battery (RTE 1.0), no standby, export FORBIDDEN by a zero
    export cap so surplus PV has nowhere else to go:

        interval 0:  load 0 kWh,  pv 3 kWh   → 3 kWh of surplus
        interval 1:  load 3 kWh,  pv 0 kWh   → a 3 kWh deficit

    Baseline (run A): interval 0 exports 3 kWh — but the export cap is 0, so all 3 kWh are curtailed
    and nothing is exported. Interval 1 imports 3 kWh. Baseline import = 3 kWh.

    Perfect foresight: charge the 3 kWh of surplus in interval 0 (within the 5 kW rating and the
    10 kWh window, taking the SoC 5.0 → 8.0), discharge it into interval 1's load (8.0 → 5.0). Both
    intervals import 0, and the terminal constraint is satisfied exactly.

        bound import = 0 kWh,  saved = 3 − 0 = 3 kWh,  final SoC = 5.0 kWh

    The 3.0 is the whole point: with a lossless battery the shifted energy is recovered in full, so
    any deviation is a conversion loss the fixture does not have or a clamp misfiring.
    """
    frame = _frame([0.0, 3.0], pv=[3.0, 0.0])
    cfg = _cfg(
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=50.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        roundtrip_efficiency=1.0,
        standby_w=0.0,
        max_export_kw=0.0,
        has_pv=True,
    )
    runs = run_all(frame, cfg)
    bench = energy_benchmark(runs.a, runs.c, frame, cfg)
    result = perfect_foresight(frame, cfg)

    assert bench.baseline_import_kwh == pytest.approx(3.0, abs=1e-9)
    assert result.import_kwh == pytest.approx(0.0, abs=1e-9)
    assert bench.perfect_foresight_saved_kwh == pytest.approx(3.0, abs=1e-9)
    assert result.soc_end == pytest.approx(5.0, abs=1e-9)


def test_hand_computed_lossy_round_trip_costs_the_efficiency():
    """The same PV shift at 90 percent RTE returns `3 × 0.9 = 2.7` kWh, not 3.0 and not 2.85.

    Identical to the fixture above except `roundtrip_efficiency = 0.90`, so §6.8's geometric split
    gives `eta_c = eta_d = sqrt(0.9) = 0.9486832980505138`. Charging 3 kWh AC stores
    `3 × 0.9486832980505138 = 2.846049894…` kWh; discharging all of it returns
    `2.846049894… × 0.9486832980505138 = 2.7` kWh AC exactly, since `eta_c × eta_d == 0.9` is the
    identity §6.8's convention rests on.

    Interval 1's 3 kWh of load is therefore served 2.7 kWh from the battery and 0.3 kWh from the
    grid:

        bound import = 0.3 kWh,  saved = 3 − 0.3 = 2.7 kWh

    Pinning 2.7 rather than 3.0 distinguishes the geometric split from a lossless model, and pinning
    it rather than 2.85 distinguishes it from a linear (0.95/0.95) split, which would return 2.85.

    **Asserted at a FINE action grid, and the coarse-grid answer is asserted beside it.** At
    appendix A's 41 action levels the 2.7 kWh discharge is not representable: the neighbouring
    actions are 2.75, which withdraws 2.899 kWh and would end the battery at 4.947 — below the
    starting SoC and therefore infeasible under the terminal constraint — and 2.5, which the DP
    takes instead, leaving 0.5 kWh of import. That is the `_interval_actions` residual, documented
    there, and it makes the bound CONSERVATIVE rather than wrong. Both figures are pinned so the
    distinction between "the efficiency convention is right" and "the grid is coarse" stays visible.
    """
    frame = _frame([0.0, 3.0], pv=[3.0, 0.0])
    base = dict(
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=50.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        roundtrip_efficiency=0.90,
        roundtrip_dc_bonus=0.0,  # so the DC path does not add its bonus to this hand computation
        standby_w=0.0,
        max_export_kw=0.0,
        has_pv=True,
    )
    # Fine grid: 1001 actions over [−5, +5] is a 0.01 kWh step, fine enough to reach 2.7 within the
    # tolerance below, so the hand-computed 0.3 kWh is what the DP returns.
    fine = perfect_foresight(frame, _cfg(**base, dp_action_levels=1001))
    assert fine.import_kwh == pytest.approx(0.3, abs=0.02)
    assert fine.soc_end >= 5.0 - SOC_COMPARE_EPS_KWH  # the terminal constraint still binds

    # Appendix A's grid: conservative by the action step, never optimistic.
    coarse = perfect_foresight(frame, _cfg(**base))
    assert coarse.import_kwh == pytest.approx(0.5, abs=1e-6)
    assert coarse.import_kwh >= fine.import_kwh, "a coarser grid may only weaken the bound"


def test_capture_ratio_is_the_policy_saving_over_the_bound():
    """`capture_ratio = policy_saved / perfect_foresight_saved` — the arithmetic, pinned directly.

    Trivial by construction, and worth pinning anyway: the ratio is the number the panel prints as a
    percentage, and an inverted division produces a plausible-looking figure that no other test in
    this file would catch.
    """
    frame = _frame([0.0, 3.0], pv=[3.0, 0.0])
    cfg = _cfg(usable_capacity_kwh=10.0, max_export_kw=0.0, has_pv=True)
    runs = run_all(frame, cfg)
    bench = energy_benchmark(runs.a, runs.c, frame, cfg)
    assert bench.capture_ratio == pytest.approx(
        bench.policy_saved_kwh / bench.perfect_foresight_saved_kwh
    )


def test_capture_ratio_is_none_when_nothing_could_have_been_avoided():
    """A window in which even perfect foresight avoids nothing has NO ratio — None, not 0 and not ∞.

    A household with zero load and zero PV imports nothing in any scenario, so the bound's saving is
    ~0 and the ratio's denominator vanishes. §6.11's discipline for such cases is an explicit
    absence: a number here would assert something the data cannot support.
    """
    frame = _frame(np.zeros(24))
    cfg = _cfg(standby_w=0.0)
    runs = run_all(frame, cfg)
    bench = energy_benchmark(runs.a, runs.c, frame, cfg)
    assert bench.perfect_foresight_saved_kwh == pytest.approx(0.0, abs=1e-9)
    assert bench.capture_ratio is None


def test_empty_window_is_handled_without_raising():
    """A zero-interval frame produces a finite, empty result rather than an IndexError.

    `resolve_window` can hand the view a window that reconciles to nothing, and a DP that raised
    there would take down a page the user is looking at.
    """
    frame = _frame([])
    result = perfect_foresight(frame, _cfg())
    assert result.import_kwh == 0.0
    assert result.soc_end == result.soc_start
    assert len(result.imp) == 0


# ── The action set (`_interval_actions`) ─────────────────────────────────────────────────────


def test_interval_actions_include_the_exact_pv_surplus_and_deficit():
    """The two continuous dispatch points §6.6/§6.7 use are exactly representable.

    Without them a policy can make a move the DP cannot, and the DP stops being an upper bound —
    measured at ~0.3 kWh (≈3 percent) below a P1/D1 policy before they were added. See
    `_interval_actions` for the measurement.
    """
    cfg = _cfg(max_charge_kw=5.0, max_discharge_kw=5.0)
    lim = _DpLimits.of(cfg, 1.0, allow_grid_export=False)

    # A sunny interval: surplus 2.3 kWh, which is not on the 0.25 kWh linspace.
    actions = _interval_actions(load_kwh=0.7, pv_kwh=3.0, lim=lim)
    assert np.any(np.isclose(actions, -2.3, atol=1e-12))
    assert not np.any(np.isclose(lim.actions, -2.3, atol=1e-12)), "fixture: must be off the grid"

    # A dark interval: deficit 1.4 kWh, likewise off the grid.
    actions = _interval_actions(load_kwh=1.4, pv_kwh=0.0, lim=lim)
    assert np.any(np.isclose(actions, 1.4, atol=1e-12))


def test_interval_actions_are_clipped_to_rated_power():
    """A surplus or deficit beyond rated power is clipped — it is not an action the battery has."""
    cfg = _cfg(max_charge_kw=2.0, max_discharge_kw=3.0)
    lim = _DpLimits.of(cfg, 1.0, allow_grid_export=False)
    actions = _interval_actions(load_kwh=0.0, pv_kwh=50.0, lim=lim)
    assert actions.min() >= -2.0 - 1e-12
    actions = _interval_actions(load_kwh=50.0, pv_kwh=0.0, lim=lim)
    assert actions.max() <= 3.0 + 1e-12


# ── The SoC-grid snap must not delete an endpoint (§6.12 + `perfect_foresight`'s interp comment) ──


def test_soc_grid_snap_never_moves_an_endpoint_level():
    """`_DpLimits.of` keeps `soc_min` and `soc_max` on the grid at every legal `dp_soc_levels`.

    `perfect_foresight` interpolates `V` with `np.interp`, which CLAMPS outside its grid, and the
    comment there justifies that as harmless because "the ends of `soc_levels` ARE the window's
    ends". The snap that moves the nearest level onto the starting SoC can falsify it: at
    `dp_soc_levels = 2` with `initial_soc = 5.0` over `[1, 10]` the nearest level IS `soc_min`, so
    moving it deletes `soc_min` from the grid and every `soc_next` below 5.0 is then read at a
    state the trajectory is not in. `validate()` permits `dp_soc_levels >= 2`, so this is reachable
    by configuration; nothing in production sets it.

    Asserted across a range of level counts and starting SoCs, including ones deliberately placed
    right next to an endpoint, which is where the same failure recurs at any grid size.
    """
    for levels in (2, 3, 4, 5, 11, 101):
        for initial_pct in (10.0, 11.0, 12.0, 50.0, 99.0, 100.0):
            cfg = _cfg(
                usable_capacity_kwh=10.0,
                min_soc_pct=10.0,
                initial_soc_pct=initial_pct,
                dp_soc_levels=levels,
            )
            lim = _DpLimits.of(cfg, 1.0, allow_grid_export=False)
            where = f"levels={levels}, initial_soc_pct={initial_pct}"
            assert lim.soc_levels[0] == pytest.approx(cfg.soc_min_kwh, abs=1e-12), (
                f"the snap dropped soc_min from the grid at {where}"
            )
            assert lim.soc_levels[-1] == pytest.approx(cfg.soc_max_kwh, abs=1e-12), (
                f"the snap dropped soc_max from the grid at {where}"
            )
            # `np.interp` requires a non-decreasing grid, and a snap that moved a level past a
            # neighbour (or onto one, producing a zero-width interval) would break it.
            assert np.all(np.diff(lim.soc_levels) > 0), f"grid not strictly sorted at {where}"


def test_soc_grid_snap_still_puts_an_interior_start_on_the_grid():
    """The snap's PURPOSE survives the endpoint guard: an interior starting SoC is still a level.

    The guard restricts the search to the interior; it must not stop the snap from doing the job it
    was added for. `soc_start = 2.5` on a `[1, 10]` window with 5 levels falls between 3.25 and
    1.0 — an interior gap — so a level must land exactly on it, which is what makes "hold the
    starting SoC and do nothing" an exactly representable trajectory.
    """
    cfg = _cfg(
        usable_capacity_kwh=10.0, min_soc_pct=10.0, initial_soc_pct=25.0, dp_soc_levels=5
    )
    lim = _DpLimits.of(cfg, 1.0, allow_grid_export=False)
    assert np.any(np.isclose(lim.soc_levels, cfg.initial_soc_kwh, atol=1e-12)), (
        "the starting SoC is not on the grid, so standing still is not representable"
    )
    assert lim.soc_start_kwh == pytest.approx(cfg.initial_soc_kwh, abs=1e-12)


# ════════════════════════════════════════════════════════════════════════════════════════════
# §6.12's COST benchmark — run E
# ════════════════════════════════════════════════════════════════════════════════════════════
#
# The euro sibling of everything above. Four things this section has to establish, in order of
# how load-bearing they are:
#
#   1. Fixture 6 holds IN EUROS, within the cost block, and is never asserted across the two
#      blocks (§6.12: "the cost-optimal dispatch routinely avoids less import than the
#      import-optimal one", so a cross-block assertion fails correctly-built code).
#   2. Fixture 20: `benchmarks.energy` is bit-identical with and without cost simulation. This
#      is what distinguishes "a cost benchmark was added" from "the benchmark was re-aimed".
#   3. The two objectives genuinely DIFFER — a case where the cost-optimal dispatch imports MORE
#      than the import-optimal one. If this cannot be built, only one DP is really running.
#   4. The export baselines and the negative-price behaviour, on the cost side.
#
# **Runtime.** Every fixture here is 48 intervals at reduced DP grids (41 SoC levels × 41
# actions rather than appendix A's 101 × 41) unless the assertion depends on resolution. The DP
# is O(T × n_soc × n_actions) and this section runs several dozen of them; at appendix A's grids
# the section took minutes. The invariants asserted — an ordering, an identity, an inequality
# between two runs sharing one grid — are not statements about the discretisation, and the two
# tests that ARE about resolution (`test_cost_bound_tightens_as_the_action_grid_refines` and the
# hand-computed arbitrage) say so and pay for the finer grid.

# The euro analogue of `_DP_SLACK_KWH`. The DP's residual discretisation error is an ENERGY
# quantity (§6.12: "finish exactly at the starting SoC" is state-dependent and cannot share one
# action row), so its euro cost is that energy times a price. At `_DP_SLACK_KWH` = 0.03 kWh and
# the all-in prices these fixtures reach (up to ~0.62 EUR/kWh), 0.03 × 0.62 ≈ 0.02 EUR; the
# constant is rounded up to 0.05 to leave room for the two-sided case, where both the bound and
# the policy carry one. It is NOT a fudge factor: it does not grow with the window, and refining
# `dp_action_levels` shrinks it, which
# `test_cost_bound_tightens_as_the_action_grid_refines` demonstrates.
_DP_SLACK_EUR = 0.05

# The coarse-but-honest grids this section runs the DP at — see the section note on runtime.
_FAST_DP = dict(dp_soc_levels=41, dp_action_levels=41)


def _square_wave_spot(n: int, *, low: float = 0.02, high: float = 0.40) -> np.ndarray:
    """Fixture 20's price shape: a daily square wave between a cheap and an expensive half-day.

    §6.14 fixture 20 asks for "a square-wave price alternating daily between a low inside band
    `[A,B]` and a high inside band `[C,D]`" — the shape that makes arbitrage the whole story, so
    the cost objective has something to be optimal AT that the energy objective is indifferent to.
    A smoothly varying price would let the two objectives agree by accident and would prove
    nothing.
    """
    return np.where((np.arange(n) % 24) < 12, low, high)


def _cost_setup(
    *, n: int = 48, load=None, pv=None, spot=None, **cfg_kw
) -> tuple:
    """One (frame, cfg, curves) triple for the cost block, at the reduced DP grids.

    `simulate_cost=True` is set here rather than at each call site because §6.12's table makes it
    the precondition for running the cost benchmark at all; a fixture that forgot it would be
    asking for a euro bound on a run the spec says has none.
    """
    spot = _square_wave_spot(n) if spot is None else np.asarray(spot, dtype=np.float64)
    load = np.full(n, 1.0) if load is None else np.asarray(load, dtype=np.float64)
    frame = _frame(load, pv=pv, spot=spot)
    cfg = _cfg(simulate_cost=True, **{**_FAST_DP, **cfg_kw})
    curves = price_curves(cfg.pricing, spot)
    return frame, cfg, curves


def _cost_bench(frame, cfg, curves) -> CostBenchmark:
    """Runs A/B/C and the §6.12 COST DP(s) over one frame+config."""
    runs = run_all(frame, cfg)
    return cost_benchmark(runs.a, runs.c, frame, cfg, curves)


# ── Fixture 6, in the cost block's own units ─────────────────────────────────────────────────


def _fixture_6_cost_configs():
    """Fixture 6's "for every configuration", on the euro side: 9 policy pairs × PV × capacity.

    The same sweep shape as `_fixture_6_configs`, narrowed to two capacities and two starting
    SoCs and run at the reduced DP grids, because each configuration here costs two DP passes
    (inheriting + unconstrained) and the sweep is over a square-wave price where the arbitrage
    the cost objective exists to find is unambiguous.

    Both starting SoCs are deliberately present: 10 percent starts the battery at its floor, so
    there is no opening charge to liquidate and the RAW fixture-6 form is assertable; 50 percent
    starts it half full, which is where the §6.12 terminal-constraint asymmetry bites and where
    the euro-side drift question below is measured.
    """
    n = 48
    hours = np.arange(n)
    spot = _square_wave_spot(n)
    for seed in (1, 2):
        rng = np.random.default_rng(seed)
        load = 0.6 + 0.5 * rng.random(n)
        pv_series = 2.0 * np.maximum(0.0, np.sin(hours * np.pi / 12.0))
        for charge in ChargePolicy:
            for discharge in DischargePolicy:
                for has_pv in (False, True):
                    for capacity in (5.0, 10.0):
                        for initial_soc_pct in (10.0, 50.0):
                            frame, cfg, curves = _cost_setup(
                                n=n,
                                load=load,
                                pv=pv_series if has_pv else None,
                                spot=spot,
                                charge_policy=charge,
                                discharge_policy=discharge,
                                usable_capacity_kwh=capacity,
                                has_pv=has_pv,
                                initial_soc_pct=initial_soc_pct,
                                band_a=-1.0,
                                band_b=0.10,
                                band_c=0.20,
                                band_d=9.999,
                            )
                            yield frame, cfg, curves


_FIXTURE_6_COST_BENCHED = None


def _fixture_6_cost_benched():
    """The euro sweep with its benchmark already run — the cost-side twin of `_fixture_6_benched`.

    Same reasoning, and the same purity and frozen-dataclass guarantees (`CostBenchmark`); see
    that function. The saving is smaller here only because the sweep is smaller and already runs
    at `_FAST_DP`: ~3.8s per pass across two consumers rather than ~8.5s across three.
    """
    global _FIXTURE_6_COST_BENCHED
    if _FIXTURE_6_COST_BENCHED is None:
        _FIXTURE_6_COST_BENCHED = [
            (frame, cfg, _cost_bench(frame, cfg, curves))
            for frame, cfg, curves in _fixture_6_cost_configs()
        ]
    return _FIXTURE_6_COST_BENCHED


def test_fixture_6_cost_bound_holds_when_the_policy_does_not_liquidate():
    """§6.14 fixture 6 IN EUROS: `perfect_foresight_eur ≥ policy_eur`, over 72 configurations.

    Asserted RAW — no drift correction — and restricted to the configurations where the policy
    run did not end below its starting SoC, which is the restriction §6.14 itself names for the
    literal form ("only over configurations where the policy's drift is non-negative"). Over the
    144-configuration sweep, half satisfy that restriction and the worst violation among them was
    measured at exactly 0.0 EUR: where the comparison is fair, the euro bound is not merely
    within tolerance, it is never approached from the wrong side.

    **Nothing here compares against the energy block**, and that is §6.12's explicit instruction:
    the cost-optimal dispatch avoids less import than the import-optimal one, so a bound asserted
    across the two blocks would fail correctly-built code. See
    `test_the_cost_objective_imports_more_than_the_energy_one`, which measures exactly that
    divergence rather than asserting it away.
    """
    checked = 0
    for _frame_, cfg, bench in _fixture_6_cost_benched():
        if bench.policy_soc_delta_kwh < -SOC_COMPARE_EPS_KWH:
            continue  # a liquidating policy — see the test below for why it is excluded
        assert bench.perfect_foresight_eur >= bench.policy_eur - _DP_SLACK_EUR, (
            f"fixture 6 violated in EUROS: policy EUR {bench.policy_eur:.4f} beat the bound "
            f"{bench.perfect_foresight_eur:.4f} under "
            f"{cfg.policy.charge_policy.value}/{cfg.policy.discharge_policy.value}, "
            f"has_pv={cfg.has_pv}, capacity={cfg.battery.usable_capacity_kwh}"
        )
        checked += 1
    assert checked >= 60, f"the non-liquidating half of the sweep shrank to {checked}"


def test_the_euro_drift_correction_does_not_restore_the_bound_for_a_liquidating_policy():
    """A MEASUREMENT, not a wish: §6.12's kWh drift correction has no sound euro analogue here.

    §6.12 corrects both sides by `saved_kwh + soc_delta_kwh × eta_d` before asserting fixture 6,
    because the DP's terminal constraint binds it and nothing binds the policy run. The obvious
    euro analogue multiplies that residual by a price, and §6.11 has already chosen one for the
    same physical quantity: it defines `soc_delta_value_eur` as the drift "valued at the median
    import price". `CostBenchmark.median_import_price_eur_kwh` carries it.

    **It does not work, and this test pins the reason so a future reader does not re-derive it as
    an improvement.** In kWh the correction is exact because a kWh is a kWh: one unit of residual
    storage is worth exactly one unit of avoided import, whenever it is used. In euros the
    residual's worth depends on WHEN it would be used, and the two sides use it at different
    times by construction. On this fixture — a square-wave price whose expensive half-day is
    LAST — the policy liquidates 4 kWh of opening charge into the cheap half and never buys it
    back, while the DP's terminal constraint forces it to hold charge through, or repurchase it
    at, the expensive half. Valuing both residuals at one scalar price cannot express that, and
    measured across the sweep the median-price correction leaves violations up to €0.91 — far
    outside `_DP_SLACK_EUR`. Valuing at the window's MAXIMUM import price nearly restores the
    ordering (measured at €0.002 short at appendix-A-scale grids, inside slack at finer ones),
    which is itself the evidence that the basis, not the DP, is what is wrong.

    So `cost_benchmark` reports `median_import_price_eur_kwh` as an INPUT and applies no euro
    drift correction (see `CostBenchmark`'s field note), and the euro fixture-6 assertion above
    is stated on the non-liquidating configurations instead. Recorded as an unresolved spec gap:
    §6.12 states the drift correction only in kWh, and a defensible euro form would have to value
    each side's residual at that side's own marginal continuation value — which the DP has (it is
    `V`'s slope at the terminal SoC) and the policy run does not.
    """
    frame, cfg, curves = _cost_setup(
        usable_capacity_kwh=10.0,
        standby_w=0.0,
        has_pv=False,
        initial_soc_pct=50.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0, band_b=0.10, band_c=0.20, band_d=9.999,
    )
    bench = _cost_bench(frame, cfg, curves)

    # The fixture really is the liquidating case the correction is supposed to handle.
    assert bench.policy_soc_delta_kwh < -1.0
    assert bench.median_import_price_eur_kwh is not None

    price = bench.median_import_price_eur_kwh
    policy_corrected = bench.policy_eur + bench.policy_soc_delta_kwh * cfg.eta_d * price
    bound_corrected = bench.perfect_foresight_eur + (
        (bench.soc_end_kwh - bench.soc_start_kwh) * cfg.eta_d * price
    )
    # The correction does NOT restore the ordering — this is the measurement.
    assert policy_corrected > bound_corrected + _DP_SLACK_EUR, (
        "the median-price euro drift correction now restores the bound on this fixture; if that "
        "is a real improvement, `CostBenchmark`'s field note and this test both need rewriting"
    )
    # …and no correction is applied inside the block: the fields are inputs, not adjustments.
    assert bench.perfect_foresight_eur == pytest.approx(
        bench.baseline_eur - bench.bound_eur
    )


def test_cost_capture_ratio_is_the_policy_saving_over_the_bound_in_euros():
    """`capture_ratio = policy_eur / perfect_foresight_eur` — the arithmetic, pinned directly.

    Trivial by construction and worth pinning for the same reason its energy twin is: the ratio is
    what a panel prints as a percentage, and an inverted division produces a plausible number.
    Also pins that the cost block reuses `_capture_ratio`, so the two blocks cannot acquire
    different divide-by-zero conventions.
    """
    frame, cfg, curves = _cost_setup(usable_capacity_kwh=10.0, initial_soc_pct=10.0)
    bench = _cost_bench(frame, cfg, curves)
    assert bench.capture_ratio == pytest.approx(bench.policy_eur / bench.perfect_foresight_eur)
    assert bench.no_battery_eur == 0.0


def test_cost_block_figures_are_savings_against_run_a_s_bill():
    """§4.5: `policy_eur` is `cost(A) − cost(C)`, the same 331.10 that `cost.saved_eur` shows.

    Recomputed here from `compute_costs` directly rather than read back off the block, so a future
    change that made the block bill its runs some other way — a second implementation of §6.10's
    arithmetic living inside `benchmark.py` — fails rather than quietly reporting a euro figure
    the cost panel disagrees with.
    """
    frame, cfg, curves = _cost_setup(usable_capacity_kwh=10.0, initial_soc_pct=10.0)
    runs = run_all(frame, cfg)
    bench = cost_benchmark(runs.a, runs.c, frame, cfg, curves)

    def bill(flows):
        return compute_costs(
            flows, curves.p_import, curves.p_export_net, curves.compensation,
            frame.index, cfg.pricing,
        ).eur

    assert bench.baseline_eur == pytest.approx(bill(runs.a))
    assert bench.policy_bill_eur == pytest.approx(bill(runs.c))
    assert bench.policy_eur == pytest.approx(bill(runs.a) - bill(runs.c))
    assert bench.perfect_foresight_eur == pytest.approx(bench.baseline_eur - bench.bound_eur)


# ── Fixture 20: two runs, not one retargeted run ─────────────────────────────────────────────


def test_fixture_20_energy_block_is_identical_with_and_without_cost_simulation():
    """§6.14 fixture 20 / fixture 18: `benchmarks.energy` is BIT-IDENTICAL across the toggle.

    §6.14 fixture 18: "A failure in `benchmarks.energy` means the perfect-foresight DP is being
    retargeted at euros instead of a second DP being added." Fixture 20 restates it as the thing
    that "distinguishes 'a cost benchmark was added' from 'the benchmark was re-aimed'".

    Asserted on the whole block field by field, not on a sample, and with `==` rather than
    `approx`: identical inputs through identical code must produce identical floats, so any
    tolerance here would be hiding something. The two configs differ ONLY in `simulate_cost` and
    are run over the same frame with a full contract configuration present in both — §6.14
    fixture 18's shape, which is what makes it a test of the toggle rather than of the prices.
    """
    n = 48
    spot = _square_wave_spot(n)
    frame = _frame(np.full(n, 1.0), spot=spot)
    shared = dict(
        usable_capacity_kwh=10.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0, band_b=0.10, band_c=0.20, band_d=9.999,
        pricing=PricingConfig(),
        **_FAST_DP,
    )
    with_cost = _cfg(simulate_cost=True, **shared)
    without_cost = _cfg(simulate_cost=False, **shared)

    def energy_block(cfg):
        runs = run_all(frame, cfg)
        return energy_benchmark(runs.a, runs.c, frame, cfg)

    a, b = energy_block(with_cost), energy_block(without_cost)
    for field in EnergyBenchmark.__dataclass_fields__:
        assert getattr(a, field) == getattr(b, field), (
            f"benchmarks.energy.{field} moved when cost simulation was toggled — the DP is being "
            f"retargeted at euros instead of a second DP being added (fixture 18/20)"
        )

    # …and the cost block over the same data really was computable, so the comparison above is not
    # vacuously between two energy-only runs.
    curves = price_curves(with_cost.pricing, spot)
    cost = cost_benchmark(*[getattr(run_all(frame, with_cost), k) for k in ("a", "c")],
                          frame, with_cost, curves)
    assert np.isfinite(cost.perfect_foresight_eur)


def test_the_cost_objective_imports_more_than_the_energy_one():
    """Fixture 20's core: the two objectives produce DIFFERENT dispatches, and in the stated way.

    §6.12: "a cost-optimal dispatch does not minimise import, because it will happily import more
    during cheap hours." That is a falsifiable claim, and this is the test that falsifies the
    alternative — if the two objectives produced the same trace, only one DP would really be
    running and `transition_cost` would be returning the same quantity for both.

    The fixture is fixture 20's: a flat 1 kW load, no PV, and a square-wave price alternating
    daily between 0.02 and 0.40 EUR/kWh bare. The import-minimising dispatch has nothing to gain
    (with no PV and a lossy battery, every kWh cycled through storage costs energy) so it stands
    still; the cost-minimising one charges through the cheap half-day and discharges through the
    expensive one, paying the round-trip loss in kWh to save money. Measured: 48.00 kWh for the
    energy DP against 49.72 for the cost DP — the cost-optimal dispatch imports ~1.7 kWh MORE.

    This is exactly why §6.12 forbids asserting fixture 6 across the two blocks.
    """
    frame, cfg, curves = _cost_setup(
        usable_capacity_kwh=10.0, standby_w=0.0, has_pv=False, initial_soc_pct=50.0
    )
    energy_dp = perfect_foresight(frame, cfg, objective=ENERGY_OBJECTIVE)
    cost_dp = perfect_foresight(
        frame, cfg, objective=CostObjective(curves.p_import, curves.p_export_net)
    )

    assert energy_dp.objective == "energy" and cost_dp.objective == "cost"
    # The dispatches differ — the falsifiable part.
    assert not np.allclose(energy_dp.soc, cost_dp.soc, atol=1e-6), (
        "the two objectives produced the same SoC trace; only one DP is really running"
    )
    # …and they differ in the direction §6.12 states: the cost-optimal dispatch imports MORE.
    assert cost_dp.import_kwh > energy_dp.import_kwh + 1.0, (
        f"cost DP imported {cost_dp.import_kwh:.3f} kWh against the energy DP's "
        f"{energy_dp.import_kwh:.3f}; §6.12 says a cost-optimal dispatch imports more here"
    )
    # Each is optimal for its OWN quantity, which is the other half of the claim: the energy DP
    # cannot be beaten on kWh, and the cost DP cannot be beaten on euros.
    assert energy_dp.import_kwh <= cost_dp.import_kwh

    def bill(result):
        return compute_costs(
            _dispatch_flows(result), curves.p_import, curves.p_export_net,
            curves.compensation, frame.index, cfg.pricing,
        ).eur

    assert bill(cost_dp) < bill(energy_dp) - 0.10, (
        "the cost DP must beat the energy DP on euros, or it is not optimising euros"
    )


# ── The two export baselines, on the cost side ───────────────────────────────────────────────


def test_cost_unconstrained_fields_are_null_when_export_is_allowed():
    """§6.12: with `allow_grid_export` ON the second DP is SKIPPED and the fields are None.

    The exact mirror of the energy block's rule, and it matters more here: on the cost objective
    the export permission genuinely changes the optimum (exporting into a high-price hour is the
    whole arbitrage case), so a reader seeing two equal-and-present figures would reasonably
    conclude two DPs ran and agreed. They must be None.
    """
    frame, cfg, curves = _cost_setup(allow_grid_export=True, usable_capacity_kwh=10.0)
    bench = _cost_bench(frame, cfg, curves)
    assert bench.perfect_foresight_eur_unconstrained is None
    assert bench.capture_ratio_unconstrained is None
    assert bench.bound_eur_unconstrained is None
    # …and the inheriting figure IS present: skipping the second pass must not skip the first.
    assert bench.perfect_foresight_eur == pytest.approx(bench.baseline_eur - bench.bound_eur)


def test_cost_unconstrained_bound_is_at_least_the_inheriting_one():
    """§6.12's second invariant, in EUROS: `unconstrained ≥ inheriting`, over the sweep.

    The unconstrained DP optimises over a SUPERSET of the inheriting DP's action set — the same
    feasibility rule with the battery-export prohibition lifted — so it cannot do worse. Asserted
    across the fixture-6 sweep rather than on one fixture, because the only way it can fail is a
    change that makes the unconstrained pass somehow WORSE, which is not fixture-specific.
    """
    for _frame_, cfg, bench in _fixture_6_cost_benched():
        assert bench.perfect_foresight_eur_unconstrained is not None
        assert bench.bound_eur_unconstrained is not None
        assert (
            bench.perfect_foresight_eur_unconstrained
            >= bench.perfect_foresight_eur - _DP_SLACK_EUR
        ), (
            f"unconstrained EUR bound {bench.perfect_foresight_eur_unconstrained:.4f} fell below "
            f"the inheriting one {bench.perfect_foresight_eur:.4f}, which optimises over a subset"
        )


def test_cost_unconstrained_bound_strictly_exceeds_the_inheriting_one_with_pv_to_sell():
    """The euro case where the export permission REALLY bites — and the energy one where it cannot.

    On the energy objective the two baselines are usually equal even with export off: exporting
    battery energy earns revenue but avoids no grid import, so the permission cannot change an
    import-minimising dispatch (the energy block's own test says so). On euros it can, and this
    is the fixture that shows it: PV worth storing, a square-wave price, and a high enough
    expensive-half price that discharging to the GRID beats holding.

    Asserted as a strict inequality on the cost side and an equality on the energy side over the
    same data, which is the sharpest available statement that the two objectives are answering
    different questions about the same window.
    """
    n = 48
    hours = np.arange(n)
    pv = 3.0 * np.maximum(0.0, np.sin(hours * np.pi / 12.0))
    frame, cfg, curves = _cost_setup(
        n=n,
        load=np.full(n, 0.3),
        pv=pv,
        usable_capacity_kwh=10.0,
        has_pv=True,
        allow_grid_export=False,
        initial_soc_pct=10.0,
        standby_w=0.0,
    )
    bench = _cost_bench(frame, cfg, curves)
    assert bench.perfect_foresight_eur_unconstrained is not None
    assert bench.perfect_foresight_eur_unconstrained > bench.perfect_foresight_eur + 0.05, (
        "with PV to sell into an expensive half-day, lifting the battery-export prohibition must "
        "buy the cost DP something; if it does not, the feasibility rule is not being relaxed"
    )
    # The same relaxation over the same data buys the ENERGY DP nothing, because export avoids no
    # import — the contrast that makes the point above about two different questions.
    energy = energy_benchmark(*[getattr(run_all(frame, cfg), k) for k in ("a", "c")], frame, cfg)
    assert energy.perfect_foresight_saved_kwh_unconstrained == pytest.approx(
        energy.perfect_foresight_saved_kwh, abs=_DP_SLACK_KWH
    )


# ── Negative prices: the case §6.10 says the tool exists to surface ──────────────────────────


def test_the_cost_dp_charges_through_a_negative_price_window():
    """A negative-price hour pays the household to consume, and the cost DP must exploit it.

    §6.10: a negative `p_export_net` means exporting COSTS money, and §6.5 clamps nothing. The
    import side has the mirror property — a bare spot price low enough drives `p_import` negative
    (energy tax and VAT are added to a negative number), and then importing is a gain. The
    import-minimising DP is blind to this by construction; the cost-minimising one must not be.

    The fixture is four days in which one 6-hour window has a deeply negative spot price and the
    rest is expensive. The assertion is on the realised dispatch: the cost DP's import during the
    negative window must exceed the energy DP's, i.e. it deliberately draws energy it does not
    need because doing so is paid for. Asserted on the interval sums rather than on the SoC trace
    because "charging" is what the SoC does and "importing" is what the bill sees, and it is the
    bill this objective is minimising.
    """
    n = 48
    spot = np.full(n, 0.30)
    negative = slice(6, 12)
    spot[negative] = -0.60  # well below the ~-0.21 point where all-in p_import turns negative
    frame, cfg, curves = _cost_setup(
        n=n, spot=spot, usable_capacity_kwh=10.0, standby_w=0.0, has_pv=False,
        initial_soc_pct=10.0,
    )
    assert float(np.min(curves.p_import[negative])) < 0.0, (
        "fixture precondition: the all-in import price must actually be negative in the window"
    )

    energy_dp = perfect_foresight(frame, cfg, objective=ENERGY_OBJECTIVE)
    cost_dp = perfect_foresight(
        frame, cfg, objective=CostObjective(curves.p_import, curves.p_export_net)
    )
    cost_window_import = float(np.nansum(cost_dp.imp[negative]))
    energy_window_import = float(np.nansum(energy_dp.imp[negative]))
    assert cost_window_import > energy_window_import + 1.0, (
        f"the cost DP imported {cost_window_import:.3f} kWh across the negative-price window "
        f"against the energy DP's {energy_window_import:.3f}; a DP that is paid to consume and "
        f"does not is not minimising euros"
    )
    # The battery really did fill up during the window — the mechanism, not just the symptom.
    assert cost_dp.soc[negative.stop - 1] > cost_dp.soc[negative.start - 1] + 1.0


def test_the_cost_objective_prices_export_and_does_not_clamp_it():
    """`CostObjective.cost` is `imp × p_import − exp × p_export_net`, with a NEGATIVE export term.

    The unit-level statement behind the module's warning that a `max(0, .)` on the export term
    would hide the effect §6.10 says the tool exists to show. Driven directly through the
    objective with a hand-made transition so there is no dispatch in the way: an export at a
    negative `p_export_net` must INCREASE the interval's cost.
    """
    lim = _DpLimits.of(_cfg(usable_capacity_kwh=10.0), 1.0, allow_grid_export=True)
    # A pure export: 2 kWh of PV surplus, no import, no battery action.
    tr = _transition(np.array([[5.0]]), np.array([[0.0]]), load_kwh=0.0, pv_kwh=2.0, lim=lim)
    assert tr.exp[0, 0] == pytest.approx(2.0)
    assert tr.imp[0, 0] == pytest.approx(0.0)

    positive = CostObjective(np.array([0.30]), np.array([0.05]))
    negative = CostObjective(np.array([0.30]), np.array([-0.05]))
    assert positive.cost(tr, 0)[0, 0] == pytest.approx(-0.10)  # export earned money
    assert negative.cost(tr, 0)[0, 0] == pytest.approx(+0.10)  # export COST money — not clamped


def test_the_cost_objective_treats_an_unpriced_interval_as_free():
    """§6.10's gap rule: a NaN price contributes exactly zero, matching `costs._nansum`.

    §4.4 writes NaN into `spot` where no price covers the interval and it propagates through
    every §6.5 array; `compute_costs` excludes those intervals from the bill. The DP has to agree,
    or its bound would be summed over a different interval set than the bill it bounds. A DP that
    let NaN through would propagate it into `V` and poison the whole window's answer off one
    missing price.
    """
    lim = _DpLimits.of(_cfg(usable_capacity_kwh=10.0), 1.0, allow_grid_export=True)
    tr = _transition(np.array([[5.0]]), np.array([[0.0]]), load_kwh=2.0, pv_kwh=0.0, lim=lim)
    unpriced = CostObjective(np.array([np.nan]), np.array([np.nan]))
    assert np.all(np.isfinite(unpriced.cost(tr, 0)))
    assert unpriced.cost(tr, 0)[0, 0] == pytest.approx(0.0)

    # …and the whole-window version: an all-NaN price series gives a finite, zero bound.
    n = 24
    frame, cfg, curves = _cost_setup(n=n, spot=np.full(n, np.nan), usable_capacity_kwh=10.0)
    result = perfect_foresight(
        frame, cfg, objective=CostObjective(curves.p_import, curves.p_export_net)
    )
    assert np.isfinite(result.import_kwh)
    assert result.soc_end >= result.soc_start - SOC_COMPARE_EPS_KWH


# ── The shared machinery really is shared ────────────────────────────────────────────────────


def test_the_cost_dp_obeys_the_same_terminal_constraint_and_limits_as_the_energy_one():
    """§6.12: the terminal constraint, the SoC window and the connection caps serve BOTH objectives.

    The point of parameterising the objective rather than writing a second DP is that these
    properties cannot hold for one run and not the other. Asserted on the cost run over a fixture
    that gives it every incentive to break each of them: a full battery (liquidation is tempting),
    an expensive final half-day (so holding charge is costly), and a binding 2 kW fuse against a
    5 kW charge rating and a price that begs for grid charging.
    """
    frame, cfg, curves = _cost_setup(
        usable_capacity_kwh=10.0,
        min_soc_pct=10.0,
        initial_soc_pct=100.0,
        max_import_kw_override=2.0,
        standby_w=0.0,
    )
    result = perfect_foresight(
        frame, cfg, objective=CostObjective(curves.p_import, curves.p_export_net)
    )
    assert result.soc_end >= result.soc_start - SOC_COMPARE_EPS_KWH, "terminal constraint"
    assert np.all(result.soc >= cfg.soc_min_kwh - SOC_COMPARE_EPS_KWH)
    assert np.all(result.soc <= cfg.soc_max_kwh + SOC_COMPARE_EPS_KWH)
    assert np.nanmax(result.imp) <= cfg.max_import_kw * frame.dt_hours + 1e-9, "import cap"


def test_the_cost_dp_skips_gaps_exactly_as_run_c_does():
    """§6.9's gap rule reaches the cost run through the same shared code path.

    The DP and run C must exclude the SAME intervals, or the euro bound and the euro saving would
    be sums over different interval sets and fixture 6 would compare unlike things.
    """
    load = np.array([1.0, 1.0, np.nan, 1.0, 1.0, np.nan])
    frame, cfg, curves = _cost_setup(n=6, load=load, spot=np.full(6, 0.10))
    result = perfect_foresight(
        frame, cfg, objective=CostObjective(curves.p_import, curves.p_export_net)
    )
    runs = run_all(frame, cfg)
    assert list(result.gap) == list(runs.c.gap)
    assert np.isnan(result.imp[2]) and np.isnan(result.exp[2])
    assert result.soc[2] == pytest.approx(result.soc[1])


def test_cost_bound_tightens_as_the_action_grid_refines():
    """The euro bound is CONSERVATIVE by the action step, never optimistic — the basis of the slack.

    §6.12's residual discretisation error ("finish exactly at the starting SoC" is state-dependent
    and cannot share one action row) makes the bound understate the achievable saving; refining
    `dp_action_levels` shrinks that. This is the one test in this section that is ABOUT the
    resolution, so it pays for the finer grid, and it is what makes `_DP_SLACK_EUR` a measured
    tolerance rather than a fudge factor: a regression that made the DP genuinely suboptimal would
    not improve with refinement.
    """
    kw = dict(usable_capacity_kwh=10.0, standby_w=0.0, has_pv=False, initial_soc_pct=10.0)
    savings = []
    for action_levels in (11, 41, 161):
        frame, cfg, curves = _cost_setup(**kw, dp_soc_levels=101, dp_action_levels=action_levels)
        savings.append(_cost_bench(frame, cfg, curves).perfect_foresight_eur)
    assert savings[1] >= savings[0] - 1e-9 and savings[2] >= savings[1] - 1e-9, (
        f"refining the action grid must not weaken the euro bound, but it moved {savings}"
    )
    assert savings[2] - savings[0] > 0.0, "the coarse grid should be visibly conservative"


def test_cost_benchmark_flags_a_binding_feedin_floor():
    """`floor_binds` says when `perfect_foresight_eur` is a bound on the PRE-top-up bill only.

    Run E minimises the per-interval bill; §6.5's floor top-up is a period aggregate and is not
    separable across intervals, so the DP cannot see it (module comment). In the ordinary window
    the floor does not bind and the two bases coincide; the flag exists so a window where it does
    bind is not read as if the bound were unqualified.

    Fixture 14's shape: a deeply negative spot price with export to make, so the month's export
    earns a net negative amount and the floor tops it back up to zero.
    """
    n = 48
    hours = np.arange(n)
    frame, cfg, curves = _cost_setup(
        n=n,
        load=np.full(n, 0.2),
        pv=3.0 * np.maximum(0.0, np.sin(hours * np.pi / 12.0)),
        spot=np.full(n, -0.5205),
        usable_capacity_kwh=10.0,
        has_pv=True,
        allow_grid_export=True,
        pricing=PricingConfig(feedin_floor_mode=FeedinFloorMode.MONTHLY),
    )
    bench = _cost_bench(frame, cfg, curves)
    assert bench.floor_binds is True
    assert np.isfinite(bench.perfect_foresight_eur)

    # …and the ordinary window does not raise the flag, so it is a signal rather than a constant.
    ordinary_frame, ordinary_cfg, ordinary_curves = _cost_setup(usable_capacity_kwh=10.0)
    assert _cost_bench(ordinary_frame, ordinary_cfg, ordinary_curves).floor_binds is False
