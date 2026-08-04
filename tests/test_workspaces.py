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

from tests.conftest import seed_workspace


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
    assert workspaces.list_summaries(workspaces.OWNER_ID) == []


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
    assert len(workspaces.list_summaries(workspaces.OWNER_ID)) == 1
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
    assert len(workspaces.list_summaries(workspaces.OWNER_ID)) == 1

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
    assert [s.title for s in workspaces.list_summaries(workspaces.OWNER_ID)] == ["Something else"]


# ── list_summaries ───────────────────────────────────────────────────────────────────────────


def test_summary_with_data(mods):
    dataset, db, simconfig_store, workspaces = mods
    from app.domain.simconfig import GridConfig, SimulationConfig

    simconfig_store.save(SimulationConfig(has_pv=True, grid=GridConfig(phases=3, fuse_a=25)))
    _save_dataset(dataset)
    workspaces.migrate_local()

    (card,) = workspaces.list_summaries(workspaces.OWNER_ID)
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

    (card,) = workspaces.list_summaries(workspaces.OWNER_ID)
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

    (card,) = workspaces.list_summaries(workspaces.OWNER_ID)
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

    (card,) = workspaces.list_summaries(workspaces.OWNER_ID)
    assert card.data.pv_applicable is False
    assert card.data.pv_production is False


def test_summaries_are_ordered_most_recently_updated_first(mods):
    """§2′.2's ordering, and §2′.10's rule that it follows the CONFIG's save time."""
    _, _, _, workspaces = mods

    a = workspaces.create("A")
    b = workspaces.create("B")
    workspaces.touch(a)  # a saved after b was created

    assert [s.id for s in workspaces.list_summaries(workspaces.OWNER_ID)] == [a, b]

    workspaces.touch(b)
    assert [s.id for s in workspaces.list_summaries(workspaces.OWNER_ID)] == [b, a]


def test_touch_moves_updated_at_and_rename_does_not(mods):
    """§2′.10: `touch()` is the only writer of `updated_at`, and a rename is not one.

    **The `touch()` half is asserted against a back-dated row.** It used to read `assert
    updated_at >= created`, with `created` taken from the same row a moment earlier — which holds
    whether or not `touch()` wrote anything, because `_now()` never goes backwards. So the one
    unit test of `touch()` did not constrain `touch()`. Writing a fixed instant well in the past
    into the column first makes the `>` real: only a write can move the row off it.

    The rename half needs no such treatment. It asserts EQUALITY against the value the row was
    created with, which a spurious write would break.
    """
    from datetime import timedelta

    from app import db

    _, _, _, workspaces = mods

    wid = workspaces.create("Before")
    created = workspaces.get(wid)["updated_at"]

    workspaces.rename(wid, "After")
    row = workspaces.get(wid)
    assert row["title"] == "After"
    assert row["updated_at"] == created  # a rename is not a configuration save (§2′.10)

    past = created - timedelta(days=365)
    with db.connect() as conn:
        conn.execute(
            "UPDATE workspaces SET updated_at = ? WHERE id = ?", (past.isoformat(), wid)
        )
    assert workspaces.get(wid)["updated_at"] == past

    workspaces.touch(wid)
    assert workspaces.get(wid)["updated_at"] > past, (
        "touch() must write updated_at; the row is still at its back-dated value"
    )


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
    (card,) = workspaces.list_summaries(workspaces.OWNER_ID)
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
    assert workspaces.list_summaries(workspaces.OWNER_ID) == []
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


def test_a_crash_partway_through_delete_leaves_residue_not_a_gutted_workspace(mods):
    """`delete`'s steps are not atomic with each other, so the ORDER decides the failure mode.

    **What this used to assert, and why it was the wrong post-condition.** The previous version
    ran under the previous ordering — data first, then the workspace row — and asserted that after
    a crash in between, the workspace row "survives intact", calling that "the honest
    post-condition: no half-deleted row set, and nothing orphaned". It is not honest and it is not
    nothing orphaned: the surviving row is a card still on the user's list, still offering
    `[ Results ]`, whose measurements have silently been destroyed. That presents as corruption of
    a live analysis.

    It also rested on a docstring claim that was false — that `delete_data`'s block nested into
    `delete`'s into one transaction. It cannot: `delete_data` opens `dataset.connect()` and
    `delete` opens `db.connect()`, and `_Connection._depth` is per-connection, so two connection
    objects never nest. There were always three independent steps.

    **What is asserted now.** The row goes first, so a crash leaves the inverse — the workspace is
    gone from the index and some data rows or files may remain behind it. That residue is
    unreachable: nothing lists the workspace, so nothing can open its series, which is the same
    shape as the orphaned directory the `rmtree` step has always tolerated (finding I3).

    Genuine atomicity is still not claimed anywhere; see `workspaces.delete` for why that trade
    stands rather than threading one connection through both functions.
    """
    dataset, db, _, workspaces = mods
    from app.domain.simconfig import SimulationConfig
    import app.simconfig_store as store

    store.save(SimulationConfig())
    _save_dataset(dataset)
    workspaces.migrate_local()
    db.bump_source_generation(db.WORKSPACE_ID)

    # Crash at the start of the SECOND step, i.e. immediately after the workspace row's own
    # transaction has committed. Restored by hand: monkeypatch.undo() would also revert the
    # fixture's BATTERY_SIM_DATA_DIR setenv and send the assertions below at the real ./data.
    real_delete_data = workspaces.delete_data

    def crash(*args, **kwargs):
        raise RuntimeError("crash between the row delete and the data delete")

    workspaces.delete_data = crash
    try:
        with pytest.raises(RuntimeError):
            workspaces.delete(db.WORKSPACE_ID)
    finally:
        workspaces.delete_data = real_delete_data

    # The workspace is gone from the index — the user's request, as far as it got.
    assert workspaces.get(db.WORKSPACE_ID) is None
    assert workspaces.list_summaries(workspaces.OWNER_ID) == []
    # Its data rows are still on disk, and that is the accepted residue: unreachable, because
    # nothing lists the workspace they belong to. The inverse — a listed workspace with no data —
    # is what the previous ordering produced and what this ordering exists to avoid.
    with dataset.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM series_meta WHERE workspace_id = ?", (db.WORKSPACE_ID,)
        ).fetchone()[0] > 0


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


# ── The migration's check-then-act race (phase 2 review, should-fix 3) ───────────────────────

def test_concurrent_migrations_insert_exactly_one_row_and_none_of_them_raise(mods):
    """`migrate_local` is safe to run from several starting processes at once.

    **The shape this guards.** Written as `SELECT COUNT(*)`, connection released, then `create()`,
    the migration is a check-then-act race: two uvicorn workers (or two threads) starting together
    both read an empty table and both insert `local`, and the loser gets
    `IntegrityError: UNIQUE constraint failed: workspaces.id`. It was reproduced at this width —
    2 failures in 6 runs — before the count and the insert were put in one transaction.

    **Why it mattered more than a swallowed exception usually does.** `app/main.py`'s lifespan
    catches it broadly and logs `workspace migration failed (ignored)`, and that message tells the
    reader an installation may have been left unadopted. The adoption had in fact succeeded; the
    log said otherwise, during the one startup step where a frightening log would be believed.

    **Why the suite never saw it.** Both conditions are needed: an empty `workspaces` table AND
    something on disk under `local` to adopt. Every other migration test runs single-threaded, so
    the window is real but never entered. This one arranges a genuine pre-index directory (a saved
    config, no workspace row) and enters it deliberately.

    Two assertions, and the second is the one that would catch a "fix" that merely swallowed the
    error: exactly ONE row exists afterwards, and exactly one call reports having inserted it.
    """
    import threading

    _, _, simconfig_store, workspaces = mods
    # A genuine pre-index installation: a config document under `local`, no workspaces row.
    simconfig_store.save(simconfig_store.load("local"), "local")

    errors: list[Exception] = []
    inserted: list[bool] = []
    barrier = threading.Barrier(16)

    def run():
        # Line the threads up so they contend, rather than serialising on thread start-up.
        barrier.wait()
        try:
            inserted.append(workspaces.migrate_local())
        except Exception as exc:  # noqa: BLE001 - the failure this test is about
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"migrate_local raced: {errors!r}"
    assert inserted.count(True) == 1, "more than one caller claimed to have adopted `local`"
    assert [s.id for s in workspaces.list_summaries(workspaces.OWNER_ID)] == ["local"]


# ── Cross-owner invisibility (phase 2, changelog 20260804-owner-scoping.md) ────────────────────
#
# `get_principal()` stays hard-coded to `Principal(id="local")` (D2): there is still only one
# principal in this build. What these tests pin is that ownership, once carried on a row, is
# actually CHECKED — by `list_summaries`'s filter and by `_authorize` — rather than merely stored.
# They exist so that whenever `get_principal` stops being constant, a missing filter fails here
# first instead of silently leaking another owner's workspaces.


def test_list_summaries_is_filtered_by_owner(mods):
    """A workspace owned by `"other"` is invisible to `"local"` and visible to its own owner.

    Both directions are asserted on the SAME row: a filter that vacuously returned `[]` for every
    owner would still pass the first assertion, and a filter that ignored `owner_id` entirely
    would still pass the second — only the pair together pins that the SQL predicate is doing the
    work (D3).
    """
    _, _, _, workspaces = mods
    workspaces.create("Someone else's analysis", workspace_id="mine-not-yours", owner_id="other")

    assert workspaces.list_summaries(workspaces.OWNER_ID) == []
    (card,) = workspaces.list_summaries("other")
    assert card.id == "mine-not-yours"


def test_the_workspace_list_page_omits_another_owners_workspace(mods):
    """`GET /` renders only the requesting principal's cards (§2′.2), not every owner's.

    `get_principal()` always returns `"local"` (D2), so a workspace seeded for `"other"` must
    never appear on the rendered list. Checked both ways on the same response: the other
    owner's `data-workspace-id` marker (present on the card's `<article>` and its two delete
    buttons in `app/templates/_workspace_card.html`) must be entirely absent, while a workspace
    seeded for `"local"` in the same test must still have its own `data-workspace-id` marker
    present — otherwise an empty-for-unrelated-reasons page would pass vacuously.
    """
    from starlette.testclient import TestClient

    _, _, _, workspaces = mods
    seed_workspace(workspace_id="not-yours", owner_id="other")
    workspaces.create("My own analysis", workspace_id="mine-too")

    from app import main

    client = TestClient(main.app)
    html = client.get("/").text
    assert 'data-workspace-id="not-yours"' not in html
    assert 'data-workspace-id="mine-too"' in html


@pytest.mark.parametrize("method,suffix,kwargs", [
    ("get", "/results", {}),
    ("get", "/edit", {}),
    ("get", "/data", {}),
    ("post", "/params", {"data": {"sections": "battery"}}),
])
def test_workspace_scoped_routes_404_on_another_owners_workspace(mods, method, suffix, kwargs):
    """`_authorize` (app/deps.py) denies access as a 404, for every workspace-scoped route.

    Pins `_authorize`'s EXISTING behaviour rather than adding any: a row belonging to `"other"`
    must be indistinguishable from a workspace that does not exist at all, for the same reason
    `deps.get_workspace`'s docstring gives — a workspace you may not use should not be
    distinguishable from one that is simply absent.
    """
    from starlette.testclient import TestClient

    _, _, _, workspaces = mods
    workspaces.create("Someone else's analysis", workspace_id="not-yours", owner_id="other")

    from app import main

    client = TestClient(main.app)
    r = getattr(client, method)(f"/w/not-yours{suffix}", **kwargs)
    assert r.status_code == 404, f"{method.upper()} /w/not-yours{suffix} -> {r.status_code}"


def test_delete_on_another_owners_workspace_redirects_and_leaves_the_row_intact(mods):
    """`POST /w/{id}/delete` on someone else's workspace is a no-op redirect, not a 404 or a delete.

    This is where `get_optional_workspace`'s deliberate 404-softening (for a double-submitted
    deletion, app/deps.py) meets ownership, and it is untested before this: the dependency
    resolves an unowned row to `None` exactly as it would an already-deleted one, so the route
    redirects to the list — but the row itself must still be there afterwards, unlike a genuine
    double-submission where there is truly nothing left. Both the redirect and the row's survival
    are asserted, because either one failing alone would be the wrong kind of "safe": a 404 here
    would at least not delete anything, and a silent delete would at least not confuse the caller
    with a raw error.
    """
    from starlette.testclient import TestClient

    _, _, _, workspaces = mods
    workspaces.create("Someone else's analysis", workspace_id="not-yours", owner_id="other")

    from app import main

    client = TestClient(main.app)
    r = client.post("/w/not-yours/delete", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert workspaces.get("not-yours") is not None


def test_create_writes_the_principals_id_not_the_owner_constant(mods):
    """`workspaces.create` records the CALLER'S owner, not the module constant `OWNER_ID`.

    Phase 1 made `create` take an explicit `owner_id`; this pins that the value actually reaches
    the row rather than `_insert` falling back to its own default (which is deliberately
    `OWNER_ID`-defaulted for `migrate_local`, D7). `"other"` is chosen precisely because it is not
    `OWNER_ID`, so a regression to the hard-coded constant is visible rather than accidentally
    matching.
    """
    _, _, _, workspaces = mods
    assert workspaces.OWNER_ID != "other"

    wid = workspaces.create("Someone else's analysis", owner_id="other")

    row = workspaces.get(wid)
    assert row["owner_id"] == "other"
