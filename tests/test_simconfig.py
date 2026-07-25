"""Unit tests for the simulation configuration object (app/domain/simconfig.py).

What these pin, and why each is worth a test:

  * **Defaults against appendix A**, table-driven. Appendix A is the single authority for every
    shipped default, and a default silently drifting from it is the kind of change nothing else
    would catch — the simulation would still run and still produce a plausible number. The table
    is written out longhand rather than looped over the dataclass so that ADDING a field with a
    wrong default fails too.
  * **The efficiency split.** `eta_c == eta_d == 0.9486832980505138` and `eta_c_dc == sqrt(0.94)`,
    as HARDCODED literals rather than as `math.sqrt(0.90)` — an assertion written with the
    implementation's own formula passes for any implementation using that formula, including a
    wrong one, so the numbers are pinned instead. That convention is what §6.14 fixture 2 rests
    on: a 10 kWh charge+discharge at 90% RTE must return 9.0 kWh AC, a loss of exactly 1.0 kWh.
    The round trip is simulated arithmetically so the 1.0 figure is asserted directly, and the
    linear 0.95/0.95 alternative is asserted NOT to reproduce it.
  * **SoC bounds**, including a non-100 max, since percentages of USABLE capacity (§6.8) and
    percentages of the min..max window are easy to confuse and agree at max = 100.
  * **The fuse derivation**, split two ways: the EXACT cap §6.8 step 6 compares against, and the
    rounded figure panel ② prints. 3×25 A (17.25 exact / 17.3 display) and 3×16 A (11.04 exact /
    11.0 display — the only published-adjacent case that rounds DOWN) pin both halves.
  * **Check 11 blocks**, one case per condition, each asserted to key the RIGHT field — Phase 6
    renders these inline, so an error keyed to the wrong input is a real defect.
  * **Check 12 warns and does not block**, and the overlapping config is still usable.
  * **The two forced invariants**: `economic_guard` off without cost simulation even when a
    caller sets it True, and `pv_coupling` null without PV — including after POST-CONSTRUCTION
    mutation and with no `validate()` call, since dispatch must not depend on either.
  * **Post-construction mutation of every input a derived value reads.** Derived quantities are
    properties, not cached fields, precisely so a Phase-6 form binding cannot leave `soc_max_kwh`
    or `eta_c` answering for a value the user has already changed. This is the gap that let the
    original cached-field defect through 75 tests, so it gets a test per derived quantity.
  * **No aliasing between configs.** `SimulationConfig` copies its sub-configs, because forcing
    the invariants WRITES to them and a shared group would otherwise have one config silently
    rewrite another's.
  * **Construction never raises**, for None / str / nan / inf, with `validate()` reporting each
    against the field that carries it — an empty Phase-6 form field is exactly this case.
  * **Offerability without PV**, together with the absence of any has_pv effect on the fields
    §6.6/§6.7 dispatch on — the spec says that branch must not exist, so the test checks the
    dispatch-relevant fields are untouched rather than only checking the UI query.
"""

import math

import pytest

from app.domain.simconfig import (
    RTE_MIN,
    BatteryConfig,
    BatteryPhases,
    ChargePolicy,
    Coupling,
    DischargePolicy,
    GridConfig,
    PolicyConfig,
    PvCoupling,
    SimulationConfig,
    TopologyConfig,
    connection_capacity_kw,
    connection_capacity_kw_display,
)
from app.domain.simframe import CLOSURE_TOL

# ── Defaults vs appendix A ───────────────────────────────────────────────────────────────────

# (dotted path, expected value) — every default this object ships, as appendix A states it.
# Bands and the two policies are NOT in appendix A (it says so: "no fixed default"); their
# expected values come from the §2.3 wireframe and are marked as such.
_APPENDIX_A_DEFAULTS = [
    ("battery.usable_capacity_kwh", 10.0),
    ("battery.min_soc_pct", 10.0),
    ("battery.max_soc_pct", 100.0),
    ("battery.max_charge_kw", 5.0),
    ("battery.max_discharge_kw", 5.0),
    ("battery.roundtrip_efficiency", 0.90),
    ("battery.roundtrip_dc_bonus", 0.04),
    ("battery.standby_w", 30.0),
    ("battery.initial_soc_pct", 50.0),
    ("battery.coupling", Coupling.AC),
    ("grid.phases", 1),
    ("grid.fuse_a", 25.0),
    ("grid.max_export_kw", None),  # appendix A: "= import", i.e. follow, not a number
    ("policy.allow_grid_export", False),
    ("policy.economic_guard", False),
    ("topology.pv_coupling", PvCoupling.DC_HYBRID),
    ("topology.battery_phases", BatteryPhases.THREE_PHASE),
    ("has_pv", True),
    ("simulate_cost", False),
]

# §2.3 wireframe (appendix A carries no default for these).
_WIREFRAME_DEFAULTS = [
    ("policy.charge_policy", ChargePolicy.P3),
    ("policy.discharge_policy", DischargePolicy.D1),
    ("policy.band_a", -0.050),
    ("policy.band_b", 0.040),
    ("policy.band_c", 0.180),
    ("policy.band_d", 9.999),
]


def _get(obj, path: str):
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


@pytest.mark.parametrize("path,expected", _APPENDIX_A_DEFAULTS + _WIREFRAME_DEFAULTS)
def test_defaults_match_the_spec(path, expected):
    """Every shipped default is the one appendix A (or §2.3, for the bands) states."""
    assert _get(SimulationConfig(), path) == expected


def test_default_max_export_follows_import():
    """`max_export_kw = None` means "same as import", resolved on the derived property."""
    cfg = SimulationConfig()
    assert cfg.max_export_kw == cfg.max_import_kw == 5.75
    # And it FOLLOWS: changing the connection moves the export cap with it, which is the whole
    # reason the stored field is None rather than a copied 5.75. The 3-phase figure here is the
    # EXACT 17.25, not the 17.3 panel ② prints — the export cap is a physical limit (§6.8 step 6).
    three = SimulationConfig(grid=GridConfig(phases=3))
    assert three.max_export_kw == three.max_import_kw == 17.25


# ── The efficiency split (§6.8; §6.14 fixture 2 depends on it) ───────────────────────────────


def test_efficiency_split_is_geometric():
    """`eta_c = eta_d = sqrt(RTE)`, and the DC path uses sqrt(RTE + bonus).

    The expected values are HARDCODED literals, not `math.sqrt(0.90)`. Writing the assertion with
    the implementation's own formula makes it pass for whatever that formula happens to be, which
    is precisely the convention this test exists to pin.
    """
    b = SimulationConfig().battery
    assert b.eta_c == pytest.approx(0.9486832980505138)
    assert b.eta_d == pytest.approx(0.9486832980505138)
    assert b.eta_c == b.eta_d
    assert b.eta_c_dc == pytest.approx(0.9695359714832659)  # sqrt(0.94)
    # The DC path is better than the AC one — by construction, but worth pinning, since a sign
    # error on the bonus would still produce two plausible-looking efficiencies.
    assert b.eta_c_dc > b.eta_c


def test_the_split_is_geometric_and_not_linear():
    """The convention, pinned against the alternative that also looks symmetric.

    Replaces an earlier `sqrt(r) * sqrt(r) == r` assertion, which was near-unfailable: it holds
    for any implementation that uses the same expression twice, including a wrong one. What
    actually needs pinning is (a) the literal value of the split at the default RTE and (b) that
    the OTHER symmetric-looking split — 0.95/0.95, half the loss each way in linear terms — does
    NOT reproduce §6.14 fixture 2's 1.0 kWh round-trip loss.
    """
    b = BatteryConfig(roundtrip_efficiency=0.90)
    assert b.eta_c == pytest.approx(0.9486832980505138)

    # `eta_c * eta_d == roundtrip_efficiency` is the identity fixture 2 rests on, across the range.
    for rte in (0.90, 0.85, 0.95, 1.0, 0.75):
        other = BatteryConfig(roundtrip_efficiency=rte)
        assert abs(other.eta_c * other.eta_d - rte) < CLOSURE_TOL

    # The linear split: plausible, symmetric, and wrong. 10 kWh in returns 9.025, not 9.0 — the
    # loss is 0.975 kWh where the fixture says exactly 1.0.
    linear_returned = 10.0 * 0.95 * 0.95
    assert linear_returned == pytest.approx(9.025)
    assert abs(10.0 - linear_returned - 1.0) > CLOSURE_TOL


def test_ten_kwh_round_trip_loses_exactly_one_kwh():
    """§6.14 fixture 2: 10 kWh AC in, 9.0 kWh AC out at 90% RTE — a 1.0 kWh loss, not 0.9/1.11.

    The §6.8 step function stores `chg_ac * eta_c` and returns `dis_ac` for `dis_ac / eta_d`
    withdrawn; run through here arithmetically so the published figure is asserted directly rather
    than only through the identity above.
    """
    b = BatteryConfig(usable_capacity_kwh=10.0, roundtrip_efficiency=0.90)
    charged_ac = 10.0
    stored = charged_ac * b.eta_c
    returned_ac = stored * b.eta_d
    assert returned_ac == pytest.approx(9.0, abs=CLOSURE_TOL)
    assert charged_ac - returned_ac == pytest.approx(1.0, abs=CLOSURE_TOL)
    # The intermediate SoC is what distinguishes the geometric split from putting the whole loss
    # on the charge side (which also returns 9.0 but stores 9.0, not 9.4868).
    assert stored == pytest.approx(9.48683298, abs=1e-6)


def test_finite_returns_none_for_an_int_too_large_to_be_a_float():
    """The numeric funnel's contract is "None for anything unusable", never an exception.

    A Python int is unbounded; a float is not. The form layer parses digit strings with `int()`
    first, which succeeds up to Python's 4300-digit limit, so an int with no float representation
    is an ORDINARY value for this funnel to be handed — and `float()` on it raises `OverflowError`
    rather than returning inf. Unguarded, that reached the web route as a 500.
    """
    from app.domain.simconfig import _finite

    assert _finite(int("9" * 400)) is None
    assert _finite(int("9" * 4000)) is None
    assert _finite(-int("9" * 400)) is None
    assert _finite(10**308) == pytest.approx(1e308)   # still inside float range, still a number


def test_a_config_holding_an_unfloatable_int_is_constructible_and_blocks():
    """Same guarantee one level up: construction never raises, `validate()` reports it."""
    cfg = SimulationConfig(battery=BatteryConfig(usable_capacity_kwh=int("9" * 4000)))
    assert cfg.validate().blocking
    assert cfg.battery.soc_max_kwh == 0.0    # the funnel's 0.0 substitute, not a crash


def test_invalid_efficiency_does_not_raise_on_construction():
    """A nonsense RTE must be CONSTRUCTIBLE so the form can render it back with its error."""
    cfg = SimulationConfig(battery=BatteryConfig(roundtrip_efficiency=-0.5))
    assert cfg.battery.eta_c == 0.0  # floored, meaningless, and reported by validate()
    assert cfg.validate().blocking


# ── SoC bounds (§6.8) ────────────────────────────────────────────────────────────────────────


def test_soc_bounds_are_percentages_of_usable_capacity():
    b = SimulationConfig().battery
    assert b.soc_min_kwh == pytest.approx(1.0)  # 10% of 10 kWh
    assert b.soc_max_kwh == pytest.approx(10.0)  # 100% of 10 kWh
    assert b.initial_soc_kwh == pytest.approx(5.0)  # 50% of 10 kWh


def test_soc_bounds_with_a_non_full_max():
    """max_soc_pct 80 on a 14 kWh battery: bounds are of USABLE capacity, not of the window.

    With min 20 / max 80 the operating window is 8.4 kWh wide, but `initial_soc_pct = 50` means
    50% of 14 kWh = 7.0 kWh — NOT the midpoint of [2.8, 11.2], which would also be 7.0, so the
    initial SoC is deliberately set to 30 here where the two readings differ (4.2 vs 5.32).
    """
    b = BatteryConfig(
        usable_capacity_kwh=14.0, min_soc_pct=20.0, max_soc_pct=80.0, initial_soc_pct=30.0
    )
    assert b.soc_min_kwh == pytest.approx(2.8)
    assert b.soc_max_kwh == pytest.approx(11.2)
    assert b.initial_soc_kwh == pytest.approx(4.2)


# ── The connection capacity (appendix A / background E-A) ────────────────────────────────────


def test_connection_capacity_is_exact_for_computation():
    """The cap §6.8 step 6 compares against carries NO rounding — `phases × A × 230 / 1000`.

    Rounding the cap would bake a display decision into the physics. The two cases where it shows:
    3×25 A is 17.25 exactly (displayed 17.3, +50 W if used as the limit) and 3×16 A is 11.04
    (displayed 11.0, −40 W).
    """
    assert connection_capacity_kw(1, 25) == pytest.approx(5.75)
    assert connection_capacity_kw(3, 25) == pytest.approx(17.25)
    assert connection_capacity_kw(3, 16) == pytest.approx(11.04)
    assert SimulationConfig().max_import_kw == pytest.approx(5.75)
    assert SimulationConfig(grid=GridConfig(phases=3)).max_import_kw == pytest.approx(17.25)


def test_connection_capacity_display_matches_the_published_figures():
    """1×25 A → 5.75 kW, 3×25 A → 17.3 kW — the only two figures the specs publish.

    17.3 is the one that catches a wrong rounding mode: `3 × 25 × 230 / 1000` is exactly 17.25,
    and Python's `round(17.25, 1)` is 17.2 (banker's rounding to the even digit), so plain `round`
    cannot produce the published value at all.
    """
    assert connection_capacity_kw_display(1, 25) == 5.75
    assert connection_capacity_kw_display(3, 25) == 17.3
    assert SimulationConfig().max_import_kw_display == 5.75
    assert SimulationConfig(grid=GridConfig(phases=3)).max_import_kw_display == 17.3


def test_display_rounding_can_go_down_as_well_as_up():
    """3×16 A → 11.04 kW → 11.0. The one common case where the display is BELOW the real cap.

    Every other case in these tests rounds up, so a display helper that only ever rounded away
    from zero upward would still pass them. The exact value stays 11.04 for the simulation.
    """
    assert connection_capacity_kw(3, 16) == pytest.approx(11.04)
    assert connection_capacity_kw_display(3, 16) == 11.0
    cfg = SimulationConfig(grid=GridConfig(phases=3, fuse_a=16))
    assert cfg.max_import_kw == pytest.approx(11.04)
    assert cfg.max_import_kw_display == 11.0


def test_connection_capacity_scales_with_the_fuse():
    """Derived, not table-looked-up — any fuse rating works, which is the point of the control."""
    assert connection_capacity_kw(1, 35) == pytest.approx(8.05)
    assert connection_capacity_kw(3, 35) == pytest.approx(24.15)
    assert connection_capacity_kw_display(1, 35) == 8.05
    assert connection_capacity_kw_display(3, 35) == 24.2  # 24.15 → half-up


def test_import_override_wins_over_the_derivation():
    cfg = SimulationConfig(grid=GridConfig(max_import_kw_override=4.0))
    assert cfg.max_import_kw == 4.0
    assert cfg.max_export_kw == 4.0  # export still follows import
    # An override is a number the user typed, so it is not re-rounded for display either.
    assert cfg.max_import_kw_display == 4.0


# ── §7.3 check 11 — blocks, with the error keyed to the right field ──────────────────────────


def _error_fields(cfg: SimulationConfig) -> set[str]:
    return cfg.validate().fields_with_errors()


def test_default_config_is_valid():
    result = SimulationConfig().validate()
    assert result.errors == ()
    assert result.warnings == ()
    assert not result.blocking


def test_check11_blocks_when_soc_window_is_empty():
    for min_pct, max_pct in ((60.0, 40.0), (50.0, 50.0)):  # inverted, and zero-width
        cfg = SimulationConfig(battery=BatteryConfig(min_soc_pct=min_pct, max_soc_pct=max_pct))
        result = cfg.validate()
        assert result.blocking
        assert "battery.min_soc_pct" in result.fields_with_errors()
        assert any(i.code == "soc_window_empty" for i in result.errors)


@pytest.mark.parametrize(
    "kwargs,expected_field",
    [
        ({"max_charge_kw": 0.0}, "battery.max_charge_kw"),
        ({"max_charge_kw": -1.0}, "battery.max_charge_kw"),
        ({"max_discharge_kw": 0.0}, "battery.max_discharge_kw"),
        ({"max_discharge_kw": -2.5}, "battery.max_discharge_kw"),
    ],
)
def test_check11_blocks_on_non_positive_powers(kwargs, expected_field):
    result = SimulationConfig(battery=BatteryConfig(**kwargs)).validate()
    assert result.blocking
    assert expected_field in result.fields_with_errors()
    assert any(i.code == "power_not_positive" for i in result.errors)


@pytest.mark.parametrize("rte", [0.5, 0.4, 0.0, -0.1, 1.01, 2.0])
def test_check11_blocks_on_out_of_range_rte(rte):
    """`rte_min < RTE <= 1.0`. 0.5 is excluded (strict lower bound), 1.0 is not (physics bound)."""
    result = SimulationConfig(battery=BatteryConfig(roundtrip_efficiency=rte)).validate()
    assert result.blocking
    assert "battery.roundtrip_efficiency" in result.fields_with_errors()
    assert any(i.code == "rte_out_of_range" for i in result.errors)


@pytest.mark.parametrize("rte", [0.5001, 0.75, 0.90, 1.0])
def test_rte_inside_the_range_is_accepted(rte):
    """The bounds are asymmetric on purpose: RTE_MIN is strict, 1.0 (a lossless battery) is not."""
    assert rte > RTE_MIN
    result = SimulationConfig(battery=BatteryConfig(roundtrip_efficiency=rte)).validate()
    assert not any(i.code == "rte_out_of_range" for i in result.errors)


@pytest.mark.parametrize(
    "kwargs,expected_field,code",
    [
        ({"min_soc_pct": -5.0}, "battery.min_soc_pct", "soc_pct_out_of_range"),
        ({"max_soc_pct": 120.0}, "battery.max_soc_pct", "soc_pct_out_of_range"),
        ({"initial_soc_pct": 130.0}, "battery.initial_soc_pct", "soc_pct_out_of_range"),
        ({"standby_w": -1.0}, "battery.standby_w", "standby_negative"),
        ({"usable_capacity_kwh": 0.0}, "battery.usable_capacity_kwh", "capacity_not_positive"),
    ],
)
def test_structurally_impossible_values_block(kwargs, expected_field, code):
    result = SimulationConfig(battery=BatteryConfig(**kwargs)).validate()
    assert result.blocking
    assert expected_field in result.fields_with_errors()
    assert any(i.code == code for i in result.errors)


def test_unsupported_phase_count_blocks_on_the_phases_field():
    result = SimulationConfig(grid=GridConfig(phases=2)).validate()
    assert result.blocking
    assert "grid.phases" in result.fields_with_errors()


def test_non_positive_import_override_is_keyed_to_the_override_field():
    """A bad override is the OVERRIDE's fault, not the fuse's.

    Phase 6 renders errors inline against the input the user typed in, so keying this to
    `grid.fuse_a` would put a red border on a perfectly good 25 A fuse and leave the field that
    actually caused it unmarked.
    """
    result = SimulationConfig(grid=GridConfig(max_import_kw_override=-1.0)).validate()
    assert result.blocking
    assert any(i.code == "power_not_positive" for i in result.errors)
    # ONE field, and it is the override. Not the fuse, and not `max_export_kw` either — the export
    # cap follows import when unset, so reporting it too would be one mistake shown against two
    # inputs the user has to reason about separately.
    assert result.fields_with_errors() == {"grid.max_import_kw_override"}


def test_an_explicitly_negative_export_cap_still_blocks_on_its_own_field():
    """The follow-import suppression above must not silence a real, explicit export value."""
    result = SimulationConfig(grid=GridConfig(max_export_kw=-1.0)).validate()
    assert result.blocking
    assert result.fields_with_errors() == {"grid.max_export_kw"}
    assert any(i.code == "power_negative" for i in result.errors)


def test_non_positive_derived_import_is_still_keyed_to_the_fuse():
    """With no override, the fuse IS the field the user typed in, so it keeps the key."""
    result = SimulationConfig(grid=GridConfig(fuse_a=0.0)).validate()
    assert result.blocking
    assert result.fields_with_errors() == {"grid.fuse_a"}


# ── §7.3 check 12 — warns, allows ────────────────────────────────────────────────────────────


def test_check12_warns_but_does_not_block_on_overlapping_bands():
    """§6.7 nets overlapping requests at runtime, so an overlap must not block the run."""
    cfg = SimulationConfig(
        policy=PolicyConfig(band_a=-0.05, band_b=0.20, band_c=0.10, band_d=9.999)
    )
    result = cfg.validate()
    assert cfg.bands_overlap()
    assert not result.blocking
    assert result.errors == ()
    assert any(i.code == "bands_overlap" for i in result.warnings)
    # ...and the config is still fully usable: every quantity §6.6–§6.8 reads is present.
    assert cfg.band_a == -0.05 and cfg.band_b == 0.20
    assert cfg.band_c == 0.10 and cfg.band_d == 9.999
    assert cfg.eta_c > 0 and cfg.max_import_kw > 0


def test_default_bands_do_not_overlap():
    """§2.3's wireframe shows the ✓ for exactly these numbers."""
    cfg = SimulationConfig()
    assert not cfg.bands_overlap()
    assert not any(i.code == "bands_overlap" for i in cfg.validate().warnings)


def test_touching_bands_count_as_overlapping():
    """Both bands are CLOSED (§6.6/§6.7 use `<=` at both ends), so a shared endpoint fires both."""
    cfg = SimulationConfig(policy=PolicyConfig(band_a=-0.05, band_b=0.10, band_c=0.10, band_d=0.5))
    assert cfg.bands_overlap()
    assert not cfg.validate().blocking


def test_inverted_band_warns_and_does_not_block():
    """A band that never fires is well-defined; almost certainly a typo, so warn, do not block."""
    result = SimulationConfig(policy=PolicyConfig(band_a=0.20, band_b=-0.05)).validate()
    assert not result.blocking
    assert any(i.code == "band_inverted" and i.field == "policy.band_a" for i in result.warnings)


def test_initial_soc_outside_the_window_warns_only():
    """§6.8 clamps at the first step, so this is a surprise to explain, not a run to refuse."""
    result = SimulationConfig(
        battery=BatteryConfig(min_soc_pct=20.0, max_soc_pct=80.0, initial_soc_pct=5.0)
    ).validate()
    assert not result.blocking
    assert any(i.code == "initial_soc_outside_window" for i in result.warnings)


def test_dc_bonus_pushing_past_unity_warns():
    result = SimulationConfig(
        battery=BatteryConfig(roundtrip_efficiency=0.99, roundtrip_dc_bonus=0.04)
    ).validate()
    assert not result.blocking
    assert any(i.code == "dc_efficiency_above_unity" for i in result.warnings)


# ── The forced invariants ────────────────────────────────────────────────────────────────────


def test_economic_guard_is_forced_off_without_cost_simulation():
    """Appendix A / §6.7: FORCED, not merely hidden — it reads a cost-model output."""
    cfg = SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=False)
    assert cfg.policy.economic_guard is False
    assert cfg.economic_guard is False


def test_economic_guard_survives_when_cost_simulation_is_on():
    cfg = SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=True)
    assert cfg.economic_guard is True


def test_economic_guard_is_off_by_default_even_with_cost_simulation():
    """Appendix A default is false regardless: "policies stay literal by default"."""
    assert SimulationConfig(simulate_cost=True).economic_guard is False


def test_pv_coupling_is_null_without_pv():
    """§2.5: "Set cfg.coupling = ac and topology.pv_coupling = null"."""
    cfg = SimulationConfig(
        topology=TopologyConfig(pv_coupling=PvCoupling.DC_HYBRID), has_pv=False
    )
    assert cfg.topology.pv_coupling is None
    # Forcing the battery coupling to AC is not an approximation: eta_c_dc multiplies chg_pv only,
    # which is identically zero without PV.
    assert cfg.coupling is Coupling.AC


def test_pv_coupling_is_kept_with_pv():
    cfg = SimulationConfig(
        battery=BatteryConfig(coupling=Coupling.DC_HYBRID),
        topology=TopologyConfig(pv_coupling=PvCoupling.DC_HYBRID),
        has_pv=True,
    )
    assert cfg.topology.pv_coupling is PvCoupling.DC_HYBRID
    assert cfg.coupling is Coupling.DC_HYBRID


# ── Offerability — a UI query, not dispatch semantics (§6.6) ─────────────────────────────────


def test_without_pv_only_p2_is_offered():
    """P1 charges nothing and P3 degenerates to P2 when `pv` is all zeros (§6.6)."""
    cfg = SimulationConfig(has_pv=False)
    assert cfg.offerable_charge_policies() == (ChargePolicy.P2,)


def test_with_pv_all_three_charge_policies_are_offered():
    assert SimulationConfig().offerable_charge_policies() == (
        ChargePolicy.P1,
        ChargePolicy.P2,
        ChargePolicy.P3,
    )


def test_all_discharge_policies_are_offered_regardless_of_pv():
    """§6.7: "all three remain available and distinct without PV" — only D1's LABEL changes."""
    expected = (DischargePolicy.D1, DischargePolicy.D2, DischargePolicy.D3)
    assert SimulationConfig().offerable_discharge_policies() == expected
    assert SimulationConfig(has_pv=False).offerable_discharge_policies() == expected


def test_no_pv_does_not_touch_the_dispatch_relevant_fields():
    """§6.6: the dispatch code "needs no branch on has_pv ... and should not acquire one".

    So turning PV off must leave everything §6.6/§6.7 read IDENTICAL — the stored charge policy
    included. Rewriting a stored P3 to P2 would change no number (P3 degenerates to P2 there) but
    would silently discard the user's answer if they later turn PV back on.

    **Two dispatch-relevant fields are deliberately NOT in the lists below: `coupling` and
    `eta_c_dc`.** §6.8 step 3 does read `cfg.coupling`, so this test's coverage is not "every
    field dispatch reads" — those two ARE changed by `has_pv`, by §2.5's explicit instruction
    ("set cfg.coupling = ac"), and `test_pv_coupling_is_null_without_pv` is what pins them. The
    change is invariant-preserving rather than semantic: `eta_c_dc` multiplies `chg_pv` only, and
    `chg_pv` is identically zero when `pv` is all zeros, so both settings give the same numbers.
    """
    with_pv = SimulationConfig(policy=PolicyConfig(charge_policy=ChargePolicy.P3))
    without = SimulationConfig(policy=PolicyConfig(charge_policy=ChargePolicy.P3), has_pv=False)
    for name in (
        "charge_policy",
        "discharge_policy",
        "band_a",
        "band_b",
        "band_c",
        "band_d",
        "allow_grid_export",
        "economic_guard",
    ):
        assert getattr(with_pv.policy, name) == getattr(without.policy, name), name
    for name in ("max_charge_kw", "max_discharge_kw", "soc_min_kwh", "soc_max_kwh", "eta_c",
                 "eta_d", "max_import_kw", "max_export_kw"):
        assert getattr(with_pv, name) == getattr(without, name), name


# ── Topology: the §2.5(b) phase selector and the soft block ──────────────────────────────────


def test_phase_selector_is_offered_only_on_a_three_phase_connection():
    assert SimulationConfig().battery_phases_offered is False
    assert SimulationConfig(grid=GridConfig(phases=3)).battery_phases_offered is True


def test_battery_phases_is_retained_but_inert_on_one_phase():
    """Appendix A defaults battery_phases to three_phase while phases defaults to 1.

    The stored value is left alone rather than normalised — v1 has no per-phase model, so it
    changes no number, and clearing it would lose the user's answer on a later switch to 3-phase.
    """
    cfg = SimulationConfig()
    assert cfg.topology.battery_phases is BatteryPhases.THREE_PHASE
    assert cfg.battery_phases_offered is False


def test_approximated_is_a_user_choice_not_a_derivation():
    """§2.5's soft block: `approximated` records that the user continued past the dialog."""
    assert SimulationConfig().topology.approximated is False
    unsupported = SimulationConfig(
        grid=GridConfig(phases=3),
        topology=TopologyConfig(battery_phases=BatteryPhases.ONE_PHASE),
    )
    # Not set merely by picking an unsupported topology — the user has to continue past the dialog.
    assert unsupported.topology.approximated is False
    assert not unsupported.validate().blocking


# ── Post-construction mutation: derived values are properties, never cached ──────────────────
#
# The defect this section exists for: derived quantities were once computed in `__post_init__`
# and stored in `init=False` fields, so `cfg.battery.usable_capacity_kwh = 20.0` left
# `cfg.soc_max_kwh` answering 10.0 forever, with nothing raised and nothing in the result looking
# wrong. Seventy-five tests passed over it because every one of them read the derived value on a
# freshly constructed object. Phase 6 binds a mutable form to these objects, so mutation is the
# normal path, not an edge case — hence one test per derived quantity, all mutating AFTER
# construction and all reading through `SimulationConfig`'s flat accessors, which is how §6.8
# reads them.


def test_soc_bounds_follow_a_post_construction_capacity_change():
    cfg = SimulationConfig()
    assert cfg.soc_max_kwh == pytest.approx(10.0)
    cfg.battery.usable_capacity_kwh = 20.0
    assert cfg.soc_max_kwh == pytest.approx(20.0)
    assert cfg.soc_min_kwh == pytest.approx(2.0)
    assert cfg.initial_soc_kwh == pytest.approx(10.0)


def test_soc_bounds_follow_post_construction_percentage_changes():
    cfg = SimulationConfig()
    cfg.battery.min_soc_pct = 20.0
    cfg.battery.max_soc_pct = 80.0
    cfg.battery.initial_soc_pct = 30.0
    assert cfg.soc_min_kwh == pytest.approx(2.0)
    assert cfg.soc_max_kwh == pytest.approx(8.0)
    assert cfg.initial_soc_kwh == pytest.approx(3.0)


def test_efficiencies_follow_a_post_construction_rte_change():
    """0.64 → 0.8 exactly, which is the point: a stale 0.94868 would corrupt every §6.8 number."""
    cfg = SimulationConfig()
    cfg.battery.roundtrip_efficiency = 0.64
    assert cfg.eta_c == pytest.approx(0.8)
    assert cfg.eta_d == pytest.approx(0.8)


def test_dc_efficiency_follows_a_post_construction_bonus_change():
    cfg = SimulationConfig()
    cfg.battery.roundtrip_dc_bonus = 0.0
    assert cfg.eta_c_dc == pytest.approx(cfg.eta_c)
    cfg.battery.roundtrip_efficiency = 0.64
    cfg.battery.roundtrip_dc_bonus = 0.36
    assert cfg.eta_c_dc == pytest.approx(1.0)


def test_connection_cap_follows_post_construction_fuse_and_phase_changes():
    cfg = SimulationConfig()
    assert cfg.max_import_kw == pytest.approx(5.75)
    cfg.grid.fuse_a = 80.0
    cfg.grid.phases = 3
    assert cfg.max_import_kw == pytest.approx(55.2)  # 3 × 80 × 230 / 1000
    assert cfg.max_export_kw == pytest.approx(55.2)  # follows, since max_export_kw is still None
    assert cfg.max_import_kw_display == 55.2


def test_standby_kw_follows_a_post_construction_change():
    cfg = SimulationConfig()
    assert cfg.standby_kw == pytest.approx(0.030)
    cfg.battery.standby_w = 45.0
    assert cfg.standby_kw == pytest.approx(0.045)


def test_validate_sees_a_post_construction_change():
    """A config mutated into an invalid state must validate as invalid.

    With cached derived fields this passed as valid — `validate()` compared stale numbers.
    """
    cfg = SimulationConfig()
    assert not cfg.validate().blocking
    cfg.battery.roundtrip_efficiency = 0.2
    result = cfg.validate()
    assert result.blocking
    assert "battery.roundtrip_efficiency" in result.fields_with_errors()


# ── The forced invariants under mutation, and without any validate() call ────────────────────


def test_economic_guard_reads_false_without_a_cost_model_and_no_validation():
    """Set directly on the sub-config, never validated — dispatch still must not see it True.

    §6.7's guard reads `st.p_export_net`, which does not exist in an energy-only run. Making the
    forcing a validate-time correction would leave a caller who skipped `validate()` able to make
    §6.7 read an array that is not there. So it is applied on READ.
    """
    cfg = SimulationConfig(simulate_cost=False)
    cfg.policy.economic_guard = True  # no validate() call anywhere in this test
    assert cfg.economic_guard is False


def test_economic_guard_forcing_follows_simulate_cost_being_turned_off():
    cfg = SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=True)
    assert cfg.economic_guard is True
    cfg.simulate_cost = False
    assert cfg.economic_guard is False


def test_economic_guard_raw_choice_is_retained_for_the_round_trip():
    """Appendix A: cost-only parameters are RETAINED, not reset, so re-enabling restores them.

    Phase 6 has to round-trip the checkbox through a save/load cycle, so the user's raw answer
    stays stored while the read path forces False.
    """
    cfg = SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=True)
    cfg.simulate_cost = False
    assert cfg.economic_guard is False
    cfg.simulate_cost = True
    assert cfg.economic_guard is True


def test_validate_normalises_the_stored_economic_guard():
    """The read path is what makes it safe; validate() keeps the STORED value honest too.

    So a persisted parameter file, or a config inspected in a debugger, does not show a setting
    the spec forbids.
    """
    cfg = SimulationConfig(simulate_cost=False)
    cfg.policy.economic_guard = True
    cfg.validate()
    assert cfg.policy.economic_guard is False


def test_pv_coupling_forcing_follows_has_pv_being_turned_off():
    """Turning PV off after construction must still give §2.5's `coupling = ac`, unvalidated."""
    cfg = SimulationConfig(
        battery=BatteryConfig(coupling=Coupling.DC_HYBRID),
        topology=TopologyConfig(pv_coupling=PvCoupling.DC_HYBRID),
        has_pv=True,
    )
    assert cfg.coupling is Coupling.DC_HYBRID
    cfg.has_pv = False
    assert cfg.coupling is Coupling.AC  # no validate() call
    assert cfg.pv_coupling is None


def test_pv_coupling_raw_choice_is_retained_for_the_round_trip():
    """The user's illustrated §2.5(a) answer survives a PV-off/PV-on cycle, like economic_guard."""
    cfg = SimulationConfig(
        battery=BatteryConfig(coupling=Coupling.DC_HYBRID),
        topology=TopologyConfig(pv_coupling=PvCoupling.DC_HYBRID),
        has_pv=True,
    )
    cfg.has_pv = False
    assert cfg.pv_coupling is None
    cfg.has_pv = True
    assert cfg.pv_coupling is PvCoupling.DC_HYBRID
    assert cfg.coupling is Coupling.DC_HYBRID


def test_validate_normalises_the_stored_pv_coupling():
    cfg = SimulationConfig(topology=TopologyConfig(pv_coupling=PvCoupling.DC_HYBRID))
    cfg.has_pv = False
    cfg.validate()
    assert cfg.topology.pv_coupling is None
    assert cfg.battery.coupling is Coupling.AC


# ── No aliasing between configs ──────────────────────────────────────────────────────────────


def test_sub_configs_are_copied_so_two_configs_cannot_share_one():
    """Forcing the invariants WRITES to the sub-objects, so a shared group would corrupt both.

    Realistic in Phase 6: "clone this config", or a with-PV / without-PV comparison, naturally
    reuses a group. Before the copy, constructing `c2` reached back into `c1`.
    """
    shared = BatteryConfig()
    c1 = SimulationConfig(battery=shared, has_pv=True)
    c1.battery.coupling = Coupling.DC_HYBRID
    c2 = SimulationConfig(battery=shared, has_pv=False)
    assert c1.coupling is Coupling.DC_HYBRID  # untouched by c2's construction
    assert c2.coupling is Coupling.AC


def test_mutating_one_config_does_not_move_another():
    """The copy is a real copy, not just protection against the forcing."""
    shared = GridConfig()
    c1 = SimulationConfig(grid=shared)
    c2 = SimulationConfig(grid=shared)
    c1.grid.fuse_a = 40.0
    assert c2.max_import_kw == pytest.approx(5.75)
    assert shared.fuse_a == 25.0  # the caller's own object is untouched too


def test_two_default_configs_do_not_share_their_groups():
    """`default_factory` was already correct; asserted so a later "fix" cannot regress it."""
    a, b = SimulationConfig(), SimulationConfig()
    a.battery.usable_capacity_kwh = 99.0
    assert b.soc_max_kwh == pytest.approx(10.0)


# ── Construction never raises: None, strings, nan, inf ───────────────────────────────────────
#
# An empty Phase-6 form field arrives as `None` and an un-coerced text input as a `str`. The
# object that would carry the error message must not be the one that fails to exist, so these
# construct, derive without raising, and are reported by `validate()` against their own field.


@pytest.mark.parametrize("bad", [None, "3", float("nan"), float("inf"), float("-inf"), True])
def test_bad_phases_constructs_and_blocks_on_the_phases_field(bad):
    cfg = SimulationConfig(grid=GridConfig(phases=bad))
    assert isinstance(cfg.max_import_kw, float)  # derived, no raise
    result = cfg.validate()
    assert result.blocking
    # Exactly one field. A non-numeric phase count derives a 0.0 cap, which would otherwise also
    # trip "max import must be greater than 0" against a perfectly good 25 A fuse.
    assert result.fields_with_errors() == {"grid.phases"}


def test_a_true_phase_count_is_rejected_rather_than_read_as_one_phase():
    """`phases=True` would otherwise derive a plausible 5.75 kW and pass `phases in (1, 3)`.

    `True == 1` in Python, so the check and the derivation would BOTH accept it — a form-binding
    mistake that produces a completely normal-looking single-phase connection. The two paths are
    made to agree by rejecting bool at the funnel.
    """
    cfg = SimulationConfig(grid=GridConfig(phases=True))
    assert cfg.max_import_kw == 0.0
    assert any(i.code == "not_a_number" for i in cfg.validate().errors)


@pytest.mark.parametrize("bad", [None, "25", float("nan"), float("inf")])
def test_bad_fuse_constructs_and_blocks_on_the_fuse_field(bad):
    cfg = SimulationConfig(grid=GridConfig(fuse_a=bad))
    assert isinstance(cfg.max_import_kw, float)
    result = cfg.validate()
    assert result.blocking
    assert "grid.fuse_a" in result.fields_with_errors()


@pytest.mark.parametrize(
    "field_name,bad",
    [
        ("usable_capacity_kwh", None),
        ("usable_capacity_kwh", float("nan")),
        ("min_soc_pct", None),
        ("max_soc_pct", "100"),
        ("initial_soc_pct", float("inf")),
        ("max_charge_kw", None),
        ("max_discharge_kw", float("nan")),
        ("roundtrip_efficiency", None),
        ("roundtrip_efficiency", float("nan")),
        ("roundtrip_dc_bonus", "0.04"),
        ("standby_w", None),
    ],
)
def test_bad_battery_field_constructs_and_blocks_on_its_own_field(field_name, bad):
    cfg = SimulationConfig(battery=BatteryConfig(**{field_name: bad}))
    # Every derived quantity is still readable and still a finite float.
    for name in ("soc_min_kwh", "soc_max_kwh", "initial_soc_kwh", "eta_c", "eta_d", "eta_c_dc"):
        value = getattr(cfg, name)
        assert isinstance(value, float) and math.isfinite(value), name
    result = cfg.validate()
    assert result.blocking
    assert f"battery.{field_name}" in result.fields_with_errors()
    assert any(i.code == "not_a_number" for i in result.errors)


@pytest.mark.parametrize("field_name", ["band_a", "band_b", "band_c", "band_d"])
def test_bad_band_constructs_and_blocks_on_its_own_field(field_name):
    cfg = SimulationConfig(policy=PolicyConfig(**{field_name: None}))
    assert cfg.bands_overlap() in (True, False)  # no raise
    result = cfg.validate()
    assert result.blocking
    assert f"policy.{field_name}" in result.fields_with_errors()


def test_a_bad_field_is_reported_once_not_twice():
    """`capacity must be > 0 (got None)` on top of `must be a number` is one mistake, two errors.

    Phase 6 renders these inline; two messages under one input for one cause is noise.
    """
    result = SimulationConfig(battery=BatteryConfig(usable_capacity_kwh=None)).validate()
    capacity_errors = [
        i for i in result.errors if i.field == "battery.usable_capacity_kwh"
    ]
    assert len(capacity_errors) == 1
    assert capacity_errors[0].code == "not_a_number"


def test_optional_grid_fields_accept_none_but_not_nonsense():
    """None means "not overridden" / "follow import" — a defined value, not a bad one."""
    assert not SimulationConfig(
        grid=GridConfig(max_import_kw_override=None, max_export_kw=None)
    ).validate().blocking

    result = SimulationConfig(grid=GridConfig(max_export_kw="5")).validate()
    assert result.blocking
    assert "grid.max_export_kw" in result.fields_with_errors()


def test_a_broken_override_falls_back_to_the_fuse_rather_than_to_zero():
    """A nan override must not silently present the house as a 0 kW connection.

    It blocks either way, but the derived value staying sane keeps anything that reads the config
    before validating from producing a run in which every interval hits the import limit.
    """
    cfg = SimulationConfig(grid=GridConfig(max_import_kw_override=float("nan")))
    assert cfg.max_import_kw == pytest.approx(5.75)
    result = cfg.validate()
    assert result.blocking
    assert "grid.max_import_kw_override" in result.fields_with_errors()
