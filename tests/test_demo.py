"""The committed demo dataset and its loader (`app/demo.py`, `app/data/demo/`).

Two things are under test here, and they fail for different reasons, so they are kept apart:

  * **The committed artifacts.** `test_manifest_*` and `test_committed_*` assert properties of the
    files in `app/data/demo/` — shape, coverage, internal consistency. These break when the
    artifacts are regenerated wrongly (or by hand), which is a build-time bug in
    `scripts/build_demo_dataset.py`.
  * **The loader.** `test_materialize_*` drives `demo.materialize()` against an isolated data dir
    and asserts the workspace it produces is a normal, fully-formed one. These break when the
    persistence layer moves under the loader.

The anonymisation is deliberately NOT asserted numerically. Its parameters are a judgement call
documented in the builder, and pinning the resampled values here would turn every future revision
of that judgement into a test failure with no information in it. What IS asserted is the property
the whole exercise exists for and that a regeneration could silently lose: that the manifest still
records which days were resampled and still carries the caveat about what the smoothing does not
achieve (`test_manifest_documents_anonymisation`).
"""

import json
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app import dataset, demo, simconfig_store, workspaces
from app.domain.series_vocab import is_known_series

# The window the committed dataset covers (docs: scripts/build_demo_dataset.py).
WINDOW_START = datetime(2026, 4, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 7, 1, tzinfo=timezone.utc)
HOURS = 2184  # 91 days


# ── The committed artifacts ──────────────────────────────────────────────────────────────────


def test_manifest_loads_and_declares_the_window():
    doc = demo.load_manifest()
    assert doc["version"] == 1
    assert datetime.fromisoformat(doc["window"]["start"]) == WINDOW_START
    assert datetime.fromisoformat(doc["window"]["end"]) == WINDOW_END
    assert doc["resolution_s"] == 3600


def test_manifest_series_are_all_in_the_known_vocabulary():
    """A name outside §4.1 would be dropped silently on load, yielding a short dataset."""
    for spec in demo.load_manifest()["series"]:
        assert is_known_series(spec["name"]), spec["name"]


def test_manifest_documents_anonymisation():
    """The provenance must keep saying what was done AND what it does not achieve.

    Regenerating the artifacts with a different rule is fine; shipping them with the caveat
    quietly dropped is not, because the demo is real household data and the honest description
    of its limits is the thing a reader needs.
    """
    prov = demo.load_manifest()["provenance"]
    assert prov["resampled_days"], "no resampled days recorded"
    note = prov["anonymisation"].lower()
    assert "resampled" in note
    assert "inference remains possible" in note or "not" in note


def test_committed_csvs_cover_the_window_at_hourly_resolution():
    doc = demo.load_manifest()
    for spec in doc["series"]:
        index, values, quality = demo._read_series_csv(demo.DEMO_DIR / spec["file"])
        assert len(index) == HOURS, spec["name"]
        assert len(values) == HOURS and len(quality) == HOURS, spec["name"]
        steps = np.unique(np.diff(index).astype("int64"))
        assert steps.tolist() == [3600], f"{spec['name']}: spacing {steps.tolist()}"


def test_committed_energy_values_are_physical():
    """Energy per interval is non-negative and finite; a NaN here would poison the simulation."""
    for spec in demo.load_manifest()["series"]:
        _, values, _ = demo._read_series_csv(demo.DEMO_DIR / spec["file"])
        assert np.isfinite(values).all(), spec["name"]
        assert (values >= 0).all(), spec["name"]


def test_bundled_prices_cover_the_window():
    """The demo carries no price file; it slices the committed spot prices instead."""
    frame = demo._price_frame(demo.load_manifest())
    assert frame.kind == "price"
    assert frame.covers((WINDOW_START, WINDOW_END))
    assert frame.resolution_s == 900


# ── The loader ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def demo_workspace():
    """Materialize the demo into the session's isolated data dir; yield its id."""
    return demo.materialize()


def test_materialize_creates_a_listed_workspace(demo_workspace):
    row = workspaces.get(demo_workspace)
    assert row is not None
    assert row["title"] == demo.DEMO_TITLE


def test_materialize_persists_every_series(demo_workspace):
    loaded = dataset.load_latest(demo_workspace)
    assert loaded is not None
    names = {f.name for f in loaded.frames}
    assert names == {
        "grid_import_t1",
        "grid_import_t2",
        "grid_export_t1",
        "grid_export_t2",
        "solar_production",
        "price_spot",
    }
    assert loaded.window == (WINDOW_START, WINDOW_END)
    assert loaded.source_type == demo.DEMO_SOURCE_TYPE


def test_materialize_round_trips_resolutions_and_lengths(demo_workspace):
    """The `.npz` carry no metadata, so this is really a test that series_meta was written."""
    loaded = dataset.load_latest(demo_workspace)
    by_name = {f.name: f for f in loaded.frames}
    for name in ("grid_import_t1", "solar_production"):
        assert by_name[name].resolution_s == 3600, name
        assert len(by_name[name].index) == HOURS, name
    assert by_name["price_spot"].resolution_s == 900
    assert len(by_name["price_spot"].index) == HOURS * 4


def test_materialize_writes_a_usable_config(demo_workspace):
    cfg = simconfig_store.load(demo_workspace)
    assert cfg.has_pv is True
    assert cfg.battery.usable_capacity_kwh > 0
    assert cfg.pricing.contract.value == "dynamic"


def test_the_demo_ships_the_intended_battery_and_policies(demo_workspace):
    """P1/D1 on a 6 kWh / 5 kW battery — all four overridden by the builder, so all four asserted.

    None of these are inherited: the source workspace runs P3/D3 on 15 kWh / 7 kW, and
    `scripts/build_demo_dataset.py` replaces them. P1/D1 is the appendix-A default and the pair
    §6.6/§6.7 says cannot conflict, so the demo's flows read as self-consumption rather than as
    price arbitrage; 6 kWh / 5 kW is a commonly-sold domestic size. A regeneration that dropped
    the override would silently change the story the demo tells, with every other test here
    still passing.
    """
    cfg = simconfig_store.load(demo_workspace)
    assert cfg.policy.charge_policy.value == "P1"
    assert cfg.policy.discharge_policy.value == "D1"
    assert cfg.battery.usable_capacity_kwh == 6
    assert cfg.battery.max_charge_kw == 5.0
    assert cfg.battery.max_discharge_kw == 5.0


def test_materialize_reports_full_data_facts(demo_workspace):
    """The list card's five dataset facts, which come from SQLite metadata alone."""
    card = next(s for s in workspaces.list_summaries("local") if s.id == demo_workspace)
    facts = card.data
    assert facts.loaded is True
    assert facts.grid_consumption and facts.grid_production and facts.pv_production
    assert facts.window == (WINDOW_START, WINDOW_END)
    assert facts.resolution_s == 3600
    assert facts.intervals == HOURS


def test_materialize_twice_creates_independent_workspaces():
    """The button is pressable more than once; a second press must not touch the first copy."""
    first = demo.materialize()
    second = demo.materialize()
    assert first != second
    assert dataset.load_latest(first) is not None
    assert dataset.load_latest(second) is not None


def test_materialize_accepts_an_explicit_id_and_title():
    wid = demo.materialize(title="Mine", workspace_id="demo-explicit")
    assert wid == "demo-explicit"
    assert workspaces.get(wid)["title"] == "Mine"


# ── Failure modes ────────────────────────────────────────────────────────────────────────────


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(demo.ManifestError, match="not found"):
        demo.load_manifest(tmp_path)


def test_unparseable_manifest_raises(tmp_path):
    (tmp_path / "manifest.json").write_text("{not json")
    with pytest.raises(demo.ManifestError, match="valid JSON"):
        demo.load_manifest(tmp_path)


def test_wrong_manifest_version_raises(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"version": 99}))
    with pytest.raises(demo.ManifestError, match="version"):
        demo.load_manifest(tmp_path)


def test_manifest_missing_a_required_key_raises(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"version": 1, "window": {}}))
    with pytest.raises(demo.ManifestError, match="missing"):
        demo.load_manifest(tmp_path)


def test_series_file_shorter_than_the_window_raises(tmp_path):
    """A truncated CSV must fail loudly rather than produce a short, silently-wrong demo."""
    doc = demo.load_manifest()
    spec = doc["series"][0]
    (tmp_path / "manifest.json").write_text(
        json.dumps({**doc, "series": [spec]})
    )
    lines = (demo.DEMO_DIR / spec["file"]).read_text().splitlines()
    (tmp_path / spec["file"]).write_text("\n".join(lines[:50]) + "\n")
    with pytest.raises(demo.ManifestError, match="does not cover"):
        demo._energy_frames(demo.load_manifest(tmp_path), tmp_path)


# ── The route ────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_the_list_offers_the_demo(client):
    """Both the populated header and the empty state carry the action."""
    body = client.get("/").text
    assert 'action="/workspaces/demo"' in body


def test_post_creates_a_workspace_and_redirects_to_its_results(client):
    r = client.post(
        "/workspaces/demo", headers={"sec-fetch-site": "same-origin"}, follow_redirects=False
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.endswith("/results")
    wid = location.removeprefix("/w/").removesuffix("/results")
    assert dataset.load_latest(wid) is not None
    # It goes to the results screen, not the wizard: unlike a new empty workspace, the demo
    # already has its config and data, so the screen the user pressed the button to see is ready.
    assert client.get(location).status_code == 200


def test_the_demo_run_produces_results(client):
    """The point of the dataset: it drives the real simulation, not just the list card."""
    r = client.post(
        "/workspaces/demo", headers={"sec-fetch-site": "same-origin"}, follow_redirects=False
    )
    wid = r.headers["location"].removeprefix("/w/").removesuffix("/results")
    computed = client.post(
        f"/w/{wid}/results",
        json={"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        headers={"sec-fetch-site": "same-origin"},
    )
    assert computed.status_code == 200
    assert str(HOURS) in computed.text or f"{HOURS:,}" in computed.text


def test_cross_site_post_is_refused(client):
    """Writes are same-site only, as for every other creating route."""
    r = client.post(
        "/workspaces/demo", headers={"sec-fetch-site": "cross-site"}, follow_redirects=False
    )
    assert r.status_code == 403
