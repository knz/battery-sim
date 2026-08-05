"""Unit tests for the panel-③ results view-model and window resolver (specs §2.4, §7.4).

Two units under test, both from app/results_view:

  * results_from(dataset, window) — the ENERGY SAVINGS view-model over a window, computed from a
    REAL run of the §6.6–§6.9 core under appendix-A defaults. Covers the headline figures, the
    omit-don't-zero discipline (no self-consumption row without PV), the negative-saving
    presentation (§7.2 item 9), the §2.3a self-sufficiency display clamp, and the no-grid → None
    guard.
  * resolve_window(dataset, *, period/start/end) — preset anchoring to the END of data coverage
    (§7.4) and clamping to coverage.
  * the §2.4 COST SAVINGS section (Phase 6, at the foot of this file) — §6.14 fixtures 18 and 19,
    the euro arithmetic checked against `app/domain/costs.py` directly, the display/JSON split on
    zero waterfall lines, and the money box's capture-ratio shapes, which are NOT the energy
    box's four: §6.12's drift correction has no sound euro analogue (follow-up H10), so a
    drift-funded euro ratio is reported as unavailable rather than restated.

**These assertions were hand-derived, not read off the view.** The scenarios below carry NO spot
price, which makes `frame.spot` all-NaN; §6.6/§6.7's band comparisons are then all False (IEEE),
so the default P3/D1 configuration reduces to D1 alone — the battery serves the household deficit
from its starting SoC and never grid-charges. That makes the whole run analytically closed, and
each test's comment carries the derivation.

Synthetic SeriesFrames are built in-process (no browser, no real dataset), reusing the frame/dataset
helpers from tests/test_data_summary.py so the two suites share one construction of a LoadedDataset.

**Caveats and the benchmark gloss are (msgid, params) PAIRS, not finished sentences.** They used to
be built here with f-strings, which made their msgid a runtime value no `pybabel extract` run could
see — the whole reason a Dutch reader saw them in English. `_en(m)` below renders a pair the way the
template does (translate, then interpolate) so these tests keep asserting on the ENGLISH SENTENCE a
reader sees, rather than being weakened to substring checks against a bare msgid. Where a test is
about the msgid itself — the wording a translator receives — it says so and reads `m["msgid"]`.
"""

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.i18n import format_num, month_abbr
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


def _en(m, locale: str = "en") -> str:
    """Render a view-model message or figure as the sentence a reader sees, in ENGLISH by default.

    The same steps templates/_msg.html performs, with the null catalog so the msgid IS the English
    text: format any FIGURE param, render any NESTED message param, pick the plural form, then
    interpolate. A plain string passes through unchanged, which keeps the helper usable against a
    view-model field whose shape is still a bare literal.

    `locale` is explicit and defaults to "en" because these tests assert on English wording and
    English number conventions ("3,924 kWh"). Those assertions are still correct — they are
    assertions ABOUT ENGLISH — and naming the locale is what keeps them so now that the figures are
    formatted at render time (A6) rather than baked in by the view-model. Pass locale="nl" to
    assert the Dutch form of the same field.
    """
    if isinstance(m, dict) and "fmt" in m:
        return format_num(m["num"], m["fmt"], locale)
    if not isinstance(m, dict):
        return m
    params = {k: _en(v, locale) if isinstance(v, dict) else v
              for k, v in (m.get("params") or {}).items()}
    text = m["plural"] if "plural" in m and m["n"] != 1 else m["msgid"]
    return text % params


def _caveats(r) -> list[str]:
    """Every caveat in a results view-model, rendered to English (see `_en`)."""
    return [_en(c) for c in r["caveats"]]


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
    assert _en(saved_tile["value"]) == "3"  # round(3.0747)
    assert saved_tile["unit"] == "kWh"
    assert _en(saved_tile["delta"]) == "+6.4 %"  # 100 × 3.0747 / 48

    cycles = next(k for k in r["kpis"] if k["title"] == "EQUIVALENT FULL CYCLES")
    assert _en(cycles["value"]) == "0"     # 0.40 EFC rounds to 0 whole cycles
    assert _en(cycles["delta"]) == "0.40 / day"  # 0.40 over a 1-day window
    assert _en(cycles["extra"]) == "4 kWh throughput"  # round(3.7947) AC delivered

    by_label = {row["label"]: _en(row["value"]) for row in r["energy_breakdown"]}
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
    assert _en(ss["value"]) == "75% → 78%"
    assert _en(ss["delta"]) == "+3 pp"


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

    assert _en(ss["value"]) == "75% → 78%", "the left half must be run A's simulated baseline"
    assert _en(ss["value"]) != "50% → 78%", "the left half must NOT be the measured self-sufficiency"
    assert _en(ss["delta"]) == "+3 pp"
    assert _en(ss["delta"]) != "+28 pp", "the measured baseline inflates the delta by 25 pp here"

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


def test_self_sufficiency_tile_carries_an_info_blurb_explaining_the_baseline():
    """The ⓘ that documents what the left half is, and why it is not the household card's figure.

    `test_..._not_the_meter` above pins the CHOICE; this pins the EXPLANATION of it. Both figures
    are on one screen — the data-glance band's measured self-sufficiency and this tile's simulated
    baseline — and on this fixture they read 50% and 75%. §7.1 requires the divergence, so the
    only thing left is to say so on the page; without the blurb the difference is indistinguishable
    from a bug. The sibling caveat (next test) does this for the two IMPORT figures in kWh; this
    is the same obligation for the two self-sufficiency PERCENTAGES.

    Only this tile carries one — asserted, so a future generic ⓘ on every tile is a deliberate
    change rather than something this test waves through.
    """
    r = results_from(_overlap_dataset(), (_WIN_START, _WIN_END))
    assert r is not None
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")

    # The blurb exists, is a plain _N msgid (the template translates it), and names the two things
    # a reader needs: that the left half is the battery-free baseline, and that the measured
    # figure elsewhere on the page is a different quantity rather than a contradiction.
    assert ss["info_title"] == "Self-sufficiency"
    body = ss["info_body"]
    assert isinstance(body, str), "a data-* attribute takes a string, not an _msg pair"
    assert "baseline" in body
    assert "measured" in body and "simulation" in body

    # It is ONE paragraph: ha_fetch.js sets the dialog body with textContent into a single <p>,
    # so an embedded newline would silently render as a space.
    assert "\n" not in body

    # The other two tiles do not have one.
    for other in ("GRID IMPORT SAVED", "EQUIVALENT FULL CYCLES"):
        tile = next(k for k in r["kpis"] if k["title"] == other)
        assert "info_body" not in tile


def test_resolution_loss_is_both_a_caveat_and_an_info_button_on_the_baseline_row():
    """The kWh discrepancy is explained in two places from ONE msgid.

    The caveat states it unprompted; the ⓘ on "Grid import, no battery" puts it at the figure it
    is about, for a reader who questions that number without reading the caveat list. Sharing the
    msgid is the point — two hand-written copies would drift apart and cost the translator twice.
    """
    r = results_from(_overlap_dataset(), (_WIN_START, _WIN_END))
    assert r is not None

    row = next(x for x in r["energy_breakdown"] if x["label"] == "Grid import, no battery")
    assert row["info_title"] == "Grid import, no battery"

    # Same msgid AND same params as the caveat — literally the same object, not a copy.
    caveat = next(c for c in r["caveats"]
                  if isinstance(c, dict) and c["msgid"].startswith("Your meter recorded"))
    assert row["info_body"] is caveat

    # It renders with both figures substituted (48 measured vs 24 simulated on this fixture).
    rendered = _en(row["info_body"])
    assert "48 kWh" in rendered and "24 kWh" in rendered

    # No other breakdown row carries one.
    assert [x["label"] for x in r["energy_breakdown"] if "info_body" in x] \
        == ["Grid import, no battery"]


def test_self_sufficiency_discrepancy_gets_its_own_caveat_beside_the_import_one():
    """The same divergence in PERCENTAGES, which the kWh caveat never names.

    The pair a reader actually compares is the two self-sufficiency figures on screen, not the two
    import totals — so the reconciliation is stated in that unit too, immediately after the kWh
    one. On this fixture the measured figure is 50% and the simulated baseline 75%.
    """
    r = results_from(_overlap_dataset(), (_WIN_START, _WIN_END))
    caveats = [c["msgid"] if isinstance(c, dict) else c for c in r["caveats"]]

    import_i = next(i for i, m in enumerate(caveats) if m.startswith("Your meter recorded"))
    ss_i = next(i for i, m in enumerate(caveats) if m.startswith("For the same reason"))
    assert ss_i == import_i + 1, "the two halves of one discrepancy read together"

    rendered = _en(r["caveats"][ss_i])
    assert "50%" in rendered and "75%" in rendered
    # It quotes the figures as the page shows them: the measured one from the household card and
    # the tile's simulated baseline, NOT the with-battery half.
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")
    assert _en(ss["value"]).startswith("75%")


def test_no_self_sufficiency_caveat_when_the_two_percentages_agree():
    """Silent when there is nothing visible to explain.

    Export is zero in every interval here, so the meter's import and run A's coincide: both the
    kWh caveat and its percentage counterpart must stay away rather than point at a difference the
    reader cannot see on the page.
    """
    r = results_from(_dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ]), (_WIN_START, _WIN_END))
    caveats = [c["msgid"] if isinstance(c, dict) else c for c in r["caveats"]]
    assert not any(m.startswith("For the same reason") for m in caveats)
    assert not any(m.startswith("Your meter recorded") for m in caveats)
    # …and with no discrepancy the ⓘ is absent from the row too.
    assert not any("info_body" in x for x in r["energy_breakdown"])


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
    assert _en(r["data_summary"]["grid"]["imported"]) == "48 kWh"
    by_label = {row["label"]: _en(row["value"]) for row in r["energy_breakdown"]}
    assert by_label["Grid import, no battery"] == "24 kWh"

    note = next((c for c in _caveats(r) if "no-battery baseline" in c), None)
    assert note is not None, "the measured/simulated import gap must be explained"
    assert "48 kWh" in note and "24 kWh" in note, "both figures must be named"
    assert "24 kWh" in note  # the difference, which here equals the baseline

    # It is NOT raised when there is nothing to explain: with export 0 in every interval the two
    # figures coincide and a caveat about a difference the reader cannot see would be noise.
    clean = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r2 = results_from(clean, (_WIN_START, _WIN_END))
    assert not any("no-battery baseline" in c for c in _caveats(r2))


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
    assert _en(r["data_summary"]["grid"]["exported"]) == "24 kWh"
    assert _en(row["value"]) == "100% → 100%", "both halves are run figures over the same window"
    assert _en(row["value"]) != "67% → 100%", "the left half must not be the measured export ratio"


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
    assert _en(row["value"]) == (
        f"{_en(_fmt_pct(max(0.0, masked.self_consumption_baseline)))} → "
        f"{_en(_fmt_pct(max(0.0, masked.self_consumption_battery)))}"
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
    assert _en(ss["value"]) == "n/a → n/a"
    assert _en(ss["value"]) != "n/a → 100%", "a household with no load is not 100% self-sufficient"
    assert _en(ss["value"]) != "n/a → 0%", "nor 0% — absence, not a measurement"
    assert ss["delta"] == "", "no delta between two absences"


def test_kwh_and_signed_kwh_use_the_same_minus_glyph():
    """Both formatters render a negative with U+2212, never the ASCII hyphen.

    `_fmt_kwh`'s callers all pass non-negative quantities today, so this is latent rather than
    live — but Python's `format` emits "-" and so does babel (both locales' CLDR minus IS the ASCII
    hyphen), while `_fmt_signed_kwh` emits "−", and two different minus glyphs on one panel is the
    kind of inconsistency that survives until someone screenshots it.

    Asserted in BOTH locales, because the formatting moved to render time (A6) and the minus is
    now applied by `i18n.format_num` after babel: a locale whose CLDR minus differs, or a code path
    that returns babel's output unmodified, would show up here rather than on a screenshot.
    """
    from app.results_view import _fmt_kwh, _fmt_signed_kwh

    for locale, expected in (("en", "−1,234 kWh"), ("nl", "−1.234 kWh")):
        assert _en(_fmt_kwh(-1234.0), locale) == expected
        assert "-" not in _en(_fmt_kwh(-1234.0), locale), "ASCII hyphen must not appear"
        assert _en(_fmt_kwh(-1234.0), locale)[0] == _en(_fmt_signed_kwh(-1234.0), locale)[0]
    assert _en(_fmt_kwh(1234.0)) == "1,234 kWh"       # unchanged on the normal path
    assert _en(_fmt_kwh(1234.0), "nl") == "1.234 kWh" # …and Dutch-separated in Dutch


def test_no_caveat_contains_a_literal_percent_sign():
    """No literal "%" in a RENDERED caveat, and the real render path is lossless.

    History: this began as a corruption guard. `app/i18n.install_for` used to install the Jinja
    i18n extension with `newstyle=True`, which %-formatted the translated result, so a caveat
    reading "90% round-trip" rendered as "90{}ound-trip" — "% r" parsed as a conversion specifier —
    silently, with no exception. That trap is gone (`newstyle=False`), so the "%"-free wording is
    now a house style rather than a safety requirement, and the assertion is kept as such: the
    caveats say "0.90 round-trip" where the tiles say "34.2 %", and a "%" appearing here would
    mean someone changed a sentence.

    ONE caveat is exempt, at the loop below: the self-sufficiency reconciliation caveat is about
    two percentages differing and has to quote them as percentages. See the note there.

    What it now also pins is the RENDER PATH, which changed shape. A caveat is a (msgid, params)
    pair, so the template does `_(msgid) | interpolate(**params)` — translate, then substitute.
    The round trip below runs exactly that and asserts the result equals the English sentence,
    which catches a params key that no placeholder consumes, or a placeholder no key fills
    (`interpolate` raises on the latter).
    """
    from html import unescape

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
    # The REAL render path: the real per-locale environment and the real `_msg.html` macro, not a
    # hand-rolled two-liner. It used to be the latter — `_(m.msgid) | interpolate(**m.params)` —
    # which stopped being the whole story when figures moved to render time (A6): the macro also
    # formats a param that is a NUMBER and renders one that is a nested MESSAGE, and a
    # reimplementation that skips either would assert against itself rather than against the page.
    tmpl = i18n.env_for("en").from_string(
        '{% from "_msg.html" import msg with context %}{{ msg(m) }}'
    )

    seen = 0
    branches: set[str] = set()
    for frames in scenarios:
        r = results_from(_dataset(frames), (_WIN_START, _WIN_END))
        for m in r["caveats"]:
            c = _en(m)
            seen += 1
            branches.add(c[:40])
            # The house style has ONE documented exception, and it is a deliberate one. The
            # self-sufficiency reconciliation caveat exists to explain why two PERCENTAGES on this
            # page differ (the household card's measured figure against the tile's simulated
            # baseline), and it quotes both. Restating them as fractions to satisfy the style —
            # "0.44 against 0.47" — would describe neither figure as the page shows it, which is
            # the opposite of what that caveat is for. The corruption trap the rule began as is
            # gone (`newstyle=False`, see above), so the cost of the exception is cosmetic.
            # Pinned by prefix rather than waived generally: any OTHER caveat growing a "%" still
            # fails, which is the regression the assertion is kept for.
            if not c.startswith("For the same reason, the self-sufficiency"):
                assert "%" not in c, f"literal % in a rendered caveat: {c!r}"
            # Every caveat here is a pair (no counted caveat exists yet), and the real render path
            # reproduces the English sentence exactly.
            assert isinstance(m, dict) and "plural" not in m
            # `unescape` because the macro autoescapes its output (an apostrophe becomes &#39;)
            # while `_en` above does not. The escaping is correct and wanted on the page; it is
            # simply not what this assertion is about.
            assert unescape(tmpl.render(m=m)) == c
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
    assert _en(sc["value"]) == "100% → 100%"


def test_results_state_the_parameter_set_they_were_computed_under():
    """The caveat names the battery the figures are for — it is no longer a placeholder.

    Two earlier wordings are gone: the zero-battery caveat (the battery runs now) and the
    "parameters panel is not wired up yet" one (Phase 6 wired it). What must stay is the fact
    itself: a computed number whose parameter set is unstated is exactly the kind of figure that
    propagates unchallenged, so the caveat still names capacity, powers, efficiency and policies.
    """
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert not any("No battery is configured" in c for c in _caveats(r))
    assert not any("every savings figure is zero" in c for c in _caveats(r))
    assert not any("not wired up yet" in c for c in _caveats(r))
    assert any(
        "10 kWh usable" in c and "5/5 kW" in c and "charge P3" in c for c in _caveats(r)
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
    assert _en(saved_tile["value"]) == "−6"      # round(5.9905), signed
    assert _en(saved_tile["delta"]) == "−12.5 %"  # the percentage keeps the sign too

    labels = [row["label"] for row in r["energy_breakdown"]]
    assert "Grid import avoided" not in labels, "a cost must not be captioned 'avoided'"
    assert "Extra grid import" in labels
    by_label = {row["label"]: _en(row["value"]) for row in r["energy_breakdown"]}
    assert by_label["Extra grid import"] == "6 kWh"   # the magnitude; the label has the direction
    assert by_label["Grid import, no battery"] == "48 kWh"
    assert by_label["Grid import, with battery"] == "54 kWh"  # round(48 + 5.9905)
    assert by_label["Charged into the battery"] == "5 kWh"    # round(5.2705)
    assert by_label["Discharged from the battery"] == "0 kWh"

    assert any("MORE from the grid" in c for c in _caveats(r))
    assert any("worth buying" in c for c in _caveats(r))


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
    assert any("more charged than it started" in c for c in _caveats(r))


def test_negative_saving_never_renders_a_signed_zero():
    """A saving that rounds to zero prints "0 kWh" / "0.0 %", never "−0" — that reads as a bug."""
    from app.results_view import _fmt_signed_kwh, _fmt_signed_pct

    assert _en(_fmt_signed_kwh(-0.4)) == "0 kWh"
    assert _en(_fmt_signed_kwh(-1.6)) == "−2 kWh"
    assert _en(_fmt_signed_kwh(1.6)) == "2 kWh"
    assert _en(_fmt_signed_pct(-0.04)) == "0.0 %"
    assert _en(_fmt_signed_pct(-34.21)) == "−34.2 %"
    assert _en(_fmt_signed_pct(8.75)) == "+8.8 %"
    # The zero guard is locale-independent: it is about the SIGN, not the separators.
    assert _en(_fmt_signed_kwh(-0.4), "nl") == "0 kWh"
    assert _en(_fmt_signed_pct(-0.04), "nl") == "0,0 %"


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
    assert (_en(_clamped_pct(-0.12)[0]), _clamped_pct(-0.12)[1]) == ("0%", True)
    assert (_en(_clamped_pct(0.0)[0]), _clamped_pct(0.0)[1]) == ("0%", False)
    assert (_en(_clamped_pct(0.52)[0]), _clamped_pct(0.52)[1]) == ("52%", False)
    # "n/a" stays a plain STRING rather than becoming a figure — it is not one, and it is the
    # same abbreviation in Dutch, so it needs neither formatting nor a msgid.
    assert _clamped_pct(None) == ("n/a", False)

    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", 0.02),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r is not None
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")
    assert _en(ss["value"]).endswith("→ 0%"), "a negative self-sufficiency must display as 0%"
    assert any("shown as zero" in c for c in _caveats(r))

    # The underlying metric is untouched — the clamp is presentation only.
    from app.domain.metrics import energy_metrics
    from app.domain.simconfig import SimulationConfig
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    cfg = SimulationConfig()
    m = energy_metrics(run_all(frame, cfg), frame, cfg)
    assert m.self_sufficiency_battery == pytest.approx(-0.108, abs=1e-3)


def test_results_period_line_and_monthly_import_chart_are_real():
    # The coverage line reflects the effective window, hourly grid, and interval count; the chart is
    # a real monthly MEASURED-IMPORT series (one bucket here — a single January), which is what the
    # tab is labelled as. It is deliberately NOT a per-month saving: that series is not built, and
    # the old "Monthly savings" tab label over these values overstated the saving by ~11×.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r["period"] == "2026-01-01 → 2026-01-02 · simulated hourly · 24 intervals"
    # `months` are month NUMBERS now; the locale-bound `monthname` filter names them at render
    # time (A6), so a Dutch axis reads "jan" rather than the English table this used to assert.
    assert r["chart"]["months"] == [1]
    assert month_abbr(1, "en") == "Jan" and month_abbr(1, "nl") == "jan"
    assert r["chart"]["values"] == [48]  # 2 kWh/h × 24 h


def test_results_short_window_emits_no_annualisation_guard():
    # §7.4's short-window guard is not emitted, because nothing in the app annualises: the box it
    # set told the user an annual projection had been withheld and pointed at a range selection
    # that produced none. A 24 h window is well under min_annualisation_days (90) and so would have
    # tripped the old guard — this asserts the keys stay absent until an annualised figure exists,
    # at which point the guard returns with it.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert "annualisation_disabled" not in r
    assert "annualisation_message" not in r


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
    assert _en(block["rows"][0]["value"]) == "0 kWh"
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
    assert "export" in _en(block["gloss"])


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
    assert "export" not in _en(block["gloss"])


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

    Also asserts the RENDERED gloss carries no literal "%". That began as an i18n constraint — the
    Jinja i18n extension was installed with `newstyle=True`, which %-formatted the translated
    result, so a "%" before a letter raised at render time — and no longer is one: `app/i18n.py`
    now installs with `newstyle=False`. The assertion is kept as a wording check, because the box
    saying "57 percent" and the tiles saying "34.2 %" is a deliberate distinction (prose vs figure)
    and a "%" appearing here would mean someone changed the sentence.
    """
    block = _bench_block(capture=0.57, capture_unconstrained=None)
    assert "57 percent" in _en(block["gloss"])
    assert "floor" in _en(block["gloss"])
    assert "%" not in _en(block["gloss"])


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
    assert "capture ratio" in _en(block["gloss"])
    assert "percent" not in _en(block["gloss"])
    assert all(row["frac"] == 0.0 for row in block["rows"])  # no scale → no bars, not a crash


def test_benchmark_strings_contain_no_literal_percent_sign():
    """No literal "%" in the benchmark box's RENDERED text or its row labels.

    Mirrors `test_no_caveat_contains_a_literal_percent_sign`. Once an i18n safety requirement
    (`newstyle=True` %-formatted every translated string, so a stray "%" raised); now a wording
    check, since `app/i18n.py` uses `newstyle=False`. Note this asserts on the RENDERED gloss:
    the msgid legitimately contains `%(pct)s`, which is the placeholder, not a percent sign.
    """
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    # `with_benchmark=True`: the DP is LAZY now (it costs ~4.6 s on a year of hourly data and is
    # fetched by POST /results/benchmark), so the key is absent unless asked for.
    r = results_from(ds, (_WIN_START, _WIN_END), with_benchmark=True)
    assert r is not None
    block = r["benchmark"]
    assert "%" not in _en(block["gloss"])
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
    assert {k: _en(v) for k, v in r["data_summary"]["grid"].items()} == {
        "imported": "48 kWh", "exported": "0 kWh"}
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
    assert _en(r["data_summary"]["grid"]["imported"]) == "48 kWh"


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
    assert "captures 70 percent" in _en(block["gloss"])
    assert "floor" in _en(block["gloss"])
    # The drift-corrected wording must NOT appear: 1 kWh against a 700 kWh saving is far below
    # §6.11's 2% threshold, so there is nothing to correct for.
    assert "less charged than it started" not in _en(block["gloss"])
    assert "%" not in _en(block["gloss"])


def test_capture_ratio_shape_2_drift_funded_does_not_render_as_a_plain_percentage():
    """A materially-negative drift: the ratio is restated on the drift-corrected basis, and said so.

    The saving is 400 kWh against a 1,000 kWh bound — a raw ratio of 0.40 — but 200 kWh of the
    battery's opening charge went into funding it. Corrected: 400 − 200 × eta_d = 210.26 kWh, a
    ratio of 0.21. The box must show the corrected figure and explain the correction, never the raw
    0.40, because 0.40 credits the policy with charge it did not earn.
    """
    block = _shape_block(policy_saved=400.0, pf_saved=1000.0, drift=-200.0)
    corrected = (400.0 - 200.0 * _ETA) / 1000.0
    assert f"captures {round(100 * corrected)} percent" in _en(block["gloss"])
    assert "captures 40 percent" not in _en(block["gloss"])
    # The correction is stated, not applied silently — §6.11's drift metric is untouched, and the
    # reader has to be able to see that this figure is on a different basis from the rows above.
    assert "less charged than it started" in _en(block["gloss"])
    assert "%" not in _en(block["gloss"])


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

    gloss = _en(_benchmark_block(bench, cfg.eta_d)["gloss"])
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
    assert _en(next(r for r in block["rows"] if r["label"] == "Your policy")["value"]) == "9 kWh"
    assert "could not have avoided any grid import, so there is no capture ratio" \
        not in _en(block["gloss"])
    # It says something TRUE about the situation instead: the saving is not one the benchmark
    # could reproduce under the terminal constraint.
    assert "9 kWh" in _en(block["gloss"])
    assert "state of charge it started from" in _en(block["gloss"])
    assert "no capture ratio" in _en(block["gloss"])
    assert "%" not in _en(block["gloss"])


def test_capture_ratio_shape_3_zero_bound_and_zero_policy_keeps_the_plain_sentence():
    """When the policy saved ~0 too, the original wording is true and is kept."""
    block = _shape_block(policy_saved=0.0, pf_saved=0.0, drift=0.0)
    assert "could not have avoided any grid import" in _en(block["gloss"])
    assert "percent" not in _en(block["gloss"])
    assert all(row["frac"] == 0.0 for row in block["rows"])  # no scale → no bars, not a crash


def test_capture_ratio_shape_4_above_one_is_never_a_plain_percentage():
    """A ratio above 1 with no drift to explain it is a FAULT and must not be presented as a result.

    Fixture 6 says the bound cannot be beaten, so a capture above 100 percent is not a measurement
    of anything. The box states no number at all — "captures 2859 percent" is worse than silence,
    because it reads as a finding.
    """
    block = _shape_block(policy_saved=1000.0, pf_saved=35.0, drift=0.0)  # ratio 28.57
    assert "percent" not in _en(block["gloss"])
    assert "2857" not in _en(block["gloss"]) and "2859" not in _en(block["gloss"])
    assert "did not come out usable" in _en(block["gloss"])
    assert "%" not in _en(block["gloss"])
    # The ROWS stay honest — the defect was the ratio and the gloss, never the bars.
    assert _en(next(r for r in block["rows"] if r["label"] == "Your policy")["value"]) == "1,000 kWh"
    assert _en(next(r for r in block["rows"] if r["label"] == "Perfect foresight")["value"]) == "35 kWh"


def test_capture_ratio_exactly_one_is_a_result_not_a_fault():
    """A policy that exactly matches the bound is the best possible outcome, not a broken one.

    Guards the float slack on the range test: the drift correction subtracts one computed quantity
    from another and can land at 1.0000000000000024, which without the tolerance would be reported
    as a fault. Measured on the reproduction in
    `test_capture_ratio_shape_2_reproduces_the_reported_defect_end_to_end`.
    """
    block = _shape_block(policy_saved=1000.0, pf_saved=1000.0, drift=0.0)
    assert "captures 100 percent" in _en(block["gloss"])
    assert "did not come out usable" not in _en(block["gloss"])


def test_positive_drift_does_not_trigger_the_correction():
    """Only a NEGATIVE drift funds a saving out of opening charge; a positive one needs no guard.

    A battery that ends MORE charged has energy it bought and still holds counted as consumed, so
    its raw ratio understates the policy. Understating is not the failure mode this guards against,
    and correcting it would inflate a figure §6.11 wants reported conservatively.
    """
    block = _shape_block(policy_saved=400.0, pf_saved=1000.0, drift=+200.0)
    assert "captures 40 percent" in _en(block["gloss"])
    assert "less charged than it started" not in _en(block["gloss"])


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
    assert "less charged than it started" not in _en(_shape_block(
        policy_saved=saving, pf_saved=2000.0, drift=below
    )["gloss"])
    assert "less charged than it started" in _en(_shape_block(
        policy_saved=saving, pf_saved=2000.0, drift=above
    )["gloss"])


# ══ Phase 6 — the §2.4 COST SAVINGS section ═══════════════════════════════════════════════════
#
# Six groups, in the order the deliverable is built:
#
#   * fixture 18 — the central invariant: every ENERGY figure bit-identical across the toggle,
#     asserted BLOCK BY BLOCK rather than on a sample, because §6.14 says each of the three known
#     ways to break it lands in a different block;
#   * fixture 19 — the shape without cost: `cost`, `cost_benchmark` and the monthly euro series
#     absent, never 0.0;
#   * the arithmetic, checked against `compute_costs` DIRECTLY so the panel cannot disagree with
#     the domain layer;
#   * the display/JSON split on zero waterfall lines;
#   * the money box's capture-ratio shapes, which are NOT the energy box's four (H10);
#   * the energy-only affordance.
#
# The windows are ONE DAY of hourly data throughout. Where a DP is involved the deliverable's own
# warning applies — run D and run E are ~2.3 s per pass — so `with_benchmark=True` appears only in
# the tests that are about the boxes, and never over a long window.

from app.domain.simconfig import SimulationConfig  # noqa: E402
from app.i18n import num  # noqa: E402
from app.results_view import (  # noqa: E402
    WATERFALL_DISPLAY_EPS_EUR,
    _cost_benchmark_block,
)
from tests.test_data_summary import _price  # noqa: E402


def _cost_cfg(**kw) -> SimulationConfig:
    """Appendix-A defaults with `simulate_cost` ON, plus any overrides.

    `simulate_cost` is set AFTER construction deliberately: `SimulationConfig` applies its forcing
    on READ (the `economic_guard` property), so this is the same state a user's persisted config
    reaches through panel ②, not a special constructor path.
    """
    cfg = SimulationConfig(**kw)
    cfg.simulate_cost = True
    return cfg


# A day of prices with a real spread, so the bill is not a constant times a total and a sign error
# somewhere in §6.10 has somewhere to show up. Six cheap hours, eighteen ordinary ones.
_PRICES = [0.30 if h in (7, 8, 17, 18, 19, 20) else 0.04 for h in range(24)]


def _cost_dataset():
    """Import, export, PV and a spot price — every waterfall line has an input that can move it."""
    return _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.5),
        _energy("solar_production", 3.0),
        _price("price_spot", _PRICES),
    ])


# ── Fixture 18: cost-invariance of the energy results ────────────────────────────────────────


def test_fixture_18_every_energy_block_is_bit_identical_across_the_cost_toggle():
    """§6.14 fixture 18, block by block — the central invariant of the optional-cost design.

    The same dataset and the same battery, run once with `simulate_cost = true` and once with it
    false. §4.5: "no field switches units, no field switches basis, and no figure already on
    screen moves". The assertions below walk each block SEPARATELY rather than comparing one
    sampled number, because §6.14 names three distinct failures and each lands in a different
    block:

      * a difference in the ENERGY figures or the SoC trace means a cost term has leaked into the
        dispatch path, most likely `economic_guard`;
      * a difference in the energy BENCHMARK means the perfect-foresight DP was retargeted at
        euros instead of a second DP being added;
      * a difference in the CAVEATS or the monthly kWh chart would mean a diagnostic is selecting
        its basis from `simulate_cost`.

    The comparison is on the rendered ENGLISH text of every figure and sentence, which is stricter
    than comparing floats: it catches a change of format kind (kWh → euro) as well as a change of
    value, and those are exactly the two ways a "figure already on screen" can move.
    """
    ds = _cost_dataset()
    off = results_from(ds, (_WIN_START, _WIN_END), cfg=SimulationConfig())
    on = results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert off is not None and on is not None

    # Block 1 — the KPI tiles. Title, value, unit and both sub-lines.
    assert [(k["title"], _en(k["value"]), k.get("unit"), _en(k.get("delta", "")),
             _en(k.get("extra", ""))) for k in off["kpis"]] == \
           [(k["title"], _en(k["value"]), k.get("unit"), _en(k.get("delta", "")),
             _en(k.get("extra", ""))) for k in on["kpis"]]

    # Block 2 — "Where the energy comes from", label for label and figure for figure, including
    # the rule/gap flags that decide where the subtraction line is drawn.
    assert [(r["label"], _en(r["value"]), r.get("rule_above"), r.get("gap_above"))
            for r in off["energy_breakdown"]] == \
           [(r["label"], _en(r["value"]), r.get("rule_above"), r.get("gap_above"))
            for r in on["energy_breakdown"]]

    # Block 3 — the secondary metrics (self-consumption's presence is itself a §6.11 statement).
    assert [(r["label"], _en(r["value"])) for r in off["secondary"]] == \
           [(r["label"], _en(r["value"])) for r in on["secondary"]]

    # Block 4 — the kWh chart. Same buckets, same values. §2.4: the Charts box GAINS an option,
    # it does not swap the series it already had.
    assert off["chart"] == on["chart"]

    # Block 5 — the window/coverage line. §4.5 puts `window` and `series` permanently off the
    # nullable list: they describe the input data, which the cost model does not touch.
    for key in ("period", "period_dates", "period_days", "period_selected", "benchmark_request"):
        assert off[key] == on[key], key
    assert _en(off["period_run"]) == _en(on["period_run"])

    # Block 6 — the CAVEATS. §2.4 says the kWh caveats are "identical across the toggle" and the
    # euro ones are an addition, so the energy ones appear unchanged, in the same order, at the
    # head of the longer list, with the standing parameter-set note still last on both.
    #
    # ONE exception, which §2.4 asks for by name rather than forbids: §7.2 item 9's negative-saving
    # caveat ends "a euro quantity this energy-only run does not compute", which is false once
    # euros ARE computed and would contradict the section directly below it. That is prose about
    # what the panel can tell you, not a figure, and fixture 18 governs the FIGURES. The
    # substitution itself is pinned by
    # `test_the_negative_saving_caveat_stops_disclaiming_euros_once_euros_exist`; here it is
    # normalised out by its opening clause, and the assertion is that it is the ONLY difference —
    # same count, same positions, same text everywhere else.
    def _key(text: str) -> str:
        return "NEGATIVE_SAVING" if "MORE from the grid" in text else text

    energy_caveats = [_key(c) for c in _caveats(off)]
    on_caveats = [_key(c) for c in _caveats(on)]
    assert on_caveats[:len(energy_caveats) - 1] == energy_caveats[:-1]
    # …and the standing parameter-set note is still last on both, verbatim.
    assert _caveats(on)[-1] == _caveats(off)[-1]
    # The kWh FIGURE inside the substituted caveat is identical on both sides, which is the part
    # fixture 18 is actually about.
    import re as _re
    off_neg = next((c for c in _caveats(off) if "MORE from the grid" in c), None)
    if off_neg is not None:
        on_neg = next(c for c in _caveats(on) if "MORE from the grid" in c)
        assert _re.search(r"([\d,]+) kWh MORE", off_neg).group(1) == \
               _re.search(r"([\d,]+) kWh MORE", on_neg).group(1)

    # Block 7 — the data-glance band over the selected range.
    assert json.dumps(off["data_summary"], sort_keys=True, default=str) == \
           json.dumps(on["data_summary"], sort_keys=True, default=str)


def test_fixture_18_the_per_interval_soc_trace_is_bit_identical():
    """The SoC trace, not just the totals — §6.14 fixture 18 says "down to the per-interval trace".

    Asserted against the SIMULATION directly rather than through the view-model, because the view
    does not carry the trace and the invariant is about the dispatch. This is the assertion that
    catches a cost term reaching `economic_guard`: totals can coincide while the path differs, and
    §6.14 names that failure specifically.
    """
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    ds = _cost_dataset()
    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert frame is not None
    off = run_all(frame, SimulationConfig())
    on = run_all(frame, _cost_cfg())
    for run in ("a", "b", "c"):
        np.testing.assert_array_equal(
            getattr(off, run).soc, getattr(on, run).soc, err_msg=f"run {run} SoC trace"
        )
        np.testing.assert_array_equal(getattr(off, run).imp, getattr(on, run).imp)
        np.testing.assert_array_equal(getattr(off, run).exp, getattr(on, run).exp)


def test_fixture_18_the_energy_benchmark_is_bit_identical_across_the_toggle():
    """§6.14 fixture 18's second named failure: the energy DP must not be RETARGETED at euros.

    The whole `benchmark` block — rows, bar fractions and the gloss — is identical with cost
    simulation on and off. A cost benchmark being ADDED is what this phase does; the energy one
    changing would mean run E replaced run D rather than joining it. Fixture 20 makes the same
    point from the other side, in tests/test_benchmark.py.

    One day of hourly data, so the two DP passes are cheap.
    """
    ds = _cost_dataset()
    off = results_from(ds, (_WIN_START, _WIN_END), cfg=SimulationConfig(), with_benchmark=True)
    on = results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg(), with_benchmark=True)
    assert off is not None and on is not None
    assert [(r["label"], _en(r["value"]), r["frac"], r["dot"]) for r in off["benchmark"]["rows"]] \
        == [(r["label"], _en(r["value"]), r["frac"], r["dot"]) for r in on["benchmark"]["rows"]]
    assert _en(off["benchmark"]["gloss"]) == _en(on["benchmark"]["gloss"])
    # And the money box is the thing that appeared. Its presence is the point of the phase; its
    # absence on the left is fixture 19's.
    assert "cost_benchmark" not in off
    assert "cost_benchmark" in on


# ── Fixture 19: the energy-only shape ────────────────────────────────────────────────────────


def test_fixture_19_cost_is_absent_wholesale_never_zero():
    """§6.14 fixture 19 / §4.5: with `simulate_cost = false` the euro fields are null, NEVER 0.0.

    §4.5 nulls the whole BLOCK rather than every leaf, and says why: "not an object of null
    fields, and in particular not a `waterfall` array of eight null-valued entries, which would
    invite a template to render eight empty rows". So the assertion is on the block, and it also
    checks the failure mode §4.5 names — a present-but-empty `cost` would satisfy a naive
    falsiness test while still handing the template eight rows to draw.
    """
    r = results_from(_cost_dataset(), (_WIN_START, _WIN_END), cfg=SimulationConfig())
    assert r is not None
    assert r["cost"] is None
    assert r["monthly_saved_eur"] is None
    assert r["simulate_cost"] is False
    # Not zero, and not an empty shell: the two failure modes §4.5 names by name.
    assert r["cost"] != 0.0
    assert not isinstance(r["cost"], dict)
    # `benchmarks.cost`'s view-model counterpart is an ABSENT key, on the same convention the
    # energy benchmark already uses for "the DP did not run".
    assert "cost_benchmark" not in r
    # …while every ENERGY figure is fully populated. Fixture 19: "benchmarks.energy is fully
    # populated" and the kWh diagnostics are computed rather than None.
    assert r["kpis"] and r["energy_breakdown"] and r["chart"]["values"]


def test_fixture_19_a_zero_euro_saving_is_still_a_number_not_a_null():
    """The converse of fixture 19: with cost ON, a saving that comes out to zero is 0.0, not null.

    Guards the reading that "absent means zero". A window whose battery does nothing still has two
    bills and a difference between them; if that difference is zero the block says zero. Only the
    TOGGLE produces a null.
    """
    # A zero-capacity battery cannot move anything, so cost(A) == cost(C) exactly.
    cfg = _cost_cfg()
    cfg.battery.usable_capacity_kwh = 0.0
    cfg.battery.standby_w = 0.0
    r = results_from(_cost_dataset(), (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None and r["cost"] is not None
    assert r["cost"]["saved_eur"] == pytest.approx(0.0, abs=1e-9)
    assert r["cost"]["saved_eur"] is not None


# ── The arithmetic, against the domain layer directly ────────────────────────────────────────


def test_the_cost_block_agrees_with_compute_costs_line_for_line():
    """Every euro figure the panel shows is re-derived here from §6.10 DIRECTLY.

    The panel must not be able to disagree with the domain layer — that is the whole reason
    `results_view` calls `compute_costs` rather than re-implementing a bill. So this test builds
    the price curves and bills runs A and C itself, and asserts the block's four scalars and its
    eight waterfall entries against those.

    It also pins the two identities §4.5 and §6.10 assert:
      * `saved_eur == baseline_eur − battery_eur`, and
      * the eight lines close on that difference (fixture 4), so the "Net saving" row the box
        prints under its rule is the same number as the KPI tile above it.
    """
    from app.domain.costs import WATERFALL_LINES, compute_costs, waterfall
    from app.domain.pricing import price_curves
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    ds = _cost_dataset()
    cfg = _cost_cfg()
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None
    cost = r["cost"]

    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert frame is not None
    runs = run_all(frame, cfg)
    curves = price_curves(cfg.pricing, frame.spot)
    args = (curves.p_import, curves.p_export_net, curves.compensation, frame.index, cfg.pricing)
    cost_a = compute_costs(runs.a, *args)
    cost_c = compute_costs(runs.c, *args)

    assert cost["currency"] == "EUR"
    assert cost["baseline_eur"] == pytest.approx(cost_a.eur, abs=1e-12)
    assert cost["battery_eur"] == pytest.approx(cost_c.eur, abs=1e-12)
    assert cost["saved_eur"] == pytest.approx(cost_a.eur - cost_c.eur, abs=1e-12)
    assert cost["saved_pct"] == pytest.approx(
        100 * (cost_a.eur - cost_c.eur) / cost_a.eur, abs=1e-9
    )

    tlk = float(np.nanmax(np.asarray(curves.compensation) - np.asarray(curves.p_export_net)))
    lines = waterfall(runs.a, runs.b, runs.c, curves.p_import, curves.compensation, tlk,
                      cfg.pricing, frame.index, curves.p_export_net)
    # The JSON waterfall is complete, in §6.10's order, at the domain layer's own values.
    assert [ln["label"] for ln in cost["waterfall"]] == list(WATERFALL_LINES)
    for got, want in zip(cost["waterfall"], lines):
        assert got["eur"] == pytest.approx(want.eur, abs=1e-12), got["label"]
    # Fixture 4's closure, restated on what the PANEL carries: the eight lines account for the
    # whole difference between the two bills, with the degradation term on both sides.
    total = sum(ln["eur"] for ln in cost["waterfall"])
    degradation = next(ln["eur"] for ln in cost["waterfall"] if ln["label"] == "degradation")
    assert total == pytest.approx(cost["saved_eur"] + degradation, abs=1e-6)


def test_the_money_tile_states_the_two_bills_it_is_the_difference_of():
    """§2.4's tile: "€ 1,153 without a battery → € 822 with one", and a signed percentage.

    The sentence is a `_msg` pair whose two halves are figures, so it is asserted on the rendered
    ENGLISH — the same discipline every other sentence assertion in this file follows.
    """
    r = results_from(_cost_dataset(), (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert r is not None
    kpi = r["cost"]["kpi"]
    assert kpi["title"] == "MONEY SAVED"
    assert kpi["unit"] == "€"
    sentence = _en(kpi["sentence"])
    assert "without a battery" in sentence and "with one" in sentence
    # Both bills appear, formatted as euro amounts with the symbol ahead of the digits.
    assert sentence.count("€") == 2
    # The delta is a signed percentage, which is how the reader tells a saving from a cost.
    assert _en(kpi["delta"]).startswith(("+", "−"))


def test_the_euro_figures_are_formatted_in_the_render_locale():
    """A6, in euros: Dutch writes € 1.153 where English writes € 1,153.

    The euro amounts are `num()` figures, not strings, for the same reason every other figure on
    this panel is. Asserted on a value with a thousands separator, since that is where the two
    conventions differ.
    """
    from app.i18n import format_num

    assert format_num(1153.2, "eur", "en") == "€ 1,153"
    assert format_num(1153.2, "eur", "nl") == "€ 1.153"
    # The sign sits AHEAD of the symbol (§2.4's waterfall column), with U+2212 for the minus.
    assert format_num(-141.3, "eur_force_signed", "en") == "− € 141"
    assert format_num(402.1, "eur_force_signed", "en") == "+ € 402"


# ── The display / JSON split on zero lines ───────────────────────────────────────────────────


def test_zero_waterfall_lines_are_dropped_from_the_display_but_kept_in_the_json():
    """§2.4 exactly: "dropped from the display, never from `cost.waterfall`".

    A no-PV household exports nothing, so `avoided_terugleverkosten`, `lost_feedin_compensation`,
    `arbitrage_export_revenue` and `feedin_floor_topup` are all structurally zero. §2.4's "Panel ③
    without PV" section says to test the VALUE rather than `has_pv`, and to keep the JSON
    complete so it "must continue to close against cost(A) − cost(C)".

    So: eight entries in `waterfall`, and none of those four labels among the rendered rows.
    """
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", _PRICES),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert r is not None
    cost = r["cost"]

    assert len(cost["waterfall"]) == 8
    zero_labels = {
        "avoided_terugleverkosten", "lost_feedin_compensation",
        "arbitrage_export_revenue", "feedin_floor_topup",
    }
    for line in cost["waterfall"]:
        if line["label"] in zero_labels:
            assert abs(line["eur"]) < WATERFALL_DISPLAY_EPS_EUR, line

    shown = [row["label"] for row in cost["waterfall_rows"]]
    for absent in ("Avoided terugleverkosten", "Lost feed-in compensation",
                   "Grid arbitrage export revenue", "Feed-in floor top-up"):
        assert absent not in shown
    # The closing row is always there, and it is the §2.4 "Net saving" row under a rule.
    assert shown[-1] == "Net saving"
    assert cost["waterfall_rows"][-1]["rule_above"] is True
    assert _en(cost["waterfall_rows"][-1]["value"]) == _en(num(cost["saved_eur"],
                                                              "eur_force_signed"))


def test_the_drop_threshold_matches_what_the_rows_actually_round_to():
    """§2.4's drop rule is about the DISPLAY, so the threshold has to key on the rows' rounding.

    The rows render with pattern `#,##0` — whole euros — so anything under €0.50 reaches the
    reader as "€ 0" whatever its true magnitude. A threshold below that lets rows through that
    print as zero, which is precisely the column of "€ 0" the rule exists to prevent: it reads as
    figures that failed to compute rather than as figures too small to matter.

    Pinned as a RELATIONSHIP between the constant and the format kind, not as a literal, so giving
    the rows cents later fails here rather than silently reinstating the mismatch. Regression:
    the constant was once 0.005 — half a cent, the currency's precision rather than the row's —
    and a line at €0.49 survived the filter to render "€ 0".
    """
    # Everything the filter keeps must render as a nonzero figure...
    for value in (0.51, 0.75, -0.51, 12.0):
        assert abs(value) > WATERFALL_DISPLAY_EPS_EUR
        assert _en(num(value, "eur_force_signed")) not in ("€ 0", "+ € 0", "− € 0")
    # ...and everything it drops would have rendered as zero. Note €0.50 itself is DROPPED: the
    # rows round half-to-even, so 0.5 prints "€ 0" while 0.500001 prints "+ € 1", which is why the
    # filter's comparison is `<=` rather than `<`.
    for value in (0.0, 0.004, 0.30, 0.49, -0.49, 0.5, -0.5):
        assert abs(value) <= WATERFALL_DISPLAY_EPS_EUR
        assert _en(num(value, "eur_force_signed")) == "€ 0"


def test_a_disabled_degradation_line_is_shown_as_disabled_rather_than_dropped():
    """§4.5's `"enabled": false`, and why it is the exception to the drop rule.

    Appendix A's default degradation rate is 0.0 ("Disabled"), so the line's VALUE is zero — but
    `app/domain/costs.py` is explicit that deciding a line is disabled is a statement about the
    CONFIG, not about the computed number. Dropping the row would lose that statement; printing
    "€ 0" would assert a measurement. §2.4's wireframe prints the word, and so does the box.
    """
    r = results_from(_cost_dataset(), (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert r is not None
    row = next(row for row in r["cost"]["waterfall_rows"] if row["label"] == "Degradation cost")
    assert row["disabled"] is True
    assert _en(row["value"]) == "disabled"
    assert "€" not in _en(row["value"])
    # The JSON entry carries §4.5's flag alongside the figure.
    entry = next(ln for ln in r["cost"]["waterfall"] if ln["label"] == "degradation")
    assert entry["enabled"] is False


def test_a_nonzero_degradation_rate_makes_the_line_an_ordinary_figure():
    """The converse: with a rate SET, the row is a euro figure and obeys the ordinary drop rule.

    This is what makes the previous test a statement about the config rather than about the label
    "degradation" being special-cased.
    """
    cfg = _cost_cfg()
    # Large enough that the line survives the whole-euro rounding the box prints in — the window
    # is one day and the battery withdraws a handful of kWh, so appendix A's order of magnitude
    # would round to "€ 0" and say nothing about the flag under test.
    cfg.pricing.degradation_eur_per_kwh = 5.0
    r = results_from(_cost_dataset(), (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None
    row = next(row for row in r["cost"]["waterfall_rows"] if row["label"] == "Degradation cost")
    assert not row.get("disabled")
    assert "€" in _en(row["value"])
    # Degradation is a COST, so the line is negative and shows its sign (§6.10's convention).
    assert _en(row["value"]).startswith("−")
    entry = next(ln for ln in r["cost"]["waterfall"] if ln["label"] == "degradation")
    assert "enabled" not in entry


# ── The money box's capture ratio — THREE shapes, not the energy box's four (H10) ─────────────


def _cost_shape_block(*, policy_eur: float, pf_eur: float, drift: float,
                      floor_binds: bool = False, unconstrained: float | None = None):
    """A `_cost_benchmark_block` from a synthetic `CostBenchmark` with a chosen saving and drift.

    Synthetic for the same reason `_shape_block` is: the shapes under test are presentation
    decisions keyed on a ratio and a drift, and steering a real DP to a chosen ratio would be
    neither possible nor informative.
    """
    from app.domain.benchmark import CostBenchmark, _capture_ratio

    return _cost_benchmark_block(
        CostBenchmark(
            no_battery_eur=0.0,
            policy_eur=policy_eur,
            perfect_foresight_eur=pf_eur,
            capture_ratio=_capture_ratio(policy_eur, pf_eur),
            perfect_foresight_eur_unconstrained=unconstrained,
            capture_ratio_unconstrained=(
                _capture_ratio(policy_eur, unconstrained) if unconstrained is not None else None
            ),
            bound_eur=1000.0 - pf_eur,
            bound_eur_unconstrained=None,
            baseline_eur=1000.0,
            policy_bill_eur=1000.0 - policy_eur,
            soc_start_kwh=5.0,
            soc_end_kwh=5.0,
            median_import_price_eur_kwh=0.30,
            floor_binds=floor_binds,
            policy_soc_delta_kwh=drift,
        ),
        _cost_cfg(),
    )


def test_cost_capture_ratio_shape_1_normal_renders_a_percentage_and_says_why_it_differs():
    """Drift immaterial and 0 ≤ ratio ≤ 1: a plain percentage, plus §2.4's one-line explanation.

    §2.4 requires the money box to say in one line that its ceiling comes from a different
    dispatch than the energy box's — "a battery that buys cheaply imports more, not less" — so
    that two different capture percentages on one panel read as information rather than as an
    inconsistency.
    """
    block = _cost_shape_block(policy_eur=69.0, pf_eur=100.0, drift=-0.01)
    gloss = _en(block["gloss"])
    assert "captures 69 percent" in gloss
    assert "buying cheaply is not the same as importing little" in gloss
    assert "%" not in gloss
    assert block["title"] == "Benchmark: money saved"


def test_cost_capture_ratio_shape_2_drift_funded_prints_no_ratio_and_no_restatement():
    """**Shape 2 does not carry over from the energy box.** Follow-up H10, and CostBenchmark's own
    docstring: §6.12's `saved + soc_delta × eta_d` correction is exact in kWh and has NO sound euro
    analogue, because a residual kWh's euro worth depends on WHEN it is used and the DP's terminal
    constraint and a liquidating policy use it at different times by construction.

    So the money box does the thing the energy box does not: it prints no number at all, and it
    does not restate one on a corrected basis either. Both failure modes are asserted — a raw
    percentage AND a corrected one — because reaching for the corrected form is the specific
    mistake H10 exists to prevent, and it is the one a reader of `_benchmark_block` would make.
    """
    # A 200 kWh liquidation against a €40 saving: at the €0.30 median that residual is worth ~€57,
    # far above 2% of the saving, so the drift is material by §6.11's own threshold.
    block = _cost_shape_block(policy_eur=40.0, pf_eur=100.0, drift=-200.0)
    gloss = _en(block["gloss"])
    assert "percent" not in gloss
    assert "%" not in gloss
    # Neither the raw ratio (40%) nor any drift-corrected restatement of it.
    assert "40 percent" not in gloss
    assert "captures" not in gloss
    # What it says INSTEAD: the drift, and that the comparison is unavailable in euros.
    assert "less charged than it started" in gloss
    assert "in euros they cannot" in gloss
    assert "no capture ratio is shown" in gloss.lower()
    # The residual is named in KILOWATT-HOURS — the quantity that is actually measured. Converting
    # it to euros here would be the correction the block does not have.
    assert "200 kWh" in gloss


def test_cost_capture_ratio_above_one_from_a_liquidating_policy_is_not_a_percentage():
    """The COMMON case, measured: 48 of 144 swept configurations exceed 1, all liquidating.

    A ratio of 1.60 with a materially negative drift is drift-funding, not a fault — and it must
    not reach the reader as "captures 160 percent", which is the presentation defect this whole
    branch exists to prevent. `CostBenchmark`'s docstring: "a view MUST NOT print this as a plain
    percentage, and must not reach for a drift-corrected euro restatement either".
    """
    block = _cost_shape_block(policy_eur=160.0, pf_eur=100.0, drift=-300.0)
    gloss = _en(block["gloss"])
    assert "160" not in gloss
    assert "percent" not in gloss and "%" not in gloss
    assert "less charged than it started" in gloss
    # The ROWS stay honest — the defect was the ratio and the gloss, never the bars. §7.2 item 9's
    # discipline, in euros.
    assert _en(next(r for r in block["rows"] if r["label"] == "Your policy")["value"]) == "€ 160"
    assert _en(next(r for r in block["rows"]
                    if r["label"] == "Perfect foresight")["value"]) == "€ 100"


def test_cost_capture_ratio_above_one_WITHOUT_drift_is_reported_as_a_fault():
    """`CostBenchmark`: "A ratio above 1 with NON-negative drift is the case that is a genuine
    fault." It gets the energy box's fault wording — one condition, one sentence, on either box.
    """
    block = _cost_shape_block(policy_eur=160.0, pf_eur=100.0, drift=0.0)
    gloss = _en(block["gloss"])
    assert "did not come out usable" in gloss
    assert "160" not in gloss
    assert "percent" not in gloss and "%" not in gloss


def test_cost_capture_ratio_bound_near_zero_branches_on_the_visible_policy_row():
    """§2.4: "A box must never assert that nothing was achievable directly above a visible
    non-zero policy figure." The same rule the energy box obeys, in euros.
    """
    # Policy also ~0: the plain "nothing was achievable" wording is TRUE and is used.
    quiet = _en(_cost_shape_block(policy_eur=0.0, pf_eur=0.0, drift=0.0)["gloss"])
    assert "could not have saved any money" in quiet
    # Policy visibly positive: the wording must not contradict the row above it.
    loud = _en(_cost_shape_block(policy_eur=9.0, pf_eur=0.0, drift=0.0)["gloss"])
    assert "€ 9" in loud
    assert "not something a perfectly-informed battery could reproduce" in loud
    assert "no capture ratio to report" in loud


def test_the_export_row_and_sentence_appear_only_when_the_two_bounds_diverge():
    """§2.4's conditional fourth row, on the money box — where it is EXPECTED to earn its keep.

    `CostBenchmark`'s docstring: the unconstrained reading "bites HARDER here than on the energy
    side", because exporting into a high-price hour is the whole arbitrage case while an export
    permission cannot change an import-minimising dispatch. So this row, rare on the energy box, is
    the one the money box is built to show.
    """
    # Divergent: 0.69 vs 0.55, well past appendix A's 0.02 threshold.
    wide = _cost_shape_block(policy_eur=69.0, pf_eur=100.0, drift=0.0, unconstrained=125.0)
    assert [r["label"] for r in wide["rows"]][-1] == "…if export allowed"
    assert "Allowed to export" in _en(wide["gloss"])
    # Near-identical bounds: §2.4 says a near-duplicate line "says nothing", so it is omitted.
    narrow = _cost_shape_block(policy_eur=69.0, pf_eur=100.0, drift=0.0, unconstrained=100.5)
    assert "…if export allowed" not in [r["label"] for r in narrow["rows"]]
    assert "Allowed to export" not in _en(narrow["gloss"])


def test_floor_binds_adds_a_disclosure_rather_than_suppressing_the_box():
    """Follow-up H11: run E's bound is on the PRE-TOP-UP bill wherever the feed-in floor binds.

    The top-up is `max(0, −Σ_period export × compensation)` — a function of a whole assessment
    period — so it cannot be priced inside `transition_cost` without a second DP state dimension,
    and is applied afterwards. In a window where it binds, a policy could in principle beat the
    full-bill figure by stumbling into a larger top-up, and H11 records that how large such a
    violation could get HAS NOT BEEN MEASURED.

    The chosen disclosure: show the figure and append one sentence saying the ceiling is soft and
    in which direction. Suppressing the box would overreact to a rare condition on a bound that is
    still informative; printing the figure unqualified is what `floor_binds` exists to prevent.
    The note is SEPARATE from the gloss because it qualifies the ceiling whatever shape the gloss
    took.
    """
    ordinary = _cost_shape_block(policy_eur=69.0, pf_eur=100.0, drift=0.0)
    assert "note" not in ordinary

    binding = _cost_shape_block(policy_eur=69.0, pf_eur=100.0, drift=0.0, floor_binds=True)
    note = _en(binding["note"])
    assert "feed-in floor" in note
    assert "approximate" in note
    # It names the DIRECTION the bound is soft in, which is what makes it actionable rather than
    # merely worrying.
    assert "larger top-up" in note
    # And the box still says what it was going to say.
    assert "captures 69 percent" in _en(binding["gloss"])


# ── The monthly euro series ──────────────────────────────────────────────────────────────────


def test_monthly_saved_eur_buckets_like_the_kwh_series_and_sums_to_the_saving():
    """§4.5's `monthly[].saved_eur` and §2.4's second chart option.

    Two properties, both load-bearing for the chart being two VIEWS rather than two series: the
    euro buckets line up one-for-one with the kWh ones (so a month's two bars describe one
    window), and over a window where the feed-in floor does not bind they sum to the headline
    `saved_eur`. The floor case is the documented exception — the top-up has no per-interval
    allocation — and it raises its own caveat when it happens.
    """
    r = results_from(_cost_dataset(), (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert r is not None
    assert len(r["monthly_saved_eur"]) == len(r["chart"]["values"])
    assert sum(r["monthly_saved_eur"]) == pytest.approx(r["cost"]["saved_eur"], abs=1e-9)


# ── The energy-only affordance, and the section's presence ───────────────────────────────────


def test_the_cost_section_is_absent_and_the_affordance_offered_when_cost_is_off():
    """§2.4 "Panel ③ without cost simulation", on the view-model side.

    The section's presence is a single key, which is what lets the template gate it with one
    `{% if %}` — §4.5's stated reason for nulling the block wholesale. The affordance itself is
    template chrome (a fixed sentence and a link), so it is asserted in the ROUTE tests, where the
    rendered page is; here we pin the condition the template branches on.
    """
    ds = _cost_dataset()
    off = results_from(ds, (_WIN_START, _WIN_END), cfg=SimulationConfig())
    on = results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert off is not None and on is not None
    assert not off["cost"]
    assert on["cost"]


def test_the_euro_caveats_appear_only_with_cost_simulation_on():
    """§2.4: "The caveats that qualify a euro figure … appear only with cost simulation on,
    because there is no euro figure to qualify." The kWh ones are identical across the toggle,
    which fixture 18 above asserts; this is the other half of that statement.
    """
    ds = _cost_dataset()
    off = _caveats(results_from(ds, (_WIN_START, _WIN_END), cfg=SimulationConfig()))
    on = _caveats(results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg()))
    assert len(on) > len(off)
    added = " ".join(c for c in on if c not in off)
    # This fixture's saving is negative, so §7.2 item 9's caveat is present and is the ONE energy
    # caveat whose wording differs across the toggle — its cost-off form disclaims a euro figure
    # that, with cost on, is stated directly below it. Pinned in its own test; excluded here so
    # this test stays about the euro caveats being an ADDITION.
    _SUBSTITUTED = "MORE from the grid"
    # What the marginal bill IS — the standing-charge exclusion §6.10 makes and §2.4's tile
    # sentence could otherwise be read as contradicting.
    assert "vastrecht" in added
    assert "not two invoice totals" in added
    # And that the tariffs behind it are not yet published (appendix A calls the terugleverkosten
    # rate an explicit placeholder).
    assert "not yet published" in added
    assert "placeholder" in added
    for text in off:
        if _SUBSTITUTED in text:
            continue
        assert text in on


def test_the_negative_saving_caveat_stops_disclaiming_euros_once_euros_exist():
    """§7.2 item 9's caveat has two wordings, and the cost-on one must not contradict the section
    below it.

    The energy-only wording ends "a euro quantity this energy-only run does not compute". With
    cost simulation on that sentence is simply false — the COST SAVINGS section states that very
    quantity a few centimetres further down the page — so the cost-on variant keeps the
    explanation of why the kWh figure is negative and POINTS AT the euro figure instead of
    disclaiming it.

    Fixture 18 is unaffected: it governs the energy FIGURES, and §2.4 explicitly has the caveats
    box gain euro-qualifying text when euros are modelled. The cost-OFF wording is unchanged,
    which is what a reader comparing the two modes actually checks.
    """
    # 2 kWh/h of import, no PV, no export: the battery's round-trip losses and standby exceed
    # what its bands recover, so the kWh saving comes out negative (the fixture the energy-only
    # tests above already use), and a price series makes the euro side computable.
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", _PRICES),
    ])
    cfg = SimulationConfig()
    cfg.battery.usable_capacity_kwh = 0.5   # tiny store, so standby dominates
    off = results_from(ds, (_WIN_START, _WIN_END), cfg=cfg)
    cfg_on = SimulationConfig()
    cfg_on.battery.usable_capacity_kwh = 0.5
    cfg_on.simulate_cost = True
    on = results_from(ds, (_WIN_START, _WIN_END), cfg=cfg_on)
    assert off is not None and on is not None

    off_text = " ".join(_caveats(off))
    on_text = " ".join(_caveats(on))
    assert "MORE from the grid" in off_text and "MORE from the grid" in on_text
    # Cost off: the disclaimer stands, unchanged.
    assert "this energy-only run does not compute" in off_text
    assert "cannot tell you whether the battery is worth buying" in off_text
    # Cost on: it is gone, replaced by a pointer to the figures that answer the question.
    assert "this energy-only run does not compute" not in on_text
    assert "read the cost savings below" in on_text
    # And the kWh figure it quotes is the SAME on both sides — fixture 18 is about the figures.
    import re as _re
    assert _re.search(r"([\d,]+) kWh MORE", off_text).group(1) == \
           _re.search(r"([\d,]+) kWh MORE", on_text).group(1)


# ── §6.16: the pricing-uncertainty width ─────────────────────────────────────────────────────
#
# What is under test is a NUMBER, not a sentence — the caveat that prints it is the next
# increment. So these assert the view-model's `price_bracket` directly.
#
# The fixture that produces a real spread is a QUARTER-HOURLY price series against HOURLY energy
# series. `simulation_frame` puts the run on the energy grid (3600 s) and collapses the four
# quarter-hour prices per hour, which is exactly the D1 condition the bracket keys on: min/max
# over the intervals that were actually collapsed. An hourly price series collapses nothing and
# must therefore report no width at all.

from app.domain.simconfig import SupplierSettlement  # noqa: E402


def _price_15min(name: str, values, n: int = HOURS * 4) -> "SeriesFrame":  # noqa: F821
    """A 15-minute price series over the same window `_price` covers hourly.

    Separate from `tests.test_data_summary._price` rather than parameterised into it, because
    every existing caller of that helper depends on its hourly index and on `resolution_s`
    being 3600 — the resolution is what `simulation_frame` reads to decide whether anything is
    being collapsed at all.
    """
    from app.domain.frames import QUALITY_DTYPE, SeriesFrame
    idx = (np.arange(n).astype("timedelta64[s]") * 900
           + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    vals = np.full(n, float(values)) if np.isscalar(values) else np.asarray(values, dtype=float)
    return SeriesFrame(name, "price", 900, idx, vals, np.zeros(n, dtype=QUALITY_DTYPE))


# Four quarters per hour with a wide, deliberately asymmetric intra-hour spread, so the hourly
# mean sits well inside [min, max] and a width that came out zero would mean the collapse was
# not seen rather than that the prices happened to agree.
_QUARTER_PRICES = [
    (0.02, 0.10, 0.40, 0.28)[q] if h in (7, 8, 17, 18, 19, 20) else (0.05, 0.03, 0.06, 0.02)[q]
    for h in range(HOURS) for q in range(4)
]


def _bracket_dataset(prices=None):
    """The `_cost_dataset` shape, but with a quarter-hourly spot price."""
    return _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.5),
        _energy("solar_production", 3.0),
        _price_15min("price_spot", _QUARTER_PRICES if prices is None else prices),
    ])


def _qh_cfg(**kw) -> SimulationConfig:
    """`_cost_cfg`, plus the supplier billing every quarter-hour — D10's gate open."""
    cfg = _cost_cfg(**kw)
    cfg.pricing.supplier_settlement = SupplierSettlement.QUARTER_HOURLY
    return cfg


def test_a_quarter_hourly_price_with_real_spread_produces_a_non_zero_width():
    """The ordinary case §6.16 exists for: hourly energy, quarter-hourly prices, a spread.

    The width is the half-band, so it must be positive and finite, and the fraction must be 1.0
    here — every hour of `_QUARTER_PRICES` has four distinct quarters, so every priced interval
    on the grid carries a spread.
    """
    r = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None
    assert pb.width_eur > 0
    assert np.isfinite(pb.width_eur)
    assert pb.bracketed_fraction == pytest.approx(1.0)


def test_the_three_evaluations_are_ordered_low_central_high():
    """§6.16 fixture 10 on the ordinary fixture: `saved_low <= saved_central <= saved_high`.

    The width is the half-difference and is non-negative, which is the rest of what fixture 10
    names. This is the invariant the caveat depends on: the band it prints must CONTAIN the
    figure beside it. `_price_bracket` gets it by sorting all three evaluations rather than by
    assigning names to the two extremes — the saving is a difference of bills, and a difference
    of bracketed quantities is not itself monotone in the price (see `PriceBracket`).

    Fixture 10's STRICT case — a window where the central figure really does fall outside the
    two extremes, so the sort is load-bearing rather than defensive — is
    `test_the_band_still_contains_the_headline_when_the_two_extremes_do_not` below. This test
    passes on either implementation and does not substitute for it.
    """
    r = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None
    assert pb.saved_low <= pb.saved_central <= pb.saved_high
    assert pb.width_eur == pytest.approx((pb.saved_high - pb.saved_low) / 2.0, abs=1e-12)
    assert pb.width_eur >= 0


def test_the_central_saving_is_exactly_todays_headline_saving():
    """The bracket must not perturb the number it brackets — the point of D5′'s "caveat, not range".

    `saved_central` is asserted to be the SAME float as `cost.saved_eur`, exactly (`==`, not
    approx): the bracket is handed the central saving rather than re-deriving it, so anything
    other than bit-equality would mean a second derivation had crept in. The whole cost block is
    checked against the cost-off run too, so an unrelated leak into the dispatch would show here
    as well as in fixture 18.
    """
    ds = _bracket_dataset()
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None
    assert pb.saved_central == r["cost"]["saved_eur"]

    # And the headline is identical to what the SAME run reports with the supplier billing
    # hourly — i.e. turning the bracket on does not move a euro on screen.
    hourly = results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert hourly is not None
    assert hourly["cost"]["saved_eur"] == r["cost"]["saved_eur"]
    assert hourly["cost"]["waterfall"] == r["cost"]["waterfall"]


def test_hourly_settlement_reports_no_width_even_when_the_price_has_a_spread():
    """D10: if the supplier bills the hourly mean, the hourly price IS what the household paid.

    Same dataset, same spread, only `supplier_settlement` differs — so this isolates the gate
    rather than the data. `None`, not a zero width: there is no uncertainty to state, and a
    printed "±€0" would be a claim about the prices rather than about the contract.
    """
    ds = _bracket_dataset()
    assert results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg())["price_bracket"] is None
    # ... and the same config with the gate open does produce one, so the assertion above is
    # about the gate and not about the fixture failing to have a spread.
    assert results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())["price_bracket"] is not None


def test_a_natively_hourly_price_reports_no_width():
    """D1/D2: nothing was collapsed, so no intra-hour spread is observable.

    `spot_min == spot == spot_max` on every interval, `spread > 0` nowhere, and the bracket is
    absent. This is the case the step-1 note flagged for the caveat copy: it means "not
    measurable from this data", not "measured and found to be nothing" — which is why it is
    None rather than a zero width, and why `bracketed_fraction` exists for the partial case.
    """
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.5),
        _energy("solar_production", 3.0),
        _price("price_spot", _PRICES),          # hourly, resolution_s == 3600
    ])
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    assert r["cost"] is not None                # cost simulation really did run
    assert r["price_bracket"] is None


def test_a_flat_quarter_hourly_price_reports_no_width():
    """Collapsing happened, but the four quarters agreed — so there is still nothing to report.

    Distinct from the hourly case above: here the grid DID collapse four points per interval,
    and the width is legitimately zero. The bracket is still absent, because the caveat has
    nothing to say either way and "±€0" reads as a precision claim.
    """
    ds = _bracket_dataset(prices=[0.12] * (HOURS * 4))
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    assert r["price_bracket"] is None


def test_the_bracketed_fraction_counts_only_priced_intervals_and_only_spread_ones():
    """The partial case: half the window collapses a spread, half is flat.

    Models the real straddle §6.16's D2 describes — a window crossing 2025-10-01, hourly
    settlement before and quarter-hourly after. The fraction must be the share of PRICED
    intervals carrying a spread, so the caveat can say "over part of your window" rather than
    implying the whole of it is uncertain.
    """
    flat_half = [0.12] * (12 * 4)
    spread_half = [(0.05, 0.30, 0.02, 0.19)[q] for _ in range(12) for q in range(4)]
    ds = _bracket_dataset(prices=flat_half + spread_half)
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None
    assert pb.bracketed_fraction == pytest.approx(0.5)
    assert pb.width_eur > 0


def test_nan_intervals_do_not_poison_the_width():
    """A price series with gaps still yields a finite width over the intervals that have one.

    NaN is how an uncovered interval reaches this code (step 1 guarantees `spot_min`/`spot_max`
    are NaN exactly where `spot` is), and a plain `max` over the spread would make the whole
    window's width NaN. The reductions are nan-aware, so the width is finite and the fraction's
    denominator counts only the priced intervals.
    """
    prices = list(_QUARTER_PRICES)
    for i in range(0, 8 * 4):               # first eight hours unpriced
        prices[i] = float("nan")
    ds = _bracket_dataset(prices=prices)
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None
    assert np.isfinite(pb.width_eur) and pb.width_eur > 0
    assert np.isfinite(pb.saved_low) and np.isfinite(pb.saved_high)
    # The gap intervals are excluded from the denominator, not counted as un-bracketed: every
    # interval that HAS a price here also has a spread.
    assert pb.bracketed_fraction == pytest.approx(1.0)


def test_an_all_nan_price_window_yields_no_width_rather_than_nan():
    """No priced interval at all: no spread is knowable, so no width — and no NaN, no crash.

    The guard is an explicit count of non-NaN intervals rather than relying on `nanmax` of an
    empty selection, which returns NaN with a warning and would take the "no spread" branch by
    IEEE accident (`NaN > 0` is False) instead of by decision.
    """
    ds = _bracket_dataset(prices=[float("nan")] * (HOURS * 4))
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    assert r["price_bracket"] is None


def test_the_width_is_absent_when_cost_simulation_is_off():
    """A euro figure has no meaning without the euro pipeline, whatever the settlement says."""
    cfg = SimulationConfig()
    cfg.pricing.supplier_settlement = SupplierSettlement.QUARTER_HOURLY
    r = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None
    assert r["simulate_cost"] is False
    assert r["cost"] is None
    assert r["price_bracket"] is None


def test_the_bracket_is_not_a_field_of_the_cost_block():
    """D5′ dropped the §4.5 `cost.price_bracket` result block; only the width survives.

    Pinned because the obvious place to put the number is inside `cost`, and doing so would put
    a field into a spec-fixed object — with a null-when-off contract and low/central/high public
    fields the decision explicitly removed.
    """
    r = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    assert "price_bracket" not in r["cost"]
    assert "price_bracket" in r


# A second bracket fixture where the battery genuinely changes EXPORT, not only import. The one
# above is import-only (the load reconstruction absorbs all the PV, so runs A and C both export
# nothing), and with `expA == expC` the export half of the price vector cancels out of the
# saving entirely — which makes the by-direction-of-flow split unobservable there. Midday PV
# large enough to spill to the grid in run A, and a battery that soaks part of it in run C,
# restores the term.
_EXPORT_PV = [6.0 if 9 <= h <= 15 else 0.0 for h in range(HOURS)]
_EXPORT_GRID = [5.0 if 9 <= h <= 15 else 0.0 for h in range(HOURS)]
_EXPORT_IMPORT = [0.0 if 9 <= h <= 15 else 1.0 for h in range(HOURS)]


def _exporting_bracket_dataset():
    return _dataset([
        _energy("grid_import_t1", _EXPORT_IMPORT),
        _energy("grid_export_t1", _EXPORT_GRID),
        _energy("solar_production", _EXPORT_PV),
        _price_15min("price_spot", _QUARTER_PRICES),
    ])


def test_the_width_does_not_cancel_itself_on_a_grid_charging_window():
    """The defect the per-interval envelope exists to prevent, pinned on the real code path.

    A window-uniform extreme (bill EVERY interval at `spot_min`, or every one at `spot_max`) is
    only a corner of the price box, and the saving is separable, so its extremum picks each
    interval's price on the sign of THAT interval's flow difference. Where the battery
    grid-charges, `impA − impC` is negative and the interval wants the opposite extreme from one
    where the battery cuts import. A window containing both — the ordinary case; 182 of 200
    realistic windows do — has the two uniform corners partially cancel, and in the symmetric
    limit cancel exactly: a measured four-hour case reported €0.00 against a true envelope of
    ±€0.48.

    A width of zero is not a harmless understatement. It is the caveat announcing "no
    uncertainty" precisely where the uncertainty is largest, which is the one failure mode a
    worst-case claim must not have. So the assertion here is not "the number is bigger" but
    "the number is not zero on a window whose prices genuinely spread".

    A price that is cheap overnight and dear in the evening makes the battery grid-charge in the
    small hours and discharge later, which is what puts both signs of `impA − impC` in one window.
    """
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    cheap_night_dear_evening = [
        (0.01, 0.02, 0.03, 0.01)[q] if h < 6 else
        (0.30, 0.45, 0.50, 0.35)[q] if 17 <= h <= 20 else
        (0.12, 0.14, 0.18, 0.13)[q]
        for h in range(HOURS) for q in range(4)
    ]
    ds = _bracket_dataset(prices=cheap_night_dear_evening)
    cfg = _qh_cfg()

    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    runs = run_all(frame, cfg)
    d_imp = np.asarray(runs.a.imp, dtype=float) - np.asarray(runs.c.imp, dtype=float)
    assert np.any(d_imp > 1e-9) and np.any(d_imp < -1e-9), (
        "fixture does not exercise the cancellation: it needs BOTH intervals where the battery "
        "cuts import and intervals where it grid-charges"
    )

    r = results_from(ds, (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None
    assert pb.width_eur > 0.0, "the width cancelled to zero on a genuinely uncertain window"
    assert pb.saved_low <= pb.saved_central <= pb.saved_high

    # `width > 0` alone does not discriminate — the uniform corners cancel only PARTIALLY here,
    # not to zero, so both constructions clear it. What separates them is the magnitude: the
    # cancellation is exactly the understatement, so the shipped width must exceed what the
    # superseded window-uniform construction would have reported on this same window.
    from app.domain.costs import compute_costs
    from app.domain.pricing import price_curves

    lo = price_curves(cfg.pricing, frame.spot_min)
    hi = price_curves(cfg.pricing, frame.spot_max)

    def _saved(p_import, p_export_net, compensation):
        a = (p_import, p_export_net, compensation, frame.index, cfg.pricing)
        return compute_costs(runs.a, *a).eur - compute_costs(runs.c, *a).eur

    central = r["cost"]["saved_eur"]
    uniform = [_saved(lo.p_import, hi.p_export_net, hi.compensation),
               _saved(hi.p_import, lo.p_export_net, lo.compensation), central]
    w_uniform = (max(uniform) - min(uniform)) / 2.0
    assert pb.width_eur > w_uniform + 1e-9, (
        f"width {pb.width_eur} did not exceed the window-uniform construction's {w_uniform}; "
        "the per-interval envelope is not being used"
    )


def test_the_split_is_by_direction_of_flow_not_by_price_vector():
    """The crux of §6.16, and the thing an earlier prototype got wrong.

    The worst case for the household is imports billed at the hour's ceiling AND exports
    credited at its floor — the two sides taken from DIFFERENT price vectors, because
    cost = import·p_import − export·p_export_net and the export term enters with a minus sign.
    Pricing both sides off the same vector (the arrangement that reads as "obviously symmetric")
    lets the export term partially offset the import term, and returns a band that is too
    narrow — it is not the worst case it claims to be.

    So this test re-derives BOTH arrangements from the domain layer and asserts the shipped
    width equals the crossed one and is strictly wider than the uncrossed one. It is a mutation
    test: transposing the two `p_export_net` arguments in `_price_bracket` fails it.

    It needs a fixture where runs A and C export DIFFERENT amounts. With `expA == expC` the
    export term cancels out of the saving and the two arrangements coincide exactly — which is
    true of `_bracket_dataset` above, and is why that fixture cannot pin this.
    """
    from app.domain.costs import compute_costs
    from app.domain.pricing import price_curves
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    ds = _exporting_bracket_dataset()
    cfg = _qh_cfg()
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None

    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    runs = run_all(frame, cfg)
    assert np.nansum(runs.a.exp) != pytest.approx(np.nansum(runs.c.exp)), \
        "fixture no longer exercises the export term; the assertions below would be vacuous"

    lo = price_curves(cfg.pricing, frame.spot_min)
    hi = price_curves(cfg.pricing, frame.spot_max)

    def _saved(p_import, p_export_net, compensation):
        a = (p_import, p_export_net, compensation, frame.index, cfg.pricing)
        return compute_costs(runs.a, *a).eur - compute_costs(runs.c, *a).eur

    central = r["cost"]["saved_eur"]

    # The envelope is chosen PER INTERVAL on the sign of that interval's own flow difference —
    # not by billing the whole window at one extreme. Re-derived here from the domain layer so
    # the test pins the construction rather than restating the implementation's arithmetic.
    d_imp = np.asarray(runs.a.imp, dtype=float) - np.asarray(runs.c.imp, dtype=float)
    d_exp = np.asarray(runs.a.exp, dtype=float) - np.asarray(runs.c.exp, dtype=float)
    # Mirrored on purpose: the export term is SUBTRACTED, so a positive `d_exp` wants the LOW
    # export price to maximise the saving. Transposing either pair fails this test.
    per_interval = [
        _saved(np.where(d_imp > 0, hi.p_import, lo.p_import),
               np.where(d_exp > 0, lo.p_export_net, hi.p_export_net),
               np.where(d_exp > 0, lo.compensation, hi.compensation)),
        _saved(np.where(d_imp > 0, lo.p_import, hi.p_import),
               np.where(d_exp > 0, hi.p_export_net, lo.p_export_net),
               np.where(d_exp > 0, hi.compensation, lo.compensation)),
        central,
    ]
    w_per_interval = (max(per_interval) - min(per_interval)) / 2.0

    # The superseded construction: one extreme applied uniformly across the whole window. It is
    # the corner-of-the-box scheme, and it is what this test previously asserted. Kept as the
    # comparison because the defect it hides is invisible otherwise — the uniform corners cancel
    # against each other wherever the battery grid-charges in some intervals and cuts import in
    # others, understating the width and, in the symmetric limit, collapsing it to exactly zero.
    uniform = [_saved(lo.p_import, hi.p_export_net, hi.compensation),
               _saved(hi.p_import, lo.p_export_net, lo.compensation), central]
    w_uniform = (max(uniform) - min(uniform)) / 2.0

    assert w_per_interval > w_uniform, "fixture no longer separates the two constructions"
    assert pb.width_eur == pytest.approx(w_per_interval, abs=1e-12)
    assert pb.width_eur != pytest.approx(w_uniform, abs=1e-9)
    # And the ordering invariant still holds on the wider, correct band.
    assert pb.saved_low <= pb.saved_central <= pb.saved_high


# Two windows on which the CENTRAL saving falls OUTSIDE the two extreme evaluations
# `_price_bracket` ACTUALLY PERFORMS — the case that makes `saved_central`'s presence in its
# `min`/`max` load-bearing rather than merely defensive. One crosses on the LOW side and one on
# the HIGH side, because a single fixture only ever pins ONE of the two calls: where central is
# below both extremes, `max(opt, pess, central)` and `max(opt, pess)` agree, so a fixture of that
# shape leaves the `max` unpinned (and vice versa). Both are found by random search and pinned as
# literals; the mechanism is real but neither window is one anybody would write by hand.
#
# **The mechanism is the feed-in floor, not the four-corner argument.** An earlier single fixture
# here was built against the ORIGINAL, window-uniform envelope: bill every interval at `spot_min`,
# or every one at `spot_max`. Those are two corners of a box the saving is linear over, so the
# mean-priced figure could land outside them. `_price_bracket` no longer evaluates that pair — it
# chooses the extreme PER INTERVAL on the sign of that interval's own flow difference, which is
# the exact extremum of a separable sum. For the affine part of §6.5 the central figure therefore
# cannot escape it, that fixture stopped crossing under the shipped code, and the premise
# assertion went on passing because it recomputed the uniform corners rather than the shipped
# ones. Both mutants survived the whole suite in that state.
#
# What remains is the one term that is NOT separable: §6.5's feed-in floor under
# `FeedinFloorMode.MONTHLY` (appendix A's default), a window-level `max(0, −Σ export·c)`. The
# per-interval pick optimises the separable part and can land on the wrong side of that clamp, so
# the two evaluations are only a bound on the true envelope and the central figure — which sees
# the clamp at the mean prices — can sit outside them in either direction.
#
# The clamp binds only where compensation is negative, which at appendix-A tariffs is spot below
# about −0.02 EUR/kWh, so both fixtures carry mostly negative prices: an unusual but real day.

# LOW-side crossing: central 0.2827 against extremes 0.3191 and 0.3466, both above it. Found with
# numpy default_rng(5) over spot in [−0.20, 0.06].
_CROSS_LOW_QUARTERS = [
    -0.1509, -0.1762, 0.0503, -0.1862, -0.189, -0.0718, -0.1204, -0.1112,
    -0.0848, 0.0268, -0.1082, -0.0863, -0.0619, -0.1793, -0.0814, -0.1681,
    -0.111, -0.0208, -0.0624, -0.0238, -0.1937, -0.0608, -0.1271, -0.0259,
    -0.0245, -0.1633, 0.0316, 0.0322, -0.1984, -0.1104, -0.164, 0.0449,
    -0.0119, -0.1311, 0.0098, 0.0345, 0.0368, -0.1697, -0.1127, 0.0364,
    -0.1178, -0.1092, -0.0261, -0.0837, -0.0097, -0.12, -0.1283, -0.1007,
    -0.1395, -0.0491, -0.1755, -0.1086, -0.1314, -0.1598, -0.0693, 0.0017,
    -0.0037, -0.0111, -0.0167, -0.1628, -0.0848, 0.033, 0.0413, -0.1515,
    -0.0017, -0.1573, -0.1682, -0.1616, 0.0221, -0.0794, 0.0246, -0.1597,
    0.0305, -0.0999, 0.0434, -0.1342, -0.0092, -0.1893, -0.0057, 0.0382,
    0.0268, -0.0554, -0.0841, -0.0617, 0.0043, 0.0566, -0.1459, 0.0534,
    -0.0132, -0.0984, 0.0536, -0.0889, 0.01, -0.0089, -0.1527, -0.0474,
]
_CROSS_LOW_IMPORT = [
    0.58, 1.83, 0.15, 0.38, 2.89, 1.79, 2.04, 1.93,
    1.08, 2.15, 1.11, 2.52, 0.1, 1.18, 1.4, 0.2,
    2.72, 2.92, 1.94, 1.4, 0.7, 1.37, 1.64, 0.35,
]
_CROSS_LOW_EXPORT = [
    3.72, 4.58, 0, 5.78, 5.77, 5.29, 0, 4.2,
    5.89, 5.29, 0.61, 3.7, 2.43, 4.24, 3.72, 1,
    3.8, 4.97, 2.64, 0.56, 3.51, 5.61, 1.3, 1.93,
]
_CROSS_LOW_PV = [
    0.63, 0.98, 3.26, 7.33, 7.44, 6.56, 4.9, 7.22,
    0.8, 3.41, 4.99, 3.35, 2.63, 6.42, 6.76, 6.68,
    4.39, 3.15, 5.91, 5.14, 4.92, 7.72, 0.08, 1.99,
]

# HIGH-side crossing: central 0.4921 against extremes 0.2410 and −0.1131, both below it. Found
# with numpy default_rng(224) over spot in [−0.268, 0.196]. A wider price band than the low-side
# fixture, and correspondingly a wider bracket (€0.30 against €0.03).
_CROSS_HIGH_QUARTERS = [
    0.1655, -0.2487, -0.1424, -0.2198, -0.0384, -0.1186, -0.2535, -0.1838,
    0.1293, -0.149, 0.1697, -0.1026, 0.1323, 0.1163, -0.1274, 0.1427,
    -0.2652, -0.1715, -0.1041, -0.0515, -0.1342, 0.122, 0.1167, 0.0015,
    0.1599, 0.0888, 0.0546, -0.2564, -0.2647, -0.128, 0.1724, 0.1096,
    -0.0114, 0.1512, -0.1487, 0.0567, -0.1399, -0.0523, -0.0871, 0.1089,
    -0.079, 0.1298, -0.0226, -0.0527, 0.1669, 0.0346, -0.017, -0.0362,
    -0.2429, -0.2561, 0.1818, 0.145, -0.07, -0.1282, -0.1412, 0.1238,
    -0.0072, 0.0494, 0.1039, 0.0114, 0.0606, -0.0541, -0.2461, 0.1224,
    -0.0558, 0.0099, 0.0325, -0.1954, 0.0436, -0.0847, -0.0769, 0.0545,
    -0.0879, 0.1098, 0.1764, 0.0909, 0.111, -0.1188, 0.1481, -0.1797,
    -0.0843, -0.203, -0.0025, -0.0391, -0.0056, -0.0665, 0.0516, -0.0912,
    0.191, 0.0076, 0.1881, 0.1862, -0.0283, -0.1853, 0.1113, 0.0223,
]
_CROSS_HIGH_IMPORT = [
    1.15, 0.52, 0.71, 0.24, 0.64, 0.94, 0.96, 0.08,
    0.09, 1.08, 0.85, 0.76, 0.7, 0.22, 0.82, 0.43,
    0.89, 0.41, 0.13, 0.72, 1.02, 1.2, 1.05, 0.61,
]
_CROSS_HIGH_EXPORT = [
    4.47, 2.86, 0.1, 5.42, 3.36, 4.89, 1.25, 3.33,
    1.41, 5.74, 1.5, 1.05, 2.78, 4.67, 6.46, 1.46,
    4.48, 4.25, 5.14, 0.5, 6.54, 4.08, 2.1, 6.36,
]
_CROSS_HIGH_PV = [
    7.77, 2.83, 2.26, 7.04, 3, 2.09, 1.3, 2.11,
    5.79, 0.05, 3.93, 5.25, 2.16, 6.66, 7.63, 6.49,
    5.27, 0.23, 4.03, 1.43, 3.19, 0.44, 0.73, 3.44,
]


def _crossing_dataset(side: str):
    """The crossing fixture for one side of the band; `side` is "low" or "high"."""
    q, imp, exp, pv = {
        "low": (_CROSS_LOW_QUARTERS, _CROSS_LOW_IMPORT, _CROSS_LOW_EXPORT, _CROSS_LOW_PV),
        "high": (_CROSS_HIGH_QUARTERS, _CROSS_HIGH_IMPORT, _CROSS_HIGH_EXPORT, _CROSS_HIGH_PV),
    }[side]
    return _dataset([
        _energy("grid_import_t1", imp),
        _energy("grid_export_t1", exp),
        _energy("solar_production", pv),
        _price_15min("price_spot", q),
    ])


def _shipped_extremes(ds, cfg):
    """Re-derive `_price_bracket`'s TWO extreme evaluations the way the shipped code does.

    Deliberately a re-derivation of the PER-INTERVAL envelope rather than of the window-uniform
    corners. The premise of the test below is about the pair `_price_bracket` actually sorts, so
    computing anything else lets the premise pass on a window the shipped code does not cross on
    — which is exactly how this test came to assert nothing while both mutants survived.
    """
    from app.domain.costs import compute_costs
    from app.domain.pricing import price_curves
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    runs = run_all(frame, cfg)
    lo = price_curves(cfg.pricing, np.asarray(frame.spot_min, dtype=np.float64))
    hi = price_curves(cfg.pricing, np.asarray(frame.spot_max, dtype=np.float64))

    def _saved(p_import, p_export_net, compensation):
        a = (p_import, p_export_net, compensation, frame.index, cfg.pricing)
        return compute_costs(runs.a, *a).eur - compute_costs(runs.c, *a).eur

    d_imp = np.asarray(runs.a.imp, dtype=np.float64) - np.asarray(runs.c.imp, dtype=np.float64)
    d_exp = np.asarray(runs.a.exp, dtype=np.float64) - np.asarray(runs.c.exp, dtype=np.float64)
    optimistic = _saved(
        np.where(d_imp > 0, hi.p_import, lo.p_import),
        np.where(d_exp > 0, lo.p_export_net, hi.p_export_net),
        np.where(d_exp > 0, lo.compensation, hi.compensation),
    )
    pessimistic = _saved(
        np.where(d_imp > 0, lo.p_import, hi.p_import),
        np.where(d_exp > 0, hi.p_export_net, lo.p_export_net),
        np.where(d_exp > 0, hi.compensation, lo.compensation),
    )
    return optimistic, pessimistic


@pytest.mark.parametrize("side", ["low", "high"])
def test_the_band_still_contains_the_headline_when_the_two_extremes_do_not(side):
    """§6.16 fixture 10, in its STRICT case — the ordering is not free.

    `saved_low <= saved_central <= saved_high` is bought by sorting all THREE evaluations. On
    each of these windows the mean-priced saving lies outside both of the extreme evaluations
    `_price_bracket` performs — below both on the "low" fixture, above both on the "high" one
    (see the comment on the fixtures: §6.5's feed-in floor is a window-level clamp and therefore
    not separable, so the per-interval envelope is only a bound on the true one). Assigning
    `saved_low`/`saved_high` to the two extremes would publish a band that does not contain the
    figure printed beside it, and a caveat reading "±€X" around a number outside its own band is
    worse than no caveat.

    Structure matters here as much as the assertions. The PREMISE — that the fixture really does
    straddle-fail — is asserted first, re-derived from the shipped per-interval envelope; the
    CONTAINMENT is the conclusion. A test asserting only the containment passes against a
    `min`/`max` that never saw `saved_central`.

    Mutation-checked: dropping `saved_central` from `_price_bracket`'s `min(...)` fails the
    "low" case, and dropping it from the `max(...)` fails the "high" case. Both parameters are
    needed — each mutant is invisible on the other side's fixture.
    """
    ds = _crossing_dataset(side)
    cfg = _qh_cfg()
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None

    optimistic, pessimistic = _shipped_extremes(ds, cfg)
    lo_e, hi_e = min(optimistic, pessimistic), max(optimistic, pessimistic)
    central = r["cost"]["saved_eur"]

    # The premise, and it is asserted per SIDE rather than as a plain "outside the pair": a
    # low-side fixture that drifted into crossing high would satisfy a side-agnostic premise
    # while leaving the `min` call unpinned. If a change to the dispatch or to §6.5 makes either
    # false, the conclusions below stop testing anything and this says so rather than passing.
    if side == "low":
        assert central < lo_e, \
            "fixture no longer crosses on the low side; the assertions below would be vacuous"
    else:
        assert central > hi_e, \
            "fixture no longer crosses on the high side; the assertions below would be vacuous"

    # What the bracket must nevertheless guarantee. The two bounds are asserted separately, so a
    # failure names which end of the sort lost `saved_central`.
    assert pb.saved_low <= pb.saved_central
    assert pb.saved_central <= pb.saved_high
    assert pb.saved_central == central
    assert pb.width_eur >= 0

    # And the crossing end must be the CENTRAL figure itself, not an extreme — the assertion the
    # corresponding mutant actually trips. The other end stays the extreme it was.
    if side == "low":
        assert pb.saved_low == central
        assert pb.saved_high == hi_e
    else:
        assert pb.saved_high == central
        assert pb.saved_low == lo_e


# ── §6.16 step 4: the caveat that prints the width ───────────────────────────────────────────
#
# The number above is asserted on the view-model; what follows is the SENTENCE. Two things are
# separable here and both matter: that the caveat is emitted on exactly the runs where
# `price_bracket` is not None, and that the figures reach the text rather than an unsubstituted
# "%(width)s". The rendered-PAGE half lives in tests/test_results_route.py — a caveat that exists
# in the view-model and never reaches the HTML has been this project's recurring defect.

_UNCERTAINTY_MARK = "the electricity market prices every 15 minutes"


def _uncertainty_caveat(r) -> str | None:
    """The §6.16 caveat's English text, or None if it was not emitted."""
    hits = [c for c in _caveats(r) if _UNCERTAINTY_MARK in c]
    assert len(hits) <= 1, "the width caveat was emitted more than once"
    return hits[0] if hits else None


def test_the_pricing_uncertainty_caveat_appears_when_there_is_a_width():
    """The ordinary case: hourly energy, quarter-hourly prices, quarter-hourly settlement.

    Asserts the load-bearing clauses rather than the whole sentence, so a copy edit that keeps
    the meaning does not fail the test but one that drops the meaning does. "worst case" is D9
    and is the reason the figure may be quoted at all; the hourly/15-minute contrast is the
    user-facing reason; and the width in euros is the number the step exists to surface.
    """
    r = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    text = _uncertainty_caveat(r)
    assert text is not None
    assert "worst case" in text
    assert "hourly" in text
    # The width interpolated, in whole euros with the € prefix — the fixture's is €2.46 → "€ 2".
    assert "€ 2" in text
    assert "%(width)s" not in text and "%(share)s" not in text
    # NOT phrased as a ± around the saving. On this very fixture the width (€2.46) EXCEEDS the
    # central saving (€0.45), and "your saving is € 0, give or take € 2" reads as a claim that
    # the household might lose money — far stronger than a worst-case bound on the PRICING
    # supports. Pinned because it is the natural way to write the sentence and it is wrong here.
    assert r["cost"]["saved_eur"] < r["price_bracket"].width_eur
    for banned in ("give or take", "±", "plus or minus"):
        assert banned not in text


def test_the_caveat_is_absent_on_every_run_that_has_no_width():
    """The three suppression reasons, all of which reach the caveat as `price_bracket is None`.

    The gate is a single `is not None`, so this is really one assertion three times — but the
    three reasons are independent decisions (D10, D1/D2, and cost simulation being off) and a
    future change could break any one of them alone.
    """
    ds = _bracket_dataset()
    # (a) D10: the supplier bills the hourly mean, so the hourly price IS what was paid.
    hourly_settlement = results_from(ds, (_WIN_START, _WIN_END), cfg=_cost_cfg())
    assert hourly_settlement["price_bracket"] is None
    assert _uncertainty_caveat(hourly_settlement) is None

    # (b) D1/D2: the price series is natively hourly, so no intra-hour spread is observable.
    hourly_price = results_from(
        _dataset([
            _energy("grid_import_t1", 2.0),
            _energy("grid_export_t1", 0.5),
            _energy("solar_production", 3.0),
            _price("price_spot", _PRICES),
        ]),
        (_WIN_START, _WIN_END), cfg=_qh_cfg(),
    )
    assert hourly_price["price_bracket"] is None
    assert _uncertainty_caveat(hourly_price) is None

    # (c) cost simulation off: there is no euro figure to qualify.
    cost_off = SimulationConfig()
    cost_off.pricing.supplier_settlement = SupplierSettlement.QUARTER_HOURLY
    no_cost = results_from(ds, (_WIN_START, _WIN_END), cfg=cost_off)
    assert no_cost["price_bracket"] is None
    assert _uncertainty_caveat(no_cost) is None

    # And the same dataset WITH the gate open does emit it, so the three assertions above are
    # about their gates and not about a fixture that could never produce a caveat.
    assert _uncertainty_caveat(results_from(ds, (_WIN_START, _WIN_END), cfg=_qh_cfg())) is not None


def test_the_caveat_says_how_much_of_the_window_carries_a_spread():
    """The partial case gets its own wording, carrying `bracketed_fraction` as a percentage.

    The fraction counts INTERVALS with a spread among PRICED intervals — not energy and not
    euros — so the sentence must attach it to hours.

    Half the window flat, half with a wide spread, for a fraction of exactly 0.5. The spread half
    is put FIRST — where `_QUARTER_PRICES` has this fixture's battery actually cycling — rather
    than second as `test_the_bracketed_fraction_counts_only_priced_intervals_and_only_spread_ones`
    does: with the spread in the quiet half the flows the width multiplies are small and the
    width lands under `WATERFALL_DISPLAY_EPS_EUR`, which correctly suppresses the caveat and
    would make this test assert nothing about the partial WORDING.
    """
    spread_half = [(0.02, 0.40, 0.05, 0.28)[q] for _ in range(12) for q in range(4)]
    flat_half = [0.12] * (12 * 4)
    r = results_from(
        _bracket_dataset(prices=spread_half + flat_half), (_WIN_START, _WIN_END), cfg=_qh_cfg(),
    )
    assert r is not None
    assert r["price_bracket"].bracketed_fraction == pytest.approx(0.5)
    text = _uncertainty_caveat(r)
    assert text is not None
    # The percentage is interpolated, and it is attached to HOURS rather than to the saving or
    # to "your electricity" — the fraction is a count of intervals and the copy must not imply
    # it is a share of energy or of euros.
    assert "50%" in text
    assert "50% of the priced hours" in text
    assert "%(share)s" not in text
    # The whole-window wording is NOT the one used here.
    assert "every priced hour landing on its least favourable quarter" not in text


def test_the_full_window_wording_omits_the_fraction_entirely():
    """At a fraction of 1.0 there is no partial share to state, and stating "100%" would invite
    the reader to look for the other 0%.

    The counterpart of the test above: same code path, opposite branch. The pair pins that there
    ARE two wordings and which fires at 0.5 and at 1.0 — it does NOT pin the 0.95 cut, since both
    `< 0.51` and `< 0.999` reproduce it. `test_a_fraction_just_above_the_threshold_takes_the_
    whole_window_wording` and its counterpart do that.

    Note "priced": the denominator is PRICED intervals, so a window half of which carries no
    price at all still has a fraction of 1.0 and lands here. "every hour" would then claim
    something about hours that were never priced, which is why both wordings carry the qualifier.
    """
    r = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    assert r["price_bracket"].bracketed_fraction == pytest.approx(1.0)
    text = _uncertainty_caveat(r)
    assert text is not None
    assert "100%" not in text
    assert "of the priced hours" not in text
    assert "every priced hour landing on its least favourable quarter" in text


def test_a_width_that_would_print_as_zero_euros_is_not_stated_at_all():
    """`num(_, "eur")` prints whole euros, so a sub-half-euro width renders "€ 0".

    A caveat announcing a worst case of "€ 0" asserts the very precision D5′'s None-not-zero rule
    exists to avoid claiming. Suppressed on the same rounding the pattern applies — the rule
    `WATERFALL_DISPLAY_EPS_EUR` already encodes for waterfall rows.

    The fixture narrows the intra-hour spread until the width falls under the threshold; the
    bracket itself is still present (the spread is real and non-zero), which is what separates
    this from the suppression test above.
    """
    tiny = [(0.1200, 0.1201, 0.1199, 0.1200)[q] for _ in range(HOURS) for q in range(4)]
    r = results_from(_bracket_dataset(prices=tiny), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    pb = r["price_bracket"]
    # The number IS available — this is a display decision, not a computation one.
    assert pb is not None and 0 < pb.width_eur <= WATERFALL_DISPLAY_EPS_EUR
    assert _uncertainty_caveat(r) is None


def test_a_width_of_exactly_the_display_threshold_is_suppressed_too(monkeypatch):
    """The gate is `> WATERFALL_DISPLAY_EPS_EUR`, so a width of exactly €0.50 prints nothing.

    Not a fencepost detail: `num(_, "eur")` rounds half-to-even, so 0.5 renders as "€ 0" like
    everything below it, and a `>=` gate would emit the one sentence the suppression exists to
    prevent. The code comment at the gate says so; nothing asserted it, and the `>=` mutant
    survived the whole suite.

    Patched rather than driven from a fixture. The boundary IS reachable unpatched — scaling each
    quarter's deviation from its own hour's mean by 0.2035372163776674 makes `width_eur` exactly
    0.5 — but not robustly: that landing holds over a basin of about 21 ULPs of the scale, so it
    depends on the summation order inside `compute_costs` and `price_curves` and is not evidence
    it survives a numpy version bump or a different platform. A boundary test pinned to a value
    that fragile would be a latent flake, so the value is supplied directly. Patching
    `_price_bracket` is the same seam `_share_pct` is pinned through above, and for the same
    reason; the assertion is about the DISPLAY gate, and the number it gates on is an input to
    that decision.

    Both sides are asserted, so a gate that suppressed everything would not pass either.
    """
    import app.results_view as rv
    from app.results_view import PriceBracket

    def _fixed(width: float):
        def _stub(cfg, frame, runs, saved_central):
            return PriceBracket(
                width_eur=width,
                bracketed_fraction=1.0,
                saved_low=saved_central - width,
                saved_central=saved_central,
                saved_high=saved_central + width,
            )
        return _stub

    monkeypatch.setattr(rv, "_price_bracket", _fixed(WATERFALL_DISPLAY_EPS_EUR))
    at = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert at is not None and at["price_bracket"].width_eur == WATERFALL_DISPLAY_EPS_EUR
    assert _uncertainty_caveat(at) is None

    # One ULP above, and the caveat appears — which is what stops the assertion above from
    # passing against a gate that never fires.
    monkeypatch.setattr(rv, "_price_bracket", _fixed(np.nextafter(WATERFALL_DISPLAY_EPS_EUR, 1.0)))
    above = results_from(_bracket_dataset(), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert _uncertainty_caveat(above) is not None


def _mostly_bracketed_prices(flat_hours: set[int]) -> list[float]:
    """`_QUARTER_PRICES`, with the named hours flattened to a single price.

    A flattened hour has `spot_min == spot_max`, so it is PRICED but not BRACKETED and drops out
    of `bracketed_fraction`'s numerator only. With a 24-hour window the reachable fractions are
    k/24, which is what lets the two tests below sit either side of the 0.95 threshold.

    The flattened hours are taken from the QUIET part of the day (`_QUARTER_PRICES` puts its wide
    spread in hours 7, 8, 17-20, which is where this fixture's battery cycles). That is
    deliberate: the width scales with the FLOWS the spread multiplies, not with the spread alone,
    so flattening a cycling hour would shrink the width toward `WATERFALL_DISPLAY_EPS_EUR` and
    the caveat would vanish, leaving both tests asserting nothing about the branch.
    """
    return [0.12 if h in flat_hours else _QUARTER_PRICES[h * 4 + q]
            for h in range(HOURS) for q in range(4)]


def test_a_fraction_just_above_the_threshold_takes_the_whole_window_wording():
    """0.958 (23 of 24 hours bracketed) is at or above 0.95, so no share is stated.

    The pair with the test below pins the THRESHOLD, which the 0.5-and-1.0 fixtures elsewhere
    in this section cannot: both `bracketed_fraction < 0.51` and `bracketed_fraction < 0.999`
    reproduce their results exactly. These two fixtures sit either side of 0.95 and nowhere near
    either mutant's cut, so each of those mutations flips one of them.

    The rationale for the threshold is that a handful of held or gap-filled hours is not worth a
    qualifying clause the reader then has to place — "96% of the priced hours" invites a search
    for the missing 4% that the data cannot answer.
    """
    r = results_from(
        _bracket_dataset(prices=_mostly_bracketed_prices({0})),
        (_WIN_START, _WIN_END), cfg=_qh_cfg(),
    )
    assert r is not None
    pb = r["price_bracket"]
    assert pb.bracketed_fraction == pytest.approx(23 / 24)
    # Anti-vacuity: the fixture must clear the display gate, or the caveat is suppressed and
    # every assertion below passes on a `None` that says nothing about the wording.
    assert pb.width_eur > WATERFALL_DISPLAY_EPS_EUR, \
        "fixture no longer produces a width the caveat will print"
    text = _uncertainty_caveat(r)
    assert text is not None
    assert "every priced hour landing on its least favourable quarter" in text
    assert "of the priced hours" not in text
    assert "96%" not in text and "95%" not in text


def test_a_fraction_just_below_the_threshold_takes_the_partial_wording():
    """0.917 (22 of 24 hours bracketed) is below 0.95, so the share is stated.

    The counterpart of the test above. See `_mostly_bracketed_prices` for why the flattened
    hours are the quiet ones.
    """
    r = results_from(
        _bracket_dataset(prices=_mostly_bracketed_prices({0, 1})),
        (_WIN_START, _WIN_END), cfg=_qh_cfg(),
    )
    assert r is not None
    pb = r["price_bracket"]
    assert pb.bracketed_fraction == pytest.approx(22 / 24)
    assert pb.width_eur > WATERFALL_DISPLAY_EPS_EUR, \
        "fixture no longer produces a width the caveat will print"
    text = _uncertainty_caveat(r)
    assert text is not None
    assert "92% of the priced hours" in text
    assert "every priced hour landing on its least favourable quarter" not in text
    # Both wordings are scoped to the SAVING, not to every euro on the page — see
    # `test_the_caveat_is_scoped_to_the_saving_and_not_to_every_euro_on_the_page` for why the
    # broader claim would be an understatement. Pinned on this branch too, because the two
    # msgids are independent strings and a copy edit can revert one without the other.
    assert "shifts the saving shown on this page" in text
    assert "the euro figures on this page" not in text


def test_a_share_too_small_for_a_whole_percent_is_not_printed_as_zero(monkeypatch):
    """`num(_, "pct")` writes `#,##0`, which prints "0%" for anything under half a percent.

    "for 0% of the priced hours here … that shifts the saving by € 2" contradicts itself: it
    states a width while denying there is anything to state it about. The case is not exotic — a
    365-day window carrying three spread hours has a fraction of 0.00034 — but it is not
    reachable through `results_from` at this fixture's 24-hour length, where the smallest
    non-zero fraction is 1/24, so the formatting decision is pinned on `_share_pct` directly.

    Both branches are asserted, because a helper that always returned two decimals would satisfy
    the small case while writing an ordinary half-window straddle as "50.00%".
    """
    from app.results_view import _share_pct
    from app.i18n import format_num

    def rendered(fraction: float) -> str:
        d = _share_pct(fraction)
        return format_num(d["num"], d["fmt"], "en")

    assert rendered(0.00034) == "0.03%"
    # Exactly 0.005 is the case a `>= 0.005` cut would get wrong: `#,##0` rounds half to even,
    # so this value renders as "0%" under the whole-percent kind.
    assert rendered(0.005) == "0.50%"
    assert rendered(0.0) == "0.00%"
    # Ordinary shares keep the whole-percent form; no trailing ".00" on a 50% straddle.
    assert rendered(0.5) == "50%"
    assert rendered(0.9166666666666666) == "92%"

    # And the caveat's PARTIAL branch actually routes its share through this helper, rather than
    # calling `num(_, "pct")` directly. Asserted on the raw view-model message because the case
    # that separates the two is not reachable through `results_from`: at this fixture's window
    # length the smallest non-zero fraction is 1/24, and lengthening the window to reach a
    # sub-half-percent share also shrinks the width below `WATERFALL_DISPLAY_EPS_EUR` — the width
    # scales with the flow difference in the spread hours, so few spread hours means little width
    # and the caveat suppresses itself. A rendered-text assertion would therefore be vacuous.
    spread_half = [(0.02, 0.40, 0.05, 0.28)[q] for _ in range(12) for q in range(4)]
    r = results_from(
        _bracket_dataset(prices=spread_half + [0.12] * 48), (_WIN_START, _WIN_END), cfg=_qh_cfg(),
    )
    caveat = next(c for c in r["caveats"]
                  if isinstance(c, dict) and _UNCERTAINTY_MARK in c.get("msgid", ""))
    assert caveat["params"]["share"] == {"num": 0.5, "fmt": "pct"}

    # And that it goes through THIS helper rather than calling `num(_, "pct")` itself, which at
    # a fraction of 0.5 is indistinguishable by value. Patched to a sentinel so the call site is
    # observed directly; without it the assertion above would pass under either construction.
    import app.results_view as rv
    seen: list[float] = []

    def _spy(fraction):
        seen.append(fraction)
        return {"num": fraction, "fmt": "pct_dec2"}

    monkeypatch.setattr(rv, "_share_pct", _spy)
    r2 = results_from(
        _bracket_dataset(prices=spread_half + [0.12] * 48), (_WIN_START, _WIN_END), cfg=_qh_cfg(),
    )
    assert seen == [pytest.approx(0.5)], "the caveat does not route its share through _share_pct"
    caveat2 = next(c for c in r2["caveats"]
                   if isinstance(c, dict) and _UNCERTAINTY_MARK in c.get("msgid", ""))
    assert caveat2["params"]["share"]["fmt"] == "pct_dec2"


def test_the_whole_window_wording_still_says_priced_when_half_the_window_is_unpriced():
    """A fraction of 1.0 does not mean every hour of the window carries a price.

    `bracketed_fraction`'s denominator is PRICED intervals, so a window whose first half has no
    spot price at all and whose second half carries a spread everywhere has a fraction of exactly
    1.0 and takes the whole-window branch. This is the case that makes the qualifier necessary
    rather than merely tidy: without it the sentence would say "every hour landing on its least
    favourable quarter" over a window where half the hours were never priced.

    Not a hypothetical shape — a price series that begins after the energy series does produces
    it, and step 1 guarantees `spot_min`/`spot_max` are NaN exactly where `spot` is.
    """
    nan = float("nan")
    prices = ([nan] * (12 * 4)
              + [_QUARTER_PRICES[h * 4 + q] for h in range(12, HOURS) for q in range(4)])
    r = results_from(_bracket_dataset(prices=prices), (_WIN_START, _WIN_END), cfg=_qh_cfg())
    assert r is not None
    pb = r["price_bracket"]
    assert pb.bracketed_fraction == pytest.approx(1.0)
    assert pb.width_eur > WATERFALL_DISPLAY_EPS_EUR, \
        "fixture no longer produces a width the caveat will print"
    text = _uncertainty_caveat(r)
    assert text is not None
    # The whole-window branch fired, and it names PRICED hours in both of its two mentions.
    assert "each priced hour" in text
    assert "every priced hour landing on its least favourable quarter" in text


def test_the_caveat_is_scoped_to_the_saving_and_not_to_every_euro_on_the_page():
    """`width_eur` bounds a DIFFERENCE of two bills, so it does not bound either bill.

    All three evaluations are savings — `cost(A) − cost(C)` at three price vectors — and the two
    bills' errors partly cancel in that difference. Each individual bill therefore moves by MORE
    than the stated width, and both bills are on this same page: the KPI sentence prints them
    ("X without a battery → Y with one") and the waterfall decomposes one of them. A caveat sold
    as a worst case must not name a quantity it understates, so the copy names only the saving.

    The understatement is MEASURED here rather than assumed, on the same fixture the caveat's
    other tests use. The bill's own envelope is the window-uniform pair (each bill genuinely IS
    bracketed by billing the whole window at one extreme — it is only their DIFFERENCE that is
    not; see `PriceBracket`).
    """
    from app.domain.costs import compute_costs
    from app.domain.pricing import price_curves
    from app.domain.simframe import simulation_frame
    from app.domain.simulate import run_all

    ds = _bracket_dataset()
    cfg = _qh_cfg()
    r = results_from(ds, (_WIN_START, _WIN_END), cfg=cfg)
    assert r is not None
    pb = r["price_bracket"]
    assert pb is not None

    frame = simulation_frame(ds, (_WIN_START, _WIN_END))
    runs = run_all(frame, cfg)
    lo = price_curves(cfg.pricing, frame.spot_min)
    hi = price_curves(cfg.pricing, frame.spot_max)

    def _bill(run, imp_curves, exp_curves):
        return compute_costs(run, imp_curves.p_import, exp_curves.p_export_net,
                             exp_curves.compensation, frame.index, cfg.pricing).eur

    # The BATTERY bill (run A) at its cheapest and dearest: imports at the floor and exports at
    # the ceiling minimises it, and the reverse maximises it.
    bill_low = _bill(runs.a, lo, hi)
    bill_high = _bill(runs.a, hi, lo)
    bill_half_range = (bill_high - bill_low) / 2.0

    # The claim the narrowed wording rests on, checked rather than asserted: the width the caveat
    # prints is SMALLER than how far the battery bill alone could move. Measured on this fixture
    # when the test was written: €2.46 against €2.72.
    assert bill_half_range > pb.width_eur, (
        "fixture no longer separates the saving's width from the bill's own range; "
        "the wording test below would then be pinning a distinction that does not exist"
    )

    text = _uncertainty_caveat(r)
    assert text is not None
    assert "shifts the saving shown on this page" in text
    # The superseded, over-broad claim must not come back: it named the euro figures on the page,
    # of which the two bills are the largest, and understated their movement.
    assert "the euro figures on this page" not in text
