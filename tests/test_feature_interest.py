"""Unit tests for the feature-interest back end (specs/08-architecture.md §5.1).

These are pure-Python, no browser: they assert the counter's upsert invariant, the config's
first-run installation_id generation, and the reporter's egress posture (off unless a URL is
set; body is exactly three fields). Each test points the data dir at a pytest tmp_path via
the BATTERY_SIM_DATA_DIR env var so nothing touches the repo's ./data.

Three tests cover the §2′.10 re-key migration specifically: that old per-workspace rows collapse
by key, that a leftover scratch table from an INTERRUPTED migration is resumed rather than
bricking every subsequent connect, and that several threads opening an old-shape database at once
all succeed and migrate it exactly once.

    uv run pytest tests/test_feature_interest.py
"""

import asyncio
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


@pytest.fixture()
def app_modules(tmp_path, monkeypatch):
    """Reload config/db against a fresh temp data dir so state does not leak between tests."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BATTERY_SIM_FEATURE_INTEREST_URL", raising=False)
    monkeypatch.delenv("BATTERY_SIM_INSTALLATION_ID", raising=False)
    from app import config, db, interest

    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(interest)
    return config, db, interest


def test_upsert_counts_once(app_modules):
    _, db, _ = app_modules
    assert db.record_interest("export_csv") is True   # first click
    assert db.record_interest("export_csv") is False  # repeat click
    assert db.record_interest("export_csv") is False
    assert db.interest_count("export_csv") == 1        # never bumped past 1


def test_distinct_keys_independent(app_modules):
    _, db, _ = app_modules
    db.record_interest("export_csv")
    assert db.interest_count("export_csv") == 1
    assert db.interest_count("simulate_cost") == 0     # untouched key stays 0


def test_old_shape_rows_collapse_by_key(app_modules):
    """An existing per-workspace table is re-keyed on `feature_key` alone.

    specs/20-workspaces-ux.md §2′.10: the merge is a UNION, not a sum — interest is boolean per
    household, so two workspaces having thumbed the same key is still one wish — and it keeps the
    EARLIEST `last_clicked_at`, which is when the household first asked.
    """
    import sqlite3

    _, db, _ = app_modules

    # Build the pre-migration shape directly, as a user's data dir would already hold it.
    path = db._db_path()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE feature_interest (
            workspace_id     TEXT    NOT NULL,
            feature_key      TEXT    NOT NULL,
            count            INTEGER NOT NULL DEFAULT 0,
            last_clicked_at  TEXT    NOT NULL,
            PRIMARY KEY (workspace_id, feature_key)
        );
        INSERT INTO feature_interest VALUES
            ('local', 'export_csv',    1, '2026-01-02T00:00:00+00:00'),
            ('other', 'export_csv',    1, '2026-01-01T00:00:00+00:00'),
            ('other', 'simulate_cost', 1, '2026-03-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    with db.connect() as migrated:
        rows = migrated.execute(
            "SELECT feature_key, count, last_clicked_at FROM feature_interest ORDER BY feature_key"
        ).fetchall()
        columns = {
            r[1] for r in migrated.execute("PRAGMA table_info(feature_interest)").fetchall()
        }

    assert "workspace_id" not in columns
    assert rows == [
        ("export_csv", 1, "2026-01-01T00:00:00+00:00"),     # earliest of the two, not the sum
        ("simulate_cost", 1, "2026-03-01T00:00:00+00:00"),
    ]

    # And the migration is idempotent: a second connect leaves the collapsed rows alone.
    assert db.interest_count("export_csv") == 1
    assert db.record_interest("export_csv") is False        # already known, so not a first click


_OLD_SHAPE = """
CREATE TABLE feature_interest (
    workspace_id     TEXT    NOT NULL,
    feature_key      TEXT    NOT NULL,
    count            INTEGER NOT NULL DEFAULT 0,
    last_clicked_at  TEXT    NOT NULL,
    PRIMARY KEY (workspace_id, feature_key)
);
INSERT INTO feature_interest VALUES
    ('local', 'export_csv', 1, '2026-01-02T00:00:00+00:00'),
    ('other', 'export_csv', 1, '2026-01-01T00:00:00+00:00');
"""


def test_migration_resumes_after_a_leftover_scratch_table(app_modules):
    """An interrupted migration must not brick the installation.

    The reshape builds `feature_interest_new` and renames it into place. If the process dies
    between the two, the scratch table is left behind. Before the migration became one explicit
    transaction, the next `_connect()` then raised `table feature_interest_new already exists` on
    the CREATE — and `_connect` is the entry point for every persistence call, so the whole app
    was dead with no self-repair path. The scratch table is now dropped before it is created.
    """
    import sqlite3

    _, db, _ = app_modules

    conn = sqlite3.connect(db._db_path())
    conn.executescript(_OLD_SHAPE)
    # The committed artifact of a migration that stopped after its CREATE.
    conn.execute(
        """CREATE TABLE feature_interest_new (
               feature_key TEXT PRIMARY KEY,
               count INTEGER NOT NULL DEFAULT 0,
               last_clicked_at TEXT NOT NULL)"""
    )
    conn.commit()
    conn.close()

    with db.connect() as resumed:
        rows = resumed.execute(
            "SELECT feature_key, count, last_clicked_at FROM feature_interest"
        ).fetchall()
        columns = {r[1] for r in resumed.execute("PRAGMA table_info(feature_interest)").fetchall()}
        leftover = resumed.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'feature_interest_new'"
        ).fetchone()[0]

    assert "workspace_id" not in columns
    assert rows == [("export_csv", 1, "2026-01-01T00:00:00+00:00")]
    assert leftover == 0  # the scratch table is gone, not merely tolerated


def test_concurrent_connects_migrate_exactly_once(app_modules):
    """Several openers racing on an old-shape DB must all succeed and collapse the rows once.

    Two uvicorn workers, or a request arriving while the lifespan migration runs, produce exactly
    this. Measured before the fix: 4 of 12 runs of a six-thread version failed, mostly on
    `table feature_interest_new already exists`, once on the rename colliding with an
    already-renamed table.

    Deterministic enough not to flake: a `threading.Barrier` releases every thread at the same
    moment (rather than hoping the OS interleaves them), and the connection timeout in `app/db.py`
    makes a thread that loses the write lock WAIT rather than fail. The assertion is on the
    outcome — no errors, one collapsed row — not on which thread did the work.
    """
    import sqlite3

    _, db, _ = app_modules

    conn = sqlite3.connect(db._db_path())
    conn.executescript(_OLD_SHAPE)
    conn.commit()
    conn.close()

    n_threads = 8
    errors: list[str] = []
    barrier = threading.Barrier(n_threads)

    def opener():
        barrier.wait(timeout=30)
        try:
            with db.connect() as c:
                c.execute("SELECT 1 FROM feature_interest").fetchone()
        except Exception as exc:  # recorded, not raised: a thread's traceback would be swallowed
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=opener) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert errors == []
    assert not any(t.is_alive() for t in threads)
    with db.connect() as final:
        rows = final.execute(
            "SELECT feature_key, count, last_clicked_at FROM feature_interest"
        ).fetchall()
    # Collapsed exactly once — not duplicated by a second migration, not summed to 2.
    assert rows == [("export_csv", 1, "2026-01-01T00:00:00+00:00")]


def test_installation_id_generated_and_persisted(app_modules, tmp_path):
    config, _, _ = app_modules
    cfg = config.load()
    assert cfg.feature_interest_url == ""              # empty by default
    assert len(cfg.installation_id) >= 16
    # Persisted to config.toml and stable across a reload.
    assert (tmp_path / "config.toml").exists()
    importlib.reload(config)
    assert config.load().installation_id == cfg.installation_id


def test_reporter_noop_without_url(app_modules):
    config, _, interest = app_modules
    cfg = config.Config(feature_interest_url="", installation_id="x")
    # Must complete without attempting any network I/O.
    asyncio.run(interest.report("export_csv", cfg))


def test_reporter_posts_three_field_body(app_modules):
    config, _, interest = app_modules
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(n)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = config.Config(
            feature_interest_url=f"http://127.0.0.1:{srv.server_address[1]}/",
            installation_id="testid",
            app_version="9.9.9",
        )
        asyncio.run(interest.report("export_csv", cfg))
    finally:
        srv.shutdown()

    assert received == [
        {"feature_key": "export_csv", "app_version": "9.9.9", "installation_id": "testid"}
    ]


def test_reporter_swallows_failure(app_modules):
    config, _, interest = app_modules
    # An unreachable endpoint must not raise — failures are invisible (§5.1 invariant 1).
    cfg = config.Config(
        feature_interest_url="http://127.0.0.1:1/",  # nothing listens here
        installation_id="x",
        app_version="0",
    )
    asyncio.run(interest.report("export_csv", cfg))
