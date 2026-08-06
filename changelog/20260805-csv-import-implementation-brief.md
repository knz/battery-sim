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
- `ha_fetch.js`'s `stagedBackendSlots()` discovers backend slots **by descriptor kind**, so a new
  `backend_load` source needs no JS change to be reified. But CSV **does** need JS for its drawer
  controls.
- `ha_fetch.js`'s `csvPendingOption()` — the disabled placeholder to replace (**deleted by step 6**;
  the reference is historical). `renderSourceList`'s HA branch builds the `[ Configure… ]` button;
  `[ Upload… ]` mirrors it.

  *Line numbers in this section were written against the pre-step-6 file and are ~500 lines stale;
  everything above is cited by NAME instead, which is what step 6's review asked for. Search by
  symbol, not by line.*
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

**Status:** done, reviewed, review defects fixed (2026-08-06). Storage is **candidate E**: the per-slot
entry in `localStorage ha.slots.<workspace>` grew from `{source, statId}` to
`{source, statId, uploadId, column, unit}`, and **no server-side binding store was built** — no
table, no `series_meta` column, no `simconfig.json` key. The binding travels on the ingest WS
`backend_load` message as `binding: {upload_id, column, unit}`; `app/ingest_ws.py` shape-checks it
and `app/main.py` validates its existence via `uploads.get(workspace_id, upload_id)`, which is the
security boundary because the id is client-supplied. `_load_backend_frame` now returns
`(frame, warnings)` and both it and `load_slot` call `load_with_warnings`, passing the extras **only**
for the `csv_upload` key (a blanket pass raises `TypeError` in `EnergyChartsSource.load`).
`CsvBindingError` → 400 on the endpoint, above the bare `except Exception`. `PENDING_SOURCE_KEYS`
is **unchanged** — the radio is still hidden, so this is plumbing behind the existing guard.
New/changed tests: `tests/test_csv_binding_reify.py` (23), `tests/test_slot_load.py` (+12),
`tests/test_ingest_ws.py` (+13), `tests/test_smoke.py` (+4, mutation-verified).

**The review (2026-08-06) found six defects; all are fixed** and none reopened D-BIND. One was
behavioural and step 6 must not undo it: the completeness gate on a `csv_upload` store entry (a file
AND a column; `unit` has a default and is excluded) now also runs on the READ side —
`usableStoreEntry` in the seed loop — because `saveSlotStore` only governs what this build writes,
and a hand-edited or older-build store could otherwise restore half a binding, stage it, and fail
the entire all-or-nothing fetch. An unusable entry is dropped whole, so the slot falls back to the
server's committed source rather than sitting in a CSV-configured state the user cannot correct.
**Step 6's Confirm gate is therefore the third copy of that same rule, not the first.** The other
five: a malformed `upload_id` and a non-dict `binding` now answer 400 / "not fully configured"
instead of 502, translated at the two places the binding is interpreted (`CsvSource` and
`_csv_binding`) — `uploads._check_upload_id`'s traversal whitelist is untouched and must stay so;
and four comments that contradicted D-BIND or the code were corrected in `app/uploads.py` and
`app/static/ha_fetch.js`. Details, rationales and the mutation runs are in
[20260806-csv-import-step5-binding.md](20260806-csv-import-step5-binding.md).
**Depends on:** steps 1, 4.

### Inherited requirements from steps 3 and 4 — status after the step-5 work

These came out of the step-3/step-4 reviews and are not derivable from the sections below. Each is
marked with what became of it, since a later reader will otherwise re-derive it:

- **DONE** — Thread `workspace_id=` and `binding=` through **both** `app/main.py`'s
  `_load_backend_frame` (the WS reify path) and the `POST /w/{id}/data/slot/{slot}/load` endpoint.
  Threaded via the `_CSV_SOURCE_KEY` condition, not unconditionally: the `DataSource` protocol is
  narrow and `EnergyChartsSource.load`'s own extras are `opener`/`now`, so passing `binding=` to it
  raises `TypeError`. Pinned by
  `test_load_endpoint_energy_charts_still_takes_no_binding_extras` and
  `test_a_non_csv_backend_slot_still_needs_no_binding`.
- **DONE** — Call **`load_with_warnings`**, not `load`. `_load_backend_frame`'s return type changed
  to `(frame, warnings)` for it, and the WS handler stamps each warning with the series name and
  extends the dataset's list.
- **DONE** — Map `CsvBindingError` → **400**, ordered above the bare `except Exception` (it is a
  `ValueError`, so order is load-bearing).
- **CARRIED TO STEP 6** — The binding's `column` must be the **uniquified** name `csv_wide` reports
  (`"A (2)"`, `"Column 4"`), never a raw header cell. Step 5 stores and transports whatever string it
  is given and resolves it by name, so the requirement now lands entirely on the drawer's column
  selector, which is what will produce the string. `app/main.py`'s `_upload_json` docstring already
  records the trap (`columns[0]` is not uniquified; send names, never a searched index).
- **DONE, differently** — Honour **D-SEQ**. Nothing needed sequencing, because no second write was
  added: under candidate E the binding is not server state. The `uploads.get` inside the load runs to
  completion before `save_dataset`/`upsert_series` opens a transaction, so the two writers never
  nest. `_load_backend_frame`'s docstring records that anyone moving the load inside a
  `dataset.connect()` block would deadlock.
- **UNCHANGED, deliberately** — `ha_fetch.js` still filters `csv_upload` out of the live radio list.
  Step 5 was a precondition for lifting it, not the whole of it: step 6 must also gate Confirm on a
  complete binding, or a completed-looking drawer still stages an empty one.
- **MOOT under E** — the `delete_upload` cascade. There is no server-side binding to clear; the
  `TODO (step 5)` marker was replaced by a note recording why. The rule it carried is kept on record
  in D-BIND below in case the binding ever moves server-side.

### Rebase onto master `4a4fa10`, 2026-08-06 — what changed underneath

Steps 1–4 were rebased onto master after PRs #7/#8 landed twelve commits (results-screen defaults,
charge policy P1, `simulate_cost` on by default, the HA entity preselect fix, Tailwind glob
narrowing). Three files conflicted; the rest auto-merged. What a step-5/6 agent needs to know:

- **`ha_fetch.js` gained `defaultSourceFor`** (master's fix for a fresh slot leaving `draft.source`
  null, so no radio matched and the entity `<select>` never populated). `renderSourceList` now
  stages a default source before building the radios. The merge puts our `csv_upload` filter
  **before** that staging deliberately, so a pending key can never be staged as the default.
  Today every CSV-capable slot also offers Home Assistant, which sorts first, so the ordering is a
  guard rather than a fix for observed behaviour — but step 6 removes the filter, and step 6 must
  keep `defaultSourceFor` in mind: once `csv_upload` is a live radio it becomes stageable, and on a
  slot where it is the only option it would be staged with no `(upload, column, unit)` binding yet.
  Confirm must stay disabled until the binding is complete.
- **The two `.mo` catalogs conflicted** (binary, unmergeable) and were regenerated with
  `uv run pybabel compile -d app/locales -D messages` from the auto-merged `.po` files. Both sides'
  strings survived. Regenerate rather than resolve these on any future rebase.
- **Step 5's call sites are untouched by the rebase.** `_load_backend_frame(slot_name, source_key,
  window)` still takes no workspace and still calls `source.load(slot, win)`; `load_slot` still has
  the bare `except Exception`. Every requirement listed above stands as written.
- **`tests/test_smoke.py` auto-merged** and gained master's two preselect tests, which drive the
  hand-merged `renderSourceList`. They pass — see the verification below.

### D-BIND — where the binding lives, and how it travels (decided by the user, 2026-08-06)

The brief previously left this open ("belongs with the slot's stored source choice… verify against
how `dataset.series_sources` and the simconfig store actually divide responsibility"). It was
investigated and **decided**. The investigation findings, because they are the reason:

- **The server persists NO per-slot source choice today.** There are exactly five tables
  (`workspace_state`, `workspaces` in `app/db.py:78-82`; `datasets`, `series_meta` in
  `app/dataset.py:68-79`; `uploads` in `app/uploads.py:109`) and none holds a slot's chosen source.
  The slot source lives only in browser `localStorage` (`ha.slots.<workspace_id>`); the server
  learns it per-fetch from the WS message. So there was no existing home to add a field to.
- **`dataset.series_sources` is `dict[str, str]`** (`app/dataset.py:113`) — a bare source key per
  series, restored with the frames. It is provenance (what *was* loaded), not configuration.
- **`simconfig_store` is the wrong home and says so itself.** It is one JSON document of *run
  parameters* per workspace, and its module comment argues at length against adding anything that
  is not a parameter of a run ("It is not the home of … as a class… none generalises to a fourth
  without the same argument being made again"). A data-source binding is not a run parameter.
- **`series_meta.stat_id` is the precedent.** `app/dataset.py:129-131` already stores the HA
  statistic id per series "so a fetched HA slot can render its entity after a reload", surfaced to
  the roster as `row.stat_id` and read back by the drawer via `data-slot-stat-id`
  (`app/templates/_data_roster.html:114-128`). A CSV binding is the same kind of thing.

**Decision 1 — storage: RETRACTED AND REOPENED, 2026-08-06.** An earlier revision of this section
recorded "extend `series_meta`, exactly like `stat_id`". **That was wrong and must not be
implemented.** It was proposed on the strength of the `stat_id` precedent before `series_meta`'s
lifecycle was checked. Verified against the code, `series_meta` fails two requirements outright:

- **A row exists only for a series that already has data.** `_insert_series_meta`
  (`app/dataset.py:232`) is reached only from `save_dataset` / `upsert_series`, both of which
  persist frames. There is no row to hold a binding for a slot the user has *bound but not yet
  fetched* — which is precisely the state that has to survive, because the binding is what the
  next fetch reifies.
- **Each fetch orphans the last one's bindings.** `save_dataset` does `INSERT INTO datasets` per
  fetch (`app/dataset.py:298-300`) and `load_latest` reads only the newest row
  (`ORDER BY id DESC LIMIT 1`, `app/dataset.py:517`). `workspaces.delete_data` deletes every
  `series_meta` row for the workspace (`app/workspaces.py:452`) and its docstring already states
  that a fetched slot's source mapping does not survive.

**The `stat_id` precedent is misleading, and that is the general lesson.** `source_type` and
`stat_id` record *data that exists* (provenance — what was fetched). A binding records *data the
user intends to load* (configuration). They have the same shape and opposite lifecycles; do not
reason from one to the other.

**Decision 1, as actually made (user, 2026-08-06): candidate E — `localStorage`, extending the
existing pre-fetch slot store.** See "### D-BIND candidates" below for E and the two rejected
server-side alternatives (B: `retained.slot_bindings` in `simconfig.json`; D: a new `slot_bindings`
table). E was chosen because the **"two things carry a source choice across a reload"** list in
`app/static/ha_fetch.js`'s file header (find it by that phrase, not by line number — step 6 moved it
by ~500 lines) already documents pre-fetch
customizations as a category with a home and a reconciliation rule, and a CSV binding is one; it
needs no new table, no new document key, no delete cascade, and no new architectural category.

**What this changes about Step 5's scope — read carefully, it is smaller and differently shaped
than the section below was originally written to describe:**

- **There is NO server-side binding storage to build.** No new table, no `series_meta` columns, no
  `simconfig.json` key. Any earlier text in this file implying otherwise is superseded.
- **The binding is a per-slot `localStorage` field** beside `statId` in
  `ha.slots.<workspace_id>` → `slots[<slot>] = {source, statId, uploadId, column, unit}`, and it
  inherits the existing `source_generation` reconciliation with no change to that mechanism.
- **The WS message is therefore the only path the binding takes to the server** (Decision 2), which
  makes server-side validation of `upload_id` load-bearing rather than defence in depth: the server
  receives an id from the client and must check it against `uploads.get(workspace_id, upload_id)`.
- **No delete cascade is needed in `delete_upload`.** A deleted upload leaves a stale local entry
  that fails validation at the next fetch. Remove the `TODO (step 5)` marker in `delete_upload`'s
  docstring and replace it with a short note recording *why* there is nothing to cascade, so a
  later reader does not mistake the absence for an oversight. The "clear bindings unconditionally,
  not gated on `existed`" requirement in "Inherited requirements" is **moot under E** — it applied
  to a server-side store. Keep the reasoning on record; it will matter if the binding ever moves
  server-side.
- **Step 6 gains an obligation:** when the drawer lists uploads, it should drop local entries whose
  upload no longer exists, so a stale binding surfaces in the drawer rather than only at fetch time.

**Decision 2 — transport: carry the binding in the WS `backend_load` message.** Confirmed by
reading the code as it then stood: `stagedBackendSlots()` in `app/static/ha_fetch.js` sent only
`{name, source}`, so it had no room for a binding and had to be extended (step 5 did; the line
numbers this once cited are stale — search for the function). The message gains a
`binding: {upload_id, column, unit}` object for CSV slots:

```json
{"type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
 "binding": {"upload_id": "…", "column": "Verbruik_T1", "unit": "kWh"},
 "window": {"start": "<iso>", "end": "<iso>"}}
```

This keeps the drawer a **pure staging surface** — Confirm still writes nothing to the server,
matching how an HA slot carries its `statId` — and it is what makes step 6's rule work ("uploads
survive Cancel; the binding does not"). Rejected alternative: look the binding up server-side from
storage. It would need the binding persisted *before* the fetch, which forces the new table and
makes Confirm a server write, breaking the staging contract the drawer documents in
`ha_fetch.js`'s file header under **"Staged-then-confirm model (the crux)"** (cited by name: the
header's line numbers moved with step 6).

**Validate the binding server-side regardless of transport.** A client-supplied `upload_id` must be
checked against `uploads.get(workspace_id, upload_id)` — a foreign or absent id must not load.
This holds under every storage candidate and is not affected by the retraction above.

### D-BIND candidates — storage, RESOLVED (candidate E, chosen by the user 2026-08-05)

**The decision: candidate E, `localStorage`, extending the existing pre-fetch slot store.** The
three candidates are kept below with their costs, because the trade-offs are the record of why the
binding is *not* server state and are what a later move to B or D would have to re-argue.

Requirements a candidate must meet: **(a)** survives dataset re-versioning; **(b)** can be cleared
when an upload is deleted; **(c)** exists for a slot with no data yet (a binding is chosen *before*
any fetch). `series_meta` fails (a) and (c) — see the retraction above.

**Candidate B — a `retained.slot_bindings` block in `simconfig.json`** (`app/simconfig_store.py`).
Meets (a) by construction (per-workspace document, no dataset linkage, and `delete_data` explicitly
preserves it, `app/workspaces.py:417-421`), (c) trivially, and (b) via a read-modify-write copied
from `save_results_period` (`:607-658`) — which is already exactly this shape: a single-slot update
that does not go through `save()` and creates a missing document with `retained` alone. Being a
file, it does not contend with `uploads.delete`'s write lock, so D-SEQ's `database is locked` hazard
does not arise here at all. Costs, all specific: (i) `retained`'s own module comment (`:35-62`)
argues that it "is not the home of … as a class" and that each of its three entries needed its own
argument — a fourth needs that argument made, and a per-slot *dict* is structurally unlike the three
scalars there; (ii) **`to_dict` rebuilds `retained` from named keys only** (`:234-238`), so omitting
a `slot_bindings` line silently drops every binding on the next parameter save — this is the exact
defect that once ate the stored results period, so it is a demonstrated failure mode, not a
hypothetical; (iii) whole-document `os.replace` writes mean a binding write and a concurrent
parameter save can lose one another; (iv) it puts a reference to a SQLite row id (`upload_id`) in a
JSON file, so referential integrity is manual; (v) `load()` never raises and substitutes defaults,
so a corrupt document silently reverts slots to "Choose source…". Note `08-architecture.md:79` says
a slot's binding lives in `params`, and the spec's `params` *table* does not exist — the honest
reading of the spec is this document.

**Candidate D — a new `slot_bindings` SQLite table.** Shape
`slot_bindings(workspace_id, slot_name, upload_id, column_name, unit, updated_at)` with
`PRIMARY KEY (workspace_id, slot_name)`, upserted with the `ON CONFLICT DO UPDATE` idiom already
used by `bump_source_generation` (`app/db.py:243-251`). Meets (a) and (c); meets (b) most cleanly of
all — `DELETE FROM slot_bindings WHERE workspace_id = ? AND upload_id = ?` is one indexable
statement rather than JSON surgery, and a `delete_all_rows` sibling slots into `workspaces.delete`'s
existing step list (`app/workspaces.py:500-507`). Costs: (i) a fourth module following the
`app/uploads.py` template verbatim — its own `_SCHEMA` + `_connect()`, id guards, row→dataclass, at
this codebase's comment density; (ii) it lands in the same SQLite file as `uploads`, so the delete
cascade is two `BEGIN IMMEDIATE` transactions on two connections — D-SEQ's sequenced, non-atomic
window, and `database is locked` if anyone ever nests them (`app/uploads.py:67-74`); (iii) it is the
app's first table holding pure configuration, which cuts against the "params live in the JSON
document" division `simconfig_store`'s module comment establishes; (iv) §5.5 invariant 1 (every row
carries `workspace_id`) and the `workspaces.delete` cascade become new obligations.

**Candidate E — `localStorage`, extending the existing pre-fetch slot store.** Surfaced last, and it
is the one that matches the architecture already documented in `app/static/ha_fetch.js`'s file header
— the **"two things carry a source choice across a reload"** list, cited by that phrase because the
line numbers it used to carry are now stale — which states there are exactly **two** carriers of a
source choice across a reload: (1) *fetched* slots,
server-side in `series_meta` — provenance; (2) *pre-fetch customizations*, in
`localStorage ha.slots.<workspace>`, reconciled by the `source_generation` number. A CSV binding is
a choice the user has made but **not yet fetched**, i.e. category 2 verbatim. The store already
holds `{gen, slots: {<slot>: {source, statId}}}`; a binding extends the per-slot entry with
`{uploadId, column, unit}` beside `statId`, and inherits the generation reconciliation unchanged
(local gen === server gen → use local; server ahead → drop stale local, because the fetch that
advanced it has already written real provenance).

Consequences, stated honestly: (a) is met differently from B/D — the binding does not *survive*
dataset re-versioning, it is *superseded* by it, which is the existing designed behaviour for HA
slots rather than a new asymmetry; (b) needs no cascade at all in the server's delete path — a
deleted upload leaves a stale local entry that fails validation on the next fetch, which is the
same class of staleness the generation number already handles, though it does mean the *user-facing*
error arrives at fetch time rather than delete time (the drawer should also drop entries whose
upload is gone when it lists uploads); (c) is met natively. It also keeps Confirm a pure client
action, which is what makes the drawer's staging contract and step 6's "uploads survive Cancel, the
binding does not" rule work without a server write.

The cost, and it is real: `localStorage` is browser-local, so a binding does not follow the user to
another browser or device, and it is not part of the workspace's exportable state. For a
locally-run single-user app this is the same trade already accepted for the HA entity choice and the
URL/token — but it is a genuine limitation, not a free win, and it is the reason B or D might still
be preferred.

**B and D differ in failure mode, not in capability.** B makes a binding part of the workspace's
configuration document, inheriting never-raise-on-read and whole-file replace. D makes it a row,
inheriting per-statement integrity and writer-lock contention. **E differs from both in kind:** it
declines to make the binding server state at all, and instead files it under the existing pre-fetch
category — no new table, no new document key, no cascade, and no new architectural category.

**Under E as chosen, there is no clear-on-upload-delete write at all** — there is no server-side
binding to clear, and `delete_upload`'s docstring now records that absence as a decision rather than
a TODO. The rule the rejected candidates carried is kept here in case the binding ever moves
server-side: such a cascade would be a **separate transaction** from `uploads.delete` (D-SEQ) and
would run **unconditionally**, not gated on `existed`, because the retry after a crash between the
two writes is exactly the call where `existed` is false.

Then carry it into the ingest WS reify path (`app/ingest_ws.py` `BackendLoadRequest` /
`on_backend_load` at `:75-95` and `:222-240`, and the reify loop in `app/main.py:1366-1372`, where
`workspace.id` is already in scope and `sources_map` already records per-series provenance) so a
fetch loads CSV slots server-side alongside HA and backend slots, into the same dataset,
all-or-nothing.

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

**Status:** done and **reviewed (2026-08-06)**. `app/static/ha_fetch.js` +
`app/templates/workspace_data.html` + 60 new msgids translated into Dutch, plus nine Playwright
tests (`tests/test_smoke.py`: 45 → 54). The review found **no correctness defects** — the shipped
behaviour is right — and five places where correct code was unpinned by any test. Three were closed
here (a failed uploads LIST must not wipe bindings; `syncCsvUnitRadios`; and two store tests that
passed for the wrong reason, because their synthetic upload id let the PRUNE remove the entry the
completeness predicate was supposed to reject). Two were left to step 8 and are listed there.
`csvPendingOption()` and `PENDING_SOURCE_KEYS` are **gone** —
the guard against a bindingless CSV slot failing the whole all-or-nothing fetch moved from "you may
not choose this radio" to `updateConfirmEnabled`'s "you may not confirm this half-done".

Three things a later reader should know before touching this:

- **The completeness rule is now ONE predicate, `csvBindingComplete(o)`**, backing all three gates
  (`saveSlotStore`, `usableStoreEntry`, the Confirm gate). Step 5's review created the second copy;
  this step factored rather than adding a third. `usableStoreEntry`'s scoping is unchanged — still
  `csv_upload` only, because `_make_slot_pristine` writes an empty-source entry deliberately.
- **The delete cascade runs CLIENT-SIDE**, in `pruneStaleCsvBindings`, because under D-BIND the
  server holds no binding to clear. It runs on any 2xx (not gated on `existed` — the retry after a
  partial failure is exactly the call where `existed` is false), clears the slot WHOLE so the row
  returns to "Choose source…", and names the affected slots in the dialog's status line. It also runs
  whenever the uploads are listed, which discharges D-BIND's "drop entries whose upload is gone"
  obligation; the module lists eagerly on load only when some slot arrived CSV-bound.
- **`detail` is handled as `dict | str`** in `csvErrorText(status, detail)`: 413 first (no envelope),
  then `detail.code` against `CSV_ERROR_KEYS`, then a generic fallback that covers both a bare-string
  detail and an unknown code. The server's English message is appended only for the codes that name a
  specific offender, and every write is `textContent`.

See [20260806-csv-import-step6-drawer-ui.md](20260806-csv-import-step6-drawer-ui.md).

### Known gap — a cumulative column is refused at FETCH time, not at bind time

Recorded properly rather than as a footnote, because D-KIND's wording invites a wrong reading.

**The gap.** D-KIND says a cumulative-register column is "rejected on selection". The refusal is real
but it lives in `column_frame`, which runs at LOAD time — so "selection" means the moment the loader
selects the column, not the moment the user picks it in the drawer. The drawer has no way to ask:
`_upload_json` reports `columns` (names only), and the values live server-side. A user can therefore
bind a slot to a monotone column, press Confirm, and learn only when the fetch fails. The dialog's
fourth format bullet states the per-interval rule, so the user is warned before they get there, which
softens the surprise but does not remove it.

**Why step 6 could not close it.** There is no per-column route, and adding server surface is out of
this step's scope (the step's own constraint: no new routes). The client cannot decide monotonicity
because it never sees a value.

**Options, with what each costs.**

1. **A new per-column inspection route** (`GET …/uploads/{id}/columns/{name}` returning a verdict).
   Cleanest separation and the most room to say WHY a column was refused, but it is a whole new route
   — auth, workspace scoping, its own tests — for one boolean, and it re-reads the file on demand.
2. **A per-column `cumulative` flag in `_upload_json`, annotating the options in the column selector.**
   No new route; one field on a response that already exists, computed where the file is already being
   parsed, and the drawer greys or marks the affected options at the moment the user is choosing. This
   is the **intended shape if the gap is taken up.**
3. **Leave it as-is** — the format bullet plus a fetch-time error. Zero cost, and the failure is
   panel-local rather than run-fatal, but the user has to have read the bullet.

**Caveat to settle first, and it is a real precondition for option 2.** Step 2 recorded that the
register heuristic **rejects monotone partial-day PV** — a legitimate per-interval column that happens
never to decrease over a short file. Greying out a column the user is entitled to bind is a WORSE
failure than a late rejection: a late error is recoverable and explains itself, whereas a disabled
option looks like the app deciding the file is wrong. So option 2 should not ship until that
false-positive question is settled (a threshold, a minimum span, or a user override) — and whatever
surface carries the `cumulative` flag is also the natural place to carry the override.

**Not implemented here, deliberately.** This section is the record, not a task.

**Depends on:** steps 3, 4, 5.

In `app/static/ha_fetch.js` and `app/templates/workspace_data.html`:

- Replace `csvPendingOption()` in `ha_fetch.js` with a real radio carrying an `[ Upload… ]` button,
  mirroring HA's `[ Configure… ]` in `renderSourceList` (both cited by name: the line numbers this
  once carried predate step 6 and are stale, and `csvPendingOption` no longer exists at all).
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

**Inherited from step 6's review (2026-08-06) — two coverage gaps step 8 owns.** Both are correct
code today with no test holding it in place; neither is a defect. They were left here rather than
closed in step 6 because each needs a fixture step 6 does not have:

1. **`usableStoreEntry`'s SCOPING is untested.** It gates `csv_upload` only, deliberately: a
   `{source:'', statId:''}` entry is how a slot is cleared to pristine and must still restore. Pinning
   that needs a slot with a **committed** source that is then cleared to pristine and reloaded — i.e. a
   fetched slot, which means a real dataset, which is harness territory rather than a smoke fixture.
   Widening the predicate's scope to every source would break `_make_slot_pristine` and nothing else
   would notice.
2. **The 413 branch of `csvErrorText` is untested.** It is the one status with no error envelope of
   ours (`_read_capped_body` raises a plain string, and python-multipart's own part limits are enforced
   by Starlette before our handler runs), so it is a genuinely different path from the `detail.code`
   table. Driving it needs an upload over the size cap, which a Playwright test can only do by pushing
   a multi-megabyte buffer through a file input.

**Follow-up, not a gap:** `[ remove ]` in the upload dialog confirms with `window.confirm`. Its real
cost is not styling — it is that the OK/Cancel labels come from the browser and are therefore
**untranslated**, in an app where every other string goes through `_()`. Replacing it means nesting a
second `<dialog>` inside the open one; the message is already a single msgid, so the move is cheap
whenever it is judged worth doing. Deliberately not changed in step 6.

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
