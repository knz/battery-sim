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

import json
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
    # The §6.12 benchmark box is emitted only ON REQUEST. Its DP costs ~4.6 s on a year of hourly
    # data against ~0.12 s for everything above, so it is fetched separately (POST
    # /results/benchmark) and the default call must NOT pay for it. The absence here is the
    # lazy-load working, not a missing feature.
    assert "benchmark" not in r
    # The placeholder's window request rides in the view-model so the fetcher knows what to ask for.
    assert json.loads(r["benchmark_request"]).keys() == {"start", "end"}

    # Asked for explicitly, the box is present and structurally sound. Its contents are pinned in
    # tests/test_benchmark.py; this fixture is about the breakdown's arithmetic.
    rb = results_from(ds, (_WIN_START, _WIN_END), with_benchmark=True)
    assert rb is not None
    assert [row["label"] for row in rb["benchmark"]["rows"]][:3] == [
        "No battery",
        "Your policy",
        "Perfect foresight",
    ]


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


def test_results_state_the_parameter_set_they_were_computed_under():
    """The caveat names the battery the figures are for — it is no longer a placeholder.

    Two earlier wordings are gone: the zero-battery caveat (the battery runs now) and the
    "parameters panel is not wired up yet" one (Phase 6 wired it). What must stay is the fact
    itself: a computed number whose parameter set is unstated is exactly the kind of figure that
    propagates unchallenged, so the caveat still names capacity, powers, efficiency and policies.
    """
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert not any("No battery is configured" in c for c in r["caveats"])
    assert not any("every savings figure is zero" in c for c in r["caveats"])
    assert not any("not wired up yet" in c for c in r["caveats"])
    assert any(
        "10 kWh usable" in c and "5/5 kW" in c and "charge P3" in c for c in r["caveats"]
    )


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


# ── §2.4's benchmark box, and its conditional fourth row ─────────────────────────────────────
#
# Driven against `_benchmark_block` with SYNTHETIC EnergyBenchmark values rather than through a DP
# run. The display rule under test — when the "…if export allowed" row appears — is a presentation
# decision keyed on two capture ratios and a threshold, and the DP has no say in it. Constructing
# the ratios directly is what makes "just below the threshold" and "just above it" testable at all;
# steering a real DP to a chosen divergence would be neither possible nor informative.


def _bench_block(*, capture: float, capture_unconstrained: float | None):
    """A `_benchmark_block` rendered from an EnergyBenchmark with the given two capture ratios.

    The kWh figures are back-derived from the ratios against a fixed 1,000 kWh policy saving, so the
    rows carry plausible numbers and the ratios are exactly what was asked for.
    """
    from app.domain.benchmark import EnergyBenchmark
    from app.results_view import _benchmark_block

    policy_saved = 1000.0
    pf = policy_saved / capture
    unc = None if capture_unconstrained is None else policy_saved / capture_unconstrained
    return _benchmark_block(
        EnergyBenchmark(
            policy_saved_kwh=policy_saved,
            perfect_foresight_saved_kwh=pf,
            capture_ratio=capture,
            perfect_foresight_saved_kwh_unconstrained=unc,
            capture_ratio_unconstrained=capture_unconstrained,
            bound_import_kwh=5000.0 - pf,
            bound_import_kwh_unconstrained=None if unc is None else 5000.0 - unc,
            baseline_import_kwh=5000.0,
            soc_start_kwh=5.0,
            soc_end_kwh=5.2,
            # No POLICY drift: these fixtures are about the conditional export row, and a
            # materially-negative drift would send the gloss down the drift-corrected branch and
            # change what they are testing.
            policy_soc_delta_kwh=0.0,
        ),
        _ETA,
    )


def _labels(block) -> list[str]:
    return [row["label"] for row in block["rows"]]


def test_benchmark_box_has_the_three_unconditional_rows_in_wireframe_order():
    """§2.4's box: No battery, Your policy, Perfect foresight — always, in that order."""
    block = _bench_block(capture=0.70, capture_unconstrained=None)
    assert _labels(block) == ["No battery", "Your policy", "Perfect foresight"]
    assert block["rows"][0]["value"] == "0 kWh"
    assert block["rows"][0]["frac"] == 0.0
    assert block["rows"][0]["dot"] is False
    # Every bar fill is a fraction of the widest row, so none can overflow its track.
    assert all(0.0 <= row["frac"] <= 1.0 for row in block["rows"])
    # The widest row shown fills the track exactly — the shared scale is the widest baseline.
    assert max(row["frac"] for row in block["rows"]) == pytest.approx(1.0)


def test_export_row_renders_when_the_capture_ratios_diverge_beyond_the_threshold():
    """§2.4: the fourth row shows when the unconstrained fields are non-null AND the ratios diverge.

    0.70 against 0.55 is a 0.15 gap, comfortably above appendix A's 0.02 threshold.
    """
    block = _bench_block(capture=0.70, capture_unconstrained=0.55)
    assert _labels(block)[3] == "…if export allowed"
    assert "export" in block["gloss"]


def test_export_row_is_omitted_when_the_capture_ratios_barely_differ():
    """§2.4: below the threshold the row is OMITTED — a near-duplicate line "says nothing".

    0.700 against 0.695 is a 0.005 gap, well inside the 0.02 threshold.
    """
    block = _bench_block(capture=0.700, capture_unconstrained=0.695)
    assert "…if export allowed" not in _labels(block)
    assert len(block["rows"]) == 3


def test_export_row_threshold_boundary():
    """The comparison is strictly GREATER than the threshold, so an exactly-equal gap is omitted.

    Pinned because "> threshold" and ">= threshold" are equally plausible readings of §2.4's "differ
    by more than", and a boundary that silently flips would change what a whole class of runs shows.
    """
    from app.results_view import benchmark_divergence_display_threshold as thr

    assert thr == 0.02
    # **A gap of exactly `thr` is not constructible at a realistic capture ratio.** 0.02 has no
    # exact binary representation, so for `high` anywhere near a plausible ratio no `low` satisfies
    # `high - low == thr` — the representable differences straddle it (from 0.5 the nearest are
    # 0.020000000000000018 above and one ulp below). Walking `nextafter` does not converge, and a
    # test that pretended otherwise would be asserting something floating point cannot express.
    #
    # So the boundary is pinned the only way it exists: with the two nearest representable gaps on
    # either side of the threshold. That is exactly the distinction the code makes.
    high = 0.5
    just_under = float(np.nextafter(high - thr, 0.0))  # gap fractionally ABOVE thr → shown
    while high - just_under <= thr:
        just_under = float(np.nextafter(just_under, 0.0))
    just_over = float(np.nextafter(high - thr, high))  # gap fractionally BELOW thr → omitted
    while high - just_over >= thr:
        just_over = float(np.nextafter(just_over, high))

    assert high - just_over < thr < high - just_under, "fixture: the pair must straddle thr"
    # Gap below the threshold: OMITTED (§2.4 — a near-duplicate line "says nothing").
    assert "…if export allowed" not in _labels(
        _bench_block(capture=high, capture_unconstrained=just_over)
    )
    # Gap above it: shown.
    assert "…if export allowed" in _labels(
        _bench_block(capture=high, capture_unconstrained=just_under)
    )


def test_export_row_is_omitted_when_export_is_allowed():
    """§6.12/§2.4: with `allow_grid_export` on the second DP does not run, so the row cannot show.

    The unconstrained fields are None, and the row's condition requires them non-null — regardless
    of any ratio, because there is no second ratio to compare against.
    """
    block = _bench_block(capture=0.70, capture_unconstrained=None)
    assert "…if export allowed" not in _labels(block)
    assert "export" not in block["gloss"]


def test_export_row_is_omitted_end_to_end_when_export_is_allowed():
    """The same, through the real pipeline: `allow_grid_export=True` yields a three-row box.

    `_bench_block` above constructs the None fields directly; this asserts the DP layer really does
    produce them, so the two halves of the rule cannot pass independently while the join is broken.
    """
    import app.results_view as rv
    from app.domain.simconfig import PolicyConfig, SimulationConfig

    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    original = rv.SimulationConfig
    try:
        rv.SimulationConfig = lambda: SimulationConfig(
            policy=PolicyConfig(allow_grid_export=True)
        )
        r = results_from(ds, (_WIN_START, _WIN_END), with_benchmark=True)
    finally:
        rv.SimulationConfig = original
    assert r is not None
    assert "…if export allowed" not in [row["label"] for row in r["benchmark"]["rows"]]


def test_benchmark_gloss_states_the_capture_ratio_and_the_floor_caveat():
    """§2.4's gloss, and §7.2 item 6: the ratio is a FLOOR on achievable improvement, not a target.

    Also asserts the gloss carries no literal "%": `app/i18n.py` installs the Jinja i18n extension
    with `newstyle=True`, so a "%" before a letter in a string that reaches `_()` raises before it
    can be rendered. The gloss says "percent" in words instead.
    """
    block = _bench_block(capture=0.57, capture_unconstrained=None)
    assert "57 percent" in block["gloss"]
    assert "floor" in block["gloss"]
    assert "%" not in block["gloss"]


def test_benchmark_gloss_has_no_ratio_when_nothing_could_have_been_avoided():
    """A null capture ratio yields a plain sentence, never an invented percentage."""
    from app.domain.benchmark import EnergyBenchmark
    from app.results_view import _benchmark_block

    block = _benchmark_block(
        EnergyBenchmark(
            policy_saved_kwh=0.0,
            perfect_foresight_saved_kwh=0.0,
            capture_ratio=None,
            perfect_foresight_saved_kwh_unconstrained=None,
            capture_ratio_unconstrained=None,
            bound_import_kwh=0.0,
            bound_import_kwh_unconstrained=None,
            baseline_import_kwh=0.0,
            soc_start_kwh=5.0,
            soc_end_kwh=5.0,
            policy_soc_delta_kwh=0.0,
        ),
        _ETA,
    )
    assert "capture ratio" in block["gloss"]
    assert "percent" not in block["gloss"]
    assert all(row["frac"] == 0.0 for row in block["rows"])  # no scale → no bars, not a crash


def test_benchmark_strings_contain_no_literal_percent_sign():
    """The i18n guard, applied to every string the benchmark box sends through `_()`.

    Mirrors `test_no_caveat_contains_a_literal_percent_sign`. The template wraps both the row labels
    and the gloss in `_()`, so a "%" in either raises at render time under `newstyle=True`.
    """
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    # `with_benchmark=True`: the DP is LAZY now (it costs ~4.6 s on a year of hourly data and is
    # fetched by POST /results/benchmark), so the key is absent unless asked for.
    r = results_from(ds, (_WIN_START, _WIN_END), with_benchmark=True)
    assert r is not None
    block = r["benchmark"]
    assert "%" not in block["gloss"]
    for row in block["rows"]:
        assert "%" not in row["label"]


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


# ── The capture ratio's PRESENTATION, and the four shapes it must distinguish ─────────────────
#
# Background: §6.12's terminal constraint is ASYMMETRIC with the policy run — the DP must end at or
# above its starting SoC, the policy run need not, and §6.11 deliberately does not net the drift
# out. A policy that liquidates its opening charge therefore books a saving the DP is forbidden to
# book, and the raw capture ratio divides a drift-funded numerator by a drift-neutral denominator.
# Printed unconditionally, that produced "captures −493 percent" on a reproducible configuration.
#
# `EnergyBenchmark.capture_ratio` stays UNCLAMPED (its docstring: a clamp would turn a detectable
# fault into a plausible number). The fix is in the VIEW, and these four tests are its contract.
# Synthetic EnergyBenchmark values, for the same reason the export-row tests use them: the shapes
# under test are presentation decisions keyed on a ratio and a drift, and steering a real DP to a
# chosen ratio would be neither possible nor informative.


def _shape_block(*, policy_saved: float, pf_saved: float, drift: float):
    """A `_benchmark_block` from a synthetic block with a chosen saving, bound and POLICY drift."""
    from app.domain.benchmark import EnergyBenchmark, _capture_ratio
    from app.results_view import _benchmark_block

    return _benchmark_block(
        EnergyBenchmark(
            policy_saved_kwh=policy_saved,
            perfect_foresight_saved_kwh=pf_saved,
            capture_ratio=_capture_ratio(policy_saved, pf_saved),
            perfect_foresight_saved_kwh_unconstrained=None,
            capture_ratio_unconstrained=None,
            bound_import_kwh=5000.0 - pf_saved,
            bound_import_kwh_unconstrained=None,
            baseline_import_kwh=5000.0,
            soc_start_kwh=5.0,
            soc_end_kwh=5.0,
            policy_soc_delta_kwh=drift,
        ),
        _ETA,
    )


def test_capture_ratio_shape_1_normal_renders_a_plain_percentage():
    """Drift immaterial and 0 ≤ ratio ≤ 1: the wireframe's plain percentage, unchanged.

    This is the case the box was always right about, pinned so the three guards below cannot be
    made to fire on a perfectly ordinary run.
    """
    block = _shape_block(policy_saved=700.0, pf_saved=1000.0, drift=-1.0)
    assert "captures 70 percent" in block["gloss"]
    assert "floor" in block["gloss"]
    # The drift-corrected wording must NOT appear: 1 kWh against a 700 kWh saving is far below
    # §6.11's 2% threshold, so there is nothing to correct for.
    assert "less charged than it started" not in block["gloss"]
    assert "%" not in block["gloss"]


def test_capture_ratio_shape_2_drift_funded_does_not_render_as_a_plain_percentage():
    """A materially-negative drift: the ratio is restated on the drift-corrected basis, and said so.

    The saving is 400 kWh against a 1,000 kWh bound — a raw ratio of 0.40 — but 200 kWh of the
    battery's opening charge went into funding it. Corrected: 400 − 200 × eta_d = 210.26 kWh, a
    ratio of 0.21. The box must show the corrected figure and explain the correction, never the raw
    0.40, because 0.40 credits the policy with charge it did not earn.
    """
    block = _shape_block(policy_saved=400.0, pf_saved=1000.0, drift=-200.0)
    corrected = (400.0 - 200.0 * _ETA) / 1000.0
    assert f"captures {round(100 * corrected)} percent" in block["gloss"]
    assert "captures 40 percent" not in block["gloss"]
    # The correction is stated, not applied silently — §6.11's drift metric is untouched, and the
    # reader has to be able to see that this figure is on a different basis from the rows above.
    assert "less charged than it started" in block["gloss"]
    assert "%" not in block["gloss"]


def test_capture_ratio_shape_2_reproduces_the_reported_defect_end_to_end():
    """The exact configuration that printed "captures −493 percent", through a REAL DP run.

    20 kWh usable, 100 → 10 percent SoC, 96 intervals of 1.0 kWh load against 0.2 kWh PV. The
    policy saves 14.20 kWh, the bound is −2.88 kWh, so the raw ratio is −4.93. The whole 14.20 was
    funded by an 18.00 kWh liquidation of the opening charge; corrected, the policy exactly matches
    the bound. The synthetic tests above pin the rule; this one pins that the rule fires on the
    configuration that motivated it.
    """
    import numpy as np

    from app.domain.benchmark import energy_benchmark
    from app.domain.simulate import run_all
    from app.results_view import _benchmark_block
    from tests.test_simulate import _cfg, _frame

    cfg = _cfg(usable_capacity_kwh=20.0, initial_soc_pct=100.0, min_soc_pct=10.0)
    frame = _frame(np.full(96, 1.0), pv=np.full(96, 0.2))
    runs = run_all(frame, cfg)
    bench = energy_benchmark(runs.a, runs.c, frame, cfg)

    # The raw metric is unchanged and still shows the fault — that is deliberate (see
    # EnergyBenchmark's docstring); only the VIEW is fixed.
    assert bench.capture_ratio == pytest.approx(-4.929, abs=1e-3)
    assert bench.policy_soc_delta_kwh == pytest.approx(-18.0, abs=1e-6)

    gloss = _benchmark_block(bench, cfg.eta_d)["gloss"]
    assert "-493" not in gloss and "−493" not in gloss
    assert "less charged than it started" in gloss
    assert "%" not in gloss


def test_capture_ratio_shape_3_zero_bound_with_a_positive_policy_row_does_not_contradict_it():
    """A ~0 bound beside a POSITIVE policy row: the gloss must not deny what the row shows.

    The reported defect: "even a perfectly-informed battery could not have avoided any grid import"
    printed directly above a row reading "Your policy 9 kWh". The sentence is a claim about the DP
    and is true, but placed above that row it reads as a contradiction. The box now branches.
    """
    block = _shape_block(policy_saved=9.0, pf_saved=0.0, drift=-5.0)
    # The row the gloss must not contradict is still there and still honest.
    assert next(r for r in block["rows"] if r["label"] == "Your policy")["value"] == "9 kWh"
    assert "could not have avoided any grid import, so there is no capture ratio" \
        not in block["gloss"]
    # It says something TRUE about the situation instead: the saving is not one the benchmark
    # could reproduce under the terminal constraint.
    assert "9 kWh" in block["gloss"]
    assert "state of charge it started from" in block["gloss"]
    assert "no capture ratio" in block["gloss"]
    assert "%" not in block["gloss"]


def test_capture_ratio_shape_3_zero_bound_and_zero_policy_keeps_the_plain_sentence():
    """When the policy saved ~0 too, the original wording is true and is kept."""
    block = _shape_block(policy_saved=0.0, pf_saved=0.0, drift=0.0)
    assert "could not have avoided any grid import" in block["gloss"]
    assert "percent" not in block["gloss"]
    assert all(row["frac"] == 0.0 for row in block["rows"])  # no scale → no bars, not a crash


def test_capture_ratio_shape_4_above_one_is_never_a_plain_percentage():
    """A ratio above 1 with no drift to explain it is a FAULT and must not be presented as a result.

    Fixture 6 says the bound cannot be beaten, so a capture above 100 percent is not a measurement
    of anything. The box states no number at all — "captures 2859 percent" is worse than silence,
    because it reads as a finding.
    """
    block = _shape_block(policy_saved=1000.0, pf_saved=35.0, drift=0.0)  # ratio 28.57
    assert "percent" not in block["gloss"]
    assert "2857" not in block["gloss"] and "2859" not in block["gloss"]
    assert "did not come out usable" in block["gloss"]
    assert "%" not in block["gloss"]
    # The ROWS stay honest — the defect was the ratio and the gloss, never the bars.
    assert next(r for r in block["rows"] if r["label"] == "Your policy")["value"] == "1,000 kWh"
    assert next(r for r in block["rows"] if r["label"] == "Perfect foresight")["value"] == "35 kWh"


def test_capture_ratio_exactly_one_is_a_result_not_a_fault():
    """A policy that exactly matches the bound is the best possible outcome, not a broken one.

    Guards the float slack on the range test: the drift correction subtracts one computed quantity
    from another and can land at 1.0000000000000024, which without the tolerance would be reported
    as a fault. Measured on the reproduction in
    `test_capture_ratio_shape_2_reproduces_the_reported_defect_end_to_end`.
    """
    block = _shape_block(policy_saved=1000.0, pf_saved=1000.0, drift=0.0)
    assert "captures 100 percent" in block["gloss"]
    assert "did not come out usable" not in block["gloss"]


def test_positive_drift_does_not_trigger_the_correction():
    """Only a NEGATIVE drift funds a saving out of opening charge; a positive one needs no guard.

    A battery that ends MORE charged has energy it bought and still holds counted as consumed, so
    its raw ratio understates the policy. Understating is not the failure mode this guards against,
    and correcting it would inflate a figure §6.11 wants reported conservatively.
    """
    block = _shape_block(policy_saved=400.0, pf_saved=1000.0, drift=+200.0)
    assert "captures 40 percent" in block["gloss"]
    assert "less charged than it started" not in block["gloss"]


def test_drift_threshold_is_soc_drift_warn_frac_not_a_second_constant():
    """The gate reuses §6.11's own 2% threshold, so the box and the drift caveat fire together.

    Just below `SOC_DRIFT_WARN_FRAC × |saving|` the raw ratio is shown; just above it the corrected
    one is. Pinning the boundary against the imported constant means a change to §6.11's threshold
    moves both, rather than leaving a second copy behind.
    """
    from app.domain.metrics import SOC_DRIFT_WARN_FRAC

    saving = 1000.0
    below = -(SOC_DRIFT_WARN_FRAC * saving) * 0.9
    above = -(SOC_DRIFT_WARN_FRAC * saving) * 1.1
    assert "less charged than it started" not in _shape_block(
        policy_saved=saving, pf_saved=2000.0, drift=below
    )["gloss"]
    assert "less charged than it started" in _shape_block(
        policy_saved=saving, pf_saved=2000.0, drift=above
    )["gloss"]
