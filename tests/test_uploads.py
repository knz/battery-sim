"""Unit tests for the uploaded-CSV store (app/uploads.py, docs/specs/08-architecture.md §5.1).

This is step 1 of the CSV-import work (changelog/20260805-csv-uploads-storage.md): the `uploads`
table and the per-workspace file store, with no routes, no parser and no slot binding involved.
The tests therefore feed `create` a summary directly rather than parsing anything — which is also
the contract, since the store does not parse.

Covered here:

  * round-trip — a created upload reads back with every field intact, including the JSON-encoded
    header and the tz-aware UTC timestamps;
  * the file lands at `<data_dir>/<workspace>/uploads/<upload_id>.csv` with the app-assigned id as
    its name, NOT the user's filename, and two uploads of the same filename stay separate;
  * `list_for` is newest-first and workspace-scoped;
  * `get` / `delete` are workspace-scoped, so another workspace's id reads as absent;
  * traversal is rejected on both the workspace id and the upload id, and rejected BEFORE any
    directory is created or any row is read — for BOTH ids, which an earlier version of the
    before-any-mkdir test only claimed;
  * a bad argument to `create` leaves no file, not merely no row: an ordinary argument error is not
    the crash the residue argument was made about;
  * an offset-bearing `first_ts` / `last_ts` is normalised to UTC on both the create and read paths;
  * `MAX_UPLOAD_BYTES` exists and is deliberately not enforced here;
  * `delete` removes row and file, is idempotent, and tolerates a file that is already gone;
  * `delete_all_rows` removes rows and LEAVES files, which is what `workspaces.delete` relies on;
  * `workspaces.delete` removes the rows and the files; `workspaces.delete_data` removes neither
    (the §2′.3 split, decision D7 in the changelog).

Each test points the data dir at a pytest tmp_path via BATTERY_SIM_DATA_DIR so nothing touches the
repo's ./data. The app modules read `config.data_dir()` per call, so setting the env var is enough.

    uv run pytest tests/test_uploads.py
"""

from datetime import datetime, timezone

import pytest

_CSV = (
    "Tijdstip,Verbruik_T1,Teruglevering_T1\n"
    "01-01-2025 00:00:00,0.412,0.000\n"
    "01-01-2025 01:00:00,0.388,0.000\n"
)

_COLUMNS = ["Tijdstip", "Verbruik_T1", "Teruglevering_T1"]
_FIRST = datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc)
_LAST = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    """The persistence modules bound to a throwaway data dir."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import config, uploads, workspaces

    return {"config": config, "uploads": uploads, "workspaces": workspaces, "tmp": tmp_path}


def _create(uploads, workspace_id="ws1", *, filename="export.csv", tz="Europe/Amsterdam", **kw):
    """One upload with the fixture summary, overridable per test."""
    fields = dict(
        filename=filename,
        tz=tz,
        content=_CSV,
        columns=_COLUMNS,
        rows=2,
        resolution_s=3600,
        first_ts=_FIRST,
        last_ts=_LAST,
    )
    fields.update(kw)
    return uploads.create(workspace_id, **fields)


# ── Round-trip ───────────────────────────────────────────────────────────────────────────────


def test_create_round_trips_every_field(mods):
    uploads = mods["uploads"]
    made = _create(uploads)

    read = uploads.get("ws1", made.id)
    assert read is not None
    assert read.id == made.id
    assert read.workspace_id == "ws1"
    assert read.filename == "export.csv"
    assert read.tz == "Europe/Amsterdam"
    # The header comes back as a list, not the JSON text it is stored as.
    assert read.columns == _COLUMNS
    assert read.rows == 2
    assert read.resolution_s == 3600
    assert read.first_ts == _FIRST
    assert read.last_ts == _LAST
    # Timestamps read back tz-aware, so a caller can compare them without a TypeError.
    assert read.uploaded_at.tzinfo is not None
    assert read.first_ts.tzinfo is not None


def test_nullable_summary_fields_round_trip_as_none(mods):
    """A file too irregular for `infer_resolution_s` is still a legitimate upload."""
    uploads = mods["uploads"]
    made = _create(uploads, resolution_s=None, first_ts=None, last_ts=None)

    read = uploads.get("ws1", made.id)
    assert (read.resolution_s, read.first_ts, read.last_ts) == (None, None, None)


def test_the_cumulative_verdict_round_trips(mods):
    """The per-column cumulative verdict survives storage, which is the whole reason it is a column.

    The drawer fills its file cache from the LIST route, not from the upload POST's response, so a
    verdict that did not persist would annotate the column picker once and then vanish on reload.
    Asserted on `get` and on `list_for`, because `_COLUMNS` is read POSITIONALLY by `_row_to_upload`
    and a column added to only some of the queries fails silently.
    """
    uploads = mods["uploads"]
    made = _create(uploads, cumulative_columns=["Meterstand", "Teruglevering"])
    assert made.cumulative_columns == ["Meterstand", "Teruglevering"]

    read = uploads.get("ws1", made.id)
    assert read.cumulative_columns == ["Meterstand", "Teruglevering"]
    assert uploads.list_for("ws1")[0].cumulative_columns == ["Meterstand", "Teruglevering"]


def test_an_empty_verdict_is_not_the_same_as_no_verdict(mods):
    """`[]` (computed, nothing flagged) and None (never computed) must stay distinguishable.

    Only `[]` licenses a reader to say "this file has no suspect columns". Collapsing None to `[]`
    would make a row written before the column existed claim a check that never ran.
    """
    uploads = mods["uploads"]
    checked = _create(uploads, cumulative_columns=[])
    unchecked = _create(uploads, cumulative_columns=None)

    assert uploads.get("ws1", checked.id).cumulative_columns == []
    assert uploads.get("ws1", unchecked.id).cumulative_columns is None
    # And the default is the "unknown" one: a caller that does not compute a verdict must not be
    # recorded as having found nothing.
    assert _create(uploads).cumulative_columns is None


def test_an_older_table_without_the_verdict_column_is_migrated(mods):
    """A database created before `cumulative_columns_json` existed keeps working.

    Reproduced rather than asserted about: the pre-change table is created by hand, a row is written
    into it, and then the module's own `connect` must grow the table so every `_COLUMNS`-based SELECT
    still resolves. Without the migration this fails with "no such column", which is what an existing
    local installation would have hit on its first read.

    The pre-existing row reads back with `cumulative_columns is None` — the migration adds the column
    NULL and deliberately does not backfill, since backfilling would mean re-parsing every stored
    file to answer a question the picker can simply not answer for that row.
    """
    uploads = mods["uploads"]
    from app import db

    old_schema = """
    CREATE TABLE uploads (
        id           TEXT    NOT NULL PRIMARY KEY,
        workspace_id TEXT    NOT NULL,
        filename     TEXT    NOT NULL,
        tz           TEXT    NOT NULL,
        columns_json TEXT    NOT NULL,
        rows         INTEGER NOT NULL,
        resolution_s INTEGER,
        first_ts     TEXT,
        last_ts      TEXT,
        uploaded_at  TEXT    NOT NULL
    );
    """
    conn = db.connect()
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO uploads (id, workspace_id, filename, tz, columns_json, rows, "
        "resolution_s, first_ts, last_ts, uploaded_at) "
        "VALUES (?, 'ws1', 'oud.csv', 'UTC', '[\"Tijdstip\", \"Verbruik\"]', 2, "
        "3600, NULL, NULL, '2026-01-01T00:00:00+00:00')",
        ("a" * 32,),
    )
    conn.close()

    old = uploads.get("ws1", "a" * 32)
    assert old is not None, "an existing row must still be readable after the migration"
    assert old.filename == "oud.csv"
    assert old.cumulative_columns is None

    # And a new row written against the migrated table carries its verdict.
    made = _create(uploads, cumulative_columns=["Verbruik"])
    assert uploads.get("ws1", made.id).cumulative_columns == ["Verbruik"]


def test_read_text_returns_the_stored_bytes(mods):
    uploads = mods["uploads"]
    made = _create(uploads)
    assert uploads.read_text("ws1", made.id) == _CSV


def test_connect_creates_the_table_on_a_fresh_installation(mods):
    """The public `connect()` must add `uploads` to db.py's schema, or a query would 404 the table.

    `list_for` proves this indirectly; this pins the public entry point directly, since step 3 and
    the workspace card may want to query `uploads` alongside other tables on one connection.
    """
    uploads = mods["uploads"]
    with uploads.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 0
        # db.py's own schema is present on the same connection.
        assert conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["first_ts", "last_ts"])
def test_offset_bearing_timestamps_are_normalised_to_utc(mods, field):
    """An aware non-UTC argument reads back as UTC, not at its original offset.

    The same INSTANT either way, so every comparison agrees — which is exactly why an unconverted
    offset went unnoticed. The visible difference is wall-clock: `.hour` and anything that formats
    the value report Amsterdam time where the field is documented as UTC.
    """
    from datetime import timedelta

    uploads = mods["uploads"]
    amsterdam_summer = timezone(timedelta(hours=2))
    aware = datetime(2025, 7, 1, 12, 0, tzinfo=amsterdam_summer)
    made = _create(uploads, **{field: aware})

    for value in (getattr(made, field), getattr(uploads.get("ws1", made.id), field)):
        # Same instant...
        assert value == aware
        # ...but expressed as UTC, so wall-clock reads are right.
        assert value.utcoffset() == timedelta(0)
        assert value.hour == 10
    # The create-path result and the read-path result are indistinguishable.
    assert getattr(made, field) == getattr(uploads.get("ws1", made.id), field)


def test_get_returns_none_for_an_unknown_id(mods):
    uploads = mods["uploads"]
    assert uploads.get("ws1", "0" * 32) is None


# ── The file, and the app-assigned id ────────────────────────────────────────────────────────


def test_file_is_named_by_the_app_assigned_id_not_the_filename(mods):
    uploads, tmp = mods["uploads"], mods["tmp"]
    made = _create(uploads, filename="../../etc/passwd")

    path = tmp / "ws1" / "uploads" / f"{made.id}.csv"
    assert path.exists()
    assert path.read_text() == _CSV
    # The hostile filename is stored verbatim for display and used for no path.
    assert made.filename == "../../etc/passwd"
    assert list((tmp / "ws1" / "uploads").iterdir()) == [path]


def test_two_uploads_of_the_same_filename_stay_separate(mods):
    """A name is not an identity: the second must not overwrite the first (§5.1)."""
    uploads = mods["uploads"]
    a = _create(uploads, filename="export.csv", content="a\n1\n", columns=["a"], rows=1)
    b = _create(uploads, filename="export.csv", content="b\n2\n", columns=["b"], rows=1)

    assert a.id != b.id
    assert uploads.read_text("ws1", a.id) == "a\n1\n"
    assert uploads.read_text("ws1", b.id) == "b\n2\n"
    assert len(uploads.list_for("ws1")) == 2


@pytest.mark.parametrize(
    ("kwargs", "exc"),
    [
        ({"rows": "not-an-int"}, ValueError),           # int(rows)
        ({"columns": [object()]}, TypeError),           # json.dumps of a non-JSON value
        ({"first_ts": "2025-01-01"}, AttributeError),   # str has no .isoformat
        ({"last_ts": "2025-01-01"}, AttributeError),
        ({"resolution_s": "hourly"}, ValueError),       # int(resolution_s)
    ],
)
def test_a_bad_argument_writes_no_file(mods, kwargs, exc):
    """A rejected `create` must leave nothing behind — a plain argument error is not a crash.

    These all used to raise INSIDE the INSERT's argument tuple, i.e. after the file was written, and
    because `create` never returns the caller never learned the generated id. The residue was
    therefore unreachable and undeletable, from a mistake that could have been reported for free.
    The coercions now run before the write.
    """
    uploads, tmp = mods["uploads"], mods["tmp"]
    with pytest.raises(exc):
        _create(uploads, **kwargs)

    assert uploads.list_for("ws1") == []
    # No stray .csv anywhere under the workspace — the directory may exist, a file must not.
    assert list((tmp / "ws1" / "uploads").glob("*.csv")) == []


def test_max_upload_bytes_is_a_declared_cap_this_module_does_not_enforce(mods):
    """Pins the constant's existence and its documented non-enforcement (step 3 owns the check).

    Two claims, both load-bearing for step 3. The cap is exported from here so the route and its
    tests share one number rather than each carrying a literal; and `create` deliberately does NOT
    apply it, because by the time it runs the content is already in memory and rejecting would be
    too late to have protected anything. A future reader who adds the check here should have to
    change this test, and should then find the reasoning in the constant's docstring.
    """
    uploads = mods["uploads"]
    assert uploads.MAX_UPLOAD_BYTES == 32 * 1024 * 1024

    # Genuinely over the cap, so the non-enforcement is demonstrated rather than assumed. 32 MiB of
    # a single repeated character costs little to build and writes fast; a smaller stand-in would
    # prove nothing about a limit it does not cross.
    oversized = "x" * (uploads.MAX_UPLOAD_BYTES + 1)
    made = _create(uploads, content=oversized, columns=["a"], rows=1)
    assert uploads.path_for("ws1", made.id).stat().st_size == len(oversized)


def test_path_for_sits_beside_the_series_directory(mods):
    """One workspace is one directory on disk: `uploads/` next to `series/`."""
    uploads, tmp = mods["uploads"], mods["tmp"]
    made = _create(uploads)
    assert uploads.path_for("ws1", made.id).parent == tmp / "ws1" / "uploads"


# ── Listing and workspace scoping ────────────────────────────────────────────────────────────


def test_list_for_is_newest_first(mods):
    uploads = mods["uploads"]
    first = _create(uploads, filename="jan.csv")
    second = _create(uploads, filename="feb.csv")
    third = _create(uploads, filename="mar.csv")

    listed = uploads.list_for("ws1")
    assert len(listed) == 3
    # Uploads within the same clock resolution are ordinary; the order must at least be a stable
    # permutation of the three, with the newest-first intent visible when the clock does separate
    # them. Assert set-equality plus the descending-timestamp property rather than a strict order
    # a same-microsecond tie could legitimately break.
    assert {u.id for u in listed} == {first.id, second.id, third.id}
    stamps = [u.uploaded_at for u in listed]
    assert stamps == sorted(stamps, reverse=True)


def test_list_for_is_workspace_scoped(mods):
    uploads = mods["uploads"]
    mine = _create(uploads, "ws1")
    theirs = _create(uploads, "ws2")

    assert [u.id for u in uploads.list_for("ws1")] == [mine.id]
    assert [u.id for u in uploads.list_for("ws2")] == [theirs.id]


def test_list_for_is_empty_on_a_fresh_installation(mods):
    """No row and no `uploads` table has ever been written: this must not raise "no such table"."""
    assert mods["uploads"].list_for("ws1") == []


def test_get_does_not_cross_workspaces(mods):
    """Another workspace's upload id reads as absent, not as a row."""
    uploads = mods["uploads"]
    theirs = _create(uploads, "ws2")
    assert uploads.get("ws1", theirs.id) is None
    assert uploads.get("ws2", theirs.id) is not None


def test_delete_does_not_cross_workspaces(mods):
    uploads = mods["uploads"]
    theirs = _create(uploads, "ws2")

    assert uploads.delete("ws1", theirs.id) is False
    # The other workspace's row AND file both survive the attempt.
    assert uploads.get("ws2", theirs.id) is not None
    assert uploads.path_for("ws2", theirs.id).exists()


# ── Traversal ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "", ".", ".."])
def test_unsafe_workspace_id_is_rejected(mods, bad):
    uploads = mods["uploads"]
    with pytest.raises(ValueError):
        _create(uploads, bad)
    with pytest.raises(ValueError):
        uploads.list_for(bad)
    with pytest.raises(ValueError):
        uploads.path_for(bad, "0" * 32)


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "..",
        "",
        "a" * 31,
        "a" * 33,
        "0" * 31 + "Z",  # right length, wrong alphabet
        "0" * 31 + "A",  # uppercase hex is not what uuid4().hex produces
    ],
)
def test_unsafe_upload_id_is_rejected(mods, bad):
    uploads = mods["uploads"]
    for call in (uploads.get, uploads.delete, uploads.path_for, uploads.read_text):
        with pytest.raises(ValueError):
            call("ws1", bad)


def test_bad_workspace_id_is_rejected_before_any_directory_is_created(mods):
    """The guard runs before the mkdir, so a rejected workspace id leaves no trace on disk."""
    uploads, tmp = mods["uploads"], mods["tmp"]
    with pytest.raises(ValueError):
        _create(uploads, "../escape")
    assert not (tmp.parent / "escape").exists()
    assert list(tmp.iterdir()) == []


def test_bad_upload_id_is_rejected_before_any_directory_is_created(mods):
    """`path_for(create_dir=True)` must validate the UPLOAD id before it mkdirs.

    This is the case the previous test's name over-claimed: it passed only a bad workspace id, so
    it stayed green while `path_for` was spelled as a single expression whose left operand — the
    mkdir — Python evaluates first. A bad upload id then raised with `uploads/` already created.
    """
    uploads, tmp = mods["uploads"], mods["tmp"]
    with pytest.raises(ValueError):
        uploads.path_for("wsX", "zzz", create_dir=True)
    assert not (tmp / "wsX").exists()
    assert list(tmp.iterdir()) == []


# ── Deletion ─────────────────────────────────────────────────────────────────────────────────


def test_delete_removes_row_and_file(mods):
    uploads = mods["uploads"]
    made = _create(uploads)
    path = uploads.path_for("ws1", made.id)

    assert uploads.delete("ws1", made.id) is True
    assert uploads.get("ws1", made.id) is None
    assert not path.exists()


def test_delete_is_idempotent(mods):
    uploads = mods["uploads"]
    made = _create(uploads)
    assert uploads.delete("ws1", made.id) is True
    assert uploads.delete("ws1", made.id) is False


def test_delete_tolerates_a_file_that_is_already_gone(mods):
    """Residue from an interrupted earlier delete must not block the row delete."""
    uploads = mods["uploads"]
    made = _create(uploads)
    uploads.path_for("ws1", made.id).unlink()

    assert uploads.delete("ws1", made.id) is True
    assert uploads.get("ws1", made.id) is None


def test_delete_leaves_the_other_uploads_alone(mods):
    uploads = mods["uploads"]
    keep = _create(uploads, filename="keep.csv")
    drop = _create(uploads, filename="drop.csv")

    uploads.delete("ws1", drop.id)
    assert [u.id for u in uploads.list_for("ws1")] == [keep.id]
    assert uploads.path_for("ws1", keep.id).exists()


# ── Workspace deletion (§2′.3's two operations) ──────────────────────────────────────────────


def test_workspace_delete_removes_uploads_rows_and_files(mods):
    """Every row keyed by the workspace's id goes with it (§5.5 invariant 1)."""
    uploads, workspaces = mods["uploads"], mods["workspaces"]
    workspaces.create("Mine", "ws1", owner_id=workspaces.OWNER_ID)
    made = _create(uploads, "ws1")
    path = uploads.path_for("ws1", made.id)
    assert path.exists()

    workspaces.delete("ws1")

    assert uploads.list_for("ws1") == []
    # The file went with the workspace directory, not in a separate step.
    assert not path.exists()
    assert not path.parent.exists()


def test_workspace_delete_does_not_touch_another_workspaces_uploads(mods):
    uploads, workspaces = mods["uploads"], mods["workspaces"]
    for wid in ("ws1", "ws2"):
        workspaces.create(wid, wid, owner_id=workspaces.OWNER_ID)
    mine = _create(uploads, "ws1")
    theirs = _create(uploads, "ws2")

    workspaces.delete("ws1")

    assert uploads.list_for("ws1") == []
    assert [u.id for u in uploads.list_for("ws2")] == [theirs.id]
    assert uploads.path_for("ws2", theirs.id).exists()
    assert uploads.get("ws1", mine.id) is None


def test_delete_all_rows_removes_rows_and_leaves_files(mods):
    """The rows-only contract `workspaces.delete` depends on.

    Called directly rather than through `workspaces.delete`, which follows it with an `rmtree` of
    the whole workspace directory and so would hide whether the files were left. The split is
    deliberate: leaving them here is what keeps `workspaces.delete` from traversing the same tree
    twice, and a future change that made this remove files too would be silently redundant rather
    than visibly wrong.
    """
    uploads = mods["uploads"]
    a = _create(uploads, "ws1")
    b = _create(uploads, "ws1")
    theirs = _create(uploads, "ws2")

    uploads.delete_all_rows("ws1")

    assert uploads.list_for("ws1") == []
    assert uploads.path_for("ws1", a.id).exists()
    assert uploads.path_for("ws1", b.id).exists()
    # Scoped: another workspace's row is untouched.
    assert [u.id for u in uploads.list_for("ws2")] == [theirs.id]


@pytest.mark.parametrize("bad", ["../evil", "a/b", "", ".", ".."])
def test_delete_all_rows_rejects_an_unsafe_workspace_id(mods, bad):
    with pytest.raises(ValueError):
        mods["uploads"].delete_all_rows(bad)


def test_delete_data_keeps_uploads(mods):
    """§2′.3: clearing the data keeps the configuration, and an upload is nearer configuration."""
    uploads, workspaces = mods["uploads"], mods["workspaces"]
    workspaces.create("Mine", "ws1", owner_id=workspaces.OWNER_ID)
    made = _create(uploads, "ws1")

    workspaces.delete_data("ws1")

    assert [u.id for u in uploads.list_for("ws1")] == [made.id]
    assert uploads.path_for("ws1", made.id).exists()
    assert uploads.read_text("ws1", made.id) == _CSV
