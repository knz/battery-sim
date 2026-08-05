"""Fixtures for the §6.10 cost accounting and waterfall (app/domain/costs.py).

The centre of this file is validation-harness **fixture 4**, the waterfall closure identity:

    sum(waterfall) == cost(A) - cost(C) - degradation   +/- CLOSURE_TOL

Unlike the energy path's conservation identity, this one is NOT closed by construction — see
`tests/test_metrics.py`'s opening note on why fixture 3 says nothing about whether a metric is
right. `test_broken_waterfall_fails_the_closure` demonstrates the same discipline in the other
direction: it perturbs one line of a real waterfall and shows the closure catching it, so a reader
can see the assertion has teeth rather than taking it on trust.

What each group pins:

  * `test_compute_costs_*`       the bill against hand arithmetic: the export term is SUBTRACTED,
        a negative `p_export_net` raises the bill, the top-up is subtracted, gaps cost nothing.
  * `test_fixture_4_*`           the closure, over five shapes: hand-built flows with PV, export
        and negative prices; the same with zero degradation; a no-PV arbitrage run; a run with
        gaps; and a REAL `run_all()` output over a real frame, so the invariant is pinned against
        actual dispatch and not only against hand-made arrays.
  * `test_fixture_14_*`          the floor binding: a month whose export earns a net negative
        unclamped amount yields exactly zero compensation revenue under MONTHLY, the shortfall
        lands in `feedin_floor_topup` and in NO other line, and the closure still holds with the
        top-up nonzero.
  * `test_waterfall_lines_*`     §6.10's eight labels, in §6.10's order.
  * `test_degradation_*`         a zero-degradation run reports 0.0 rather than dropping the line.
  * `test_fixed_costs_*`         vastrecht and friends are absent; the bill is marginal only.

Frames are built with the same `_frame` / `_cfg` helpers `tests/test_simulate.py` uses, so all
three suites construct their inputs identically.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.costs import (
    WATERFALL_LINES,
    compute_costs,
    waterfall,
)
from app.domain.pricing import price_curves
from app.domain.simconfig import (
    ChargePolicy,
    DischargePolicy,
    FeedinFloorMode,
    PricingConfig,
)
from app.domain.simframe import CLOSURE_TOL
from app.domain.simulate import Flows, run_all
from tests.test_simulate import _arbitrage_cfg, _cfg, _frame


def _hours(start: str, n: int) -> np.ndarray:
    """`n` hourly interval STARTS from `start`, in the frame's UTC-naive datetime64[s] form."""
    return (np.datetime64(start, "s") + np.arange(n) * np.timedelta64(3600, "s")).astype(
        "datetime64[s]"
    )


def _flows(imp, exp, *, withdrawn=None, gap=None) -> Flows:
    """A `Flows` carrying only the fields §6.10 reads — `imp`, `exp`, `withdrawn` and `gap`.

    Built directly rather than by running the simulator, because the point of the hand-computed
    fixtures below is that every euro figure can be checked on paper. The unread fields are left
    at `Flows.empty`'s NaN, which is also what would catch this module quietly starting to read
    one of them: a NaN would propagate into the bill.

    `gap` marks intervals the run skipped; the flow arrays are set to NaN there, exactly as §6.9
    writes them, so the tests exercise the real absence and not a stand-in for it.
    """
    imp = np.asarray(imp, dtype=np.float64)
    exp = np.asarray(exp, dtype=np.float64)
    n = len(imp)
    f = Flows.empty(n)
    f.imp = imp.copy()
    f.exp = exp.copy()
    f.withdrawn = (
        np.zeros(n) if withdrawn is None else np.asarray(withdrawn, dtype=np.float64).copy()
    )
    if gap is not None:
        g = np.asarray(gap, dtype=bool)
        f.gap = g
        f.imp[g] = np.nan
        f.exp[g] = np.nan
        f.withdrawn[g] = np.nan
    return f


def _assert_fixture_4(a, b, c, curves, index, pcfg, label: str) -> float:
    """§6.14 fixture 4: `sum(waterfall) == cost(A) - cost(C) - degradation +/- CLOSURE_TOL`.

    Returns the waterfall's sum so a caller can assert something further about it.

    `degradation` on the right-hand side is the COST (a positive number of euros lost), while the
    eighth waterfall line is its negation, so the identity says in substance that the first seven
    lines reproduce `cost(A) - cost(C)` with nothing left over. Both forms are asserted, because
    the literal one is what the harness writes and the seven-line one is the statement with
    content.
    """
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    total = sum(line.eur for line in lines)
    cost_a = compute_costs(a, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg)
    cost_c = compute_costs(c, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg)
    degradation_cost = pcfg.degradation_eur_per_kwh * float(np.nansum(c.withdrawn))

    assert total == pytest.approx(cost_a.eur - cost_c.eur - degradation_cost, abs=CLOSURE_TOL), (
        f"{label}: waterfall sums to {total}, "
        f"expected {cost_a.eur - cost_c.eur - degradation_cost}"
    )
    seven = sum(line.eur for line in lines if line.label != "degradation")
    assert seven == pytest.approx(cost_a.eur - cost_c.eur, abs=CLOSURE_TOL), (
        f"{label}: the seven priced lines sum to {seven}, expected {cost_a.eur - cost_c.eur}"
    )
    return total


# ── compute_costs, against hand arithmetic ───────────────────────────────────────────────────


def test_compute_costs_subtracts_the_export_term() -> None:
    """§6.10: `(imp * p_import).sum() - (exp * p_export_net).sum()`, then minus the top-up.

    Two hourly intervals at a flat spot of 0.10 on appendix A's defaults:
        bare = 0.1205, p_import = (0.1205 + 0.09161) * 1.21 = 0.2566531,
        compensation = 0.06025, p_export_net = 0.06025 - 0.04 = 0.02025.

    imp = [2.0, 0.0], exp = [0.0, 3.0]:
        import cost   2.0 * 0.2566531 = 0.5133062
        export revenue 3.0 * 0.02025  = 0.06075
        bill = 0.5133062 - 0.06075    = 0.4525562

    The top-up is zero: the month's export earned `3.0 * 0.06025 = +0.18075`, comfortably positive,
    so the statutory floor does not bind.
    """
    pcfg = PricingConfig()
    index = _hours("2026-03-05T00:00:00", 2)
    curves = price_curves(pcfg, np.full(2, 0.10))
    result = compute_costs(
        _flows([2.0, 0.0], [0.0, 3.0]),
        curves.p_import, curves.p_export_net, curves.compensation, index, pcfg,
    )
    assert result.topup_eur == pytest.approx(0.0)
    assert result.per_interval_eur == pytest.approx(0.4525562)
    assert result.eur == pytest.approx(0.4525562)


def test_negative_export_price_increases_the_bill() -> None:
    """§6.10's "one of the more important things this tool can show a user".

    At a bare price of 0.06 (spot 0.0395) the compensation is 0.03 and the net after 4 ct of
    terugleverkosten is -0.01: exporting a kWh COSTS one cent. Two runs identical except that one
    exported 5 kWh in the second hour; the exporting run's bill is 5 * 0.01 = 0.05 HIGHER.

    The compensation itself is still positive here, so no top-up is due — the floor is assessed on
    the compensation, not on the net after charges (§6.5), and this test would be measuring the
    floor rather than the sign of the export term if it used a negative-price interval.
    """
    pcfg = PricingConfig()
    index = _hours("2026-03-05T00:00:00", 2)
    curves = price_curves(pcfg, np.full(2, 0.06 - 0.0205))
    assert curves.p_export_net == pytest.approx(np.full(2, -0.01))

    args = (curves.p_import, curves.p_export_net, curves.compensation, index, pcfg)
    no_export = compute_costs(_flows([1.0, 0.0], [0.0, 0.0]), *args)
    with_export = compute_costs(_flows([1.0, 0.0], [0.0, 5.0]), *args)
    assert with_export.eur - no_export.eur == pytest.approx(0.05)
    assert with_export.eur > no_export.eur


def test_gap_intervals_cost_exactly_zero() -> None:
    """A gap contributes nothing — not NaN, and not a number derived from a NaN flow.

    The same two-interval scenario as `test_compute_costs_subtracts_the_export_term`, with a third
    interval appended that the run gapped. Its flows are NaN (§6.9), so `NaN * price` is NaN and a
    plain `.sum()` would return NaN for the whole window. The bill must be unchanged.
    """
    pcfg = PricingConfig()
    index = _hours("2026-03-05T00:00:00", 3)
    curves = price_curves(pcfg, np.full(3, 0.10))
    gapped = _flows([2.0, 0.0, 9.0], [0.0, 3.0, 9.0], gap=[False, False, True])
    assert np.isnan(gapped.imp[2]) and np.isnan(gapped.exp[2])

    result = compute_costs(
        gapped, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg
    )
    assert np.isfinite(result.eur)
    assert result.eur == pytest.approx(0.4525562)


def test_an_uncovered_price_interval_costs_exactly_zero() -> None:
    """The other kind of absence: the flows are real but no price covers the interval (§4.4).

    `spot` is NaN in the third interval, so every price array is NaN there and the interval drops
    out of the bill by the same rule. This is the case a plain `.sum()` would turn into a NaN euro
    figure for a window that is priced almost everywhere.
    """
    pcfg = PricingConfig()
    index = _hours("2026-03-05T00:00:00", 3)
    curves = price_curves(pcfg, np.array([0.10, 0.10, np.nan]))
    result = compute_costs(
        _flows([2.0, 0.0, 4.0], [0.0, 3.0, 4.0]),
        curves.p_import, curves.p_export_net, curves.compensation, index, pcfg,
    )
    assert np.isfinite(result.eur)
    assert result.eur == pytest.approx(0.4525562)


def test_the_topup_is_subtracted_from_the_bill() -> None:
    """§6.10: the top-up is money received, so it reduces the bill.

    One month, hourly, with a single exporting interval at a deeply negative spot. spot -0.5205
    gives bare -0.5, compensation -0.25; exporting 4 kWh earns `4 * -0.25 = -1.00`, so under
    MONTHLY the floor binds and the top-up is exactly 1.00.

    The per-interval bill already charges the household for that export (the net is
    -0.25 - 0.04 = -0.29, so `-(4 * -0.29) = +1.16` on the bill); the top-up returns the
    compensation part of it, leaving the household paying only the 0.16 of terugleverkosten. That
    is the statutory floor working: compensation cannot go below zero over the period, but
    terugleverkosten is a separate charge and is not floored.
    """
    pcfg = PricingConfig()
    index = _hours("2026-03-05T00:00:00", 4)
    curves = price_curves(pcfg, np.full(4, -0.5205))
    result = compute_costs(
        _flows([0.0, 0.0, 0.0, 0.0], [4.0, 0.0, 0.0, 0.0]),
        curves.p_import, curves.p_export_net, curves.compensation, index, pcfg,
    )
    assert result.topup_eur == pytest.approx(1.0)
    assert result.per_interval_eur == pytest.approx(1.16)
    assert result.eur == pytest.approx(0.16)


def test_no_fixed_costs_are_added() -> None:
    """§6.10: vastrecht, netbeheerkosten and the vermindering energiebelasting are EXCLUDED.

    A run that imported nothing and exported nothing has a bill of exactly 0.00. Any standing
    charge folded into this module — a per-day vastrecht, a capaciteitstarief, an annual credit —
    would make this number nonzero, in either direction. The assertion is deliberately on a
    degenerate run: it is the only shape where "no fixed component" is observable without knowing
    the size of the component.
    """
    pcfg = PricingConfig()
    index = _hours("2026-03-05T00:00:00", 24)
    curves = price_curves(pcfg, np.full(24, 0.10))
    result = compute_costs(
        _flows(np.zeros(24), np.zeros(24)),
        curves.p_import, curves.p_export_net, curves.compensation, index, pcfg,
    )
    assert result.eur == 0.0


# ── Fixture 4: the waterfall closure ─────────────────────────────────────────────────────────


def _hand_built_scenario(degradation: float = 0.0):
    """Three hand-built runs over six hours with PV, export in both directions and a negative hour.

    Not a dispatch — the flows are chosen to exercise every waterfall line rather than to be
    physically derivable from a policy, which is what makes them useful here: run C imports less
    in some hours and MORE in others (grid charging), exports less in some and more in others
    (arbitrage export), and the sixth hour has a negative spot so the compensation is negative.

    Returns `(a, b, c, curves, index, pcfg)`.
    """
    spot = np.array([0.10, 0.30, 0.05, -0.20, 0.15, 0.02])
    pcfg = PricingConfig(degradation_eur_per_kwh=degradation)
    curves = price_curves(pcfg, spot)
    index = _hours("2026-04-10T00:00:00", 6)

    #        hour:      0     1     2     3     4     5
    a = _flows([1.0, 2.0, 0.0, 0.0, 1.5, 0.0],
               [0.0, 0.0, 3.0, 4.0, 0.0, 2.0])
    # B: battery, no standby. Imports more in hour 2 (grid charging), less in hour 1 (discharge),
    # exports less in hours 2-3 (charged instead) and more in hour 1 (arbitrage export).
    b = _flows([1.0, 0.5, 2.0, 0.0, 0.5, 0.0],
               [0.0, 1.0, 0.5, 1.0, 0.0, 2.5],
               withdrawn=[0.0, 1.6, 0.0, 0.0, 1.1, 0.0])
    # C: B plus a 0.03 kWh/h standby draw, served from the grid where there is grid, and shaved off
    # export otherwise.
    c = _flows([1.03, 0.53, 2.03, 0.0, 0.53, 0.0],
               [0.0, 1.0, 0.5, 0.97, 0.0, 2.47],
               withdrawn=[0.0, 1.6, 0.0, 0.0, 1.1, 0.0])
    return a, b, c, curves, index, pcfg


def test_fixture_4_closure_with_pv_export_and_negative_prices() -> None:
    """§6.14 fixture 4 over a scenario exercising all six per-interval lines, with degradation on.

    Degradation is 0.05 EUR/kWh withdrawn against 2.7 kWh withdrawn, so the eighth line is
    -0.135 and is a real term rather than a zero that the identity could not distinguish from an
    omission.
    """
    a, b, c, curves, index, pcfg = _hand_built_scenario(degradation=0.05)
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    by_label = {line.label: line.eur for line in lines}
    assert by_label["degradation"] == pytest.approx(-0.135)
    # Every per-interval line is genuinely exercised, so the closure is not passing on a scenario
    # where five of the eight terms are zero.
    for label in WATERFALL_LINES[:6]:
        assert abs(by_label[label]) > 1e-9, f"{label} is zero; the fixture does not exercise it"
    _assert_fixture_4(a, b, c, curves, index, pcfg, "hand-built, degradation on")


def test_degradation_is_charged_on_run_c_not_run_b() -> None:
    """§6.10: `-cfg.degradation_eur_per_kwh * C.withdrawn.sum()` — run C, the headline result.

    Asserted directly because no other test can see the difference. Every hand-built fixture gives
    B and C the same `withdrawn` (standby is served from the grid and from export, not by extra
    discharge), so swapping `c` for `b` in that line is invisible to them; it currently turns
    exactly one test red, and only because real dispatch happens to withdraw different amounts in
    that particular run. That is a dispatch accident, not coverage. Here the two runs are given
    deliberately different throughput so the line has to name the right one.
    """
    a, b, c, curves, index, pcfg = _hand_built_scenario(degradation=0.05)
    # 1.0 kWh through B, 4.0 through C — nothing else about the runs changes.
    b.withdrawn = np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0])
    c.withdrawn = np.array([0.0, 1.0, 0.0, 0.0, 3.0, 0.0])

    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    by_label = {line.label: line.eur for line in lines}
    # 4.0 kWh * 0.05 = 0.20, negated. Run B's 1.0 kWh would give -0.05.
    assert by_label["degradation"] == pytest.approx(-0.20)


def test_fixture_4_closure_with_zero_degradation() -> None:
    """The same scenario with appendix A's default rate of 0.0 — the identity is unchanged."""
    a, b, c, curves, index, pcfg = _hand_built_scenario(degradation=0.0)
    _assert_fixture_4(a, b, c, curves, index, pcfg, "hand-built, degradation off")


def test_fixture_4_closure_with_gaps_present() -> None:
    """Gaps contribute zero to every line, and the closure still holds.

    Hours 2 and 4 are gapped in ALL THREE runs, which is what §6.9 produces: `simulate_baseline`
    propagates the same gap mask as the battery runs, so A and C exclude the same intervals and
    `saved_kwh` compares like with like. A waterfall line that summed a NaN product without
    excluding it would produce NaN and fail the closure outright.
    """
    a, b, c, curves, index, pcfg = _hand_built_scenario(degradation=0.02)
    gap = np.array([False, False, True, False, True, False])
    for f in (a, b, c):
        f.gap = gap.copy()
        for arr in (f.imp, f.exp, f.withdrawn):
            arr[gap] = np.nan

    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    assert all(np.isfinite(line.eur) for line in lines)
    _assert_fixture_4(a, b, c, curves, index, pcfg, "hand-built with gaps")


def test_fixture_4_closure_on_a_no_pv_arbitrage_run() -> None:
    """The closure over a REAL `run_all()` output — no PV, P2/D2 grid-arbitrage BANDS.

    Pinned against actual dispatch rather than hand-made arrays, so an import-side flow the hand
    fixtures happen not to produce (a clamped charge, a discharge the policy declined to make)
    cannot slip past. The square-wave price alternates 0.02 / 0.40 daily over five days, which
    drives a full charge and discharge cycle each day and a nonzero standby line.

    **This run has no export at all** — `_arbitrage_cfg` sets `allow_grid_export=False` and there
    is no PV, so `A.exp` and `C.exp` are identically zero and four of the eight lines are 0.00.
    "Arbitrage" here names the charge/discharge BAND policy, not arbitrage export. The export half
    of the waterfall is covered by `test_fixture_4_closure_on_a_real_pv_run` and by the hand
    fixtures, not by this test.
    """
    n = 24 * 5
    hours = np.arange(n) % 24
    spot = np.where(hours < 12, 0.02, 0.40)
    frame = _frame(np.full(n, 1.0), pv=np.zeros(n), spot=spot)
    cfg = _arbitrage_cfg(
        simulate_cost=True, pricing=PricingConfig(degradation_eur_per_kwh=0.03)
    )
    runs = run_all(frame, cfg)

    pcfg = cfg.pricing
    curves = price_curves(pcfg, frame.spot)
    total = _assert_fixture_4(
        runs.a, runs.b, runs.c, curves, frame.index, pcfg, "run_all, no PV arbitrage"
    )
    assert np.isfinite(total)


def test_fixture_4_closure_on_a_real_pv_run() -> None:
    """The closure over a REAL `run_all()` output with PV, surplus charging and export.

    Ten days of a PV profile against a flat load, P1/D1. Both the baseline and the battery scenario
    export, so the two export lines carry real numbers and the top-up is nonzero.

    Note the export here is PV SURPLUS, which `allow_grid_export` does not gate — that flag governs
    battery-to-grid discharge only (see `simulate.py`), and this config leaves it at its default
    False. So the coverage is real, but it is not "export allowed" in the policy sense.
    """
    n = 24 * 10
    hours = np.arange(n) % 24
    pv = np.where((hours >= 8) & (hours < 17), 3.0, 0.0)
    load = np.full(n, 0.8)
    spot = 0.05 + 0.15 * np.sin(np.arange(n) * 2 * np.pi / 24.0)
    frame = _frame(load, pv=pv, spot=spot)
    cfg = _cfg(
        has_pv=True,
        simulate_cost=True,
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=0.0,
        charge_policy=ChargePolicy.P1,
        discharge_policy=DischargePolicy.D1,
        standby_w=30.0,
        pricing=PricingConfig(degradation_eur_per_kwh=0.04),
    )
    runs = run_all(frame, cfg)
    pcfg = cfg.pricing
    curves = price_curves(pcfg, frame.spot)
    _assert_fixture_4(runs.a, runs.b, runs.c, curves, frame.index, pcfg, "run_all, PV")


def test_broken_waterfall_fails_the_closure() -> None:
    """The closure has teeth: a single perturbed line breaks it by more than CLOSURE_TOL.

    Written because fixture 3's conservation identity closes by construction on the unconstrained
    path (see `tests/test_metrics.py`'s opening note), so "the identity holds" is not on its own
    evidence that an identity is checking anything. Here it is: flip the sign of
    `added_grid_import_charging`, the line §6.10 writes with a leading minus, and the sum moves by
    twice that line and the closure fails.
    """
    a, b, c, curves, index, pcfg = _hand_built_scenario(degradation=0.05)
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    by_label = {line.label: line.eur for line in lines}
    broken = sum(
        -v if label == "added_grid_import_charging" else v for label, v in by_label.items()
    )
    cost_a = compute_costs(a, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg)
    cost_c = compute_costs(c, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg)
    target = cost_a.eur - cost_c.eur - pcfg.degradation_eur_per_kwh * float(np.nansum(c.withdrawn))
    assert abs(broken - target) > CLOSURE_TOL


# ── Fixture 14: the floor binds, and only the top-up line moves ──────────────────────────────


def _fixture_14_scenario():
    """A month whose export earns a net negative unclamped amount in the BASELINE but not with a
    battery — the shape fixture 14 asks for, and the only shape in which the top-up line is
    nonzero.

    31 hourly intervals inside one UTC calendar month, at a spot of -0.5205 throughout, so bare is
    -0.50 and the unclamped compensation is -0.25 EUR/kWh in every interval. The baseline exports
    10 kWh, earning `10 * -0.25 = -2.50`; under MONTHLY the floor binds and tops the baseline up by
    2.50. The battery scenario stores that energy instead and exports nothing at all, so its
    period aggregate is 0 and its top-up is 0.

    Returns `(a, b, c, curves, index, pcfg)`.
    """
    n = 31
    pcfg = PricingConfig(degradation_eur_per_kwh=0.05, feedin_floor_mode=FeedinFloorMode.MONTHLY)
    curves = price_curves(pcfg, np.full(n, -0.5205))
    index = _hours("2026-05-02T00:00:00", n)

    imp_a = np.zeros(n)
    exp_a = np.zeros(n)
    exp_a[:10] = 1.0  # 10 kWh exported at a negative compensation
    a = _flows(imp_a, exp_a)

    # The battery absorbs all of it: no export at all, and it discharges 8 kWh back to the house
    # later, which reduces nothing in the baseline (the baseline imported nothing here) so the
    # import lines stay zero and the scenario isolates the export side.
    b = _flows(np.zeros(n), np.zeros(n), withdrawn=np.full(n, 8.0 / n))
    c = _flows(np.full(n, 0.03), np.zeros(n), withdrawn=np.full(n, 8.0 / n))
    return a, b, c, curves, index, pcfg


def test_fixture_14_binding_month_earns_exactly_zero_compensation() -> None:
    """§6.14 fixture 14, first half: under MONTHLY the binding month's compensation revenue is 0.

    The baseline's export earns `-2.50` unclamped over the month, and the top-up is exactly
    `+2.50`, so the compensation component of the bill nets to exactly zero. What the household
    still pays is the terugleverkosten — `10 kWh * 0.04 = 0.40` — which the statutory floor does
    not cover (§6.5: the floor is assessed on the compensation, not on the net).
    """
    a, _b, _c, curves, index, pcfg = _fixture_14_scenario()
    cost_a = compute_costs(
        a, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg
    )
    assert cost_a.topup_eur == pytest.approx(2.50)
    # per-interval bill = -(export * net) = -(10 * -0.29) = +2.90; minus the 2.50 top-up = 0.40.
    assert cost_a.per_interval_eur == pytest.approx(2.90)
    assert cost_a.eur == pytest.approx(0.40)


def test_fixture_14_shortfall_appears_only_in_the_topup_line() -> None:
    """§6.14 fixture 14, second half: the shortfall lands in `feedin_floor_topup` and nowhere else.

    The baseline received a 2.50 top-up and the battery scenario receives none, so the line is
    `topup(C) - topup(A) = -2.50`: the battery COST the household the top-up it would otherwise
    have been credited. That is the correct sign — the top-up existed only because the baseline was
    exporting at a negative compensation, and the battery stopped it doing so, which is also why
    the export lines show a large offsetting gain.

    The assertion with content is the second one: no other line contains any part of 2.50. The
    export lines are checked against their own hand arithmetic, so a top-up leaking into
    `lost_feedin_compensation` — the fold §6.5 and §6.10 both forbid — would show up as those
    numbers being wrong rather than merely as the closure moving.
    """
    a, b, c, curves, index, pcfg = _fixture_14_scenario()
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    by_label = {line.label: line.eur for line in lines}

    assert by_label["feedin_floor_topup"] == pytest.approx(-2.50)
    # d_exp = B.exp - A.exp = -1.0 in the first ten intervals, 0 elsewhere. So:
    #   avoided_terugleverkosten  = 10 * 0.04  = +0.40
    #   lost_feedin_compensation  = -(10 * -0.25) = +2.50  (positive: the "lost" compensation was
    #                               itself negative, so not receiving it is a gain)
    #   arbitrage_export_revenue  = 0 (the battery added no export)
    assert by_label["avoided_terugleverkosten"] == pytest.approx(0.40)
    assert by_label["lost_feedin_compensation"] == pytest.approx(2.50)
    assert by_label["arbitrage_export_revenue"] == pytest.approx(0.0)
    # No import moved in either direction between A and B.
    assert by_label["avoided_grid_import"] == pytest.approx(0.0)
    assert by_label["added_grid_import_charging"] == pytest.approx(0.0)


def test_fixture_14_closure_holds_with_a_nonzero_topup() -> None:
    """§6.14 fixture 14, third of four: fixture 4's closure still holds to CLOSURE_TOL.

    This is the case the closure is really for. With the top-up zero on both sides — which is
    almost every window — the seventh line is 0.0 and the identity cannot tell a correct top-up
    treatment from no treatment at all. Here it is -2.50 against a total of the same order, so a
    fold into `lost_feedin_compensation`, a double count, or the standby line being taken on the
    post-top-up bills would each move the sum by euros rather than by rounding.
    """
    a, b, c, curves, index, pcfg = _fixture_14_scenario()
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    by_label = {line.label: line.eur for line in lines}
    assert abs(by_label["feedin_floor_topup"]) > 1.0  # the fixture's point: it is not zero
    _assert_fixture_4(a, b, c, curves, index, pcfg, "fixture 14, floor binding")


def test_fixture_14_closure_holds_when_only_the_battery_scenario_binds() -> None:
    """The mirror case: the top-up line is POSITIVE when the battery is the one that binds.

    Same month, but the baseline exports nothing and the battery scenario exports 10 kWh at the
    negative compensation (an arbitrage export the policy chose to make). The top-up now accrues
    to C, so the line is `+2.50`, and the closure must hold with the opposite sign — which a
    treatment that had accidentally hard-coded `topup(A) - topup(C)` would fail.
    """
    n = 31
    pcfg = PricingConfig(degradation_eur_per_kwh=0.05)
    curves = price_curves(pcfg, np.full(n, -0.5205))
    index = _hours("2026-05-02T00:00:00", n)

    exp_c = np.zeros(n)
    exp_c[:10] = 1.0
    a = _flows(np.zeros(n), np.zeros(n))
    b = _flows(np.zeros(n), exp_c, withdrawn=np.full(n, 10.0 / n))
    c = _flows(np.full(n, 0.03), exp_c, withdrawn=np.full(n, 10.0 / n))

    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    by_label = {line.label: line.eur for line in lines}
    assert by_label["feedin_floor_topup"] == pytest.approx(2.50)
    _assert_fixture_4(a, b, c, curves, index, pcfg, "fixture 14 mirrored")


def test_fixture_14_closure_holds_when_standby_itself_moves_the_topup() -> None:
    """The case that pins which bills the `standby_consumption` line is taken on.

    §6.10 writes that line as `cost(B) - cost(C)`, which is ambiguous: `cost` there could be the
    full bill or the pre-top-up one, and the two differ by exactly `topup(C) - topup(B)`. Almost
    every window has both top-ups at zero, so the ambiguity is invisible — including in the other
    fixture-14 tests above, where the floor binds in A but not in B or C.

    This scenario makes it visible. Run B exports 10 kWh at a negative compensation, earning
    `-2.50` over the month and binding the floor; run C is B plus a standby draw large enough that
    the same export is reduced to 8 kWh, earning `-2.00` and binding at a different level. The two
    top-ups now differ by 0.50, and the full-bill reading of the standby line misses the closure by
    exactly that. The pre-top-up reading closes, because then each top-up appears once: the
    per-interval lines tile `per(A) - per(C)` and the seventh line carries the whole floor effect.
    """
    n = 31
    pcfg = PricingConfig(degradation_eur_per_kwh=0.05)
    curves = price_curves(pcfg, np.full(n, -0.5205))
    index = _hours("2026-05-02T00:00:00", n)

    exp_b = np.zeros(n)
    exp_b[:10] = 1.0
    exp_c = np.zeros(n)
    exp_c[:8] = 1.0
    a = _flows(np.zeros(n), np.zeros(n))
    b = _flows(np.zeros(n), exp_b, withdrawn=np.full(n, 10.0 / n))
    c = _flows(np.zeros(n), exp_c, withdrawn=np.full(n, 10.0 / n))

    cost_b = compute_costs(b, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg)
    cost_c = compute_costs(c, curves.p_import, curves.p_export_net, curves.compensation, index, pcfg)
    assert cost_b.topup_eur == pytest.approx(2.50)
    assert cost_c.topup_eur == pytest.approx(2.00)  # the two genuinely differ

    _assert_fixture_4(a, b, c, curves, index, pcfg, "fixture 14, standby moves the top-up")


# ── The shape of the waterfall ───────────────────────────────────────────────────────────────


def test_waterfall_lines_are_in_the_spec_order_with_the_spec_labels() -> None:
    """§6.10's eight labels, spelled and ordered exactly as §6.10 writes them.

    The order is load-bearing: the view renders the lines as a left-to-right bar chart in which
    each term is read as following on from the previous one, and the labels are translation keys.
    """
    a, b, c, curves, index, pcfg = _hand_built_scenario()
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    assert [line.label for line in lines] == [
        "avoided_grid_import",
        "added_grid_import_charging",
        "avoided_terugleverkosten",
        "lost_feedin_compensation",
        "arbitrage_export_revenue",
        "standby_consumption",
        "feedin_floor_topup",
        "degradation",
    ]
    assert list(WATERFALL_LINES) == [line.label for line in lines]


def test_zero_degradation_reports_a_zero_line_rather_than_dropping_it() -> None:
    """Appendix A's default rate is 0.0 ("Disabled"), and the line is still present, at 0.0.

    §4.5 shows that line carrying `"enabled": false`. That flag is NOT set here: whether
    degradation is enabled is a fact about the CONFIG (`degradation_eur_per_kwh == 0`), while this
    module reports the computed euro figure — and a run can produce a 0.00 line with degradation
    perfectly enabled, simply by never discharging. Collapsing the two here would lose that
    distinction; the view has the config in hand and renders the flag.

    §2.3a's rule for the display is the same shape: zero lines are dropped from the CHART, never
    from `cost.waterfall` in the result JSON, "which must continue to close against
    `cost(A) - cost(C)`".
    """
    a, b, c, curves, index, pcfg = _hand_built_scenario(degradation=0.0)
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    degradation = [line for line in lines if line.label == "degradation"]
    assert len(degradation) == 1
    assert degradation[0].eur == 0.0


def test_standby_line_is_negative_when_standby_costs_money() -> None:
    """§6.9's exact run difference, with the sign the waterfall needs.

    The waterfall's lines are SAVINGS, so a standby draw that cost the household money is a
    negative line. In `_hand_built_scenario` run C draws 0.03 kWh/h more from the grid than run B
    in four of the six hours and exports 0.03 less in two, all at positive prices.
    """
    a, b, c, curves, index, pcfg = _hand_built_scenario()
    lines = waterfall(
        a, b, c, curves.p_import, curves.compensation,
        pcfg.tlk_eur_per_kwh, pcfg, index, curves.p_export_net,
    )
    standby = next(line.eur for line in lines if line.label == "standby_consumption")
    assert standby < 0.0
