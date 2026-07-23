# 5. Software architecture

> **Purpose:** the layer split, why it is drawn where it is, the compute model,
> configuration, and the constraints that keep multi-tenancy a later additive change.
> **Audience:** backend.
> **Read with:** [04-state-machine.md](04-state-machine.md), which the service layer
> implements, and [07-internal-representation.md](07-internal-representation.md) for the
> types crossing these boundaries.

## 5.1 Diagram

```
┌───────────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                                  │
│  Jinja2-rendered HTML · HTMX (fragment swaps) · Plotly (chart JSON)       │
│  No build step, no SPA framework, no client-side computation.             │
└───────────────────────────┬───────────────────────────────────────────────┘
                            │  HTTP (fragments + JSON) · SSE /api/stream
┌───────────────────────────▼───────────────────────────────────────────────┐
│  WEB LAYER — FastAPI                                                      │
│    routes/data.py     POST /data/source  /data/mapping  /data/fetch       │
│    routes/params.py   PATCH /params                                       │
│    routes/results.py  GET  /results  /results/export.csv                  │
│    routes/stream.py   GET  /api/stream           (SSE)                    │
│                                                                           │
│    deps.py:  get_principal() -> Principal        ← v1 returns "local"      │
│              get_workspace(principal, id) -> Workspace                    │
└───────────────────────────┬───────────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────────┐
│  SERVICE LAYER  (orchestration, state machine, no numerics)               │
│    IngestService       source config → SeriesFrames → persist             │
│    WorkspaceService    params CRUD, validation, dirty tracking            │
│    SimulationService   run_id, debounce, cancellation, LRU result cache   │
│    JobRunner           ProcessPoolExecutor keyed by workspace_id          │
└──────┬──────────────────────────────────────┬─────────────────────────────┘
       │                                      │
┌──────▼──────────────────────┐   ┌───────────▼────────────────────────────┐
│  ADAPTERS  (all I/O)        │   │  DOMAIN  (pure functions, no I/O)      │
│    HaStatsClient            │   │    ingest/     cumulative→delta        │
│    CsvLoader                │   │    normalize/  grid selection, resample│
│    PriceLoader              │   │    quality/    checks, flags           │
│    (future) EntsoeClient    │   │    pricing/    import/export curves    │
└──────┬──────────────────────┘   │    policies/   charge + discharge      │
       │                          │    battery/    step function, limits   │
       │                          │    simulate/   main loop               │
       │                          │    metrics/    KPIs, waterfall         │
       │                          │    benchmark/  perfect-foresight DP    │
       │                          └────────────────────────────────────────┘
┌──────▼────────────────────────────────────────────────────────────────────┐
│  PERSISTENCE                                                              │
│    SQLite  (SQLAlchemy)                                                   │
│      workspaces(id, owner_id, name, created_at)                           │
│      datasets(id, workspace_id, source_type, fetched_at, coverage, qa)    │
│      series_meta(id, dataset_id, name, kind, resolution_s, path)          │
│      params(workspace_id, json, updated_at)          -- current config    │
│      runs(id, workspace_id, run_id, config_hash, result_json, created_at) │
│      credentials(workspace_id, ha_url, ha_token_enc)                      │
│                                                                           │
│    Filesystem                                                             │
│      <data_dir>/<workspace_id>/series/<name>_<res>.parquet                │
│      <data_dir>/<workspace_id>/uploads/<original_filename>                │
└───────────────────────────────────────────────────────────────────────────┘
```

The `domain/` sub-packages map onto the specification files as follows:

| Package | Specification |
|---|---|
| `ingest/`, `normalize/` | [09-ingest-algorithms.md](09-ingest-algorithms.md) §6.1–6.3 |
| `quality/` | [14-diagnostics.md](14-diagnostics.md), [§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order), [13-configuration-epochs.md](13-configuration-epochs.md) |
| `pricing/` | [10-pricing.md](10-pricing.md) §6.5, plus §6.4 zone assignment |
| `policies/`, `battery/`, `simulate/` | [11-policies-and-battery.md](11-policies-and-battery.md) §6.6–6.9 |
| `metrics/` | [§6.10](10-pricing.md#610-cost-accounting) waterfall, [§6.11](12-metrics-and-benchmarks.md#611-metrics) |
| `benchmark/` | [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark) |

## 5.2 Why this split

The **domain layer is pure** — it takes arrays and a config object and returns arrays and
a result object. No database, no HTTP, no clock. This is what makes the simulator testable
against hand-computed fixtures ([16-validation-harness.md](16-validation-harness.md)), and
it is what allows the resolution-bias diagnostic and the perfect-foresight benchmark to be
implemented as *additional calls* rather than special cases threaded through the
application.

## 5.3 Compute

`ProcessPoolExecutor` with one worker per workspace. A year of hourly data is 8,760
intervals; the vectorisable parts (pricing, metrics) run in numpy, and the sequential
battery loop is the only genuine bottleneck. Expect ~50 ms for the policy run and ~1–3 s
for the perfect-foresight DP at 100 SoC levels. If the sequential loop proves too slow at
5-minute resolution over a year (105k intervals), the fallback is Numba `@njit` on
`simulate_core` — keep that function free of Python objects so the option stays open.

Cancellation is cooperative: `simulate_core` checks a shared `multiprocessing.Event`
every 1,024 intervals. The `run_id` protocol that drives cancellation is in
[§3.3](04-state-machine.md#33-concurrency-and-run-identity).

## 5.4 Configuration

Single `config.toml` next to the data directory: bind host/port, data dir, log level,
default parameter values, encryption key for stored HA tokens. Environment variables
override. HA tokens are encrypted at rest with a key derived from a local secret file
(0600); this is deterrence against casual disclosure, not a security boundary. See also
[§7.5](15-data-quality-and-limits.md#75-operational-notes).

Default parameter values shipped in `config.toml` are listed in
[appendix-a-defaults.md](appendix-a-defaults.md).

## 5.5 Multi-user readiness (designed for, not implemented)

The following are v1 requirements *because* they make multi-tenancy a later additive
change rather than a rewrite:

1. **Every persisted row carries `workspace_id`.** No table is implicitly global.
2. **`Workspace` is resolved via a FastAPI dependency**, never read from a global.
   In v1 `get_principal()` returns a hard-coded `Principal(id="local")` and
   `get_workspace()` returns the single workspace. Adding auth means replacing exactly
   these two functions.
3. **No module-level mutable state.** Session state, run ids, debounce timers and caches
   live inside `SimulationService`, instantiated per workspace and held in a registry
   keyed by `workspace_id`.
4. **Filesystem paths derive from `workspace_id`**, with path traversal rejected.
5. **The job runner is keyed by `workspace_id`** with a per-workspace concurrency limit
   of 1, so one user's year-long run cannot starve another's.
6. **SSE streams are per-workspace channels.** The stream endpoint takes the workspace
   from the dependency, not from a query parameter.
7. **`owner_id` exists on `workspaces` from day one**, populated with `"local"`.

Deliberately deferred: authentication, authorisation policy, quotas, per-user encryption
keys, workspace sharing, migration of the v1 single workspace into a user account
(a one-row `UPDATE` when the time comes).
