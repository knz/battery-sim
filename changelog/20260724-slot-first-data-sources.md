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

## Current status

Backend DataSource abstraction + Energy-Charts source implemented, reviewed, and tested (Phase A
complete). Frontend (slot-first drawer, reusable HA connection), spec rewrites, main.py wiring,
and CSV source remain for later phases.
