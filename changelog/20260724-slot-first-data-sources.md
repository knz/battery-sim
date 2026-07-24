# Slot-first data input + per-slot data-source abstraction

> Status: **scoping — clarifying questions asked, plan not yet approved.** Created 2026-07-24.

## Task specification (original request)

User prompt, verbatim:

> "currently the data input first asks what the source should be (home assistant or CSV),
> and only then asks the user to provide details. we'd like to flip this: first define/explain
> the data slots to the user, then for each slot let the user decide where the data should be
> pulled from. (using a side panel)
> when the user chooses home assistant for one slot, the connection information should be
> reusable across multiple other slots (i.e. only test/connect once). please figure out a
> meaningful UX/UI for this.
> different slots may have different available data sources. For example for the spot price we
> can use either a home assistant data series or preset historical data. The app source code
> should abstract the data source behind an interface.
> regarding the spot price data: we've found an online API
> ( https://api.energy-charts.info/price?bzn=NL&start=2026-07-23&end=2026-07-24 ). It would be
> good to download the data since 2023 until today, commit it to the repository, then during
> live use have the data source combine the data from disk with additional API calls to bridge
> the interval between the last date in the on-disk data and the last date in the time range
> selected by the user."

### Scope (four intertwined parts)

1. **Slot-first UX** — panel ① leads with the roster of data slots (roles) and their
   explanations; source is chosen *per slot*, not once for the whole panel. Source picker is
   a side panel.
2. **Reusable HA connection** — connecting/testing HA once makes that connection available to
   every slot that uses HA. Test/connect only once.
3. **Per-slot source abstraction** — a `DataSource` interface in the backend; different slots
   expose different available sources (e.g. spot price: HA series *or* preset historical).
4. **Energy-Charts spot-price source** — download NL day-ahead prices from
   api.energy-charts.info since 2023, commit to the repo, and at runtime combine on-disk data
   with live API calls to bridge from the last on-disk date to the end of the selected range.

## Context gathered (existing state, pre-change)

- Panel ① (`_panel_data.html`) currently: a single `Source:` radio (HA / Upload CSV, CSV
  pending), then one HA connection card, then the series-mapping table, then data-quality.
- HA fetch is **browser-side** (`ha_fetch.js`): token in localStorage, never reaches backend;
  fetched rows streamed to `WS /data/ingest/ws` (`app/ingest_ws.py`), normalised into
  SeriesFrames (`app/domain/`), persisted (`app/dataset.py`), panel re-rendered from the
  persisted dataset (`app/data_view.py`).
- Series vocabulary + slot metadata: `app/domain/series_vocab.py` (`SERIES_SLOTS`,
  requirement/pv_only/cost_only flags).
- Specs: §2.2 (02-ux-wireframes) currently documents source-first with HA and CSV variants;
  §4.3 (06) documents browser-side HA fetch. §5.1 (08) is the layer diagram.

## Open questions (asked 2026-07-24)

See the questions put to the user. Key design tensions:
- Where the Energy-Charts fetch runs (browser vs backend) — the spot-price API is a public
  cloud endpoint reachable from the backend, unlike HA. This breaks the "all fetch in browser"
  invariant and needs an explicit decision.
- How the per-slot source picker interacts with the existing whole-panel HA fetch flow.
- Scope of this pass vs. follow-up (spec rewrites, CSV path).

## Backend phase — DataSource abstraction + Energy-Charts runtime source (2026-07-24)

Scoped implementation of parts 3 and 4 (backend only; no frontend/templates/main.py/persistence
touched — that is a later phase).

### Files created

- `app/domain/sources/base.py` — `SourceKind` (`"browser_fetch"` | `"backend_load"`),
  `SourceDescriptor` (frozen dataclass: key/label/kind/blurb), `DataSource` runtime-checkable
  Protocol (descriptor / available_for / load).
- `app/domain/sources/home_assistant.py` — `HomeAssistantSource`, kind `browser_fetch`,
  `available_for` True for every slot, `load` raises NotImplementedError (HA frames arrive over
  WS /data/ingest/ws; token stays in the browser).
- `app/domain/sources/energy_charts.py` — `EnergyChartsSource`, kind `backend_load`,
  `available_for` True only for `price_spot`. `load(slot, window, *, opener=None, now=None)`
  reads committed points via `price_store.load_range`, bridges the tail past `last_on_disk` via
  `energy_charts_api.fetch_prices`, merges (on-disk authoritative on overlap), and normalises
  through `ingest.price_frame`. Pure helper `bridge_date_range(last, end, now)` factored out.
- `app/domain/sources/registry.py` — `ALL_SOURCES` (HA first), `sources_for(slot)`,
  `get_source(key)` (ValueError on unknown). Plain lookup table, no behaviour.
- `app/domain/sources/__init__.py` — re-exports the public names + `PricePoint` / `price_store`.
- `tests/test_sources.py` — 14 tests (registry, descriptors, HA no-load, bridge arithmetic,
  on-disk load with no bridge, bridge-fires load with stub opener, empty-window).

### Design decisions

- **Overlap dedup direction:** on-disk wins over the bridged re-fetch of the last committed day.
  The bridge `from` date is the last on-disk interval's calendar date (API is day-inclusive), so
  that day is re-fetched; the merge keeps the committed value. Committed CSVs are the reviewable
  source of truth.
- **Empty window:** a window entirely before committed data (and API returning nothing) yields an
  empty zero-row SeriesFrame with `resolution_s=None` (ingest.price_frame handles empty rows) —
  chosen over raising, matching how the ingest path treats absence.
- **`now` caps the bridge tail:** `bridge_date_range` clamps `to` at `now`'s date so a
  future-ending window does not request data the API cannot serve.
- **No bug found** in the pre-written `energy_charts_api.py` / `price_store.py`.

### Test results

`uv run pytest tests/test_sources.py -x -q` → 14 passed. `tests/test_ingest.py` → 17 passed.

### Review + fixes applied (2026-07-24)

A sub-agent review (see `20260724-phase-a-source-review.md`) found no blockers. Resolved:

- **Layering (should-fix):** the sources package did I/O (network/file/wall-clock) from under
  `app/domain/`, which spec §5.1/§5.2 reserve for pure code. **Moved the whole package
  `app/domain/sources/` → `app/sources/`** (an adapter concern — it decides where data comes
  from and does the I/O), rewriting the `app.domain.sources` → `app.sources` imports in the
  package, the seed script, and the tests. Fixed `PRICE_DATA_DIR` (one fewer `.parent` now the
  module sits at `app/sources/`). `base.py`'s Protocol still depends on domain types
  (`SeriesFrame`, `SlotSpec`) — an adapter depending on domain types is the correct direction.
- **bzn path-traversal (nit):** `price_store` now guards `bzn` with `_safe_bzn` (`isalnum`)
  before interpolating it into a filename/glob (§5.5).
- **Comment/code drift (nit):** the merge comment in `energy_charts.py` now describes the actual
  window-filter + `_merge` overlap resolution, not a `last_on_disk` filter.
- **Mixed-resolution straddle (should-fix, documented not fixed):** a window straddling the
  hourly→15-min transition gets a single modal `resolution_s` from `ingest.price_frame`, which is
  not per-interval authoritative. No downstream consumer of that resolution exists yet; the real
  fix belongs in the §6.2 grid selector (as with the HA hourly/5-min pair). Documented in
  `EnergyChartsSource.load` and filed as follow-up.
- **Transition-date note:** the review brief guessed 2025-10-23; the committed data actually
  transitions at 2025-09-30T22:00Z, which is the real NL market data. Data is correct; the brief
  was wrong. No change.

Package now at `app/sources/`: `base.py`, `home_assistant.py`, `energy_charts.py`,
`energy_charts_api.py`, `price_store.py`, `registry.py`, `__init__.py`.

Post-fix: `pytest tests/test_sources.py tests/test_ingest.py tests/test_ingest_ws.py` → 38 passed.

## Backend wiring (Phase B) — persistence + load endpoint (2026-07-24)

Wires the Phase A source layer into persistence and a load route, without touching templates or
.js (that is Phase C).

### Files touched

- `app/dataset.py` — per-series provenance + the merge/upsert:
  - Added a `source_type TEXT` column to `series_meta` (both in `_SCHEMA` for fresh DBs and in
    `_SERIES_META_ADDED_COLUMNS` so a stale local DB gets it via the existing idempotent
    `_migrate`; no destructive migration).
  - `save_dataset(...)` gained an optional `sources: dict[str,str] | None` param (series name →
    source descriptor key). None / absent → the series falls back to the dataset-level
    `source_type`, so the WS ingest path (which passes only a whole-dataset source) is unchanged.
    Series_meta writing factored into `_insert_series_meta` and shared with the upsert path.
  - `LoadedDataset` gained `series_sources: dict[str,str]`; `load_latest` reads the per-series
    `source_type` back (falling back to the dataset source for legacy NULL rows).
  - New `upsert_series(frame, source_key, window=None, workspace_id=…)` — merges one frame into
    the latest dataset (see design below) or creates a standalone dataset if none exists.
- `app/main.py` — new `POST /data/slot/{slot_name}/load` route (see below). Added imports
  (`datetime`, `Body`, `JSONResponse`, `SLOT_BY_NAME`, `registry`, `SourceKind`) and a
  `_parse_window` helper mirroring `ingest_ws.on_header`. Routes list in the module docstring
  updated.
- `app/data_view.py` — each mapping row now carries `name`, `source` (from
  `LoadedDataset.series_sources`, else None), and `sources` (the list of available
  `{key,label,kind,blurb}` descriptors from `registry.sources_for(slot)`). Existing keys
  (role/req/entity/pv_only/cost_only + `data.*`) are unchanged — a superset, so the current
  template keeps working; Phase C's drawer will read the new keys. (`name` was previously missing
  from the real-data mapping rows though the template referenced it — added now.)
- `tests/test_slot_load.py` — new; 12 tests (migration, per-series sources round-trip,
  upsert replace/standalone, endpoint happy path + merge, endpoint error paths).

### upsert_series — window/coverage design

- **Merge into existing dataset:** replaces any `series_meta` row of the same name (and overwrites
  the deterministic `<name>.npz` via `_frame_path`, so no orphan file) and leaves the other series
  intact. Returns the same dataset id. This is what lets an Energy-Charts spot price attach to an
  HA-fetched energy dataset.
- **Standalone:** if no dataset exists, creates one containing just this series, with `source_type`
  = the source key and window = the supplied window (else the frame's own coverage).
- **Window semantics (chosen, documented in the docstring):** when merging with a `window`, the
  dataset's stored window is **widened to the union** of the existing and supplied windows — never
  shrunk. When `window` is None the window is left unchanged. Rationale: the stored window is only
  the advertised fetch span; the coverage the simulation grid actually uses is recomputed from the
  frames' own indices at read time (`normalize.grid_report`, §6.2), so a slightly-wide stored
  window is harmless and a union avoids clipping either series' advertised span.

### Endpoint — POST /data/slot/{slot_name}/load

- Body `{"source": "<key>", "window": {"start","end"}}`. Validates slot (404 unknown), source
  (404 unknown), availability (`available_for`, 400), and kind — a `browser_fetch` source (HA) is
  rejected 400 with a message pointing at the ingest WS. Window parsed like the WS header (400 on
  malformed / end≤start).
- `source.load` and `dataset.upsert_series` both run via `asyncio.to_thread` (file + possible
  network I/O off the event loop). A `load` exception maps to a clean **502** with a message
  ("could not load … from …: …"), not a stack trace.
- **Response shape:** JSON `{dataset_id, series, resolution_s, intervals, grid}` where `grid` is the
  same `normalize.grid_report` payload the WS `result` frame returns (built over just the loaded
  frame). Minimal + enough for Phase C to re-render or trigger a reload.

### Test results

`uv run pytest tests/test_ingest_ws.py tests/test_slot_load.py tests/test_sources.py
tests/test_ingest.py -q` → **50 passed**. Full suite minus the known-flaky smoke test:
**56 passed, 2 skipped**. No network hit: the endpoint test uses a 2024-03 historical window that
is fully on-disk (last_on_disk is 2026-07, so `bridge_date_range` returns None → no API call).

### For a reviewer to scrutinise

- **Merge correctness:** `upsert_series` DELETEs then re-INSERTs the same-named series_meta row in
  one transaction and overwrites the deterministic .npz. Confirmed by a test asserting exactly one
  price_spot row after upsert and the other series surviving. The FK `series_meta.dataset_id` and
  `workspace_id` on every row are preserved.
- **Datasets-window when merging different coverage:** the union widening is a deliberate,
  possibly-surprising choice — flagged above. It means a dataset's stored window can exceed any
  single series' coverage; nothing downstream trusts it for coverage (grid_report recomputes), but
  worth a second look if a later increment starts treating the stored window as authoritative.
### Review + fixes applied (2026-07-24)

A sub-agent review found one **blocker**, reproduced end-to-end, plus nits. Resolved:

- **Blocker — naive/aware datetime crash (HTTP 500).** `upsert_series`' union-window widening did
  `min(cur_start, window[0])` where `cur_start` (stored window, aware if written by the HA WS path)
  and `window[0]` (from `_parse_window`) could differ in tz-awareness — a request window without a
  UTC offset is naive, and `min()`/`max()` across naive and aware raises `TypeError`, surfacing as a
  500 (the exact outcome the endpoint claims to avoid, specs §3.2). Fix: `_parse_window` now
  normalises to tz-aware UTC (a naive instant is read as UTC — the one boundary where the tz
  decision is made, specs §4.4), via a shared `_as_utc`; `upsert_series` also normalises both sides
  defensively (a window stored naive by an older build). This also removes the `energy_charts.load`
  local-tz-promotion smell, since the window now arrives already-aware. The earlier changelog note
  that called naive windows "matches existing behaviour; not tightened here" was wrong — it was a
  live crash on the normal HA-then-price flow.
- **Test coverage (should-fix).** Added: an endpoint regression sending an offset-less window into a
  pre-seeded aware dataset (was the 500); a unit-level naive-window `upsert_series` test; and the
  three-series A,B → C → B′ survival sequence (A and C survive, B replaced, no duplicate rows).
  Now 53 tests across the slot-load/ingest/sources suites.

Verified-correct (no change): the DELETE-then-INSERT merge is scoped by `dataset_id` AND `name` in
one transaction (no duplicate rows possible); `.npz` overwrite by deterministic path leaves no
orphan; `workspace_id` on every row; migration idempotent with legacy NULL → dataset-source
fallback; the endpoint's error gates (404/400/502) and `asyncio.to_thread` off-loading.

## Spec rewrites (Phase D) — canonical prose brought in line with the build (2026-07-24)

Edited only the four spec markdown files below to describe the slot-first data-input reshape, the
per-slot `DataSource` abstraction, and the Energy-Charts backend spot-price source as the
specification (timeless prose), not as a change log. No code touched.

- **specs/02-ux-wireframes.md §2.2** — reshaped Panel ① from source-first to slot-first. The
  panel now leads with the slot roster; each slot row carries a per-slot source chosen in a
  right-side drawer that lists the sources available for that slot (energy slots → HA; the Spot
  price slot → HA or the preset Energy-Charts NL source). Replaced the single per-panel HA card
  framing with a shared HA connection (tested once, reused by every HA slot). Documented the
  preset backend-loaded spot-price source. Recast the CSV-variant section as one pending source
  offered per slot (feature key `data_source_csv`) rather than a whole-panel mode, keeping its
  substance (collect-the-files checklist, per-slot validation, slot supplies identity). Updated
  the ASCII wireframes to the slot-first layout with a Source column plus the drawer. Setup-band
  gating rules (has_pv, simulate_cost, Spot price required in both modes) and the four
  availability states are unchanged.
- **specs/06-home-assistant-ingestion.md** — added a "The spot-price slot has a second source"
  section: the preset Energy-Charts NL dataset is fetched by the backend (committed on-disk
  2023→today + live bridge via api.energy-charts.info), the one backend-initiated outbound data
  fetch, with the EUR/MWh→EUR/kWh conversion and the mixed hourly/15-min resolution caveat
  (grid selector owns resampling). Cross-linked to §5.1 and §7.5.
- **specs/08-architecture.md §5.1, §5.4** — added the `app/sources/` adapter package
  (SourceDescriptor + DataSource protocol + registry), HomeAssistantSource (browser_fetch) and
  EnergyChartsSource (backend_load) to the ADAPTERS column with a note on why a "source" is an
  adapter not domain; added POST /data/slot/{name}/load to the routes; added `source_type` to
  the series_meta schema line; noted the committed dataset at app/data/spot_prices/. §5.4 notes
  the Energy-Charts source needs no configuration and no API key.
- **specs/15-data-quality-and-limits.md §7.5** — promoted backend price egress from "a later
  increment" to a current, named egress case: a bidding zone + date range to
  api.energy-charts.info, no user or energy data, only when the user picks the preset source.

Reconciliations where the new feature met stale prose:
- §2.3 Pricing box "Spot source (•) from mapped sensor ( ) upload CSV" radio referred to the old
  whole-panel CSV mode; left the dispatch-signal wording intact but this is now consistent with
  the slot-first framing since "mapped sensor" is one slot source. No edit was required there —
  the radio names the price origin for the cost model, not the data-input mode — but noted for
  the reader.
- §7.5 previously said backend price fetch was "a later increment"; now current (fixed).
- §5.1 series_meta schema omitted the per-series `source_type`; added.

## Current status

Phase A (source abstraction + Energy-Charts source) and Phase B (per-series persistence,
upsert/merge, load endpoint, data_view provenance) complete, reviewed, and tested. Remaining:
Phase C frontend (slot-first drawer, reusable HA connection, rendering the new `source`/`sources`
row fields), spec rewrites, and the CSV source.
