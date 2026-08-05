"""SQLite plumbing: source generation and the workspace index (§5.1).

This module owns the small tables and the connection/data-dir resolution the rest of the
persistence layer reuses (app/dataset.py opens its own schema on the same connection), using
the standard-library `sqlite3` — no SQLAlchemy yet, that arrives with the full schema. The file
lives in the resolved data directory (app/config.py).

Two tables live here:

    workspace_state(workspace_id, source_generation)        PRIMARY KEY (workspace_id)
    workspaces(id, owner_id, title, created_at, updated_at) PRIMARY KEY (id)

## The retired `feature_interest` table, and why the FILE is still named after it

A third table, `feature_interest(feature_key, count, last_clicked_at)`, counted thumbs-up clicks
on pending controls. It was the one deliberate exception to §5.5 invariant 1 (every row carries a
`workspace_id`), because a feature request is a fact about the household rather than about any
one analysis. The whole mechanism is gone: the pending dialog now links to a pre-filled GitHub
issue form (app/features.py) and nothing about a request is stored or transmitted. So the
exception is gone with it — every table here is workspace-keyed again — and `_drop_feature_interest`
removes the table from installations that still have it.

The database FILE is still `feature_interest.db`. Renaming it would strand the workspace index of
every existing installation, which is a real cost against a cosmetic gain; the name is now simply
historical, and this paragraph is why. Nothing about feature interest remains inside it.

`workspace_state.source_generation` was never affected and stays per-workspace: it tracks one
workspace's fetches and sharing it would make one analysis's fetch invalidate another's saved
source customization.

This module also holds the **source generation** counter used by the slot-first source picker
(specs §2.2). It is a per-workspace integer, bumped once each time a Home Assistant fetch
persists a new dataset (main.py's ingest `done`). The browser tags each locally-saved source
customization with the generation it saw; on reload it keeps its local choice only while the
server generation is unchanged, and yields to the server once a fetch (possibly on another
client in the same workspace) has advanced it. A backend_load Confirm (energy-charts) does NOT
bump it — otherwise it would discard a just-saved HA customization on the reload it triggers.

## Transaction semantics of the shared connection

The connection is opened in **autocommit** mode (`isolation_level=None`) because the migration
above needs to control its own `BEGIN IMMEDIATE`, and sqlite3's implicit transaction handling —
which opens a transaction before the first DML statement and commits it at points the caller does
not choose — is what made that migration non-atomic in the first place. A statement run outside a
`with` block therefore commits on its own.

Autocommit alone would leave every `with conn:` block looking like a transaction while being none,
so **the transaction is managed explicitly** by the `_Connection` subclass this module installs as
sqlite3's `factory`: entering a `with` block issues `BEGIN IMMEDIATE`, leaving it issues `COMMIT`,
or `ROLLBACK` if an exception is escaping. That is what makes a multi-statement write
all-or-nothing — `dataset.upsert_series` replaces a series by DELETE-then-INSERT, and without the
rollback an exception between the two destroys a series the user already had. Blocks nest safely
(only the outermost begins and ends the transaction), which `workspaces.delete` → `delete_data`
relies on. The details and the trade-offs are in `_Connection`.

Main items:
    WORKSPACE_ID              the id of the migrated single workspace ("local").
    connect()                 an open connection with the schema and migrations applied.
    _Connection               the subclass making `with conn:` an explicit, nesting transaction.
    source_generation(ws)     read the workspace's current source generation (0 if never fetched).
    bump_source_generation(ws)  increment it (called only on a persisted HA fetch); returns the new value.
"""

import sqlite3
from pathlib import Path

from app import config

# The id of the workspace an existing single-workspace installation migrates to
# (app/workspaces.migrate_local). Named explicitly by migrate_local and by test fixtures; the
# workspace-parameterised calls in the persistence layer no longer default to it (owner-scoping
# changelog phase 3) — every caller must pass a workspace_id.
WORKSPACE_ID = "local"

_DB_FILENAME = "feature_interest.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_state (
    workspace_id      TEXT    NOT NULL PRIMARY KEY,
    source_generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT NOT NULL PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _db_path() -> Path:
    return config.data_dir() / _DB_FILENAME


_TIMEOUT_S = 10.0
"""How long a statement waits for another writer's lock before raising "database is locked".

The migration takes a write lock up front (`BEGIN IMMEDIATE`), and a second process or thread
opening the DB in the same instant must WAIT for it rather than fail — two uvicorn workers, or a
request arriving while the lifespan migration runs, is an ordinary situation, not an error. The
default is 5 s; 10 s is generous for a reshape of a table that holds a handful of rows.
"""


class _Connection(sqlite3.Connection):
    """A connection whose `with` block is an explicit, non-nesting transaction.

    Two requirements meet here, and neither is satisfied by a stock connection.

    The migration needs **autocommit** (`isolation_level=None`). Left at sqlite3's default, the
    module opens an implicit transaction before the first DML statement and commits it at points
    the caller does not choose — which is what made `_migrate_feature_interest` non-atomic — so
    the migration can only take the write lock when it wants it if sqlite3 is doing no
    transaction management of its own.

    Callers need `with conn:` to be **all-or-nothing**. Under sqlite3's default that came for
    free: the implicit transaction committed on a clean exit and rolled back when an exception
    escaped the block. Autocommit removes the rollback and leaves the `with` blocks looking
    unchanged, which is exactly how `dataset.upsert_series` — a DELETE of a series followed by
    the INSERT of its replacement — came to be able to destroy a series the user already had when
    an exception landed between the two.

    So the transaction is managed here explicitly instead. `__enter__` issues `BEGIN IMMEDIATE`,
    `__exit__` issues `COMMIT`, or `ROLLBACK` when the block is leaving via an exception. Nothing
    is swallowed: `__exit__` returns False, so the exception continues to propagate after the
    rollback.

    `BEGIN IMMEDIATE` rather than a plain (deferred) `BEGIN`: it takes the write lock up front, so
    a concurrent writer waits out `_TIMEOUT_S` instead of getting partway into its block and
    failing with "database is locked" on the first write. The cost is that even a read-only block
    takes the write lock for its duration, which for a local single-user app is acceptable but is
    a real change rather than a free one.

    **Nesting is handled, not avoided.** SQLite raises on a nested `BEGIN`, and nested blocks do
    occur — `workspaces.delete` calls `delete_data`. `_depth` counts them per connection so only
    the outermost block begins and ends the transaction; an inner one joins it and is a no-op on
    exit. An inner block that exits via an exception therefore does NOT roll back on its own — the
    exception has to reach the outermost block for that, which it does whenever it is not caught
    in between, and a caller that catches it has chosen to keep the partial work either way. The
    `in_transaction` guard covers the other direction: a block entered while a transaction is
    already open (the migration's explicit `BEGIN`) does not try to begin a second one.
    """

    def __enter__(self) -> "_Connection":
        depth = getattr(self, "_depth", 0)
        # Begin only for the outermost block, and only if nothing else already has a transaction
        # open on this connection (the migration's explicit BEGIN). `_owned_depth` records which
        # nesting level opened it, so the matching __exit__ — and only that one — closes it. A
        # single `_owns` flag would NOT do: the inner __enter__ overwrites it, and the outer
        # __exit__ then reads the inner block's value and skips its own COMMIT.
        if depth == 0 and not self.in_transaction:
            self.execute("BEGIN IMMEDIATE")
            self._owned_depth = 0
        self._depth = depth + 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._depth = depth = getattr(self, "_depth", 1) - 1
        if depth == getattr(self, "_owned_depth", None) and self.in_transaction:
            self.execute("ROLLBACK" if exc_type is not None else "COMMIT")
            self._owned_depth = None
        return False  # never swallow: the exception keeps propagating past the rollback


def _connect() -> sqlite3.Connection:
    # isolation_level=None disables sqlite3's implicit transaction handling: it otherwise opens a
    # transaction before the first DML statement and commits it at unpredictable points (including
    # before any DDL on older Pythons), which is precisely what made the migration non-atomic. With
    # it off, SQLite autocommits each statement outside a transaction, and a transaction exists
    # only where one is opened explicitly — by `_Connection`'s `with` block. `factory=_Connection`
    # is what keeps `with conn:` an all-or-nothing unit under autocommit; see that class for why
    # both properties are needed at once.
    conn = sqlite3.connect(
        _db_path(), timeout=_TIMEOUT_S, isolation_level=None, factory=_Connection
    )
    # executescript (not execute): _SCHEMA holds more than one CREATE TABLE, and execute() runs a
    # single statement only. All are `IF NOT EXISTS`, so this stays idempotent per connect.
    conn.executescript(_SCHEMA)
    _drop_feature_interest(conn)
    return conn


def connect() -> sqlite3.Connection:
    """An open connection with the schema created and migrations applied.

    The public spelling of `_connect`, for the modules that layer their own tables on the same
    file (app/dataset.py, app/workspaces.py). Used as a context manager it is a **transaction**:
    the block commits on a clean exit and rolls back if an exception escapes it, so a
    multi-statement write is all-or-nothing. That is `_Connection`'s doing rather than sqlite3's —
    the connection is in autocommit mode for the migration's sake, and a statement run outside a
    `with` block commits on its own. Blocks nest safely (see `_Connection`). Closing is left to
    refcounting as elsewhere in this package.
    """
    return _connect()


def _drop_feature_interest(conn: sqlite3.Connection) -> None:
    """Drop the retired `feature_interest` table if an older installation still carries it.

    Feature requests are filed as GitHub issues now (app/features.py) and nothing is recorded
    locally, so the table has no reader and no writer. Dropping it rather than leaving it in
    place keeps the file honest about what the app stores — a table nothing writes is a claim
    about behaviour that is no longer true, and this database is the thing a privacy-minded user
    would open to check.

    The rows are counts of which pending controls this household clicked. They were never shown
    to the user and never left the machine unless an endpoint was configured, so nothing readable
    is lost; the drop is still irreversible, which is the argument for doing it once, here, rather
    than leaving it to accumulate.

    Runs on every connect. `IF EXISTS` makes the repeat a no-op, and DDL under the autocommit
    connection is its own transaction, so a concurrent connect either sees the table or does not.
    """
    conn.execute("DROP TABLE IF EXISTS feature_interest")
    # A crash during the pre-GitHub re-key migration could have committed this scratch table.
    conn.execute("DROP TABLE IF EXISTS feature_interest_new")


def source_generation(workspace_id: str) -> int:
    """The workspace's current source generation, or 0 if it has never been fetched (specs §2.2).

    Rendered into the page so the browser can compare it against the generation its locally-saved
    source customizations were tagged with.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT source_generation FROM workspace_state WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
    return row[0] if row else 0


def bump_source_generation(workspace_id: str) -> int:
    """Increment and return the workspace's source generation (specs §2.2).

    Called once per persisted Home Assistant fetch (main.py ingest `done`). A first bump inserts
    generation 1. This is the ONLY writer — a backend_load Confirm must not call it, or it would
    invalidate an HA customization the user saved just before the reload that Confirm triggers.
    The upsert is atomic on the (workspace_id) primary key.
    """
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO workspace_state (workspace_id, source_generation)
            VALUES (?, 1)
            ON CONFLICT (workspace_id)
            DO UPDATE SET source_generation = source_generation + 1
            """,
            (workspace_id,),
        )
        row = conn.execute(
            "SELECT source_generation FROM workspace_state WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
    return row[0]
