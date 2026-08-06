"""Tests for the wide-CSV upload routes (step 3; specs §4.2a, §2.2, harness fixture 22).

The three routes under test are the join between step 1's store (`app/uploads.py`) and step 2's
parser (`app/domain/csv_wide.py`), neither of which knows about the other:

    POST   /w/{id}/data/uploads              parse, then store; 201 with the dialog's summary
    GET    /w/{id}/data/uploads              the list, newest first
    DELETE /w/{id}/data/uploads/{upload_id}  row + file

What is asserted here, and why each claim is worth a test:

  * **Happy path** — a valid file yields 201, a row, a file on disk, and a payload carrying the
    header (with the timestamp column at index 0), the coverage and the resolution the dialog
    displays. `columns[0]` matters: the drawer offers `columns[1:]`, so an off-by-one here breaks
    every binding.
  * **A rejected upload writes NOTHING** — §4.2a and harness fixture 22's central promise, and the
    one property `uploads.create` cannot provide on its own. Checked for a missing header row, a
    first column that does not parse, a one-column file and a header-only file: each 400s with the
    parser's `code` and, where there is one, the offending `row` — and leaves the table and the
    uploads directory exactly as they were, including when a valid file was already there.
  * **The declared zone is applied once, at upload (D-TZ, harness fixture 22a)** — the same bytes
    declared `Europe/Amsterdam` and `UTC` produce first/last timestamps an hour apart, not
    identical ones; an unknown zone 400s; and an Amsterdam file spanning the October transition
    reports `ambiguous_rows` while the same dates declared UTC report zero.
  * **The size cap** — over `MAX_UPLOAD_BYTES` answers 413 and writes nothing, both when the client
    declares an oversized `Content-Length` and when it lies about it. The two branches are pinned
    SEPARATELY, by an input only one of them can answer plus the byte count only one of them names:
    a shared message let a mutation deleting the whole header check pass the suite.
  * **Failures the parser does not own** — a cell over the csv module's 128 KiB field limit
    (`_csv.Error`, which is not even a `ValueError`) and a client that disconnects mid-body both
    answer 400 rather than 500. Both were 500s once; the second is driven at the ASGI level because
    `TestClient` cannot send a disconnect.
  * **Request shapes** — a zero-byte file, `tz` absent from the form entirely (a different shape
    from `tz=""`), duplicate `file` parts, and a traversal-shaped filename that is stored as a
    literal display string while the file on disk keeps its uuid4 name.
  * **Nullability at the boundary** — `resolution_s: null` round-trips through both the POST and the
    GET for an irregular-spacing file and a single-row file, which is what §5.1's amended box means.
  * **Cross-workspace isolation, in its two separate mechanisms** — a workspace belonging to another
    PRINCIPAL is 404'd by `deps.get_workspace` before any handler runs (asserted on all three
    routes), while an id belonging to another workspace of the SAME owner is simply never acted on,
    because `uploads.delete` filters on `workspace_id`. The load-bearing assertion in the second case
    is that the other workspace's row and file survive, not the status code.
  * **Delete is idempotent** (user decision, 2026-08-06) — a second DELETE succeeds so a double-click
    on `[ remove ]` is harmless, with `existed` distinguishing the real removal from the no-op. A
    malformed id is still 400 (the store raises `ValueError` on a non-hex id; unhandled that would be
    a 500 on a hand-typed URL), because an invalid id is a client error and not an absent resource.
  * **CSRF** — the two state-changing routes are same-site checked and the GET is not, matching
    `app/csrf.py`'s destroy-or-create line.

Every test runs against an isolated data dir (BATTERY_SIM_DATA_DIR) so no SQLite database or
uploaded file touches the working tree. Nothing here hits the network.

    uv run pytest tests/test_upload_routes.py
"""

import importlib

import pytest

from tests.conftest import seed_workspace, w

# A minimal well-formed wide file: three hourly rows, two value columns (§4.2a's example shape).
_CSV = (
    "Tijdstip,Verbruik_T1,Teruglevering_T1\n"
    "01-01-2025 00:00:00,0.412,0.000\n"
    "01-01-2025 01:00:00,0.388,0.000\n"
    "01-01-2025 02:00:00,0.401,0.100\n"
)

# The October transition under Amsterdam: 02:00–03:00 occurs twice, so both 02:00 rows resolve to
# the same UTC instant and carry DST_AMBIGUOUS (D-DST). 2025's transition is 26 October.
_CSV_OCTOBER = (
    "Tijdstip,Verbruik\n"
    "26-10-2025 01:00:00,0.1\n"
    "26-10-2025 02:00:00,0.2\n"
    "26-10-2025 02:30:00,0.3\n"
    "26-10-2025 03:00:00,0.4\n"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient on an isolated data dir, plus the reloaded `main` and `uploads` modules.

    Same reload chain as `tests/test_slot_load.py`: `config` resolves the data dir once per call but
    `db`, `workspaces`, `deps` and `main` captured module objects at import, so every one of them
    has to be rebuilt against the new directory or the workspace row lands in the wrong database.
    `uploads` is reloaded too and returned, because `main` holds a reference to it and a test that
    queries the store directly must be querying the SAME module object the route wrote through.
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

    return TestClient(main.app), uploads, tmp_path


def _post(client, text=_CSV, *, tz="Europe/Amsterdam", filename="export.csv", path=None):
    """POST one file as multipart, the way the dialog's `FormData` will.

    `Sec-Fetch-Site: same-origin` on every call: the route is same-site checked, and while
    `app/csrf.py` allows a request carrying NEITHER header (a test client, `curl`), sending the
    header explicitly means these tests exercise the accepting branch that a browser will take
    rather than the unlabelled-request hole.
    """
    return client.post(
        path or w("/data/uploads"),
        files={"file": (filename, text.encode("utf-8"), "text/csv")},
        data={"tz": tz},
        headers={"Sec-Fetch-Site": "same-origin"},
    )


def _uploads_dir(tmp_path, workspace_id="local"):
    return tmp_path / workspace_id / "uploads"


def _csv_files(tmp_path, workspace_id="local"):
    d = _uploads_dir(tmp_path, workspace_id)
    return sorted(p.name for p in d.glob("*.csv")) if d.exists() else []


# ── 1. Happy path ────────────────────────────────────────────────────────────────────────────


def test_upload_stores_row_and_file_and_returns_the_summary(client):
    api, uploads, tmp_path = client
    r = _post(api)
    assert r.status_code == 201, r.text
    payload = r.json()["upload"]

    # The header, WITH the timestamp column at index 0 — the drawer offers columns[1:].
    assert payload["columns"] == ["Tijdstip", "Verbruik_T1", "Teruglevering_T1"]
    assert payload["timestamp_name"] == "Tijdstip"
    assert payload["rows"] == 3
    assert payload["resolution_s"] == 3600
    assert payload["filename"] == "export.csv"
    assert payload["tz"] == "Europe/Amsterdam"
    assert payload["ambiguous_rows"] == 0
    # 01-01-2025 00:00 Amsterdam is CET (+01:00), so 23:00 UTC the previous day.
    assert payload["first_ts"].startswith("2024-12-31T23:00:00")
    assert payload["last_ts"].startswith("2025-01-01T01:00:00")

    # The row exists, and the bytes landed under the app-assigned id (never the user's filename).
    stored = uploads.get("local", payload["id"])
    assert stored is not None
    assert stored.columns == payload["columns"]
    assert _csv_files(tmp_path) == [f"{payload['id']}.csv"]
    assert uploads.read_text("local", payload["id"]) == _CSV


_CSV_REGISTER = (
    "Tijdstip,Meterstand,Verbruik\n"
    + "".join(
        f"01-01-2025 {i:02d}:00:00,{14200 + i * 0.5:.1f},{0.3 + 0.1 * (i % 3):.1f}\n"
        for i in range(24)
    )
)
"""24 hourly rows: `Meterstand` rises throughout (a meter register), `Verbruik` does not.

Two columns rather than one, so a test can assert the verdict names the right one — a verdict that
flagged every column, or flagged by position, would pass against a single-column file.
"""


def test_upload_reports_which_columns_look_like_meter_registers(client):
    """The POST computes a per-column cumulative verdict and reports it (non-blocking).

    Three claims, and they fail for three different reasons: the upload SUCCEEDS (it used to be the
    binding, not the upload, that refused — but a verdict computed by raising would break this), the
    flagged column is named, and the ordinary column is not.
    """
    api, uploads, tmp_path = client
    r = _post(api, _CSV_REGISTER, tz="UTC")
    assert r.status_code == 201, r.text
    payload = r.json()["upload"]
    assert payload["cumulative_columns"] == ["Meterstand"]
    # Persisted, not merely echoed: the drawer reads this off the LIST route on every page load.
    assert uploads.get("local", payload["id"]).cumulative_columns == ["Meterstand"]


def test_the_verdict_is_an_empty_list_for_an_ordinary_file(client):
    """`[]` and not null: the check ran and found nothing, which is what licenses "no warning"."""
    api, uploads, tmp_path = client
    r = _post(api)
    assert r.json()["upload"]["cumulative_columns"] == []


def test_the_list_route_reports_the_verdict_too(client):
    """The LIST route is what the drawer actually reads, so the verdict has to be there.

    `ha_fetch.js` fills its file cache from `refreshCsvUploads`, i.e. from GET, never from the POST
    response. A verdict present only on the POST would annotate the column picker once and vanish on
    the next page load — the worst shape for a warning, since its absence reads as "this is fine".
    """
    api, uploads, tmp_path = client
    assert _post(api, _CSV_REGISTER, tz="UTC").status_code == 201

    r = api.get(w("/data/uploads"))
    assert r.status_code == 200
    rows = r.json()["uploads"]
    assert [row["cumulative_columns"] for row in rows] == [["Meterstand"]]


def test_a_non_numeric_column_does_not_break_the_verdict_for_the_others(client):
    """§4.2a defers the numeric check to SELECTION, so a text column must not fail the upload.

    `_cumulative_columns` skips a column it cannot parse. Without that, this file would 500 — the
    verdict pass would raise `CsvFormatError` for `Notitie` from inside a route that has already
    decided the file is acceptable.
    """
    api, uploads, tmp_path = client
    text = "Tijdstip,Meterstand,Notitie\n" + "".join(
        f"01-01-2025 {i:02d}:00:00,{100 + i:.1f},tekst\n" for i in range(24)
    )
    r = _post(api, text, tz="UTC")
    assert r.status_code == 201, r.text
    assert r.json()["upload"]["cumulative_columns"] == ["Meterstand"]


def test_a_file_part_with_no_filename_is_a_400(client):
    """A `file` part carrying no `filename=` is not a file as far as the parser is concerned.

    Starlette's multipart parser classifies a part by whether its Content-Disposition names a
    filename: with none it yields a plain `str` form value rather than an `UploadFile`, so the route
    cannot read bytes from it and answers 400. Asserted rather than assumed because the route's
    `isinstance(..., str)` branch reads as defensive and is in fact the branch this shape takes.
    A browser's `FormData.append(name, File)` always sets a filename, so step 6 will not hit it.
    """
    api, uploads, _tmp = client
    r = api.post(
        w("/data/uploads"),
        files={"file": ("", _CSV.encode("utf-8"), "text/csv")},
        data={"tz": "UTC"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "no_file"
    assert uploads.list_for("local") == []


def test_upload_accepts_a_utf8_bom(client):
    """A BOM'd file (Excel's default CSV export) parses, with the BOM stripped from column 1."""
    api, _uploads, _tmp = client
    r = _post(api, "﻿" + _CSV)
    assert r.status_code == 201, r.text
    assert r.json()["upload"]["columns"][0] == "Tijdstip"


def test_upload_uniquifies_duplicate_header_names(client):
    """The PARSED (uniquified) names are persisted, not the raw header cells.

    Bindings key on the uniquified name, so storing `["A", "A"]` would make one of the two columns
    unreachable. `csv_wide._value_column_names` produces `A` / `A (2)` / `Column 4`.
    """
    api, _uploads, _tmp = client
    text = "Tijdstip,A,A,\n01-01-2025 00:00:00,1,2,3\n01-01-2025 01:00:00,2,3,4\n"
    r = _post(api, text, tz="UTC")
    assert r.status_code == 201, r.text
    assert r.json()["upload"]["columns"] == ["Tijdstip", "A", "A (2)", "Column 4"]


def test_list_is_newest_first_and_delete_removes_row_and_file(client):
    api, uploads, tmp_path = client
    first = _post(api, filename="a.csv").json()["upload"]["id"]
    second = _post(api, filename="b.csv").json()["upload"]["id"]

    listed = api.get(w("/data/uploads")).json()["uploads"]
    assert [u["id"] for u in listed] == [second, first]
    # The list reads rows, not files, so it carries neither of the parse-only fields (D3-4).
    assert "ambiguous_rows" not in listed[0]
    assert "timestamp_name" not in listed[0]

    r = api.delete(
        w(f"/data/uploads/{first}"), headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": first, "existed": True}
    assert uploads.get("local", first) is None
    assert _csv_files(tmp_path) == [f"{second}.csv"]
    assert [u["id"] for u in api.get(w("/data/uploads")).json()["uploads"]] == [second]


def test_list_is_empty_not_404_when_nothing_uploaded(client):
    api, _uploads, _tmp = client
    r = api.get(w("/data/uploads"))
    assert r.status_code == 200
    assert r.json() == {"uploads": []}


# ── 2. A rejected upload writes nothing (§4.2a, harness fixture 22) ──────────────────────────

_REJECTED = [
    # (label, text, expected code, expected row)
    (
        "no header row (row 1 is data)",
        "01-01-2025 00:00:00,0.4\n01-01-2025 01:00:00,0.5\n",
        "missing_header",
        1,
    ),
    (
        "first column does not parse",
        "Tijdstip,V\nnot-a-timestamp,0.4\n",
        "bad_timestamp",
        2,
    ),
    ("only one column", "Tijdstip\n01-01-2025 00:00:00\n", "too_few_columns", None),
    ("header but no data rows", "Tijdstip,V\n", "no_data_rows", None),
    (
        "a row with the wrong number of cells",
        "Tijdstip,V\n01-01-2025 00:00:00,0,4\n",
        "row_length_mismatch",
        2,
    ),
    (
        "a March timestamp that does not exist in Amsterdam",
        "Tijdstip,V\n30-03-2025 02:30:00,0.4\n",
        "nonexistent_local_time",
        2,
    ),
]


@pytest.mark.parametrize("label,text,code,row", _REJECTED, ids=[c[0] for c in _REJECTED])
def test_malformed_upload_is_rejected_and_writes_nothing(client, label, text, code, row):
    """400 with the parser's code and row, and no row and no file left behind.

    The file is written before the row by `uploads.create`, so "no row" alone would not prove
    nothing was stored — the directory is checked too.
    """
    api, uploads, tmp_path = client
    r = _post(api, text)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code
    assert detail["row"] == row
    assert detail["message"]  # §4.2a: say what was expected and what was found
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


def test_rejection_leaves_an_earlier_valid_upload_intact(client):
    """Fixture 22: the first file is still listed and still readable after the second is refused."""
    api, uploads, tmp_path = client
    good = _post(api, filename="good.csv").json()["upload"]["id"]

    bad = _post(api, "Tijdstip,V\nnope,1\n", filename="bad.csv")
    assert bad.status_code == 400

    assert [u.id for u in uploads.list_for("local")] == [good]
    assert _csv_files(tmp_path) == [f"{good}.csv"]
    assert uploads.read_text("local", good) == _CSV


def test_non_utf8_file_is_a_400_and_writes_nothing(client):
    """A Latin-1 export answers 400 with its own code rather than escaping as a 500."""
    api, uploads, tmp_path = client
    body = "Tijdstip,Meterstand\n01-01-2025 00:00:00,0.4\n".encode("latin-1").replace(
        b"Meterstand", b"Meterstand\xe9"
    )
    r = api.post(
        w("/data/uploads"),
        files={"file": ("latin.csv", body, "text/csv")},
        data={"tz": "UTC"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "bad_encoding"
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


def test_missing_file_part_is_a_400(client):
    api, uploads, _tmp = client
    r = api.post(
        w("/data/uploads"),
        data={"tz": "UTC"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "no_file"
    assert uploads.list_for("local") == []


def test_zero_byte_file_is_a_400_missing_header(client):
    """An empty file is a missing header row, not a crash and not an empty upload."""
    api, uploads, tmp_path = client
    r = api.post(
        w("/data/uploads"),
        files={"file": ("empty.csv", b"", "text/csv")},
        data={"tz": "UTC"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "missing_header"
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


def test_a_cell_over_the_csv_field_limit_is_a_400_not_a_500(client):
    """A single value or column name over the csv module's 128 KiB field limit.

    `csv.reader` raises a bare `_csv.Error` for this, which is neither `CsvFormatError` nor even a
    `ValueError` (it derives straight from `Exception`), so catching the parser's own type alone let
    it escape as a 500 — reachable with a ~200 KB body, nowhere near `MAX_UPLOAD_BYTES`.
    """
    api, uploads, tmp_path = client
    text = "Tijdstip," + "x" * 200_000 + "\n01-01-2025 00:00:00,1\n01-01-2025 01:00:00,2\n"
    r = _post(api, text, tz="UTC")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "unreadable_csv"
    assert detail["row"] is None
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


def test_client_disconnect_mid_body_is_a_400_not_a_500(client):
    """A cancelled or dropped upload answers 400, matching a stock `UploadFile` route.

    `request.stream()` raises `starlette.requests.ClientDisconnect` on an `http.disconnect`, and
    uncaught that is a logged traceback for an ordinary network event. Driven at the ASGI level
    because `TestClient` cannot send a disconnect mid-body.

    No response reaches the client — it is what went away — so the assertion is on the status the app
    GENERATED, read off the ASGI `send` messages.
    """
    import asyncio

    api, uploads, tmp_path = client
    app = api.app
    sent = []

    async def receive():
        if not sent:
            sent.append(1)
            return {"type": "http.request", "body": b"x" * 100, "more_body": True}
        return {"type": "http.disconnect"}

    messages = []

    async def send(message):
        messages.append(message)

    path = w("/data/uploads")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"multipart/form-data; boundary=abc"),
            (b"content-length", b"100000"),
            (b"sec-fetch-site", b"same-origin"),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))  # must not raise

    starts = [m for m in messages if m["type"] == "http.response.start"]
    assert starts and starts[0]["status"] == 400
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


# ── 3. The declared zone is applied once, at upload (D-TZ; harness fixture 22a) ──────────────


def test_the_same_bytes_differ_by_the_offset_under_the_two_zones(client):
    """Fixture 22a: Amsterdam and UTC declarations of one file are not identical."""
    api, _uploads, _tmp = client
    ams = _post(api, tz="Europe/Amsterdam").json()["upload"]
    utc = _post(api, tz="UTC").json()["upload"]
    assert ams["first_ts"].startswith("2024-12-31T23:00:00")
    assert utc["first_ts"].startswith("2025-01-01T00:00:00")
    assert ams["first_ts"] != utc["first_ts"]
    assert ams["tz"] == "Europe/Amsterdam" and utc["tz"] == "UTC"


def test_october_amsterdam_file_reports_ambiguous_rows_and_utc_does_not(client):
    """Fixture 22a: the repeated hour is flagged under Amsterdam, and not under UTC.

    `ambiguous_rows` is the count §7.3's data-quality box reports. It is returned by the POST and
    deliberately not persisted (D3-4), so this is the only place it crosses the boundary.
    """
    api, _uploads, _tmp = client
    ams = _post(api, _CSV_OCTOBER, tz="Europe/Amsterdam").json()["upload"]
    assert ams["ambiguous_rows"] == 2  # 02:00 and 02:30 exist under both offsets

    utc = _post(api, _CSV_OCTOBER, tz="UTC").json()["upload"]
    assert utc["ambiguous_rows"] == 0


@pytest.mark.parametrize("tz", ["", "Europe/Brussels", "CET", "utc"])
def test_unknown_timezone_is_a_400_and_writes_nothing(client, tz):
    """Validated against `csv_wide.TZ_KEYS` before the decode, so it is never an encoding error."""
    api, uploads, tmp_path = client
    r = _post(api, tz=tz)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "bad_timezone"
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


def test_an_absent_tz_field_is_the_same_400_as_an_empty_one(client):
    """`tz` missing from the form entirely, which is a different REQUEST SHAPE from `tz=""`.

    The route collapses both with `form.get("tz") or ""`, so they answer identically — asserted
    rather than assumed, since a `None` reaching `str()` would have produced `"None"` and a message
    naming a zone the client never sent.
    """
    api, uploads, _tmp = client
    r = api.post(
        w("/data/uploads"),
        files={"file": ("a.csv", _CSV.encode("utf-8"), "text/csv")},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "bad_timezone"
    assert "''" in detail["message"]  # reported as empty, not as "None"
    assert uploads.list_for("local") == []


# ── 4. The size cap ─────────────────────────────────────────────────────────────────────────


def test_oversized_declared_body_is_413_before_anything_is_read(client, monkeypatch):
    """A declared Content-Length over the cap answers 413, and the HEADER branch is what answered.

    The cap is monkeypatched small rather than posting 32 MiB: the assertion is about the check, not
    about the constant, and `main` reads `uploads.MAX_UPLOAD_BYTES` per request.

    **The input is chosen so the two 413 branches are distinguishable.** An earlier version posted a
    body that was genuinely over the cap, so the streaming check answered it identically and deleting
    the entire Content-Length check left this test passing (review item M3 — a surviving mutant). Here
    the real body is TINY and only the declared length is huge, so the streaming check can never fire;
    and the header branch's message names the declared size while the streaming branch's does not, so
    the assertion on that number proves which one ran.
    """
    api, uploads, tmp_path = client
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 200)
    r = api.post(
        w("/data/uploads"),
        content=b"tiny",
        headers={
            "Sec-Fetch-Site": "same-origin",
            "Content-Length": "1000000000",
            "Content-Type": "multipart/form-data; boundary=abc",
        },
    )
    assert r.status_code == 413
    # Only the header branch knows the declared size; the streaming branch reports the limit alone.
    assert r.json()["detail"] == "file too large: 1000000000 bytes, limit is 200"
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


def test_the_streaming_branch_reports_no_byte_count(client, monkeypatch):
    """The counterpart to the test above: an honest small header, an oversized real body.

    Together the two pin which branch answers which request. This one's message deliberately carries
    no declared size, because there is no honest one to name.
    """
    api, uploads, _tmp = client
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 64)

    def chunks():
        for _ in range(20):
            yield b"x" * 100

    r = api.post(
        w("/data/uploads"), content=chunks(), headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "file too large: over the limit of 64 bytes"
    assert uploads.list_for("local") == []


def test_oversized_body_is_413_even_when_content_length_lies(client, monkeypatch):
    """A chunked or mis-declared body is still capped, by the streaming byte count.

    `httpx` sends a generator body with `Transfer-Encoding: chunked` and no Content-Length, which
    is exactly the case the header check cannot see. Without the streaming check this would be
    accepted in full.
    """
    api, uploads, tmp_path = client
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 64)

    def chunks():
        for _ in range(20):
            yield b"x" * 100

    r = api.post(
        w("/data/uploads"), content=chunks(), headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 413
    assert uploads.list_for("local") == []
    assert _csv_files(tmp_path) == []


def test_a_body_at_the_cap_is_accepted(client, monkeypatch):
    """The cap is a limit, not an off-by-one: a body of exactly `limit` bytes still passes.

    Multipart framing means the *body* is larger than the CSV, so the cap is set from the encoded
    request rather than from `len(_CSV)`.
    """
    api, uploads, _tmp = client
    probe = api.build_request(
        "POST",
        w("/data/uploads"),
        files={"file": ("export.csv", _CSV.encode("utf-8"), "text/csv")},
        data={"tz": "UTC"},
    )
    exact = len(probe.read())
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", exact)
    r = _post(api, tz="UTC")
    assert r.status_code == 201, r.text


# ── 5. Cross-workspace isolation ────────────────────────────────────────────────────────────


def test_another_workspace_neither_lists_nor_deletes_this_ones_uploads(client):
    """An id belonging to another workspace of the SAME owner is never acted on.

    The load-bearing assertion is that the row and the file survive — `uploads.delete` filters on
    `workspace_id`, so the foreign call is a no-op on the other workspace's data. That property is
    unchanged by the move to an idempotent delete.

    The STATUS did change, from 404 to 200, and that is the deliberate consequence of the user's
    2026-08-06 decision rather than a weakening. Both workspaces here belong to the same principal,
    so there is no confidentiality boundary between them: the requester supplied the id, owns both
    workspaces, and learns only "this workspace has no such upload", which is true. The store cannot
    distinguish "never existed" from "exists elsewhere" through its public API anyway (both are
    False/None, by design — it has no unscoped query), so a 404 for only the foreign case was never
    available without breaking that invariant. Cross-OWNER isolation is a separate mechanism and is
    asserted in the next test.
    """
    api, uploads, tmp_path = client
    from app import workspaces

    workspaces.create("Other analysis", "other", owner_id="local")
    mine = _post(api).json()["upload"]["id"]

    other = "/w/other/data/uploads"
    assert api.get(other).json() == {"uploads": []}
    r = api.delete(f"{other}/{mine}", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200
    # It reports having removed NOTHING, which is what actually happened over there.
    assert r.json() == {"deleted": mine, "existed": False}
    # The point of the test: the other workspace's row and file are untouched.
    assert uploads.get("local", mine) is not None
    assert _csv_files(tmp_path) == [f"{mine}.csv"]
    assert [u["id"] for u in api.get(w("/data/uploads")).json()["uploads"]] == [mine]


def test_a_different_owners_workspace_is_404_before_the_store_is_consulted(client):
    """Cross-OWNER isolation, which is where the real scoping guarantee lives.

    `deps.get_workspace` rejects a workspace the requesting principal does not own with a 404 before
    the handler runs, so the store is never reached and the idempotent delete cannot soften it. This
    is the test that pins the boundary the old blanket 404 was mistakenly credited with defending —
    asserted for all three routes so a future change to one of them cannot quietly drop it.
    """
    api, uploads, _tmp = client
    from app import workspaces

    workspaces.create("Theirs", "theirs", owner_id="someone-else")
    mine = _post(api).json()["upload"]["id"]

    theirs = "/w/theirs/data/uploads"
    assert api.get(theirs).status_code == 404
    assert api.post(
        theirs,
        files={"file": ("x.csv", _CSV.encode("utf-8"), "text/csv")},
        data={"tz": "UTC"},
        headers={"Sec-Fetch-Site": "same-origin"},
    ).status_code == 404
    r = api.delete(f"{theirs}/{mine}", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 404
    # Not a 200-with-existed-false: the dependency refused, so nothing about the upload was examined.
    assert "existed" not in r.text
    assert uploads.get("local", mine) is not None


def test_upload_to_an_unknown_workspace_is_404(client):
    api, _uploads, _tmp = client
    r = _post(api, path="/w/nope/data/uploads")
    assert r.status_code == 404


# ── 6. Delete edge cases ────────────────────────────────────────────────────────────────────


def test_delete_a_well_formed_id_that_never_existed_succeeds(client):
    """A syntactically valid id this workspace has never held is a no-op, not an error.

    The end state the request asked for already holds, which is the same reasoning
    `deps.get_optional_workspace` applies to the workspace-deletion routes. `existed: false` says
    there was nothing to remove.
    """
    api, _uploads, _tmp = client
    r = api.delete(
        w("/data/uploads/" + "0" * 32), headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": "0" * 32, "existed": False}


@pytest.mark.parametrize("bad", ["not-hex", "ZZZZ", "abc", "0" * 31, "0" * 33])
def test_delete_malformed_id_is_400_not_500(client, bad):
    """The store raises ValueError on a non-hex id; unhandled that would be a 500 on a typed URL."""
    api, _uploads, _tmp = client
    r = api.delete(w(f"/data/uploads/{bad}"), headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "bad_upload_id"


def test_malformed_id_message_does_not_echo_the_submitted_segment(client):
    """The 400 must not reflect raw user input back, even into a JSON body.

    `uploads._check_upload_id` builds `f"unsafe upload_id: {upload_id!r}"`, so forwarding `str(exc)`
    put attacker-chosen bytes in the response — verified with a NUL byte, which came back as
    `unsafe upload_id: '\\x00abc'`. Not an XSS hole at the HTTP layer, but the client already knows
    what it sent, so a fixed message costs nothing and removes the question.
    """
    api, _uploads, _tmp = client
    r = api.delete(
        w("/data/uploads/%00sentinelXYZ"), headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 400
    assert "sentinelXYZ" not in r.text
    assert "\\u0000" not in r.text and "\x00" not in r.text


def test_delete_is_idempotent(client):
    """A second DELETE of the same id succeeds, so a double-click on `[ remove ]` is harmless.

    User decision, 2026-08-06. The route previously answered 404 on the second call, on the reasoning
    that a JSON API call should tell the dialog its list is stale — which this test's earlier version
    argued for. That was the wrong trade: the file IS removed, so an error in front of the user
    describes a failure that did not happen, and it contradicted `deps.get_optional_workspace`'s
    "already-gone is fine" convention for no decided reason.

    Both calls answer 200 with the same `deleted` id. Only `existed` differs, which is what lets a
    caller reconciling a stale list tell "I just did that" from "my list was out of date" without the
    end state depending on it.
    """
    api, uploads, tmp_path = client
    uid = _post(api).json()["upload"]["id"]

    first = api.delete(w(f"/data/uploads/{uid}"), headers={"Sec-Fetch-Site": "same-origin"})
    assert first.status_code == 200
    assert first.json() == {"deleted": uid, "existed": True}

    second = api.delete(w(f"/data/uploads/{uid}"), headers={"Sec-Fetch-Site": "same-origin"})
    assert second.status_code == 200
    assert second.json() == {"deleted": uid, "existed": False}

    # Idempotent in effect as well as in status: still gone, and nothing was recreated.
    assert uploads.get("local", uid) is None
    assert _csv_files(tmp_path) == []


# ── 7. CSRF (app/csrf.py's destroy-or-create line) ──────────────────────────────────────────


def test_cross_site_upload_and_delete_are_403(client):
    api, uploads, tmp_path = client
    r = _post(api, path=None)
    uid = r.json()["upload"]["id"]

    cross = {"Sec-Fetch-Site": "cross-site"}
    r = api.post(
        w("/data/uploads"),
        files={"file": ("x.csv", _CSV.encode("utf-8"), "text/csv")},
        data={"tz": "UTC"},
        headers=cross,
    )
    assert r.status_code == 403
    assert api.delete(w(f"/data/uploads/{uid}"), headers=cross).status_code == 403

    # Neither reached the store.
    assert [u.id for u in uploads.list_for("local")] == [uid]
    assert _csv_files(tmp_path) == [f"{uid}.csv"]


def test_cross_site_list_is_allowed(client):
    """The GET is a read, so it carries no same-site check (`app/csrf.py`'s line)."""
    api, _uploads, _tmp = client
    r = api.get(w("/data/uploads"), headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200


# ── 8. Request shapes and stored-summary round-trips ────────────────────────────────────────


def test_duplicate_file_parts_take_the_last(client):
    """Two `file` parts in one request: Starlette's form is last-wins, and exactly one is stored.

    Defensible (a `MultiDict` keeps both and `.get` returns the last) but undocumented, so pinned
    here rather than left as a surprise. The point of the assertion is that ONE upload results, not
    two — a request with a duplicated part must not silently create a second row.
    """
    api, uploads, tmp_path = client
    second = _CSV + "01-01-2025 03:00:00,0.5,0.0\n"
    r = api.post(
        w("/data/uploads"),
        files=[
            ("file", ("first.csv", _CSV.encode("utf-8"), "text/csv")),
            ("file", ("second.csv", second.encode("utf-8"), "text/csv")),
        ],
        data={"tz": "UTC"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()["upload"]
    assert payload["filename"] == "second.csv"
    assert payload["rows"] == 4
    assert len(uploads.list_for("local")) == 1
    assert len(_csv_files(tmp_path)) == 1


def test_a_traversal_shaped_filename_is_stored_as_a_literal_display_string(client):
    """The user's filename is DISPLAY-only and never a path component (`uploads.Upload.filename`).

    This is the assertion that documents that invariant rather than trusting it: the name comes back
    verbatim, including the `../` and the slashes, and the file on disk is still named for the
    app-assigned uuid4 hex — nothing escaped the workspace's `uploads/` directory.
    """
    api, _uploads, tmp_path = client
    r = _post(api, filename="../../etc/passwd.csv", tz="UTC")
    assert r.status_code == 201, r.text
    payload = r.json()["upload"]
    assert payload["filename"] == "../../etc/passwd.csv"
    assert _csv_files(tmp_path) == [f"{payload['id']}.csv"]
    # Nothing anywhere under the data dir is named for the submitted string.
    assert not list(tmp_path.rglob("passwd.csv"))


@pytest.mark.parametrize(
    "label,text",
    [
        (
            "irregular spacing (no modal answer)",
            "Tijdstip,V\n01-01-2025 00:00:00,1\n01-01-2025 00:07:00,2\n"
            "01-01-2025 03:00:00,3\n01-01-2025 09:31:00,4\n",
        ),
        ("a single data row (no spacing at all)", "Tijdstip,V\n01-01-2025 00:00:00,1\n"),
    ],
)
def test_null_resolution_round_trips_through_post_and_get(client, label, text):
    """`resolution_s: null` survives both the POST response and the GET list.

    `infer_resolution_s` returns None when no spacing covers more than half the gaps, and such a file
    is still a legitimate upload — the resolution is a summary for display, not a validity condition.
    That nullability is what the step-1 review amended `08-architecture.md` §5.1 for, so it is pinned
    at the boundary as well as in the store: a route that coerced None to 0 would report "hourly" for
    a file with no inferable resolution.
    """
    api, _uploads, _tmp = client
    r = _post(api, text, tz="UTC")
    assert r.status_code == 201, r.text
    payload = r.json()["upload"]
    assert payload["resolution_s"] is None

    listed = [u for u in api.get(w("/data/uploads")).json()["uploads"] if u["id"] == payload["id"]]
    assert listed and listed[0]["resolution_s"] is None


@pytest.mark.parametrize(
    "header,row,expected",
    [
        (",A,B", "01-01-2025 00:00:00,1,2", ["", "A", "B"]),
        ("Tijdstip,Tijdstip", "01-01-2025 00:00:00,1", ["Tijdstip", "Tijdstip"]),
    ],
)
def test_columns_zero_is_not_uniquified(client, header, row, expected):
    """`columns[0]` may be empty or duplicate a value column — a trap for index-based step-6 code.

    `csv_wide._value_column_names` de-duplicates over `header[1:]` only, so the timestamp name never
    participates. Both files are accepted, and name-based resolution still works (the value columns'
    own names are unique among themselves). Pinned so step 6 knows `columns.indexOf(name)` can
    return 0 — it must slice for the selector and send the NAME back, never a searched index.
    """
    api, _uploads, _tmp = client
    r = _post(api, f"{header}\n{row}\n", tz="UTC")
    assert r.status_code == 201, r.text
    assert r.json()["upload"]["columns"] == expected
