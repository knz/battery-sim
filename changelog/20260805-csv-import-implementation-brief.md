# CSV import — implementation brief

> **Purpose:** the durable, self-contained spec of the implementation work. Written so that a
> fresh agent with no conversation context can pick up any step from this file plus the specs it
> cites. The orchestrator's context WILL be compacted; this file is the source of truth.
>
> **Companion:** [20260805-csv-import.md](20260805-csv-import.md) holds the decision record and
> the user's verbatim prompts. Read it for *why*; read this file for *what to build*.
>
> **Status marker:** each step below carries a `Status:` line. Update it as work lands.

## Ground rules for every step

1. **Read the cited spec sections before writing code.** They are authoritative and were written
   for exactly this work: `docs/specs/02-ux-wireframes.md` §"The CSV source",
   `docs/specs/05-data-formats.md` §4.2a, `docs/specs/08-architecture.md` §5.1
   (storage layout, `uploads` table, `CsvSource`), `docs/specs/15-data-quality-and-limits.md`
   §7.3 "Where these checks run on the CSV path", `docs/specs/16-validation-harness.md`
   fixtures 22 and 22a.
2. **Every source file gets a top-of-file explanatory comment** naming the main items it defines,
   per `AGENTS.md`. Update it when the file changes.
3. **Match surrounding style.** This codebase writes long, reasoned comments explaining *why*.
   Mirror that density; do not add terse one-liners or strip existing prose.
4. **`app/domain/` is pure — no I/O, no clock, no filesystem.** The parser goes there and must
   stay pure. Adapters (`app/sources/`, routes) do the I/O.
5. **i18n:** any user-facing string in a template needs `_()`. Source `label`/`blurb` strings live
   in `app/sources/*.py` where pybabel cannot see them, so they must be mirrored into
   `app/sample_data.py` `_SOURCE_STRINGS` with `_N(...)`. `tests/test_no_english_leakage.py`
   enforces this. Runtime JS strings go in the `drawer_i18n` dict in
   `app/templates/workspace_data.html` and are read via `t("key", "fallback")`.
6. **Do not commit** unless the user asks. Run the tests you touched.
7. **Run targeted tests, never the whole suite.** The full suite contains benchmarks and takes a
   long time; CI has targets for it. Each step runs its own new tests plus any directly-related
   existing ones, and reports the exact command and its output.

## The design in one paragraph

Uploading a CSV and mapping it to a data series are **two separate tasks**. A user uploads a
**wide** file once (timestamp column + one column per measurement); it persists server-side,
per workspace. Then, in each slot's source drawer, they pick "Upload CSV" and bind that slot to a
`(upload_id, column, unit)` triple. One file therefore feeds many slots. The timezone is asked
once, at upload, and the data is converted to UTC there and then.

## The format (authoritative: `05-data-formats.md` §4.2a)

```csv
Tijdstip,Verbruik_T1,Verbruik_T2,Teruglevering_T1,Zon
01-01-2025 00:00:00,0.412,0.000,0.000,0.0
01-01-2025 01:00:00,0.388,0.000,0.000,0.0
```

- **Row 1 required**, holds column names. Names are shown to the user, **never interpreted** —
  a column called `Verbruik_T1` is not thereby the `grid_import_t1` series.
- **Column 1** = timestamp, `DD-MM-YYYY HH:MM:SS`, 24-hour clock, **no offset**.
- **Columns 2..N** = values, `.` decimal separator, fractional supported. Empty cell = **gap, not
  zero**. At least one value column required.
- **No `unit` and no `kind` in the file.** Unit is a per-slot radio (`kWh` default, or `Wh`).
  Kind does not exist: every value column is a **per-interval amount** for the interval starting
  at its timestamp.

### The four decisions that shape the code

- **D-TZ** — the upload dialog asks **Amsterdam local time** (`Europe/Amsterdam`) or **UTC**, per
  file, and the file is converted to UTC **at upload**. Nothing downstream sees a naive
  timestamp. The label says "Amsterdam", not "the Netherlands", because the Caribbean Netherlands
  (Bonaire, Saba, Sint Eustatius) are on AST with no DST.
- **D-DST** — under Amsterdam, a timestamp in the repeated October 02:00–03:00 hour resolves to
  its **first (CEST)** occurrence, and those samples are **flagged** for the data-quality box.
  Deliberately NOT resolved by row order (first-of-pair = CEST, second = CET): that recovers the
  hour exactly for a well-formed chronological export but is silently wrong for a file with gaps
  across the boundary. UTC uploads raise no such flag.
- **D-KIND** — **per-interval values only.** A column whose values never decrease is a cumulative
  meter register and is **rejected on selection** with an explanation, never differenced. Known
  cost, accepted by the user: a Dutch P1 export of cumulative registers cannot be used this
  increment. `cumulative_to_delta` exists (`app/domain/ingest.py:101`) if that changes.
- **D-PRICE** — **energy slots only.** `price_spot` does NOT offer CSV; it keeps the
  Energy-Charts / ENTSO-E preset sources. No price units on this path.

## Key facts about the existing code (verified, with anchors)

- `SeriesFrame` (`app/domain/frames.py:56`) — the target representation. `index` is
  `np.datetime64[s]` **UTC interval starts**; `values` is float64 **kWh in the interval** for
  energy; `quality` is a per-sample `uint16` bitfield (`QualityFlags`, `frames.py:32`).
  `__post_init__` enforces equal lengths. `name` must be a `SERIES_SLOTS` name.
- `infer_resolution_s(index)` (`app/domain/ingest.py:79`) — modal spacing, `None` if no spacing
  covers more than half the gaps. **Reuse this**; do not reimplement.
- `cumulative_to_delta` (`app/domain/ingest.py:101`) — exists for the HA path. **Not used here**
  (D-KIND).
- `QualityFlags` (`frames.py:42-47`) currently defines OK, GAP_FILLED, RESET_CORRECTED,
  INTERPOLATED, RESAMPLED_DOWN, CLAMPED_NEGATIVE. **The DST-ambiguity flag is a new bit** —
  add it here (next free bit, `1 << 5`) and document it in that docstring.
- `DataSource` protocol (`app/sources/base.py:58`) — `descriptor` property, `available_for(slot)`,
  `load(slot, window)`. `SourceKind` is `browser_fetch | backend_load` (`base.py:38`) and
  **stays that way** — `CsvSource` is `backend_load`.
- `EnergyChartsSource.load` (`app/sources/energy_charts.py:110`) takes **keyword-only extras**
  beyond the protocol signature. That is the precedent for `CsvSource.load` needing the binding.
- Registry (`app/sources/registry.py:30`) — hand-written `ALL_SOURCES` list; `_BY_KEY` raises on
  duplicate keys at import.
- Slot source lists are computed **twice**: `app/data_view.py:224-227` (real) and
  `app/sample_data.py:74-91` `_sources_for` (empty state). Both call `registry.sources_for`.
- `app/dataset.py:188-201` — `_series_dir` / `_frame_path` show the per-workspace filesystem
  pattern **and the traversal guard** (`"/" in workspace_id or ...` → `ValueError`). Copy that
  guard for the uploads dir.
- `dataset.upsert_series(frame, source_key, window, *, workspace_id)` (`dataset.py:322`) — merges
  one series into the latest dataset. This is what a single-slot load uses.
- Ingest WS (`app/ingest_ws.py:1-58`) reifies a whole staged config at once: HA slots stream as
  `series`/`rows`, `backend_load` slots are declared by name+source+window and loaded
  server-side on `done`, then persisted as ONE dataset, all-or-nothing.
- `ha_fetch.js:624-631` discovers backend slots **by descriptor kind**, so a new `backend_load`
  source needs no JS change to be reified. But CSV **does** need JS for its drawer controls.
- `ha_fetch.js:948-978` `csvPendingOption()` — the disabled placeholder to replace.
  `ha_fetch.js:926-937` builds HA's `[ Configure… ]` button; `[ Upload… ]` mirrors it.
- `app/features.py:18-27` — the retirement rule: move the key to `RETIRED_KEYS`, **keep its
  title**, never rename or reuse a key.
- Existing tests to mirror: `tests/test_sources.py`, `tests/test_slot_load.py`,
  `tests/test_ingest.py`, `tests/test_ingest_ws.py`, `tests/test_workspace_data.py`.

---

## Step 1 — uploads storage

**Status:** done, reviewed. `app/uploads.py` + `tests/test_uploads.py` (49 tests). The table is
created on the shared connection like `dataset`'s; `create` / `get` / `list_for` / `delete` /
`path_for` / `read_text` / `delete_all_rows` are all workspace-scoped and reject traversal on BOTH
the workspace id and the (hex-validated) upload id, before any filesystem access.
`workspaces.delete` now also clears the `uploads` rows; `delete_data` deliberately does not (an
upload is nearer configuration than to a run — §2′.3). A review found and fixed three defects
(mkdir-before-id-validation, an unreachable file leaked on a bad argument, and a missing aware→UTC
conversion), each mutation-tested; `08-architecture.md` §5.1's box was amended to `columns_json`
with nullability marked. **Notes for step 3:** `create` does not parse and cannot reject, so the
route must parse first for "a rejected upload writes nothing" to hold; `MAX_UPLOAD_BYTES` is
declared here but enforced nowhere, and belongs at the edge before the content is read; and
`uploads.delete` does not clear slot bindings. **For step 5:** calling `uploads.create` inside an
open `dataset.connect()` transaction deadlocks on the write lock, as `db.bump_source_generation`
already does — pre-existing, but it constrains writing a binding and an upload as one operation.
See [20260805-csv-uploads-storage.md](20260805-csv-uploads-storage.md).

Add persistence for uploaded files. Two halves:

- **Table `uploads`** (see `08-architecture.md` §5.1 persistence box):
  `id, workspace_id, filename, tz, columns, rows, resolution_s, first_ts, last_ts, uploaded_at`.
  `filename` is the user's original name (for display only). `tz` is the zone they declared.
  `columns` is the parsed header (JSON list). `rows`/`resolution_s`/`first_ts`/`last_ts` are the
  parse summary the drawer and dialog display. Follow the workspace-keying and owner-scoping
  discipline every other table uses (`app/dataset.py:67-93`, and
  `changelog/20260804-owner-scoping.md` for the principal rules).
- **Files** at `<data_dir>/<workspace_id>/uploads/<upload_id>.csv`. The id is **app-assigned, not
  the user's filename** — two exports may share a name and a name is not an identity. Reuse the
  traversal guard from `dataset.py:188-191`.

Also: deleting a workspace must remove its uploads. Check how workspace deletion currently
handles `series/` (`app/workspaces.py`) and follow it.

**Done when:** rows can be created/listed/deleted per workspace, files land in the right place,
traversal is rejected, and workspace deletion cleans up.

## Step 2 — the pure parser (`app/domain/csv_wide.py`)

**Status:** done, reviewed, review defects fixed. `app/domain/csv_wide.py` +
`tests/test_csv_wide.py` (77 tests, full matrix); `QualityFlags.DST_AMBIGUOUS = 1 << 5` added and
documented in `docs/specs/07-internal-representation.md`. API for steps 3/4:
`parse_wide_csv(text, tz) -> WideCsv`, `summarise(wide) -> WideCsvSummary`,
`parse_and_summarise(text, tz)`, `parse_column_values(wide, column)`,
`column_frame(wide, column, series_name, unit) -> (SeriesFrame, warnings)`,
`CsvFormatError(code, message, row=None)`, `TZ_KEYS`, `UNIT_FACTORS`. Open items 1/2/4 decided
(March nonexistent → reject; register threshold = ≥12 finite samples AND non-decreasing AND
overall rise > 1e-6, so flat/constant columns are ordinary data; gaps = NaN + `GAP_FILLED`,
infinities rejected).

Known weakness Step 6 should carry into the UI: the register heuristic **rejects monotone
partial-day PV** (a measured false positive, not a theoretical one) and **accepts a register
spanning a meter reset**. Both are documented at the constants in `csv_wide.py` and pinned by
tests; mitigating the false positive needs drawer UI (an override, or a total-vs-window check).
Also note an October Amsterdam file's index behaviour, by design — see the module docstring.
**Corrected during step 4's review (2026-08-06), because the original wording here and in
`csv_wide.py`'s docstring was too broad:** a *chronological 24-row hourly* October file yields **no
duplicate** — its single `02:00` local row resolves to `00:00Z` and `01:00Z` is simply absent, a
missing UTC hour with 1 row flagged ambiguous. The **duplicate** index entry needs a genuine 25-hour
export that writes the repeated hour twice (2 rows flagged). Both shapes were run against the parser
rather than reasoned about. The parser's behaviour is unchanged and correct in both cases; only the
justification was wrong. `csv_wide.py`'s module docstring and
`changelog/20260805-csv-import-step2-parser.md` still carry the broad wording and should be amended
by whoever owns step 2. Details in `changelog/20260805-csv-import-step2-parser.md`.

**Depends on:** nothing (pure). Can be built first and in parallel.

A new pure module. No I/O, no clock — it takes text (or an iterable of lines) and returns data.

Required behaviour:

- **Header:** first row is column names. Reject a file with no header, fewer than 2 columns, or
  no data rows, naming what was expected and what was found.
- **Timestamps:** parse `DD-MM-YYYY HH:MM:SS` strictly (24-hour). Reject unparseable, naming the
  offending row number and its content. Apply the declared zone → UTC.
  - Under `Europe/Amsterdam`: the March gap hour (nonexistent local times) and the October
    repeated hour both need handling. October → **first/CEST occurrence + flag** (D-DST). Decide
    and document what a *nonexistent* March timestamp does — recommend rejecting it, since it
    cannot be a real local reading; state the choice in the module docstring either way.
  - Under `UTC`: direct, no ambiguity, no flag.
  - Use the stdlib `zoneinfo` (Python ≥3.9); check `pyproject.toml` for the floor.
- **Value columns:** parse float, `.` separator. Empty cell → **gap, not zero** (NaN + a gap
  quality flag; see how `cumulative_to_delta` flags gaps for the convention). Reject a
  non-numeric column naming the row.
- **Monotonicity rejection (D-KIND):** a column whose values never decrease across the file is a
  cumulative register → reject with an explanation. Be careful with the degenerate cases: an
  all-constant column (also non-decreasing) and a very short column. A flat-zero column is
  ordinary (an unused register), so the check needs a sensible threshold — decide it, document
  the reasoning, and cover it with tests.
- **Unit:** `kWh` (identity) or `Wh` (÷1000).
- **Resolution:** reuse `infer_resolution_s`.
- **Output:** a `SeriesFrame` for a requested `(column, series_name, unit)`, plus warnings in the
  shape the rest of the pipeline uses (see `energy_frame`'s `list[dict]` return,
  `ingest.py:174`).
- Also expose a **header/summary parse** that reads just enough for the upload dialog: column
  names, row count, inferred resolution, first/last timestamp.

Add the DST-ambiguity bit to `QualityFlags` (`frames.py`) and document it there.

**Done when:** unit-tested against all of: both zones; the October repeated hour; a March
nonexistent time; Wh and kWh; empty cells; a monotonic column; a flat column; an irregular-spacing
file; a malformed header; a bad timestamp; a non-numeric value.

## Step 3 — upload routes

**Status:** done, reviewed, review defects fixed. All three routes in `app/main.py` +
`tests/test_upload_routes.py` (48 tests). Statuses: 201 on upload, 200 on list and delete, **413**
over the cap, 400 bad input, 404 for a workspace the principal does not own. The size cap is enforced
at the edge by `_read_capped_body` — the raw
`Request` rather than an `UploadFile`, because a `File(...)` parameter makes Starlette parse the whole
body before the handler's first statement; Content-Length is refused up front and the stream read
aborts on the accumulated byte count. A review constructed attacks against it (lying header both
ways, chunked with no header, exactly-`limit`, garbage values) and the cap held on all of them. Both
`POST` and `DELETE` take `csrf.require_same_site` (the destroy-or-create line); the `GET` does not.

A round-2 review found and fixed **two 500s**, each mutation-tested: a CSV cell over the csv module's
128 KiB field limit raised bare `_csv.Error` (not a `CsvFormatError`, not even a `ValueError`) and a
client disconnecting mid-body raised `ClientDisconnect` — both now 400, the latter matching what a
stock `UploadFile` route answers for the identical request. It also found a size-cap test that
survived deleting the whole `Content-Length` check; the two 413 branches now carry distinguishable
messages and are pinned separately.

**DELETE is idempotent** (user decision, 2026-08-06): a second delete of the same id answers 200, not
404, so a double-click on `[ remove ]` is harmless and the route matches
`deps.get_optional_workspace`'s convention. Body is `{"deleted": "<id>", "existed": true|false}`.
Cross-OWNER isolation is untouched and now pinned directly — `deps.get_workspace` 404s a workspace the
principal does not own before the handler runs (mutation-tested). A same-owner cross-workspace id is
200-with-`existed: false` and the other workspace's row and file stay untouched; the store cannot
distinguish "never existed" from "exists elsewhere" through its public API by design, so a 404 for only
the foreign case was never available without an unscoped read. A malformed id is still 400.

**Step 6 must know:** (1) `detail` is `dict | str` — every 4xx these routes raise themselves carries
`{"code","message","row"}`, but python-multipart's own limit errors answer with a bare string before
the handler runs, so key off `detail.code` when it is a dict and fall back otherwise. (2) Use
`textContent`, never `innerHTML`, on any server `message` — parser messages quote the user's own
column names and cell values. (3) `columns[0]` (the timestamp) is NOT uniquified and may be empty or
duplicate a value column, so slice for the selector and send NAMES, never a searched index. (4) DELETE
never 404s, so a stale list entry cleans up silently; use `existed` if you want to tell the user their
list was out of date.

**Step 5 must know:** run the binding cascade **unconditionally**, not only when `existed` is true — a
delete that removed the row but crashed before clearing bindings leaves a stranded binding, and the
retry that fixes it is exactly the call where `existed` is false.

**Two things step 3 deliberately did NOT do:** the delete→binding cascade is a marked TODO naming
step 5, since no binding store exists and open item 3 is still open; and the `code` → translated
string table is deferred to **step 6**, following `drawer_i18n`'s existing
`ingest_rejected: _("Ingest rejected: %(reason)s")` shape (a translated envelope around an
untranslated server reason). `ambiguous_rows` and `timestamp_name` are returned by the POST but not
persisted (recomputable by re-parsing; the `uploads` table has no column for either), so the GET list
does not carry them — verified dialog-cosmetic only, since §7.3's reporting runs through step 4's
load path. Also recorded there and not fixed: the cap bounds the body, not peak memory — a 30 MiB
2000-column file peaks at 727 MB RSS (~19x), bounded in practice by localhost + same-site rather than
by the cap. See [20260805-csv-import-step3-routes.md](20260805-csv-import-step3-routes.md).
**Depends on:** steps 1, 2.

- `POST /w/{workspace_id}/data/uploads` — multipart upload. Parses via step 2, writes the file and
  the row, returns the parsed header + coverage summary for the dialog. **Enforce a size cap** and
  CSRF (`app/csrf.py`; note `changelog/20260804-owner-scoping.md` says CSRF coverage of
  `POST /w/{id}/params` was explicitly out of scope there — check what the current convention is
  before assuming).
- `GET /w/{workspace_id}/data/uploads` — list, for the dialog and the drawer's file selector.
- `DELETE /w/{workspace_id}/data/uploads/{upload_id}` — removes row + file, and **clears any slot
  binding that referenced it** (spec: the slot returns to "Choose source…").

A rejected upload must write nothing: no row, no file. Follow the existing error-status
conventions (`app/main.py:1427-1432`: 404 for unknown, 400 for bad input, 502 for load failure).

**Done when:** routes work, rejection is clean, deletion cascades to bindings, size cap holds.

## Step 4 — `CsvSource`

**Status:** done, reviewed, review defects fixed. `app/sources/csv_source.py` +
`tests/test_csv_source.py` (43 tests), registered last in `ALL_SOURCES`; descriptor key
`csv_upload`, kind `backend_load`. `available_for` gates on `SlotSpec.kind == "energy"` **minus
`power_grid`** — §4.1 gives that slot kind *power* (signed W) but `SeriesKind` has no third member,
so `series_vocab` records it as "energy"; §6.17 wants mean watts and this path has no watt unit, so
it is excluded by name. Both slot-list call sites go through `registry.sources_for` and needed no
edit. **The parser returns a whole-file frame, so the source slices to the half-open
`[start, end)` window itself** (`slice_to_window`, pure and directly tested); a window outside
coverage yields the intersection, empty if need be, never padded (§7.4), `resolution_s` is
re-inferred on the slice, and both fractional bounds round **up** (derived: for integer-second
samples `s >= start` ⟺ `s >= ceil(start)`, `s < end` ⟺ `s < ceil(end)`). `load` takes
`workspace_id=` and `binding=CsvBinding(upload_id, column, unit)` as keyword-only extras (the
`EnergyChartsSource` precedent; the protocol is unwidened) and raises `CsvBindingError` naming the
slot when they are absent — **which is what happens today: `app/main.py`'s `_load_backend_frame`
and `load_slot` both call `source.load(slot, win)` with no extras, so step 5 must thread both**, and
must also map `CsvBindingError` to 400 (it currently reaches the user as 502 via `load_slot`'s bare
`except Exception`). `load_with_warnings` is the second entry point returning `CSV_GAP_CELLS` /
`CSV_DST_AMBIGUOUS_HOUR` recounted against the *window*; step 5 should call it so §7.3's box names
only days the run covers. Blurb/label mirrored into `_SOURCE_STRINGS` **and** translated in both
catalogs (the roster template already serialises them into the drawer JSON, so they reach a Dutch
page now, not at step 6).

**Registering the source changed the drawer roster, which broke two indirect consumers** — both
fixed here, and both worth knowing about before touching `ALL_SOURCES` again: `tests/test_smoke.py`
selected a backend source by `[data-slot-sources*='backend_load']").first`, which stopped meaning
`price_spot` (now targeted by name), and `ha_fetch.js` appended the pending "Upload CSV" stub
unconditionally, so every energy slot showed the control twice. `renderSourceList` now filters
`csv_upload` out of the live list until step 6 builds its controls — **that filter is also what
stops a selected CSV radio from failing an entire all-or-nothing fetch** (bindingless
`backend_load` slot → `CsvBindingError` → `IngestError`), so do not lift it before step 5 threads
bindings. `tests/test_smoke.py::test_new_pending_controls_marked` pins the stub step 6 must delete.
See [20260805-csv-import-step4-source.md](20260805-csv-import-step4-source.md).

**Depends on:** steps 1, 2.

`app/sources/csv_source.py`, registered in `ALL_SOURCES`.

- `kind = "backend_load"`. **Rationale to preserve in the file comment:** the bytes originate in
  the browser, but they arrive in a *separate, earlier* upload step; by load time the file is
  ordinary server-side data. Nothing about the load needs the browser, which is what the kind
  means.
- `available_for(slot)` → **energy slots only**, not `price_spot` (D-PRICE). Check how
  `series_vocab.SlotSpec` expresses energy-vs-price and gate on that rather than name-matching.
- `load(slot, window)` reads the slot's binding — the one source whose load needs more than
  `(slot, window)`. Follow `EnergyChartsSource`'s keyword-only-extras precedent
  (`energy_charts.py:110`). Do not widen the `DataSource` protocol signature.
- Mirror `label`/`blurb` into `app/sample_data.py` `_SOURCE_STRINGS` with `_N(...)` or
  `test_no_english_leakage.py` will fail.

**Done when:** the source appears in every energy slot's drawer list and not in `price_spot`'s,
and `load` produces a correct `SeriesFrame` from a stored upload.

## Step 5 — persist the binding, and reify it on fetch

**Status:** not started — **HELD AT THE USER'S REQUEST, 2026-08-06.** Do not dispatch. The user
asked for a pause once steps 3 and 4 closed (they are the last open ones), before any Step 5 work
begins. This is a deliberate checkpoint, not a blocker: resume only on the user's explicit say-so.
**Depends on:** steps 1, 4.

### Inherited requirements from steps 3 and 4 — read before starting

These came out of the step-3/step-4 reviews and are not derivable from the sections below:

- Thread `workspace_id=` and `binding=` through **both** `app/main.py`'s `_load_backend_frame`
  (the WS reify path) and the `POST /w/{id}/data/slot/{slot}/load` endpoint. Both currently call
  `source.load(slot, win)` with no extras, so a CSV slot raises `CsvBindingError`.
- Call **`load_with_warnings`**, not `load`, or §7.3's quality box loses the CSV flags.
- Map `CsvBindingError` → **400**. It is currently swallowed by `load_slot`'s bare
  `except Exception` → 502, which contradicts the exception's own docstring.
- The binding's `column` must store the **uniquified** name `csv_wide` reports (`"A (2)"`,
  `"Column 4"`), never a raw header cell, or it will not resolve.
- Honour **D-SEQ** above: sequence the upload write and the binding write, never nest them.
- `ha_fetch.js` currently **filters `csv_upload` out of the live radio list** — a deliberate guard,
  because a bindingless `backend_load` message fails the whole all-or-nothing fetch, HA slots
  included. Do NOT lift that filter until both call sites are threaded.
- Step 3 left a `**TODO (step 5)**` in `delete_upload`'s docstring: after `uploads.delete`
  succeeds, clear every binding of that workspace whose `upload_id` matches, as a separate write.
  Until then a slot bound to a deleted upload fails at load time rather than delete time.

The binding `(upload_id, column, unit)` is per-slot **configuration**, not data, so it belongs
with the slot's stored source choice (`08-architecture.md` says `params`; verify against how
`dataset.series_sources` and the simconfig store actually divide responsibility —
`app/simconfig_store.py`, `app/dataset.py:96-113`).

Then carry it into the ingest WS reify path (`app/ingest_ws.py`, and the `done` handler at
`app/main.py:1199-1222`) so a fetch loads CSV slots server-side alongside HA and backend slots,
into the same dataset, all-or-nothing. Note `ha_fetch.js:624-631` already stages `backend_load`
slots by kind — confirm whether the existing `backend_load` WS message carries enough for CSV or
needs the binding added.

### D-SEQ — do not nest the two writes; sequence them

**Decided by the user, 2026-08-05.** Calling `uploads.create` from inside an open
`dataset.connect()` transaction fails with `database is locked`. This is **pre-existing
cross-connection behaviour, not introduced by the CSV work** — `db.bump_source_generation` fails
identically inside a `dataset.connect()` block. The database uses SQLite's default rollback
journal (there is no `journal_mode` pragma anywhere in `app/`), but WAL would **not** help here:
the conflict is writer-vs-writer, and SQLite allows exactly one writer at a time under WAL too,
so a second `BEGIN IMMEDIATE` (`app/db.py:153`) would still wait out `db._TIMEOUT_S` and still
raise. Do not reach for a pragma to fix this.

So: **sequence the two writes — upload write first, close, then the binding write.** Do not pass
an open connection down into the other module to make them one transaction. The rejected
alternative was exactly that (a shared-connection variant of both writes), which buys atomicity
at the cost of changing the connection signature of code that currently works.

The accepted consequence: there is a window in which an upload row exists with no binding
referencing it. That is tolerable because it is already the design — uploading and mapping are
two separate user actions (see "The design in one paragraph"), so an unbound upload is a normal
resting state, not a torn write. An orphaned upload is visible in the file selector and the user
can delete it; nothing downstream treats "upload without binding" as an error.

**Done when:** a fetch with a CSV-bound slot persists that series with `source_type` recording
provenance, and survives a reload.

## Step 6 — drawer UI

**Status:** not started. **Depends on:** steps 3, 4, 5.

In `app/static/ha_fetch.js` and `app/templates/workspace_data.html`:

- Replace `csvPendingOption()` (`ha_fetch.js:948`) with a real radio carrying an
  `[ Upload… ]` button, mirroring HA's `[ Configure… ]` (`ha_fetch.js:926-937`).
- **Upload dialog** — a new `<dialog>` in `workspace_data.html` beside `#ha-config-dialog`.
  Contents per `02-ux-wireframes.md` §"The upload dialog": intro text, the four format bullets,
  the **Amsterdam local time | UTC** radio, a file chooser, and the list of already-uploaded
  files with `[ remove ]`.
- **Per-slot controls** under the radio, shown only while it is selected: **File** select,
  **Column** select (populated from the chosen file's header), **Unit** radio (kWh default | Wh).
- Staged into the drawer's `draft` (`ha_fetch.js` `onSelectSource`/`updateConfirmEnabled`);
  Confirm enabled once file+column are chosen. **Uploads survive Cancel** (they are a side effect
  on shared state, like a tested HA connection); the *binding* does not.
- Row label shows `Upload CSV · <file> · <column>`.
- All new user-facing strings: `_()` in the template, `drawer_i18n` + `t()` in JS.

**Done when:** the flow works end-to-end in the browser and the smoke tests pass.

## Step 7 — retire the pending key

**Status:** not started. **Depends on:** step 6.

Per `app/features.py:18-27`: move `data_source_csv` from `FEATURE_KEYS` to `RETIRED_KEYS`,
**keep** its `FEATURE_TITLES` entry (issues already filed under it must stay readable), never
rename it. Remove the now-dead pending markup and the `data-feature-key` wiring. Update the
"Currently pending" table in `docs/specs/implementation-progress.md` (`:94`).

## Step 8 — tests

**Status:** not started. **Runs alongside every step, not after.**

- **Parser** (step 2) — the full matrix listed there.
- **Routes** (step 3) — happy path, malformed rejection writes nothing, size cap, deletion
  cascade, cross-workspace isolation.
- **Source** (step 4) — mirror `tests/test_sources.py` and `tests/test_slot_load.py`: appears for
  energy slots, absent for `price_spot`, `load` output correct.
- **Template/UI** (step 6) — mirror `tests/test_workspace_data.py`; the Playwright smoke tests DO
  run (see the test-suite memory), so the drawer flow can be covered there.
- **Harness fixtures** — implement **22** (two failure points, plus reuse: two slots bound to two
  columns of the same file; rebinding; deletion clearing a binding) and **22a** (same file
  uploaded as Amsterdam vs UTC differs by the offset; October file flags the ambiguous hour; UTC
  file does not) from `docs/specs/16-validation-harness.md`.
- Check `tests/test_no_english_leakage.py` and `tests/test_i18n.py` pass after any string change.

## Open items deliberately left to the implementer

Named here so they are not mistaken for oversights:

1. **Nonexistent March timestamps** under Amsterdam (the spring-forward gap). Recommend
   rejecting; the spec does not say. Document whichever way it goes.
2. **The monotonicity threshold** for register rejection — a flat-zero column is non-decreasing
   but perfectly ordinary. Needs a judgement call, documented and tested.
3. **Whether the binding lives in `params` or beside `series_sources`.** The architecture spec
   says `params`; confirm against the code before following it.
4. **Gap representation** for empty cells — NaN plus which quality flag. Follow whatever
   `cumulative_to_delta` established so the two ingest paths agree.
