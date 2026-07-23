# 3. Application state machine

> **Purpose:** session states and transitions, run identity under rapid
> re-parameterisation, panel focus rules, and when state hits disk.
> **Audience:** frontend and backend.
> **Read with:** [02-ux-wireframes.md](02-ux-wireframes.md) for the panels these states
> drive, and [08-architecture.md](08-architecture.md) §5.1 for where each piece lives.

## 3.1 Session-level states

```
                         ┌──────────────┐
        app start ──────►│    EMPTY     │  no data, no params
                         └──────┬───────┘
                                │ SOURCE_CONFIGURED
                                ▼
                         ┌──────────────┐
              ┌─────────►│ DATA_LOADING │◄────── RELOAD_DATA
              │          └──────┬───────┘
              │                 │
              │        ┌────────┴────────┐
              │        │                 │
              │  LOAD_FAILED        LOAD_SUCCEEDED
              │        │                 │
              │        ▼                 ▼
              │  ┌───────────┐    ┌─────────────┐
              └──┤ DATA_ERROR│    │ DATA_READY  │
                 └───────────┘    └──────┬──────┘
                                         │ PARAMS_VALID
                                         ▼
                                  ┌─────────────┐
                                  │PARAMS_READY │
                                  └──────┬──────┘
                                         │ RUN_REQUESTED
                                         ▼
                         ┌───────────────────────────┐
             ┌──────────►│        SIMULATING         │
             │           └─────────────┬─────────────┘
             │                         │
             │              ┌──────────┴──────────┐
             │         RUN_FAILED            RUN_COMPLETED
             │              │                     │
             │              ▼                     ▼
             │        ┌───────────┐        ┌─────────────┐
             │        │ RUN_ERROR │        │RESULTS_FRESH│
             │        └─────┬─────┘        └──────┬──────┘
             │              │                     │
             │              │              INPUT_CHANGED
             │              │                     ▼
             │              │              ┌─────────────┐
             └──────────────┴──────────────┤RESULTS_STALE│
                        DEBOUNCE_ELAPSED   └─────────────┘
                                            (old results still
                                             displayed, dimmed)
```

**Key behaviour:** `RESULTS_STALE` continues to render the previous results, visually
dimmed, with a spinner. It never blanks the panel. This is what makes continuous
re-parameterisation feel responsive.

## 3.2 Events

| Event | Trigger | Effect |
|---|---|---|
| `SOURCE_CONFIGURED` | HA credentials tested OK, or every required CSV slot holds a file that passed validation | → `DATA_LOADING` |
| `LOAD_SUCCEEDED` | Ingest + normalise + QA complete | → `DATA_READY`, persist dataset |
| `LOAD_FAILED` | Network, auth, or a validation error against the assembled dataset | → `DATA_ERROR` with actionable message |
| `PARAMS_CHANGED` | Any field in panel ② | Validate; persist; if valid → `INPUT_CHANGED` |
| `RANGE_CHANGED` | Period selector in panel ③ | Persist; → `INPUT_CHANGED` |
| `INPUT_CHANGED` | From `PARAMS_CHANGED` / `RANGE_CHANGED` / `LOAD_SUCCEEDED` | → `RESULTS_STALE`, start debounce timer |
| `DEBOUNCE_ELAPSED` | `debounce_ms` (default 400) after last `INPUT_CHANGED` | → `SIMULATING`, enqueue run |
| `RUN_REQUESTED` | Explicit **Calculate** button | Bypass debounce → `SIMULATING` |
| `RUN_COMPLETED` | Worker finishes, `run_id` is current | → `RESULTS_FRESH` |
| `RUN_SUPERSEDED` | Worker finishes, `run_id` is stale | Discard result silently, no state change |
| `RUN_FAILED` | Exception in domain layer | → `RUN_ERROR`, previous results retained |
| `RELOAD_DATA` | User edits panel ① | → `DATA_LOADING` |

**Per-slot CSV validation is panel-local and emits nothing here.** On the CSV path the user
uploads one file per series into a named slot, and each file is validated against that
slot's expected format as it arrives
([§2.2](02-ux-wireframes.md#csv-variant-of-the-source-sub-panel)). A file that fails is
rejected on its own row, with the other slots untouched and the session state unchanged —
it never reaches `DATA_ERROR`. Downloading the wrong export from a supplier's website is an
ordinary event on this path, and the recourse is another file for the same slot, not a
restart. `SOURCE_CONFIGURED` fires only once every required slot holds a file that passed,
so the states below always describe an assembled dataset. This mirrors the Home Assistant
path, where filling in the mapping table likewise produces no session event until
**Fetch history**.

Two choices live in the **setup band** above panel ① (§2.1) rather than in a panel:
`has_pv` and `simulate_cost`. They change *which other fields and data slots exist* rather
than only their values, and this is why they are asked first — the data panel's slot roster
(§2.2), the parameter panel's boxes (§2.3) and the result panel's sections (§2.4) are all
derived from them. The band is available from `EMPTY` onward; it has no collapsed/expanded
panel state of its own (§3.4) and is never disabled, so both answers can be changed at any
point in the session, including after data is loaded.

Editing either answer emits an ordinary `PARAMS_CHANGED`; there is no separate event and no
new state. What it additionally requires is:

- **Validation runs against the field set implied by the new answer, not the old one.**
  Switching cost simulation off must clear any pending validation errors on contract fields
  that have just ceased to exist, or the panel reports itself invalid over fields the user
  can no longer see.
- **The panel ① slot roster is re-derived in place.** A slot that ceases to apply — the
  solar slot when PV is switched off, the `price_spot_min`/`price_spot_max` slots when cost
  simulation is switched off — is removed; a slot that begins to apply appears empty. A file
  or mapping already placed in a slot that still applies is **kept**, and `SOURCE_CONFIGURED`
  is re-evaluated against the new required set (a run may become blocked if a now-required
  slot is empty, or unblocked if the newly-absent slot was the only thing missing).
- **Values already entered are retained, not discarded**, so switching an answer back
  restores the previous configuration rather than resetting it to defaults.

`RESULTS_STALE` keeps rendering the previous results while the recalculation runs, which
means a run made with cost simulation on stays visible, dimmed, for the few hundred
milliseconds after the user switches it off. That is acceptable and needs no special
handling — the stale results are visibly dimmed and are replaced on `RUN_COMPLETED`.

## 3.3 Concurrency and run identity

A monotonically increasing `run_id` per workspace guards against out-of-order results:

```
on INPUT_CHANGED:
    session.run_id += 1
    cancel_pending_debounce()
    schedule_debounce(cfg.debounce_ms, run_id=session.run_id)

on DEBOUNCE_ELAPSED(run_id):
    if run_id != session.run_id: return          # superseded during debounce
    request_cancel(in_flight_run)                # cooperative, checked per chunk
    enqueue_simulation(run_id)

on worker finishes(run_id, result):
    if run_id != session.run_id:
        emit RUN_SUPERSEDED
    else:
        cache[run_id] = result
        emit RUN_COMPLETED
```

Cancellation is cooperative on the domain side: `simulate_core` checks a shared
`multiprocessing.Event` every 1,024 intervals — see
[§5.3](08-architecture.md#53-compute) and the main loop in
[§6.9](11-policies-and-battery.md#69-main-simulation-loop).

Results are pushed to the browser over **SSE** on `/api/stream`. HTMX swaps the results
fragment. Polling every `sse_poll_fallback_ms` (default 750) is an acceptable fallback if
SSE proves troublesome behind a reverse proxy.

## 3.4 Panel focus model

Panels are independent of session state; they have their own UI state:
`COLLAPSED_INCOMPLETE`, `EXPANDED`, `COLLAPSED_COMPLETE`. The CTA in panel *n* collapses
panel *n* and expands panel *n+1*. Panel ③ auto-expands on first `RUN_COMPLETED`.
Reopening panel ① or ② does **not** collapse panel ③ — the user must be able to watch
results change while editing parameters. This is the single most important interaction
detail in the app.

The **setup band** (§2.1) is not a panel and has no focus state. It is always expanded,
never collapses to a summary, and carries no CTA — it is a scope selector, not a step in
the stepper. It sits above panel ① and is editable throughout the session.

## 3.5 Persistence points

State is written to disk on: `LOAD_SUCCEEDED` (dataset), `PARAMS_CHANGED` (debounced
`params_persist_debounce_ms`, default 1000), `RANGE_CHANGED`, and `RUN_COMPLETED` (result
cache, last `result_cache_runs` = 5 runs). On startup the
server restores the most recent workspace and lands the user in `RESULTS_STALE`, then
immediately recalculates.

The tables and file layout behind these writes are in
[§5.1](08-architecture.md#51-diagram).
