# 20260726 — Workspaces restructure, phase 0 (prepare)

Implements phase 0 of
[20260726-workspaces-implementation-plan.md](20260726-workspaces-implementation-plan.md),
against [specs/20-workspaces-ux.md](../specs/20-workspaces-ux.md) §2′.2, §2′.4, §2′.6, §2′.10.

## Task specification

No user-visible change. Build the plumbing the later phases need:

1. A `workspaces` table (§5.1 shape plus `updated_at` and `title`).
2. `app/workspaces.py` — `create`, `list_summaries`, `get`, `rename`, `touch`, `delete`,
   `delete_data`.
3. An idempotent startup migration inserting `local` when the table is empty and a config or
   dataset exists on disk, setting `pricing.configured = simulate_cost` for it.
4. `feature_interest` becomes installation-wide (drop `workspace_id` from the key), with a
   real migration for existing databases. `workspace_state.source_generation` stays
   per-workspace.
5. Three new fields: `title` (workspace row), `postcode` and `pricing.configured` (config
   document).

## High-level decisions

**`title` on the workspace row, not the config document.** Per §2′.10: it names the workspace
rather than parameterising a run. `SimulationConfig` stays a pure parameter set.

**`pricing.configured` lives in the store's `retained` block, not on `PricingConfig`.**
Reasoning recorded in `simconfig_store`'s module comment. The short version: the flag is not a
simulation parameter — no domain code reads it, and §6.5 would be unable to say what it means.
It is a UI precondition. The two candidate homes were `PricingConfig` (where it would have to
be threaded through `parse_form`, `clone`, `to_dict` and every construction site, and would
appear in a dataclass whose docstring says every field is a contract term) and the store's
existing `retained` block (which already holds one non-parameter fact the config object cannot
carry). The `retained` block is the closer fit, but for a different reason from
`economic_guard`: that one is there because `_force_invariants` erases it. `configured` is
there because it is not a parameter at all. The module comment states both so the block is not
read as "the drawer for cost stuff".

The store therefore grows `is_pricing_configured()` / `save(..., pricing_configured=...)`
beside `load()`, and the flag is carried forward untouched when a save does not mention it —
§2′.6's "never cleared automatically".

**`postcode` on the config document**, as a plain top-level string field on
`SimulationConfig`. Unlike `configured` it *is* household-scoped configuration in the same
sense as `has_pv`, nothing forces or normalises it, and the alternative (a second sidecar
slot) would put two unrelated things in `retained`. Stored as typed, no format validation
(§2′.4 leaves that open). Read by nothing.

**`list_summaries` reads SQLite metadata only.** The five data facts come from `datasets` +
`series_meta` rows, never from the `.npz` arrays: a list of N cards must not load N datasets.
The consequence, stated openly: the interval count is *derived* from the stored window and the
grid resolution (§6.2's coarsest covering energy resolution) rather than counted from the
index array. It can differ from the count the results screen reports, which reconciles real
indices over a resolved window. For a card badge that is an acceptable trade; if it turns out
to mislead, the fix is a persisted `n_intervals` column on `datasets`, not an npz read per
card.

**Slot → role mapping for the card.** "Grid consumption" is loaded when `grid_import_t1` is
present, "grid production" when `grid_export_t1` is. §2′.2 says the card reports the role and
does not expose the T1/T2 register split; T1 is the `required` slot of each pair in §4.1, so
its presence is the honest test of whether the role is filled.

**`feature_interest` migration.** `CREATE TABLE IF NOT EXISTS` cannot change an existing
table's primary key, so the migration is explicit: detect the old shape via
`PRAGMA table_info`, and if `workspace_id` is present, create a new table with
`PRIMARY KEY (feature_key)`, `INSERT … SELECT feature_key, MIN(count-as-1), MIN(last_clicked_at)
GROUP BY feature_key`, drop the old, rename. Earliest timestamp, count clamped to 1 — the merge
is a union, not a sum (§2′.10: interest is boolean per household). Runs inside the
`_connect()` path so any code path that touches the DB repairs the shape, which also means the
tests do not need to call it.

**Startup migration hook.** `app/main.py` had no lifespan handler; it did import-time work
(`CONFIG = config.load()`). The workspace migration is added as a FastAPI `lifespan` rather
than more import-time work, so a test importing `app.main` does not write to a data directory
it has not chosen yet.

## Files modified

- `app/db.py` — `workspaces` table in `_SCHEMA`; `feature_interest` re-keyed on `feature_key`
  alone plus `_migrate_feature_interest`; `record_interest` / `interest_count` lose their
  `workspace_id` parameter; docstring rewritten (invariant-1 exception, migration).
- `app/workspaces.py` — new. The workspace service and `WorkspaceSummary` / `DataFacts`.
- `app/simconfig_store.py` — `postcode` in `to_dict`/`from_dict`; `pricing_configured` in the
  `retained` block with `is_pricing_configured()` and a `save()` keyword; `is_document_readable()`
  added during the review fixes (see below); docstring extended.
- `app/domain/simconfig.py` — `postcode: str = ""` on `SimulationConfig`, carried by `clone`.
- `app/main.py` — lifespan running `workspaces.migrate_local()`; `/feature-interest/{key}`
  drops the workspace argument; module docstring updated.
- `specs/08-architecture.md` — §5.5 invariant 1 amended with the `feature_interest` exception.
- `tests/test_feature_interest.py` — updated for the new signature; added the collapse test.
- `tests/test_workspaces.py` — new: migration idempotence, `list_summaries` in three states,
  deletion, traversal rejection, ordering, and the postcode / `pricing.configured` round-trip
  and defaulting tests. These last were written here rather than in a new
  `tests/test_simconfig_store.py`, since the store has no dedicated test module and the fields
  arrived with the workspace work.
- `specs/implementation-progress.md` — the backend-status entry restated for the re-keyed
  `feature_interest`, which it still described in its old `(workspace_id, feature_key)` shape.

## Obstacles

- `SimulationConfig` reconstructs itself field by field in `clone` and in `params_view`'s
  candidate build — a new top-level field must be named in `clone` or it silently resets
  (the defect `test_clone_preserves_has_battery` guards). `postcode` added there.
- `save()` had no way to express "the caller did not draw this control", the same problem
  `guard_submitted` solves for `economic_guard`. Solved the same way: the keyword defaults to
  `None`, meaning carry forward.

## Review findings and fixes

Two independent reviews of the phase-0 working tree raised eight findings. A ninth — a regression
introduced by the fix for the first — was found afterwards by verifying that fix, not by either
review. All nine are fixed in place; no phase-1 work was started.

**1 (blocking) — `_migrate_feature_interest` could brick an installation.** The reshape used
`executescript`, which issues an implicit COMMIT and then commits statement by statement, so
there was no atomicity, and the scratch table name was unguarded. Two consequences were
reproduced: a process dying between the `CREATE TABLE feature_interest_new` and the final
`ALTER TABLE … RENAME` left the scratch table behind as a committed artifact, after which every
`_connect()` raised `table feature_interest_new already exists` with no self-repair path; and
six threads opening an old-shape DB failed in 4 of 12 runs, mostly on the same error, once on
the rename colliding.

Fix: the reshape now runs inside an explicit `BEGIN IMMEDIATE` (write lock taken up front)
rather than `executescript`, with `isolation_level=None` on the connection so `sqlite3` does no
implicit transaction management of its own, and a `timeout` (10 s) so a concurrent writer waits
rather than failing immediately with "database is locked". The shape is re-checked *inside* the
transaction — the check outside it is only a cheap fast path — so a thread that lost the race
sees the migrated shape and does nothing. The scratch table is dropped before it is created, so
a leftover from an interrupted run is reclaimed rather than being fatal.

Connections are now opened with `isolation_level=None` throughout, which changes what
`with conn:` means for the rest of the package: SQLite still autocommits each statement, so the
`with` block no longer wraps a transaction. Every existing use is a single statement or a
single-statement upsert plus a read, so behaviour is unchanged; `record_interest`'s
existence-check comment was corrected, since that pair is no longer one transaction (the
existence check and the upsert can now interleave with a concurrent writer — the reported
first-vs-repeat boolean is advisory, and the upsert itself remains atomic).

**2 (blocking) — `migrate_local` cleared a set `pricing_configured`.** It passed
`pricing_configured=bool(cfg.simulate_cost)`, and an explicit `False` overrides the store's
carry-forward, so a user with pricing configured but cost simulation off had the flag cleared —
the inverse of §2′.6's "never cleared automatically". Fixed to pass
`True if cfg.simulate_cost else None`: the migration only ever *sets* the flag.

**3 (should-fix) — `migrate_local` overwrote a config document it could not parse.**
`simconfig_store.load()` returns appendix-A defaults on any failure, including a document with a
version other than 1, and the migration wrote those defaults straight back — a v2 document was
downgraded to v1 and the user's parameters discarded.

Fixed by making the missing distinction explicit rather than by guessing at it from `load()`'s
output. `simconfig_store` grows `is_document_readable(workspace_id)`: true only for a document
that parses as JSON, is an object, and carries a version this build accepts — the same rule
`from_dict` applies, exposed so a caller that intends a read-modify-WRITE can tell "defaults
because there is nothing there" from "defaults because we could not read it". The check belongs
in the store, beside the rule it mirrors, rather than being duplicated in `workspaces`.
`migrate_local` skips the save when a document exists that fails that check, and adopts the
workspace with the file untouched. Both ordinary cases still land the flag: a readable v1
document is re-saved with its own values, and a dataset-only workspace gets one written with
appendix-A defaults.

The accepted consequence, stated in the docstring: a workspace whose document is unreadable does
not get the flag set, so its cost toggle asks for a contract once. That is recoverable in a single
screen; a destroyed parameter set is not.

**4 (should-fix) — `MIN(last_clicked_at)` is lexicographic.** SQLite's `MIN` over TEXT is a
string comparison, which matches chronological order only for a fixed-width fixed-offset format.
`record_interest` writes `datetime.now(timezone.utc).isoformat()`, always `+00:00`, so the result
is correct for data this app writes — but the comments asserted "the earliest" as a general
property the code does not have. Softened the comments to state the assumption rather than making
telemetry ordering instant-based, which would cost a parse per row for a counter no user reads.

**5 (should-fix) — an overstated module comment.** `app/workspaces.py`'s module comment called
the derived interval count "an approximation"; `_data_facts` uses `max(resolutions)` without
`choose_grid`'s `covers(window)` filter, so a short auxiliary series drags the reported grid
coarser and the count can be off by a factor of several with no gaps and no irregularity. The
module comment now states the same thing `_data_facts`' own comment does. `app/db.py`'s
"any code path that opens the DB repairs a stale shape" now also names its cost (a
`PRAGMA table_info` on every connection, permanently).

**6 (minor) — `delete_data` left orphaned `series_meta` rows.** The delete was scoped through
`datasets`, but `series_meta` carries its own `workspace_id` and `PRAGMA foreign_keys` is off, so
the declared cascade never fires and a row whose parent is already gone survived. Not reachable
through the normal save paths; the delete is now `WHERE workspace_id = ?`, which is simpler and
complete.

**7 (minor) — a test that did not test what it said.**
`test_pricing_configured_defaults_when_absent` popped the flag from the block and then asserted
on unrelated fields. It now writes the flag-less document to disk and asserts
`is_pricing_configured()` is False.

**8 (minor) — atomicity note on `delete`.** Rows and files are removed in separate steps with
`ignore_errors=True`, so a crash in between leaves unreferenced `.npz` files with no route to
reclaim them, and a failed `rmtree` is silent. Chose to state the limit in the docstring rather
than tighten the behaviour: making it genuinely atomic needs a reclaim pass over orphaned
directories at startup, which is more machinery than a local single-user app's delete warrants,
and the failure mode is wasted disk rather than wrong results.

**9 (blocking) — the finding-1 fix silently removed rollback from every multi-statement write.**
Found by verification *after* the fix landed, not by either review and not by the test suite —
both were green with the regression in place. Recorded here because the miss is part of the
finding.

Setting `isolation_level=None` gave the migration the autocommit it needs, but that setting is a
property of the connection, so it applied to every consumer of `db.connect()` — including
`app/dataset.py`, which wraps it. Under the previous default (`isolation_level=""`) `sqlite3`
opened an implicit transaction before the first DML statement and `with conn:` committed on a
clean exit or **rolled back when an exception escaped the block**. Autocommit removed that
rollback while leaving the `with` blocks looking unchanged. Finding 1's own note — "every
existing use is a single statement or a single-statement upsert plus a read" — was wrong:
`dataset.save_dataset` and `dataset.upsert_series` are both multi-statement writes.

Two consequences were reproduced against the working tree, each comparing the new connection
against one with `isolation_level` restored to `""`:

  * `upsert_series` does `DELETE FROM series_meta … ` then `_insert_series_meta(…)` to put the
    replacement in. With an exception escaping between the two, the old connection left 1 series
    (rolled back) and the new one left 0 — the user's existing series silently lost. This is the
    sharp case: the visible damage is destruction of data the user already had, not the loss of
    the write that failed.
  * `save_dataset` inserts one `datasets` row then N `series_meta` rows. With an exception
    escaping, the old connection left 0 rows and the new one left 1 — a dataset row with missing
    or partial series beneath it.

Calibration, since it bounds what the fix can claim: an exception *caught inside* the `with`
block behaves identically before and after, because the block then exits cleanly and both spellings
commit the partial work. The regression is specifically about exceptions **escaping** the block.

Fix: keep autocommit — it is what makes the migration's explicit `BEGIN IMMEDIATE … COMMIT`
correct — and restore `with conn:` as a transaction by giving the connection an explicit
`__enter__`/`__exit__`. `app/db.py` grows a `_Connection` subclass, used as `sqlite3.connect`'s
`factory`, whose `__enter__` issues `BEGIN IMMEDIATE` and whose `__exit__` issues `COMMIT` or,
on an exception, `ROLLBACK`.

Three alternatives were weighed:

  * *Revert `isolation_level` to `""` and keep an explicit transaction only in the migration.*
    Rejected: the implicit-transaction machinery is exactly what made the migration non-atomic
    under finding 1, and the interaction is version-dependent.
  * *A separate `transaction(conn)` context manager that the multi-statement writers wrap their
    work in.* This is a clean shape and was the brief's suggestion, but it leaves `with conn:`
    meaning nothing while still *looking* like a transaction at every call site. The regression
    happened because the two diverged; a fix that keeps them diverged invites the next one. It
    also fixes only the sites someone remembers to convert.
  * *Wrap the writers in a helper AND leave `with conn:` inert.* Same objection, plus two ways to
    spell the same intent.

Choosing the subclass restores the semantics every `with db.connect()` / `with dataset.connect()`
site was already written against, so the audit below is about confirming each site is *correct*
under transactions rather than about converting sites.

Nesting is handled explicitly rather than by accident: SQLite errors on a nested `BEGIN`, and
`workspaces.delete` calls `delete_data`, which opens its own connection. `__enter__` keeps a
per-instance depth counter and only the outermost `with` on a given connection begins and ends
the transaction; an inner one is a no-op that joins the outer transaction. It also declines to
begin when the connection is already `in_transaction`, so the migration's explicit `BEGIN` is
never nested into.

Per-site audit of every `with db.connect()` / `with dataset.connect()` / `with _connect()` block
in `app/`. All now get a transaction (the semantics are the connection's), so the column records
whether one is *needed*:

  * `dataset.save_dataset` — **needed.** Insert + N inserts; the regression case.
  * `dataset.upsert_series` — **needed.** Delete + insert (+ conditional window update); the sharp
    regression case.
  * `workspaces.delete_data` — **needed.** Two deletes across `series_meta` and `datasets`. A
    partial delete is the orphan-row problem finding 6 was about, reachable here by interruption
    rather than by a bad query.
  * `workspaces.delete` — **needed.** Two deletes across `workspace_state` and `workspaces`, and it
    calls `delete_data` first. Note the file half stays non-atomic, as finding 8 records; the
    transaction covers the rows only.
  * `workspaces.migrate_local` — **not needed, kept.** The `with` block holds two reads only; the
    writes that follow (`create`, `simconfig_store.save`) are outside it and stay outside it. The
    read pair is now consistent, which is a small honest improvement, not the fix.
  * `db.record_interest` — **not needed for correctness, but now real.** A read-then-upsert. The
    docstring finding 1 corrected said the pair is *not* one transaction and the returned boolean
    is advisory; under `BEGIN IMMEDIATE` the pair now genuinely is one transaction, so the
    docstring was corrected again — in the other direction this time — to match the code.
  * `workspaces.list_summaries` — not needed. Reads only.
  * `db.interest_count`, `db.source_generation`, `dataset.load_latest`, `workspaces.get` — not
    needed. Single reads.
  * `db.bump_source_generation` — not needed. Upsert plus a read-back; the upsert is atomic on the
    primary key. Grouping them does make the returned value certain to be the one this call
    produced, which it was not before.
  * `workspaces.create`, `workspaces.rename`, `workspaces.touch` — not needed. Single statements.

Cost, stated plainly: every `with` block on these connections now takes SQLite's write lock up
front, including the read-only ones, and holds it for the block. For a local single-user app with
a handful of short blocks that is not a concern, but it is a real change in locking behaviour
rather than a free one. `BEGIN IMMEDIATE` rather than a deferred `BEGIN` is deliberate — it is
what makes concurrent writers queue on the 10 s timeout instead of failing partway through with
`SQLITE_BUSY` on upgrade.

Two things surfaced while implementing this that are worth recording, since neither was
anticipated when the fix was scoped.

*The first attempt at `_Connection` was wrong, and the nesting test is what caught it.* It tracked
ownership of the transaction in a single `_owns` boolean. The inner `__enter__` overwrites that
attribute, so the outer `__exit__` read the inner block's `False` and skipped its own `COMMIT` —
nested blocks silently discarded the whole outer transaction. Replaced with `_owned_depth`, which
records the nesting level that opened the transaction so only the matching `__exit__` closes it.
Worth stating plainly: the first spelling passed every pre-existing test, because nothing in the
suite nested two blocks on one connection until the new test did.

*The row-level guarantee does not extend to the `.npz` files, and `upsert_series` is where that
shows.* It calls `_save_frame` before opening the transaction, and `_frame_path` is deterministic
by name, so the array is overwritten in place before any SQL runs. A rollback restores the
`series_meta` row and cannot restore the file. The honest post-condition after a failed
`upsert_series` is therefore "the series is still there, still listed and still readable with its
original metadata", NOT "its values are unchanged" — the file holds the new array. That is a
strictly smaller loss than the regression (which removed the series outright) and the same
rows-versus-files split findings 6 and 8 already accept, so it is documented in `upsert_series`'
docstring and pinned by an assertion rather than fixed. Fixing it properly means writing to a temp
path and renaming on commit, plus a reclaim pass for the leftovers.

New tests: `tests/test_slot_load.py` gains a test that an exception escaping an `upsert_series`
leaves the pre-existing series present and readable — the user-visible property — and asserts the
`.npz` limit above so it stays a known one; plus a test that an exception escaping a `save_dataset`
leaves neither a `datasets` row nor a partial `series_meta` row. `tests/test_workspaces.py` gains
three: nested blocks commit once at the outermost, an exception escaping the outer block rolls back
work done in an inner one, and `workspaces.delete` failing partway leaves no half-deleted row set.
The finding-1 migration tests in `tests/test_feature_interest.py` are unchanged and still pass,
which is what pins that this fix did not reintroduce the non-atomic migration.

Suite: 818 passed → 823 passed, 2 skipped (the two skips are the Playwright and live-HA tests, as
before).

New tests: `tests/test_feature_interest.py` gains a leftover-scratch-table resume test and a
concurrent-open test (eight threads through a `threading.Barrier` against one temp data dir,
asserting no errors and exactly one collapsed row). `tests/test_workspaces.py` gains a test that
`migrate_local` does not clear a set flag, and one that it does not overwrite a future-version
document.

**10 (minor) — `simulate_cost` dropped from `WorkspaceSummary`.** The summary carried a field no
card renders. §2′.2 shows the contract badge at full strength whether or not cost simulation is
on, so holding the flag beside the badge made conditioning on it the easy mistake rather than a
deliberate one. Removed, with the reason recorded on the dataclass. A screen that genuinely needs
it can load the config.

## Verification of the finished phase

Beyond the suite (823 passed, 2 skipped — `test_smoke.py` needs Playwright Chromium and
`test_ha_live.py` a live Home Assistant), three properties were checked directly rather than
argued:

- **`GET /` is byte-for-byte identical** before and after the phase, rendered against the
  developer's real `data/` directory (14 datasets, a populated `local` workspace). This is the
  phase's "no user-visible change" claim, measured rather than asserted.
- **The migration fixes hold** against the scripts that originally reproduced them: the
  leftover-scratch-table brick now connects cleanly, and the concurrent-open race that failed 4
  runs in 12 passed 20 of 20.
- **Transaction nesting is correct** on the real `delete` → `delete_data` path, including
  rollback propagating out through an inner block — the case the first attempt at finding 9's fix
  got wrong while still passing all 818 tests then in the suite.

## Current status

Phase 0 complete, with the ten findings above fixed. Phases 1+ not started.

Worth carrying forward: findings 1, 2 and 9 were each invisible to a green suite — they needed a
crash, a race, or a state only a later phase creates. Finding 9 was introduced *by* the fix for
finding 1 and was caught by post-fix verification, not by either review. For the remaining phases
that argues for continuing to probe the failure paths directly rather than reading a passing run
as evidence.
