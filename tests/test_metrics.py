"""Hand-computed fixtures for the §6.11 energy metrics (app/domain/metrics.py).

**Every expected number here is derived on paper from the spec, never read off the
implementation.** That discipline is not stylistic. The conservation identity in
tests/test_simulate.py is §6.8 step 5 algebraically rearranged, so on the unconstrained path it
closes by construction — its own docstring demonstrates an energy-creating mutation (dropping
`eta_d` from `withdrawn`) that leaves it closing perfectly in every run. It therefore says nothing
about whether a metric computed from those same arrays is right, and no assertion below leans on
it.

The scenarios are small enough to work out by hand:

  * `test_hand_computed_*`      one 4-hour scenario whose every metric is derived in the
                                docstring: saved_kwh, saved_pct, efc, conversion loss, both
                                self-sufficiencies, both self-consumptions, throughput.
  * `test_saved_pct_denominator_is_run_a`   a frame where the SIMULATED baseline and the OBSERVED
                                import deliberately differ, pinning which one §6.11 divides by.
  * `test_self_consumption_is_none_without_pv`   null, not 0.0 and not 1.0.
  * `test_standby_is_the_exact_c_minus_b_difference`
  * `test_efc_counts_on_the_storage_side`   the ~5% convention §6.11 warns about.
  * `test_soc_drift_*`          the 2% surfacing threshold, above and below.
  * `test_negative_saving_*`    §7.2 item 9 — a negative saving passes through with its sign.

Frames are built with the same `_frame` / `_cfg` helpers tests/test_simulate.py uses, so the two
suites construct their inputs identically.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.domain.metrics import SOC_DRIFT_WARN_FRAC, energy_metrics
from app.domain.simconfig import ChargePolicy, DischargePolicy
from app.domain.simulate import run_all
from tests.test_simulate import _ETA, _arbitrage_cfg, _cfg, _frame, _square_wave_frame


# ── The one fully hand-worked scenario ────────────────────────────────────────────────────────
#
# Four hours, PV present, no standby, no grid charging, no grid export. Everything below is
# derived from these inputs and the §6.8 efficiency convention alone.
#
#   hour   load   pv     what the battery does under P1 (surplus only) / D1 (deficit only)
#   ----   ----   ---    ------------------------------------------------------------------
#     0     1.0   5.0    surplus 4.0 → charge 4.0 AC, stores 4.0 × η  = 3.7947
#     1     1.0   5.0    surplus 4.0 → charge 4.0 AC, stores          = 3.7947   (SoC 7.5895)
#     2     3.0   0.0    deficit 3.0 → discharge 3.0 AC, withdraws 3.0/η = 3.1623
#     3     3.0   0.0    deficit 3.0 → discharge 3.0 AC, withdraws     = 3.1623  (SoC 1.2649)
#
# η = sqrt(0.9) = 0.9486832980505138 both ways (§6.8's geometric split).
# Capacity 10 kWh, SoC window 0–100%, initial SoC 0, 5 kW each way — no clamp binds:
#   charge request 4.0 ≤ 5.0 kWh/h and SoC peaks at 7.5895 ≤ 10.0;
#   discharge request 3.0 ≤ 5.0 and available (7.5895 − 0) × η = 7.2 ≥ 3.0 at hour 2.
#
# Baseline (run A, no battery, no export cap binding):
#   hour 0: net = 1 − 5 = −4 → export 4.0
#   hour 1: export 4.0
#   hour 2: net = 3 − 0 = +3 → import 3.0
#   hour 3: import 3.0
#   A.imp = 6.0     A.exp = 8.0
#
# Battery (run C, standby 0 so C == B):
#   hour 0: net = load + chg − pv − dis = 1 + 4 − 5 − 0 = 0  → imp 0, exp 0
#   hour 1: 0
#   hour 2: net = 3 + 0 − 0 − 3 = 0 → imp 0, exp 0
#   hour 3: 0
#   C.imp = 0.0     C.exp = 0.0
#
# Metrics:
#   saved_kwh  = 6.0 − 0.0 = 6.0
#   saved_pct  = 100 × 6.0 / 6.0 = 100.0                    (denominator is run A)
#   charge_ac  = 8.0     discharge_ac = throughput = 6.0
#   withdrawn  = 2 × 3.0/η = 6.3246
#   efc        = 6.3246 / 10.0 = 0.63246                    (STORAGE side)
#   AC-side efc would be 6.0/10 = 0.60 — 5.1% lower, the convention §6.11 warns about
#   soc_start  = 0.0,  soc_end = 2×4.0×η − 2×3.0/η = 7.5895 − 6.3246 = 1.2649
#   conv_loss  = 8.0 − 6.0 − 1.2649 = 0.7351
#   pv_total   = 10.0    load_total = 8.0
#   self_sufficiency_baseline = 1 − 6.0/8.0 = 0.25
#   self_sufficiency_battery  = 1 − 0.0/8.0 = 1.00           (standby 0, so the loads are equal)
#   self_consumption_baseline = 1 − 8.0/10.0 = 0.20
#   self_consumption_battery  = 1 − 0.0/10.0 = 1.00

_HAND_LOAD = [1.0, 1.0, 3.0, 3.0]
_HAND_PV = [5.0, 5.0, 0.0, 0.0]


def _hand_metrics():
    frame = _frame(_HAND_LOAD, pv=_HAND_PV)
    cfg = _cfg(
        has_pv=True,
        usable_capacity_kwh=10.0,
        min_soc_pct=0.0,
        max_soc_pct=100.0,
        initial_soc_pct=0.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        roundtrip_efficiency=0.90,
        standby_w=0.0,
        charge_policy=ChargePolicy.P1,
        discharge_policy=DischargePolicy.D1,
        allow_grid_export=False,
        max_import_kw_override=100.0,
        max_export_kw=100.0,
    )
    return energy_metrics(run_all(frame, cfg), frame, cfg), frame, cfg


def test_hand_computed_saved_kwh_and_pct():
    """saved_kwh = A.imp − C.imp = 6.0 − 0.0; saved_pct = 100 × 6/6 (denominator run A)."""
    m, _, _ = _hand_metrics()
    assert m.baseline_import_kwh == pytest.approx(6.0, abs=1e-9)
    assert m.battery_import_kwh == pytest.approx(0.0, abs=1e-9)
    assert m.saved_kwh == pytest.approx(6.0, abs=1e-9)
    assert m.saved_pct == pytest.approx(100.0, abs=1e-9)


def test_hand_computed_efc_is_on_the_storage_side():
    """efc = Σ withdrawn / capacity = (2 × 3.0/η) / 10 = 0.63246 — NOT the AC-side 0.60.

    §6.11: "Convention matters: AC-side throughput gives a figure ~5% lower." Both figures are
    asserted so a switch to the AC side fails here rather than shifting the number quietly.
    """
    m, _, _ = _hand_metrics()
    expected_withdrawn = 2 * 3.0 / _ETA
    assert expected_withdrawn == pytest.approx(6.324555320336759, abs=1e-9)
    assert m.efc == pytest.approx(expected_withdrawn / 10.0, abs=1e-9)
    assert m.efc == pytest.approx(0.6324555320336759, abs=1e-9)
    # The AC-side alternative, which this must NOT be. It is lower by exactly the discharge
    # conversion — a factor of η — i.e. 5.1% at a 90% round trip, which is the "~5% lower" §6.11
    # warns about. (Not 1/0.9: only ONE of the two conversions sits between these two figures.)
    assert m.throughput_kwh / 10.0 == pytest.approx(0.60, abs=1e-9)
    assert m.efc / (m.throughput_kwh / 10.0) == pytest.approx(1 / _ETA, abs=1e-9)
    assert 1 - _ETA == pytest.approx(0.0513, abs=1e-4)


def test_hand_computed_throughput_and_charge_ac():
    """throughput = Σ (dis_home + dis_grid) = 6.0 AC; charge_ac = Σ (chg_pv + chg_grid) = 8.0."""
    m, _, _ = _hand_metrics()
    assert m.charge_ac_kwh == pytest.approx(8.0, abs=1e-9)
    assert m.discharge_ac_kwh == pytest.approx(6.0, abs=1e-9)
    assert m.throughput_kwh == pytest.approx(6.0, abs=1e-9)


def test_hand_computed_conversion_loss():
    """conversion_loss = charge_ac − discharge_ac − (soc_end − soc_start) = 8 − 6 − 1.2649."""
    m, _, _ = _hand_metrics()
    expected_soc_end = 2 * 4.0 * _ETA - 2 * 3.0 / _ETA
    assert expected_soc_end == pytest.approx(1.2649110640673518, abs=1e-9)
    assert m.soc_start_kwh == pytest.approx(0.0, abs=1e-9)
    assert m.soc_end_kwh == pytest.approx(expected_soc_end, abs=1e-9)
    assert m.soc_delta_kwh == pytest.approx(expected_soc_end, abs=1e-9)
    assert m.conversion_loss_kwh == pytest.approx(8.0 - 6.0 - expected_soc_end, abs=1e-9)
    assert m.conversion_loss_kwh == pytest.approx(0.7350889359326482, abs=1e-9)


def test_hand_computed_both_self_sufficiencies():
    """baseline 1 − 6/8 = 0.25; battery 1 − 0/8 = 1.00. Standby is 0, so the loads are equal."""
    m, _, _ = _hand_metrics()
    assert m.load_kwh == pytest.approx(8.0, abs=1e-9)
    assert m.self_sufficiency_baseline == pytest.approx(0.25, abs=1e-9)
    assert m.self_sufficiency_battery == pytest.approx(1.0, abs=1e-9)


def test_hand_computed_both_self_consumptions():
    """baseline 1 − 8/10 = 0.20; battery 1 − 0/10 = 1.00. Denominator is Σ PV in both."""
    m, _, _ = _hand_metrics()
    assert m.pv_kwh == pytest.approx(10.0, abs=1e-9)
    assert m.baseline_export_kwh == pytest.approx(8.0, abs=1e-9)
    assert m.battery_export_kwh == pytest.approx(0.0, abs=1e-9)
    assert m.self_consumption_baseline == pytest.approx(0.20, abs=1e-9)
    assert m.self_consumption_battery == pytest.approx(1.0, abs=1e-9)


# ── saved_pct's denominator (§6.11 / §7.1) ────────────────────────────────────────────────────


def test_saved_pct_denominator_is_run_a_not_observed_import():
    """The divisor is the SIMULATED baseline (run A), not `frame.import_obs`.

    §6.11 states it and §7.1 gives the reason: the two come from different information sets, and
    resolution damage makes them differ in reality. This fixture makes them differ by construction:
    the frame carries `import_obs = 12.0` while run A imports 6.0 over the same window (the same
    hand-computed scenario above). The two candidate percentages are therefore:

        against run A (correct)     100 × 6.0 / 6.0  = 100.0 %
        against import_obs (wrong)  100 × 6.0 / 12.0 =  50.0 %

    Both are asserted — the right one to hold, the wrong one to be absent — so an implementation
    that "simplifies" to the observed meter figure fails here with a legible message.
    """
    frame = _frame(_HAND_LOAD, pv=_HAND_PV)
    # Deliberately inconsistent with the reconstructed load: 3.0 kWh/h observed import in every
    # hour, 12.0 kWh over the window, against run A's 6.0. `import_obs` is documented as never
    # read by the battery model (§4.4) and must not be read by the metrics either.
    frame.import_obs = np.full(frame.intervals, 3.0)
    cfg = _cfg(
        has_pv=True, usable_capacity_kwh=10.0, min_soc_pct=0.0, max_soc_pct=100.0,
        initial_soc_pct=0.0, max_charge_kw=5.0, max_discharge_kw=5.0,
        roundtrip_efficiency=0.90, standby_w=0.0,
        charge_policy=ChargePolicy.P1, discharge_policy=DischargePolicy.D1,
        max_import_kw_override=100.0, max_export_kw=100.0,
    )
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    assert float(np.nansum(frame.import_obs)) == pytest.approx(12.0, abs=1e-9)
    assert m.baseline_import_kwh == pytest.approx(6.0, abs=1e-9)
    assert m.saved_pct == pytest.approx(100.0, abs=1e-9)
    assert m.saved_pct != pytest.approx(50.0, abs=1e-6), "saved_pct divided by observed import"


def test_saved_pct_is_none_when_the_baseline_imported_nothing():
    """A baseline that imported ~nothing gives None, not a percentage of noise (DIV_GUARD_EPS)."""
    # PV covers the load exactly in every hour → run A imports 0.
    frame = _frame([1.0, 1.0], pv=[1.0, 1.0])
    cfg = _cfg(has_pv=True, standby_w=0.0, initial_soc_pct=0.0, min_soc_pct=0.0)
    m = energy_metrics(run_all(frame, cfg), frame, cfg)
    assert m.baseline_import_kwh == pytest.approx(0.0, abs=1e-9)
    assert m.saved_pct is None


# ── Self-consumption without PV (§6.11: null, never 0 or 1) ───────────────────────────────────


def test_self_consumption_is_none_without_pv():
    """No PV → both self-consumptions are None. Not 0.0, not 1.0 — §6.11 is explicit.

    0 would assert "none of the generation was self-consumed" and 1 "all of it was"; there was no
    generation, so both are claims the data cannot support. Self-sufficiency, by contrast, stays
    defined — its denominator is the household load.
    """
    frame = _square_wave_frame(2)  # flat 1 kW load, pv all zeros
    cfg = _arbitrage_cfg()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    assert m.pv_kwh == pytest.approx(0.0, abs=1e-12)
    assert m.self_consumption_baseline is None
    assert m.self_consumption_battery is None
    # Not the falsy near-misses a `or 0.0` would produce.
    assert m.self_consumption_baseline is not False and m.self_consumption_baseline != 0.0
    # Self-sufficiency is still computed.
    assert m.self_sufficiency_baseline is not None
    assert m.self_sufficiency_battery is not None


def test_self_sufficiency_is_none_on_both_sides_without_load():
    """§6.11's "null, never 0 or 1", applied SYMMETRICALLY to self-sufficiency.

    A household that consumed nothing over the window is not self-sufficient — it is unmeasurable.
    The baseline side gets that right for free (its denominator IS the load), but the battery
    side's denominator is the STANDBY-INCLUSIVE load, which is nonzero from the standby draw
    alone. So the ratio computes successfully rather than hitting the DIV_GUARD_EPS branch, and
    whatever it returns is presented as a measurement of a household that measured nothing.

    The guard is therefore rejecting a number, not papering over a division error, and the number
    is pinned below so it is clear what was rejected.
    """
    frame = _frame([0.0] * 8)  # no load, no PV
    cfg = _arbitrage_cfg()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    assert m.load_kwh == pytest.approx(0.0, abs=1e-12)
    assert cfg.battery.standby_w > 0, "the fixture must actually have a standby draw"

    assert m.self_sufficiency_baseline is None
    assert m.self_sufficiency_battery is None, "must be null, not a computed ratio"

    # What the ungated ratio would have been. On THIS fixture the battery covers its own standby
    # from the grid, so import equals the standby load exactly and the ratio is a clean 0.0 —
    # "0% self-sufficient" for a household that consumed nothing, which is as unsupportable as
    # 100% and is the reason the guard is on the BARE load rather than on the denominator.
    standby_load = cfg.battery.standby_w / 1000.0 * frame.dt_hours * frame.intervals
    assert standby_load == pytest.approx(0.24, abs=1e-12)
    assert m.battery_import_kwh == pytest.approx(0.24, abs=1e-9)
    assert 1.0 - m.battery_import_kwh / standby_load == pytest.approx(0.0, abs=1e-9)


# ── Self-consumption over the PV series' own window (§2.3a) ───────────────────────────────────


def test_pv_mask_restricts_self_consumption_to_the_pv_window():
    """`pv_mask` puts both self-consumption ratios and `pv_kwh` on the PV series' own coverage.

    §2.3a: "Self-consumption compares PV against export over the PV's window, not the whole window
    — comparing six months of production against two years of export would be meaningless."

    Here the mask genuinely bites, because this frame is assembled straight from arrays and can
    carry export outside the PV window — which the §6.9 runs cannot produce from a real dataset
    (export is `max(0, pv − load)`, hence zero wherever `pv` is zero). The point of the parameter
    is that the ratio is defined over the PV window by construction rather than by coincidence.

    Four hours: PV only in hours 2–3, and a load below PV there so run A exports.

        masked   pv 8.0, A.exp over hours 2–3 = 2 × (4 − 1) = 6.0  → 1 − 6/8 = 0.25
        unmasked pv 8.0 (zero-filled outside), A.exp identical      → the same 0.25 here
    """
    frame = _frame(load=[1.0, 1.0, 1.0, 1.0], pv=[0.0, 0.0, 4.0, 4.0])
    cfg = _arbitrage_cfg()
    runs = run_all(frame, cfg)
    mask = np.array([False, False, True, True])

    masked = energy_metrics(runs, frame, cfg, pv_mask=mask)
    whole = energy_metrics(runs, frame, cfg)

    assert masked.pv_kwh == pytest.approx(8.0, abs=1e-9)
    # `frame.pv` is zero outside the mask, so pv_kwh is unchanged — only the export numerator
    # could have widened, and §6.9 guarantees it does not.
    assert whole.pv_kwh == pytest.approx(8.0, abs=1e-9)
    assert float(np.nansum(runs.a.exp[~mask])) == pytest.approx(0.0, abs=1e-12)
    assert masked.self_consumption_baseline == pytest.approx(whole.self_consumption_baseline)

    # The mask does NOT reach self-sufficiency or any flow total — those are window quantities and
    # restricting them would change what the headline saving measures.
    assert masked.load_kwh == pytest.approx(whole.load_kwh)
    assert masked.baseline_import_kwh == pytest.approx(whole.baseline_import_kwh)
    assert masked.saved_kwh == pytest.approx(whole.saved_kwh)
    assert masked.self_sufficiency_baseline == pytest.approx(whole.self_sufficiency_baseline)

    # A mask that excludes ALL the PV makes the ratio null, not 0 or 1 — the §6.11 discipline
    # survives the new parameter.
    empty = energy_metrics(runs, frame, cfg, pv_mask=np.array([True, True, False, False]))
    assert empty.pv_kwh == pytest.approx(0.0, abs=1e-12)
    assert empty.self_consumption_baseline is None
    assert empty.self_consumption_battery is None


# ── Standby (§6.9: the exact C − B run difference) ────────────────────────────────────────────


def test_standby_is_the_exact_c_minus_b_difference():
    """`standby_kwh == Σ C.imp − Σ B.imp` exactly, not `standby_w × hours`.

    The two agree only when every watt of standby was served by the grid. Here they do NOT: the
    scenario has PV surplus in hours 0–1, so part of the standby draw is served by PV and the
    parameter-derived figure overstates the metered difference. Both are computed and the metric
    is pinned to the run difference.
    """
    frame = _frame(_HAND_LOAD, pv=_HAND_PV)
    cfg = _cfg(
        has_pv=True, usable_capacity_kwh=10.0, min_soc_pct=0.0, max_soc_pct=100.0,
        initial_soc_pct=0.0, max_charge_kw=5.0, max_discharge_kw=5.0,
        roundtrip_efficiency=0.90, standby_w=500.0,  # 0.5 kWh/h, large enough to be visible
        charge_policy=ChargePolicy.P1, discharge_policy=DischargePolicy.D1,
        max_import_kw_override=100.0, max_export_kw=100.0,
    )
    runs = run_all(frame, cfg)
    m = energy_metrics(runs, frame, cfg)

    exact = float(np.nansum(runs.c.imp) - np.nansum(runs.b.imp))
    assert m.standby_kwh == pytest.approx(exact, abs=1e-12)
    # The parameter-derived figure would be 0.5 kWh/h × 4 h = 2.0 kWh. The metered difference is
    # smaller, because the surplus hours absorb part of the draw without touching the meter.
    naive = cfg.battery.standby_w / 1000.0 * frame.dt_hours * frame.intervals
    assert naive == pytest.approx(2.0, abs=1e-12)
    assert m.standby_kwh < naive - 1e-6, "standby must be the run difference, not standby_w × h"


def test_battery_self_sufficiency_denominator_carries_the_full_standby_draw():
    """The self-sufficiency denominator uses `standby_w × h`, NOT the metered `standby_kwh`.

    The two are different quantities and the previous test shows they differ in this scenario.
    Self-sufficiency is `1 − import/load`, so its denominator is the load the household had to
    SERVE — and §6.9 adds the full `standby_kw × dt` to the load in every evaluated interval,
    whatever ended up serving it. The metered figure `standby_kwh` (= `C.imp − B.imp`) counts only
    the part the GRID served, so substituting it shrinks the denominator by exactly the standby
    that PV or the battery covered and reports a self-sufficiency for a household load that is not
    the one run C simulated.

    Here that substitution moves the figure from 0.930 to 0.920. The direction of the error is not
    fixed — it depends on where the import sits relative to the load — which is precisely why the
    test pins the identity rather than an inequality: both candidate denominators are computed and
    the metric must equal the load-side one.
    """
    frame = _frame(_HAND_LOAD, pv=_HAND_PV)
    cfg = _cfg(
        has_pv=True, usable_capacity_kwh=10.0, min_soc_pct=0.0, max_soc_pct=100.0,
        initial_soc_pct=0.0, max_charge_kw=5.0, max_discharge_kw=5.0,
        roundtrip_efficiency=0.90, standby_w=500.0,
        charge_policy=ChargePolicy.P1, discharge_policy=DischargePolicy.D1,
        max_import_kw_override=100.0, max_export_kw=100.0,
    )
    runs = run_all(frame, cfg)
    m = energy_metrics(runs, frame, cfg)

    load_bare = 8.0                       # 1 + 1 + 3 + 3
    load_with_standby = load_bare + 2.0   # 0.5 kWh/h × 4 h — what run C simulated as load
    assert m.load_kwh == pytest.approx(load_bare, abs=1e-9)

    # Here the whole standby draw was served by PV surplus, so the metered figure is smaller than
    # the parameter-derived one and the two denominators genuinely differ (10.0 vs 8.70).
    assert m.standby_kwh == pytest.approx(0.70, abs=1e-9)
    assert load_with_standby == pytest.approx(10.0, abs=1e-12)

    right = 1 - m.battery_import_kwh / load_with_standby
    wrong = 1 - m.battery_import_kwh / (load_bare + m.standby_kwh)
    assert right == pytest.approx(0.93, abs=1e-9)
    assert wrong == pytest.approx(0.9195402298850575, abs=1e-9)
    assert m.self_sufficiency_battery == pytest.approx(right, abs=1e-12)
    assert m.self_sufficiency_battery != pytest.approx(wrong, abs=1e-6)


# ── SoC drift surfacing (§6.11, SOC_DRIFT_WARN_FRAC = 2%) ─────────────────────────────────────


def test_soc_drift_is_significant_above_two_percent_of_the_saving():
    """The hand-worked scenario: drift 1.2649 kWh against a 6.0 kWh saving = 21% > 2% → surfaced."""
    m, _, _ = _hand_metrics()
    assert abs(m.soc_delta_kwh) > SOC_DRIFT_WARN_FRAC * abs(m.saved_kwh)
    assert m.soc_drift_significant is True


def test_soc_drift_is_silent_below_two_percent_of_the_saving():
    """A run that ends where it started reports zero drift and stays silent.

    Twelve hours: six of PV surplus filling the battery, six of deficit emptying it back to the
    starting SoC. Because charge and discharge both pass through η, the battery is deliberately
    given enough deficit hours to return to exactly `soc_min` — the discharge clamp
    `(soc − soc_min) × eta_d` in §6.8 step 4 stops it there, so `soc_end == soc_start == 0` and
    the drift is exactly 0 while the saving is large. `0 > 0.02 × saving` is false, so the flag is
    off. This is the negative half of the threshold test; the positive half is above.
    """
    load = [1.0] * 6 + [5.0] * 6
    pv = [5.0] * 6 + [0.0] * 6
    frame = _frame(load, pv=pv)
    cfg = _cfg(
        has_pv=True, usable_capacity_kwh=100.0, min_soc_pct=0.0, max_soc_pct=100.0,
        initial_soc_pct=0.0, max_charge_kw=10.0, max_discharge_kw=10.0,
        roundtrip_efficiency=0.90, standby_w=0.0,
        charge_policy=ChargePolicy.P1, discharge_policy=DischargePolicy.D1,
        max_import_kw_override=100.0, max_export_kw=100.0,
    )
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    # 6 h × 4 kWh surplus stored at η = 22.768 kWh; the 6 × 5 kWh deficit can draw
    # 22.768 × η = 21.6 kWh AC < 30 kWh of demand, so the battery empties completely.
    assert m.soc_end_kwh == pytest.approx(0.0, abs=1e-9)
    assert m.soc_delta_kwh == pytest.approx(0.0, abs=1e-9)
    assert m.saved_kwh > 1.0
    assert m.soc_drift_significant is False


def test_soc_drift_threshold_boundary():
    """The flag is a strict `>` against 2% of the saving — checked either side of the boundary.

    Rather than engineer a run whose drift lands exactly on 2%, the rule itself is exercised on the
    metrics of a real run by comparing the reported flag with the §6.11 predicate recomputed here
    from the two reported numbers. Any change to the constant or to the direction of the
    comparison breaks this.
    """
    m, _, _ = _hand_metrics()
    expected = abs(m.soc_delta_kwh) > SOC_DRIFT_WARN_FRAC * abs(m.saved_kwh)
    assert m.soc_drift_significant is expected
    assert SOC_DRIFT_WARN_FRAC == 0.02


# ── A negative saving is a legitimate result (§7.2 item 9) ────────────────────────────────────


def test_negative_saving_passes_through_with_its_sign():
    """Fixture 16's no-PV arbitrage run: the saving is negative, and both figures carry the sign.

    The per-day cost is derived in tests/test_simulate.py's fixture-16 docstring:
    standby 0.030 × 24 = 0.72 kWh plus round-trip loss 10 × (1/η − η) = 1.0541 kWh, i.e.
    −1.7741 kWh/day. Over 5 days that is −8.8705 kWh against a 24 kWh/day baseline (120 kWh),
    so saved_pct = 100 × −8.8705 / 120 = −7.392 %.
    """
    days = 5
    frame = _square_wave_frame(days)
    cfg = _arbitrage_cfg()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    per_day = -(0.030 * 24 + 10.0 * (1.0 / _ETA - _ETA))
    assert per_day == pytest.approx(-1.7740925533894583, abs=1e-9)
    assert m.saved_kwh == pytest.approx(days * per_day, abs=1e-6)
    assert m.baseline_import_kwh == pytest.approx(days * 24.0, abs=1e-6)
    assert m.saved_pct == pytest.approx(100 * days * per_day / (days * 24.0), abs=1e-6)
    assert m.saved_pct == pytest.approx(-7.392052305789409, abs=1e-6)
    assert m.saved_pct < 0


def test_conversion_loss_closes_on_the_arbitrage_fixture():
    """The §6.11 identity on a second, independently derived scenario.

    Fixture 16 cycles a 10 kWh battery exactly once per day and ends each day empty, so the
    conversion loss is exactly `days × 10 × (1/η − η)` — the round-trip loss on 10 kWh of storage,
    derived from the §6.8 efficiency convention rather than from the run.
    """
    days = 5
    frame = _square_wave_frame(days)
    cfg = _arbitrage_cfg()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    expected = days * 10.0 * (1.0 / _ETA - _ETA)
    assert expected == pytest.approx(5.270462766947292, abs=1e-9)
    assert m.conversion_loss_kwh == pytest.approx(expected, abs=1e-6)
    # And the identity's own form, so a term dropped from the implementation is caught directly.
    assert m.conversion_loss_kwh == pytest.approx(
        m.charge_ac_kwh - m.discharge_ac_kwh - (m.soc_end_kwh - m.soc_start_kwh), abs=1e-12
    )


# ── Cycles per day and window length ──────────────────────────────────────────────────────────


def test_cycles_per_day_divides_by_the_window_length():
    """Fixture 16 does exactly one full cycle per day, so `cycles_per_day` is 1.0 over 5 days.

    The span comes from the GRID (120 hourly intervals = 5 days), not from `frame.window`, which
    the test helper leaves unpopulated because the §6.6–§6.9 core never reads it.
    """
    days = 5
    frame = _square_wave_frame(days)
    cfg = _arbitrage_cfg()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    assert m.window_days == pytest.approx(5.0, abs=1e-9)
    assert m.efc == pytest.approx(5.0, abs=1e-6)
    assert m.cycles_per_day == pytest.approx(1.0, abs=1e-6)


def test_gap_intervals_are_excluded_from_every_sum():
    """A NaN interval is excluded from the flow sums AND from the frame sums behind the ratios.

    §7.3 check 3 excludes gaps from sums. The risk this pins is a mismatch: `nansum(frame.load)`
    would include an interval whose load is a number but whose PV is NaN — an interval run C
    skipped entirely — putting the ratio's numerator and denominator on different interval sets.
    Here hour 1's PV is NaN while its load is 2.0; the load total must be 2.0 — hours 0 and 2 at
    1.0 each — and NOT 4.0, which is what summing `frame.load` over all three intervals would give.
    """
    frame = _frame([1.0, 2.0, 1.0], pv=[0.0, math.nan, 0.0])
    cfg = _cfg(has_pv=True, standby_w=0.0, initial_soc_pct=0.0, min_soc_pct=0.0)
    runs = run_all(frame, cfg)
    m = energy_metrics(runs, frame, cfg)

    assert bool(runs.c.gap[1]) is True
    assert float(np.nansum(frame.load)) == pytest.approx(4.0, abs=1e-9)  # the wrong answer
    assert m.load_kwh == pytest.approx(2.0, abs=1e-9)
    assert m.pv_kwh == pytest.approx(0.0, abs=1e-9)
    # Baseline import over the two good hours only.
    assert m.baseline_import_kwh == pytest.approx(2.0, abs=1e-9)


def test_metrics_never_modify_the_frame_arrays():
    """The frame's arrays are shared with app/summary_view.py; nothing here may write to them."""
    frame = _frame(_HAND_LOAD, pv=_HAND_PV)
    cfg = _cfg(has_pv=True, standby_w=30.0, initial_soc_pct=0.0, min_soc_pct=0.0)
    before = {
        "load": frame.load.copy(), "pv": frame.pv.copy(), "spot": frame.spot.copy(),
        "import_obs": frame.import_obs.copy(), "export_obs": frame.export_obs.copy(),
    }
    energy_metrics(run_all(frame, cfg), frame, cfg)
    for name, original in before.items():
        np.testing.assert_array_equal(getattr(frame, name), original, err_msg=name)
