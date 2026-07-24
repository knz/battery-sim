# Stage source config; reify the dataset only on fetch

## Task Specification

Reported bug: with an HA source configured for grid import and the energy-charts
(backend-load) source configured for spot price, clicking **Fetch** restores the HA
config but LOSES the spot-price config.

Root cause (confirmed by tracing): the two source kinds persist asymmetrically in the
pre-fetch phase.

- A backend-load Confirm (`confirmBackend` in `ha_fetch.js`) immediately POSTs
  `/data/slot/price_spot/load`, which calls `dataset.upsert_series` and **creates a
  `datasets` row server-side** (the first one in the flow, since no dataset existed).
- An HA Confirm writes nothing server-side (localStorage only).
- The HA **Fetch** then calls `dataset.save_dataset`, which INSERTs a *brand-new*
  `datasets` row. `load_latest` picks the newest by id, so the earlier price-only
  dataset is orphaned and the spot-price series disappears (its `.npz` survives on disk
  but no `series_meta` row points to it).

This also violates the state machine: specs §3.5 persists a dataset only on
`LOAD_SUCCEEDED`, and §3.2/§4 say configuring a slot ("filling in the mapping table")
"produces no session event until **Fetch history**." The immediate backend-load write
is a mid-config persistence the spec does not sanction.

## Requested model (user)

Pre-fetch configuration is a pure **staging** phase: selecting ANY source — HA or
backend-load — stages the choice client-side and writes NO dataset server-side. The
dataset is **reified only when Fetch is clicked**, which persists the full staged set
(HA slots streamed from the browser + backend-load slots loaded by the backend) as one
dataset. Source selections are persisted with the same localStorage + generation logic
already used for HA slots.

## Decisions (confirmed with the user)

1. **One button reifies all staged slots.** Fetch streams the HA slots over the WS AND
   triggers the backend load for each staged backend-load (energy-charts) slot, into one
   dataset. The button enables when any slot is staged (not only HA).
2. **Backend-load Confirm stops POSTing + reloading.** It becomes pure staging, like HA.
   The `/data/slot/{slot}/load` endpoint stays but is invoked by the reify step, not by
   the drawer Confirm. This also removes the mid-config reload that caused the earlier
   "reload loses HA config" bug — that bug's trigger disappears.
3. **Full staging model + specs update.** Implement uniform staging, reify-on-fetch,
   remove mid-config server writes; bring specs (§3.5/§4, §2.2, §06) in line and update
   the changelog. (Brings code back to what the state machine already describes.)

## Plan (approved)

Client (`ha_fetch.js`):
- Backend-load Confirm becomes pure staging (no POST, no reload), identical to the HA
  arm; `confirmBackend` removed. `saveSlotStore` generalized to store any staged source
  (HA with statId, or a backend-load key with statId "").
- `stagedBackendSlots()` helper (source kind read from `data-slot-sources`).
- Fetch gates on ANY staged slot; reifies all: streams HA `series`/`rows`, then sends a
  new `backend_load` WS message per staged backend slot, then `done`. Works with backend
  slots only (no HA) too.

WS protocol + backend (`ingest_ws.py`, `main.py`):
- New `backend_load` message `{name, source, window}` recorded on the session.
- `done` handler reifies in one transaction: build HA frames, then load every staged
  backend slot (`source.load` off-thread). **All-or-nothing**: any backend failure →
  LOAD_FAILED, persist nothing. On full success, one `save_dataset` with HA + backend
  frames and a per-series `sources` map; bump the generation once.
- `POST /data/slot/{slot}/load` kept working (tests intact), just no longer called by the
  drawer.

Specs: §04 (backend-load reifies on fetch, not on pick), §02.2 (pick → staged; Fetch
loads backend slots), §06 (energy-charts loads at fetch time).

Tests: ingest_ws — HA + staged price → fetch → both in one dataset (the reported
regression); backend-only fetch; all-or-nothing on backend failure. slot_load — endpoint
still works. Browser — stage HA + energy-charts, fetch, both survive.

## User prompts (verbatim, per specs/CLAUDE.md — spec files were edited)

1. "in the following scenario: 1. configure a HA source (e.g. grid import) 2. configure the
   spot price source with external data source (this reloads, and I see the HA source is
   preserved - good) 3. click "fetch" then after fetch completes, I see the HA source config
   is restored but the spot price source config is lost. please investigate"
2. "so from a UX / conceptual perspective, we'd like the pre-fetch config to "stage" changes,
   without writing datasets server-side. This means that selecting a server-side source for the
   spot price during the pre-fetch config phase should not create the dataset server-side just
   yet. instead, the "reification" of the dataset should be delayed until the fetch button is
   clicked. however, the selection of which data source to use should be persisted (with a
   similar logic as the HA source selection)"
3. "continue; please also create a new (fresh) changelog file"

(Earlier in the session, before this file: the request to persist client-side selections to
localStorage, then to let a pre-fetch HA source survive reload via a generation number, then to
persist the fetched entity server-side — see the related changelog.)

## Implementation (done)

Backend:
- `app/ingest_ws.py` — `BackendLoadRequest` + `IngestSession.on_backend_load`; `finish` allows a
  fetch with only backend slots. Protocol doc updated with the `backend_load` message.
- `app/main.py` — WS `done` reifies: build HA frames, load each staged backend slot
  (`_load_backend_frame`, all-or-nothing → `IngestError`/LOAD_FAILED), then one `save_dataset`
  with a per-series `sources` map; bump generation once. `_resolve_backend_source` shared by the
  reify path and `load_slot` (which keeps its HTTP semantics). `SeriesFrame` imported.

Client (`app/static/ha_fetch.js`):
- Backend-load Confirm now STAGES (no POST, no reload); `confirmBackend` removed; `confirmDraft`
  unified for HA and backend. `saveSlotStore` stores backend sources too. `backendSourceKeys` +
  `stagedBackendSlots()` learned from `data-slot-sources`. `fetchHistory` reifies HA + backend
  (HA-optional); `updateFetchEnabled` gates on ANY staged slot; connection test no longer the
  sole enabler.

Specs: §02-ux-wireframes (backend source stages; Fetch reifies all, enabled on any staged slot),
§06-home-assistant-ingestion (energy-charts egress fires at fetch time), §08-architecture (reify
via WS; `/load` kept as standalone).

Tests:
- `tests/test_ingest_ws.py` — `test_fetch_reifies_ha_and_backend_into_one_dataset` (the reported
  bug as a regression), `test_fetch_with_only_a_backend_slot`, `test_fetch_backend_failure_is_
  all_or_nothing`.
- `tests/test_slot_load.py` — endpoint still works (unchanged, via the shared resolver).

## Testing results

`uv run pytest`: 77 passed, 2 skipped, 0 failed. (The previously-noted
`test_new_pending_controls_marked` failure was fixed by the user in a separate commit.)

Browser (Playwright scratch, `$CLAUDE_JOB_DIR/tmp/test_slot_ls.py`): the reported scenario
(Case E) — staging energy-charts does NOT reload the page, and after the HA fetch BOTH the HA
entity and the energy-charts spot price survive (rendered from the one persisted dataset). Cases
A–D (localStorage + generation reconciliation, server-side stat_id) still pass.

## Status

Implemented and tested (backend regression tests + browser automation), specs updated. Not yet
committed.

## Related

Supersedes the merge-on-fetch direction considered earlier in the session; see
[20260724-ha-source-reset-on-price-pick.md](20260724-ha-source-reset-on-price-pick.md)
for the localStorage + source-generation reconciliation and server-side `stat_id`
persistence this builds on.
