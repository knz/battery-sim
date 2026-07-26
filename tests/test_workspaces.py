"""Unit tests for phase 0 of the workspaces restructure (specs/20-workspaces-ux.md §2′.2, §2′.10).

Covered here:

  * `migrate_local` — that it adopts an existing `local` config or dataset, that it does NOT
    invent a workspace on a fresh installation, that a second run is a no-op, and that it sets
    `pricing.configured` from `simulate_cost` (§2′.6's don't-regress-an-existing-user rule)
    without ever CLEARING an already-set flag, and without rewriting a config document this build
    cannot read.
  * `list_summaries` — the card in its three interesting states: with data, without data, and
    with `has_pv` off (where PV reads *not applicable* rather than *not loaded*, §2′.2).
  * The two new config fields round-tripping through save/load, and defaulting when a stored
    document predates them.

Each test points the data dir at a pytest tmp_path via BATTERY_SIM_DATA_DIR so nothing touches
the repo's ./data. The app modules read `config.data_dir()` per call, so setting the env var is
enough — no module reload is needed for these (unlike test_feature_interest.py, which reloads
`config` to exercise its first-run installation_id write).

    uv run pytest tests/test_workspaces.py
"""

from datetime import datetime, timezone

import numpy as np
import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    """The persistence modules bound to a throwaway data dir."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import dataset, db, simconfig_store, workspaces

    return dataset, db, simconfig_store, workspaces


def _frame(name, kind, resolution_s, n=48):
    from app.domain.frames import QUALITY_DTYPE, SeriesFrame

    start = np.datetime64("2025-06-01T00:00:00", "s")
    index = start + np.arange(n, dtype="int64") * np.timedelta64(resolution_s, "s")
    return SeriesFrame(
        name=name,
        kind=kind,
        resolution_s=resolution_s,
        index=index,
        values=np.ones(n, dtype=float),
        quality=np.zeros(n, dtype=QUALITY_DTYPE),
    )


def _save_dataset(dataset, names=("grid_import_t1", "grid_export_t1", "solar_production")):
    """Persist a 48-hour dataset holding `names`, all hourly energy series."""
    frames = [_frame(n, "energy", 3600) for n in names]
    window = (
        datetime(2025, 6, 1, tzinfo=timezone.utc),
        datetime(2025, 6, 3, tzinfo=timezone.utc),
    )
    return dataset.save_dataset(frames, window, "home_assistant", [])


# ── Migration ────────────────────────────────────────────────────────────────────────────────


def test_migration_skips_a_fresh_installation(mods):
    """No config and no dataset on disk → no phantom workspace (§2′.10)."""
    _, _, _, workspaces = mods
    assert workspaces.migrate_local() is False
    assert workspaces.list_summaries() == []


def test_migration_adopts_an_existing_config(mods):
    _, db, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig())

    assert workspaces.migrate_local() is True
    row = workspaces.get(db.WORKSPACE_ID)
    assert row is not None
    assert row["title"] == workspaces.DEFAULT_TITLE
    assert row["owner_id"] == workspaces.OWNER_ID


def test_migration_adopts_a_workspace_that_only_has_data(mods):
    """A dataset with no config document is still a workspace the user must not lose."""
    dataset, db, _, workspaces = mods
    _save_dataset(dataset)

    assert workspaces.migrate_local() is True
    assert workspaces.get(db.WORKSPACE_ID) is not None


def test_migration_is_idempotent(mods):
    """Running it twice inserts nothing the second time and changes no stored value."""
    _, db, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(simulate_cost=True))

    assert workspaces.migrate_local() is True
    first = workspaces.get(db.WORKSPACE_ID)

    assert workspaces.migrate_local() is False
    assert workspaces.get(db.WORKSPACE_ID) == first
    assert len(workspaces.list_summaries()) == 1
    assert simconfig_store.is_pricing_configured() is True


def test_migration_sets_pricing_configured_from_simulate_cost(mods):
    """§2′.6: an existing cost-simulating user must not be blocked after the upgrade."""
    _, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(simulate_cost=True))
    assert simconfig_store.is_pricing_configured() is False  # not set before migration

    workspaces.migrate_local()
    assert simconfig_store.is_pricing_configured() is True


def test_migration_leaves_the_flag_false_without_cost_simulation(mods):
    _, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(simulate_cost=False))
    workspaces.migrate_local()
    assert simconfig_store.is_pricing_configured() is False


def test_migration_never_clears_a_set_pricing_configured(mods):
    """§2′.6's "never cleared automatically", which the migration itself must honour.

    A user who configured pricing but has cost simulation OFF must keep the flag. The migration
    used to pass `pricing_configured=bool(cfg.simulate_cost)`, and an explicit False overrides the
    store's carry-forward, so it cleared exactly the flag this phase exists to protect. Reachable
    the moment the empty-`workspaces` guard is met on a database that has the flag — e.g. a user
    deletes their last workspace and restarts.
    """
    _, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(simulate_cost=False), pricing_configured=True)
    assert simconfig_store.is_pricing_configured() is True

    assert workspaces.migrate_local() is True
    assert simconfig_store.is_pricing_configured() is True


def test_migration_does_not_overwrite_a_future_version_document(mods):
    """A document this build cannot read is adopted untouched, never rewritten with defaults.

    `simconfig_store.load()` answers appendix-A defaults for a version other than 1 — deliberately,
    so a future build's file is not misread as this one's. The migration used to save those
    defaults straight back, downgrading the document and discarding the user's parameters.
    """
    import json

    _, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    path = simconfig_store.config_path()
    doc = simconfig_store.to_dict(SimulationConfig())
    doc["version"] = 2
    doc["battery"]["usable_capacity_kwh"] = 42.0
    path.write_text(json.dumps(doc), encoding="utf-8")

    # The workspace is still adopted — the document exists, so there is something to adopt.
    assert workspaces.migrate_local() is True
    assert len(workspaces.list_summaries()) == 1

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["version"] == 2
    assert on_disk["battery"]["usable_capacity_kwh"] == 42.0


def test_migration_does_not_run_once_a_workspace_exists(mods):
    """A user who already has real workspaces gets no `local` adopted under them."""
    _, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig())  # a `local` document exists on disk
    workspaces.create("Something else")

    assert workspaces.migrate_local() is False
    assert [s.title for s in workspaces.list_summaries()] == ["Something else"]


# ── list_summaries ───────────────────────────────────────────────────────────────────────────


def test_summary_with_data(mods):
    dataset, db, simconfig_store, workspaces = mods
    from app.domain.simconfig import GridConfig, SimulationConfig

    simconfig_store.save(SimulationConfig(has_pv=True, grid=GridConfig(phases=3, fuse_a=25)))
    _save_dataset(dataset)
    workspaces.migrate_local()

    (card,) = workspaces.list_summaries()
    assert (card.phases, card.fuse_a) == (3, 25)
    assert card.contract == "dynamic"  # the enum VALUE verbatim (§2.3)
    assert card.data.loaded is True
    assert card.data.grid_consumption is True
    assert card.data.grid_production is True
    assert card.data.pv_production is True
    assert card.data.pv_applicable is True
    assert card.data.window == (
        datetime(2025, 6, 1, tzinfo=timezone.utc),
        datetime(2025, 6, 3, tzinfo=timezone.utc),
    )
    assert card.data.resolution_s == 3600
    assert card.data.intervals == 48  # derived from window / resolution — see the module comment


def test_summary_without_data(mods):
    """The no-data card: `loaded` false, and nothing pretending to be a coverage window."""
    _, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig())
    workspaces.migrate_local()

    (card,) = workspaces.list_summaries()
    assert card.data.loaded is False
    assert card.data.window is None
    assert card.data.intervals is None
    assert card.data.grid_consumption is False


def test_summary_without_pv_reports_not_applicable(mods):
    """§2′.2: with `has_pv` off, PV is *not applicable*, which is not the same as not loaded."""
    dataset, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(has_pv=False))
    _save_dataset(dataset, names=("grid_import_t1", "grid_export_t1"))
    workspaces.migrate_local()

    (card,) = workspaces.list_summaries()
    assert card.data.pv_applicable is False
    assert card.data.pv_production is False
    assert card.data.grid_consumption is True


def test_summary_without_pv_ignores_a_stray_solar_series(mods):
    """A solar series present while `has_pv` is off still reads not-applicable, not loaded.

    The configuration is the authority on whether PV is a thing this household has (§8.16:
    asked explicitly, never inferred), so the card must not contradict it from the data side.
    """
    dataset, _, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(has_pv=False))
    _save_dataset(dataset)  # includes solar_production
    workspaces.migrate_local()

    (card,) = workspaces.list_summaries()
    assert card.data.pv_applicable is False
    assert card.data.pv_production is False


def test_summaries_are_ordered_most_recently_updated_first(mods):
    """§2′.2's ordering, and §2′.10's rule that it follows the CONFIG's save time."""
    _, _, _, workspaces = mods

    a = workspaces.create("A")
    b = workspaces.create("B")
    workspaces.touch(a)  # a saved after b was created

    assert [s.id for s in workspaces.list_summaries()] == [a, b]

    workspaces.touch(b)
    assert [s.id for s in workspaces.list_summaries()] == [b, a]


def test_touch_moves_updated_at_and_rename_does_not(mods):
    _, _, _, workspaces = mods

    wid = workspaces.create("Before")
    created = workspaces.get(wid)["updated_at"]

    workspaces.rename(wid, "After")
    row = workspaces.get(wid)
    assert row["title"] == "After"
    assert row["updated_at"] == created  # a rename is not a configuration save (§2′.10)

    workspaces.touch(wid)
    assert workspaces.get(wid)["updated_at"] >= created


# ── Deletion ─────────────────────────────────────────────────────────────────────────────────


def test_delete_data_keeps_the_config_and_the_workspace(mods, tmp_path):
    dataset, db, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(has_pv=False))
    _save_dataset(dataset)
    workspaces.migrate_local()

    workspaces.delete_data(db.WORKSPACE_ID)

    assert dataset.load_latest() is None
    assert simconfig_store.config_path().exists()
    assert workspaces.get(db.WORKSPACE_ID) is not None
    (card,) = workspaces.list_summaries()
    assert card.data.loaded is False
    assert not (tmp_path / db.WORKSPACE_ID / "series").exists()


def test_delete_removes_the_workspace_but_not_feature_interest(mods, tmp_path):
    """§2′.10: interest is installation-wide and survives the deletion of every workspace."""
    dataset, db, simconfig_store, workspaces = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig())
    _save_dataset(dataset)
    workspaces.migrate_local()
    db.record_interest("export_csv")

    workspaces.delete(db.WORKSPACE_ID)

    assert workspaces.get(db.WORKSPACE_ID) is None
    assert workspaces.list_summaries() == []
    assert not (tmp_path / db.WORKSPACE_ID).exists()
    assert db.interest_count("export_csv") == 1


def test_delete_rejects_path_traversal(mods):
    _, _, _, workspaces = mods
    with pytest.raises(ValueError):
        workspaces.delete("../evil")


# ── Transaction semantics of the shared connection (changelog 20260726 finding 9) ─────────────


def test_nested_with_blocks_commit_once_at_the_outermost(mods):
    """A `with` block inside another must not raise on a nested BEGIN, and must commit once.

    `workspaces.delete` calls `delete_data`, which opens its own connection-scoped block, so
    nesting is a real path rather than a hypothetical. SQLite errors on a nested `BEGIN`, so
    `db._Connection` counts depth and lets only the outermost block begin and end the transaction.
    """
    _, db, _, _ = mods
    conn = db.connect()
    with conn:
        conn.execute("INSERT INTO workspaces VALUES ('a', 'local', 'A', 'now', 'now')")
        with conn:  # nested: joins the outer transaction, must not BEGIN again
            conn.execute("INSERT INTO workspaces VALUES ('b', 'local', 'B', 'now', 'now')")
        # Still inside the outer block: nothing is committed yet, but both rows are visible here.
        assert conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 2
    # Closed before reopening: the write lock is held for the life of the block, so a second
    # connection taken while this one is still open would wait out the timeout and fail.
    conn.close()

    check = db.connect()
    assert check.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 2
    check.close()


def test_exception_escaping_a_nested_block_rolls_back_the_whole_outer_transaction(mods):
    """The inner block does not commit independently: an escape past the outer one undoes both."""
    _, db, _, _ = mods
    conn = db.connect()
    with pytest.raises(RuntimeError):
        with conn:
            conn.execute("INSERT INTO workspaces VALUES ('a', 'local', 'A', 'now', 'now')")
            with conn:
                conn.execute("INSERT INTO workspaces VALUES ('b', 'local', 'B', 'now', 'now')")
            raise RuntimeError("escapes the outer block")
    conn.close()

    check = db.connect()
    assert check.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0
    check.close()


def test_delete_leaves_no_rows_when_it_fails_partway(mods):
    """`workspaces.delete` removes rows from two tables; a failure between them must undo both.

    This is the orphan-row shape finding 6 was about, reached by interruption rather than by a
    query that missed rows. The `.npz` files are a separate matter and stay non-atomic by the
    decision recorded in finding 8 — only the rows are covered here.
    """
    dataset, db, _, workspaces = mods
    from app.domain.simconfig import SimulationConfig
    import app.simconfig_store as store

    store.save(SimulationConfig())
    _save_dataset(dataset)
    workspaces.migrate_local()
    db.bump_source_generation(db.WORKSPACE_ID)

    real_rmtree = workspaces.shutil.rmtree
    calls = {"n": 0}

    def fail_first(*args, **kwargs):
        # Fail inside `delete_data`, after its two row deletes have run.
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("crash after the row deletes")
        return real_rmtree(*args, **kwargs)

    # Restored by hand: monkeypatch.undo() would also revert the fixture's BATTERY_SIM_DATA_DIR
    # setenv, sending the assertions below at the real ./data.
    workspaces.shutil.rmtree = fail_first
    try:
        with pytest.raises(RuntimeError):
            workspaces.delete(db.WORKSPACE_ID)
    finally:
        workspaces.shutil.rmtree = real_rmtree

    # delete_data's transaction committed (its block exited cleanly; the rmtree is outside it),
    # so the dataset rows are gone — but the workspace row was never reached and survives intact,
    # which is the honest post-condition: no half-deleted row set, and nothing orphaned.
    assert workspaces.get(db.WORKSPACE_ID) is not None
    assert db.source_generation(db.WORKSPACE_ID) == 1


# ── The two new config fields ────────────────────────────────────────────────────────────────


def test_postcode_round_trips(mods):
    _, _, simconfig_store, _ = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig(postcode="1234 AB"))
    assert simconfig_store.load().postcode == "1234 AB"  # stored as typed, unvalidated (§2′.4)


def test_postcode_defaults_when_absent(mods):
    """A document written before the field existed still loads, with an empty postcode."""
    _, _, simconfig_store, _ = mods
    from app.domain.simconfig import SimulationConfig

    doc = simconfig_store.to_dict(SimulationConfig(postcode="1234 AB"))
    doc.pop("postcode")
    assert simconfig_store.from_dict(doc).postcode == ""


def test_postcode_survives_clone(mods):
    """`clone` rebuilds field by field, so an unnamed field silently resets."""
    _, _, simconfig_store, _ = mods
    from app.domain.simconfig import SimulationConfig

    assert simconfig_store.clone(SimulationConfig(postcode="9999 ZZ")).postcode == "9999 ZZ"


def test_pricing_configured_round_trips_and_is_carried_forward(mods):
    """§2′.6: set on the contract save, and never cleared by any other save."""
    _, _, simconfig_store, _ = mods
    from app.domain.simconfig import SimulationConfig

    simconfig_store.save(SimulationConfig())
    assert simconfig_store.is_pricing_configured() is False  # default on a new workspace

    simconfig_store.save(SimulationConfig(), pricing_configured=True)
    assert simconfig_store.is_pricing_configured() is True

    # An ordinary parameter save (no keyword) must not clear it.
    simconfig_store.save(SimulationConfig(simulate_cost=False))
    assert simconfig_store.is_pricing_configured() is True

    # An explicit False does clear it — the flag is settable both ways by its own screen.
    simconfig_store.save(SimulationConfig(), pricing_configured=False)
    assert simconfig_store.is_pricing_configured() is False


def test_pricing_configured_defaults_when_absent(mods):
    """A `retained` block written before the flag existed reads as False, not as missing."""
    import json

    _, _, simconfig_store, _ = mods
    from app.domain.simconfig import SimulationConfig

    doc = simconfig_store.to_dict(SimulationConfig(), pricing_configured=True)
    doc["retained"].pop("pricing_configured")
    simconfig_store.config_path().write_text(json.dumps(doc), encoding="utf-8")

    assert simconfig_store.is_pricing_configured() is False  # absent reads as False
    assert simconfig_store.load().postcode == ""             # and the document still loads


def test_pricing_configured_is_false_without_any_document(mods):
    """No stored config at all → blocked, which is the safe direction (§2′.6)."""
    _, _, simconfig_store, _ = mods
    assert simconfig_store.is_pricing_configured() is False
