# 3. Application state machine

> **Purpose:** session states and transitions, run identity under rapid
> re-parameterisation, what must stay visible together, and when state hits disk.
> **Audience:** frontend and backend.
> **Read with:** [02-ux-wireframes.md](02-ux-wireframes.md) for the contents of the surfaces
> these states drive, [20-workspaces-ux.md](20-workspaces-ux.md) for the screens they sit on —
> the states below are **per workspace** and are entered when a workspace is opened
> ([§2′.9](20-workspaces-ux.md#29-state-machine-revisited)) — and
> [08-architecture.md](08-architecture.md) §5.1 for where each piece lives.

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
| `SOURCE_CONFIGURED` | HA credentials tested OK, or every required CSV slot holds a validated file-and-column binding | → `DATA_LOADING` |
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

**CSV upload and column binding are panel-local and emit nothing here.** On the CSV path the
user uploads a file once and then binds one of its columns to each slot that needs it
([§2.2](02-ux-wireframes.md#the-csv-source)). Both steps are validated where they happen: a
malformed file is rejected in the upload dialog, and an unusable column is rejected on
selection in the drawer. Neither touches the other slots, any other uploaded file, or the
session state — it never reaches `DATA_ERROR`. Downloading the wrong export from a supplier's
website is an ordinary event on this path, and the recourse is another file or another column,
not a restart. `SOURCE_CONFIGURED` fires only once every required slot holds a binding that
passed, so the states below always describe an assembled dataset. This mirrors the Home
Assistant path, where filling in the mapping table likewise produces no session event until
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
  solar slot when PV is switched off, the existing-battery slots when the household declares
  no battery — is removed; a slot that begins to apply appears empty. Cost simulation no
  longer adds or removes any slot: the roster is the same in both cost modes. A file
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

## 3.4 Screen structure, and what must stay visible together

An earlier layout put data, parameters and results in three collapsible panels on one page,
each with its own focus state (`COLLAPSED_INCOMPLETE`, `EXPANDED`, `COLLAPSED_COMPLETE`) and a
CTA that collapsed one panel and expanded the next. That model is gone: the surfaces are now
screens ([§2′.5](20-workspaces-ux.md#25-configure-data),
[§2′.6](20-workspaces-ux.md#26-results)), so there is no collapse or expand to model and no
focus state to hold. The states in §3.1 are the only ones a surface has.

**The requirement the old model existed to protect survives, and is the reason for the screen
split that replaced it: the parameters and the results must be visible at the same time.** A
user changes a capacity in order to watch the answer move; a layout that takes the figures off
screen while the parameter is edited breaks the one loop the app exists to support. The old
model met this by refusing to collapse panel ③ when ① or ② was reopened. The current layout
meets it structurally — [§2′.6](20-workspaces-ux.md#the-controls-are-a-fixed-column-not-the-top-of-a-long-page)
puts the battery box and the period card in a **fixed control column that does not scroll**,
beside the result sections in a column that does. That is why parameters were not given a
screen of their own. This is the single most important interaction detail in the app, and any
future layout change has to keep it.

The fixed column replaced an earlier arrangement in which the controls and the results sat on
one long page and scrolled together. That satisfied the requirement only while the reader
stayed near the top: scrolling to the charts took the capacity field off screen, which is the
exact failure this paragraph describes. The requirement is unchanged — what changed is a
mechanism that met it conditionally being replaced by one that meets it at every scroll
position. (Below the `lg` breakpoint the screen falls back to the stacked, single-scroll form,
where the constraint is the viewport rather than the layout.)

`RESULTS_STALE` is the other half of the same requirement: it renders the previous results
dimmed rather than blanking them (§3.1), so an edit never leaves the user looking at nothing.

The **data summary** ([§2.3a](02-ux-wireframes.md#23a-the-data-summary--your-data-at-a-glance))
is a read-only section of the configure-data screen and drives no transition. It has nothing to
show until data exists, so it is **absent until `DATA_READY`** and renders from that point on,
re-rendering on every subsequent `RELOAD_DATA` (§3.2). The results screen repeats the same
figures over the selected range (§2.4), where they re-render on `RANGE_CHANGED`.

## 3.5 Persistence points

State is written to disk on: `LOAD_SUCCEEDED` (dataset), `PARAMS_CHANGED` (debounced
`params_persist_debounce_ms`, default 1000), `RANGE_CHANGED`, and `RUN_COMPLETED` (result
cache, last `result_cache_runs` = 5 runs).

**On startup the server renders the workspace list** ([§2′.2](20-workspaces-ux.md#22-the-workspace-list--the-apps-home-screen)),
which is outside the state machine: it reads stored config and dataset metadata for every
workspace and drives no transition. **No workspace is restored and nothing is recalculated
until one is opened**, and the states above apply from that point
([§2′.9](20-workspaces-ux.md#29-state-machine-revisited)). This replaces an earlier rule under
which the server restored the most recent workspace on startup and landed the user in
`RESULTS_STALE`, which was written when there was one implicit workspace and no list to land
on.

> **Specified but not built: the debounced parameter persist.** `PARAMS_CHANGED` is listed
> above as a persistence point debounced by `params_persist_debounce_ms`, and that debounce
> does not exist in the code — the constant is referenced by no implementation. Today a
> parameter edit is committed by the parameter box's `[ Calculate → ]` and by nothing else, so
> an edit left uncommitted is lost on navigation. Recorded here rather than quietly deleted
> because which of the two should change is a product decision: auto-persist matches what this
> section specifies, and an explicit commit matches what the screen currently affords.

The tables and file layout behind these writes are in
[§5.1](08-architecture.md#51-diagram).
