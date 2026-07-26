"""SQLite plumbing: feature-interest counts, source generation, the workspace index (§5.1).

This module owns the small tables and the connection/data-dir resolution the rest of the
persistence layer reuses (app/dataset.py opens its own schema on the same connection), using
the standard-library `sqlite3` — no SQLAlchemy yet, that arrives with the full schema. The file
lives in the resolved data directory (app/config.py).

Three tables live here:

    feature_interest(feature_key, count, last_clicked_at)   PRIMARY KEY (feature_key)
    workspace_state(workspace_id, source_generation)        PRIMARY KEY (workspace_id)
    workspaces(id, owner_id, title, created_at, updated_at) PRIMARY KEY (id)

Invariants from §5.1, asserted by this module in place of a fixture:
  * The interest write is an **upsert, not an append**: a repeat click for the same key updates
    `last_clicked_at` and leaves `count` alone. Interest is a boolean fact about a household;
    the count is only meaningful summed across installations, so a single install never exceeds
    1. This is also what makes a second thumbs-up not count twice (§2.1).

## `feature_interest` is installation-wide — the one exception to §5.5 invariant 1

Invariant 1 says every persisted row carries `workspace_id` and no table is implicitly global.
`feature_interest` is a **deliberate exception**, recorded as such in §5.5 and argued in
specs/20-workspaces-ux.md §2′.10: the row records that *this household* wants a feature, which
is a fact about the person using the app rather than about any one analysis. Keying it per
workspace made the counter answer the wrong question — the same person could register the same
wish three times from three analyses, and deleting a workspace would retract a signal the user
never withdrew. The invariant's purpose is that user *data* never leaks between workspaces or,
later, between accounts; these counters are outbound product telemetry, already reported under
the pseudonymous `installation_id` from config.toml rather than under any workspace identity.

`workspace_state.source_generation` is NOT affected and stays per-workspace: it tracks one
workspace's fetches and sharing it would make one analysis's fetch invalidate another's saved
source customization.

## Migrating an existing database

`CREATE TABLE IF NOT EXISTS` never alters an existing table, and SQLite has no
`ALTER TABLE … DROP CONSTRAINT`, so the re-key is an explicit migration
(`_migrate_feature_interest`): detect the old shape via `PRAGMA table_info`, build the new
table, `INSERT … SELECT … GROUP BY feature_key`, drop, rename. The collapse takes `MIN` of
`last_clicked_at` and a count of 1 — a union, not a sum, because interest is boolean per
household and two workspaces thumbing the same key is still one household wanting one thing.
`MIN` over a TEXT column is a string comparison, which is the earliest INSTANT only because
`record_interest` writes `datetime.now(timezone.utc).isoformat()` — fixed width, always the
`+00:00` offset. That holds for every row this app has ever written; it is an assumption about
the stored format, not a general property of the query.

The migration runs on every `_connect()`, so any code path that opens the DB repairs a stale
shape — at the cost of one `PRAGMA table_info` on every connection, permanently, which is what
makes the repeat a no-op. It is wrapped in an explicit `BEGIN IMMEDIATE` and re-checks the shape
inside that transaction, so it is atomic, safe to run from several processes or threads at once,
and resumable after a crash: an interrupted run leaves at most a scratch table, which the next
run drops before recreating.

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
    record_interest(key)      upsert a click; returns True if this was the first click for the key.
    interest_count(key)       read a key's count (used by tests; never shown to the user, §2.1).
    source_generation(...)    read the workspace's current source generation (0 if never fetched).
    bump_source_generation()  increment it (called only on a persisted HA fetch); returns the new value.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import config

# The id of the workspace an existing single-workspace installation migrates to
# (app/workspaces.migrate_local). Still the default of every workspace-parameterised call in the
# persistence layer; phase 1 of the workspaces restructure gives those parameters real values.
WORKSPACE_ID = "local"

_DB_FILENAME = "feature_interest.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_interest (
    feature_key      TEXT    NOT NULL PRIMARY KEY,
    count            INTEGER NOT NULL DEFAULT 0,
    last_clicked_at  TEXT    NOT NULL
);
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
    # only where one is opened explicitly — by `_migrate_feature_interest`, or by `_Connection`'s
    # `with` block. `factory=_Connection` is what keeps `with conn:` an all-or-nothing unit under
    # autocommit; see that class for why both properties are needed at once.
    conn = sqlite3.connect(
        _db_path(), timeout=_TIMEOUT_S, isolation_level=None, factory=_Connection
    )
    # executescript (not execute): _SCHEMA holds more than one CREATE TABLE, and execute() runs a
    # single statement only. All are `IF NOT EXISTS`, so this stays idempotent per connect.
    #
    # Order matters: the feature_interest migration runs FIRST, because the CREATE above is a
    # no-op against an existing old-shape table and would otherwise leave the stale key in place
    # for the rest of this connection's statements.
    _migrate_feature_interest(conn)
    conn.executescript(_SCHEMA)
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


def _migrate_feature_interest(conn: sqlite3.Connection) -> None:
    """Re-key an old-shape `feature_interest` on `feature_key` alone (module comment).

    Idempotent and cheap: a table that is absent, or already in the new shape, is left alone
    after one `PRAGMA table_info`. The collapse is a UNION — one row per key, `MIN` of
    `last_clicked_at`, count clamped to 1 — because interest is boolean per household and the
    same person thumbing a key from two analyses has not wished for it twice (§2′.10). `MIN` is a
    string comparison and equals the earliest instant because of how `record_interest` writes the
    column (module comment).

    **Atomic, concurrent-safe and resumable.** Every statement runs inside one
    `BEGIN IMMEDIATE`, which takes the write lock before doing any work, so a second opener blocks
    (up to `_TIMEOUT_S`) instead of racing. Either the whole reshape lands or none of it does —
    the earlier `executescript` spelling committed statement by statement, so a crash between the
    CREATE and the RENAME left the scratch table behind as a committed artifact and every
    subsequent connect then failed with "table feature_interest_new already exists". Two things
    make that unreachable now: the scratch table is DROPped before it is created, so a leftover
    from an interrupted older run is reclaimed rather than fatal; and the shape is re-checked
    INSIDE the transaction, so the loser of a race sees the already-migrated table and does
    nothing rather than trying to rename over it.
    """
    if not _has_old_shape(conn):
        return  # fast path: absent (fresh DB) or already re-keyed, no lock taken
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Re-checked under the write lock: another process may have migrated between the fast-path
        # check above and the moment we got the lock.
        if not _has_old_shape(conn):
            conn.execute("ROLLBACK")
            return
        conn.execute("DROP TABLE IF EXISTS feature_interest_new")
        conn.execute(
            """CREATE TABLE feature_interest_new (
                   feature_key      TEXT    NOT NULL PRIMARY KEY,
                   count            INTEGER NOT NULL DEFAULT 0,
                   last_clicked_at  TEXT    NOT NULL
               )"""
        )
        conn.execute(
            """INSERT INTO feature_interest_new (feature_key, count, last_clicked_at)
                   SELECT feature_key, 1, MIN(last_clicked_at)
                   FROM feature_interest
                   GROUP BY feature_key"""
        )
        conn.execute("DROP TABLE feature_interest")
        conn.execute("ALTER TABLE feature_interest_new RENAME TO feature_interest")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _has_old_shape(conn: sqlite3.Connection) -> bool:
    """Whether `feature_interest` still carries the pre-§2′.10 `workspace_id` column.

    False for a fresh database (no such table — `PRAGMA table_info` returns no rows) as well as
    for an already-migrated one, which is why the caller can treat both the same way.
    """
    columns = {r[1] for r in conn.execute("PRAGMA table_info(feature_interest)").fetchall()}
    return "workspace_id" in columns


def record_interest(feature_key: str) -> bool:
    """Upsert a thumbs-up for `feature_key`. Returns True iff it was the first click.

    First click inserts count 1. A repeat click refreshes `last_clicked_at` only — count is not
    bumped (interest is boolean per household, §5.1 invariant 2). The `feature_key` primary key
    makes this a single atomic upsert.

    Installation-wide: there is no workspace argument, deliberately (module comment, §2′.10).

    The existence check and the upsert run in ONE transaction: the `with` block takes the write
    lock up front (`_Connection`), so a concurrent `record_interest` for the same key waits rather
    than interleaving between the two statements, and the returned boolean reflects the state the
    upsert actually acted on. An earlier revision of this docstring called the boolean advisory,
    which was true of the window in which connections autocommitted every statement and is not
    true now; the code and this comment are meant to agree, and they do.

    The stored row would be correct either way — the upsert is atomic on the primary key — and the
    one caller uses the boolean only to decide whether to report the click outbound, where a
    duplicate is deduplicated by the key anyway. So this is a tightening, not a fix for an
    observed bug.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        # Check existence first so we can report first-vs-repeat; the upsert itself cannot tell
        # them apart via rowcount.
        existed = conn.execute(
            "SELECT 1 FROM feature_interest WHERE feature_key = ?",
            (feature_key,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO feature_interest (feature_key, count, last_clicked_at)
            VALUES (?, 1, ?)
            ON CONFLICT (feature_key)
            DO UPDATE SET last_clicked_at = excluded.last_clicked_at
            """,
            (feature_key, now),
        )
    return existed is None


def interest_count(feature_key: str) -> int:
    """The recorded count for a key (0 if none). For tests only — never shown to users (§2.1)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT count FROM feature_interest WHERE feature_key = ?",
            (feature_key,),
        ).fetchone()
    return row[0] if row else 0


def source_generation(workspace_id: str = WORKSPACE_ID) -> int:
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


def bump_source_generation(workspace_id: str = WORKSPACE_ID) -> int:
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
