"""Hand-computed fixtures for the §6.5 price curves (app/domain/pricing.py).

**Every expected number here is derived on paper from the spec and appendix A's defaults, never
read off the implementation.** The arithmetic is small enough that this is cheap, and it is the
only thing standing between a sign error and a confident wrong euro figure: unlike the energy
path, there is no conservation identity that a mispriced interval would violate.

What each group pins:

  * `test_bare_supply_*`, `test_import_price_*`, `test_feedin_*`, `test_export_price_net_*`
        the three price functions against hand arithmetic, including the shipped appendix-A
        defaults, and the §6.5 rule that nothing is clamped.
  * `test_negative_spot_*`           §6.10's "one of the more important things this tool can
        show a user" — a negative spot price makes the net export price negative, so exporting
        costs money.
  * `test_fixture_13_*`              validation harness fixture 13: MONTHLY revenue ≤
        PER_INTERVAL revenue, strict when an interval has negative unclamped compensation
        carrying export, equal when none does.
  * `test_floor_binds_*`             a month whose export earns a net negative amount yields a
        nonzero top-up; an ordinary month yields exactly zero.
  * `test_partial_periods_*`, `test_shorter_than_period_*`   the two §4.5 diagnostics.
  * `test_*_not_implemented`         FIXED, VARIABLE and TIERED raise rather than returning a
        number that would look like an answer.
  * `test_nan_*`                     an uncovered interval stays NaN through the price arrays and
        is excluded from the floor's period sums, rather than becoming a real-looking euro
        figure.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.pricing import (
    FeedinFloorResult,
    bare_supply_price,
    export_price_net,
    feedin_compensation,
    feedin_floor_topup,
    import_price,
    price_curves,
)
from app.domain.simconfig import Contract, FeedinFloorMode, PricingConfig, TlkMode


def _hours(start: str, n: int) -> np.ndarray:
    """`n` hourly interval STARTS from `start`, in the frame's UTC-naive datetime64[s] form."""
    return (np.datetime64(start, "s") + np.arange(n) * np.timedelta64(3600, "s")).astype(
        "datetime64[s]"
    )


# ── The three price functions ─────────────────────────────────────────────────────────────────
#
# Appendix A's shipped defaults, used throughout below:
#   supplier_markup 0.0205, energy_tax_excl_vat 0.09161, vat_rate 0.21,
#   feedin_alpha 0.50, feedin_beta 0.0000, tlk_eur_per_kwh 0.0400.


def test_bare_supply_price_is_spot_plus_markup_on_the_defaults() -> None:
    """DYNAMIC: bare = spot + 0.0205 (appendix A's inkoopvergoeding).

    spot 0.1000 -> 0.1205; spot 0.0000 -> 0.0205; spot -0.0500 -> -0.0295.
    """
    cfg = PricingConfig()
    bare = bare_supply_price(cfg, np.array([0.10, 0.0, -0.05]))
    assert bare == pytest.approx([0.1205, 0.0205, -0.0295])


def test_import_price_applies_tax_then_vat_in_that_order() -> None:
    """§6.5: `(bare + energy_tax_excl_vat) * (1 + vat_rate)` — VAT is charged on the tax too.

    bare 0.1205 -> (0.1205 + 0.09161) * 1.21 = 0.21211 * 1.21 = 0.2566531
    bare 0.0000 -> 0.09161 * 1.21                            = 0.1108481
    """
    cfg = PricingConfig()
    p = import_price(cfg, np.array([0.1205, 0.0]))
    assert p == pytest.approx([0.2566531, 0.1108481])


def test_import_price_taxes_a_negative_bare_price_the_same_way() -> None:
    """No special case for a negative bare price; the all-in price simply falls.

    bare -0.0295 -> (-0.0295 + 0.09161) * 1.21 = 0.06211 * 1.21 = 0.0751531
    """
    cfg = PricingConfig()
    assert import_price(cfg, np.array([-0.0295])) == pytest.approx([0.0751531])


def test_feedin_compensation_is_the_legal_minimum_preset_on_the_defaults() -> None:
    """α = 0.50, β = 0.0000 — §6.5's "Legal minimum", so compensation is half the bare price.

    bare 0.1205 -> 0.06025; bare -0.0295 -> -0.01475 (NOT clamped to zero).
    """
    cfg = PricingConfig()
    c = feedin_compensation(cfg, np.array([0.1205, -0.0295]))
    assert c == pytest.approx([0.06025, -0.01475])


def test_feedin_compensation_honours_the_spot_minus_fee_preset() -> None:
    """§6.5's "Spot minus fee" preset, α = 1.00 / β = −0.0200: compensation = bare − 2 ct.

    bare 0.1205 -> 0.1005; bare 0.0150 -> -0.0050, negative from β alone even at a positive bare
    price.
    """
    cfg = PricingConfig(feedin_alpha=1.0, feedin_beta=-0.02)
    c = feedin_compensation(cfg, np.array([0.1205, 0.015]))
    assert c == pytest.approx([0.1005, -0.005])


def test_export_price_net_subtracts_the_flat_terugleverkosten() -> None:
    """net = compensation − 0.0400 on the defaults.

    bare 0.1205 -> 0.06025 − 0.04 =  0.02025
    bare 0.0600 -> 0.03000 − 0.04 = -0.01000   negative at an ordinary positive spot price
    """
    cfg = PricingConfig()
    net = export_price_net(cfg, np.array([0.1205, 0.06]))
    assert net == pytest.approx([0.02025, -0.01])


def test_export_price_net_is_never_clamped() -> None:
    """§6.5: both the compensation and the net after charges may be negative.

    A deeply negative bare price gives a deeply negative net; nothing floors it at 0.
    bare -0.5000 -> compensation -0.25 -> net -0.29
    """
    cfg = PricingConfig()
    assert export_price_net(cfg, np.array([-0.5])) == pytest.approx([-0.29])


def test_negative_spot_produces_a_negative_net_export_price() -> None:
    """§6.10: exporting during a negative-price hour increases the bill.

    spot −0.08 -> bare −0.0595 -> compensation −0.02975 -> net −0.06975. The import price stays
    positive at 0.0388531, because energy tax and VAT are levied on the import side regardless.
    """
    cfg = PricingConfig()
    curves = price_curves(cfg, np.array([-0.08]))
    assert curves.p_export_net[0] < 0.0
    assert curves.p_export_net == pytest.approx([-0.06975])
    assert curves.compensation == pytest.approx([-0.02975])
    assert curves.p_import[0] > 0.0


def test_price_curves_bundles_arrays_consistent_with_the_functions() -> None:
    """`price_curves` is the individual functions composed, not a second implementation.

    Also pins that the flat terugleverkosten rate is recoverable as compensation − net, which is
    what lets §6.10's waterfall take a `tlk` argument without a fifth field.
    """
    cfg = PricingConfig()
    spot = np.array([0.10, -0.02, 0.25])
    curves = price_curves(cfg, spot)
    bare = bare_supply_price(cfg, spot)
    assert curves.bare == pytest.approx(bare)
    assert curves.p_import == pytest.approx(import_price(cfg, bare))
    assert curves.compensation == pytest.approx(feedin_compensation(cfg, bare))
    assert curves.p_export_net == pytest.approx(export_price_net(cfg, bare))
    assert curves.compensation - curves.p_export_net == pytest.approx(
        np.full(3, cfg.tlk_eur_per_kwh)
    )


# ── The unbuilt branches refuse rather than guess ─────────────────────────────────────────────


def test_fixed_contract_is_not_implemented() -> None:
    """FIXED needs §6.4's `tariff_zone` (follow-up H1). It must not fall back to the spot branch."""
    cfg = PricingConfig(contract=Contract.FIXED)
    with pytest.raises(NotImplementedError, match="FIXED"):
        bare_supply_price(cfg, np.array([0.1]))


def test_variable_contract_is_not_implemented() -> None:
    """VARIABLE additionally needs a dated `rate_schedule` that PricingConfig does not carry (H6)."""
    cfg = PricingConfig(contract=Contract.VARIABLE)
    with pytest.raises(NotImplementedError, match="VARIABLE"):
        bare_supply_price(cfg, np.array([0.1]))


def test_tiered_terugleverkosten_is_not_implemented() -> None:
    """TIERED resolves its rate from ANNUALISED export (follow-up H3); FLAT is the only rate built."""
    cfg = PricingConfig(tlk_mode=TlkMode.TIERED)
    with pytest.raises(NotImplementedError, match="[Tt]iered"):
        export_price_net(cfg, np.array([0.1]))


def test_price_curves_refuses_a_non_dynamic_contract_up_front() -> None:
    """The refusal happens where the curves are built, not at the first euro figure downstream."""
    with pytest.raises(NotImplementedError):
        price_curves(PricingConfig(contract=Contract.FIXED), np.array([0.1]))


# ── Fixture 13: the floor ordering ────────────────────────────────────────────────────────────
#
# specs/16-validation-harness.md fixture 13: over identical data with identical (α, β), feed-in
# compensation revenue under MONTHLY is <= the revenue under PER_INTERVAL, with equality iff no
# interval has negative unclamped compensation.
#
# "Revenue" here is what §6.10 credits the household for exporting, i.e. the compensation side of
# the bill plus the floor top-up:
#
#     revenue = Σ export(t)·c(t) + topup
#
# Under PER_INTERVAL that collapses to Σ export·max(0, c) — the clamp. Under MONTHLY it collapses
# to Σ over months of max(0, Σ export·c) — the aggregate. Asserting on revenue rather than on the
# top-up is deliberate: the top-up ordering runs the OTHER way (per-interval tops up more), and
# §6.5's claim is about the revenue.


def _compensation_revenue(cfg: PricingConfig, export: np.ndarray, spot: np.ndarray, index) -> float:
    """§6.10's compensation-side revenue: Σ export·c + the floor top-up, under `cfg`'s mode."""
    comp = feedin_compensation(cfg, bare_supply_price(cfg, spot))
    per_interval = float(np.nansum(np.where(np.isnan(export) | np.isnan(comp), 0.0, export * comp)))
    return per_interval + feedin_floor_topup(cfg, export, comp, index).topup_eur


def test_fixture_13_monthly_revenue_is_strictly_below_per_interval_with_a_negative_hour() -> None:
    """Fixture 13, strict case: one negative-price interval carrying nonzero export.

    Four hours in one month, α = 1.00 / β = 0.0000 (§6.5's "Spot minus fee" without the fee, so
    c = bare = spot + 0.0205) and 1 kWh exported in each:

        spot   0.10   0.20  -0.30   0.10
        c      0.1205 0.2205 -0.2795 0.1205

      PER_INTERVAL revenue = 0.1205 + 0.2205 + 0 + 0.1205 = 0.4615
      MONTHLY      revenue = max(0, 0.1205+0.2205-0.2795+0.1205) = 0.1820

    The €0.2795 the negative hour costs is absorbed by the month under the law and discarded by
    the clamp — which is exactly §6.5's "the first is always greater than or equal to the second".
    """
    index = _hours("2026-03-05T00:00:00", 4)
    export = np.array([1.0, 1.0, 1.0, 1.0])
    spot = np.array([0.10, 0.20, -0.30, 0.10])
    monthly = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    per_interval = PricingConfig(
        feedin_alpha=1.0, feedin_beta=0.0, feedin_floor_mode=FeedinFloorMode.PER_INTERVAL
    )

    rev_monthly = _compensation_revenue(monthly, export, spot, index)
    rev_clamped = _compensation_revenue(per_interval, export, spot, index)

    assert rev_clamped == pytest.approx(0.4615)
    assert rev_monthly == pytest.approx(0.1820)
    assert rev_monthly < rev_clamped


def test_fixture_13_the_two_modes_agree_when_no_interval_is_negative() -> None:
    """Fixture 13's equality half: with every c(t) ≥ 0, clamping discards nothing.

    Same shape as above with the negative hour replaced by a positive one.
    """
    index = _hours("2026-03-05T00:00:00", 4)
    export = np.array([1.0, 1.0, 1.0, 1.0])
    spot = np.array([0.10, 0.20, 0.05, 0.10])
    monthly = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    per_interval = PricingConfig(
        feedin_alpha=1.0, feedin_beta=0.0, feedin_floor_mode=FeedinFloorMode.PER_INTERVAL
    )

    rev_monthly = _compensation_revenue(monthly, export, spot, index)
    rev_clamped = _compensation_revenue(per_interval, export, spot, index)
    assert rev_monthly == pytest.approx(rev_clamped)
    assert rev_monthly == pytest.approx(0.1205 + 0.2205 + 0.0705 + 0.1205)


def test_fixture_13_a_negative_hour_with_no_export_does_not_break_equality() -> None:
    """The strictness condition is a negative c(t) CARRYING export, not merely a negative c(t)."""
    index = _hours("2026-03-05T00:00:00", 3)
    export = np.array([1.0, 0.0, 1.0])
    spot = np.array([0.10, -0.30, 0.10])
    monthly = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    per_interval = PricingConfig(
        feedin_alpha=1.0, feedin_beta=0.0, feedin_floor_mode=FeedinFloorMode.PER_INTERVAL
    )
    assert _compensation_revenue(monthly, export, spot, index) == pytest.approx(
        _compensation_revenue(per_interval, export, spot, index)
    )


def test_fixture_13_ordering_holds_across_a_multi_month_window() -> None:
    """The ordering is per period, so it survives summing over months.

    Two months, one negative hour in each; the aggregate offsets within a month but never across
    months, which is what makes MONTHLY stricter than a whole-window aggregate would be.
    """
    index = np.concatenate([_hours("2026-01-10T00:00:00", 3), _hours("2026-02-10T00:00:00", 3)])
    export = np.ones(6)
    spot = np.array([0.10, -0.30, 0.10, 0.20, -0.05, 0.20])
    monthly = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    per_interval = PricingConfig(
        feedin_alpha=1.0, feedin_beta=0.0, feedin_floor_mode=FeedinFloorMode.PER_INTERVAL
    )
    assert _compensation_revenue(monthly, export, spot, index) < _compensation_revenue(
        per_interval, export, spot, index
    )


# ── When the floor actually binds ─────────────────────────────────────────────────────────────


def test_an_ordinary_month_yields_exactly_zero_topup() -> None:
    """The floor binds only on a period whose export earned a net NEGATIVE amount overall.

    Three hours, spot 0.10 / −0.30 / 0.10 with α = 1: the month earns
    0.1205 − 0.2795 + 0.1205 = −0.0385 per exported kWh... which IS negative, so use export
    weights that keep the month positive: 1 / 0.1 / 1 kWh gives 0.1205 − 0.02795 + 0.1205 =
    0.21305 > 0 and the top-up is exactly zero, not merely small.
    """
    cfg = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    index = _hours("2026-03-05T00:00:00", 3)
    export = np.array([1.0, 0.1, 1.0])
    comp = feedin_compensation(cfg, bare_supply_price(cfg, np.array([0.10, -0.30, 0.10])))
    result = feedin_floor_topup(cfg, export, comp, index)
    assert result.topup_eur == 0.0


def test_a_net_negative_month_yields_a_topup_equal_to_the_shortfall() -> None:
    """A month whose export earns a net negative amount is topped up to exactly zero.

    Same three hours, 1 kWh exported in each:
        earned = 0.1205 − 0.2795 + 0.1205 = −0.0385  ->  topup = 0.0385
    """
    cfg = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    index = _hours("2026-03-05T00:00:00", 3)
    export = np.array([1.0, 1.0, 1.0])
    comp = feedin_compensation(cfg, bare_supply_price(cfg, np.array([0.10, -0.30, 0.10])))
    result = feedin_floor_topup(cfg, export, comp, index)
    assert result.topup_eur == pytest.approx(0.0385)


def test_the_topup_is_assessed_per_month_not_across_the_window() -> None:
    """A negative January is topped up even though the window as a whole earned money.

    January: 1 kWh at spot −0.30 -> earned −0.2795, topped up 0.2795.
    February: 1 kWh at spot 0.50 -> earned 0.5205, no top-up.
    A whole-window aggregate would find +0.2410 and credit nothing.
    """
    cfg = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    index = np.concatenate([_hours("2026-01-10T00:00:00", 1), _hours("2026-02-10T00:00:00", 1)])
    comp = feedin_compensation(cfg, bare_supply_price(cfg, np.array([-0.30, 0.50])))
    result = feedin_floor_topup(cfg, np.array([1.0, 1.0]), comp, index)
    assert result.topup_eur == pytest.approx(0.2795)


def test_per_interval_mode_tops_up_every_negative_interval() -> None:
    """PER_INTERVAL: Σ export·max(0, −c), which is ≥ the monthly top-up on the same data.

    The month above earns −0.0385 net and is topped up by that much under MONTHLY; under
    PER_INTERVAL the single negative hour alone is topped up by 0.2795.
    """
    cfg = PricingConfig(
        feedin_alpha=1.0, feedin_beta=0.0, feedin_floor_mode=FeedinFloorMode.PER_INTERVAL
    )
    index = _hours("2026-03-05T00:00:00", 3)
    comp = feedin_compensation(cfg, bare_supply_price(cfg, np.array([0.10, -0.30, 0.10])))
    result = feedin_floor_topup(cfg, np.array([1.0, 1.0, 1.0]), comp, index)
    assert result.topup_eur == pytest.approx(0.2795)


def test_per_interval_mode_reports_no_period_diagnostics() -> None:
    """No period is assessed under PER_INTERVAL, so both §4.5 diagnostics are inert."""
    cfg = PricingConfig(feedin_floor_mode=FeedinFloorMode.PER_INTERVAL)
    index = _hours("2026-03-05T12:00:00", 3)
    comp = np.array([0.05, 0.05, 0.05])
    result = feedin_floor_topup(cfg, np.ones(3), comp, index)
    assert result == FeedinFloorResult(
        topup_eur=0.0, partial_periods=0, shorter_than_period=False
    )


# ── The two §4.5 diagnostics ──────────────────────────────────────────────────────────────────


def test_partial_periods_counts_both_window_edges() -> None:
    """§7.4: a window starting and ending mid-month leaves a partial period at each end.

    15 Jan 12:00 through 15 Mar 12:00, hourly. February is whole; January and March are not.
    """
    cfg = PricingConfig()
    n = 24 * 59  # 15 Jan 12:00 + 59 days = 15 Mar 12:00
    index = _hours("2026-01-15T12:00:00", n)
    comp = np.full(n, 0.05)
    result = feedin_floor_topup(cfg, np.ones(n), comp, index)
    assert result.partial_periods == 2
    assert result.shorter_than_period is False


def test_a_month_aligned_window_has_no_partial_periods() -> None:
    """A window covering whole calendar months exactly leaves nothing partial.

    1 Jan 00:00 through 1 Mar 00:00, hourly interval starts: 31 + 28 = 59 days in 2026.
    """
    cfg = PricingConfig()
    n = 24 * 59
    index = _hours("2026-01-01T00:00:00", n)
    result = feedin_floor_topup(cfg, np.ones(n), np.full(n, 0.05), index)
    assert result.partial_periods == 0
    assert result.shorter_than_period is False


def test_a_window_partial_at_only_one_edge_counts_one() -> None:
    """Starting on the 1st but ending mid-month leaves exactly one partial period."""
    cfg = PricingConfig()
    n = 24 * 40  # 1 Jan -> 10 Feb
    index = _hours("2026-01-01T00:00:00", n)
    result = feedin_floor_topup(cfg, np.ones(n), np.full(n, 0.05), index)
    assert result.partial_periods == 1
    assert result.shorter_than_period is False


def test_a_sub_month_window_sets_the_shorter_than_period_flag() -> None:
    """§7.4: a window shorter than one assessment period is assessed whole — a WEAKER constraint.

    Ten days inside March. The flag is how the result carries the fact; the single bucket is
    itself partial, so `partial_periods` is 1.
    """
    cfg = PricingConfig()
    n = 24 * 10
    index = _hours("2026-03-05T00:00:00", n)
    result = feedin_floor_topup(cfg, np.ones(n), np.full(n, 0.05), index)
    assert result.shorter_than_period is True
    assert result.partial_periods == 1


def test_a_short_window_straddling_a_month_boundary_is_still_flagged_short() -> None:
    """§7.4's flag is about the window's DURATION, not about how many buckets it lands in.

    Three days over 30 Jan → 2 Feb. This is the case a bucket-count reading gets backwards: the
    window lands in two buckets and is therefore assessed as two sub-month FRAGMENTS, which is a
    weaker constraint than the same three days inside one month — yet a `keys.size == 1` test
    flags the latter and not the former. Any run started mid-month and shorter than a month hits
    it, so this is not an exotic window.
    """
    cfg = PricingConfig()
    n = 24 * 3
    index = _hours("2026-01-30T00:00:00", n)
    result = feedin_floor_topup(cfg, np.ones(n), np.full(n, 0.05), index)
    assert result.shorter_than_period is True
    assert result.partial_periods == 2


def test_a_multi_month_window_is_not_flagged_short_even_with_partial_edges() -> None:
    """The mirror: two months from mid-January is longer than one period, partial edges and all.

    Pins that the fix to the test above did not simply turn the flag on whenever an edge is
    partial — `partial_periods` and `shorter_than_period` answer different questions.
    """
    cfg = PricingConfig()
    n = 24 * 59
    index = _hours("2026-01-15T00:00:00", n)
    result = feedin_floor_topup(cfg, np.ones(n), np.full(n, 0.05), index)
    assert result.shorter_than_period is False
    assert result.partial_periods == 2


def test_a_window_covering_exactly_one_whole_month_is_not_flagged_short() -> None:
    """A whole calendar month is one assessment period, not a short window."""
    cfg = PricingConfig()
    n = 24 * 31
    index = _hours("2026-03-01T00:00:00", n)
    result = feedin_floor_topup(cfg, np.ones(n), np.full(n, 0.05), index)
    assert result.shorter_than_period is False
    assert result.partial_periods == 0


def test_an_empty_window_assesses_nothing() -> None:
    """No intervals, no periods: zero top-up and neither diagnostic asserted."""
    cfg = PricingConfig()
    result = feedin_floor_topup(
        cfg, np.array([]), np.array([]), np.array([], dtype="datetime64[s]")
    )
    assert result == FeedinFloorResult(
        topup_eur=0.0, partial_periods=0, shorter_than_period=False
    )


# ── NaN: absence must not become a euro figure ────────────────────────────────────────────────


def test_nan_spot_propagates_through_every_price_array() -> None:
    """§4.4: an uncovered interval is NaN, never 0 — and it stays NaN through the prices.

    A zero would be a real price here (§4.4's own argument for NaN in `spot`), so silently
    substituting one would put a plausible 11.08 ct/kWh import price on an interval no price
    covers.
    """
    cfg = PricingConfig()
    curves = price_curves(cfg, np.array([0.10, np.nan, 0.20]))
    for array in (curves.bare, curves.p_import, curves.compensation, curves.p_export_net):
        assert np.isnan(array[1])
        assert not np.isnan(array[0]) and not np.isnan(array[2])


def test_the_floor_excludes_uncovered_intervals_rather_than_returning_nan() -> None:
    """A NaN compensation contributes nothing to its period rather than poisoning the scalar.

    Same shape as the binding-month fixture with the middle hour's price missing: the month's
    aggregate is the two covered hours, 0.1205 + 0.1205 > 0, so no top-up — and crucially a
    finite number, not NaN.
    """
    cfg = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    index = _hours("2026-03-05T00:00:00", 3)
    comp = feedin_compensation(cfg, bare_supply_price(cfg, np.array([0.10, np.nan, 0.10])))
    result = feedin_floor_topup(cfg, np.array([1.0, 1.0, 1.0]), comp, index)
    assert result.topup_eur == 0.0


def test_the_floor_excludes_gap_intervals_on_the_export_side_too() -> None:
    """`Flows.exp` is NaN on a §6.9 gap interval; that interval must not enter the aggregate.

    The gap hour carries the only negative compensation, so including it would produce a
    −0.2795 month and a top-up; excluding it leaves a positive month and zero.
    """
    cfg = PricingConfig(feedin_alpha=1.0, feedin_beta=0.0)
    index = _hours("2026-03-05T00:00:00", 3)
    comp = feedin_compensation(cfg, bare_supply_price(cfg, np.array([0.10, -0.30, 0.10])))
    export = np.array([1.0, np.nan, 1.0])
    result = feedin_floor_topup(cfg, export, comp, index)
    assert result.topup_eur == 0.0


def test_an_all_nan_window_yields_a_zero_topup_not_a_nan() -> None:
    """Every interval uncovered: nothing is assessed, and the answer is 0.0 rather than NaN.

    A NaN here would propagate into §6.10's bill for a window that may be priced almost
    everywhere else. The frame reports `spot_missing_intervals` for the caller to caveat with;
    this module does not re-report it.
    """
    cfg = PricingConfig()
    index = _hours("2026-03-05T00:00:00", 3)
    result = feedin_floor_topup(cfg, np.ones(3), np.full(3, np.nan), index)
    assert result.topup_eur == 0.0
