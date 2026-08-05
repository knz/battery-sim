# 20260805 — CSV import

## Task Specification

Original request: "create a workspace, we're going to work on csv import".

Scope so far: workspace (git worktree `csv-import`, branch `worktree-csv-import`) created.
The actual CSV-import work is not yet specified — awaiting the user's requirements.

## High-Level Decisions

- Work happens in an isolated worktree at `.claude/worktrees/csv-import/` rather than on
  `master`, per the project's worktree convention.

## Requirements Changes

None yet.

## Files Modified

- `changelog/20260805-csv-import.md` (new) — this file.

## Rationales and Alternatives

Nothing to record yet; no implementation decisions taken.

## Obstacles and Solutions

None yet.

## Requirements (from the user, 2026-08-05)

> "in the data configuration panel, when the user opens the source side bar for a data
> series, we'd like to let them upload a CSV."

So: build the CSV upload source inside the existing source-picker drawer, per data slot.

## Findings from reading the existing code (before any changes)

The scaffolding for this already exists and was designed in:

- `docs/specs/05-data-formats.md` §4.2 fully specifies the per-series CSV format:
  `timestamp,value,unit,kind` columns; offset-or-`Z` mandatory (naive rejected); `unit` and
  `kind` may instead appear as header comments (`# unit: kWh`); `kind` ∈
  {cumulative, delta, price} and constant within a file; one file carries one series, and the
  file never names its own series — the slot the user drops it into declares that.
- `docs/specs/05-data-formats.md` "Validation and failure": a bad file is a *recoverable,
  panel-local* condition reported on that slot; other slots unaffected, no error state.
- `app/sources/base.py:6` names CSV as a planned third source; `SourceKind` is currently
  `browser_fetch` | `backend_load`.
- `app/static/ha_fetch.js:948-978` `csvPendingOption()` already renders a disabled "Upload
  CSV" radio in the drawer with the `[?]` pending affordance. It is client-side only — CSV is
  NOT in the server-side registry (`app/sources/registry.py:30`) or `sample_data.py`.
- `app/features.py:49` holds the `data_source_csv` pending key. Its documented ongoing-work
  rule (lines 18-27) says: on building the feature, remove the pending markup and move the key
  to `RETIRED_KEYS`, keeping its title.
- `app/ingest_ws.py:1-58`: the ingest WS already reifies a whole staged source config in one
  shot, mixing browser-streamed `series`/`rows` messages with `backend_load` declarations, and
  persists them as ONE dataset. Nothing is written before a fetch.
- `app/domain/ingest.py:101` `cumulative_to_delta` already implements §6.1 register→delta with
  reset/gap flagging, so the CSV path can reuse it rather than reimplement differencing.

No CSV parser exists yet anywhere in `app/`.

## Spec conflicts found (must be resolved before building)

1. **The CSV UX section predates slot-first.** `02-ux-wireframes.md:530` "The CSV source
   (pending)" specifies an ALL-SLOTS checklist box — one row per series, per-row
   `[ choose file… ]`, its own `[ Load data ]` button, `[ Download format spec ]` /
   `[ Download example file ]`. That was written for a whole-panel CSV mode. The drawer is
   per-slot and transactional (`[ Confirm ]` / `[ Cancel ]`, §2.2). The spec never reconciles
   them. RESOLVED (user, 2026-08-05): per-slot in the drawer; rewrite the section.
2. **CSV has no `SourceKind`.** `base.py:38` offers only `browser_fetch` | `backend_load`;
   `main.py:1376-1380` gates on it, and `ha_fetch.js:624-631` discovers backend slots BY kind.
   `DataSource.load(slot, window)` has no parameter for an uploaded payload.
3. **`08-architecture.md:80-81` specifies `<workspace_id>/uploads/<original_filename>` and a
   backend `CsvLoader`** (also `:52`, `:135`). Browser-side parsing means neither exists — the
   file never leaves the browser. A deliberate divergence to write into the spec.
4. **`delta` has no normaliser.** `ingest.py:174` `energy_frame` assumes a cumulative register
   and differences it (N readings → N−1 intervals). `SeriesFrame.values` is per-interval kWh, so
   `delta` is nearly a pass-through — but that path does not exist. `price` maps onto
   `price_frame` (`ingest.py:200`) cleanly.
5. **`EnergyRow`/`PriceRow` carry epoch milliseconds** (`ingest.py:57-70`), modelled on HA.
   Browser-side parsing must convert ISO-with-offset → epoch ms in JS; the offset is consumed
   at parse time and never reaches the backend (correct, as internals are UTC, but worth stating).
6. **Four broken spec links.** `05-data-formats.md:6` and `:122`, `04-state-machine.md:84`,
   `16-validation-harness.md:195` all point at
   `02-ux-wireframes.md#csv-variant-of-the-source-sub-panel`; the heading is now "The CSV source
   (pending)" (`#the-csv-source-pending`). Fix while rewriting the section.
7. **`20-workspaces-ux.md` never says what happens to uploaded files when a workspace is
   duplicated or deleted**, though `08-architecture.md:81` puts uploads under `<workspace_id>/`.
   Moot if parsing is browser-side and nothing is stored.

Also relevant: `15-data-quality-and-limits.md:102-108` splits the checks — 1 and 2 (offset
present, monotonicity) run per-file as each upload arrives; 3 onward run once against the
assembled dataset. Browser-side parsing suits that split.

## Decisions so far (user, 2026-08-05)

- **Parse browser-side**, stream over the existing ingest WS as `series`/`rows`. No new route,
  no upload storage, no file leaves the machine; validation errors are immediate and
  panel-local, which is what §4.2 "Validation and failure" and `04-state-machine.md:81-92`
  require.
- **Per-slot chooser in the drawer**; rewrite `02-ux-wireframes.md` §"The CSV source" for
  slot-first. The checklist's "files to collect" guidance survives as help text, not layout.
- **Write the UX spec section before coding.**
- **Format and staging: ON HOLD.** The user wants to redesign the format and the UX rather than
  build to §4.2 as written. Discuss UX first, then revisit staging (browser memory vs
  localStorage vs re-read on Fetch).

## REQUIREMENTS CHANGE — the redesign (user, 2026-08-05)

Verbatim prompt:

> we'd like to enable the user to use the same CSV file as input for multiple data slots.
>
> for this, we're going to separate the task of uploading CSV files, from the task of mapping
> CSV files to data series.
> contrary to my previous instructions, we're going to let the CSV files persist server-side.
>
> general idea for UX:
> - Next to the "upload csv" radio title, there should be an "Upload..." button (akin to the
>   "Configure..." button for HA) that opens an upload dialog. (discussed below)
> - When the user picks "upload CSV", the remainder of the side pane will display a first
>   selector where the user picks a file they've previously uploaded; then another select
>   dropdown to let them select one of the columns in that file to use as value column, then for
>   energy data series another radio select for whether the value is in Wh or kWh (default kWh)
>
> upload dialog:
> - an intro text that tells the user they can upload their data as CSV
> - explain the first row should contain column names
> - explain the CSV must have the first column in format "DD-MM-YYYY HH?:mm:SS" (hours on
>   24-hour scale)
> - subsequent columns contain values, fractional values are supported
> - explain that they can customize which column maps to which data series on the next screen

### What this reverses

- **Browser-side parsing → REVERSED.** Files now persist server-side. This re-instates
  `08-architecture.md:80-81`'s `<workspace_id>/uploads/` and the `CsvLoader` adapter (`:52`),
  so spec conflict 3 above dissolves — the original architecture was right after all.
- **One file per series → REVERSED.** `05-data-formats.md` §4.2 ("One file carries one series",
  "the file never names its series") is superseded: one WIDE file now feeds MANY slots, and the
  mapping is an explicit per-slot column choice. §4.1's "the user declares which series they
  are providing by choosing which slot to put the file in" no longer holds either — the slot now
  names a (file, column) pair.

### The new format

- Row 1 = column names (header REQUIRED — was optional/absent in §4.2).
- Column 1 = timestamp, format `DD-MM-YYYY HH:MM:SS`, 24-hour. **Note: this is a fixed local
  format with NO UTC offset**, which directly contradicts §4.2's "Offset or `Z` is mandatory.
  Naive timestamps are rejected" and check 1 in `15-data-quality-and-limits.md:80`. See the
  open questions below — this needs a DST answer.
- Columns 2..N = values, fractional supported.
- Unit is chosen PER SLOT in the drawer (Wh | kWh radio, default kWh), not declared in the file.
  So §4.2's `unit` column/header-comment mechanism goes away for energy.
- `kind` is not in the format at all. §4.2's "never guess `kind`" rule needs a new answer.

### The new UX

Two separate tasks, per the user:
1. **Upload** — an `[ Upload… ]` button beside the "Upload CSV" radio title, mirroring HA's
   `[ Configure… ]` (`ha_fetch.js:926-937` builds that button for `kind === "browser_fetch"`).
   Opens a dialog whose copy explains the format (four bullets above).
2. **Map** — picking the "Upload CSV" radio fills the rest of the drawer with: a file selector
   (previously-uploaded files), then a column selector, then (energy slots only) a Wh|kWh radio.

## Format decisions on the redesign (user, 2026-08-05)

- **D-TZ — timezone is asked, once, per file, at upload.** The upload dialog gets a selector
  offering **Europe/Amsterdam** or **UTC**. The timestamps are converted to UTC **on upload**
  ("adjust the data internally on upload"), so everything downstream of the upload sees UTC and
  the naive-local format never propagates. This supersedes §4.2's "offset or `Z` is mandatory"
  for this path: the offset now comes from the user's answer instead of from each row.
- **D-DST — first occurrence plus a quality flag.** Under Europe/Amsterdam, an ambiguous
  timestamp in the repeated Oct 02:00–03:00 hour maps to its FIRST (CEST) instant, and the
  affected samples carry a quality flag reported in the Data quality box. Chosen over
  disambiguating by row order (first duplicate = CEST, second = CET), which recovers the hour
  exactly for a well-formed chronological export but is silently wrong for a file with gaps or
  unusual ordering across the boundary — the failure mode §4.2 was written to prevent. The
  misattribution is bounded to one hour a year and is visible rather than silent. UTC uploads
  have no ambiguous hour, so this rule applies only to the Europe/Amsterdam choice.
- **D-KIND — per-interval values ONLY.** Every value column is read as the amount for the
  interval STARTING at its timestamp. A column that looks like a cumulative meter register
  (monotonic non-decreasing) is REJECTED with an explanatory error rather than differenced.
  No `kind` field, no inference, no override. This keeps §4.2's "never silently guess" property
  by removing the guess entirely.
  - Reaffirmed after being flagged: this narrows the feature. A Dutch P1 smart-meter export of
    cumulative `grid_import_t1` readings — a common shape for this app's target household, and
    what `05-data-formats.md:24` describes as "cumulative/delta" — cannot be used this
    increment, even though `cumulative_to_delta` already exists and would difference it. The
    user chose the unambiguous narrow path with an explicit rejection over a detection step.
- **D-SCOPE — per workspace**, under `<workspace_id>/uploads/`, as `08-architecture.md:81`
  already specifies. Re-uploading is the cost of analysing the same household in a second
  workspace; workspace deletion stays self-contained.
- **D-PRICE — energy slots only in this increment.** CSV is offered for energy slots with the
  Wh|kWh radio (default kWh). `price_spot` keeps the existing Energy-Charts / ENTSO-E preset
  sources and does NOT offer CSV. So no price units, no `EUR/kWh` handling on this path yet.

### Consequence to resolve: `energy_frame` is now the wrong normaliser

D-KIND means the CSV path CANNOT use `ingest.py:174` `energy_frame`, which exists precisely to
difference a cumulative register. The per-interval path needs its own normaliser: validate
spacing, infer resolution (`infer_resolution_s`, `ingest.py:79`), convert Wh→kWh, flag gaps for
empty cells, and emit `SeriesFrame.values` directly. That is new code, though small.

D-PRICE means `price_frame` is not needed on this path at all.

## Files Modified — specs (no application code touched yet)

- **`docs/specs/02-ux-wireframes.md`** — replaced §"The CSV source (pending)" wholesale. The
  all-slots checklist wireframe is gone; in its place, the per-slot drawer wireframe (File /
  Column / Unit controls under the radio), the upload-dialog wireframe with its four explanatory
  bullets and the timezone radio, and prose on: upload-vs-mapping separation, the
  `(file, column, unit)` triple, why `[ Upload… ]` mirrors `[ Configure… ]`, transactionality
  (uploads survive Cancel, bindings do not), the DST rule and why row-order was rejected,
  per-interval-only with the register rejection, file removal clearing bindings, and workspace
  scoping. Also updated the earlier drawer wireframe (CSV no longer `[?]`-pending), the
  "which slots offer which sources" list, and the "nothing to bind" sentence. Added an
  `<a id="csv-variant-of-the-source-sub-panel">` compatibility anchor.
- **`docs/specs/05-data-formats.md`** — new §4.2a "The wide, multi-series file format": layout
  table, the timezone-at-upload rule and its DST consequence, units/kind moving to the drawer,
  the register rejection with its cost stated, resolution, and two-level validation. Added a
  banner to §4.2 explaining that two shapes now exist and that the narrow one is unimplemented.
  Corrected §4.1's "upload slots" paragraph to describe column binding.
- **`docs/specs/04-state-machine.md`** — rewrote the panel-local CSV paragraph for the two-step
  flow; `SOURCE_CONFIGURED`'s trigger now reads "validated file-and-column binding".
- **`docs/specs/15-data-quality-and-limits.md`** — rewrote "Where these checks run on the CSV
  path": check 1 now splits by format (offset mandatory on narrow; declared-zone-applied plus
  DST flag on wide), check 2 becomes the on-selection register rejection.
- **`docs/specs/08-architecture.md`** — storage layout now `uploads/<upload_id>.csv` with the
  rationale for app-assigned ids; added the `uploads` table; added `CsvSource` to the source
  list with its `backend_load` justification, the binding-as-parameter note, and the two upload
  routes; fixed "two implementations" → "four"; annotated `CsvLoader` in the layer diagram.
- **`docs/specs/16-validation-harness.md`** — rewrote fixture 22 for the two failure points plus
  reuse/replacement, and added fixture 22a for the timezone/DST behaviour.
- Repointed the four broken `#csv-variant-of-the-source-sub-panel` links to `#the-csv-source`
  (`05-data-formats.md:6` and `:129`, `04-state-machine.md:84`, `16-validation-harness.md:195`).

Verified: every anchor introduced resolves, and the ASCII wireframes I wrote are
column-consistent at 76 chars.

## Obstacles and Solutions

- Spec §"The CSV source" described a whole-panel checklist incompatible with the per-slot
  drawer → rewrote the section rather than patching it; recorded the superseded design here.
- `08-architecture.md` said "two implementations" while listing three → corrected to four.
- Naive timestamps contradict §4.2's central timestamp rule → resolved by asking the zone once
  at upload and converting immediately, documented as an explicit, reasoned weakening.
- My link checker flagged `#22-panel--data-input-expanded` as broken → false positive; GitHub
  strips the `①` from the heading. Left alone. (`05-data-formats.md:16`'s `#51-layers` IS a
  genuine pre-existing typo for `#51-diagram`, left alone as out of scope.)

## Plan approved (user, 2026-08-05)

> "time zone: use "Amsterdam" in the name (there are parts of the Netherlands in other time
> zones)
> approved otherwise"

Correct on the fact: the Caribbean Netherlands (Bonaire, Saba, Sint Eustatius) are on AST and
observe no DST, so "Dutch local time" names no single zone. Label changed to **"Amsterdam local
time"** in the dialog, with the reasoning recorded in `02-ux-wireframes.md` so it is not
"corrected" back later. Underlying identifier stays `Europe/Amsterdam`.

## Working method (user, 2026-08-05)

> "this is going to be a long project so we'd like the main agent to focus on orchestration and
> use sub-agents for implementation and review.
> we'll also be compacting the orchestrator context every now and then so we'll want to ensure
> task descriptions are persisted beforehand"

Consequences, which apply for the rest of this project:

- **The orchestrator does not implement.** It delegates each step to a subagent and reviews the
  result. Implementation and review are separate subagents — the reviewer must not be the
  author.
- **[20260805-csv-import-implementation-brief.md](20260805-csv-import-implementation-brief.md) is
  the durable source of truth for the work.** It is written to be picked up cold, with no
  conversation context: the format, the four decisions, verified code anchors, all eight steps
  with their dependencies, and the open items left to the implementer. Every subagent is pointed
  at it rather than briefed conversationally.
- **Task descriptions are self-contained**, each naming its step in the brief, so the task list
  survives compaction on its own.
- **Each step updates its own `Status:` line in the brief** as it lands, so progress is on disk
  rather than only in the orchestrator's context.

## Current Status

Specs written and internally consistent. Plan approved. Implementation brief written and tasks
persisted. Delegating step by step; nothing implemented yet.

1. `uploads` table + `<workspace_id>/uploads/` storage, owner/workspace-scoped with the same
   traversal guards as `_series_dir` (`dataset.py:188-191`).
2. `app/domain/csv_wide.py` — pure parser: header, `DD-MM-YYYY HH:MM:SS` + zone → UTC, DST
   ambiguity flagging, per-column numeric/monotonicity checks, Wh→kWh, resolution inference
   (reuse `infer_resolution_s`), emit `SeriesFrame`. No I/O.
3. `POST /w/{id}/data/uploads`, `DELETE …/uploads/{id}`, `GET …/uploads` — CSRF, size cap.
4. `app/sources/csv_source.py` — `CsvSource`, `backend_load`, energy slots only; register in
   `ALL_SOURCES`; mirror label/blurb into `sample_data.py:107` `_SOURCE_STRINGS` for i18n.
5. Persist the per-slot binding, and carry it into the ingest WS reify path.
6. Drawer UI in `ha_fetch.js`: replace `csvPendingOption()` with the real radio, `[ Upload… ]`
   button, upload dialog, file/column/unit controls, staged into `draft`.
7. Retire `data_source_csv` from `FEATURE_KEYS` → `RETIRED_KEYS` (`features.py`), remove pending
   markup, update `implementation-progress.md`.
8. Tests mirroring `test_sources.py`, `test_slot_load.py`, `test_ingest.py`,
   `test_workspace_data.py`, plus harness fixtures 22 and 22a.
