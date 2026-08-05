"""Unit tests for the §6.6–§6.9 simulation core (app/domain/simulate.py).

The §6.14 harness says of its fixtures: "Write these first — they are cheap, and several of them
catch whole classes of error that are otherwise invisible in plausible-looking output." Six of them
target this module, and they lead here:

  * **Fixture 1 (Trivial)** — flat 1 kW load, no PV, flat price, P2/D2 with DISJOINT bands. With a
    flat price, at most one band can contain it, so the two policies are exercised one at a time
    and cycles/throughput are computable by hand. Asserted against hand-computed numbers, never
    against the implementation's own arithmetic.
  * **Fixture 2 (Efficiency)** — one charge and one discharge of a 10 kWh battery at 90% RTE
    returns 9.0 kWh AC; the round-trip loss is 1.0 kWh, not 0.9 and not 1.11. The INTERMEDIATE
    stored value (9.48683298…) is asserted too, because putting the whole loss on the charge side
    also returns 9.0 kWh AC and only the SoC in between distinguishes the two conventions.
  * **Fixture 3 (Conservation)** — asserted for runs A, B and C. The identity that actually closes
    is the AC-side one WITH curtailment; see `_assert_conservation` for the derivation and for why
    the naive form does not close.
  * **Fixture 5 (Monotonicity)** — larger capacity never reduces savings, across several
    capacities. A violation indicates a clamping bug in §6.8 steps 3 or 4.
  * **Fixture 16 (No-PV arbitrage)** — square-wave price, P2/D2, exactly one full cycle per day,
    saving computed analytically from the spread, the RTE and the standby draw. The analytic figure
    is NEGATIVE in kWh, which is §7.2 item 9's point rather than a defect.
  * **Fixture 17 (PV-invariance)** — has_pv=True with an all-zero PV array vs has_pv=False with no
    solar series, identical energy figures. This pins that the numeric core takes no `has_pv`
    branch.

Plus §7.2 item 1 (the export limit applies to the BASELINE too — "easy to get wrong; assert in
tests"), and the cases that are not spec fixtures but are where §6.8's clamps actually break: SoC
containment over a long randomised run, NaN gaps, band-overlap netting, the two connection limits
and their shedding ORDER, and a NaN spot price.

Frames are built directly as `SimulationFrame` objects rather than through `simulation_frame()`:
the core is arrays-in/numbers-out (§5.2), and going through ingest would make each fixture depend
on reconciliation behaviour these tests are not about. `tests/test_simframe.py` covers the builder.
"""

import math

import numpy as np
import pytest

from app.domain.simconfig import (
    BatteryConfig,
    ChargePolicy,
    Coupling,
    DischargePolicy,
    GridConfig,
    PolicyConfig,
    SimulationConfig,
)
from app.domain.simframe import CLOSURE_TOL, SimulationFrame
from app.domain.simulate import (
    Cancelled,
    Flows,
    StepFlows,
    battery_step,
    charge_request,
    discharge_request,
    net_requests,
    run_all,
    simulate,
    simulate_baseline,
    _StepLimits,
    _View,
)

_EPOCH = np.datetime64("2026-01-01T00:00:00")

# sqrt(0.9), the §6.8 geometric efficiency split, written as a literal rather than as
# `math.sqrt(0.9)`: an assertion phrased with the implementation's own formula passes for any
# implementation using that formula, including a wrong one.
_ETA = 0.9486832980505138


def _frame(load, pv=None, spot=None, dt_hours: float = 1.0) -> SimulationFrame:
    """A `SimulationFrame` straight from arrays — no dataset, no ingest, no clock.

    `pv` defaults to all-zero (which is what §4.4 fills it with for a household without PV) and
    `spot` to a flat 0.10 EUR/kWh.
    """
    load = np.asarray(load, dtype=np.float64)
    n = len(load)
    pv = np.zeros(n) if pv is None else np.asarray(pv, dtype=np.float64)
    spot = np.full(n, 0.10) if spot is None else np.asarray(spot, dtype=np.float64)
    step_s = int(round(dt_hours * 3600))
    index = _EPOCH + (np.arange(n, dtype=np.int64) * step_s).astype("timedelta64[s]")
    return SimulationFrame(
        index=index,
        window=(None, None),  # not read by the core; the frame builder is tested elsewhere
        grid_s=step_s,
        dt_hours=dt_hours,
        pv=pv,
        load=load,
        spot=spot,
        # No sub-grid price points behind a hand-built frame, so the intra-interval bracket
        # collapses onto `spot` — the same value the builder produces for a single-point interval.
        spot_min=spot.copy(),
        spot_max=spot.copy(),
        import_obs=np.zeros(n),
        export_obs=np.zeros(n),
        spot_complete=not bool(np.isnan(spot).any()),
        spot_missing_intervals=int(np.isnan(spot).sum()),
        spot_extrapolated_intervals=0,
        has_pv_series=pv is not None,
    )


def _cfg(**kw) -> SimulationConfig:
    """A `SimulationConfig` with the sub-config fields flattened into keyword arguments.

    Purely a convenience so a fixture reads as a list of the parameters it actually cares about;
    everything unnamed keeps its appendix-A default, which `tests/test_simconfig.py` pins.
    """
    groups = {
        "battery": (BatteryConfig, {}),
        "grid": (GridConfig, {}),
        "policy": (PolicyConfig, {}),
    }
    field_owner = {
        f: name
        for name, (klass, _) in groups.items()
        for f in klass.__dataclass_fields__
    }
    top: dict = {}
    for key, value in kw.items():
        owner = field_owner.get(key)
        if owner is None:
            top[key] = value
        else:
            groups[owner][1][key] = value
    return SimulationConfig(
        battery=BatteryConfig(**groups["battery"][1]),
        grid=GridConfig(**groups["grid"][1]),
        policy=PolicyConfig(**groups["policy"][1]),
        **top,
    )


# ── Fixture 3: conservation — the identity every other fixture is checked against ─────────────


def _assert_conservation(frame: SimulationFrame, flows: Flows, standby_kwh: float, label: str):
    """§6.14 fixture 3: `Σ(pv + imp + dis) == Σ(load + exp + chg) ± CLOSURE_TOL`, per run.

    **What each side has to contain, and the one term the naive form is missing.**

    The identity is an AC-side energy balance at the household boundary, per interval:

        pv + imp + dis_home + dis_grid  ==  load + exp + chg_pv + chg_grid + curtailed

    Left: everything arriving at the AC bus. Right: everything leaving it. Three points where a
    plausible reading goes wrong:

    * `load` is the STANDBY-INCLUSIVE load in runs B and C. Standby is added to the load in §6.9's
      caller, so it is part of what the bus had to serve; using `frame.load` here would leave the
      identity short by exactly the standby draw in run C and close in run A, which is precisely
      the asymmetry that would make a reader trust the wrong side.
    * `curtailed` belongs on the RIGHT. It is PV that arrived at the bus (so it is counted in `pv`
      on the left) and was neither exported, consumed nor stored — generated and discarded. The
      identity as §6.14 writes it omits it, and does NOT close without it whenever an export limit
      binds; this is the term stated in the module's own comment.
    * **No SoC term appears.** `chg_*` and `dis_*` are AC-side quantities, so the conversion losses
      and the energy still sitting in the battery are both already outside this balance. An
      identity written in STORAGE units would need `soc_end − soc_start`; this one must not have
      it, and adding it would break closure by exactly the conversion loss.

    Asserted over NON-GAP intervals only (§7.3 check 3: gaps are excluded from sums), which is what
    `Flows.totals()`' `nansum` does.

    ## What this identity does NOT cover — read this before relying on it

    **On the unconstrained path it is §6.8 step 5 algebraically rearranged, and therefore close to
    tautological.** Step 5 computes the grid flows as the residual of the household balance:

        net_flow = load + chg_pv + chg_grid − pv − dis_ac
        imp = max(0, net_flow);  exp = max(0, −net_flow)

    Since exactly one of `imp`/`exp` is positive and `dis_ac == dis_home + dis_grid`, substituting
    `imp − exp = net_flow` into the identity above and moving terms across gives back step 5
    unchanged. So whenever neither connection cap binds, conservation closes BY CONSTRUCTION — not
    because the dispatch was right, but because `imp` and `exp` were DEFINED as whatever makes it
    close. A defect confined to step 5's inputs is invisible to it.

    Demonstrated rather than assumed: mutating step 4's `withdrawn = dis_ac / eta_d` to
    `withdrawn = dis_ac` — dropping the discharge conversion, a genuinely energy-creating defect
    that returns more AC than the battery ever stored — leaves this identity closing perfectly, in
    every run. `withdrawn` is a STORAGE-side quantity and no storage term appears here at all (see
    the third bullet above), so there is nothing for it to unbalance. What catches that mutation is
    the hand-computed fixtures: 1, 2 and 16, whose expected numbers were derived from the spec's
    efficiency convention rather than from the implementation's own arithmetic.

    **Where it does earn its place: steps 6 and 7.** Once a cap binds, the rearrangement no longer
    holds trivially — the shed and curtailment paths adjust `chg_grid`, `dis_grid`, `stored`,
    `withdrawn`, `imp`, `exp` and `curtailed` in several places, by hand, AFTER step 5 computed the
    residual, and any of those adjustments failing to keep the books is a real defect this catches.
    `test_fixture_3_conservation_holds_with_curtailment_and_gaps` is the case that exercises it;
    the unconstrained variant is a regression guard on step 5 keeping its residual form.

    **Note for Phase 4 (§6.11 metrics).** The metrics are computed from these same flow arrays, and
    this identity is NOT a general safety net over them. It cannot detect a wrong efficiency
    convention, a wrong `withdrawn`, a wrong SoC trajectory, or any error that stays on the storage
    side of the inverter. A new metric needs its own hand-computed fixture; "conservation still
    closes" says nothing about it.
    """
    ok = ~flows.gap
    load = frame.load + standby_kwh
    lhs = np.nansum(frame.pv[ok]) + np.nansum(flows.imp[ok]) + np.nansum(
        flows.dis_home[ok] + flows.dis_grid[ok]
    )
    rhs = (
        np.nansum(load[ok])
        + np.nansum(flows.exp[ok])
        + np.nansum(flows.chg_pv[ok] + flows.chg_grid[ok])
        + np.nansum(flows.curtailed[ok])
    )
    assert abs(lhs - rhs) < CLOSURE_TOL, f"{label}: conservation off by {lhs - rhs}"


def test_fixture_3_conservation_holds_for_runs_a_b_and_c():
    """Fixture 3, over data that exercises PV surplus, deficit, charging and discharging.

    **This is the near-tautological variant.** No connection cap binds here, so the identity is
    §6.8 step 5 rearranged and closes by construction — see `_assert_conservation`'s docstring for
    the algebra and for the `withdrawn` mutation that survives it. Kept as a regression guard that
    step 5 still computes the grid flows as the residual of the household balance (a rewrite that
    made `imp` or `exp` an independent quantity would break it), NOT as evidence the dispatch is
    numerically right. The hand-computed fixtures 1, 2 and 16 are what establish that.
    """
    n = 96
    hours = np.arange(n) % 24
    # A diurnal PV bell and a two-peak load, so surplus and deficit both occur every day.
    pv = np.where((hours >= 8) & (hours < 17), 3.0 * np.sin((hours - 8) / 9 * np.pi), 0.0)
    load = 0.4 + np.where((hours >= 7) & (hours < 9), 1.5, 0.0) + np.where(hours >= 18, 1.8, 0.0)
    spot = 0.05 + 0.15 * np.sin(hours / 24 * 2 * np.pi)
    frame = _frame(load, pv, spot)
    cfg = _cfg(
        charge_policy=ChargePolicy.P3,
        discharge_policy=DischargePolicy.D3,
        band_a=-1.0,
        band_b=0.04,
        band_c=0.15,
        band_d=9.999,
        allow_grid_export=True,
    )
    runs = run_all(frame, cfg)

    _assert_conservation(frame, runs.a, 0.0, "run A")
    _assert_conservation(frame, runs.b, 0.0, "run B")
    _assert_conservation(frame, runs.c, cfg.standby_kw * frame.dt_hours, "run C")

    # The runs must actually have done something, or the identity closes trivially at 0 == 0.
    assert runs.c.totals()["chg_pv"] > 0
    assert runs.c.totals()["chg_grid"] > 0
    assert runs.c.totals()["dis_home"] > 0


def test_fixture_3_conservation_holds_with_curtailment_and_gaps():
    """Fixture 3 again, with the two terms that make the naive identity fail: curtailment and gaps.

    A tight export cap forces curtailment (the term §6.14's written form omits) and two NaN load
    intervals force gaps (which must be excluded from BOTH sides, not just one).

    **This is the variant where the identity is actually load-bearing.** The export cap binds, so
    §6.8 step 6 runs and adjusts `dis_grid`, `withdrawn`, `exp` and `curtailed` by hand AFTER step 5
    computed its residual — at which point the rearrangement that makes the sibling test tautological
    no longer holds, and a step-6 adjustment that fails to keep the books shows up here. The gaps do
    the same job for §6.9's exclusion path. See `_assert_conservation` for what the identity still
    cannot see (anything on the storage side of the inverter).
    """
    n = 48
    hours = np.arange(n) % 24
    pv = np.where((hours >= 9) & (hours < 16), 8.0, 0.0)
    load = np.full(n, 0.5)
    load[5] = np.nan
    load[30] = np.nan
    frame = _frame(load, pv)
    cfg = _cfg(max_export_kw=1.0, charge_policy=ChargePolicy.P1, discharge_policy=DischargePolicy.D1)
    runs = run_all(frame, cfg)

    assert runs.a.totals()["curtailed"] > 0
    assert runs.c.totals()["curtailed"] > 0
    assert runs.c.gap.sum() == 2
    _assert_conservation(frame, runs.a, 0.0, "run A")
    _assert_conservation(frame, runs.b, 0.0, "run B")
    _assert_conservation(frame, runs.c, cfg.standby_kw * frame.dt_hours, "run C")


# ── Fixture 2: efficiency ────────────────────────────────────────────────────────────────────


def test_fixture_2_round_trip_returns_9_kwh_and_stores_9_486():
    """§6.14 fixture 2: 10 kWh in, 9.0 kWh out at 90% RTE — loss 1.0 kWh, not 0.9 and not 1.11.

    **The intermediate stored value is the load-bearing assertion.** Putting the whole loss on the
    charge side (eta_c = 0.9, eta_d = 1.0) ALSO returns 9.0 kWh AC and would pass an output-only
    test; it stores 9.0 kWh rather than 9.4868, and the SoC is the only place the two conventions
    differ. Splitting the loss linearly (0.95/0.95) returns 9.025, and applying 0.9 on both sides
    returns 8.1 — both excluded by the output assertion alone, the first convention is not.

    Run as ONE charge and ONE discharge through `battery_step` directly, at a power and duration
    that let the whole 10 kWh move in a single interval, so nothing else (rated power, a band, the
    household load) is between the input and the number under test.
    """
    cfg = _cfg(
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        max_charge_kw=20.0,
        max_discharge_kw=20.0,
        roundtrip_efficiency=0.90,
        coupling=Coupling.AC,
        has_pv=False,
        # The default 1×25 A connection caps import at 5.75 kW, which would shed the grid charging
        # in step 6 and make this a test of the connection rather than of the efficiency split.
        max_import_kw_override=100.0,
    )
    lim = _StepLimits.of(cfg, 1.0)

    # Charge: request more AC than the battery can hold, so step 3's headroom clamp decides.
    soc, f_chg, _ = battery_step(0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0.0, lim)
    assert soc == pytest.approx(10.0, abs=CLOSURE_TOL)
    ac_in = f_chg.chg_pv + f_chg.chg_grid
    # 10 / sqrt(0.9): the AC energy that stores exactly 10 kWh.
    assert ac_in == pytest.approx(10.0 / _ETA, abs=CLOSURE_TOL)

    # Discharge everything back.
    soc2, f_dis, _ = battery_step(soc, 0.0, 0.0, 20.0, 0.0, 20.0, 0.0, lim)
    assert soc2 == pytest.approx(0.0, abs=CLOSURE_TOL)
    ac_out = f_dis.dis_home + f_dis.dis_grid
    assert ac_out == pytest.approx(10.0 * _ETA, abs=CLOSURE_TOL)

    # And now the fixture as §6.14 states it: a FULL 10 kWh of AC charge returns 9.0 kWh AC.
    soc, f_chg, _ = battery_step(0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, lim)
    assert f_chg.stored == pytest.approx(9.486832980505138, abs=1e-9)  # NOT 9.0 — see the docstring
    assert soc == pytest.approx(9.486832980505138, abs=1e-9)
    _, f_dis, _ = battery_step(soc, 0.0, 0.0, 20.0, 0.0, 20.0, 0.0, lim)
    returned = f_dis.dis_home + f_dis.dis_grid
    assert returned == pytest.approx(9.0, abs=1e-9)
    assert 10.0 - returned == pytest.approx(1.0, abs=1e-9)  # not 0.9, not 1.11


def test_fixture_2_dc_coupling_applies_the_bonus_to_the_pv_path_only():
    """§6.8 step 3: `eta_c_dc` multiplies `chg_pv`; `chg_grid` keeps `eta_c` in the same interval."""
    cfg = _cfg(
        usable_capacity_kwh=100.0,
        min_soc_pct=0.0,
        max_charge_kw=20.0,
        roundtrip_efficiency=0.90,
        roundtrip_dc_bonus=0.04,
        coupling=Coupling.DC_HYBRID,
        has_pv=True,
        max_import_kw_override=100.0,  # keep the connection out of this test — see fixture 2 above
    )
    lim = _StepLimits.of(cfg, 1.0)
    _, f, _ = battery_step(0.0, 4.0, 6.0, 0.0, 0.0, 0.0, 4.0, lim)
    assert f.chg_pv == pytest.approx(4.0)
    assert f.chg_grid == pytest.approx(6.0)
    assert f.stored == pytest.approx(4.0 * math.sqrt(0.94) + 6.0 * math.sqrt(0.90), abs=1e-12)


# ── Fixture 1: trivial ───────────────────────────────────────────────────────────────────────


def test_fixture_1_trivial_p2_charges_at_rated_power_in_band():
    """§6.14 fixture 1: flat 1 kW load, no PV, flat price, P2/D2 with DISJOINT bands, price in [A,B].

    With the flat price inside the charge band and outside the discharge band, D2 never fires and
    the battery simply fills at rated power and then sits. Every number below is hand-computed:

        window            10 kWh usable × (100% − 0%)                        = 10.00 kWh
        AC per interval   2 kW × 1 h                                         =  2.00 kWh
        stored per int.   2 × sqrt(0.9)                                      =  1.8974 kWh
        full after        10 / 1.8974                                        =  5.27 intervals
                          → 5 full intervals, a 6th partial, then idle
        import per int.   load 1.0 + charge AC 2.0                           =  3.00 kWh (whilst filling)
                          load 1.0 alone                                     =  1.00 kWh (once full)
        throughput        withdrawn == 0 (nothing discharged)
        cycles (efc)      withdrawn / usable_capacity                        =  0
    """
    n = 12
    frame = _frame(np.full(n, 1.0), spot=np.full(n, 0.02))
    cfg = _cfg(
        has_pv=False,
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=0.0,
        max_charge_kw=2.0,
        max_discharge_kw=2.0,
        roundtrip_efficiency=0.90,
        standby_w=0.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0,
        band_b=0.05,  # 0.02 is inside  → charge
        band_c=0.30,
        band_d=9.999,  # 0.02 is outside → no discharge
    )
    out = simulate(frame, cfg)

    stored_per_interval = 2.0 * _ETA
    full_intervals = 5  # 5 × 1.8974 = 9.487 < 10; the 6th tops up the remaining 0.513
    for i in range(full_intervals):
        assert out.chg_grid[i] == pytest.approx(2.0, abs=CLOSURE_TOL)
        assert out.chg_pv[i] == 0.0
        assert out.imp[i] == pytest.approx(3.0, abs=CLOSURE_TOL)
        assert out.soc[i] == pytest.approx((i + 1) * stored_per_interval, abs=CLOSURE_TOL)

    # The partial interval: exactly the headroom is stored, and only the AC needed for it is drawn.
    remaining = 10.0 - full_intervals * stored_per_interval
    assert out.stored[5] == pytest.approx(remaining, abs=CLOSURE_TOL)
    assert out.chg_grid[5] == pytest.approx(remaining / _ETA, abs=CLOSURE_TOL)
    assert out.imp[5] == pytest.approx(1.0 + remaining / _ETA, abs=CLOSURE_TOL)
    assert out.soc[5] == pytest.approx(10.0, abs=CLOSURE_TOL)

    # Full: the battery does nothing at all, and the house imports its bare 1 kWh.
    for i in range(6, n):
        assert out.chg_grid[i] == pytest.approx(0.0, abs=CLOSURE_TOL)
        assert out.imp[i] == pytest.approx(1.0, abs=CLOSURE_TOL)
        assert out.soc[i] == pytest.approx(10.0, abs=CLOSURE_TOL)

    assert np.nansum(out.withdrawn) == pytest.approx(0.0, abs=CLOSURE_TOL)  # D2 never fired
    _assert_conservation(frame, out, 0.0, "fixture 1 charge phase")


def test_fixture_1_trivial_d2_discharges_at_rated_power_in_band():
    """Fixture 1's other half: the flat price inside `[C,D]` and outside `[A,B]` — D2 only.

    D2 discharges at full rated power but §6.7 serves the HOUSE first and `allow_grid_export` is
    off, so the delivered AC is `min(rated, deficit)` = 1.0 kWh/interval, not the 2 kW rating.
    Hand-computed:

        start SoC       10 kWh × 100%                                 = 10.00 kWh
        AC per interval min(2 kW × 1 h, deficit 1.0)                  =  1.00 kWh
        withdrawn/int.  1.0 / sqrt(0.9)                               =  1.0541 kWh
        empties after   10 / 1.0541                                   =  9.49 intervals
        import per int. 0 while discharging (deficit fully served)
    """
    n = 12
    frame = _frame(np.full(n, 1.0), spot=np.full(n, 0.40))
    cfg = _cfg(
        has_pv=False,
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=100.0,
        max_charge_kw=2.0,
        max_discharge_kw=2.0,
        roundtrip_efficiency=0.90,
        standby_w=0.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0,
        band_b=0.05,  # 0.40 outside → no charging
        band_c=0.30,
        band_d=9.999,  # 0.40 inside  → discharge
    )
    out = simulate(frame, cfg)

    withdrawn_per_interval = 1.0 / _ETA
    for i in range(9):
        assert out.dis_home[i] == pytest.approx(1.0, abs=CLOSURE_TOL)
        assert out.dis_grid[i] == 0.0  # allow_grid_export is off
        assert out.imp[i] == pytest.approx(0.0, abs=CLOSURE_TOL)
        assert out.withdrawn[i] == pytest.approx(withdrawn_per_interval, abs=CLOSURE_TOL)
        assert out.soc[i] == pytest.approx(10.0 - (i + 1) * withdrawn_per_interval, abs=CLOSURE_TOL)

    # Interval 9 empties what is left; from 10 on the house is back on the grid.
    assert out.soc[9] == pytest.approx(0.0, abs=CLOSURE_TOL)
    for i in range(10, n):
        assert out.dis_home[i] == pytest.approx(0.0, abs=CLOSURE_TOL)
        assert out.imp[i] == pytest.approx(1.0, abs=CLOSURE_TOL)

    # Throughput and cycles, on the STORAGE side per §6.11's convention.
    assert np.nansum(out.withdrawn) == pytest.approx(10.0, abs=CLOSURE_TOL)
    efc = np.nansum(out.withdrawn) / cfg.battery.usable_capacity_kwh
    assert efc == pytest.approx(1.0, abs=CLOSURE_TOL)
    _assert_conservation(frame, out, 0.0, "fixture 1 discharge phase")


# ── Fixture 16: no-PV arbitrage ──────────────────────────────────────────────────────────────


def _square_wave_frame(days: int) -> SimulationFrame:
    """Flat 1 kW load, NO PV, price alternating daily: 12 h low then 12 h high (fixture 16)."""
    n = 24 * days
    hours = np.arange(n) % 24
    spot = np.where(hours < 12, 0.02, 0.40)  # 0.02 inside [A,B]; 0.40 inside [C,D]
    return _frame(np.full(n, 1.0), pv=np.zeros(n), spot=spot)


def _arbitrage_cfg(**kw) -> SimulationConfig:
    base = dict(
        has_pv=False,
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=0.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        roundtrip_efficiency=0.90,
        standby_w=30.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0,
        band_b=0.05,
        band_c=0.30,
        band_d=9.999,
        allow_grid_export=False,
        # The appendix-A default connection is 1×25 A → 5.75 kW, and this fixture's 5 kW charge
        # request plus the ~1 kW load exceeds it, so §6.8 step 6 sheds grid charging from 5.0 down
        # to 4.72 kWh/h in the first hours of every low-price window. The results are unaffected —
        # the 12-hour window has enough slack that the battery still fills, one hour later, and the
        # totals, `efc`, `saved`, `standby_kwh` and `conversion_loss` are identical to within 1e-14
        # with and without this override — but the analytic derivation in
        # `test_fixture_16_no_pv_arbitrage_one_full_cycle_per_day`'s docstring reasons about a 5 kW
        # charge rate, and a test should exercise the rate it derives from. Fixture 16 is about
        # dispatch arithmetic; the connection limit has its own tests below.
        max_import_kw_override=100.0,
    )
    base.update(kw)
    return _cfg(**base)


def test_fixture_16_no_pv_arbitrage_one_full_cycle_per_day():
    """§6.14 fixture 16, with the saving derived analytically rather than read off the run.

    **The setup.** `has_pv = false` and no solar series at all (an all-zero `pv`, which is what §4.4
    fills the field with), flat 1 kW load, and a square-wave price alternating daily between 0.02
    (inside the charge band [−1, 0.05]) and 0.40 (inside the discharge band [0.30, 9.999]). P2/D2,
    no grid export, 10 kWh usable over a full 0–100% window, 5 kW each way, 90% RTE, 30 W standby.

    **Why exactly one full cycle per day.** During the 12 low hours P2 charges at 5 kW, which could
    move 60 kWh AC — far more than the 10.54 kWh AC needed to fill the 10 kWh window — so the
    battery reaches `soc_max` and stops. During the 12 high hours D2 discharges, but §6.7 serves
    the house first and export is off, so the delivered AC is capped by the deficit at 1.03 kWh/h;
    over 12 hours that is 12.36 kWh AC of demand against the 9.4868 kWh AC the full battery can
    return, so it empties completely. Both ends bind, so the cycle is exactly one per day and the
    day is periodic: it starts and ends at SoC 0.

    **The analytic saving, per steady-state day.** In kWh of grid import avoided:

        baseline import   24 h × 1.00 kWh                            = 24.0000 kWh
        battery import    load+standby 24 × 1.03                     = 24.7200
                        + AC drawn to fill    10 / sqrt(0.9)         = 10.5409
                        − AC returned          10 × sqrt(0.9)        = −9.4868
                                                                       ---------
                                                                       25.7741 kWh
        saved_kwh                                24.0000 − 25.7741   = −1.7741 kWh

    which decomposes exactly into the two terms the spread cannot touch:

        standby           0.030 kW × 24 h                            =  0.7200 kWh
        round-trip loss   10 × (1/sqrt(0.9) − sqrt(0.9))             =  1.0541 kWh
                                                                       ---------
                                                                        1.7741 kWh

    **The saving is NEGATIVE in kWh, and that is correct output.** §7.2 item 9 states it plainly:
    without PV the battery's value is entirely in the price SPREAD, which is a euro quantity. An
    energy-only run of an arbitrage configuration measures only what the arbitrage costs in kWh —
    the standby draw and the round-trip loss. Asserting a positive saving here would be asserting a
    bug. The euro side belongs to §6.10 and is not computed in this phase.
    """
    days = 5
    frame = _square_wave_frame(days)
    cfg = _arbitrage_cfg()
    runs = run_all(frame, cfg)

    # One full cycle per day: the SoC hits both bounds each day and returns to 0 at day's end.
    for d in range(days):
        day = runs.c.soc[d * 24 : (d + 1) * 24]
        assert day.max() == pytest.approx(10.0, abs=CLOSURE_TOL), f"day {d} never filled"
        assert day[-1] == pytest.approx(0.0, abs=CLOSURE_TOL), f"day {d} did not end empty"
    efc = np.nansum(runs.c.withdrawn) / cfg.battery.usable_capacity_kwh
    assert efc == pytest.approx(float(days), abs=1e-6)  # exactly `days` equivalent full cycles

    # The analytic saving, term by term, over the steady-state days (day 0 starts empty like the
    # rest, so every day is steady state here).
    standby_per_day = 0.030 * 24
    roundtrip_loss_per_day = 10.0 * (1.0 / _ETA - _ETA)
    expected_saved_per_day = -(standby_per_day + roundtrip_loss_per_day)
    assert expected_saved_per_day == pytest.approx(-1.7740925533894583, abs=1e-9)

    saved = np.nansum(runs.a.imp) - np.nansum(runs.c.imp)
    assert saved == pytest.approx(days * expected_saved_per_day, abs=1e-6)

    # And the two components separately, so a failure says which one moved.
    standby_kwh = runs.standby_kwh
    assert standby_kwh == pytest.approx(days * standby_per_day, abs=1e-6)
    conversion_loss = (
        np.nansum(runs.c.chg_pv + runs.c.chg_grid)
        - np.nansum(runs.c.dis_home + runs.c.dis_grid)
        - (runs.c.soc_end - runs.c.soc_start)
    )
    assert conversion_loss == pytest.approx(days * roundtrip_loss_per_day, abs=1e-6)

    _assert_conservation(frame, runs.c, cfg.standby_kw * frame.dt_hours, "fixture 16 run C")


def test_fixture_16_self_consumption_is_undefined_without_pv():
    """Fixture 16's null-not-zero clause, asserted at the layer this phase actually owns.

    §6.11 computes `self_consumption = (1 − export/pv) if pv.sum() > DIV_GUARD_EPS else None` and
    §6.14 fixture 16 requires `ratios.self_consumption_*` to be `null`, never 0 — 0 would assert
    that none of the generated energy was self-consumed, which is a claim about generation that did
    not happen. The RATIO is Phase 4's, so what is assertable here is the condition it keys on:
    total PV is exactly zero, which is what puts the metric in null territory rather than in a
    `1 − 0/0` or a `1 − x/tiny` one. Asserted rather than assumed, because a core that quietly
    fabricated PV (say by treating an absent array as the load) would still produce a plausible
    saving and would only show up here.
    """
    frame = _square_wave_frame(2)
    runs = run_all(frame, _arbitrage_cfg())
    assert float(np.nansum(frame.pv)) == 0.0
    assert float(np.nansum(runs.c.chg_pv)) == 0.0
    assert float(np.nansum(runs.c.exp)) == 0.0  # nothing to export without PV or grid discharge

    # Self-sufficiency, by contrast, IS always defined (§6.11) — the load is nonzero.
    load_total = float(np.nansum(frame.load))
    assert load_total > 0


def test_fixture_16_absent_solar_series_raises_no_missing_series_warning():
    """Fixture 16: no missing-series warning for the absent solar sensor.

    Check 4 (§7.3) is two-sided on PV — it blocks when `has_pv = true` and no solar series was
    mapped, and equally when a solar series was supplied with `has_pv = false`. Neither condition
    holds here. This module has no warning channel at all (it is a pure numeric core), so what is
    assertable at this layer is that the config is consistent and the run needs nothing more: the
    only warning-bearing surface the core exposes is `import_limit_exceeded`, and it stays empty.
    Check 4 itself is the ingest layer's, and is not re-implemented here.
    """
    cfg = _arbitrage_cfg()
    assert cfg.has_pv is False
    assert cfg.pv_coupling is None  # fixture 16's `topology.pv_coupling` is null clause
    assert cfg.validate().blocking is False
    runs = run_all(_square_wave_frame(2), cfg)
    assert runs.c.import_limit_exceeded == []


# ── Fixture 17: PV-invariance of the core ────────────────────────────────────────────────────


def test_fixture_17_pv_invariance_identical_energy_figures():
    """§6.14 fixture 17: has_pv=True + an all-zero solar series ≡ has_pv=False + no series at all.

    This pins the §6.6 decision that the numeric core "needs no branch on `has_pv` — it already
    computes the right answer — and should not acquire one". §4.4 makes `pv` unconditionally an
    array, all-zero when there is no PV, so the two configurations differ ONLY in a flag no
    dispatch code reads. Asserted bit-identically over every flow array, not just the totals: a
    branch that changed the SoC trajectory while leaving the annual import equal is exactly the
    kind of thing a totals-only assertion would miss.

    Note the frame is identical in both runs — that is the point. `has_pv_series` differs on the
    frame in the real pipeline, but it is a reporting field, not a dispatch input, and nothing in
    this module reads it.
    """
    frame = _square_wave_frame(3)

    with_pv = _arbitrage_cfg(has_pv=True, charge_policy=ChargePolicy.P3,
                             discharge_policy=DischargePolicy.D3)
    without_pv = _arbitrage_cfg(has_pv=False, charge_policy=ChargePolicy.P3,
                                discharge_policy=DischargePolicy.D3)
    # Phase 2 forces coupling to AC without PV; with PV the default is AC too, so the DC bonus is
    # not what is being compared here — the flag alone is.
    assert with_pv.coupling == without_pv.coupling

    runs_with = run_all(frame, with_pv)
    runs_without = run_all(frame, without_pv)

    for name in ("imp", "exp", "chg_pv", "chg_grid", "dis_home", "dis_grid",
                 "stored", "withdrawn", "curtailed", "soc"):
        for label, ra, rb in (
            ("A", runs_with.a, runs_without.a),
            ("B", runs_with.b, runs_without.b),
            ("C", runs_with.c, runs_without.c),
        ):
            np.testing.assert_array_equal(
                getattr(ra, name), getattr(rb, name), err_msg=f"run {label}.{name} differs"
            )


def test_fixture_17_p3_degenerates_to_p2_and_p1_charges_nothing_without_pv():
    """The mechanism behind fixture 17, asserted directly on §6.6's request function.

    Without PV, `solar_surplus` is identically zero, so P1 requests nothing at all and P3's request
    is exactly P2's. If a `has_pv` branch were ever added, this is where it would show.
    """
    frame = _frame(np.full(4, 1.0), spot=np.full(4, 0.02))
    st = _View(frame, 0.0)
    cfg = _arbitrage_cfg()

    p1 = charge_request(ChargePolicy.P1, 0, st, cfg)
    p2 = charge_request(ChargePolicy.P2, 0, st, cfg)
    p3 = charge_request(ChargePolicy.P3, 0, st, cfg)
    assert p1 == (0.0, 0.0)
    assert p3 == p2
    assert p2[1] == pytest.approx(cfg.max_charge_kw * frame.dt_hours)


# ── §7.2 item 1: the export limit applies to the BASELINE too ────────────────────────────────


def test_section_7_2_item_1_export_limit_applies_to_the_baseline_run():
    """§7.2 item 1: "If an export limit is configured, run A must apply it too."

    Constructs data where PV substantially exceeds the export cap: 9 kWh/h of PV against a 0.5
    kWh/h load and a 2 kW export cap, so 6.5 kWh/h has nowhere to go in the baseline.

    Two assertions, and the second is the one §7.2 says is easy to get wrong:

      1. The baseline CURTAILS. `A.exp` never exceeds the cap and `A.curtailed` accounts for the
         difference exactly.
      2. The battery is NOT credited with avoiding a constraint the baseline never faced. The
         comparison is made against a deliberately-wrong baseline computed here — the uncapped
         `max(pv − load, 0)` a naive implementation would produce — and the saving measured against
         that wrong baseline is shown to be LARGER. That is the inflation §7.2 describes, and the
         test asserts the real implementation does not produce it.
    """
    n = 24
    pv = np.full(n, 9.0)
    load = np.full(n, 0.5)
    frame = _frame(load, pv)
    cap_kw = 2.0
    cfg = _cfg(
        max_export_kw=cap_kw,
        charge_policy=ChargePolicy.P1,
        discharge_policy=DischargePolicy.D1,
        usable_capacity_kwh=10.0,
        standby_w=0.0,
    )
    runs = run_all(frame, cfg)

    # 1. The baseline respects the cap and books the difference as curtailment.
    assert runs.a.exp.max() == pytest.approx(cap_kw * frame.dt_hours, abs=CLOSURE_TOL)
    uncapped_export = np.maximum(pv - load, 0.0)
    assert np.nansum(runs.a.curtailed) == pytest.approx(
        float(np.sum(uncapped_export) - np.nansum(runs.a.exp)), abs=CLOSURE_TOL
    )
    assert np.nansum(runs.a.curtailed) > 0  # the fixture must actually bind

    # 2. The battery is not credited with avoiding a constraint the baseline never faced.
    #    A baseline that ignored the cap would export freely and import the same amount, so the
    #    inflation shows up on the EXPORT side of the comparison rather than on import.
    correct_baseline_export = float(np.nansum(runs.a.exp))
    naive_baseline_export = float(np.sum(uncapped_export))
    assert naive_baseline_export > correct_baseline_export
    battery_export = float(np.nansum(runs.c.exp))
    saved_export_correct = correct_baseline_export - battery_export
    saved_export_naive = naive_baseline_export - battery_export
    assert saved_export_naive > saved_export_correct  # the inflation §7.2 warns about
    # And the honest figure: the battery reduces curtailment because it stores what could not be
    # exported — a real effect, measured against a baseline that faced the same cap.
    assert np.nansum(runs.c.curtailed) < np.nansum(runs.a.curtailed)


def test_baseline_without_an_export_limit_curtails_nothing():
    """The complement: with the cap above anything the household can export, run A curtails 0.

    Keeps the assertion above from passing for a baseline that curtails unconditionally.
    """
    n = 24
    frame = _frame(np.full(n, 0.5), pv=np.full(n, 9.0))
    cfg = _cfg(max_export_kw=100.0)
    runs = run_all(frame, cfg)
    assert np.nansum(runs.a.curtailed) == pytest.approx(0.0, abs=CLOSURE_TOL)
    assert np.nansum(runs.a.exp) == pytest.approx(24 * 8.5, abs=CLOSURE_TOL)


# ── Fixture 5: monotonicity ──────────────────────────────────────────────────────────────────


def test_fixture_5_larger_capacity_never_reduces_savings():
    """§6.14 fixture 5: larger capacity never reduces savings, all else equal.

    A violation indicates a clamping bug — the classic one being a headroom clamp in §6.8 step 3
    that scales the wrong quantity, which makes a bigger battery charge LESS in some interval.

    Run over a PV household (where a battery genuinely saves kWh) with a diurnal surplus and an
    evening peak, so a larger battery keeps capturing more surplus up to the point the data
    saturates it. Tested across several capacities including a very small and a very large one,
    with the saving required to be non-decreasing at every step and strictly increasing somewhere
    (a monotone-but-flat sequence would pass a `>=`-only test even from a battery that never ran).
    """
    n = 24 * 7
    hours = np.arange(n) % 24
    pv = np.where((hours >= 8) & (hours < 17), 4.0 * np.sin((hours - 8) / 9 * np.pi), 0.0)
    load = 0.3 + np.where((hours >= 18) & (hours < 23), 2.0, 0.0)
    frame = _frame(load, pv)

    capacities = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0]
    savings = []
    for cap in capacities:
        cfg = _cfg(
            usable_capacity_kwh=cap,
            min_soc_pct=0.0,
            max_soc_pct=100.0,
            initial_soc_pct=0.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            charge_policy=ChargePolicy.P1,
            discharge_policy=DischargePolicy.D1,
            standby_w=0.0,  # "all else equal": standby is capacity-independent but would add noise
        )
        runs = run_all(frame, cfg)
        savings.append(float(np.nansum(runs.a.imp) - np.nansum(runs.c.imp)))

    for (cap_lo, s_lo), (cap_hi, s_hi) in zip(
        zip(capacities, savings), zip(capacities[1:], savings[1:])
    ):
        assert s_hi >= s_lo - CLOSURE_TOL, (
            f"saving fell from {s_lo} at {cap_lo} kWh to {s_hi} at {cap_hi} kWh — clamping bug"
        )
    assert savings[-1] > savings[0] + CLOSURE_TOL  # the sequence actually moves


# ── SoC containment, gaps, netting, limits, NaN spot ─────────────────────────────────────────


def test_soc_never_escapes_its_window_over_a_long_randomised_run():
    """§6.8 step 7's assertion, exercised over noisy data rather than over hand-built intervals.

    The step function asserts containment internally, so this test's job is to reach the clamps
    from many directions at once: random PV and load with frequent surplus and deficit, a random
    price crossing both bands, and a starting SoC deliberately BELOW `soc_min` (which Phase 2 warns
    about but allows, and which is the one input that can drive step 4's available-energy term
    negative). Fixed seed so a failure is reproducible.

    The appendix-A default connection is left in place here, unlike fixture 16: reaching step 6's
    shed and curtailment paths from a direction no hand-built interval covers is part of what this
    test is for, and the seed does hit the export cap a couple of times. Nothing below asserts a
    specific dispatch rate, so the cap cannot invalidate an assertion the way it did there.
    """
    rng = np.random.default_rng(20260725)
    n = 8760
    pv = np.clip(rng.normal(1.2, 1.6, n), 0.0, None)
    load = np.clip(rng.normal(0.9, 0.7, n), 0.0, None)
    spot = rng.normal(0.10, 0.12, n)
    frame = _frame(load, pv, spot)
    cfg = _cfg(
        usable_capacity_kwh=12.0,
        min_soc_pct=15.0,
        max_soc_pct=90.0,
        initial_soc_pct=5.0,  # below the floor on purpose — see the docstring
        max_charge_kw=4.0,
        max_discharge_kw=4.0,
        charge_policy=ChargePolicy.P3,
        discharge_policy=DischargePolicy.D3,
        band_a=-1.0,
        band_b=0.06,
        band_c=0.14,
        band_d=9.999,
        allow_grid_export=True,
    )
    out = simulate(frame, cfg)

    # The below-floor initial SoC is clamped into the window before interval 0 — Phase 2's own
    # warning for this configuration says it "will be clamped at the first step", and without the
    # clamp the run would start outside the window and trip §6.8 step 7 immediately.
    assert cfg.initial_soc_kwh < cfg.soc_min_kwh
    assert out.soc_start == pytest.approx(cfg.soc_min_kwh, abs=CLOSURE_TOL)

    soc = out.soc[~np.isnan(out.soc)]
    assert soc.min() >= cfg.soc_min_kwh - CLOSURE_TOL
    assert soc.max() <= cfg.soc_max_kwh + CLOSURE_TOL
    # Both bounds must actually be touched, or the test proves nothing about the clamps.
    assert soc.min() == pytest.approx(cfg.soc_min_kwh, abs=1e-6)
    assert soc.max() == pytest.approx(cfg.soc_max_kwh, abs=1e-6)
    _assert_conservation(frame, out, cfg.standby_kw * frame.dt_hours, "randomised run")


def test_initial_soc_outside_the_window_is_clamped_before_the_first_interval():
    """Both directions of the clamp Phase 2's warning promises ("clamped at the first step").

    §7.3 check 11 does not block an `initial_soc_pct` outside `[min, max]` — Phase 2 warns and
    allows it, since §6.9 starts from that SoC and the run is otherwise well-defined. But §6.8's
    steps cannot bring an out-of-window SoC back in on their own (step 3 charges only toward
    `soc_max`, step 4 discharges only down to `soc_min`), so an unclamped start would sit outside
    the window and trip step 7's assertion on interval 0 — a crash on a configuration the spec
    permits. `soc_start` reports the clamped value, so §6.11's `soc_end − soc_start` drift figure
    measures against the SoC the run actually began from.
    """
    frame = _frame(np.full(4, 1.0), spot=np.full(4, 0.90))  # outside both bands: battery idle

    below = _cfg(usable_capacity_kwh=10.0, min_soc_pct=20.0, max_soc_pct=80.0,
                 initial_soc_pct=5.0, standby_w=0.0, has_pv=False)
    assert any(w.code == "initial_soc_outside_window" for w in below.validate().warnings)
    assert below.validate().blocking is False
    out = simulate(frame, below)
    assert out.soc_start == pytest.approx(2.0, abs=CLOSURE_TOL)  # 10 kWh × 20%
    assert out.soc[0] == pytest.approx(2.0, abs=CLOSURE_TOL)

    above = _cfg(usable_capacity_kwh=10.0, min_soc_pct=20.0, max_soc_pct=80.0,
                 initial_soc_pct=95.0, standby_w=0.0, has_pv=False)
    out = simulate(frame, above)
    assert out.soc_start == pytest.approx(8.0, abs=CLOSURE_TOL)  # 10 kWh × 80%


def test_nan_gaps_carry_soc_forward_and_move_no_energy():
    """§6.9: a NaN `load` or `pv` marks the interval as a gap, carries the SoC and moves nothing.

    Both NaN sources are exercised, and both a load gap and a pv gap are placed mid-charge so the
    carried SoC is visibly non-trivial. The flow arrays are NaN on a gap rather than 0 — a 0 would
    be a positive claim about an interval the simulation declined to evaluate (the same reasoning
    §4.4 gives for `spot`) — so the assertion is `isnan`, not `== 0`.
    """
    n = 10
    load = np.full(n, 1.0)
    pv = np.zeros(n)
    load[3] = np.nan
    pv[6] = np.nan
    frame = _frame(load, pv, spot=np.full(n, 0.02))
    cfg = _cfg(
        has_pv=False,
        usable_capacity_kwh=20.0,
        min_soc_pct=0.0,
        initial_soc_pct=0.0,
        max_charge_kw=1.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0,
        band_b=0.05,
        band_c=0.30,
        band_d=9.999,
        standby_w=0.0,
    )
    out = simulate(frame, cfg)

    assert list(np.flatnonzero(out.gap)) == [3, 6]
    for i in (3, 6):
        assert np.isnan(out.imp[i])
        assert np.isnan(out.chg_grid[i])
        assert np.isnan(out.stored[i])
        assert out.soc[i] == pytest.approx(out.soc[i - 1], abs=CLOSURE_TOL)  # carried forward

    # Energy moved in every non-gap interval, and the SoC advanced by the same step across a gap as
    # within a run of good intervals — i.e. the gap cost the battery nothing but the interval.
    step = out.soc[1] - out.soc[0]
    assert step > 0
    assert out.soc[4] - out.soc[3] == pytest.approx(step, abs=CLOSURE_TOL)
    assert np.nansum(out.chg_grid) == pytest.approx((n - 2) * 1.0, abs=CLOSURE_TOL)

    # And run A propagates the SAME gaps, so `saved_kwh = A.imp − C.imp` compares like with like.
    base = simulate_baseline(frame, cfg)
    np.testing.assert_array_equal(base.gap, out.gap)


def test_band_overlap_nets_charge_and_discharge_requests():
    """§6.7's closing block: when both bands contain the price, the requests are NETTED.

    Phase 2 WARNS about an overlapping configuration (check 12) but allows it, so the core must
    compute something well-defined. Asserted at two levels:

      * `net_requests` on its own, including the scaling that preserves each side's PV/grid split.
      * End to end: with fully overlapping bands and a price inside both, the battery does not
        charge and discharge in the same interval, and the SoC moves in exactly one direction.

    Without the netting the battery would pay the round-trip loss twice on energy that never needed
    to move, and the conservation identity would still close — which is why this needs its own test
    rather than being covered by fixture 3.
    """
    # Charge dominant: the net is a charge, and the PV/grid proportions survive the scaling.
    rp, rg, dh, dg = net_requests(2.0, 6.0, 1.0, 1.0)
    assert (dh, dg) == (0.0, 0.0)
    assert rp + rg == pytest.approx(8.0 - 2.0)
    assert rp / (rp + rg) == pytest.approx(2.0 / 8.0)  # split preserved

    # Discharge dominant: mirror image.
    rp, rg, dh, dg = net_requests(1.0, 1.0, 3.0, 5.0)
    assert (rp, rg) == (0.0, 0.0)
    assert dh + dg == pytest.approx(8.0 - 2.0)
    assert dh / (dh + dg) == pytest.approx(3.0 / 8.0)

    # Exactly equal: nets to zero, and §6.7's `net > 0` branch sends it to the charge side at 0.
    assert net_requests(2.0, 2.0, 2.0, 2.0) == (0.0, 0.0, 0.0, 0.0)

    # End to end over a fully overlapping band pair.
    n = 6
    frame = _frame(np.full(n, 1.0), spot=np.full(n, 0.20))
    cfg = _cfg(
        has_pv=False,
        usable_capacity_kwh=20.0,
        min_soc_pct=0.0,
        initial_soc_pct=50.0,
        max_charge_kw=3.0,
        max_discharge_kw=3.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=0.0,
        band_b=0.30,  # 0.20 inside
        band_c=0.10,
        band_d=0.30,  # 0.20 inside too
        standby_w=0.0,
    )
    assert cfg.bands_overlap()
    assert any(w.code == "bands_overlap" for w in cfg.validate().warnings)
    out = simulate(frame, cfg)
    charge = out.chg_pv + out.chg_grid
    discharge = out.dis_home + out.dis_grid
    assert not np.any((charge > CLOSURE_TOL) & (discharge > CLOSURE_TOL))
    # Charge requests 3.0 (full power), discharge requests min(3.0, deficit 1.0) = 1.0 → net charge.
    assert np.all(discharge <= CLOSURE_TOL)
    assert out.chg_grid[0] == pytest.approx(2.0, abs=CLOSURE_TOL)


def test_import_limit_sheds_grid_charging_before_flagging():
    """§6.8 step 6: on an import overrun, GRID CHARGING is shed first; only then is it flagged.

    Two cases, and the ORDER between them is the assertion:

      * Load 1 kWh + a 5 kWh grid-charge request against a 3 kWh cap → the charge is cut to 2 kWh,
        the import lands exactly on the cap, `stored` is reduced by the shed energy at `eta_c`, and
        NOTHING is flagged: the connection was never actually exceeded.
      * Load 6 kWh alone against the same 3 kWh cap → there is no discretionary draw to shed, the
        import stays at 6 kWh (the house really did draw it) and the interval IS flagged.

    The distinction matters because a flag on the first case would tell the user their connection
    was overloaded when the simulator simply chose to charge less, and no flag on the second would
    hide a genuine finding — usually a mis-entered fuse rating.
    """
    cfg = _cfg(
        has_pv=False,
        usable_capacity_kwh=50.0,
        min_soc_pct=0.0,
        max_charge_kw=5.0,
        max_import_kw_override=3.0,
        roundtrip_efficiency=0.90,
    )
    lim = _StepLimits.of(cfg, 1.0)

    _, f, flagged = battery_step(0.0, 0.0, 5.0, 0.0, 0.0, 1.0, 0.0, lim)
    assert f.chg_grid == pytest.approx(2.0, abs=CLOSURE_TOL)  # 5 shed down to 2
    assert f.imp == pytest.approx(3.0, abs=CLOSURE_TOL)  # exactly the cap
    assert f.stored == pytest.approx(2.0 * _ETA, abs=CLOSURE_TOL)  # shed at eta_c
    assert flagged is False

    _, f, flagged = battery_step(0.0, 0.0, 0.0, 0.0, 0.0, 6.0, 0.0, lim)
    assert f.imp == pytest.approx(6.0, abs=CLOSURE_TOL)  # not clipped: the house drew it
    assert flagged is True


def test_export_limit_sheds_arbitrage_export_before_curtailing_pv():
    """§6.8 step 6's second half: shed ARBITRAGE EXPORT first, then curtail PV.

    Constructed so both are available at once: 6 kWh of PV and a battery discharging 4 kWh to the
    grid against a 2 kWh export cap and no load, i.e. 10 kWh wanting out through a 2 kWh door.
    The order is what is asserted — the full 4 kWh of arbitrage export is cut before a single kWh
    of PV is curtailed, leaving 4 kWh of curtailment (6 PV − 2 exported).

    The order is not arbitrary: arbitrage export is a discretionary choice the policy made and can
    unmake at no cost, whereas curtailment discards energy that was actually generated. Shedding in
    the other order would throw away free PV to preserve a battery discharge that earns less.
    """
    cfg = _cfg(
        usable_capacity_kwh=50.0,
        min_soc_pct=0.0,
        max_charge_kw=10.0,
        max_discharge_kw=10.0,
        max_export_kw=2.0,
        allow_grid_export=True,
        roundtrip_efficiency=0.90,
    )
    lim = _StepLimits.of(cfg, 1.0)

    soc_before = 20.0
    soc_after, f, _ = battery_step(soc_before, 0.0, 0.0, 0.0, 4.0, 0.0, 6.0, lim)
    assert f.dis_grid == pytest.approx(0.0, abs=CLOSURE_TOL)  # arbitrage export shed entirely
    assert f.exp == pytest.approx(2.0, abs=CLOSURE_TOL)  # at the cap
    assert f.curtailed == pytest.approx(4.0, abs=CLOSURE_TOL)  # 6 PV − 2 exported
    # `withdrawn` was reduced along with the shed discharge, so the SoC is untouched.
    assert f.withdrawn == pytest.approx(0.0, abs=CLOSURE_TOL)
    assert soc_after == pytest.approx(soc_before, abs=CLOSURE_TOL)

    # Widen the cap to 8 kWh and the same 10 kWh still does not fit: 2 kWh must go, and it comes
    # off the ARBITRAGE EXPORT (4 → 2), leaving the PV entirely uncurtailed. This is the assertion
    # that separates the two orderings — a PV-first implementation would curtail 2 kWh of PV here
    # and keep the full 4 kWh discharge, matching on `exp` but differing on both other fields.
    cfg2 = _cfg(
        usable_capacity_kwh=50.0,
        min_soc_pct=0.0,
        max_charge_kw=10.0,
        max_discharge_kw=10.0,
        max_export_kw=8.0,
        allow_grid_export=True,
    )
    lim2 = _StepLimits.of(cfg2, 1.0)
    _, f2, _ = battery_step(20.0, 0.0, 0.0, 0.0, 4.0, 0.0, 6.0, lim2)
    assert f2.dis_grid == pytest.approx(2.0, abs=CLOSURE_TOL)  # 4 shed to 2, not curtailed instead
    assert f2.exp == pytest.approx(8.0, abs=CLOSURE_TOL)
    assert f2.curtailed == pytest.approx(0.0, abs=CLOSURE_TOL)  # PV untouched


def test_nan_spot_idles_the_bands_but_not_deficit_or_surplus_dispatch():
    """A NaN `spot` interval: both band comparisons are False, so the battery idles on price.

    Phase 1 emits NaN for an interval no price covers (§4.4: absence is NaN, never 0, because an
    all-zero spot "would not mean 'no prices', it would mean 'prices are zero everywhere', and
    every band comparison would silently take a definite and wrong branch").

    `A <= nan <= B` is False under IEEE comparison semantics, so P2/D2 request nothing on such an
    interval — the battery idles rather than dispatching on a price nobody knows. That is the
    behaviour we want, but it arises from the comparison's semantics rather than from a test
    written for it, so it is pinned here explicitly. What is NOT suppressed is P1/P3 surplus
    charging and D1/D3 deficit service, neither of which reads `spot` at all: a missing price must
    not stop a battery from soaking up solar it can see.
    """
    n = 4
    spot = np.array([0.02, np.nan, 0.40, np.nan])
    frame = _frame(np.array([1.0, 1.0, 1.0, 1.0]), pv=np.array([0.0, 0.0, 0.0, 3.0]), spot=spot)
    cfg = _cfg(
        usable_capacity_kwh=20.0,
        min_soc_pct=0.0,
        initial_soc_pct=50.0,
        max_charge_kw=2.0,
        max_discharge_kw=2.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0,
        band_b=0.05,
        band_c=0.30,
        band_d=9.999,
        standby_w=0.0,
    )
    st = _View(frame, 0.0)
    assert charge_request(ChargePolicy.P2, 1, st, cfg) == (0.0, 0.0)  # NaN → not in band
    assert discharge_request(DischargePolicy.D2, 1, st, cfg) == (0.0, 0.0)
    assert charge_request(ChargePolicy.P2, 0, st, cfg)[1] > 0  # 0.02 is in band
    assert discharge_request(DischargePolicy.D2, 2, st, cfg)[0] > 0  # 0.40 is in band

    # A NaN spot interval is NOT a gap: it is simulated, it just does nothing on the price paths.
    out = simulate(frame, cfg)
    assert not out.gap.any()
    assert out.chg_grid[1] == pytest.approx(0.0, abs=CLOSURE_TOL)
    assert out.imp[1] == pytest.approx(1.0, abs=CLOSURE_TOL)  # the house still ran on the grid

    # Surplus charging is unaffected by the NaN price: P1 takes the 2 kWh of surplus at interval 3.
    cfg_p1 = _cfg(
        usable_capacity_kwh=20.0,
        min_soc_pct=0.0,
        initial_soc_pct=50.0,
        max_charge_kw=2.0,
        charge_policy=ChargePolicy.P1,
        discharge_policy=DischargePolicy.D1,
        standby_w=0.0,
    )
    out_p1 = simulate(frame, cfg_p1)
    assert out_p1.chg_pv[3] == pytest.approx(2.0, abs=CLOSURE_TOL)


# ── The run harness and the frame-mutation guard ─────────────────────────────────────────────


def test_runs_b_and_c_differ_by_exactly_the_standby_draw():
    """§6.9: "standby exists only with a battery", and `C − B` isolates it exactly.

    Run B has no purpose other than this, so the property is worth asserting directly: over data
    where the battery never runs out of a way to serve the extra draw, the import difference is the
    standby energy to the last decimal.
    """
    n = 48
    frame = _frame(np.full(n, 1.0), spot=np.full(n, 0.20))
    cfg = _cfg(
        has_pv=False,
        standby_w=30.0,
        charge_policy=ChargePolicy.P2,
        discharge_policy=DischargePolicy.D2,
        band_a=-1.0,
        band_b=0.05,  # 0.20 outside both bands: the battery does nothing at all
        band_c=0.50,
        band_d=9.999,
    )
    runs = run_all(frame, cfg)
    expected = 0.030 * n
    assert runs.standby_kwh == pytest.approx(expected, abs=1e-9)
    assert np.nansum(runs.b.imp) == pytest.approx(float(n), abs=1e-9)
    assert np.nansum(runs.c.imp) == pytest.approx(n + expected, abs=1e-9)
    # Run A has no battery, hence no standby, hence equals run B here.
    assert np.nansum(runs.a.imp) == pytest.approx(np.nansum(runs.b.imp), abs=1e-9)


def test_simulate_never_modifies_the_frames_arrays():
    """The frame's arrays are SHARED objects — the core must never write through to them.

    `frame.load`, `.pv`, `.import_obs` and `.export_obs` are the very arrays `reconcile_grid`
    produced, and the data-summary band and the panel-③ results view hold the same objects. §6.9's
    `st.load = frame.load + standby_kwh` REBINDS, which is safe; an `+=` would silently change
    numbers already published elsewhere in the app, for the life of the process, with nothing
    anywhere looking wrong. Asserted by value AND by identity, since a rebind that replaced the
    frame's own attribute would also pass a value check on a stale copy.
    """
    n = 24
    frame = _frame(np.full(n, 1.0), pv=np.full(n, 2.0), spot=np.full(n, 0.02))
    load_before, pv_before = frame.load.copy(), frame.pv.copy()
    load_obj, pv_obj = frame.load, frame.pv

    run_all(frame, _cfg(standby_w=250.0))  # a large standby, so a leak would be visible

    np.testing.assert_array_equal(frame.load, load_before)
    np.testing.assert_array_equal(frame.pv, pv_before)
    assert frame.load is load_obj
    assert frame.pv is pv_obj


def test_cancellation_hook_stops_the_loop_and_is_off_by_default():
    """§6.9's cancellation, as the injectable hook this increment provides instead of a threading model.

    The spec writes a module-level `cancel_event` polled every `CANCEL_CHECK_INTERVAL` intervals,
    which presupposes the run-orchestration layer of §3.3/§5.3 — and there is none yet. Rather than
    invent one, `should_cancel` is an optional callable; `None` skips the check entirely.
    """
    frame = _frame(np.full(4096, 1.0))
    cfg = _cfg()

    assert simulate(frame, cfg).intervals == 4096  # no hook → runs to completion

    calls = {"n": 0}

    def hook() -> bool:
        calls["n"] += 1
        return calls["n"] > 2  # let two checks pass, cancel on the third

    with pytest.raises(Cancelled):
        simulate(frame, cfg, should_cancel=hook)
    assert calls["n"] == 3


def test_flows_totals_exclude_gaps():
    """`Flows.totals()` is the single place gap exclusion (`nansum`, §7.3 check 3) is decided."""
    flows = Flows.empty(4, soc_start=1.0)
    flows.set(0, StepFlows(1.0, 0.0, 0.0, 2.0, 0.0, 0.0, 1.9, 0.0, 0.0))
    flows.mark_gap(1, 3.0)
    flows.set(2, StepFlows(4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5))
    flows.mark_gap(3, 3.0)

    totals = flows.totals()
    assert totals["imp"] == pytest.approx(5.0)
    assert totals["chg_grid"] == pytest.approx(2.0)
    assert totals["curtailed"] == pytest.approx(0.5)
    assert flows.soc_end == pytest.approx(3.0)  # carried across the trailing gap
    assert list(np.flatnonzero(flows.gap)) == [1, 3]
