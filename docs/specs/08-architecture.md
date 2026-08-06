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
│                                                                           │
│    HaStatsClient (ha_fetch.js)  ── fetches from the user's Home Assistant  │
│      • wss://<user-ha>/api/websocket, auth with the long-lived token       │
│      • the token stays here; it never reaches the backend (§7.5)           │
│      • forwards raw rows to the backend over WS /data/ingest/ws            │
└──────┬────────────────────────────────────────────────┬───────────────────┘
       │  HTTP (fragments+JSON) · SSE /api/stream         │  wss:// (user's HA)
       │  · WS /data/ingest/ws (raw rows in)              ▼
       │                                          [ user's Home Assistant ]
┌──────▼─────────────────────────────────────────────────────────────────────┐
│  WEB LAYER — FastAPI                                                      │
│    routes/data.py     WS /data/ingest/ws   (browser-fetched rows in)      │
│                       POST /data/slot/{name}/load  (backend-load a slot)  │
│    routes/params.py   PATCH /params                                       │
│    routes/results.py  GET  /results  /results/export.csv                  │
│    routes/stream.py   GET  /api/stream           (SSE)                    │
│                                                                           │
│    NB: no feedback route. A pending control's thumbs-up is a LINK to a    │
│    pre-filled GitHub issue form; the backend serves nothing for it (§2.1).│
│                                                                           │
│    deps.py:  get_principal() -> Principal        ← v1 returns "local"      │
│              get_workspace(principal, id) -> Workspace                    │
└───────────────────────────┬───────────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────────┐
│  SERVICE LAYER  (orchestration, state machine, no numerics)               │
│    IngestService       streamed rows → SeriesFrames → persist             │
│    WorkspaceService    params CRUD, validation, dirty tracking            │
│    SimulationService   run_id, debounce, cancellation, LRU result cache   │
│    JobRunner           ProcessPoolExecutor keyed by workspace_id          │
└──────┬──────────────────────────────────────┬─────────────────────────────┘
       │                                      │
┌──────▼──────────────────────┐   ┌───────────▼────────────────────────────┐
│  ADAPTERS  (backend I/O)    │   │  DOMAIN  (pure functions, no I/O)      │
│    IngestSocket parser      │   │    ingest/     cumulative→delta        │
│    CsvLoader  (wide file →  │   │    normalize/  grid selection, resample│
│                one column)  │   │                                        │
│    DatasetStore (persist)   │   │    quality/    checks, flags           │
│                             │   │    pricing/    import/export curves    │
│    sources/  DataSource     │   │                                        │
│      HomeAssistantSource    │   │                                        │
│      EnergyChartsSource     │   │                                        │
└──────┬──────────────────────┘   │    policies/   charge + discharge      │
       │                          │    battery/    step function, limits   │
       │      NB: the HA fetch is  │    simulate/   main loop               │
       │      in the BROWSER, not  │    metrics/    KPIs, waterfall         │
       │      a backend adapter.   │    benchmark/  perfect-foresight DP    │
       │                          └────────────────────────────────────────┘
┌──────▼────────────────────────────────────────────────────────────────────┐
│  PERSISTENCE                                                              │
│    SQLite  (SQLAlchemy)                                                   │
│      workspaces(id, owner_id, title, created_at, updated_at)              │
│      datasets(id, workspace_id, source_type, fetched_at, coverage, qa)    │
│      series_meta(id, dataset_id, name, kind, resolution_s, path,          │
│                  fine_resolution_s, fine_coverage, source_type)           │
│      params(workspace_id, json, updated_at)          -- current config    │
│      runs(id, workspace_id, run_id, config_hash, result_json, created_at) │
│      uploads(id, workspace_id, filename, tz, columns_json, rows,          │
│              resolution_s, first_ts, last_ts, uploaded_at,                │
│              cumulative_columns_json, delimiter)                          │
│              -- one CSV file (§4.2a). `columns_json` is the parsed header │
│              -- as a JSON array (named for its encoding; a bare `columns` │
│              -- reads as a count), `tz` the zone the user declared at     │
│              -- upload. A slot's binding to one of these is in `params`,  │
│              -- since it is configuration, not data.                      │
│              -- `delimiter` is the field separator the user chose at      │
│              -- upload, by NAME: 'comma', 'semicolon' or 'tab'. Unlike    │
│              -- the display fields it is acted on -- the fetch path       │
│              -- re-parses the stored bytes and must use it. NULLABLE,     │
│              -- and NULL reads as 'comma': a row written before the       │
│              -- column existed was parsed with the comma default and      │
│              -- accepted under it, so the value is known, not unknown.    │
│              -- resolution_s / first_ts / last_ts are NULLABLE: a file    │
│              -- too irregular for a modal resolution is still a valid     │
│              -- upload, and the summary is for display, not validity.     │
│                                                                           │
│      -- Every table is workspace-keyed. `feature_interest` was the one    │
│      -- exception and is gone; see §5.5.                                  │
│                                                                           │
│      -- No credentials table: the HA token stays in the browser (§7.5).   │
│                                                                           │
│    Filesystem                                                             │
│      <data_dir>/<workspace_id>/series/<name>.npz                          │
│      <data_dir>/<workspace_id>/uploads/<upload_id>.csv                    │
│      -- <upload_id> is app-assigned, not the user's filename: two exports │
│      -- may share a name, and a name is not an identity (§2.2). The       │
│      -- original filename, the declared timezone and the parsed header    │
│      -- live in the `uploads` table beside it.                            │
└───────────────────────────────────────────────────────────────────────────┘
```

> **On series storage format.** The series arrays are persisted as NumPy `.npz` in this
> increment rather than Parquet, to avoid a pandas dependency for a store the domain layer
> reads back into plain arrays. The on-disk format is an implementation detail behind
> `DatasetStore`; a move to Parquet is a later change if columnar tooling is wanted.

### The data-source abstraction (`app/sources/`)

Which source fills which slot lives in an `app/sources/` package: a `SourceDescriptor` (the
drawer-facing metadata — key, label, kind, blurb), a `DataSource` protocol (`descriptor`,
`available_for(slot)`, `load(slot, window)`), and a registry that answers, for a given slot,
which sources may fill it. It has four implementations:

- **`HomeAssistantSource`** — kind `browser_fetch`, available for every slot. Its `load` does
  not run: an HA frame is produced by the browser→WS ingest path
  ([§4.3](06-home-assistant-ingestion.md)), not backend-side. The source object exists as the
  descriptor the drawer shows and the `available_for` rule.
- **`EnergyChartsSource`** — kind `backend_load`, available only for the `price_spot` slot. Its
  `load` reads the committed on-disk NL day-ahead prices and bridges the recent tail from the
  public API ([§4.3](06-home-assistant-ingestion.md)). This is the only source the backend
  fetches directly. The committed dataset lives at `app/data/spot_prices/` — **shipped content
  versioned with the app, not per-workspace runtime data** — so it sits beside the code rather
  than under `<data_dir>/<workspace_id>/`.
- **`EntsoeSource`** — kind `backend_load`, also available only for the `price_spot` slot: the
  same NL day-ahead series from an independent origin, the ENTSO-E transparency platform
  ([§4.3](06-home-assistant-ingestion.md)). Its `load` is purely on-disk with no bridge, so it
  makes no request. Its committed dataset sits alongside the other at
  `app/data/spot_prices_entsoe/`, in a format carrying one extra column: each interval's own
  native resolution, since the hourly and quarter-hourly regimes coexist within a single year.
  It is produced from the raw monthly ENTSO-E dumps by `scripts/extract_entsoe_prices.py`; the
  raw corpus itself is hundreds of megabytes and is **not** committed.
- **`CsvSource`** — kind `backend_load`, available for every **energy** slot (not `price_spot`,
  [§4.2a](05-data-formats.md#42a-the-wide-multi-series-file-format)). Its `load` reads the
  uploaded file named by the slot's binding and takes the one column that binding names,
  converting Wh→kWh if asked. It is a `backend_load` and not a third kind: the *bytes* arrive
  from the browser, but they arrive during a **separate, earlier** upload step, and by load time
  the file is ordinary server-side data read from `<data_dir>/<workspace_id>/uploads/`. Nothing
  about the load needs the browser, which is exactly what the kind means.

  The binding — `(upload_id, column, unit)` — is a per-slot **parameter**, not part of the
  descriptor, so `load` reads it from the slot's stored config. This is the one source whose
  `load` depends on more than `(slot, window)`, and the seam that carries it is the same one
  `EnergyChartsSource` already uses for its keyword-only extras.

  **Upload is its own route, not part of a fetch** (`POST /w/{id}/data/uploads`, returning the
  parsed header and coverage for the dialog to display). It writes an `uploads` row and the file,
  and touches no dataset: one upload serves many slots and many fetches, so tying it to a fetch
  would force a re-upload per run. Deleting an upload (`DELETE …/uploads/{upload_id}`) clears any
  slot binding that referenced it.

Backend-load slots are reified as part of a fetch: the browser declares each staged
`backend_load` slot over the ingest WS (a `backend_load` message), and the route loads it
server-side on `done` and folds the frame into the **same** dataset as the fetched HA series —
all-or-nothing, so a failed load fails the whole fetch and persists nothing. Source selection in
the drawer only stages; no dataset is written before a fetch (§3.5). `POST /data/slot/{name}/load`
remains as a standalone route that loads one `backend_load` source and merges its frame into the
current dataset (a `browser_fetch` source is rejected there, its frame arriving over the WS
instead); it is the same load logic the reify step uses, kept available though the drawer no
longer calls it. Per-series provenance is persisted in `series_meta.source_type` (the descriptor
key of the source that produced each series), so a dataset assembled from more than one source —
an HA-fetched set of energy meters with an Energy-Charts spot price loaded in — records where
each series came from.

**`app/sources/` is an adapter, not domain.** It does I/O — network, file, wall-clock — and
deciding *where data comes from* is precisely that. It therefore sits in the adapter layer, not
under `domain/`, and the domain-is-pure invariant (§5.2) is intact: nothing in `domain/`
reaches for a source. The protocol depends on domain *types* (`SeriesFrame`, `SlotSpec`), which
is the correct direction — an adapter may depend on the domain, not the reverse. A reader
expecting a thing called a "source" to live in `domain/` should read it as an adapter that
feeds the domain, the same way `CsvLoader` and `DatasetStore` do.

The `domain/` sub-packages map onto the specification files as follows:

| Package | Specification |
|---|---|
| `ingest/`, `normalize/` | [09-ingest-algorithms.md](09-ingest-algorithms.md) §6.1–6.3 |
| `quality/` | [14-diagnostics.md](14-diagnostics.md), [§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order), [13-configuration-epochs.md](13-configuration-epochs.md) |
| `pricing/` | [10-pricing.md](10-pricing.md) §6.5, plus §6.4 zone assignment |
| `policies/`, `battery/`, `simulate/` | [11-policies-and-battery.md](11-policies-and-battery.md) §6.6–6.9 |
| `metrics/` | [§6.10](10-pricing.md#610-cost-accounting) waterfall, [§6.11](12-metrics-and-benchmarks.md#611-metrics) |
| `benchmark/` | [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark) |

`cfg.simulate_cost` cuts across this table in one specific way: when it is false the
`pricing/` package is **not called at all**, and the waterfall half of `metrics/` is
skipped. They are not invoked with neutral parameters — there is no neutral tax rate, and a
run priced at zero everywhere would report a confident €0.00 saving rather than no answer.
`benchmark/` is called **once more** when the flag is set, not differently: the
import-minimising run happens in both modes and the cost-minimising run is added
([§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)). The distinction is
worth holding on to — a package that changes its objective on a flag produces different
numbers under the same heading, which is the one thing the optional-cost design forbids.
`policies/`, `battery/` and `simulate/` are unaffected and must stay that way: they consume
the spot price as a dispatch signal, which exists in both modes. Fixture 18 in
[16-validation-harness.md](16-validation-harness.md) asserts that everything except the
added cost outputs is bit-identical across the flag.

### Feature interest — no backend at all

A user asking for a control that is specified but not built yet
([§2.1](02-ux-wireframes.md#the-pending-affordance)) produces **no server-side state and no
outbound request**. The `[?]` dialog's thumbs-up is a link to a pre-filled GitHub issue form;
the browser follows it and the issue is the whole record.

The only backend involvement is composing the URL: a closed vocabulary of feature keys, each
with a human-readable title, rendered into the dialog as a key → URL map. Keys are never
renamed or repointed, because a key is the join between an issue already filed and the control
it was about.

**This replaced a `feature_interest(feature_key, count, last_clicked_at)` table and an
`InterestReporter` adapter** that POSTed to a configurable endpoint. Two things follow from
the removal, both of which simplify the surrounding design:

1. **§5.5's invariant 1 has no exceptions any more.** `feature_interest` was the sole
   installation-wide table, argued for at length here and in
   [20-workspaces-ux.md §2′.10](20-workspaces-ux.md#210-what-the-backend-needs-noted-not-designed)
   on the grounds that a feature request is a fact about the household rather than about one
   analysis. Every table is workspace-keyed again.
2. **The application has no egress adapter.** `InterestReporter` was the only component that
   sent anything to a host the user did not nominate as a data source. Nothing does now, which
   makes [§7.5](15-data-quality-and-limits.md#75-operational-notes)'s egress posture a property
   of the code rather than of a default setting someone could change.

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

Single `config.toml` next to the data directory: bind host/port, data dir, log level and
default parameter values. Environment variables override. There is **no HA-token
configuration and no token-encryption key**: the Home Assistant token stays in the browser and
is never stored server-side
([§4.3](06-home-assistant-ingestion.md), [§7.5](15-data-quality-and-limits.md#75-operational-notes)).

The file carried two more settings until feature requests moved to GitHub issues:
`feature_interest_url`, the outbound endpoint, empty by default; and `installation_id`, the
random pseudonymous identifier described in §7.5, generated on first run and written back.
Both are gone with the mechanism they served. **The app now writes no `config.toml` of its
own** — as implemented, the only setting it reads is the data directory, from the environment.

Neither preset spot-price source needs **any configuration**. For Energy-Charts the endpoint is
a fixed public URL, the NL bidding zone is hardcoded for now, and there is **no API key** — the
API is open. The ENTSO-E source reads only committed on-disk files and makes no request at all.
Nothing about either source appears in `config.toml`.

Default parameter values shipped in `config.toml` are listed in
[appendix-a-defaults.md](appendix-a-defaults.md).

## 5.5 Multi-user readiness (designed for, not implemented)

The following are v1 requirements *because* they make multi-tenancy a later additive
change rather than a rewrite:

1. **Every persisted row carries `workspace_id`.** No table is implicitly global. Every
   read path filters on it too — an omitted filter reintroduces the leak the column exists
   to prevent.

   **This invariant now holds without exception.** `feature_interest` was the one carve-out —
   keyed on `feature_key` alone and surviving the deletion of every workspace — argued for in
   [20-workspaces-ux.md §2′.10](20-workspaces-ux.md#210-what-the-backend-needs-noted-not-designed)
   on the grounds that interest counters were product telemetry rather than user data. The
   table is gone: feature requests are filed as GitHub issues
   ([§2.1](02-ux-wireframes.md#the-pending-affordance)) and nothing is stored locally. The
   argument that justified the exception is worth keeping in view anyway, because it is the
   test any future candidate has to pass — a row is exempt only if it is genuinely not user
   data, and `workspace_state.source_generation` is the standing example of one that is not
   exempt: it tracks one workspace's fetches, and sharing it would let a fetch in one analysis
   invalidate a source customization saved in another.
2. **`Workspace` is resolved via a FastAPI dependency**, never read from a global.
   In v1 `get_principal()` returns a hard-coded `Principal(id="local")`, and
   `get_workspace()` resolves the workspace named in the `/w/{workspace_id}/…` path and
   checks it against the principal. Adding auth means replacing `get_principal()` alone —
   `get_workspace()`'s ownership check already does its part unchanged.
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
keys, workspace sharing, and attaching the existing `"local"` owner's workspaces to a real
user account once one exists. `migrate_local` already adopted the pre-index installation
into the workspaces table under that owner, and an owner can hold many workspaces, so this
is no longer the one-row update it once was.

## 5.6 Named constants

No magic numbers in the code. Every numeric literal that carries meaning is named, so a
reader meets a word before a digit and a maintainer changes a value in one place. A literal
"carries meaning" when it encodes a decision — a tolerance, a window, a discretisation, a
threshold — as opposed to being arithmetically inevitable. Three homes, by who the value
belongs to:

1. **User-facing defaults** live in `config.toml` and are listed, with their rationale, in
   [appendix-a-defaults.md](appendix-a-defaults.md). These are values a user or packager
   may reasonably set: battery parameters, tariff constants, the dal window, the plausibility
   bounds a user with an atypical installation might raise, and any threshold that changes
   what the results panel shows. The appendix table *is* the checklist for `config.toml`
   (§5.4), so a new user-facing default is added in both places or neither.

2. **Internal tunables** live as module-level named constants in the code, next to the
   function that uses them, each with a comment giving the value's origin (a datasheet
   figure, a heuristic sensitivity, a discretisation chosen for speed). These have no user
   meaning and are not exposed in `config.toml` — surfacing them would grow the appendix
   with rows no user should touch. The DP discretisation levels are the boundary case:
   they are internal in nature but are named in the appendix
   (`dp_soc_levels`, `dp_action_levels`) because an experiment
   ([X13](19-prototype-experiments.md)) is *about* their values, so they are documented
   where that experiment can point at them.

   A named constant is a single value with a single meaning. Where one name would paper over
   two distinct quantities that merely happen to share a digit, use two — the point of the
   name is to make the decision legible, and conflating decisions defeats it. `EPS` is the
   cautionary example: the pseudocode in these specs originally wrote a single undefined
   `EPS` in four distinct roles. It is replaced by four constants, defined once in a shared
   numerics module and referenced from the pseudocode:

   | Constant | Value | Role |
   |---|---|---|
   | `DIV_GUARD_EPS` | `1e-9` | Floor on a denominator that is a physical total (`x / max(total, DIV_GUARD_EPS)`), to avoid divide-by-zero when the total is genuinely ~0. Dimensionless; it only prevents a NaN, it does not set a meaningful scale. |
   | `SOC_COMPARE_EPS_KWH` | `1e-6` | Float-comparison slack, in kWh, on SoC bound assertions and the DP terminal constraint, so rounding does not trip an exact `<=`. |
   | `STD_GUARD_EPS` | `1e-9` | Guard added to a standard-deviation denominator in the time-offset confidence score, where the std can be zero for a flat signal. |
   | `FLAT_SPAN_EPS_KWH` | `1e-6` | Threshold, in kWh, below which a register's observed span counts as flat (no variation) — a presence test, not a division guard. |

   `DIV_GUARD_EPS` and `STD_GUARD_EPS` share a value today but not a meaning, so they stay
   separate: one is a ratio denominator floor, the other a variance-denominator floor, and a
   future adjustment to one should not silently move the other.

3. **Genuine literals** are left as literals. `0`, `1`, array indices, percent conversions
   (`100 *`), unit conversions (`/ 1000.0` for W→kW, `3600` for h→s), and the calendar
   constant `dayofweek >= 5` for the weekend are arithmetically inevitable or self-evident
   in context, and naming them (`ONE = 1`) would add noise, not legibility. This category is
   deliberate: "no magic numbers" is a rule about *meaningful* values, not a mandate to name
   every digit.

The rule binds new code as written and the existing pseudocode in these specs, which has
been swept to obey it (see [changelog](../../changelog/) for the pass). When a value that
looks like a genuine literal turns out to encode a choice — the weekend mask omitting public
holidays, say ([§8.21](17-open-questions.md)) — that is a signal the classification was
wrong and the value wants a name and a decision, not that the rule has an exception.
