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
    * a corrupt stored config still renders GET / (the page must always draw);
    * the Phase 7 cost tint: the Pricing box's headings, labels and inputs carry
      .cost-label / .cost-field and the Battery and Grid boxes do not.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame
from tests.conftest import WORKSPACE_ID, page, seed_workspace, w

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
    dataset.save_dataset(frames, (_WIN_START, _WIN_END), "test", [], None, workspace_id=WORKSPACE_ID)
    # The routes are workspace-scoped now, and `TestClient(app)` outside a `with` block skips the
    # lifespan that would have adopted this data dir's workspace — so create the row explicitly.
    seed_workspace()

    from app import main

    return TestClient(main.app)


# The energy-only submission. It carries the `setup` section and an explicit
# `setup.simulate_cost=no`: `parse_form` writes that field only when its section is posted, so a
# form omitting it INHERITS the stored value. That read as "cost off" only while the default was
# off (§8.18 flipped it), which made this helper's meaning depend on a default it does not name.
def _form(**overrides) -> dict:
    base = {
        "sections": "setup battery grid charge discharge topology",
        "setup.simulate_cost": "no",
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


# The same submission with cost simulation ON: the setup band's radio, the `setup`, `pricing` and
# `pricing_advanced` section markers, and every field §2.3's Pricing box draws. This is what the
# rendered form actually posts once the user answers "Yes" in the band, so it is what the
# round-trip and the retention tests have to drive. Panel ② draws BOTH of the Pricing box's
# checkboxes — the guard and `dal_weekends` — so it claims both names; the edit screen draws only
# the second and claims only `pricing_advanced` (see `params_view._section`).
def _cost_form(**overrides) -> dict:
    base = _form()
    base["sections"] = (
        "setup battery grid charge discharge topology pricing pricing_advanced"
    )
    base["setup.simulate_cost"] = "yes"
    base.update({
        "pricing.contract": "dynamic",
        "pricing.supplier_markup": "0.0205",
        "pricing.energy_tax_excl_vat": "0.09161",
        "pricing.vat_rate": "21",
        "pricing.feedin_alpha": "0.50",
        "pricing.feedin_beta": "0.0000",
        "pricing.tlk_mode": "flat",
        "pricing.tlk_eur_per_kwh": "0.0400",
        "pricing.dal_start_hour": "23",
        "pricing.dal_end_hour": "7",
        "pricing.dal_weekends": "1",
        "pricing.degradation_eur_per_kwh": "0.0000",
    })
    base.update(overrides)
    return base


def _rendered_sections(client, body=None) -> set[str]:
    """The `sections` marker panel ② actually emits for the config `body` leaves stored.

    `_form`/`_cost_form` write the marker out by hand, on purpose: several tests are ABOUT what a
    given marker does, and scraping it would make those circular. The cost is that a hardcoded
    marker can drift from what the panel renders — which is exactly how `_cost_form` could carry
    `pricing` while panel ② emitted something else and nothing noticed. This reads the real one,
    for the tests that need to compare.
    """
    r = client.post(w("/params"), data=body if body is not None else _cost_form())
    m = re.search(r'name="sections" value="([^"]*)"', r.text)
    assert m, "panel ② rendered no sections marker"
    return set(m.group(1).split())


def _saved_kwh(client, **body) -> float:
    """The `GRID IMPORT SAVED` figure panel ③ currently renders, as a number.

    Read out of the rendered fragment rather than out of the view-model, because what is being
    asserted is that the ROUTE's config threading reaches the page — a view-model call would
    bypass exactly the wiring under test.
    """
    r = client.post(w("/results"), json=body or {"period": "last_1_year"})
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



def _edit_html(client) -> str:
    """The edit-workspace screen's rendered HTML.

    §2′.1 moved the Grid connection and Pricing boxes here, so the tests below that assert about
    those controls' RENDERING read this rather than the params response. Their persistence half
    still posts to `/params`, because `parse_form` is shared by both screens and is what coerces
    and stores either screen's submission.
    """
    r = client.get(w("/edit"))
    assert r.status_code == 200, r.status_code
    return r.text


def test_a_valid_submission_persists_and_returns_the_panel(client):
    from app import simconfig_store

    r = client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "20"}))
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "1"
    assert 'id="panel-params"' in r.text          # the swap target root
    assert simconfig_store.load(WORKSPACE_ID).battery.usable_capacity_kwh == 20


def test_the_response_renders_the_submitted_values_back(client):
    """The swapped-in box shows what was just submitted, in the inputs the user will read next.

    **This pinned §2.3's collapsed summary line until phase 4.2** ("20.0 kWh · 7.0/5.0 kW · …"),
    which §2′.6 removed along with the collapsed panel it summarised: the battery box is not a
    stepper panel any more, it is a heading, one visible field and a pane whose summary carries the
    "N changed from default" count instead. `params_view.summary_line` still exists and is still
    covered in `tests/test_params_view.py`; nothing renders it.

    Pinned on the input VALUES rather than on a readout, which is the stronger property anyway: it
    is what the user sees and what the next submission would send.
    """
    r = client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "20",
                                             "battery.max_charge_kw": "7"}))
    assert 'name="battery.usable_capacity_kwh"' in r.text
    assert re.search(r'name="battery\.usable_capacity_kwh"[^>]*value="20\.0"', r.text, re.S) or \
        re.search(r'value="20\.0"[^>]*name="battery\.usable_capacity_kwh"', r.text, re.S)
    assert re.search(r'name="battery\.max_charge_kw"[^>]*value="7\.0"', r.text, re.S)


def test_a_stored_config_is_rendered_on_the_next_page_load(client):
    """The persisted parameter set drives GET / — which is the restart case, since load() holds
    no process state."""
    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "22.5"}))
    rendered_page = client.get(page())
    assert rendered_page.status_code == 200
    assert 'name="battery.usable_capacity_kwh"' in rendered_page.text
    assert 'value="22.5"' in rendered_page.text


# ── The error path ───────────────────────────────────────────────────────────────────────────


def test_an_invalid_submission_is_not_persisted_and_keeps_the_typed_value(client):
    """Deliverable 2: re-render with the user's own values and the errors bound per field.

    Persisting first and reporting after would leave a broken configuration driving panel ③; and
    re-rendering the STORED config instead of the submitted one would silently discard the typing.
    """
    from app import simconfig_store

    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "20"}))   # a good baseline
    r = client.post(w("/params"), data=_form(**{"battery.max_charge_kw": "not-a-number"}))

    assert r.status_code == 200                       # a rendered form, not a failed request
    assert r.headers["X-Params-Valid"] == "0"
    assert 'value="not-a-number"' in r.text           # what they typed, still in the input
    assert 'data-field-error="battery.max_charge_kw"' in r.text
    assert simconfig_store.load(WORKSPACE_ID).battery.max_charge_kw == 5.0   # unchanged on disk


def test_an_invalid_submission_does_not_500(client):
    """`SimulationConfig` construction never raises; this asserts the route honours that.

    Every field made simultaneously nonsense — the shape most likely to find an unguarded
    conversion somewhere between the form parser and the renderer.
    """
    junk = {k: "🙃" for k in _form() if k != "sections"}
    junk["sections"] = "battery grid charge discharge topology"
    r = client.post(w("/params"), data=junk)
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "0"


def test_an_empty_submission_does_not_500(client):
    """Nothing but the section marker: every field inherits, so this is a valid no-op."""
    r = client.post(w("/params"), data={"sections": "battery"})
    assert r.status_code == 200


def test_every_numeric_field_survives_a_very_long_value(client):
    """The defect was in the shared funnel, so it reached EVERY numeric input, including the three
    percent-typed ones (which scale by 100 and so hit `float()` a second time on the way in and a
    third on the way out). Submitted one at a time so a field that 500s is named by the failure.

    Cost simulation is turned ON for the whole sweep, because the Pricing box's numerics are only
    VALIDATED in cost mode (`validate()` gates them on `simulate_cost`, §2.3: a blocking error on
    a field the user was never shown has no input to attach itself to). With it off those fields
    would still have to survive the funnel — they just would not be reported, so the sweep could
    not tell a survivor from a silently-accepted 400-digit number.
    """
    from app import params_view

    for name, _path, _fn in params_view.FIELDS:
        r = client.post(w("/params"), data=_cost_form(**{name: "9" * 400}))
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

    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "11"}))
    r = client.post(
        w("/params"), data=_form(**{"battery.usable_capacity_kwh": "9" * digits})
    )
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "0"
    assert 'data-field-error="battery.usable_capacity_kwh"' in r.text
    assert simconfig_store.load(WORKSPACE_ID).battery.usable_capacity_kwh == 11    # unchanged on disk


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
        WORKSPACE_ID,
        guard_submitted=True,
    )
    parked = simconfig_store.load(WORKSPACE_ID)
    parked.simulate_cost = False
    simconfig_store.save(parked, WORKSPACE_ID)

    r = client.post(w("/params"), data=_form(sections="battery grid charge discharge pricing"))
    assert r.status_code == 200

    # Still parked: re-enabling cost simulation must restore the user's tick.
    restored = simconfig_store.load(WORKSPACE_ID)
    restored.simulate_cost = True
    simconfig_store.save(restored, WORKSPACE_ID)
    assert simconfig_store.load(WORKSPACE_ID).economic_guard is True


def test_panel_two_still_unticks_the_guard_and_still_carries_it_forward(client):
    """The `pricing` / `pricing_advanced` split leaves the guard's behaviour as it was.

    Phase 3's edit screen claimed `pricing` while drawing no guard checkbox, which cleared the
    stored guard on every save; the fix moved `dal_weekends` behind its own `pricing_advanced`
    name. §2′.1 then moved the Pricing box itself to the edit screen, which took `dal_weekends`
    with it and left the guard here — so the two names now belong to two different screens, and
    THIS one claims `pricing` alone. The guard's own behaviour is unchanged by either step:

      * a cost submission WITHOUT the checkbox is a user unticking it — the guard goes off;
      * an energy-only submission never drew it — the stored tick carries forward (appendix A).
    """
    from app import simconfig_store

    # The marker the tests below drive must be the one the panel really renders, or they would be
    # asserting about a form no browser sends. `pricing` yes (the guard is drawn here);
    # `pricing_advanced` no (its checkbox is on the edit screen now).
    rendered = _rendered_sections(client)
    assert "pricing" in rendered
    assert "pricing_advanced" not in rendered, (
        "the results screen must not claim a checkbox the edit screen draws"
    )
    assert "grid" not in rendered

    client.post(w("/params"), data=_cost_form(**{"policy.economic_guard": "1"}))
    assert simconfig_store.load(WORKSPACE_ID).economic_guard is True

    # Unticked: absent from the body, but the form still claims it drew the control.
    client.post(w("/params"), data=_cost_form())
    assert simconfig_store.load(WORKSPACE_ID).policy.economic_guard is False

    client.post(w("/params"), data=_cost_form(**{"policy.economic_guard": "1"}))
    assert simconfig_store.load(WORKSPACE_ID).economic_guard is True

    energy_only = _form(sections="setup battery grid charge discharge topology",
                        **{"setup.simulate_cost": "no"})
    client.post(w("/params"), data=energy_only)
    back_on = simconfig_store.load(WORKSPACE_ID)
    back_on.simulate_cost = True
    simconfig_store.save(back_on, WORKSPACE_ID)
    assert simconfig_store.load(WORKSPACE_ID).economic_guard is True


def test_dal_weekends_unticks_through_the_marker_that_claims_it(client):
    """The other half of the split, now driven from the screen that owns the checkbox.

    `dal_weekends` moved to the edit screen with the Pricing box (§2′.1), so `pricing_advanced` is
    claimed there and not here. The untick must still take effect — if no rendered form emitted
    the marker, an unticked box would read as "this build never drew the control" and be silently
    ignored, which is the defect the split exists to prevent.

    Posted through the params route rather than the edit route because what is under test is
    `parse_form`'s gate, which both routes share; the edit screen's own rendering of the marker is
    asserted in `test_workspace_edit.py`.
    """
    from app import simconfig_store

    # Not claimed by THIS screen — the assertion that would have caught the over-claim.
    assert "pricing_advanced" not in _rendered_sections(client)

    client.post(w("/params"), data=_cost_form(**{"pricing.dal_weekends": "1"}))
    assert simconfig_store.load(WORKSPACE_ID).pricing.dal_weekends is True

    body = _cost_form()
    body.pop("pricing.dal_weekends")
    client.post(w("/params"), data=body)
    assert simconfig_store.load(WORKSPACE_ID).pricing.dal_weekends is False


def test_panel_two_still_clears_approximated_on_a_supported_topology(client):
    """§2.5b's deliberate `else` branch, preserved by the section gate the fix added.

    The gate makes the whole branch conditional on the form having DRAWN the topology box, so the
    clearing must still happen for a form that did. A user who accepted the 3-phase approximation
    and then moves back to a 3-phase inverter stops carrying a caveat they no longer earn.
    """
    from app import simconfig_store

    unsupported = _form(**{"grid.phases": "3", "topology.battery_phases": "one_phase",
                           "topology.approximated": "1"})
    client.post(w("/params"), data=unsupported)
    assert simconfig_store.load(WORKSPACE_ID).topology.approximated is True
    # The gate is only honest if panel ② really claims `topology` here — a 3-phase connection is
    # what makes the selector, and therefore the checkbox, exist at all.
    assert "topology" in _rendered_sections(client, unsupported)

    client.post(
        w("/params"),
        data=_form(**{"grid.phases": "3", "topology.battery_phases": "three_phase",
                      "topology.approximated": "1"}),
    )
    assert simconfig_store.load(WORKSPACE_ID).topology.approximated is False


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

    r = client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "13"}))
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

    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "17"}))
    r = client.post(w("/params"), content=b"\x00\x01\x02", headers={"Content-Type": "text/plain"})
    assert r.status_code < 500
    assert simconfig_store.load(WORKSPACE_ID).battery.usable_capacity_kwh == 17


def test_band_overlap_warns_and_still_persists(client):
    """§7.3 check 12 / §6.7: netting handles it at runtime, so it must not block the save."""
    from app import simconfig_store

    r = client.post(w("/params"), data=_form(**{"policy.band_b": "0.500", "policy.band_c": "0.100"}))
    assert r.headers["X-Params-Valid"] == "1"
    assert simconfig_store.load(WORKSPACE_ID).policy.band_b == 0.5
    assert "overlap" in r.text.lower()


def test_a_corrupt_stored_config_still_renders_the_page(client):
    """Deliverable 1: the app must always render. A broken file falls back to defaults."""
    from app import simconfig_store

    client.post(w("/params"), data=_form())
    simconfig_store.config_path(WORKSPACE_ID).write_text("{ truncated", encoding="utf-8")
    rendered_page = client.get(page())
    assert rendered_page.status_code == 200
    # Appendix-A defaults, read off the fields themselves. This asserted the collapsed summary line
    # ("10.0 kWh · 5.0/5.0 kW · 90%") until §2′.6 removed it with the collapsed panel.
    assert re.search(r'name="battery\.usable_capacity_kwh"[^>]*value="10\.0"', rendered_page.text)
    assert re.search(r'name="battery\.max_charge_kw"[^>]*value="5\.0"', rendered_page.text)
    assert re.search(r'name="battery\.roundtrip_efficiency"[^>]*value="90"', rendered_page.text)


# ── §2.5(b) / §7.3 check 18 — the soft block ─────────────────────────────────────────────────


def test_an_unsupported_phase_topology_shows_the_soft_block(client):
    """Selecting 1-phase on a 3-phase connection reveals the dialog and does NOT block the save."""
    from app import simconfig_store

    r = client.post(
        w("/params"),
        data=_form(**{"grid.phases": "3", "topology.battery_phases": "one_phase"}),
    )
    assert r.headers["X-Params-Valid"] == "1"            # SOFT block: the config is still valid
    assert "not fully supported in version 1" in r.text
    assert 'name="topology.approximated"' in r.text
    assert simconfig_store.load(WORKSPACE_ID).topology.approximated is False   # not continued yet


def test_continuing_sets_topology_approximated(client):
    from app import simconfig_store

    client.post(
        w("/params"),
        data=_form(**{"grid.phases": "3", "topology.battery_phases": "three_times_one_phase",
                      "topology.approximated": "1"}),
    )
    assert simconfig_store.load(WORKSPACE_ID).topology.approximated is True


def test_fixture_12_an_approximated_run_is_identical_to_the_three_phase_case(client):
    """**Spec fixture 12** (docs/specs/16-validation-harness.md, §2.5b, §7.3 check 18).

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
    client.post(w("/params"), data=three_phase)
    assert simconfig_store.load(WORKSPACE_ID).topology.approximated is False
    supported_saving = _saved_kwh(client)
    supported_body = client.post(w("/results"), json={"period": "last_1_year"}).text

    approximated = _form(**{"grid.phases": "3", "topology.battery_phases": "one_phase",
                            "topology.approximated": "1"})
    client.post(w("/params"), data=approximated)
    cfg = simconfig_store.load(WORKSPACE_ID)

    # (1) the flag is set, and it is the UNSUPPORTED topology that is stored.
    assert cfg.topology.approximated is True
    assert cfg.topology.battery_phases.value == "one_phase"

    # (2) the numbers are identical.
    assert _saved_kwh(client) == supported_saving

    approximated_body = client.post(w("/results"), json={"period": "last_1_year"}).text
    # ...and the ONLY difference in the rendered panel is the caveat the soft block pins to it.
    assert "3-phase approximation" in approximated_body
    assert "3-phase approximation" not in supported_body


# ── The config drives panel ③ (deliverable 4) ────────────────────────────────────────────────


def test_a_parameter_change_moves_panel_3s_figures(client):
    """End-to-end: post a bigger battery, and the saving moves. This is the whole point of the
    phase — before it, `results_from` built its own `SimulationConfig()` and the form changed
    nothing."""
    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "5"}))
    small = _saved_kwh(client)

    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "30",
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
    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "5"}))
    assert _saved_kwh(client) == small


def test_the_benchmark_route_uses_the_same_config(client):
    """`/results` and `/results/benchmark` must not disagree about which battery is being
    described. The benchmark's `Your policy` row IS the policy saving, so it tracks the config."""
    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "5"}))
    small = client.post(w("/results/benchmark"), json={"period": "last_1_year"})
    assert small.status_code == 200

    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "30",
                                         "battery.max_charge_kw": "10",
                                         "battery.max_discharge_kw": "10"}))
    large = client.post(w("/results/benchmark"), json={"period": "last_1_year"})
    assert large.status_code == 200
    assert large.text != small.text


def test_index_renders_panel_3_under_the_stored_config(client):
    """GET / must agree with POST /results — both read the same persisted parameter set."""
    client.post(w("/params"), data=_form(**{"battery.usable_capacity_kwh": "25",
                                         "battery.max_charge_kw": "10",
                                         "battery.max_discharge_kw": "10"}))
    rendered_page = client.get(page())
    fragment_saving = _saved_kwh(client)
    # The tile prints a thousands separator and, for a negative saving, a typographic minus
    # (§7.2 item 9's honest sign); normalise both before comparing.
    rendered = re.search(
        r"GRID IMPORT SAVED.*?stat-value[^>]*>\s*([−+-]?[\d,]+(?:\.\d+)?)", rendered_page.text, re.S
    )
    assert rendered, "GET / did not render the GRID IMPORT SAVED tile"
    assert float(rendered.group(1).replace(",", "").replace("−", "-")) == fragment_saving


# ── §2.3's Pricing box, end to end ───────────────────────────────────────────────────────────


def test_the_params_panel_never_draws_the_pricing_fields_and_the_edit_screen_always_does(client):
    """Where each `pricing.*` control lives after §2′.1, asserted in both directions.

    This replaces "the Pricing box renders only with cost simulation on", which was §2.3's rule
    while the box was part of panel ②. Two things changed it. The box moved to the edit-workspace
    screen, so this panel draws NO `pricing.*` field in either cost mode; and §2′.4 answer 5 makes
    it "show always" there, so cost mode does not gate it on that screen either.

    The one control that stayed and is still cost-gated is `policy.economic_guard` — a `policy.*`
    dispatch decision, not a rate, drawn in the discharge card. §2.3 names it separately and that
    part of the old rule survives intact.
    """
    off = client.post(w("/params"), data=_form())
    assert off.headers["X-Params-Valid"] == "1"
    on = client.post(w("/params"), data=_cost_form())
    assert on.headers["X-Params-Valid"] == "1"

    for text in (off.text, on.text):
        assert not re.findall(r'<input[^>]*name="pricing\.[^"]*"', text)
        assert 'name="grid.' not in text

    # The guard: absent without a cost model, present with one. Unchanged behaviour.
    assert 'name="policy.economic_guard"' not in off.text
    assert 'name="policy.economic_guard"' in on.text

    # And the fields themselves are on the edit screen, cost mode notwithstanding — the stored
    # config here has `simulate_cost` on from the POST above; `test_the_contract_box_is_always_shown`
    # in test_workspace_edit.py drives both modes.
    html = _edit_html(client)
    for present in ('name="pricing.vat_rate"', 'name="pricing.contract"',
                    'name="pricing.supplier_markup"', 'name="pricing.dal_start_hour"',
                    'name="pricing.feedin_alpha"', 'name="pricing.tlk_mode"',
                    'name="pricing.degradation_eur_per_kwh"'):
        assert present in html, present


def test_the_setup_band_radio_changes_simulate_cost_and_re_renders_the_panel(client):
    """Followup B2: the band POSTs with panel ②'s form and the answer takes effect immediately.

    Both directions, because the interesting failure is asymmetric — a band that could only ever
    turn the box ON would look correct on a first click and trap the user afterwards.
    """
    from app import simconfig_store

    # The panel's own tell is the `pricing` section marker: it is emitted exactly when the cost
    # toggle is on, because that is when the economic-guard checkbox is drawn. It replaces the
    # Pricing box's fields as the assertion here — those moved to the edit screen (§2′.1), so a
    # re-render of THIS panel no longer contains them in either direction.
    on = client.post(w("/params"), data=_cost_form())
    assert simconfig_store.load(WORKSPACE_ID).simulate_cost is True
    assert "pricing" in re.search(r'name="sections" value="([^"]*)"', on.text).group(1).split()
    assert 'name="policy.economic_guard"' in on.text

    off = client.post(
        w("/params"),
        data=_form(sections="setup battery grid charge discharge topology",
                   **{"setup.simulate_cost": "no"}),
    )
    assert simconfig_store.load(WORKSPACE_ID).simulate_cost is False
    assert "pricing" not in re.search(r'name="sections" value="([^"]*)"', off.text).group(1).split()
    assert 'name="policy.economic_guard"' not in off.text


def test_every_pricing_field_persists_and_vat_converts_both_ways(client):
    """One submission of the whole box, read back off disk and out of the next render.

    VAT is checked on both sides of the conversion in the same test: 9 submitted, 0.09 stored,
    `value="9"` rendered. A one-sided assertion passes against an implementation that scales
    consistently in the wrong direction.
    """
    from app import simconfig_store

    r = client.post(w("/params"), data=_cost_form(**{
        "pricing.supplier_markup": "0.0300",
        "pricing.energy_tax_excl_vat": "0.10000",
        "pricing.vat_rate": "9",
        "pricing.feedin_alpha": "1.00",
        "pricing.feedin_beta": "-0.0200",
        "pricing.tlk_eur_per_kwh": "0.0500",
        "pricing.dal_start_hour": "22",
        "pricing.dal_end_hour": "6",
        "pricing.degradation_eur_per_kwh": "0.0150",
    }))
    assert r.headers["X-Params-Valid"] == "1"

    pr = simconfig_store.load(WORKSPACE_ID).pricing
    assert pr.supplier_markup == 0.03
    assert pr.energy_tax_excl_vat == 0.1
    assert pr.vat_rate == pytest.approx(0.09)
    assert pr.feedin_alpha == 1.0
    assert pr.feedin_beta == -0.02
    assert pr.tlk_eur_per_kwh == 0.05
    assert pr.dal_start_hour == 22
    assert pr.dal_end_hour == 6
    assert pr.degradation_eur_per_kwh == 0.015

    # The render half is the edit screen's now (§2′.1): these fields post through `parse_form`
    # above, but the inputs they come back into are drawn there. Asserted against a real GET so
    # the round trip stays end-to-end rather than stopping at the config object.
    html = _edit_html(client)
    assert 'value="9"' in html              # 0.09 back out as 9 percent
    assert 'value="0.0300"' in html
    assert 'value="-0.0200"' in html


def test_an_out_of_range_pricing_value_blocks_and_binds_to_its_input(client):
    """§6.5's ranges (`validate()`): a VAT rate above 1 is a confident wrong euro figure."""
    from app import simconfig_store

    client.post(w("/params"), data=_cost_form())
    r = client.post(w("/params"), data=_cost_form(**{"pricing.vat_rate": "300"}))
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "0"
    assert simconfig_store.load(WORKSPACE_ID).pricing.vat_rate == pytest.approx(0.21)   # unchanged on disk

    # The INLINE binding — the raw string kept and keyed to its input — is the edit screen's half
    # since §2′.1 moved the field there, and it is asserted through that screen's own route in
    # `test_workspace_edit.py`. What this test keeps is the part that is this route's: an
    # out-of-range pricing value blocks the save and leaves disk alone. Driving the binding from
    # here would need the edit route, whose POST re-renders with the typed value; the params
    # response no longer draws a `pricing.vat_rate` input to bind to at all.
    assert 'name="pricing.vat_rate"' not in r.text


def test_the_pending_contract_radios_render_disabled_with_their_keys(client):
    """§2.3 lists all three types; only DYNAMIC is built, so the other two are pending controls.

    Keys are read out of `app.features` rather than written as literals, so a rename in one place
    and not the other fails here rather than shipping a `[?]` with no issue URL behind it.
    """
    from app import features

    # All three controls are on the edit screen since §2′.1 (§2′.4's Contract box). `tlk_mode` is
    # the one that had to be REBUILT there: it existed only in the Pricing box, so moving the box
    # briefly left `pricing_tlk_tiered` registered as a feature key with nothing rendering it —
    # the state §2.1's pending doctrine exists to prevent. This test is what pins the repair.
    html = _edit_html(client)
    for key in ("pricing_contract_fixed", "pricing_contract_variable", "pricing_tlk_tiered"):
        assert key in features.FEATURE_KEYS
        assert f'data-feature-key="{key}"' in html, key
    # And the radios they belong to really are disabled.
    assert re.search(r'name="pricing\.contract" value="fixed"[^>]*disabled', html)
    assert re.search(r'name="pricing\.contract" value="variable"[^>]*disabled', html)
    assert re.search(r'name="pricing\.tlk_mode" value="tiered"[^>]*disabled', html)
    # DYNAMIC and FLAT are the built ones and must NOT be.
    assert not re.search(r'name="pricing\.contract" value="dynamic"[^>]*disabled', html)
    assert not re.search(r'name="pricing\.tlk_mode" value="flat"[^>]*disabled', html)


def test_the_pending_pricing_keys_carry_an_issue_url(client):
    """The other half: a key rendered into the page must have an issue URL behind it.

    This replaces an assertion that `POST /feature-interest/{key}` answered 204 for each of these
    and 404 for a retired one. The route is gone — a thumbs-up opens a GitHub issue form instead
    of writing a counter — so what has to hold now is that the map emitted into the dialog covers
    every key the page renders, and names the feature rather than the slug.
    """
    from app import features

    html = _edit_html(client)
    for key in ("pricing_contract_fixed", "pricing_contract_variable", "pricing_tlk_tiered"):
        url = features.issue_url(key)
        assert "template=feature.yml" in url
        assert features.title_for(key) != key, f"{key} has no human-readable title"
        # The dialog's key → URL map is what the click reads; the page must carry this key's entry.
        # Compared through `json.dumps` with `&` escaped the way Jinja's `tojson` emits it inside
        # a <script> block — valid JS that parses back to the URL above, but not a literal
        # substring of it.
        assert json.dumps(key) in html, key
        assert json.dumps(url).replace("&", "\\u0026") in html, key
    # Retired keys are the mirror property, asserted as one loop so that retiring a fourth key is
    # a one-line change here rather than a new test. `data_source_csv` joined this list when the
    # CSV-import work built the "Upload CSV" source and deleted its disabled stub.
    for key, title in (
        ("simulate_cost", "Simulate cost savings"),
        ("data_source_csv", "Upload CSV"),
    ):
        # Not in the pending vocabulary...
        assert key not in features.FEATURE_KEYS, key
        # ...and nothing renders it. The vocabulary check alone would pass while a template still
        # carried the attribute, which is the state that matters: a live [?] on a shipped control
        # sends the user to an issue form for something they can already use.
        assert f'data-feature-key="{key}"' not in html, key
        # But the title stays readable, because issues filed under the key are still open.
        assert features.title_for(key) == title, key


def test_the_contract_help_affordance_uses_the_shared_dialog(client):
    """§2.3's contract-type ⓘ: the three one-line definitions, carried by the existing mechanism.

    `.slot-info-btn` + `data-info-title`/`data-info-body` is the same delegated handler the slot
    roster and the disabled charge policies already use, so this adds no JS. Asserted so that a
    future refactor of the dialog cannot quietly orphan this one caller.
    """
    html = _edit_html(client)                       # §2′.1: the Contract box lives here now
    assert 'data-info-title="Contract types"' in html
    body = re.search(r'data-info-body="([^"]*)"[^>]*>ⓘ</button>', html)
    assert body, "the contract ⓘ is not rendered"
    for phrase in ("EPEX day-ahead", "normaal and one dal rate", "revises it periodically"):
        assert phrase in body.group(1)


def test_the_cost_mode_shows_as_the_pricing_box_appearing_and_disappearing(client):
    """The rendered box, through the route — §2.3's "Without cost simulation" over the wire.

    **This asserted §2.1's collapsed summary clause until phase 4.2** ("· dynamic" / "· energy
    only"), which §2′.6 removed with the collapsed panel. It then asserted the Pricing box being
    drawn or not — until §2′.1 moved that box to the edit screen, where §2′.4 answer 5 shows it in
    both modes. What is left on THIS panel that still tracks the cost mode is the economic guard,
    so that is what the test now watches: it is the one control here whose existence the toggle
    decides, and `test_workspace_results.py` covers the result sections the toggle also gates.
    """
    on = client.post(w("/params"), data=_cost_form())
    assert 'name="policy.economic_guard"' in on.text

    off = client.post(
        w("/params"),
        data=_form(sections="setup battery grid charge discharge topology",
                   **{"setup.simulate_cost": "no"}),
    )
    assert 'name="policy.economic_guard"' not in off.text
    # The dispatch bands STAY: they change which kWh move, not what a kWh is worth (§2.3).
    assert 'name="policy.band_a"' in off.text


def test_pricing_values_survive_turning_cost_simulation_off_and_on(client):
    """Appendix A's retention rule over the wire: the panel stops drawing the box, and the values
    are still there when it draws it again.

    This is the reason `parse_form` inherits absent fields and `to_dict` writes the pricing group
    unconditionally. Driven through the route rather than the store so the whole chain — form,
    coercion, save, load, re-render — is under test.
    """
    from app import simconfig_store

    client.post(w("/params"), data=_cost_form(**{
        "pricing.supplier_markup": "0.0777",
        "pricing.vat_rate": "9",
        "pricing.degradation_eur_per_kwh": "0.0250",
        "policy.economic_guard": "1",
    }))
    assert simconfig_store.load(WORKSPACE_ID).economic_guard is True

    energy_only = _form(sections="setup battery grid charge discharge topology",
                        **{"setup.simulate_cost": "no"})
    client.post(w("/params"), data=energy_only)
    parked = simconfig_store.load(WORKSPACE_ID)
    assert parked.simulate_cost is False
    assert parked.pricing.supplier_markup == 0.0777     # inert, but retained
    assert parked.pricing.vat_rate == pytest.approx(0.09)
    assert parked.economic_guard is False               # forced off in effect

    r = client.post(w("/params"), data=dict(energy_only, **{"setup.simulate_cost": "yes"}))
    restored = simconfig_store.load(WORKSPACE_ID)
    assert restored.simulate_cost is True
    assert restored.pricing.supplier_markup == 0.0777
    assert restored.pricing.degradation_eur_per_kwh == 0.025
    assert restored.economic_guard is True              # the `retained` slot, end to end
    assert 'name="policy.economic_guard"' in r.text and "checked" in r.text


def test_the_params_panel_carries_no_cost_tint_now_that_the_pricing_box_has_gone(client):
    """Phase 7's tint rule, re-scoped by §2′.1.

    The rule was "cost inputs are tinted, non-cost inputs are not", and inside panel ② the tinted
    set WAS the Pricing box. That box moved to the edit-workspace screen — which does not tint at
    all, because a box titled "Contract" between a rate and a VAT field does not need a hue to say
    it is about money — so this panel's tinted set is now empty.

    What the rule still governs is `_panel_results.html`: the cost toggle, the COST SAVINGS
    divider and the euro KPI/benchmark headings, which is where a reader now needs the cue that a
    figure is money rather than kWh. Those are asserted in `test_workspace_results.py`.

    Kept as a NEGATIVE assertion here rather than deleted. A stray `cost-field` reappearing on a
    `battery.` or `grid.` input is exactly the drift the original test existed to catch, and the
    check costs nothing.
    """
    off = client.post(w("/params"), data=_form()).text
    on = client.post(w("/params"), data=_cost_form()).text

    for text in (off, on):
        assert "cost-field" not in text
        for tag in re.findall(r'<input[^>]*name="(?:battery|policy|topology)\.[^"]*"[^>]*>', text):
            assert "cost-field" not in tag, tag

    # The structural signals the tint was only ever an accent on: still words, still headings.
    assert re.search(r'<h[1-4][^>]*>\s*Battery\s*</h[1-4]>', on)


def test_the_setup_band_toggle_carries_the_cost_tint(client):
    """The control that governs the whole thing is marked like what it governs (§2.1).

    It is tinted in BOTH states — it is the switch for cost simulation whether or not cost
    simulation is currently on — so this is asserted on the off render, where nothing else on the
    page is marked.
    """
    import re

    off = client.get(page()).text
    assert re.search(r'cost-label[^>]*>\s*Simulate cost savings\?\s*<', off)
