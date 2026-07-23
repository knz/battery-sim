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
| `SOURCE_CONFIGURED` | HA credentials tested OK, or ≥1 CSV parsed | → `DATA_LOADING` |
| `LOAD_SUCCEEDED` | Ingest + normalise + QA complete | → `DATA_READY`, persist dataset |
| `LOAD_FAILED` | Network, auth, parse or validation error | → `DATA_ERROR` with actionable message |
| `PARAMS_CHANGED` | Any field in panel ② | Validate; persist; if valid → `INPUT_CHANGED` |
| `RANGE_CHANGED` | Period selector in panel ③ | Persist; → `INPUT_CHANGED` |
| `INPUT_CHANGED` | From `PARAMS_CHANGED` / `RANGE_CHANGED` / `LOAD_SUCCEEDED` | → `RESULTS_STALE`, start debounce timer |
| `DEBOUNCE_ELAPSED` | 400 ms after last `INPUT_CHANGED` | → `SIMULATING`, enqueue run |
| `RUN_REQUESTED` | Explicit **Calculate** button | Bypass debounce → `SIMULATING` |
| `RUN_COMPLETED` | Worker finishes, `run_id` is current | → `RESULTS_FRESH` |
| `RUN_SUPERSEDED` | Worker finishes, `run_id` is stale | Discard result silently, no state change |
| `RUN_FAILED` | Exception in domain layer | → `RUN_ERROR`, previous results retained |
| `RELOAD_DATA` | User edits panel ① | → `DATA_LOADING` |

## 3.3 Concurrency and run identity

A monotonically increasing `run_id` per workspace guards against out-of-order results:

```
on INPUT_CHANGED:
    session.run_id += 1
    cancel_pending_debounce()
    schedule_debounce(400ms, run_id=session.run_id)

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
fragment. Polling every 750 ms is an acceptable fallback if SSE proves troublesome behind
a reverse proxy.

## 3.4 Panel focus model

Panels are independent of session state; they have their own UI state:
`COLLAPSED_INCOMPLETE`, `EXPANDED`, `COLLAPSED_COMPLETE`. The CTA in panel *n* collapses
panel *n* and expands panel *n+1*. Panel ③ auto-expands on first `RUN_COMPLETED`.
Reopening panel ① or ② does **not** collapse panel ③ — the user must be able to watch
results change while editing parameters. This is the single most important interaction
detail in the app.

## 3.5 Persistence points

State is written to disk on: `LOAD_SUCCEEDED` (dataset), `PARAMS_CHANGED` (debounced
1 s), `RANGE_CHANGED`, and `RUN_COMPLETED` (result cache, last N=5 runs). On startup the
server restores the most recent workspace and lands the user in `RESULTS_STALE`, then
immediately recalculates.

The tables and file layout behind these writes are in
[§5.1](08-architecture.md#51-diagram).
