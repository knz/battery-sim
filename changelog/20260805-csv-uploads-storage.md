# CSV import — step 1: uploads storage

> **Scope:** step 1 only of the plan in
> [20260805-csv-import-implementation-brief.md](20260805-csv-import-implementation-brief.md).
> That file is the source of truth for the whole feature; this one records the step-1 build.

## 1. Task specification

Add persistence for uploaded wide CSV files (specs §4.2a), as the brief's step 1 describes:

- an `uploads` table — `id, workspace_id, filename, tz, columns, rows, resolution_s, first_ts,
  last_ts, uploaded_at` — workspace-keyed, following the owner-scoping discipline of
  `changelog/20260804-owner-scoping.md` (option C: `get_principal()` hard-coded to `"local"`,
  ownership carried and checked rather than assumed);
- files at `<data_dir>/<workspace_id>/uploads/<upload_id>.csv`, with the id **app-assigned** and
  the traversal guard copied from `dataset._series_dir`;
- create / read / list / delete, plus cleanup on workspace deletion;
- unit tests.

Explicitly **out of scope** for this step: HTTP routes (step 3), the pure parser (step 2, a
concurrent agent owns `app/domain/csv_wide.py`), the source registry (step 4), any JS.

### Provenance of the `docs/specs/` edit

`docs/specs/AGENTS.md` asks that the human user's original prompts be recorded whenever `specs/` is
touched. This step's one spec edit — §5.1's persistence box, see §5 below — has **no verbatim user
prompt behind it**, and that is worth stating rather than leaving blank. The work was directed by an
orchestrating agent from `20260805-csv-import-implementation-brief.md`, and the spec amendment was
raised by a reviewing agent noting that the box's column name no longer matched the code. The
user's own prompts for the CSV-import feature as a whole are recorded verbatim in
[20260805-csv-import.md](20260805-csv-import.md), which is the decision record this brief cites.

## 2. High-level decisions

### D1 — a new module `app/uploads.py`, not more of `app/dataset.py`

`dataset.py` is about datasets: SeriesFrames, their `.npz` arrays and the `datasets` /
`series_meta` metadata that describes a *loaded run*. An upload is not a run — it is a file a
user parked, which may feed many slots and many fetches, or none. Keeping it in its own module
matches how `simconfig_store.py` sits beside `dataset.py` for the other non-dataset per-workspace
state, and keeps `dataset.py`'s module comment about one subject.

### D2 — the schema goes on the shared connection, migrated the way `dataset.py` migrates

`uploads` is created with `CREATE TABLE IF NOT EXISTS` on `db.connect()`, exactly as
`dataset._connect` layers its two tables on the same file. There is no added-columns migration
list yet, because the table has never shipped: nothing on any installation has an older shape to
grow. The hook for one (`_migrate`) is deliberately **not** pre-created — an empty migration list
is a claim that a migration mechanism was needed, and `dataset._SERIES_META_ADDED_COLUMNS` is
right there to copy when the first column is actually added.

### D3 — the id is a uuid4 hex, and the filename is display-only

Per the brief and `08-architecture.md` §5.1: two exports may share a name, and a name is not an
identity. The stored path is derived from the id alone, and the id is additionally validated as
hex before it ever touches a path — so a caller passing a user-supplied string cannot escape the
uploads directory even if the id came from somewhere untrusted. The user's filename is stored as
a column for display and never used to build a path.

### D4 — `columns` is stored as a JSON list, mirroring `datasets.warnings_json`

The header is a list of strings whose length varies and which nothing queries across rows. A JSON
text column is the shape `datasets.warnings_json` already established for exactly that; a
`upload_columns` child table would buy an ordering column and a join for no query anyone makes.
The public API exposes it as `list[str]`, so the encoding stays inside this module.

### D5 — timestamps stored as ISO 8601 text, read back as tz-aware UTC

`first_ts` / `last_ts` / `uploaded_at` follow `datasets.window_start` and `workspaces.created_at`:
ISO text in the column, parsed on read with the same naive-is-UTC rule (`dataset._as_utc`,
`workspaces._parse`). Under D-TZ the parser has already converted to UTC at upload, so a naive
value can only come from an older or hand-edited row; reading it as UTC is the pipeline's standing
convention (§4.4) rather than a new one.

### D6 — `create` writes the file first, then the row

The same ordering argument `dataset.upsert_series` makes: the file write cannot be rolled back by
SQLite, so it goes first and the row — the only thing any reader consults — goes second. A crash
between them leaves an unreferenced file (wasted disk, unreachable, the residue
`workspaces.delete` already tolerates), never a row pointing at a file that is not there.
`delete` reverses it for the mirror-image reason: the row goes first, so a crash leaves a file
nothing references rather than a row promising a file that has been removed.

Note that this shifts step 3's obligation: the brief says a rejected upload must write *nothing*,
which means the route must parse **before** calling `create` at all. `create` does not parse and
cannot reject.

### D7 — `delete_data` does not touch uploads; `delete` does

§2′.3 splits the two: "clear the data" removes the measurements of a run, keeping the
configuration. An upload is closer to configuration than to a run — it is an input the user
supplied once that many runs draw on — and `delete_data`'s dialog copy promises the workspace
survives "with its configuration intact". Silently discarding uploaded files there would make a
re-upload necessary after an operation the user was told was non-destructive to their setup.
Deleting the whole workspace removes everything, uploads included, and already did so for the
files via `rmtree` of the workspace directory; what step 1 adds is the **row** delete, which
`workspaces.delete` was not doing (rows keyed by the workspace id must go with it, §5.5).

## 3. Files modified

| File | Change |
|---|---|
| `changelog/20260805-csv-uploads-storage.md` | new — this file |
| `app/uploads.py` | new — the `uploads` table and the per-workspace file store |
| `app/workspaces.py` | `delete` also removes the workspace's `uploads` rows; module comment |
| `tests/test_uploads.py` | new — unit tests for the store |
| `docs/specs/08-architecture.md` | §5.1 persistence box: `columns_json`, and nullability marked |

## 4. Obstacles and solutions

- *Two agents editing the brief's `Status:` lines concurrently* — re-read the file immediately
  before the single targeted edit, per the orchestrator's instruction.
- *`list_for` / `delete_all_rows` touch only SQLite, so routing them through `_uploads_dir` for the
  traversal guard would have created a directory as a side effect of a read* — split the check into
  `_check_workspace_id`, applied by every public function.

## 5. Review round — three defects found and fixed

A reviewer went over the first cut and found three genuine defects, all confirmed by running code.
All three are fixed, and each fix was **mutation-tested**: the code was reverted to the defective
spelling and the new test confirmed to fail, so the tests are discriminating rather than merely
green.

### R1 — `path_for(create_dir=True)` mkdir'd before validating the upload id

`_uploads_dir(...) / f"{_check_upload_id(upload_id)}.csv"` evaluates its LEFT operand first, so a
bad upload id raised only after the workspace's `uploads/` directory had been created. Low impact
— a stray empty directory, and `create` generates its own ids — but `path_for`'s docstring claimed
both ids were validated before the filesystem was touched, and a guard whose stated ordering is
wrong is worse than one that claims nothing. Split into two statements.

The test that should have caught it, `test_traversal_is_rejected_before_any_directory_is_created`,
passed only a bad *workspace* id and stayed green with the defect present. Renamed to say what it
actually covers, and a second test added for the upload-id case.

### R2 — a bad argument to `create` leaked an unreachable file

The module comment argued that an unreferenced file is tolerable residue because a crash between
two stores cannot be prevented. That reasoning is sound for a crash and was silently covering
something else: `int(rows)`, `json.dumps(...)` and `.isoformat()` all ran inside the INSERT's
argument tuple, i.e. **after** `path.write_text`. So `rows="not-an-int"`, a non-JSON-serialisable
column name, or a string `first_ts` each raised with the file already on disk — and because `create`
never returns, the caller never learned the generated id, making the residue unreachable *and*
undeletable. From a mistake the caller could have been told about before any write.

Fixed by hoisting every coercion above the write, rather than by wrapping the insert in
`try/except` + `unlink`. Both work; hoisting is preferred because it makes the property structural
(nothing after the write can raise on argument shape) instead of dependent on an exception handler
staying correct as the function grows. The crash-residue argument in the module comment now says
explicitly that it covers a crash and is not a licence for ordinary errors.

### R3 — `_parse_ts` did not convert an offset-bearing timestamp to UTC

`dt.replace(tzinfo=utc) if dt.tzinfo is None else dt` handled the naive branch only, where
`dataset._as_utc` — named in the docstring as the rule being followed — also does
`.astimezone(timezone.utc)` on the aware branch. A `first_ts` at `+02:00` read back at `+02:00`.

Latent rather than immediately wrong, and that is exactly why it survived: aware comparison is by
instant, so every existing assertion agreed. What breaks is wall-clock — `.hour`, `.replace(...)`
and anything that formats — where the field is documented as UTC. Fixed before step 3 codes
against it. Factored into `_to_utc`, which `create` now also applies to its RETURN value, so the
create-path and read-path results are indistinguishable.

### Spec text

`docs/specs/08-architecture.md` §5.1's persistence box still read `columns` and did not mark
nullability, so the code would read as drifted. Amended. The reviewer also correctly pointed out
that `columns` is **not** a SQLite keyword and is accepted unquoted — that ground is withdrawn from
the naming justification, which stands on "a bare `columns` reads as a count" alone.

### Recorded so it is not re-litigated

- The lax workspace-name cases (`..%2f..%2f`, unicode dot lookalikes, `...`) all normalise to
  literal single-segment names inside the data dir. This is identical laxity to the existing
  `dataset._series_dir`, `simconfig_store._workspace_dir` and `workspaces._workspace_dir`, i.e. a
  faithful copy rather than a regression. Tightening belongs in one shared helper across all four
  call sites; doing it in this module alone would leave three unchanged and add a fourth spelling.
- Owner scoping by `workspace_id` alone is the option-C pattern: no table but `workspaces` carries
  `owner_id`, and a workspace-scoped route has already passed `deps.get_workspace`'s `_authorize`.
- `uploads.create` inside an open `dataset.connect()` transaction fails with "database is locked".
  `db.bump_source_generation` fails identically in the same position, so this is pre-existing
  cross-connection architecture, not something introduced here. Noted in the module comment as a
  pointer for step 5, which may want a binding and an upload in one logical operation.

## 6. Current status

**Complete** for step 1's scope, review round included. 49 tests in `tests/test_uploads.py`, all
passing; 85 with `tests/test_workspaces.py` alongside.

Two things step 3 must carry, both restated in the code:

1. `create` does not parse and cannot reject, so the route parses FIRST for "a rejected upload
   writes nothing" to hold.
2. `MAX_UPLOAD_BYTES` is declared here and enforced nowhere. The check belongs at the edge, before
   the content is read into memory — by the time `create` runs it is too late to have protected
   anything. There is currently zero enforcement anywhere in the app.

And one for step 5: `uploads.delete` does not clear slot bindings. The delete→binding cascade is
the route's job.
