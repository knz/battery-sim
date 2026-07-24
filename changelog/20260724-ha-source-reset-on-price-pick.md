# HA source appears to reset when picking the spot-price source

## Task Specification

User report: "When I select a HA source for grid consumption, then select the
alternative energy-charts source for the spot price data series, this resets the
HA configuration selected earlier. What's going on?"

Scope: diagnose the cause. No code changes yet — investigation only, pending user
decision on the fix.

## Investigation

Traced the slot-first source flow across the client (`app/static/ha_fetch.js`,
`app/templates/_panel_data.html`) and the backend (`app/main.py` `load_slot`,
`app/dataset.py` `upsert_series` / `load_latest`, `app/data_view.py`
`panel_data_from`).

### Findings

The backend merge is NOT the culprit. `upsert_series` (dataset.py) replaces only
the series of the same name and leaves the other series' `series_meta` rows and
`.npz` files intact; `load_latest` rebuilds `series_sources` per series. So a
persisted HA grid-consumption series survives an energy-charts price load.

The reset is on the CLIENT side, and there are two distinct cases:

1. **HA slot chosen in the drawer but NOT yet fetched.** The drawer's Confirm for
   an HA source writes only to in-memory `slotState[name] = {source, statId}` — it
   does NOT persist anything to the backend (no round-trip; the fetch is deferred
   to "Fetch history"). Picking the energy-charts price source runs
   `confirmBackend` → POST `/data/slot/price_spot/load` → `window.location.reload()`.
   The reload rebuilds the page from the persisted dataset, and `ha_fetch.js`
   re-seeds `slotState` from the slot buttons' `data-*` attributes with
   `statId: ""` (line ~111). Because the HA selection was never persisted, it is
   gone after the reload — the entity choice in particular, and the source too if
   the HA series was never written. This is the likely scenario behind the report.

2. **HA slot already fetched (persisted), entity still shows as reset.** Even here,
   the *entity id* (`statId`) is intentionally not re-seedable: the persisted
   view-model carries only a "(res, N intervals)" coverage summary, not a
   re-selectable statistic id (documented in `_panel_data.html` header and
   `ha_fetch.js` seeding comment). After any reload the HA row shows
   "Home Assistant · choose entity…" until re-picked, even though the data is still
   there. The *source* label persists (via `data-slot-source`) but the entity does
   not.

The trigger that surfaces this is that the energy-charts Confirm forces a full
`window.location.reload()`, discarding all in-memory `slotState`. Any HA selection
not backed by persisted data (case 1) or not re-derivable from the view-model
(case 2, the statId) is lost across that reload.

## Requirements change (mid-task)

The first cut used a "server wins for source, localStorage adds only the entity id"
rule. The user then asked that a **pre-fetch HA source** also survive the reload —
i.e. a source customization on a slot the server has no data for. That needs a way to
tell "the user just customized this" apart from "the server has newer authoritative
state", which a source-match check cannot do. Adopted a **server-issued generation
number** instead (user's proposal).

## Fix (implemented) — two tiers, split by whether a slot has been fetched

The final design carries a source choice across a reload in two ways, by whether the
slot has actually been **fetched**:

**1. Fetched slots → persisted SERVER-SIDE.** The HA statistic id is not secret (only
the token is, §7.5), so it is now stored. The browser sends the chosen id in the WS
`series` frame; it is written to `series_meta.stat_id`; `load_latest` puts it back on
the frame; and the view-model renders the slot's source AND entity from the dataset. A
fetched HA slot therefore shows "Home Assistant · <id>" after any reload, on any client
in the workspace, with no client state. This replaces an earlier idea (re-persisting the
localStorage entry at the new generation after a fetch) with the cleaner "the id lives
where the data lives".

**2. Pre-fetch customizations → localStorage, gated by a generation number.** For a
choice the user has made but not yet fetched (HA on a data-less slot, or a source
override), the server has no authoritative state, so it stays browser-local. The server
holds a per-workspace `source_generation`, bumped **only** when a fetch persists a new
dataset — never by a backend_load Confirm. The client tags each saved customization with
the generation it saw. On reload: local gen == server gen → local wins wholesale (source
+ entity); server gen > local gen → a fetch happened since, the server is authoritative,
local is dropped. Only slots the user actually customized this session are stored —
server-seeded ids are never copied into the store (that would let authoritative state
masquerade as a pre-fetch override).

Only a persisted fetch bumps the generation, so a backend_load Confirm's reload no longer
discards a just-saved HA customization (the original bug).

Decisions (confirmed with the user):
- Persist the fetched entity server-side; carry it in the WS `series` frame.
- Bump the generation only on Fetch history (HA ingest `done`).
- Local (pre-fetch) scope at equal generation: **both source and entity, per slot**.
- Generation storage: **new `workspace_state` table**.
- **No backward compatibility** for the interim flat-map localStorage format.

## Files Modified

- `app/db.py` — new `workspace_state(workspace_id, source_generation)` table;
  `source_generation()` / `bump_source_generation()`. `_connect` uses `executescript`
  (schema became multi-statement).
- `app/main.py` — bump the generation after a persisted ingest and return it in the WS
  `result` frame (the only bump site); expose `source_generation` to the index template.
- `app/templates/index.html` — render `#source-generation` JSON for the client.
- `app/domain/frames.py` — `SeriesFrame.stat_id` field.
- `app/ingest_ws.py` — carry `stat_id` from the `series` frame through the buffer onto
  the built frame.
- `app/dataset.py` — `series_meta.stat_id` column (+ migration entry); write it in
  `_insert_series_meta`; read it back onto the frame in `load_latest`.
- `app/data_view.py` — mapping rows carry `stat_id` (from the frame).
- `app/sample_data.py` — sample HA rows carry `stat_id` so the empty-state page also
  renders entities server-side.
- `app/templates/_panel_data.html` — button carries `data-slot-stat-id`; the label is
  rendered server-side as "Home Assistant · <id>" for a fetched HA slot.
- `app/static/ha_fetch.js` — read `serverGen`; store shape `{ gen, slots }`; seed
  `slotState.statId` from `data-slot-stat-id`; reconcile pre-fetch localStorage by
  generation; `locallyCustomized` set so only user-customized slots are stored. Module
  header + comments rewritten to the two-tier model.
- `tests/test_ingest_ws.py` — `stat_id` round-trips through persistence and renders on
  the page; `test_fetch_bumps_source_generation` (0 → 1 → 2).
- `tests/test_slot_load.py` — `test_load_endpoint_does_not_bump_source_generation`.
- `changelog/20260724-ha-source-reset-on-price-pick.md` — this file.

Trade-off (documented in code): a FETCHED slot's entity follows the workspace (server-
side); a PRE-FETCH customization is browser-local (same as URL/token) and reaches another
client only once fetched (the event that bumps the generation).

## Testing

Backend (pytest, committed): `stat_id` round-trips through `series_meta` and renders in
the page HTML (`data-slot-stat-id` + label); generation bumps on fetch (0→1→2, surfaced
in the result frame and the page) and does NOT bump on a backend_load Confirm.

Browser (Playwright, `$CLAUDE_JOB_DIR/tmp/test_slot_ls.py`, scratch, not committed;
drives the real DOM, stubs only the HA WebSocket). Verifies:
- A. HA entity survives a reload at equal generation; only the customized slot is stored
  (not the server-seeded siblings).
- B. A pre-fetch HA override on `price_spot` (server renders it energy_charts) survives a
  reload wholesale — source and entity.
- C. When the server generation advances (simulated by rewriting `#source-generation`),
  the stale local override is dropped and the slot falls back to the server-rendered
  entity; `ha.slots` is cleared.
- D. A real Fetch history persists the entity server-side; after the post-fetch reload it
  renders from the dataset (`data-slot-stat-id` + label) with an EMPTY `ha.slots` — i.e.
  not dependent on client state.
All four pass.

`uv run pytest`: 73 passed, 2 skipped, 1 failed. The one failure
(`test_smoke.py::test_new_pending_controls_marked`) is **pre-existing** — verified it
fails on the pristine branch too (git stash). It asserts the "Upload CSV" pending radio
is present at page load, but the drawer refactor (0594e34/dccebd0) moved that radio into
the drawer, so it is only rendered when a drawer opens. Unrelated; left untouched.

Also rendered both the persisted-dataset page and the clean empty-state page via
`tests/screenshot.py`: the empty state now shows each HA slot's entity server-side
("Home Assistant · sensor.…"), and a dataset persisted before this feature (no stored
stat_id) degrades gracefully to "Home Assistant · choose entity…".

## Current Status

Fix implemented and tested (backend unit tests + browser automation, four cases).
Pre-existing smoke-test failure noted above, not addressed here.
