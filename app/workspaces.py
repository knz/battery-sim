"""The workspace index and its service layer (specs/20-workspaces-ux.md §2′.2, §2′.10; §5.1).

Until this module existed, "the workspace" was the module constant `db.WORKSPACE_ID` and there
was no record anywhere of which workspaces exist, what they are called, or when they were last
saved. Every persistence call was already workspace-parameterised (`simconfig_store.load/save`,
`dataset.save_dataset/load_latest`, `db.source_generation`) — what was missing is the index those
parameters draw their values from. That index is the `workspaces` table in `app/db.py`, and this
module is the only thing that writes it.

## What `list_summaries` returns, and why it does not load anything

The list screen (§2′.2) renders one card per workspace, and a card shows exactly two kinds of
thing: three badges derived from the CONFIG (connection, contract, last saved), and five facts
about the DATASET (grid consumption / grid production / PV production loaded, the coverage
window, the size). `WorkspaceSummary` is that card and nothing more, so the route stays thin.

The dataset facts are read from SQLite metadata alone — the `datasets` and `series_meta` rows —
and never from the `.npz` arrays. A list of N cards must not load N datasets off disk, and the
metadata records every fact the card states.

The run's SIZE — the grid resolution and the interval count — is metadata only because it is
written there deliberately. `dataset.save_dataset` computes it with `normalize.grid_facts`, which
is the same function the results screen's `grid_report` is built on, and stores it on the
`datasets` row; this module reads it back. It is a cache of something derivable from the frames,
and it exists because deriving it HERE, from `series_meta` alone, was wrong in two ways
(followup I2, closed):

  * The count divided the stored FETCH window, but a run covers only the energy series' coverage
    intersection. A three-hour auxiliary series beside a two-day meter series put 48 on the card
    where the run has 3.
  * The grid was `max(resolution_s)` with no `covers()` test, so an EMPTY energy series carrying
    a coarse resolution reported a coarser grid than §6.2 selects.

Persisting it rather than teaching this module to redo the computation is the point: there is one
implementation of "how big is this run", so the card and the results screen cannot drift again.
Rows written before the columns existed hold NULL and fall back to the old derivation — see
`_data_facts`, which is also where that fallback's remaining wrongness is stated.

The config badges DO load the config document (`simconfig_store.load`), which is a single small
JSON read per workspace with no arrays in it — cheap enough that the alternative (denormalising
`phases`, `fuse_a` and `contract` onto the workspace row) would buy nothing and add a second
copy that can drift.

## Slot → role, for the three "loaded" facts

§2′.2 says the card reports the ROLE and does not expose the T1/T2 register split — that detail
belongs on the configure-data screen, which has room to explain it. So:

    grid consumption ← grid_import_t1        grid production ← grid_export_t1
    PV production    ← solar_production, and only when `has_pv`

T1 is the `required` slot of each register pair in §4.1 (T2 is "expected" but optional), so its
presence is the honest test of whether the role is filled. PV reports **not applicable** rather
than not loaded when `has_pv` is off (§2′.2): a deliberate configuration is not a missing input.

## `updated_at` is the CONFIG's save time

§2′.10 is explicit: it drives both the "last saved" badge and the list ordering, and loading data
must not advance it or the list would reorder itself behind a fetch. So `touch()` is called from
a config save and from nowhere else — in particular not from `dataset.save_dataset`.

## Deletion

Two different operations, per §2′.3:

  * `delete_data` clears the dataset rows and the `.npz` files, leaving `simconfig.json` and the
    workspace row. The workspace survives with its CONFIGURATION intact — but note that a FETCHED
    slot's source mapping does not survive, because it lives in `series_meta`, which is part of
    what is being deleted. See `delete_data` and §2′.3.
  * `delete` removes the workspace row, every row keyed by its id, and the whole workspace
    directory. `feature_interest` is deliberately NOT touched — it is installation-wide and
    survives the deletion of every workspace, including the last (see `app/db.py`).

The ROW deletes within EACH FUNCTION's own `with` block are atomic: a block is a transaction
(`db._Connection`), so `delete_data` cannot leave `series_meta` rows whose `datasets` parent is
gone — the orphan shape that was also reachable by a mis-scoped query before it was corrected.

**The two functions are NOT atomic with each other**, and an earlier version of this comment said
they were. `delete_data` opens `dataset.connect()` and `delete` opens `db.connect()`; `_depth` is
per-connection, so two distinct connection objects never nest. `delete` therefore runs three
sequential independent steps, and their ORDER is chosen so the crash that can happen between them
leaves unreachable residue rather than a live workspace whose data has silently vanished. The full
reasoning is in `delete`.

Nothing here is atomic across rows and files either: the files are removed after the transaction
and the `rmtree` ignores errors, so an interruption can leave files nothing references, silently.
Stated rather than fixed — the residue is wasted disk, not a wrong answer, and reclaiming it needs
a startup sweep this app does not otherwise need. The reasoning is in `delete`.

Main items:
    DataFacts                 the five dataset facts a card states, or `loaded=False`.
    WorkspaceSummary          one card: row fields, three config badges, DataFacts.
    create(title, ...)        insert a new workspace for an owner; returns its id.
    get(id)                   one workspace row, or None.
    list_summaries(owner_id)  every workspace owned by owner_id, as a card, most recently
                              updated first.
    rename(id, title)         set the title (does NOT touch updated_at — a rename is not a save).
    touch(id)                 bump `updated_at` to now; called on config save only.
    delete(id)                remove the workspace, its rows and its directory.
    delete_data(id)      remove its dataset rows and series files, keeping the config.
    migrate_local()      idempotent startup migration of the pre-index single workspace.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import config, dataset, db, simconfig_store

OWNER_ID = "local"
"""`owner_id` exists on `workspaces` from day one, populated with "local" (§5.5 invariant 7).

There is no authentication and no second owner; the column is here so that adding accounts is
an `UPDATE` rather than a schema change.
"""


@dataclass(frozen=True)
class DataFacts:
    """The dataset half of a card (§2′.2's info box).

    `loaded` false means the box collapses to the one-line invitation and the buttons that need
    a dataset are absent — the Inapplicable rule from §2.1, not a greyed control. Every other
    field is then meaningless and left at its default.

    `pv_applicable` is False when the household declared no PV: the card then reads "not
    applicable" rather than "not loaded", because a deliberate configuration is not a missing
    input (§2′.2).

    `resolution_s` and `intervals` are the run's size as `normalize.grid_facts` computed it from
    the frames when the dataset was saved, read back from the `datasets` row — the same pair the
    results screen shows, not a second derivation of it (followup I2). Both are None when no
    energy series covers the window: there is no grid, so a count would be an invention.

    Note `intervals` is NOT `window` divided by `resolution_s`. It is measured over the effective
    window — the energy coverage intersection — which is usually narrower than the advertised
    `window` this card also shows. A reader who divides the two will not get `intervals` back.
    """

    loaded: bool = False
    grid_consumption: bool = False
    grid_production: bool = False
    pv_production: bool = False
    pv_applicable: bool = True
    window: tuple[datetime, datetime] | None = None
    resolution_s: int | None = None
    intervals: int | None = None


@dataclass(frozen=True)
class WorkspaceSummary:
    """One card on the list screen (§2′.2).

    `phases` / `fuse_a` render the connection badge as `1×25 A`; `contract` is the enum VALUE
    verbatim, per §2.3's rule that label and enum do not diverge, and is shown at full strength
    whether or not `simulate_cost` is on. `updated_at` is the last-saved badge and the sort key.

    `simulate_cost` is deliberately NOT carried. §2′.2 shows the contract badge at full strength
    unconditionally, so a card has no use for it, and holding it here would make conditioning the
    badge on it the easy mistake to make. A screen that genuinely needs it can load the config.
    """

    id: str
    title: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    phases: int
    fuse_a: float
    contract: str
    data: DataFacts


# ── The workspace row ────────────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    """A stored ISO timestamp, read as UTC when it was written without an offset.

    Naive stored instants are read as UTC for the same reason `dataset._as_utc` does it: the
    pipeline holds UTC (§4.4), and comparing a naive against an aware datetime raises.
    """
    dt = datetime.fromisoformat(ts)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _insert(conn, wid: str, title: str, owner_id: str = OWNER_ID) -> str:
    """The INSERT alone, on a caller-supplied connection.

    Split out of `create` so `migrate_local` can run its emptiness check and its insert inside ONE
    transaction on ONE connection — the check-then-act race that shape otherwise has is documented
    there. Every other caller goes through `create`, which opens its own connection.

    `owner_id` defaults to the module constant because `migrate_local` is adopting the pre-index
    single workspace, which has no other owner to name (D2 in the owner-scoping changelog);
    `create` always passes one explicitly.
    """
    now = _now()
    conn.execute(
        """INSERT INTO workspaces (id, owner_id, title, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (wid, owner_id, title, now, now),
    )
    return wid


def create(title: str, workspace_id: str | None = None, owner_id: str = OWNER_ID) -> str:
    """Insert a workspace for `owner_id` and return its id.

    The id is opaque and generated (a uuid4 hex) unless the caller names one, which only tests
    do now — the migration inserts through `_insert` on its own connection, for the transaction
    reason documented there. `created_at` and `updated_at` start equal, so a workspace that has
    never been saved still sorts and badges sensibly.

    `owner_id` defaults to the module constant so existing callers — there is only ever one owner
    today — are unaffected; `POST /workspaces` (app/main.py) passes the requesting principal's id.
    """
    with db.connect() as conn:
        return _insert(conn, workspace_id or uuid.uuid4().hex, title, owner_id)


def get(workspace_id: str) -> dict | None:
    """The workspace row as a dict, or None if there is no such workspace."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, owner_id, title, created_at, updated_at FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "owner_id": row[1],
        "title": row[2],
        "created_at": _parse(row[3]),
        "updated_at": _parse(row[4]),
    }


def rename(workspace_id: str, title: str) -> None:
    """Set the title.

    Deliberately does NOT bump `updated_at`. That field is the CONFIGURATION's save time (§2′.10)
    and the route that renames also saves the config, which is what calls `touch`. Bumping here
    too would be harmless while that stays true, and wrong if a rename ever happens on its own.
    """
    with db.connect() as conn:
        conn.execute("UPDATE workspaces SET title = ? WHERE id = ?", (title, workspace_id))


def touch(workspace_id: str) -> None:
    """Record a configuration save: bump `updated_at` to now (§2′.10).

    The ONLY writer of `updated_at` after creation. Loading data must not call this — the card's
    "last saved" badge reads the config's save time, and the list is ordered by it, so a fetch
    that reordered the list would be a surprise every time.

    **The rule is "last USER-INITIATED save", which is narrower than "last time the document was
    written", and the difference is deliberate.** A fetch writes the setup-band answers onto the
    config (`main._persist_setup_answers`) without calling this, so after a fetch `simconfig.json`
    is newer than the badge claims. That is not a bug to be closed by adding a `touch` here: doing
    so would reorder the list behind a data load, which is precisely what §2′.10 forbids. If the
    badge's wording ever needs to be exact, the wording is what changes.
    """
    with db.connect() as conn:
        conn.execute(
            "UPDATE workspaces SET updated_at = ? WHERE id = ?", (_now(), workspace_id)
        )


# ── The card ─────────────────────────────────────────────────────────────────────────────────


def _data_facts(conn, workspace_id: str, has_pv: bool) -> DataFacts:
    """The five §2′.2 dataset facts from SQLite metadata alone (module comment).

    Reads the latest dataset's window, its stored run size, and its series_meta rows. `loaded` is
    false when there is no dataset, and also when the dataset carries no series — a dataset row
    with nothing under it is not something a user can get a result from, so the card should say so
    rather than show a coverage window over an empty set.
    """
    row = conn.execute(
        """SELECT id, window_start, window_end, grid_s, n_intervals FROM datasets
           WHERE workspace_id = ? ORDER BY id DESC LIMIT 1""",
        (workspace_id,),
    ).fetchone()
    if row is None:
        return DataFacts(pv_applicable=has_pv)

    dataset_id, w_start, w_end = int(row[0]), row[1], row[2]
    stored_grid_s, stored_intervals = row[3], row[4]
    metas = conn.execute(
        "SELECT name, kind, resolution_s FROM series_meta WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchall()
    if not metas:
        return DataFacts(pv_applicable=has_pv)

    names = {m[0] for m in metas}
    window = (_parse(w_start), _parse(w_end))

    # §6.2's simulation grid and its interval count, as `normalize.grid_facts` computed them from
    # the frames at save time (app/dataset.py). Read back rather than re-derived: this function
    # has metadata, not frames, and the derivation metadata alone supports was wrong in two
    # separate ways (followup I2, closed) —
    #
    #   * it divided the stored FETCH window, where the run covers only the energy series'
    #     coverage intersection: a three-hour auxiliary series next to a two-day meter series put
    #     48 on the card against a true 3; and
    #   * its `max(resolution_s)` had no `covers()` test, so an EMPTY energy series carrying a
    #     coarse resolution reported a coarser grid than the run uses.
    #
    # `grid_s` is NULL only on rows written before the columns existed, and the fallback below is
    # that old derivation, kept so an existing local DB keeps its card line until its next load.
    # It is still wrong in the two ways above; it is not worth a frame read per card to improve a
    # transient state, and a new dataset never lands here.
    if stored_grid_s is not None:
        resolution_s, intervals = int(stored_grid_s), (
            int(stored_intervals) if stored_intervals is not None else None
        )
    else:
        resolutions = [m[2] for m in metas if m[1] == "energy" and m[2] is not None]
        resolution_s = max(resolutions) if resolutions else None
        intervals = None
        if resolution_s:
            span = (window[1] - window[0]).total_seconds()
            intervals = max(int(span // resolution_s), 0)

    return DataFacts(
        loaded=True,
        # The role, not the register split (module comment): T1 is §4.1's required slot of each
        # pair, so its presence answers "is this role filled".
        grid_consumption="grid_import_t1" in names,
        grid_production="grid_export_t1" in names,
        pv_production=has_pv and "solar_production" in names,
        pv_applicable=has_pv,
        window=window,
        resolution_s=resolution_s,
        intervals=intervals,
    )


def list_summaries(owner_id: str) -> list[WorkspaceSummary]:
    """Every workspace owned by `owner_id`, as a card, most recently updated first (§2′.2).

    Required rather than defaulted or optional: an `owner_id: str | None = None` meaning "all
    owners" was considered and rejected, because an optional filter is exactly how the
    missing-filter bug this scoping closes would get reintroduced (D3 in the owner-scoping
    changelog). `GET /` (app/main.py) passes the requesting principal's id.

    One SQLite connection for the whole list, plus one small JSON read per workspace for the
    config badges. Ordering is by `updated_at` descending — the configuration's save time, so
    loading data does not reorder the list (§2′.10). Ties break on `id` so the order is stable
    rather than whatever SQLite happens to return, which matters for a fresh installation whose
    workspaces were all created in the same second.
    """
    summaries: list[WorkspaceSummary] = []
    # `dataset.connect` rather than `db.connect`: the card's data facts query `datasets` and
    # `series_meta`, which app/db.py's schema does not create, so a fresh installation would
    # raise "no such table" instead of reporting no data.
    with dataset.connect() as conn:
        rows = conn.execute(
            """SELECT id, owner_id, title, created_at, updated_at FROM workspaces
               WHERE owner_id = ? ORDER BY updated_at DESC, id ASC""",
            (owner_id,),
        ).fetchall()
        for wid, row_owner_id, title, created_at, updated_at in rows:
            cfg = simconfig_store.load(wid)
            summaries.append(
                WorkspaceSummary(
                    id=wid,
                    title=title,
                    owner_id=row_owner_id,
                    created_at=_parse(created_at),
                    updated_at=_parse(updated_at),
                    phases=cfg.grid.phases,
                    fuse_a=cfg.grid.fuse_a,
                    # The enum VALUE, not a label (§2.3: label and enum do not diverge).
                    contract=getattr(cfg.pricing.contract, "value", cfg.pricing.contract),
                    data=_data_facts(conn, wid, bool(cfg.has_pv)),
                )
            )
    return summaries


# ── Deletion ─────────────────────────────────────────────────────────────────────────────────


def _workspace_dir(workspace_id: str) -> Path:
    """`<data_dir>/<workspace>/`, WITHOUT creating it. Rejects path traversal (§5.5 invariant 4).

    Same rule as `simconfig_store._workspace_dir` and `dataset._series_dir`, but it must not
    mkdir: this one is used to delete, and a delete that first created the directory it is about
    to remove would be absurd on a workspace that never had one.
    """
    if "/" in workspace_id or "\\" in workspace_id or workspace_id in ("", ".", ".."):
        raise ValueError(f"unsafe workspace_id: {workspace_id!r}")
    return config.data_dir() / workspace_id


def delete_data(workspace_id: str) -> None:
    """Remove the workspace's datasets and series files, keeping its configuration (§2′.3).

    Deletes the `datasets` and `series_meta` rows and the `series/` directory. `simconfig.json`
    and the workspace row survive — the user asked to clear the data, not to undo their setup.

    **A FETCHED slot's source mapping does NOT survive, and the dialog copy says so.** It is not
    browser state: when a fetch persists a series, its source key and HA statistic id are stored in
    `series_meta` alongside it, and the slot roster renders the slot's source from the dataset on
    every reload (`app/static/ha_fetch.js`, branch 1 of "Two things carry a source choice across a
    reload"). Deleting `series_meta` is deleting that. Only branch 2 — a PRE-FETCH staged choice in
    `localStorage`, one the user made but has not fetched — is untouched here. §2′.3 and the
    delete-data dialog used to promise the mapping survived in general; both now state the split.

    `source_generation` is still left alone, and that is what protects branch 2: it is a monotonic
    counter the browser compares a staged mapping against, so resetting it would make a live staged
    choice look stale and discard the one kind of mapping this delete does not otherwise touch.

    The two row deletes are ONE transaction (`db._Connection`), so `series_meta` and `datasets`
    cannot go out of step with each other — no dataset stripped of its series, no series rows left
    under a dataset that is gone.

    Rows and files are still separate, though: the rows go in one step and the files in another,
    and `rmtree` ignores errors, so a crash in between (or a file the process cannot remove) leaves
    `.npz` files with no row referencing them and nothing to reclaim them later. The cost is wasted
    disk, never a wrong result — an orphaned array is unreachable, since every read goes through
    `series_meta`. See `delete` for why that is accepted rather than fixed.
    """
    _workspace_dir(workspace_id)  # traversal check before any destructive work
    with dataset.connect() as conn:
        # Scoped by `series_meta`'s OWN `workspace_id`, not through a subquery on `datasets`.
        # `PRAGMA foreign_keys` is off, so the declared ON DELETE CASCADE never fires, and a row
        # whose parent dataset is already gone would survive a delete routed through the parent.
        # Nothing in `save_dataset` / `upsert_series` can produce such a row today; this is the
        # spelling that does not depend on that staying true, and it is the simpler query.
        conn.execute("DELETE FROM series_meta WHERE workspace_id = ?", (workspace_id,))
        conn.execute("DELETE FROM datasets WHERE workspace_id = ?", (workspace_id,))
    shutil.rmtree(_workspace_dir(workspace_id) / "series", ignore_errors=True)


def delete(workspace_id: str) -> None:
    """Remove the workspace, every row keyed by its id, and its directory (§2′.3).

    `feature_interest` is NOT touched, and that is the point of it being installation-wide: a
    thumbs-up records what this household wants and must survive the deletion of the analysis it
    was clicked from, including the deletion of the last one (see `app/db.py`).

    **This is NOT one transaction, and an earlier version of this docstring wrongly said it was.**
    The claim was that the `delete_data` call nests into this function's block the way
    `db._Connection`'s blocks nest. They cannot: `delete_data` opens `dataset.connect()` and the
    block below opens `db.connect()`, and `_depth` is per-CONNECTION, so two connection objects
    never nest into each other however the `with` blocks are written. What actually runs is three
    sequential, independent steps — the row deletes, the data deletes, the `rmtree` — each atomic
    in itself, none atomic with the others.

    **So the ORDER is chosen for which crash leaves the better wreckage**, since some order has to
    lose. The workspace row goes FIRST, and the data second:

      * Row first, crash after → dataset rows and `.npz` files behind a workspace that is gone
        from the index. Unreachable residue: nothing lists it, nothing can open it, and it is the
        same shape as the orphaned directory the `rmtree` step already tolerates.
      * Data first, crash after (the previous order) → the workspace row SURVIVES with its
        measurements destroyed. The list still shows the card, `[ Results ]` still invites the
        user in, and their data is silently gone. That is strictly worse: it presents as corruption
        of a live analysis rather than as leftover bytes.

    Either way the user's request is honoured on the next successful pass; only one of them lies to
    them in the meantime.

    Genuine atomicity was considered and not attempted. The two tables live in the same SQLite
    file, so sharing one connection is technically possible — but it would mean giving
    `delete_data` a connection parameter that exists for this one caller, and threading it through
    a function whose own contract is "open the dataset database and clear it". An honest docstring
    plus the ordering that fails better is the proportionate answer for a local single-user delete.

    **Rows and files are not atomic together either**, for the same reason and with the same
    accepted cost: `rmtree` passes `ignore_errors=True`, so an interruption — or a file the process
    may not remove — leaves a directory on disk that no row references. The residue is wasted disk
    rather than a wrong answer. Reclaiming it needs a startup pass over directories with no
    workspace row, which is more machinery than this warrants; if orphans ever turn out to matter,
    that pass is where the fix goes.
    """
    _workspace_dir(workspace_id)  # traversal check before any destructive work
    # The index row first — see the docstring on why this order's failure mode is the better one.
    with db.connect() as conn:
        conn.execute("DELETE FROM workspace_state WHERE workspace_id = ?", (workspace_id,))
        conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
    delete_data(workspace_id)
    shutil.rmtree(_workspace_dir(workspace_id), ignore_errors=True)


# ── Migration ────────────────────────────────────────────────────────────────────────────────

DEFAULT_TITLE = "My analysis"
"""The generated title for the migrated workspace (§2′.10: "a generated title").

Deliberately not translated. It is written to the database once, at migration time, in whatever
locale happens to be active for the process that starts first — a stored string cannot follow the
user's later language toggle, so translating it would produce a title that is wrong half the time
rather than neutral all of it. The user renames it on the edit screen (§2′.4).
"""


def migrate_local() -> bool:
    """Give the pre-index single workspace a row. Idempotent. Returns True if it inserted one.

    Runs on startup (`app/main.py`'s lifespan). Two conditions, both required:

      * the `workspaces` table is EMPTY — a populated index means the migration already ran, or
        the user has real workspaces, and either way there is nothing to adopt. This is what
        makes a second run a no-op.
      * `local` has something on disk — a config document or a dataset row. A fresh installation
        has neither and must NOT get a phantom workspace: it should see the empty list and the
        wizard, not an "analysis" it never created.

    It also sets `pricing.configured` on the adopted config when cost simulation is already on
    (§2′.6). Someone with cost results on screen today must not find them switched off and the
    toggle blocked after an upgrade; a workspace with cost simulation off is left at whatever the
    flag already says, which for a pre-§2′.6 document is false — the toggle they were not using
    becomes one that asks for a contract first.

    **The migration only ever SETS the flag, never clears it.** `pricing_configured` is passed as
    `True` or as `None` ("carry the stored value forward"), never as `False`: an explicit `False`
    overrides `simconfig_store`'s carry-forward, so a user who had configured pricing but had cost
    simulation off would have the flag cleared — the inverse of §2′.6's "never cleared
    automatically", which is the rule this migration exists to honour.

    **And it never writes over a document it did not understand.** `simconfig_store.load()`
    returns appendix-A defaults for every failure, including a document whose version is not this
    build's — deliberately, so a future build's file is not misread as this one's. Saving those
    defaults back would DOWNGRADE such a file and discard the user's parameters, and would equally
    overwrite a partially-written file that was still hand-recoverable. So the save is SKIPPED
    when a document exists that this build cannot round-trip (`_config_is_readable`), and the
    workspace is adopted with its file untouched. The flag still lands for the two ordinary cases:
    a readable v1 document is re-saved with its own values, and a dataset-only workspace with no
    document at all gets one written with appendix-A defaults, as before.

    The accepted cost: a workspace whose document is unreadable does not get the flag set, so its
    cost toggle asks for a contract once. That is recoverable in a single screen; a destroyed
    parameter set is not.

    **The emptiness check and the INSERT are ONE transaction**, and they have to be. Written as a
    `SELECT COUNT(*)`, a released connection and then a `create()`, this is a check-then-act race:
    two threads or two uvicorn workers starting together both see an empty table and both insert
    `local`, and the second gets `IntegrityError: UNIQUE constraint failed: workspaces.id`. It was
    reproduced with 16 concurrent threads against a genuine pre-index directory — 2 failures in 6
    runs. The suite never sees it, because it only fires when there is something on disk to adopt.

    It matters more than a swallowed exception usually would: `app/main.py`'s lifespan catches it
    broadly and logs `workspace migration failed (ignored)`, and that message tells the reader an
    installation may have been left unadopted. A scary and untrue log, during the one startup
    operation where a scary log would be believed.

    So the whole decision runs inside a single `dataset.connect()` block. `_Connection.__enter__`
    issues `BEGIN IMMEDIATE`, taking the write lock BEFORE the count, so a second migration blocks
    at that point (up to `db._TIMEOUT_S`) and then reads a table that is no longer empty and
    returns False. The insert goes through `_insert` on this same connection rather than `create`,
    which would open a second one and put the INSERT outside the transaction the check holds.

    The config work stays OUTSIDE the transaction on purpose: it is file I/O, it cannot be rolled
    back by SQLite, and holding a write lock across it would serialise every other writer behind a
    disk read for no atomicity gained. By the time it runs, this call has won the race — the row is
    committed and no second migration can be in flight.

    `updated_at` is NOT bumped afterwards: the row was just created with
    `updated_at == created_at`, and this save is the migration's, not the user's.
    """
    with dataset.connect() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        if existing:
            return False
        has_dataset = conn.execute(
            "SELECT 1 FROM datasets WHERE workspace_id = ? LIMIT 1", (db.WORKSPACE_ID,)
        ).fetchone()

        has_config = simconfig_store.config_path(db.WORKSPACE_ID).exists()
        if not has_config and not has_dataset:
            return False

        # Same connection, same transaction as the count above — see the docstring.
        _insert(conn, db.WORKSPACE_ID, DEFAULT_TITLE)

    if has_config and not simconfig_store.is_document_readable(db.WORKSPACE_ID):
        # A document is there but this build cannot make sense of it (docstring). Adopt the
        # workspace and leave the file exactly as it is.
        return True
    cfg = simconfig_store.load(db.WORKSPACE_ID)
    simconfig_store.save(
        # True or None, never False — an explicit False would clear a flag the store would
        # otherwise carry forward (docstring, §2′.6).
        cfg,
        db.WORKSPACE_ID,
        pricing_configured=True if cfg.simulate_cost else None,
    )
    return True
