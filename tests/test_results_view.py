"""Unit tests for the panel-③ results view-model and window resolver (specs §2.4, §7.4).

Two units under test, both from app/results_view:

  * results_from(dataset, window) — the ENERGY SAVINGS view-model over a window, computed from a
    REAL run of the §6.6–§6.9 core under appendix-A defaults. Covers the headline figures, the
    omit-don't-zero discipline (no self-consumption row without PV), the negative-saving
    presentation (§7.2 item 9), the §2.3a self-sufficiency display clamp, and the no-grid → None
    guard.
  * resolve_window(dataset, *, period/start/end) — preset anchoring to the END of data coverage
    (§7.4) and clamping to coverage.

**These assertions were hand-derived, not read off the view.** The scenarios below carry NO spot
price, which makes `frame.spot` all-NaN; §6.6/§6.7's band comparisons are then all False (IEEE),
so the default P3/D1 configuration reduces to D1 alone — the battery serves the household deficit
from its starting SoC and never grid-charges. That makes the whole run analytically closed, and
each test's comment carries the derivation.

Synthetic SeriesFrames are built in-process (no browser, no real dataset), reusing the frame/dataset
helpers from tests/test_data_summary.py so the two suites share one construction of a LoadedDataset.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.results_view import PERIOD_DAYS, resolve_window, results_from
from tests.test_data_summary import (
    HOURS,
    _WIN_END,
    _WIN_START,
    _dataset,
    _energy,
)

# sqrt(0.9) — the §6.8 geometric efficiency split at the appendix-A default round trip. Written as
# a literal for the same reason tests/test_simulate.py does: an expectation phrased with the
# implementation's own formula passes for any implementation using that formula, right or wrong.
_ETA = 0.9486832980505138


# ── results_from ─────────────────────────────────────────────────────────────────────────────


def test_results_reports_a_real_simulated_saving():
    """The battery MOVES energy now, and every figure is hand-derivable.

    Setup: import 2 kWh/h, export 0, no PV, no price, over 24 h. Reconstructed load = 48 kWh.
    The default battery is 10 kWh usable, 10–100% SoC, initial 50%, 30 W standby, P3/D1.

    With no price series `spot` is all NaN, so P3's grid-charge band never opens and the battery
    only discharges to serve the deficit (D1). It therefore drains once, from its initial 5.0 kWh
    to the 1.0 kWh floor, and nothing ever recharges it:

        withdrawn (storage side)   5.0 − 1.0                      = 4.0000 kWh
        delivered  (AC side)       4.0 × sqrt(0.9)                = 3.7947 kWh
        standby                    0.030 kW × 24 h                = 0.7200 kWh
        saved_kwh                  3.7947 − 0.7200                = 3.0747 kWh
        saved_pct                  100 × 3.0747 / 48              = 6.4057 %
        efc                        4.0 / 10.0                     = 0.40
        conversion loss            charge 0 − discharge 3.7947 − (1.0 − 5.0) = 0.2053 kWh
    """
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r is not None

    delivered = 4.0 * _ETA
    saved = delivered - 0.720
    assert saved == pytest.approx(3.0747331922020606, abs=1e-9)

    saved_tile = next(k for k in r["kpis"] if k["title"] == "GRID IMPORT SAVED")
    assert saved_tile["value"] == "3"  # round(3.0747)
    assert saved_tile["unit"] == "kWh"
    assert saved_tile["delta"] == "+6.4 %"  # 100 × 3.0747 / 48

    cycles = next(k for k in r["kpis"] if k["title"] == "EQUIVALENT FULL CYCLES")
    assert cycles["value"] == "0"          # 0.40 EFC rounds to 0 whole cycles
    assert cycles["delta"] == "0.40 / day"  # 0.40 over a 1-day window
    assert cycles["extra"] == "4 kWh throughput"  # round(3.7947) AC delivered

    by_label = {row["label"]: row["value"] for row in r["energy_breakdown"]}
    assert by_label["Grid import, no battery"] == "48 kWh"
    assert by_label["Grid import, with battery"] == "45 kWh"  # round(48 − 3.0747)
    assert by_label["Grid import avoided"] == "3 kWh"
    assert by_label["Charged into the battery"] == "0 kWh"    # the band never opened
    assert by_label["Discharged from the battery"] == "4 kWh"
    assert by_label["Conversion losses"] == "0 kWh"           # round(0.2053)
    assert by_label["Standby consumption"] == "1 kWh"         # round(0.72)
    # No benchmark key (§6.12 DP is Phase 5).
    assert "benchmark" not in r


def test_results_self_sufficiency_shows_baseline_and_battery_apart():
    """The two halves now DIFFER — the battery displaces import — and both are derived.

    Setup: import 1 kWh/h, PV 3 kWh/h, export 0 → load = 1 + 3 = 4 kWh/h, 96 kWh over 24 h,
    baseline import 24 kWh. Baseline self-sufficiency = 1 − 24/96 = 0.75 → "75%".

    The battery discharges its 5.0 → 1.0 kWh window as above (no price, so no grid charging; the
    PV surplus is 0 in every hour because load ≥ pv, so P3 stores nothing either), delivering
    3.7947 kWh AC, while standby adds 0.72 kWh to the load:

        battery import   24 + 0.72 − 3.7947 = 20.9253 kWh
        battery load     96 + 0.72          = 96.72 kWh
        self-sufficiency 1 − 20.9253/96.72  = 0.7837  → "78%"
    """
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    batt_import = 24 + 0.720 - 4.0 * _ETA
    batt_ss = 1 - batt_import / (96 + 0.720)
    assert batt_ss == pytest.approx(0.7837, abs=1e-4)

    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")
    assert ss["value"] == "75% → 78%"
    assert ss["delta"] == "+3 pp"


# ── §7.1: one information set on both sides of every comparison ──────────────────────────────
#
# The scenarios above have export = 0 in every interval, so the meter's import and run A's
# simulated import coincide and a view that mixed the two would still pass. The fixture below
# breaks that tie deliberately: import 2 kWh/h AND export 1 kWh/h in the SAME hour is the §7.1
# overlap case — the flow reversed within the interval, the reconstruction nets it out, and the
# two information sets come apart by a factor of two.
#
#   measured   imported 48 kWh, exported 24 kWh, reconstructed load = 2 − 1 + 3 = 4 kWh/h = 96 kWh
#              measured self-sufficiency  1 − 48/96 = 0.50 → "50%"
#   simulated  run A re-simulates the reconstructed load on the grid: load 4, PV 3, so it imports
#              1 kWh/h = 24 kWh and exports nothing at all.
#              run-A self-sufficiency     1 − 24/96 = 0.75 → "75%"
#
# Every assertion below pins BOTH candidates and asserts the right one, so a regression to the
# observed figure fails loudly rather than shifting a number nobody re-derives.

def _overlap_dataset():
    """import 2 / export 1 / PV 3 kWh per hour — measured and simulated import differ 48 vs 24."""
    return _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 1.0),
        _energy("solar_production", 3.0),
    ])


def test_self_sufficiency_tile_uses_the_simulated_baseline_not_the_meter():
    """§7.1: the tile's left half is run A, never `1 − imp_obs/load`.

    "Use the *simulated* baseline (run A), so that both scenarios see identical information. […]
    Using observed import as the denominator while computing the battery case from reconstructed
    data would mix two information sets and produce a number that is wrong in a direction nobody
    can reason about."

    The bias is one-sided: the meter's import is always ≥ run A's (the overlap energy is real
    import that the reconstruction nets away), so a measured left half understates the baseline
    and flatters the battery. Here it would show 50% → 78% (+28 pp) instead of 75% → 78% (+3 pp).
    """
    r = results_from(_overlap_dataset(), (_WIN_START, _WIN_END))
    assert r is not None
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")

    # Both candidates, derived independently of the view.
    measured_ss = 1 - 48.0 / 96.0      # the WRONG one: the meter's import over the load
    simulated_ss = 1 - 24.0 / 96.0     # the RIGHT one: run A's import over the same load
    assert measured_ss == pytest.approx(0.50) and simulated_ss == pytest.approx(0.75)

    assert ss["value"] == "75% → 78%", "the left half must be run A's simulated baseline"
    assert ss["value"] != "50% → 78%", "the left half must NOT be the measured self-sufficiency"
    assert ss["delta"] == "+3 pp"
    assert ss["delta"] != "+28 pp", "the measured baseline inflates the delta by 25 pp here"

    # And the metrics layer really does offer both — the view is choosing, not falling back.
    from app.domain.metrics import energy_metrics
    from app.domain.simconfig import SimulationConfig
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    frame = simulation_frame(_overlap_dataset(), (_WIN_START, _WIN_END))
    cfg = SimulationConfig()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)
    assert m.self_sufficiency_baseline == pytest.approx(0.75)
    assert m.baseline_import_kwh == pytest.approx(24.0)
    # The measured import is on the frame and is NOT what the baseline used.
    assert float(np.nansum(frame.import_obs)) == pytest.approx(48.0)


def test_panel_states_the_resolution_loss_between_meter_and_simulated_baseline():
    """§7.1: "Report the observed import alongside it, with the difference labelled as resolution
    loss."

    Two grid-import numbers appear on this one panel — the data-glance band's measured 48 kWh and
    the Energy savings breakdown's simulated 24 kWh — and without the caveat the user is left to
    notice the contradiction unaided. The caveat names the gap in kWh and says which figure the
    savings are computed against.
    """
    r = results_from(_overlap_dataset(), (_WIN_START, _WIN_END))
    assert r is not None

    # The two figures the caveat reconciles are both actually on the panel.
    assert r["data_summary"]["grid"]["imported"] == "48 kWh"
    by_label = {row["label"]: row["value"] for row in r["energy_breakdown"]}
    assert by_label["Grid import, no battery"] == "24 kWh"

    note = next((c for c in r["caveats"] if "no-battery baseline" in c), None)
    assert note is not None, "the measured/simulated import gap must be explained"
    assert "48 kWh" in note and "24 kWh" in note, "both figures must be named"
    assert "24 kWh" in note  # the difference, which here equals the baseline

    # It is NOT raised when there is nothing to explain: with export 0 in every interval the two
    # figures coincide and a caveat about a difference the reader cannot see would be noise.
    clean = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r2 = results_from(clean, (_WIN_START, _WIN_END))
    assert not any("no-battery baseline" in c for c in r2["caveats"])


def test_self_consumption_compares_one_information_set_on_both_sides():
    """§7.1 + §2.3a: both halves of the self-consumption row are simulated, over the PV window.

    The row used to take its LEFT half from the meter (`1 − Σ exp_obs / Σ pv` over the PV
    coverage) and its right half from run C. That is the §7.1 mixing defect again, on the export
    side: the meter's export includes energy that flowed out within an interval that also imported,
    which the reconstruction nets away, so the measured ratio sits below the simulated one and the
    apparent jump is inflated by the difference.

    Both halves now come from `EnergyMetrics`.
    """
    r = results_from(_overlap_dataset(), (_WIN_START, _WIN_END))
    assert r is not None
    row = next(s for s in r["secondary"] if s["label"] == "Self-consumption ratio")

    # Measured: 24 kWh exported against 72 kWh produced → 1 − 24/72 = 0.667 → "67%".
    # Simulated: run A exports nothing at all (load 4 ≥ PV 3 in every hour) → 1 − 0/72 = 1 → "100%".
    assert r["data_summary"]["grid"]["exported"] == "24 kWh"
    assert row["value"] == "100% → 100%", "both halves are run figures over the same window"
    assert row["value"] != "67% → 100%", "the left half must not be the measured export ratio"


def test_self_consumption_uses_the_pv_series_own_coverage_window():
    """§2.3a: "comparing six months of production against two years of export would be meaningless".

    `results_from` hands `energy_metrics` a mask of the intervals the PV SERIES covers, so both
    self-consumption ratios and `pv_kwh` are measured over that one window.

    **On the simulated ratios the mask is currently a no-op, and that is a structural fact worth
    pinning rather than a reason to drop it.** §6.9 computes export as `max(0, pv − load)` with a
    non-negative (§6.3-clamped) load, so a run cannot export in an interval where `pv` is zero —
    and `frame.pv` is zero-filled outside the PV series' coverage (§4.4). Simulated export is
    therefore already confined to the PV window by construction. The mask makes that agreement
    explicit instead of incidental: it holds because of how §6.9 defines export, and if a later
    increment gives a run another way to export (grid arbitrage under D3, say), the ratio stays on
    the PV window rather than silently acquiring the pre-PV months.

    Setup (48 h window, PV only in the last 24 h, PV exceeding load so the runs really do export).
    """
    from app.domain.metrics import energy_metrics
    from app.domain.reconcile import reconcile_grid
    from app.domain.simconfig import SimulationConfig
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all
    from app.results_view import _pv_coverage_mask
    from tests.test_data_summary import _dataset_2day, _energy_subwindow

    window = (_WIN_START, datetime(2026, 1, 3, tzinfo=timezone.utc))
    ds = _dataset_2day([
        _energy("grid_import_t1", 0.5, n=48),
        _energy("grid_export_t1", 1.0, n=48),   # export in BOTH halves of the window
        _energy_subwindow("solar_production", 4.0, start_hour=24, n=24),
    ])
    rec = reconcile_grid(ds, window)
    mask = _pv_coverage_mask(ds, rec)
    assert mask is not None and int(mask.sum()) == 24, "the PV window is the last 24 of 48 hours"

    frame = simulation_frame(ds, window)
    cfg = SimulationConfig()
    runs = run_all(frame, cfg)
    masked = energy_metrics(runs, frame, cfg, pv_mask=mask)
    whole = energy_metrics(runs, frame, cfg)

    # The runs DO export here, so the ratios are not the degenerate 1.0 that would make the
    # comparison below vacuous.
    assert masked.self_consumption_baseline < 0.999
    assert masked.pv_kwh == pytest.approx(96.0)  # 24 h × 4 kWh, all inside the PV window

    # Masked and unmasked agree — because run export is structurally zero outside PV coverage.
    assert masked.self_consumption_baseline == pytest.approx(whole.self_consumption_baseline)
    assert masked.self_consumption_battery == pytest.approx(whole.self_consumption_battery)
    # The reason, asserted directly rather than inferred: no run exported before the panels.
    assert float(np.nansum(runs.a.exp[~mask])) == pytest.approx(0.0)
    assert float(np.nansum(runs.c.exp[~mask])) == pytest.approx(0.0)
    # The METER did export there, which is why the measured ratio needed the mask and still does.
    assert float(rec.exp[~mask].sum()) == pytest.approx(24.0)

    # The view shows the masked pair, both halves from the same window.
    r = results_from(ds, window)
    row = next(s for s in r["secondary"] if s["label"] == "Self-consumption ratio")
    from app.results_view import _fmt_pct
    assert row["value"] == (
        f"{_fmt_pct(max(0.0, masked.self_consumption_baseline))} → "
        f"{_fmt_pct(max(0.0, masked.self_consumption_battery))}"
    )


def test_zero_load_household_reports_neither_side_of_self_sufficiency():
    """§6.11's "null, never 0 or 1", applied SYMMETRICALLY.

    With no consumption at all the baseline self-sufficiency is correctly None (its denominator is
    the load). The battery side's denominator is NOT zero — §6.9 adds the standby draw to the load
    in every interval — so the ratio computes rather than hitting the divide guard, and whatever it
    returns is shown as a measurement of a household that measured nothing. Both sides are now None
    together, so the tile shows absence on both halves and no delta.

    The exact rejected value depends on where the standby draw was served from and is pinned in
    tests/test_metrics.py; what matters here is that the tile shows neither half.
    """
    from app.domain.metrics import energy_metrics
    from app.domain.simconfig import SimulationConfig
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    ds = _dataset([_energy("grid_import_t1", 0.0), _energy("grid_export_t1", 0.0)])
    window = (_WIN_START, _WIN_END)
    frame = simulation_frame(ds, window)
    cfg = SimulationConfig()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)

    assert m.load_kwh == pytest.approx(0.0), "the fixture really has no household load"
    assert cfg.battery.standby_w > 0, "the battery-side denominator is nonzero from standby alone"
    assert m.self_sufficiency_baseline is None
    assert m.self_sufficiency_battery is None, "must be null, not a computed ratio"

    r = results_from(ds, window)
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")
    assert ss["value"] == "n/a → n/a"
    assert ss["value"] != "n/a → 100%", "a household with no load is not 100% self-sufficient"
    assert ss["value"] != "n/a → 0%", "nor 0% — absence, not a measurement"
    assert ss["delta"] == "", "no delta between two absences"


def test_kwh_and_signed_kwh_use_the_same_minus_glyph():
    """Both formatters render a negative with U+2212, never the ASCII hyphen.

    `_fmt_kwh`'s callers all pass non-negative quantities today, so this is latent rather than
    live — but Python's `format` emits "-" and `_fmt_signed_kwh` emits "−", and two different
    minus glyphs on one panel is the kind of inconsistency that survives until someone screenshots
    it.
    """
    from app.results_view import _fmt_kwh, _fmt_signed_kwh

    assert _fmt_kwh(-1234.0) == "−1,234 kWh"
    assert "-" not in _fmt_kwh(-1234.0), "ASCII hyphen must not appear"
    assert _fmt_kwh(-1234.0)[0] == _fmt_signed_kwh(-1234.0)[0]
    assert _fmt_kwh(1234.0) == "1,234 kWh"  # unchanged on the normal path


def test_no_caveat_contains_a_literal_percent_sign():
    """Regression: a literal "%" in a caveat is EATEN by the template's gettext call.

    `_panel_results.html` renders every caveat through `_()`, and app/i18n.install_for installs
    the Jinja i18n extension with `newstyle=True`, which applies %-formatting to the translated
    result. A caveat reading "90% round-trip" therefore renders as "90{}ound-trip" — "% r" is
    parsed as a conversion specifier — and "shown as 0%." loses the "%." the same way. The
    corruption is silent: no exception, just mangled user-facing text.

    Escaping as "%%" would work but pushes the escape onto every translator of every catalog, so
    the rule is simply that caveats are worded without the sign. This test enforces it across the
    scenarios that raise every caveat branch, so a future caveat cannot reintroduce it.
    """
    from jinja2 import Environment

    from app import i18n
    from tests.test_data_summary import _price

    scenarios = [
        # A plain run: the default-battery note (and the price-granularity note when priced).
        [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)],
        # Negative saving + SoC drift + self-sufficiency clamp, all at once.
        [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0),
         _price("price_spot", 0.02)],
        # With PV, so the reconstruction and self-consumption paths are exercised too.
        [_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 0.0),
         _energy("solar_production", 3.0)],
        # Simultaneous import and export (§7.1 overlap), which is the ONLY way to raise the
        # measured-vs-simulated resolution-loss caveat — every scenario above exports nothing, so
        # the two import figures coincide and that caveat stays silent.
        [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 1.0),
         _energy("solar_production", 3.0)],
    ]
    env = Environment(extensions=["jinja2.ext.i18n"])
    i18n.install_for(env, "en")
    tmpl = env.from_string("{{ _(c) }}")

    seen = 0
    branches: set[str] = set()
    for frames in scenarios:
        r = results_from(_dataset(frames), (_WIN_START, _WIN_END))
        for c in r["caveats"]:
            seen += 1
            branches.add(c[:40])
            assert "%" not in c, f"literal % in a caveat will be eaten by gettext: {c!r}"
            # And the round trip through the template is lossless.
            assert tmpl.render(c=c) == c
    assert seen >= 5, "the scenarios above should raise several caveats between them"
    # The newest caveat is genuinely among them — the guard is only worth what it covers, and this
    # one is reachable from exactly one of the scenarios above.
    assert any("no-battery baseline" in b or b.startswith("Your meter recorded") for b in branches), \
        "the resolution-loss caveat must be exercised by this guard"


def test_results_no_pv_omits_self_consumption_row():
    # No PV → the self-consumption row (denominator is PV) is omitted (§2.4 omit-don't-zero).
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    labels = [row["label"] for row in r["secondary"]]
    assert "Self-consumption ratio" not in labels
    # Grid export IS shown (measured figure, equal on both sides).
    assert "Grid export" in labels
    # The "intervals battery full/empty" row is omitted this increment (no battery).
    assert "Intervals battery was full / empty" not in labels


def test_results_pv_shows_self_consumption_equal_halves():
    # With usable PV the self-consumption row appears, baseline == battery: "X% → X%".
    # PV 3 kWh/h, export 0 → self-consumption = 1 − 0/72 = 100%.
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    sc = next(row for row in r["secondary"] if row["label"] == "Self-consumption ratio")
    assert sc["value"] == "100% → 100%"


def test_results_no_longer_claims_the_battery_is_unconfigured():
    """The zero-battery caveat is GONE — the battery now runs — and is replaced by the honest one.

    What replaces it is narrower and true: the parameters are appendix-A defaults because panel ②
    is not wired to a config object yet (Phase 6), so the figures are for a default battery rather
    than a chosen one. That distinction has to stay visible; a computed number whose parameter set
    is unstated is exactly the kind of figure that propagates unchallenged.
    """
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert not any("No battery is configured" in c for c in r["caveats"])
    assert not any("every savings figure is zero" in c for c in r["caveats"])
    assert any("default battery" in c and "10 kWh usable" in c for c in r["caveats"])


def test_results_reports_a_negative_saving_honestly():
    """§7.2 item 9: a battery that costs kWh is correct output and must read as a cost.

    Setup: import 2 kWh/h, export 0, NO PV, and a flat spot price of 0.02 €/kWh — inside the
    default charge band [−0.050, 0.040] and below the default discharge band [0.180, 9.999]. So
    P3 grid-charges whenever the band is open, and D2 never fires (D1 serves the deficit, but the
    battery is charging, not discharging: §6.7's netting resolves the two and charge wins).

    The battery fills from its initial 5.0 kWh to its 10.0 kWh ceiling and stays there:

        stored                 10.0 − 5.0                          = 5.0000 kWh
        AC drawn to store it   5.0 / sqrt(0.9)                     = 5.2705 kWh
        standby                0.030 kW × 24 h                     = 0.7200 kWh
        discharged             nothing — the price never entered [C, D]  = 0
        saved_kwh              −(5.2705 + 0.7200)                  = −5.9905 kWh
        saved_pct              100 × −5.9905 / 48                  = −12.48 %
        conversion loss        5.2705 − 0 − 5.0                    = 0.2705 kWh

    Three things must hold in the presentation: the tile carries the minus sign, the breakdown row
    is relabelled so "avoided" never captions a cost, and a caveat explains that an energy-only
    run does not price the spread the battery exists to capture (§7.2 items 9 and 10).
    """
    from tests.test_data_summary import _price

    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", 0.02),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r is not None

    charged_ac = 5.0 / _ETA
    saved = -(charged_ac + 0.720)
    assert saved == pytest.approx(-5.990462766947296, abs=1e-9)
    assert 100 * saved / 48 == pytest.approx(-12.48, abs=1e-2)

    saved_tile = next(k for k in r["kpis"] if k["title"] == "GRID IMPORT SAVED")
    assert saved_tile["value"] == "−6"      # round(5.9905), signed
    assert saved_tile["delta"] == "−12.5 %"  # the percentage keeps the sign too

    labels = [row["label"] for row in r["energy_breakdown"]]
    assert "Grid import avoided" not in labels, "a cost must not be captioned 'avoided'"
    assert "Extra grid import" in labels
    by_label = {row["label"]: row["value"] for row in r["energy_breakdown"]}
    assert by_label["Extra grid import"] == "6 kWh"   # the magnitude; the label has the direction
    assert by_label["Grid import, no battery"] == "48 kWh"
    assert by_label["Grid import, with battery"] == "54 kWh"  # round(48 + 5.9905)
    assert by_label["Charged into the battery"] == "5 kWh"    # round(5.2705)
    assert by_label["Discharged from the battery"] == "0 kWh"

    assert any("MORE from the grid" in c for c in r["caveats"])
    assert any("worth buying" in c for c in r["caveats"])


def test_soc_drift_caveat_fires_when_the_battery_ends_more_charged():
    """§6.11: drift is surfaced when it exceeds 2% of the saving. Here it is 5.0 kWh against 5.99.

    Same scenario as the negative-saving test: the battery fills and never empties, so it ends the
    window 5.0 kWh more charged than it started. That residual is 83% of the (negative) saving, so
    the caveat fires. Its counterpart — a run whose drift stays under the threshold — is pinned in
    tests/test_metrics.py, where the threshold itself is exercised on both sides.
    """
    from tests.test_data_summary import _price

    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", 0.02),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert any("more charged than it started" in c for c in r["caveats"])


def test_negative_saving_never_renders_a_signed_zero():
    """A saving that rounds to zero prints "0 kWh" / "0.0 %", never "−0" — that reads as a bug."""
    from app.results_view import _fmt_signed_kwh, _fmt_signed_pct

    assert _fmt_signed_kwh(-0.4) == "0 kWh"
    assert _fmt_signed_kwh(-1.6) == "−2 kWh"
    assert _fmt_signed_kwh(1.6) == "2 kWh"
    assert _fmt_signed_pct(-0.04) == "0.0 %"
    assert _fmt_signed_pct(-34.21) == "−34.2 %"
    assert _fmt_signed_pct(8.75) == "+8.8 %"


def test_self_sufficiency_display_clamp_fires_with_its_caveat():
    """§2.3a: a negative self-sufficiency is displayed as 0% and says so.

    The metric `1 − import/load` goes below zero when grid import exceeds the reconstructed load —
    §2.3a's case is a battery ending the window more charged than it started, which is exactly the
    grid-charging scenario above: the simulated battery imports 5.2705 kWh to fill itself and
    never gives it back within the window, so

        battery import   48 + 5.2705 + 0.72   = 53.99 kWh
        battery load     48 + 0.72            = 48.72 kWh
        self_sufficiency 1 − 53.99/48.72      = −0.108   → displayed 0%, and flagged

    The metric itself is NOT clamped (app/domain/metrics.py returns −0.108); only the display is,
    which is why the caveat is what tells the user the figure was floored.
    """
    from app.results_view import _clamped_pct
    from tests.test_data_summary import _price

    # The clamp itself: negative → 0% AND flagged; non-negative → passed through, not flagged;
    # None (not computable) → absence, which is NOT a clamp.
    assert _clamped_pct(-0.12) == ("0%", True)
    assert _clamped_pct(0.0) == ("0%", False)
    assert _clamped_pct(0.52) == ("52%", False)
    assert _clamped_pct(None) == ("n/a", False)

    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", 0.02),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r is not None
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")
    assert ss["value"].endswith("→ 0%"), "a negative self-sufficiency must display as 0%"
    assert any("shown as zero" in c for c in r["caveats"])

    # The underlying metric is untouched — the clamp is presentation only.
    from app.domain.metrics import energy_metrics
    from app.domain.simconfig import SimulationConfig
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    cfg = SimulationConfig()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)
    assert m.self_sufficiency_battery == pytest.approx(-0.108, abs=1e-3)


def test_results_period_line_and_chart_are_real():
    # The coverage line reflects the effective window, hourly grid, and interval count; the chart is
    # a real monthly import series (one bucket here — a single January).
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r["period"] == "2026-01-01 → 2026-01-02 · simulated hourly · 24 intervals"
    assert r["chart"]["months"] == ["Jan"]
    assert r["chart"]["values"] == [48]  # 2 kWh/h × 24 h


def test_results_short_window_disables_annualisation():
    # A 24 h window is well under min_annualisation_days (90), so the short-window flag + message
    # are set for the §2.4 info box.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r["annualisation_disabled"] is True
    assert "disabled" in r["annualisation_message"]


def test_results_returns_none_without_grid():
    # No covering grid meter → reconcile_grid returns None → results_from returns None (caller falls
    # back to the empty state).
    from tests.test_data_summary import _price
    ds = _dataset([_price("price_spot", 0.15)])
    assert results_from(ds, (_WIN_START, _WIN_END)) is None


def test_results_includes_window_clamped_data_summary():
    # The panel-③ view-model now carries the "Your data at a glance" band (results.data_summary),
    # computed over the SELECTED window with the spot price clamped to it too. It must match
    # data_summary_from(ds, window=rec_window, clamp_price_to_window=True) exactly.
    from app.domain.reconcile import reconcile_grid
    from app.summary_view import data_summary_from
    from tests.test_data_summary import _price
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", 0.15),
    ])
    window = (_WIN_START, _WIN_END)
    r = results_from(ds, window)
    assert "data_summary" in r
    # Grid totals over the window (import 2 kWh/h × 24 = 48 kWh).
    assert r["data_summary"]["grid"] == {"imported": "48 kWh", "exported": "0 kWh"}
    # Window-clamped, price included: identical to the direct call over the effective window.
    rec = reconcile_grid(ds, window)
    expected = data_summary_from(ds, window=rec.window, clamp_price_to_window=True)
    assert r["data_summary"] == expected


def test_results_data_summary_window_clamped_totals():
    # A sub-window restricts the band totals: meters span 48 h at 2 kWh/h (96 kWh full), a 24 h
    # window through results_from must show 48 kWh in the band — proof it clamps to the window.
    from tests.test_data_summary import _dataset_2day, _energy as _energy2
    ds = _dataset_2day([
        _energy2("grid_import_t1", 2.0, n=48),
        _energy2("grid_export_t1", 0.0, n=48),
    ])
    sub = (_WIN_START, _WIN_END)  # first 24 h of the 48 h coverage
    r = results_from(ds, sub)
    assert r["data_summary"]["grid"]["imported"] == "48 kWh"


# ── resolve_window ───────────────────────────────────────────────────────────────────────────
#
# A wider synthetic dataset so presets have room: 400 hourly intervals is too few for day-presets,
# so build a multi-day hourly meter and drive coverage from it.


_COV_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _long_dataset(days: int):
    """An hourly grid dataset whose coverage spans exactly `days` days from _COV_START.

    Coverage end = last interval start + 1 h = _COV_START + `days` days (n = days*24 hourly
    intervals). The dataset `window` is deliberately wider (a full non-leap year) so resolve_window
    must derive the real coverage from the frames, not from the advertised window.
    """
    from app.dataset import LoadedDataset
    from app.domain.frames import QUALITY_DTYPE, SeriesFrame

    n = days * 24
    idx = (np.arange(n).astype("timedelta64[s]") * 3600
           + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    imp = SeriesFrame("grid_import_t1", "energy", 3600, idx, np.full(n, 1.0),
                      np.zeros(n, dtype=QUALITY_DTYPE))
    exp = SeriesFrame("grid_export_t1", "energy", 3600, idx, np.zeros(n),
                      np.zeros(n, dtype=QUALITY_DTYPE))
    return LoadedDataset(
        id=1, source_type="test",
        window=(_COV_START, datetime(2027, 1, 1, tzinfo=timezone.utc)),
        fetched_at=_COV_START,
        frames=[imp, exp], warnings=[],
        series_sources={"grid_import_t1": "test", "grid_export_t1": "test"},
    )


def test_resolve_window_preset_anchors_to_coverage_end():
    # Coverage spans 200 days from 2026-01-01. last_30_days ends at the coverage END (last data
    # timestamp), NOT now(), and starts 30 days before it.
    ds = _long_dataset(200)
    cov_end = _COV_START + timedelta(days=200)
    start, end = resolve_window(ds, period="last_30_days")
    assert end == cov_end
    assert (end - start).days == 30


def test_resolve_window_preset_clamps_to_coverage_start():
    # Coverage is only 40 days; last_1_year (365) would reach before the data begins, so the start
    # clamps to coverage start — never pad with zeros (§7.4).
    ds = _long_dataset(40)
    cov_end = _COV_START + timedelta(days=40)
    start, end = resolve_window(ds, period="last_1_year")
    assert start == _COV_START
    assert end == cov_end


def test_resolve_window_default_is_last_1_year():
    # No args → the DEFAULT_PERIOD (last_1_year) preset. With 200 days of coverage it clamps to the
    # full coverage (365 > 200).
    ds = _long_dataset(200)
    start_default, end_default = resolve_window(ds)
    start_year, end_year = resolve_window(ds, period="last_1_year")
    assert (start_default, end_default) == (start_year, end_year)


def test_resolve_window_explicit_range_clamps():
    # An explicit range partly outside coverage clamps both ends into coverage.
    ds = _long_dataset(100)
    cov_end = _COV_START + timedelta(days=100)
    # Ask for a range starting before coverage and ending after it → clamps to full coverage.
    start, end = resolve_window(
        ds,
        start=_COV_START - timedelta(days=10),
        end=cov_end + timedelta(days=10),
    )
    assert start == _COV_START
    assert end == cov_end


def test_resolve_window_rejects_empty_range():
    ds = _long_dataset(100)
    t = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        resolve_window(ds, start=t, end=t)  # end <= start


def test_resolve_window_rejects_unknown_preset():
    ds = _long_dataset(100)
    with pytest.raises(ValueError):
        resolve_window(ds, period="last_decade")


def test_resolve_window_rejects_period_and_range_together():
    ds = _long_dataset(100)
    with pytest.raises(ValueError):
        resolve_window(ds, period="last_30_days", start=datetime(2026, 1, 5, tzinfo=timezone.utc))


def test_resolve_window_all_presets_known():
    # Every preset the selector offers resolves without error over ample coverage.
    ds = _long_dataset(400)
    for name in PERIOD_DAYS:
        start, end = resolve_window(ds, period=name)
        assert end > start
