"""Reifying a CSV-bound slot through the ingest WS (step 5 of the CSV-import brief, §2.2, §4.2a).

Steps 1–4 built the uploads store, the pure parser, the upload routes and `CsvSource`, each with its
own tests. What this module covers is the piece step 5 adds: the per-slot `(upload_id, column, unit)`
binding travelling from the client to the server on the `backend_load` message, and being loaded and
persisted alongside the HA slots as ONE dataset.

The cases, and why each is here rather than folded into an existing file:

  * **A CSV-bound slot lands in the dataset with its provenance.** The end-to-end property step 5
    exists for. Asserted through `dataset.load_latest`, i.e. after a persist and a restore, because
    "the frame was loaded" and "the frame survived" are different claims and only the second is what
    the user gets after the reload a fetch triggers.
  * **A foreign or absent `upload_id` is rejected and persists nothing.** This is the SECURITY case,
    and it is not defence in depth: under decision D-BIND the binding lives in browser
    `localStorage`, so the id arrives from the client on every fetch. `uploads.get` is
    workspace-scoped, so the check is that a workspace cannot name another workspace's upload — the
    test creates a real upload in workspace B and asks workspace A to load it.
  * **All-or-nothing.** A failing CSV slot must leave NO dataset, including when good HA series were
    streamed in the same fetch. The reify loop loads before it persists, so this is a property of
    that ordering; it is worth pinning because a future "load what you can" change would look like an
    improvement.
  * **The §7.3 warnings reach the dataset.** `_load_backend_frame` returns `(frame, warnings)`
    specifically so the CSV gap / DST-ambiguity counts are not silently dropped, which is exactly the
    kind of loss no other assertion notices.
  * **A flagged cumulative register survives the whole path UNDIFFERENCED** (D-KIND, and harness
    fixture 22's "At column selection" paragraph). The domain layer and the source adapter each pin
    this over a full column already (`tests/test_csv_wide.py`, `tests/test_csv_source.py`), but until
    `test_a_flagged_register_loads_through_the_reify_path_undifferenced` nothing pinned it *through*
    the reify path — the sibling warning test asserted only `values[0]`, which a differencing
    implementation that keeps the first reading would pass unchanged. Silently differencing is the
    one thing this format never does, so the property is asserted where a real fetch goes.

Isolation follows `tests/test_ingest_ws.py`: an isolated `BATTERY_SIM_DATA_DIR` with the modules
reloaded against it, so the SQLite DB, the `.npz` frames and the uploaded files never touch the
working tree. No network.

    uv run pytest tests/test_csv_binding_reify.py
"""

import importlib

import pytest

from tests.conftest import seed_workspace, w

# A window fully inside the fixture file's coverage. The file is hourly from 01-01-2025 00:00 UTC.
_WINDOW = {"start": "2025-01-01T00:00:00+00:00", "end": "2025-01-01T06:00:00+00:00"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient whose app writes to an isolated data dir, plus the modules bound to it.

    Mirrors `tests/test_ingest_ws.py`'s fixture exactly, with `app.uploads` added to the reload list:
    it captures the pre-reload `db` module at import, so without the reload an upload row would be
    written to whichever database that older module still points at — the same trap the existing
    fixture documents for `app.workspaces`.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.dataset as dataset
    importlib.reload(dataset)
    import app.uploads as uploads
    importlib.reload(uploads)
    import app.workspaces as workspaces
    importlib.reload(workspaces)
    import app.deps as deps
    importlib.reload(deps)
    import app.main as main
    importlib.reload(main)
    seed_workspace()
    from fastapi.testclient import TestClient
    return TestClient(main.app), main, dataset, uploads


def _wide_csv(n: int = 8, *, gap_at: int | None = None) -> str:
    """`n` hourly rows from 01-01-2025 00:00 with two value columns.

    Values rise and then fall so neither column reads as a cumulative register (a non-decreasing
    column warns; the warning would be noise in every test here). `gap_at` blanks one cell of
    `Verbruik` to raise `CSV_GAP_CELLS`.
    """
    lines = ["Tijdstip,Verbruik,Teruglevering"]
    for i in range(n):
        # A saw pattern: strictly not monotone, so the register heuristic stays out of the way.
        v = 0.5 if i % 2 else 0.1
        cell = "" if gap_at is not None and i == gap_at else f"{v:.1f}"
        lines.append(f"01-01-2025 {i:02d}:00:00,{cell},{v / 2:.2f}")
    return "\n".join(lines) + "\n"


def _store_upload(uploads, text: str, *, workspace_id: str = "local", tz: str = "UTC"):
    """Store `text` as an upload for `workspace_id`, the way step 3's route does (parse, then create).

    Goes through `uploads.create` rather than the HTTP route because what is under test here is the
    reify path, and the route has its own 48 tests in `tests/test_upload_routes.py`. Using the store
    directly also lets a test create an upload in a workspace the client never addresses, which is
    what the cross-workspace case needs.
    """
    from app.domain import csv_wide

    wide, summary = csv_wide.parse_and_summarise(text, tz)
    return uploads.create(
        workspace_id,
        filename="export.csv",
        tz=tz,
        content=text,
        columns=[wide.timestamp_name, *wide.columns],
        rows=summary.rows,
        resolution_s=summary.resolution_s,
        first_ts=summary.first_ts,
        last_ts=summary.last_ts,
    )


def _send_csv_fetch(ws, *, upload_id, column="Verbruik", unit="kWh", slot="grid_import_t1",
                    include_binding=True, with_ha=False):
    """Drive a fetch whose only (or first) slot is CSV-bound, and return the server's reply."""
    ws.send_json({"type": "header", "source": "home_assistant", "window": _WINDOW})
    if with_ha:
        # A real HA arm alongside the CSV slot, so the all-or-nothing case has something to lose.
        ws.send_json({"type": "series", "name": "grid_export_t1", "kind": "energy", "unit": "kWh",
                      "stat_id": "sensor.export_t1"})
        ws.send_json({"type": "rows", "name": "grid_export_t1",
                      "rows": [[1735689600000, 100.0], [1735693200000, 100.5],
                               [1735696800000, 101.0]]})
        assert ws.receive_json()["type"] == "progress"
    msg = {"type": "backend_load", "name": slot, "source": "csv_upload", "window": _WINDOW}
    if include_binding:
        msg["binding"] = {"upload_id": upload_id, "column": column, "unit": unit}
    ws.send_json(msg)
    ws.send_json({"type": "done"})
    return ws.receive_json()


# --- 1. the happy path: a CSV-bound slot is loaded, persisted, and restored --------------------

def test_csv_bound_slot_reifies_into_the_dataset(client):
    """The property step 5 exists for: the binding travels on the WS message and the series lands."""
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id)

    assert result["type"] == "result", result
    assert result["series"] == 1

    # Asserted after a persist-and-restore, not off the reply: what the user sees after the reload a
    # fetch triggers is `load_latest`'s answer.
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    assert {f.name for f in loaded.frames} == {"grid_import_t1"}
    # Per-series provenance records WHICH source filled the slot (`sources_map` in the reify loop).
    # Without it the roster would attribute a CSV slot to `home_assistant`, the dataset-level source.
    assert loaded.series_sources["grid_import_t1"] == "csv_upload"
    frame = loaded.frames[0]
    # Sliced to the requested 6-hour window, not the whole 8-row file — the source windows, and a
    # load that forgot to would be silently wrong (`csv_source.slice_to_window`).
    assert len(frame.values) == 6
    assert frame.resolution_s == 3600


def test_csv_and_ha_slots_persist_as_one_dataset(client):
    """A mixed fetch: HA streamed rows plus a CSV-bound slot, in ONE dataset with two provenances."""
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id, with_ha=True)

    assert result["type"] == "result", result
    assert result["series"] == 2
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert {f.name for f in loaded.frames} == {"grid_import_t1", "grid_export_t1"}
    assert loaded.series_sources["grid_import_t1"] == "csv_upload"
    assert loaded.series_sources["grid_export_t1"] == "home_assistant"


def test_two_slots_bind_to_two_columns_of_one_file(client):
    """Harness fixture 22's reuse case: one upload feeds two slots via two bindings.

    This is the whole reason uploading and binding are separate actions (§2.2) — a wide export holds
    many measurements — so it is worth pinning that the second binding is not overwritten by, or
    confused with, the first.
    """
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header", "source": "home_assistant", "window": _WINDOW})
        ws.send_json({"type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
                      "window": _WINDOW,
                      "binding": {"upload_id": upload.id, "column": "Verbruik", "unit": "kWh"}})
        ws.send_json({"type": "backend_load", "name": "grid_export_t1", "source": "csv_upload",
                      "window": _WINDOW,
                      "binding": {"upload_id": upload.id, "column": "Teruglevering",
                                  "unit": "kWh"}})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result", result
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    imp = next(f for f in loaded.frames if f.name == "grid_import_t1")
    exp = next(f for f in loaded.frames if f.name == "grid_export_t1")
    # `Teruglevering` is half of `Verbruik` in the fixture, so the two frames are distinguishable —
    # a test that only checked both names existed would pass with the same column loaded twice.
    assert abs(imp.values[0] - 2 * exp.values[0]) < 1e-9
    assert abs(exp.values[0] - 0.05) < 1e-9


def test_unit_wh_is_converted(client):
    """`unit` in the binding is honoured: Wh divides by 1000 (csv_wide.UNIT_FACTORS)."""
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id, unit="Wh")
    assert result["type"] == "result", result

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    frame = loaded.frames[0]
    # 0.1 Wh → 0.0001 kWh. Pinned as a VALUE rather than "not equal to the kWh case", so a mutation
    # that dropped the unit through would fail here rather than pass by coincidence.
    assert abs(frame.values[0] - 0.0001) < 1e-12


def test_absent_unit_defaults_to_kwh(client):
    """A binding with no `unit` is complete: kWh is CsvBinding's documented default."""
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header", "source": "home_assistant", "window": _WINDOW})
        ws.send_json({"type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
                      "window": _WINDOW,
                      "binding": {"upload_id": upload.id, "column": "Verbruik"}})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result", result
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert abs(loaded.frames[0].values[0] - 0.1) < 1e-9


# --- 2. §7.3 warnings survive the reify path ---------------------------------------------------

def test_csv_gap_warning_reaches_the_persisted_dataset(client):
    """`_load_backend_frame` returns warnings so §7.3's box can report them; they must be persisted.

    This is the assertion nothing else would make: dropping the warnings changes no frame, no
    provenance and no status code, so a bare-frame return would have been invisible.
    """
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv(gap_at=2))

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id)

    assert result["type"] == "result", result
    codes = [warn.get("code") for warn in result["warnings"]]
    assert "CSV_GAP_CELLS" in codes
    gap = next(w_ for w_ in result["warnings"] if w_.get("code") == "CSV_GAP_CELLS")
    assert gap["count"] == 1
    # Stamped with the slot, like `build_frames` stamps the HA warnings — an anonymous count cannot
    # be shown against a row.
    assert gap["series"] == "grid_import_t1"

    # And they are stored with the dataset, not merely echoed to this one client.
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert any(warn.get("code") == "CSV_GAP_CELLS" for warn in loaded.warnings)


# --- 3. the security case: a client-supplied upload_id is validated server-side -----------------

def test_upload_id_from_another_workspace_is_rejected_and_persists_nothing(client):
    """A workspace cannot load another workspace's upload by naming its id.

    The load-bearing test under decision D-BIND: the binding lives in browser localStorage, so the
    `upload_id` is client-supplied on every fetch. `uploads.get` filters on `workspace_id`, which is
    what makes a foreign id indistinguishable from a nonexistent one. The upload here is REAL and its
    id is correct — only the workspace asking for it is wrong, which is the case a shape check or an
    id-format check would let through.
    """
    tc, main, dataset, uploads = client
    seed_workspace("other")
    foreign = _store_upload(uploads, _wide_csv(), workspace_id="other")
    # The file really is there, under the other workspace — so a failure below cannot be "no such
    # file" by accident.
    assert uploads.get("other", foreign.id) is not None
    assert uploads.get("local", foreign.id) is None

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=foreign.id)

    assert result["type"] == "error", result
    # The message names the configuration gap, not a transport failure.
    assert "not fully configured" in result["message"] or "no longer has" in result["message"]
    # NOTHING was persisted: no dataset for the asking workspace…
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None
    # …and the other workspace's upload is untouched.
    assert uploads.get("other", foreign.id) is not None


def test_absent_upload_id_is_rejected_and_persists_nothing(client):
    """A well-formed id that no workspace has: same rejection, nothing written."""
    tc, main, dataset, uploads = client

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id="0" * 32)

    assert result["type"] == "error", result
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_malformed_upload_id_is_rejected_as_a_configuration_error(client):
    """A traversal-shaped id never becomes a path component (`uploads._check_upload_id`).

    The shape check in `ingest_ws` deliberately does not duplicate that guard (a weaker copy would
    look like the guard without being it), so the rejection happens inside the load — and it must
    read like the missing-binding case above, not like a transport failure. `_check_upload_id` raises
    a plain `ValueError`, which took `_load_backend_frame`'s generic branch and produced
    "could not load 'grid_import_t1' from 'csv_upload': unsafe upload_id: …"; the id is now
    translated to `CsvBindingError` where the binding is interpreted, so both the wording and the
    status the sibling HTTP route reports (400) follow from the one fix.
    """
    tc, main, dataset, uploads = client

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id="../../etc/passwd")

    assert result["type"] == "error", result
    assert "not fully configured" in result["message"], result
    # The rejected id is not quoted back at the client (`delete_upload` records why).
    assert "etc/passwd" not in result["message"], result
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_missing_binding_fails_the_fetch_with_a_configuration_message(client):
    """A CSV slot with no binding at all: rejected as unconfigured, not as a load failure.

    This is the shape a lifted `PENDING_SOURCE_KEYS` filter without a Confirm gate would produce, and
    the reason `csv_source.py` documents the filter as a guard.
    """
    tc, main, dataset, uploads = client

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id="unused", include_binding=False)

    assert result["type"] == "error", result
    assert "not fully configured" in result["message"]
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


# --- 4. binding shape rejection (ingest_ws._check_binding_shape) --------------------------------

@pytest.mark.parametrize(
    "binding, expected",
    [
        ("not-an-object", "must be an object"),
        ({"column": "Verbruik"}, "missing 'upload_id'"),
        ({"upload_id": "", "column": "Verbruik"}, "missing 'upload_id'"),
        ({"upload_id": "a" * 32}, "missing 'column'"),
        ({"upload_id": "a" * 32, "column": ""}, "missing 'column'"),
        ({"upload_id": "a" * 32, "column": 3}, "missing 'column'"),
        ({"upload_id": "a" * 32, "column": "A", "unit": 7}, "non-string 'unit'"),
    ],
)
def test_malformed_binding_shape_is_rejected_naming_the_field(client, binding, expected):
    """A malformed binding is refused by the protocol layer, naming the offending field.

    Checked here rather than only at the source because the message is what the user sees: "missing
    'column'" is actionable, while letting an integer column reach `column_frame` produces a
    complaint about an unknown column named `3`, which reads like a file problem.

    `done` is sent as well, deliberately. Without it, removing the shape check would leave the server
    waiting for more messages and this test would HANG rather than fail — a test that hangs under
    mutation is not a test that catches it (there is no pytest timeout plugin here). With `done`, an
    unchecked binding proceeds to a load that fails for its own reason, and the message assertion is
    what distinguishes the two: the shape error names the FIELD, the load error names the file or the
    column. The `receive_json` below therefore returns the FIRST error either way, which is the shape
    error when the check is present, since `on_backend_load` rejects before `done` is read.
    """
    tc, main, dataset, uploads = client

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header", "source": "home_assistant", "window": _WINDOW})
        ws.send_json({"type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
                      "window": _WINDOW, "binding": binding})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "error", result
    assert expected in result["message"]
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_a_non_csv_backend_slot_still_needs_no_binding(client):
    """The regression the `_CSV_SOURCE_KEY` condition prevents.

    `EnergyChartsSource.load`'s keyword-only extras are `opener`/`now`, so passing it `binding=` or
    `workspace_id=` raises `TypeError: unexpected keyword argument` — a blanket "thread the extras
    everywhere" would have broken the price path silently until a fetch ran. The window is inside the
    committed NL-2024 data so no network is touched (see `tests/test_slot_load.py`).
    """
    tc, main, dataset, uploads = client

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header", "source": "home_assistant",
                      "window": {"start": "2024-03-01T00:00:00+00:00",
                                 "end": "2024-03-05T00:00:00+00:00"}})
        ws.send_json({"type": "backend_load", "name": "price_spot", "source": "energy_charts",
                      "window": {"start": "2024-03-01T00:00:00+00:00",
                                 "end": "2024-03-05T00:00:00+00:00"}})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result", result
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert {f.name for f in loaded.frames} == {"price_spot"}
    assert loaded.series_sources["price_spot"] == "energy_charts"


# --- 5. all-or-nothing ------------------------------------------------------------------------

def test_a_failing_csv_slot_discards_the_whole_fetch_including_good_ha_series(client):
    """All-or-nothing (§2.2, §3.5): one bad CSV slot leaves NO dataset, HA rows included.

    The reify loop loads every backend slot BEFORE `save_dataset`, so this is a property of that
    ordering. Pinned because "persist what worked" is a plausible-looking change that would silently
    produce partial datasets — and because a partial dataset is worse than none here: the run would
    proceed against a meter series with no export series and report a result.
    """
    tc, main, dataset, uploads = client

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id="0" * 32, with_ha=True)

    assert result["type"] == "error", result
    # The HA series streamed fine and is nonetheless gone.
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_an_unknown_column_fails_the_fetch_and_persists_nothing(client):
    """A binding naming a column the file does not have: a clean failure, nothing written."""
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id, column="Nope", with_ha=True)

    assert result["type"] == "error", result
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_a_bad_unit_fails_the_fetch_and_persists_nothing(client):
    """`unit` is checked against `csv_wide.UNIT_FACTORS` before the file is read."""
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id, unit="MWh")

    assert result["type"] == "error", result
    assert "MWh" in result["message"]
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_a_cumulative_column_warns_and_the_fetch_still_succeeds(client):
    """D-KIND: a non-decreasing column reads as a meter register — warned about, not rejected.

    The behaviour this pins is the whole point of the change: the fetch must SUCCEED and must
    persist a dataset. Asserting only the warning would pass against an implementation that warned
    and then failed the load anyway, which is what this used to do.
    """
    tc, main, dataset, uploads = client
    lines = ["Tijdstip,Register"]
    for i in range(24):
        lines.append(f"01-01-2025 {i:02d}:00:00,{1000 + i * 0.4:.1f}")
    upload = _store_upload(uploads, "\n".join(lines) + "\n")

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id, column="Register")

    assert result["type"] == "result", result
    warn = next(
        w_ for w_ in result["warnings"] if w_.get("code") == "CSV_CUMULATIVE_COLUMN"
    )
    assert warn["column"] == "Register"
    # Stamped with the slot by the same plumbing that stamps CSV_GAP_CELLS, so the quality box can
    # say which row it is about.
    assert warn["series"] == "grid_import_t1"

    # A dataset exists, and it holds the column as read — undifferenced (D-KIND). The whole
    # 6-sample window slice is compared, not just `values[0]`: differencing that keeps the first
    # reading leaves element 0 alone, so a single-element assertion pinned nothing about the rest.
    # The dedicated test below carries the full argument.
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    frame = next(f for f in loaded.frames if f.name == "grid_import_t1")
    assert list(frame.values) == pytest.approx([1000 + i * 0.4 for i in range(6)])
    assert any(w_.get("code") == "CSV_CUMULATIVE_COLUMN" for w_ in loaded.warnings)


def test_a_flagged_register_loads_through_the_reify_path_undifferenced(client):
    """Harness fixture 22: the flagged column's OWN readings reach the dataset (D-KIND).

    The property the CSV path must never break. `ingest.cumulative_to_delta` exists for the Home
    Assistant path and is deliberately never called here, so a column that looks like a meter
    register is passed through as read — confidently wrong rather than silently altered.

    Pinned at THIS layer because the other two are already covered and neither is the path a fetch
    takes: `tests/test_csv_wide.py` pins it in `column_frame` and `tests/test_csv_source.py` pins it
    in `CsvSource.load_with_warnings`, while the values a user actually gets have also been through
    `_load_backend_frame`, the reify loop's persist, and `dataset.load_latest`. The sibling test
    above went through all of that but asserted one sample.

    Three choices make the assertion resistant to a differencing mutation rather than merely
    present:

      * a **constant** step (0.7 per hour). Every difference is then the same number, so a
        differenced series is a flat line — it cannot coincidentally resemble a rising one;
      * a step three orders of magnitude smaller than the readings (0.7 against ~5000), so no
        tolerance admits one for the other;
      * the window covers the WHOLE file, and the full array is compared, plus two explicit guards
        naming the two conventions a differencing implementation would pick — `np.diff` with the
        first reading kept (element 0 unchanged, element 1 becomes the step) and `np.diff` with a
        zero prepended (element 0 becomes 0.0).

    The warning is asserted too, so the test cannot quietly become a values-only check if the
    `CSV_CUMULATIVE_COLUMN` plumbing regresses.
    """
    tc, main, dataset, uploads = client
    readings = [5000.0 + 0.7 * i for i in range(24)]
    lines = ["Tijdstip,Register"]
    for i, v in enumerate(readings):
        lines.append(f"01-01-2025 {i:02d}:00:00,{v:.1f}")
    upload = _store_upload(uploads, "\n".join(lines) + "\n")

    # The whole file, unlike `_WINDOW`: the claim is about the column, so the slice must not hide
    # part of it.
    full_day = {"start": "2025-01-01T00:00:00+00:00", "end": "2025-01-02T00:00:00+00:00"}
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header", "source": "home_assistant", "window": full_day})
        ws.send_json({"type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
                      "window": full_day,
                      "binding": {"upload_id": upload.id, "column": "Register", "unit": "kWh"}})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result", result
    assert any(w_.get("code") == "CSV_CUMULATIVE_COLUMN" for w_ in result["warnings"]), result

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    frame = next(f for f in loaded.frames if f.name == "grid_import_t1")
    assert len(frame.values) == 24
    assert list(frame.values) == pytest.approx(readings)
    # The two differencing conventions, named so a failure says which one was introduced.
    assert frame.values[0] == pytest.approx(5000.0), "first reading replaced by a delta"
    assert frame.values[1] == pytest.approx(5000.7), "second reading replaced by the 0.7 step"
    assert frame.values[-1] == pytest.approx(5000.0 + 0.7 * 23), "series flattened to its deltas"


def test_csv_is_rejected_for_a_price_slot(client):
    """D-PRICE: `available_for` excludes price_spot, and the reify path enforces it before loading."""
    tc, main, dataset, uploads = client
    upload = _store_upload(uploads, _wide_csv())

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _send_csv_fetch(ws, upload_id=upload.id, slot="price_spot")

    assert result["type"] == "error", result
    assert "not available" in result["message"]
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None
