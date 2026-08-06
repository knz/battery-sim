# Home Assistant data import — feasibility + implementation

> Status: **feasibility verified against the live instance; implementation plan awaiting
> approval.** Created 2026-07-23.

## Task specification (original request)

> "you have a home assistant instance on the LAN and a token in a local file.
> please run some checks regarding data import as per spec to verify feasibility, then do
> the data import in the app implementation"

Two parts: (1) verify the HA statistics ingestion path the spec mandates
([specs/06-home-assistant-ingestion.md](../specs/06-home-assistant-ingestion.md)) is
actually feasible against this instance; (2) build the data-import path in the app —
replacing the static sample view-model for panel ① with a real fetch.

## Part 1 — Feasibility checks (done)

Probes run from `scratchpad/ha_probe*.py` (one-off, not committed). Findings:

| Check | Result |
|---|---|
| Connectivity / auth | Instance is **HTTPS on :8123** (plain HTTP refused). REST `/api/` returns 200 with the long-lived token. HA version **2026.7.x**, tz Europe/Amsterdam, currency EUR. |
| TLS | Self-signed cert on the LAN — probes disabled verification. The app must allow the user to accept a self-signed/LAN cert (see risk below). |
| WebSocket API | `wss://…/api/websocket` auth with the token succeeds (`auth_ok`). |
| `recorder/list_statistic_ids` | 81 `sum` (energy) ids, 519 `mean` ids. The four P1 registers are present: `sensor.energy_consumed_tariff_1/_2`, `sensor.energy_produced_tariff_1/_2`. |
| `statistics_during_period` (hour) | Returns `sum`, `state`, `change`, `last_reset` per row. `sum` present on energy stats as the spec requires (already reset-corrected). HA also returns `change` (per-interval delta) directly. |
| Price sensor | `sensor.epex_spot_data_market_price` is `measurement` (`has_mean`), and an hourly row carries **mean, min, max** (e.g. mean 0.2955, min 0.2929, max 0.2982) — exactly what §4.3 needs for price bracketing. A second, supplier-provided price sensor was also present, so an instance may expose more than one price series. |
| Retention | Monthly aggregation returns **26 months** back to 2024-06 — long-term stats confirmed never-purged. |
| 5-minute (fine) window | `period: "5minute"` returns rows in the trailing window (24 rows in a 2 h probe) — supports the fine-copy / resolution-bias diagnostic. |

**One wrinkle:** `unit_of_measurement` comes back **`None`** in both `list_statistic_ids`
and `get_statistics_metadata` for these recorder/external sensors. So units cannot be read
from statistics metadata alone. Values are self-evidently kWh (register ~5127) and EUR/kWh
(price ~0.29), but the ingest must not *guess* — it will read the unit from the entity's
current state attributes (`GET /api/states/<entity_id>` → `attributes.unit_of_measurement`)
as a fallback, and surface it for user confirmation rather than assuming.

**Conclusion:** the spec's WebSocket statistics path is fully feasible on this instance. No
spec change needed. The mapping in `sample_data.py` uses different entity ids than this
instance actually has (`sensor.electricity_meter_import_t1` vs
`sensor.energy_consumed_tariff_1`) — real mapping is user-driven, so that is expected.

## Architecture decisions (from user, 2026-07-23)

User prompts recorded verbatim (per specs/CLAUDE.md, as these drive spec changes):

> "we'll want the data fetch from HA to be done from the front-end, if at all possible,
> then have the frontend code push the data towards our backend to save it for restarts.
> This is because later we'll want to host this service and the end-users will only be able
> to access their HA instance from their local browser."

> Token: "Token stays in browser only".
> Specs: "Update specs + build".
> Hand-off: "raw data per series (backend will compute). however beware of format/protocol,
> there may be a lot of data. maybe we'd want a streamed interface."
> Protocol: "ndjson and chunks if supported by frontend JS; otherwise websocket."

> Final (approval): "approve with split; ingest using WS only, drop ndjson."

**Resulting architecture (inverts spec §4.3/§5.1 backend-fetch design):**

1. **Browser fetches from HA.** Client-side JS opens `wss://<user-ha>/api/websocket`, auths
   with the token, lists statistic ids, and runs `statistics_during_period` (hourly full
   window + 5-minute trailing `ha_fine_window_days`), chunked to `ha_chunk_days`. This also
   removes the self-signed-TLS problem from the backend: the browser handles the cert.
2. **Token stays in the browser** (localStorage), sent only to the user's own HA. It never
   reaches our backend — best for the hosted future; we never hold a full-privilege HA
   credential. Supersedes spec §5.4/§7.5 server-side encrypted token storage.
3. **Browser pushes raw rows to backend**, which does all normalisation (cumulative→delta,
   native resolution, quality checks) into SeriesFrames — keeps "no client-side computation"
   and the pure, testable domain layer.
4. **Streamed hand-off over WebSocket only** (NDJSON dropped, per final approval). The
   browser opens `WS /data/ingest/ws` to our backend and streams messages: a `header`
   (window, mapping), then one `series_meta` + N `rows` batches per mapped series, then a
   `done`. The backend parses incrementally, buffers per series, and never holds the whole
   payload. WS works in every browser (no HTTP/2 request-streaming dependency) and gives
   per-chunk progress back to the UI. Fine window capped to ~10 trailing days keeps the
   realistic payload in low tens of MB.

## Build split (approved)

- **Phase 1 (this pass):** backend domain (numpy SeriesFrame, cumulative→delta, resets,
  gaps, native-resolution inference), the `WS /data/ingest/ws` endpoint + parser,
  persistence + startup restore, panel-① view-model from the persisted dataset, and tests
  (domain unit + a scripted WS-push integration test, plus a live-instance test that is
  skipped without the token). Testable end-to-end by a scripted WS client that replays
  fetched HA rows.
- **Phase 2 (next):** the browser `ha_fetch.js` (WS fetch from HA → WS push to backend) and
  wiring panel ①'s Test-connection / Fetch-history buttons; and the spec rewrites
  (§4.3, §5.1/§5.4, §7.5, §2.2) to describe browser-side fetch. Spec rewrites land with the
  UI they describe.

## Part 2 — Implementation plan (pending approval)

See the plan presented to the user. Spec files to rewrite: §4.3 (06), §5.1/§5.4 (08),
§7.5 (15), and the §2.2 data panel (02). New app modules: browser fetch JS, domain
ingest/normalise (numpy), `/data/ingest` NDJSON + WS endpoints, persistence.

## Files modified — Phase 1 (backend ingest + persistence)

Created:
- `app/domain/__init__.py`, `frames.py`, `ingest.py`, `normalize.py`, `series_vocab.py` —
  the pure domain: `SeriesFrame`/`QualityFlags` (§4.4), `cumulative_to_delta` + reset/gap +
  resolution inference + energy/price frame assembly (§6.1, §4.3), grid selection +
  reconciliation report (§6.2), and the closed series vocabulary (§4.1).
- `app/dataset.py` — persistence: SeriesFrames to `<data_dir>/<workspace>/series/<name>.npz`,
  dataset/series_meta rows to SQLite (reuses `app/db.py`), `save_dataset` + `load_latest`
  restore (§5.1, §3.5). No token stored.
- `app/ingest_ws.py` — the WS ingest protocol + pure `IngestSession` accumulator
  (header → series/rows → done), validated against the vocabulary.
- `tests/test_ingest.py` — 17 domain unit tests (reset/gap/resolution/frame/grid).
- `tests/test_ingest_ws.py` — WS endpoint integration + persistence/restore + error paths.
- `tests/test_ha_live.py` — live round-trip against the real instance, skipped unless
  `HA_URL`/`HA_TOKEN_FILE` set (pins the feasibility finding as a test).

Modified:
- `app/main.py` — added `WS /data/ingest/ws`: drives `IngestSession`, persists on `done` off
  the event loop, returns dataset id + grid report; `error` frame on validation failure.
- `pyproject.toml` / `uv.lock` — added `numpy` (domain arrays) and dev `httpx` (WS TestClient).

## Current status

**Phase 1 complete and green.** `pytest tests/ --ignore=tests/test_smoke.py`: 27 passed,
2 skipped (live tests). Live HA round-trip passes against the LAN instance (real P1 register →
hourly frame with correct deltas; real EPEX price → frame with min/max bracket).

Pre-existing, unrelated: `tests/test_smoke.py::test_new_pending_controls_marked` fails on the
base commit too — it looks for setup-band copy ("Also simulate cost savings") that a prior
commit reworded. Not touched here.

Not yet wired: panel ① still renders the static sample (`app/sample_data.py`) — replacing it
with the persisted dataset view-model, plus the browser fetch JS and the spec rewrites, are
**Phase 2**.

## Phase 2 — browser fetch, UI wiring, spec rewrites (complete)

Created / modified:
- `app/static/ha_fetch.js` — browser HA WebSocket client: Test connection (auth, list ids,
  fill mapping dropdowns with a best-effort auto-map), Fetch history (chunked hourly +
  5-minute fine window, each `rows` batch labelled with its `period`), stream to
  `WS /data/ingest/ws`, reload on success. Token in `localStorage`, sent only to the user's HA.
- `app/templates/_panel_data.html` — connection card driven client-side (URL/token inputs,
  status, token-stays-local note); mapping table uses `<select>`s populated by JS; fetch
  progress bar; price/load warnings guarded so a real dataset omits not-yet-computed ones.
- `app/data_view.py` — panel-① view-model from a persisted `LoadedDataset` (coverage, grid,
  per-series granularity incl. the fine copy, gaps/resets from quality flags, register summary).
- `app/main.py` — `index()` renders panel ① from `dataset.load_latest()` when a dataset exists,
  else the sample.
- `app/sample_data.py` — mapping rows carry the internal series `name` (for `data-series`).
- Domain/persistence changes surfaced by real data (see below): `SeriesFrame.fine_resolution_s`
  / `fine_coverage`; `ingest_ws` buffers per `(series, period)` and never differences the two
  native resolutions together; `normalize.effective_window` + `grid_report` run grid selection
  on the data's coverage overlap; `dataset` persists/restores fine metadata with a forward
  column migration.

Two real-data findings fixed (verified end-to-end against the LAN instance, ~90k rows/5 series):
1. **Two-resolution differencing.** Concatenating the hourly and 5-minute copies and
   differencing across them fabricated `AMBIGUOUS_REGISTER_DECREASE`s at the overlap (the
   5-minute register restarts lower than the hourly tail). Fix: keep the periods apart; the
   hourly copy is the frame, the 5-minute copy contributes only `fine_resolution_s`/
   `fine_coverage`. Pinned by `test_two_resolutions_are_not_differenced_together`.
2. **Grid came out `undefined`.** `choose_grid` tested coverage against the raw wall-clock fetch
   bounds, which hourly data never exactly reaches. Fix: `effective_window` = intersection of
   the energy series' coverage, clipped to the request; grid selection runs on that.

Spec rewrites (browser-side fetch), prompts recorded above per specs/CLAUDE.md:
- `06-home-assistant-ingestion.md` (§4.3) — rewritten: browser fetch, token-in-browser, WS
  hand-off, the two-resolution rule, the units-are-null wrinkle.
- `08-architecture.md` (§5.1, §5.4) — diagram: HaStatsClient moved into the browser, ingest WS
  endpoint, `credentials` table removed, `.npz` storage noted, series_meta gains fine columns;
  §5.4 drops token-encryption config.
- `15-data-quality-and-limits.md` (§7.5) — token stays in the browser; egress posture updated.
- `02-ux-wireframes.md` (§2.2) — connection runs in the browser; token stays local.

## Status: Phase 1 + Phase 2 complete

`pytest tests/ --ignore=tests/test_smoke.py`: 30 passed, 2 skipped (live). End-to-end verified
against the real instance: fetch → WS push → normalise → persist → panel ① renders real data
(5 series, hourly, 17,519 intervals), and the dataset survives a restart.

Pre-existing/unrelated: `tests/test_smoke.py` — its expand fixture (`cb.check()` on the
daisyUI collapse checkbox) times out in this environment, and does so **identically on the base
commit** (confirmed via `git stash`). The panel renders correctly (verified via curl: HTTP 200,
valid collapse structure). Not caused by this work.

## Not in scope (future increments, unchanged)

Simulation, pricing, metrics, benchmarks — the domain packages the architecture lists beyond
`ingest`/`normalize`. Panels ② and ③ still render the static sample. CSV ingestion path.
