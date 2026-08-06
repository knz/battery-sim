"""Uploaded CSV files: the `uploads` table and the per-workspace file store (§5.1, §4.2a).

The CSV import path (docs/specs/05-data-formats.md §4.2a) separates two tasks that the Home
Assistant path does not have to separate. A user uploads a **wide** file once — a timestamp column
plus one column per measurement — and that file then persists server-side, per workspace. Later,
in each slot's source drawer, they bind that slot to a `(upload_id, column, unit)` triple. One
file therefore feeds many slots and many fetches, which is precisely why the upload cannot be part
of a fetch: tying it to one would force a re-upload per run.

This module is the persistence half of that. It owns two things, and nothing else:

  * **The `uploads` row** — `id, workspace_id, filename, tz, columns, rows, resolution_s,
    first_ts, last_ts, uploaded_at`, exactly the shape docs/specs/08-architecture.md §5.1 names.
    `filename` is the user's original name, kept for DISPLAY only (see below). `tz` is the zone
    they declared at upload — `Europe/Amsterdam` or `UTC` — which the parser has already applied,
    so it is a record of what was done rather than an instruction for later. The remaining fields
    are the parse summary the upload dialog and the drawer's file selector show: the header, the
    row count, the inferred resolution and the coverage.
  * **The file** at `<data_dir>/<workspace_id>/uploads/<upload_id>.csv`, beside the `series/`
    directory the dataset writes, under the same workspace directory and behind the same
    traversal-rejecting helper — so a workspace stays one directory on disk.

## Why the id is app-assigned and the filename is never a path component

`<upload_id>` is a generated uuid4 hex, not the name the user's browser sent. Two exports may
share a name (`export.csv` twice, from two months), and a name is therefore not an identity — the
second upload would silently overwrite the first, and any slot bound to it would start reading
different measurements without anything having changed from the user's point of view. Beyond that,
a browser-supplied filename is untrusted input, and building a path from it is the classic
traversal hole. `_upload_path` derives the path from the id ALONE and additionally validates the
id as hex, so even a caller that passes an id from an untrusted place cannot escape the directory.
The original name survives as a column, shown to the user and used for nothing.

## What is NOT here

No parsing. `app/domain/csv_wide.py` is the pure parser and this module never calls it: an upload
that fails to parse must leave no row and no file (the brief's step 3), which means the ROUTE
parses first and only calls `create` once it has a summary in hand. `create` cannot reject a bad
file because it never looks inside one; it takes a summary it is told.

No slot binding either. The binding `(upload_id, column, unit)` is per-slot CONFIGURATION, not
data, so it lives with the slot's stored source choice rather than on the upload row — one upload
can back several bindings, and a binding outlives nothing about the file except its id. **And that
stored source choice is not server state at all:** decision D-BIND (candidate E) puts it in the
browser, in `localStorage ha.slots.<workspace>`, from where it reaches the server only on the
ingest-WS `backend_load` message. So "not on the upload row" understates it — there is no table,
no column and no document key anywhere holding a binding, which is why `delete` below has no
cascade to run and why the `upload_id` arriving with a load is client-supplied and must be checked
against `get`.

## Ordering, and the one thing that is not atomic

The row and the file are two stores and cannot be committed as a unit; SQLite cannot roll back a
filesystem write. So the ORDER is chosen for which crash leaves the better wreckage, the same
argument `workspaces.delete` and `dataset.upsert_series` make:

  * `create` writes the FILE first, then the row. A crash between them leaves a file nothing
    references — unreachable residue, since every reader reaches a file through its row — rather
    than a row promising a file that is not there, which would present as a corrupt upload.
  * `delete` removes the ROW first, then the file. Same reasoning mirrored: the user asked for the
    upload to be gone, and a crash after the row delete leaves residue rather than an upload that
    still lists but can no longer be read.

Neither residue is reclaimed by a sweep; the cost is wasted disk, never a wrong answer.

**That argument covers a crash and nothing else.** It is not a licence for ordinary errors to leave
files behind, and it was briefly read as one: `create` used to coerce its arguments inside the
INSERT's tuple, so a wrong-typed `rows` or a string `first_ts` raised with the file already written
and the generated id never returned to anyone — residue that was unreachable *and* undeletable, from
a mistake the caller could have been told about before any write. The coercions now all happen
before the write; see `create`. A crash between two stores is unavoidable, a preventable one is not.

**Do not nest this module's writes inside another module's transaction** (decision D-SEQ; this is
architecture rather than this module's doing). `create` and `delete` each open their own
connection, so calling either inside an open `dataset.connect()` transaction fails with "database
is locked" — `BEGIN IMMEDIATE` holds the write lock and a second connection waits out
`db._TIMEOUT_S` before raising. `db.bump_source_generation` fails identically in the same position,
so this is the pre-existing cross-connection shape rather than anything the CSV path introduced,
and WAL would not help: the conflict is writer-vs-writer, which SQLite serialises under every
journal mode. Anyone combining an uploads write with another store's write has to SEQUENCE them
across the two transactions — and then pick which crash they prefer, as above — or thread a
connection parameter through, the way `workspaces.delete` declined to.

The CSV load path stays clear of this by construction rather than by care: the `get` a load
performs completes before `dataset.upsert_series` opens its transaction (`app/main.py`
`_load_backend_frame` records it), and there is no second write to sequence, because under D-BIND
the binding is not server state.

## Owner scoping

Every row carries `workspace_id` (§5.5 invariant 1) and every query in this module filters on it —
`get`, `list_for`, `delete` and `path_for` all take one and none of them can be called without.
There is no `owner_id` column, for the same reason `datasets` has none: ownership lives on the
`workspaces` row and a workspace-scoped route has already been through `deps.get_workspace`'s
`_authorize` before it reaches here (see changelog/20260804-owner-scoping.md). What this module
must not do is answer a query that is not workspace-scoped, and it has no such function.

Main items:
    Upload                          one row: id, filename, tz, header, parse summary.
    MAX_UPLOAD_BYTES                the size cap step 3's route enforces.
    connect()                       a connection with this schema (and app/db.py's) applied.
    create(workspace_id, filename, tz, content, columns, rows, ...) -> Upload   file + row.
    get(workspace_id, upload_id) -> Upload | None                one row, workspace-scoped.
    list_for(workspace_id) -> list[Upload]                       newest first.
    delete(workspace_id, upload_id) -> bool                      row then file; False if absent.
    path_for(workspace_id, upload_id) -> Path                    where the bytes are.
    read_text(workspace_id, upload_id) -> str                    the stored CSV text.
    delete_all_rows(workspace_id) -> None                        for workspace deletion.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import config, db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
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
CREATE INDEX IF NOT EXISTS uploads_workspace ON uploads (workspace_id);
"""
"""The `uploads` table, as docs/specs/08-architecture.md §5.1 names it.

Two spellings differ from the spec's sketch and both are deliberate. `columns` is stored as
`columns_json`, because it holds a JSON array of the header strings and a bare `columns` reads as a
count of them; the public API exposes it as `list[str]`, so the encoding does not leak. (An earlier
version of this comment also called `columns` keyword-adjacent in SQLite. It is not — SQLite accepts
it unquoted — and the naming stands on the reads-as-a-count ground alone.) And `resolution_s` / `first_ts` / `last_ts` are NULLABLE: a well-formed
file always has all three, but `infer_resolution_s` returns None for a file whose spacing is too
irregular for a modal answer (app/domain/ingest.py), and that file is still a legitimate upload —
the resolution is a summary for display, not a validity condition.

There is no added-columns migration list here, unlike `dataset._SERIES_META_ADDED_COLUMNS`. This
table has never shipped, so no installation carries an older shape to grow, and an empty migration
list would assert a mechanism that is not yet needed. `dataset._migrate` is the pattern to copy
when the first column is genuinely added.

The index on `workspace_id` is for `list_for`, the only query that is not by primary key. It is
not needed at this scale — a household has a handful of uploads — and is here because the column
is in the WHERE clause of every non-key read, which is the shape an index exists for.
"""

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
"""The size cap on one uploaded file (step 3's route enforces it; this module does not).

Declared here rather than in the route because it is a property of the store — what this module is
willing to hold — and because the tests for both halves want the same number. 32 MiB is generous
for the format: a year of quarter-hourly readings across ten columns is roughly 4 MB of text, so
the cap is not a limit a real household export approaches. It exists to bound a mistake (a wrong
file, a runaway export) rather than to express a policy about how much data is reasonable.

The cap is NOT enforced in `create`. By the time `create` runs, the route has already parsed the
content, which means it has already held it in memory — rejecting here would be too late to have
protected anything. The check belongs at the edge, before the read.
"""


@dataclass(frozen=True)
class Upload:
    """One uploaded file: its identity, what the user declared, and the parse summary.

    `id` is the app-assigned uuid4 hex that names the file on disk. `filename` is the user's
    original name and is for DISPLAY only — never a path component (module comment).

    `tz` is the zone the user declared at upload (`Europe/Amsterdam` or `UTC`, decision D-TZ in the
    CSV-import brief). It is a record, not an instruction: the parser has already converted the
    timestamps to UTC, so nothing downstream re-applies it. It is kept because the dialog shows
    what a file was read as, and because a user who picked the wrong zone needs to see that they
    did before deciding to re-upload.

    `columns` is the parsed header in file order, INCLUDING the timestamp column at index 0 — the
    drawer's column selector offers `columns[1:]`, and keeping index 0 means a column's position
    in this list is its position in the file, which is what `csv_wide` is asked for by index.

    `rows` is the count of DATA rows, header excluded. `resolution_s` is `infer_resolution_s`'
    answer and is None when no spacing dominates. `first_ts` / `last_ts` are the coverage in
    tz-aware UTC, and are None only for a file with no parseable rows, which the route rejects
    before it gets here.
    """

    id: str
    workspace_id: str
    filename: str
    tz: str
    columns: list[str]
    rows: int
    resolution_s: int | None
    first_ts: datetime | None
    last_ts: datetime | None
    uploaded_at: datetime


def _connect():
    """A connection with this module's table created, layered on app/db.py's schema.

    Same shape as `dataset._connect`: `db.connect()` resolves the data dir, opens the shared file
    and applies its own schema, and this adds `uploads` on top. Used as a context manager it is a
    transaction (`db._Connection`).
    """
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def connect():
    """The public spelling of `_connect`, for callers that query `uploads` alongside other tables.

    Exists for the same reason `dataset.connect` does: `db.connect()` alone does not create this
    table, so a query against it on an installation where nothing has ever been uploaded would
    fail with "no such table" rather than returning nothing.
    """
    return _connect()


def _uploads_dir(workspace_id: str, *, create: bool = True) -> Path:
    """`<data_dir>/<workspace>/uploads/`. Rejects path traversal (§5.5 invariant 4).

    The same guard as `dataset._series_dir` and `simconfig_store._workspace_dir`, duplicated
    rather than imported for the same reason those two duplicate each other: a directory under the
    workspace root is owned equally by whichever module writes there, and importing the dataset
    layer to compute a path would make this module depend on it for nothing else.

    `create=False` is for the read and delete paths, which must not bring a directory into
    existence merely by asking where a file would be — the same distinction `workspaces._workspace_dir`
    draws for deletion.
    """
    _check_workspace_id(workspace_id)
    d = config.data_dir() / workspace_id / "uploads"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _check_workspace_id(workspace_id: str) -> str:
    """The §5.5 invariant-4 guard, split out so the SQL-only paths can apply it too.

    `dataset._series_dir` and `simconfig_store._workspace_dir` inline this check because everything
    they do is a path. Here it has to be separable: `list_for` and `delete_all_rows` touch only
    SQLite, so routing them through `_uploads_dir` for the check would either create a directory as
    a side effect of a read or need a `create=False` call whose return value is discarded — both of
    which read as accidental and would be easy to drop later.

    Checking a workspace id that is only ever a bound SQL parameter is not about injection, which
    the parameter binding already precludes. It is about the store answering ONE question about
    ONE workspace: `""` or `".."` is not a workspace, and returning an empty list for it (or
    deleting the rows of whatever it matches, which is nothing) quietly accepts a caller bug that
    a raise surfaces. It also keeps the guard uniform, so no reader has to work out which of these
    functions validates and which does not.
    """
    if "/" in workspace_id or "\\" in workspace_id or workspace_id in ("", ".", ".."):
        raise ValueError(f"unsafe workspace_id: {workspace_id!r}")
    return workspace_id


def _check_upload_id(upload_id: str) -> str:
    """Reject anything that is not a plausible generated id, before it becomes a path component.

    Ids are produced by `uuid.uuid4().hex` — 32 lowercase hex characters — so a strict check is
    available and there is no reason to accept less. This is belt-and-braces against traversal:
    the id reaches this module from a URL path segment (step 3's `DELETE …/uploads/{upload_id}`)
    and from a stored slot binding, and while both are app-assigned in the normal course, "the
    value in the URL is one we generated" is an assumption rather than a guarantee. Checking the
    SHAPE rather than checking for `..` is the stronger form: it admits nothing surprising at all,
    instead of enumerating what to forbid.
    """
    if len(upload_id) != 32 or any(c not in "0123456789abcdef" for c in upload_id):
        raise ValueError(f"unsafe upload_id: {upload_id!r}")
    return upload_id


def path_for(workspace_id: str, upload_id: str, *, create_dir: bool = False) -> Path:
    """Where the bytes of one upload live. Validates both ids; does not check the file exists.

    Public because `CsvSource.load` (step 4) needs the path for a binding it has already resolved,
    and because a caller streaming a large file should not have to go through `read_text`.

    **BOTH ids are validated before the filesystem is touched at all**, and the two-statement
    spelling below is what makes that true. Written as the one-liner it was —
    `_uploads_dir(workspace_id, create=create_dir) / f"{_check_upload_id(upload_id)}.csv"` — Python
    evaluates the left operand of `/` first, so a bad UPLOAD id raised only after `create_dir=True`
    had already mkdir'd the workspace's `uploads/` directory. The residue was a stray empty
    directory rather than an escape, but the guarantee this docstring states was false, and a guard
    whose stated ordering is wrong is worse than one that makes no claim.
    """
    _check_upload_id(upload_id)
    return _uploads_dir(workspace_id, create=create_dir) / f"{upload_id}.csv"


def _to_utc(dt: datetime | None) -> datetime | None:
    """A datetime as tz-aware UTC, or None. Naive is read as UTC; aware is CONVERTED.

    Exactly `dataset._as_utc`'s rule, with a None passthrough. Both halves matter and the aware
    half was initially missing here, which made the docstrings above wrong rather than merely
    incomplete: a `first_ts` supplied at `+02:00` read back at `+02:00`. That is the same INSTANT,
    so any comparison still answers correctly — which is precisely why it survived the tests — but
    `.hour`, `.replace(...)` and anything that formats the value all report Amsterdam wall-clock
    where the field is documented as UTC. The CSV path makes that reachable rather than theoretical:
    under D-TZ an Amsterdam upload is converted by the parser, and a caller that passed the
    pre-conversion aware value, or a row hand-edited to carry an offset, lands exactly here.

    Duplicated from `dataset._as_utc` rather than imported, for the reason `_uploads_dir` duplicates
    the traversal guard: this module would otherwise depend on the dataset layer for one three-line
    convention it shares with it and nothing else.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(ts: str | None) -> datetime | None:
    """A stored ISO timestamp as tz-aware UTC, or None.

    Naive stored instants are read as UTC and offset-bearing ones are converted, per `_to_utc` —
    the same rule as `dataset._as_utc` and `workspaces._parse`: the pipeline holds UTC (§4.4), and
    comparing a naive against an aware datetime raises. Under D-TZ the parser has already
    converted, so a naive value can only come from a hand-edited row.
    """
    if not ts:
        return None
    return _to_utc(datetime.fromisoformat(ts))


def _row_to_upload(row) -> Upload:
    """One SELECT row, in `_COLUMNS` order, as an `Upload`."""
    return Upload(
        id=row[0],
        workspace_id=row[1],
        filename=row[2],
        tz=row[3],
        columns=list(json.loads(row[4])),
        rows=int(row[5]),
        resolution_s=None if row[6] is None else int(row[6]),
        first_ts=_parse_ts(row[7]),
        last_ts=_parse_ts(row[8]),
        uploaded_at=_parse_ts(row[9]),  # type: ignore[arg-type]  # NOT NULL, always present
    )


_COLUMNS = (
    "id, workspace_id, filename, tz, columns_json, rows, resolution_s, "
    "first_ts, last_ts, uploaded_at"
)
"""The SELECT list every read shares, so `_row_to_upload` can index positionally.

Written once rather than repeated per query: the mapping from position to field is the one thing
that silently breaks when a column is added to only some of the queries.
"""


def create(
    workspace_id: str,
    *,
    filename: str,
    tz: str,
    content: str,
    columns: list[str],
    rows: int,
    resolution_s: int | None = None,
    first_ts: datetime | None = None,
    last_ts: datetime | None = None,
) -> Upload:
    """Store `content` as a new upload for this workspace and record its summary. Returns the row.

    The summary arguments (`columns`, `rows`, `resolution_s`, `first_ts`, `last_ts`) come from the
    caller's parse — this module does not parse (module comment), so it takes what it is told and
    cannot reject a malformed file. That is the route's job, and it must parse BEFORE calling here,
    because a rejected upload must leave no row and no file.

    Keyword-only past `workspace_id`: nine of the ten parameters are metadata of comparable type
    (three strings, three optionals) and a positional call would be unreadable and easy to
    transpose — `filename` and `tz` are both strings and swapping them produces a stored row that
    is wrong in a way nothing detects.

    The FILE is written before the row, so a crash between them leaves residue rather than a row
    pointing at nothing (module comment). `content` is written as UTF-8 with `newline=""` left to
    the default text encoder, i.e. the text is stored as given: this is the user's file, and
    normalising its line endings would make the stored bytes differ from what they uploaded for no
    gain — `csv_wide` reads lines either way.

    **Every argument is coerced BEFORE the write**, which is a stronger property than the ordering
    above and a separate one. The module comment argues that an unreferenced file is tolerable
    residue because a crash cannot be prevented — but an ordinary argument error is not a crash,
    and it used to produce the same residue in a strictly worse form: `int(rows)`, `json.dumps` and
    `.isoformat()` all ran in the INSERT's argument tuple, after the file existed, so
    `rows="not-an-int"` or `first_ts="2025-01-01"` raised with the file on disk and — since `create`
    never returned — no caller ever learning the id that could reach it. Unreachable *and*
    undeletable, from a mistake the caller could have been told about for free. So the coercions
    move above the write: a bad argument now raises with nothing written, and the crash-residue
    argument covers only the crash it was made about.
    """
    # Coerced up front — see the docstring. Everything below this block is either pure filesystem
    # or pure SQL, so no argument-shape error can fire once the file exists.
    columns_json = json.dumps(list(columns))
    columns_list = list(columns)
    row_count = int(rows)
    resolution = None if resolution_s is None else int(resolution_s)
    first_iso = first_ts.isoformat() if first_ts else None
    last_iso = last_ts.isoformat() if last_ts else None
    uploaded_at = datetime.now(timezone.utc)

    upload_id = uuid.uuid4().hex
    path = path_for(workspace_id, upload_id, create_dir=True)
    path.write_text(content, encoding="utf-8")

    with _connect() as conn:
        conn.execute(
            f"INSERT INTO uploads ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                upload_id,
                workspace_id,
                filename,
                tz,
                columns_json,
                row_count,
                resolution,
                first_iso,
                last_iso,
                uploaded_at.isoformat(),
            ),
        )

    return Upload(
        id=upload_id,
        workspace_id=workspace_id,
        filename=filename,
        tz=tz,
        columns=columns_list,
        rows=row_count,
        resolution_s=resolution,
        # The returned object reports what was STORED, normalised the way a later `get` will return
        # it (`_parse_ts`): a non-UTC-offset argument comes back as UTC here too, so a caller cannot
        # tell the create-path result from the read-path one. That equivalence is worth the two
        # extra conversions — Step 3 hands one of these straight to the dialog.
        first_ts=_to_utc(first_ts),
        last_ts=_to_utc(last_ts),
        uploaded_at=uploaded_at,
    )


def get(workspace_id: str, upload_id: str) -> Upload | None:
    """One upload row, or None if this workspace has no such upload.

    Scoped by workspace as well as by id, so an id leaked or guessed from another workspace reads
    as absent rather than as a row. The route turns None into a 404, which is the right answer for
    both "no such upload" and "not yours" — distinguishing them would confirm the id exists.

    A malformed `upload_id` raises `ValueError` rather than returning None: it cannot have come
    from this app, and a caller passing one has a bug the route should surface as a 400.
    """
    _check_workspace_id(workspace_id)
    _check_upload_id(upload_id)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM uploads WHERE workspace_id = ? AND id = ?",
            (workspace_id, upload_id),
        ).fetchone()
    return None if row is None else _row_to_upload(row)


def list_for(workspace_id: str) -> list[Upload]:
    """Every upload of one workspace, most recently uploaded first.

    Newest first because the upload dialog's list is a history and the file a user just added is
    the one they are looking for. Ties break on `id` so the order is stable rather than whatever
    SQLite returns — two uploads within the same clock resolution is ordinary when a user adds
    several files in a row, and a list that reshuffles between reloads looks like data moving.
    """
    _check_workspace_id(workspace_id)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {_COLUMNS} FROM uploads WHERE workspace_id = ?
                ORDER BY uploaded_at DESC, id ASC""",
            (workspace_id,),
        ).fetchall()
    return [_row_to_upload(r) for r in rows]


def read_text(workspace_id: str, upload_id: str) -> str:
    """The stored CSV text of one upload.

    Raises `FileNotFoundError` when the file is gone while its row survives — the non-atomic
    residue the module comment describes, in the direction `create`'s ordering makes unreachable
    but which a manual deletion under the data dir can still produce. Left to raise rather than
    returning None: a bound slot whose file has vanished is a real failure the load path should
    report (step 3's 502-for-load-failure convention), not an empty series.

    Decoded as UTF-8. A Dutch supplier export with a Latin-1 column name is possible and would
    raise here; if that turns out to matter, the fix is a decode at the ROUTE, where the raw bytes
    are still in hand and a decoding warning can reach the dialog — not a silent fallback here.
    """
    return path_for(workspace_id, upload_id).read_text(encoding="utf-8")


def delete(workspace_id: str, upload_id: str) -> bool:
    """Remove one upload's row and its file. Returns False if this workspace had no such upload.

    The ROW goes first, then the file — the mirror of `create`'s ordering, for the reason in the
    module comment. `missing_ok=True` on the unlink so a row whose file already went (residue from
    an interrupted earlier delete, or a hand-removed file) still deletes cleanly rather than
    leaving the row behind on an error.

    **This does not clear a slot binding that referenced the upload, and neither does anything
    else.** Under decision D-BIND (candidate E, step 5 of the CSV-import brief) a slot's
    `(upload_id, column, unit)` binding lives in the BROWSER, in `localStorage ha.slots.<workspace>`
    beside the HA statistic id — there is no server-side binding store, so there is nothing here or
    in the route to cascade to. A binding still naming a deleted id goes stale in the browser and
    fails at the next fetch, where `get` returns None and `CsvSource` raises `CsvBindingError`; the
    drawer additionally drops entries whose upload is no longer listed. `app/main.py`'s
    `delete_upload` docstring carries the full account and the cost of that trade.

    Stated here because "delete cascades to bindings" is a real requirement of §2.2 and harness
    fixture 22, and the place it is NOT implemented is the place a reader will look first. An
    earlier revision of this paragraph said step 3's route did it, which was written before D-BIND
    was decided and was never true afterwards.
    """
    _check_workspace_id(workspace_id)
    _check_upload_id(upload_id)
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM uploads WHERE workspace_id = ? AND id = ?",
            (workspace_id, upload_id),
        )
        deleted = cur.rowcount > 0
    if not deleted:
        return False
    path_for(workspace_id, upload_id).unlink(missing_ok=True)
    return True


def delete_all_rows(workspace_id: str) -> None:
    """Remove every `uploads` row of one workspace, leaving the files to the caller.

    For `workspaces.delete`, which removes the whole workspace directory — files included — in its
    own `rmtree` step and needs only the rows dealt with here. Split that way rather than deleting
    files too so the two are not removed twice, and so this function composes into
    `workspaces.delete`'s existing three-step order (rows, data, directory) without adding a
    fourth traversal of the same tree.

    Deliberately NOT called by `workspaces.delete_data`. §2′.3 splits "clear the data" from
    "delete the workspace": clearing data removes the measurements of a run and keeps the
    configuration, and an upload is an input the user supplied once that many runs draw on —
    closer to configuration than to a run. Discarding uploaded files there would force a
    re-upload after an operation the dialog describes as leaving the setup intact.
    """
    _check_workspace_id(workspace_id)
    with _connect() as conn:
        conn.execute("DELETE FROM uploads WHERE workspace_id = ?", (workspace_id,))
