"""Route tests for POST /params, and for the config driving panel ③ (specs §2.3, §2.5, §3.2).

These drive the panel-② wiring end-to-end through the FastAPI app against a seeded temporary data
dir, the same harness shape as tests/test_results_route.py.

Covered:
    * a valid submission → 200, persisted, `X-Params-Valid: 1`, the panel re-rendered;
    * an invalid submission → 200, NOT persisted, `X-Params-Valid: 0`, the user's typed value
      still in the input with the error bound to it;
    * a band overlap → warns and still persists (check 12);
    * check 18's soft block: the dialog appears, and continuing sets `topology.approximated`;
    * **spec fixture 12** — an approximated run is numerically IDENTICAL to the 3-phase case;
    * a parameter change moves panel ③'s figures (POST /results after POST /params);
    * error paths return clean 4xx, never a 500;
    * a corrupt stored config still renders GET / (the page must always draw).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame

_DAYS = 30
_HOURS = _DAYS * 24
_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 1 + _DAYS, tzinfo=timezone.utc)


def _series(name: str, kind: str, per_interval, n: int = _HOURS) -> SeriesFrame:
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    values = (
        np.full(n, float(per_interval))
        if np.isscalar(per_interval)
        else np.asarray(per_interval, dtype=float)
    )
    return SeriesFrame(name, kind, 3600, idx, values, np.zeros(n, dtype=QUALITY_DTYPE))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient over a fresh temp data dir holding one seeded dataset and no stored config.

    The seed carries a solar series and an export series so the PV-dependent paths are live —
    the P1/P3 charge options, the §2.5(a) coupling selector, and the self-consumption metric all
    only exist with PV, and a PV-less seed would leave them untested here.

    The price series alternates cheap/expensive per hour so the charge/discharge bands bite and a
    parameter change has something to move. Note that the SIGN of the saving on this seed is
    negative (the daytime surplus is already exported in the baseline, so the battery mostly
    grid-charges and pays round-trip); that is correct output per §7.2 item 9 and is asserted
    properly in test_results_view.py — see the note in test_a_parameter_change_moves_panel_3s_figures.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset

    hours = np.arange(_HOURS)
    cheap_expensive = np.where(hours % 2 == 0, 0.01, 0.30)
    # A crude diurnal solar shape: 4 kWh/h from 10:00 to 15:00 UTC, nothing otherwise.
    hour_of_day = hours % 24
    solar = np.where((hour_of_day >= 10) & (hour_of_day < 15), 4.0, 0.0)
    frames = [
        _series("grid_import_t1", "energy", 2.0),
        # Whatever solar is not consumed by the 2 kWh/h baseline load is exported in the baseline.
        _series("grid_export_t1", "energy", np.maximum(solar - 2.0, 0.0)),
        _series("solar_production", "energy", solar),
        _series("price_spot", "price", cheap_expensive),
    ]
    dataset.save_dataset(frames, (_WIN_START, _WIN_END), "test", [], None)

    from app import main

    return TestClient(main.app)


def _form(**overrides) -> dict:
    base = {
        "sections": "battery grid charge discharge topology",
        "battery.usable_capacity_kwh": "10.0",
        "battery.min_soc_pct": "10",
        "battery.max_soc_pct": "100",
        "battery.max_charge_kw": "5.0",
        "battery.max_discharge_kw": "5.0",
        "battery.roundtrip_efficiency": "90",
        "battery.standby_w": "30",
        "battery.initial_soc_pct": "50",
        "grid.phases": "1",
        "grid.fuse_a": "25",
        "grid.max_import_kw_override": "",
        "grid.max_export_kw": "",
        "policy.band_a": "-0.050",
        "policy.band_b": "0.040",
        "policy.band_c": "0.180",
        "policy.band_d": "9.999",
        "policy.charge_policy": "P3",
        "policy.discharge_policy": "D1",
        "topology.pv_coupling": "dc_hybrid",
    }
    base.update(overrides)
    return base


def _saved_kwh(client, **body) -> float:
    """The `GRID IMPORT SAVED` figure panel ③ currently renders, as a number.

    Read out of the rendered fragment rather than out of the view-model, because what is being
    asserted is that the ROUTE's config threading reaches the page — a view-model call would
    bypass exactly the wiring under test.
    """
    r = client.post("/results", json=body or {"period": "last_1_year"})
    assert r.status_code == 200
    # The tile renders as: <div class="stat-title …">GRID IMPORT SAVED</div>
    # <div class="stat-value …">1,412<span …> kWh</span></div>
    m = re.search(
        r"GRID IMPORT SAVED.*?stat-value[^>]*>\s*([−+-]?[\d,]+(?:\.\d+)?)",
        r.text,
        re.S,
    )
    assert m, "could not locate the GRID IMPORT SAVED tile in the fragment"
    return float(m.group(1).replace(",", "").replace("−", "-"))


# ── The happy path ───────────────────────────────────────────────────────────────────────────


def test_a_valid_submission_persists_and_returns_the_panel(client):
    from app import simconfig_store

    r = client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "20"}))
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "1"
    assert 'id="panel-params"' in r.text          # the swap target root
    assert simconfig_store.load().battery.usable_capacity_kwh == 20


def test_the_summary_line_in_the_response_reflects_the_submission(client):
    r = client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "20",
                                             "battery.max_charge_kw": "7"}))
    assert "20.0 kWh · 7.0/5.0 kW" in r.text


def test_a_stored_config_is_rendered_on_the_next_page_load(client):
    """The persisted parameter set drives GET / — which is the restart case, since load() holds
    no process state."""
    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "22.5"}))
    page = client.get("/")
    assert page.status_code == 200
    assert 'name="battery.usable_capacity_kwh"' in page.text
    assert 'value="22.5"' in page.text


# ── The error path ───────────────────────────────────────────────────────────────────────────


def test_an_invalid_submission_is_not_persisted_and_keeps_the_typed_value(client):
    """Deliverable 2: re-render with the user's own values and the errors bound per field.

    Persisting first and reporting after would leave a broken configuration driving panel ③; and
    re-rendering the STORED config instead of the submitted one would silently discard the typing.
    """
    from app import simconfig_store

    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "20"}))   # a good baseline
    r = client.post("/params", data=_form(**{"battery.max_charge_kw": "not-a-number"}))

    assert r.status_code == 200                       # a rendered form, not a failed request
    assert r.headers["X-Params-Valid"] == "0"
    assert 'value="not-a-number"' in r.text           # what they typed, still in the input
    assert 'data-field-error="battery.max_charge_kw"' in r.text
    assert simconfig_store.load().battery.max_charge_kw == 5.0   # unchanged on disk


def test_an_invalid_submission_does_not_500(client):
    """`SimulationConfig` construction never raises; this asserts the route honours that.

    Every field made simultaneously nonsense — the shape most likely to find an unguarded
    conversion somewhere between the form parser and the renderer.
    """
    junk = {k: "🙃" for k in _form() if k != "sections"}
    junk["sections"] = "battery grid charge discharge topology"
    r = client.post("/params", data=junk)
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "0"


def test_an_empty_submission_does_not_500(client):
    """Nothing but the section marker: every field inherits, so this is a valid no-op."""
    r = client.post("/params", data={"sections": "battery"})
    assert r.status_code == 200


def test_every_numeric_field_survives_a_very_long_value(client):
    """The defect was in the shared funnel, so it reached EVERY numeric input, including the two
    percent-typed ones (which scale by 100 and so hit `float()` a second time on the way in and a
    third on the way out). Submitted one at a time so a field that 500s is named by the failure.
    """
    from app import params_view

    for name, _path, _fn in params_view.FIELDS:
        r = client.post("/params", data=_form(**{name: "9" * 400}))
        assert r.status_code == 200, f"{name} produced {r.status_code}"
        assert r.headers["X-Params-Valid"] == "0", name


@pytest.mark.parametrize("digits", [400, 4000])
def test_a_very_long_numeric_input_is_a_field_error_not_a_500(client, digits):
    """The route's "any other value becomes a field error" guarantee, at the OverflowError edge.

    `coerce_number` parses a digit string with `int()` first, which succeeds up to Python's
    4300-digit limit and yields an int far beyond float range. `_finite` then called `float()` on
    it and raised `OverflowError` before reaching its `math.isfinite` guard — a 500 from an
    ordinary (if silly) typed value, and a hole in the "construction never raises" guarantee both
    modules rest on. Note "9" * 100000 was always SAFE, because `int()` refuses it and the
    `float()` fallback gives `inf`, which `_finite` rejects cleanly; the window is roughly
    310 < digits < 4300, which is why both ends are parametrised here.
    """
    from app import simconfig_store

    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "11"}))
    r = client.post(
        "/params", data=_form(**{"battery.usable_capacity_kwh": "9" * digits})
    )
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "0"
    assert 'data-field-error="battery.usable_capacity_kwh"' in r.text
    assert simconfig_store.load().battery.usable_capacity_kwh == 11    # unchanged on disk


def test_a_forged_sections_value_cannot_clear_the_retained_guard(client):
    """`sections` is an unprotected hidden field; it must not carry authority the server can check.

    With `simulate_cost` off the Pricing box is never drawn, so a submission claiming it WAS
    drawn is either a stale or a tampered POST. Trusting it gave `guard_submitted=True`, which
    skipped `to_dict`'s carry-forward and wiped the `economic_guard` appendix A says is retained.
    `guard_was_submitted` now also asks the server's own `stored.simulate_cost`.
    """
    from app import simconfig_store
    from app.domain.simconfig import PolicyConfig, SimulationConfig

    # A stored guard, set under cost simulation, then parked by turning cost simulation off.
    simconfig_store.save(
        SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=True),
        guard_submitted=True,
    )
    parked = simconfig_store.load()
    parked.simulate_cost = False
    simconfig_store.save(parked)

    r = client.post("/params", data=_form(sections="battery grid charge discharge pricing"))
    assert r.status_code == 200

    # Still parked: re-enabling cost simulation must restore the user's tick.
    restored = simconfig_store.load()
    restored.simulate_cost = True
    simconfig_store.save(restored)
    assert simconfig_store.load().economic_guard is True


def test_an_unwritable_data_dir_reports_on_the_panel_rather_than_500ing(client, monkeypatch):
    """A read-only or full data directory is a foreseeable local condition, not a server bug.

    The save is still NOT silently swallowed — a no-op that rendered a success would tell the
    user their parameters were stored when they were not. It surfaces as a panel-level notice
    beside the form, which is where every other non-field problem is reported.
    """
    from app import simconfig_store

    def boom(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(simconfig_store, "save", boom)

    r = client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "13"}))
    assert r.status_code == 200
    assert "could not be saved" in r.text
    # The submitted values still drive this render — they simply will not survive a restart.
    assert 'value="13.0"' in r.text


def test_a_body_that_is_not_a_form_never_500s_and_changes_nothing(client):
    """A junk body must not produce a stack trace, and must not damage the stored config.

    Starlette reads a non-form content type as an EMPTY form rather than raising, so the route
    sees a submission carrying no fields — which `parse_form` correctly treats as "inherit
    everything". The observable contract is therefore "no 5xx and nothing changed", not a
    particular 4xx code: there is no user mistake here to report, and inventing a 400 for a
    request the framework parsed successfully would be asserting our own plumbing, not behaviour.
    """
    from app import simconfig_store

    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "17"}))
    r = client.post("/params", content=b"\x00\x01\x02", headers={"Content-Type": "text/plain"})
    assert r.status_code < 500
    assert simconfig_store.load().battery.usable_capacity_kwh == 17


def test_band_overlap_warns_and_still_persists(client):
    """§7.3 check 12 / §6.7: netting handles it at runtime, so it must not block the save."""
    from app import simconfig_store

    r = client.post("/params", data=_form(**{"policy.band_b": "0.500", "policy.band_c": "0.100"}))
    assert r.headers["X-Params-Valid"] == "1"
    assert simconfig_store.load().policy.band_b == 0.5
    assert "overlap" in r.text.lower()


def test_a_corrupt_stored_config_still_renders_the_page(client):
    """Deliverable 1: the app must always render. A broken file falls back to defaults."""
    from app import simconfig_store

    client.post("/params", data=_form())
    simconfig_store.config_path().write_text("{ truncated", encoding="utf-8")
    page = client.get("/")
    assert page.status_code == 200
    assert "10.0 kWh · 5.0/5.0 kW · 90%" in page.text     # appendix-A defaults


# ── §2.5(b) / §7.3 check 18 — the soft block ─────────────────────────────────────────────────


def test_an_unsupported_phase_topology_shows_the_soft_block(client):
    """Selecting 1-phase on a 3-phase connection reveals the dialog and does NOT block the save."""
    from app import simconfig_store

    r = client.post(
        "/params",
        data=_form(**{"grid.phases": "3", "topology.battery_phases": "one_phase"}),
    )
    assert r.headers["X-Params-Valid"] == "1"            # SOFT block: the config is still valid
    assert "not fully supported in version 1" in r.text
    assert 'name="topology.approximated"' in r.text
    assert simconfig_store.load().topology.approximated is False   # not continued yet


def test_continuing_sets_topology_approximated(client):
    from app import simconfig_store

    client.post(
        "/params",
        data=_form(**{"grid.phases": "3", "topology.battery_phases": "three_times_one_phase",
                      "topology.approximated": "1"}),
    )
    assert simconfig_store.load().topology.approximated is True


def test_fixture_12_an_approximated_run_is_identical_to_the_three_phase_case(client):
    """**Spec fixture 12** (specs/16-validation-harness.md, §2.5b, §7.3 check 18).

    Both halves, as the fixture states them:

      1. selecting an unsupported phase topology and continuing sets `topology.approximated`;
      2. the resulting run is numerically IDENTICAL to the 3-phase case — because the
         approximation IS the 3-phase model. v1 has no per-phase model at all, so
         `battery_phases` changes no number; what it changes is the caveat pinned to panel ③.

    Asserting only the first half would pass against an implementation that quietly derated the
    battery; asserting only the second would pass against one that never set the flag. The point
    of the fixture is that both hold at once.
    """
    from app import simconfig_store

    three_phase = _form(**{"grid.phases": "3", "topology.battery_phases": "three_phase"})
    client.post("/params", data=three_phase)
    assert simconfig_store.load().topology.approximated is False
    supported_saving = _saved_kwh(client)
    supported_body = client.post("/results", json={"period": "last_1_year"}).text

    approximated = _form(**{"grid.phases": "3", "topology.battery_phases": "one_phase",
                            "topology.approximated": "1"})
    client.post("/params", data=approximated)
    cfg = simconfig_store.load()

    # (1) the flag is set, and it is the UNSUPPORTED topology that is stored.
    assert cfg.topology.approximated is True
    assert cfg.topology.battery_phases.value == "one_phase"

    # (2) the numbers are identical.
    assert _saved_kwh(client) == supported_saving

    approximated_body = client.post("/results", json={"period": "last_1_year"}).text
    # ...and the ONLY difference in the rendered panel is the caveat the soft block pins to it.
    assert "3-phase approximation" in approximated_body
    assert "3-phase approximation" not in supported_body


# ── The config drives panel ③ (deliverable 4) ────────────────────────────────────────────────


def test_a_parameter_change_moves_panel_3s_figures(client):
    """End-to-end: post a bigger battery, and the saving moves. This is the whole point of the
    phase — before it, `results_from` built its own `SimulationConfig()` and the form changed
    nothing."""
    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "5"}))
    small = _saved_kwh(client)

    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "30",
                                         "battery.max_charge_kw": "10",
                                         "battery.max_discharge_kw": "10"}))
    large = _saved_kwh(client)

    assert large != small
    # **The direction is deliberately NOT asserted.** On this synthetic seed the daytime surplus
    # is already exported in the baseline, so a bigger battery under P3 mostly grid-charges in the
    # cheap half-hours and loses more to round-trip and standby than it recovers — both figures
    # come out negative and the larger battery is the more negative one. That is correct output
    # (§7.2 item 9), and it is exercised properly in test_results_view.py against a dataset built
    # for it. Asserting a direction here would mean tuning this fixture until the sign came out
    # agreeable, which would test the fixture rather than the wiring. What this test owes is that
    # the config REACHES the run: before this phase, `results_from` built its own
    # `SimulationConfig()` and both numbers would have been identical.
    #
    # What IS asserted beyond inequality: the mapping is a function of the config and nothing
    # else, so going back to the first parameter set reproduces the first figure exactly. That
    # rules out the figure merely drifting with request order or with some cached state.
    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "5"}))
    assert _saved_kwh(client) == small


def test_the_benchmark_route_uses_the_same_config(client):
    """`/results` and `/results/benchmark` must not disagree about which battery is being
    described. The benchmark's `Your policy` row IS the policy saving, so it tracks the config."""
    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "5"}))
    small = client.post("/results/benchmark", json={"period": "last_1_year"})
    assert small.status_code == 200

    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "30",
                                         "battery.max_charge_kw": "10",
                                         "battery.max_discharge_kw": "10"}))
    large = client.post("/results/benchmark", json={"period": "last_1_year"})
    assert large.status_code == 200
    assert large.text != small.text


def test_index_renders_panel_3_under_the_stored_config(client):
    """GET / must agree with POST /results — both read the same persisted parameter set."""
    client.post("/params", data=_form(**{"battery.usable_capacity_kwh": "25",
                                         "battery.max_charge_kw": "10",
                                         "battery.max_discharge_kw": "10"}))
    page = client.get("/")
    fragment_saving = _saved_kwh(client)
    # The tile prints a thousands separator and, for a negative saving, a typographic minus
    # (§7.2 item 9's honest sign); normalise both before comparing.
    rendered = re.search(
        r"GRID IMPORT SAVED.*?stat-value[^>]*>\s*([−+-]?[\d,]+(?:\.\d+)?)", page.text, re.S
    )
    assert rendered, "GET / did not render the GRID IMPORT SAVED tile"
    assert float(rendered.group(1).replace(",", "").replace("−", "-")) == fragment_saving
