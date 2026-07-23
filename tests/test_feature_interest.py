"""Unit tests for the feature-interest back end (specs/08-architecture.md §5.1).

These are pure-Python, no browser: they assert the counter's upsert invariant, the config's
first-run installation_id generation, and the reporter's egress posture (off unless a URL is
set; body is exactly three fields). Each test points the data dir at a pytest tmp_path via
the BATTERY_SIM_DATA_DIR env var so nothing touches the repo's ./data.

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
