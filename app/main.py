"""FastAPI application entry point for the Home Battery Simulator.

This is the web layer described in specs/08-architecture.md §5.1. In this first increment it
does one thing: serve the single-page three-panel UI (specs/02-ux-wireframes.md) rendered
from a *static* sample view-model (app/sample_data.py). No service layer, no domain logic,
no persistence yet — the page shows the intended shape of the product, not real results.

The UI is bilingual (English / Dutch). Translation is server-side gettext (app/i18n.py): the
active locale is resolved per request (cookie → Accept-Language → English) and the matching
per-locale Jinja environment renders the response. Environments are built once per locale and
never mutated, so mixed-locale concurrent requests cannot cross-contaminate. The header carries
a language toggle that posts to /lang/{code}, which sets the `lang` cookie.

Beyond the scaffold, this layer now serves the pending affordance's back end
(specs/02-ux-wireframes.md §2.1, specs/08-architecture.md §5.1): POST /feature-interest/{key}
records a thumbs-up in the local counter (app/db.py) and fires the optional, fire-and-forget
outbound POST (app/interest.py). The counter write always succeeds and the endpoint always
returns success, whatever the outbound request does.

Beyond the pending affordance, this layer now serves the Home Assistant **data import**
(specs/06-home-assistant-ingestion.md, browser-fetch increment). The browser fetches statistics
from the user's own HA instance directly and streams the raw rows to `WS /data/ingest/ws`; the
backend normalises them into SeriesFrames (app/domain) and persists them (app/dataset.py) so
they survive a restart. No HA token ever reaches this backend — it stays in the browser.

Beyond the browser-fetch path, this layer serves the slot-first **backend_load** sources
(specs/02-ux-wireframes.md §2.2, specs/06-home-assistant-ingestion.md §4.3): POST
/data/slot/{slot_name}/load loads one slot from a backend source (e.g. the preset Energy-Charts
spot price) and merges the resulting series into the latest dataset via dataset.upsert_series —
without a browser round-trip and without discarding the other series. browser_fetch sources
(Home Assistant) are NOT loaded here; their frames still arrive over WS /data/ingest/ws.

Beyond panel ③, this layer serves **panel ② — the parameter form** (specs §2.3, §2.5, §3.2
`PARAMS_CHANGED`). POST /params coerces the submitted fields (app/params_view.py — coercion is the
form layer's job, `simconfig` rejects `str` on purpose), builds a `SimulationConfig`, validates it
against §7.3 checks 11/12, persists it ONLY when valid (app/simconfig_store.py) and returns the
re-rendered panel. An invalid submission re-renders with the user's own values still in the fields
and the errors bound inline per field. The persisted config drives panel ③: index(), POST /results
and POST /results/benchmark all read the same one, so a parameter change moves the results.

On startup (the `lifespan` below) the app adopts the pre-index single workspace into the
`workspaces` table (app/workspaces.py, specs/20-workspaces-ux.md §2′.10). This is phase 0 of the
workspaces restructure and changes nothing a user sees: every route below is still flat, and
still operates on `db.WORKSPACE_ID`.

Routes:
    GET  /                          → the full page (index.html)
    POST /params                    → validate + persist panel ②; return the HTML fragment
    POST /results                   → recompute panel ③ over a window; return the HTML fragment
    POST /results/benchmark         → the §6.12 perfect-foresight box for that window (slow; lazy)
    GET  /lang/{code}               → set the language cookie, redirect back
    POST /feature-interest/{key}    → record interest in a pending control; 204 on success
    WS   /data/ingest/ws            → stream browser-fetched HA rows in; persist SeriesFrames
    POST /data/slot/{name}/load     → load one slot from a backend_load source; merge + report
    /static/*                       → CSS, generated stylesheet, Plotly, topology SVGs

Run:  uv run uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import (
    config,
    data_view,
    dataset,
    db,
    features,
    i18n,
    ingest_ws,
    interest,
    params_view,
    results_view,
    simconfig_store,
    summary_view,
    workspaces,
)
from app.domain import normalize
from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SLOT_BY_NAME
from app.sample_data import sample_view
from app.sources import registry
from app.sources.base import SourceKind

BASE_DIR = Path(__file__).resolve().parent

log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup work: adopt the pre-index single workspace into the workspace index.

    `workspaces.migrate_local()` is idempotent — it inserts nothing once the index is non-empty,
    and nothing at all on a fresh installation with no config and no dataset on disk — so running
    it on every start is a `SELECT COUNT(*)` in the ordinary case.

    This is a lifespan rather than more import-time work beside `CONFIG` because it WRITES to the
    data directory. Importing `app.main` (a test collecting routes, a tooling import) must not
    create rows in whatever directory happens to be resolved at import time; a lifespan runs only
    when the app is actually served, which is when a data directory has been chosen deliberately.
    A migration failure is logged and swallowed: the app must still serve, and the list route
    reads the index rather than depending on this having succeeded.
    """
    try:
        workspaces.migrate_local()
    except Exception:  # pragma: no cover - defensive: startup must not be fatal
        log.exception("workspace migration failed (ignored)")
    yield


app = FastAPI(title="Home Battery Simulator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Config is resolved once at import time. This also generates and persists the installation_id
# on first run (app/config.py) so it is stable across restarts.
CONFIG = config.load()

# Jinja environments live in app/i18n.py: one per locale, built on first use from this package's
# templates/ directory and never mutated afterwards, so concurrent requests in different languages
# cannot interleave a catalog install with someone else's render (see i18n.env_for). Routes render
# via `i18n.env_for(locale).get_template(...)`; there is no shared mutable environment here.


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Render the whole page from the static sample view-model, in the request's locale."""
    locale = i18n.resolve_locale(request)

    ctx = sample_view()

    # Panel ② (§2.3) renders from the PERSISTED parameter set — appendix-A defaults until the
    # user submits the form, and appendix-A defaults again if the stored file is unreadable
    # (simconfig_store.load never raises, so the page always renders). The setup band above panel
    # ① reads has_pv / simulate_cost off the same config, so `cfg` is replaced too: it used to be
    # the static sample dict, and leaving it would let the band and the panel disagree.
    cfg = simconfig_store.load()
    ctx["params"] = params_view.params_view(cfg)
    ctx["cfg"] = {
        "has_pv": cfg.has_pv,
        "has_battery": cfg.has_battery,
        "simulate_cost": cfg.simulate_cost,
    }

    # If a real dataset has been fetched and persisted, panel ① renders from it (specs §3.5);
    # otherwise it keeps the static sample as the empty state. Params/results stay sample until
    # their own increments land. A load failure falls back to the sample rather than 500ing.
    #
    # The data summary (§2.3a) is shown ONLY once data has loaded: before the first fetch
    # there is nothing to summarise, so it is absent (§3.4). sample_view() always carries a
    # `data_summary`, so drop it here in the empty state and replace it with the COMPUTED figures
    # once a dataset exists — the real §6.3/§6.11 battery-free figures over the persisted frames
    # (app/summary_view.py), no longer the sample. data_summary_from returns None when the frames
    # yield no simulatable grid, in which case it is omitted exactly as in the empty state.
    has_dataset = False
    try:
        loaded = dataset.load_latest()
        if loaded is not None and loaded.frames:
            ctx["data"] = data_view.panel_data_from(loaded)
            ctx["data_summary"] = summary_view.data_summary_from(loaded)
            has_dataset = ctx["data_summary"] is not None
            # Panel ③ (§2.4): render the COMPUTED energy-savings view-model over the default
            # window (last_1_year, coverage-anchored) instead of the static sample. Like
            # data_summary, results_from returns None when the frames yield no simulatable grid —
            # in that case the sample ctx["results"] stays as the empty-state fallback.
            computed_results = results_view.results_from(
                loaded, results_view.resolve_window(loaded), cfg=cfg
            )
            if computed_results is not None:
                ctx["results"] = computed_results
    except Exception:  # pragma: no cover - defensive: a corrupt dataset must not break the page
        pass
    if not has_dataset:
        ctx.pop("data_summary", None)
    ctx["lang"] = {
        "current": locale,
        "options": [{"code": c, "label": c.upper()} for c in i18n.SUPPORTED],
    }
    # The source generation (specs §2.2): rendered so the browser can reconcile its locally-saved
    # source customizations. Bumped only by a persisted HA fetch; 0 before the first one.
    ctx["source_generation"] = db.source_generation()
    return HTMLResponse(i18n.env_for(locale).get_template("index.html").render(**ctx))


@app.post("/params", response_class=HTMLResponse)
async def params(request: Request):
    """Validate and persist the panel-② parameter set, and return the re-rendered panel (§3.2).

    **Why a form POST returning a fragment, and not JSON.** Panel ② is a form of ~20 inputs whose
    re-render has to carry per-field errors next to the inputs that caused them. Sending JSON and
    re-rendering client-side would mean a second, JS-side copy of the label/gating/translation
    logic that `params_view` already owns; returning the rendered panel keeps ONE renderer. It is
    also the pattern already established for panel ③ (`POST /results` → fragment → `outerHTML`
    swap, delegated listeners in index.html), so the browser side is three lines.

    The sequence, which is §3.2's `PARAMS_CHANGED` ("Validate; persist; if valid → INPUT_CHANGED"):

        1. read the submitted form and COERCE it (params_view.parse_form) — `"3"` → `3`, an empty
           field → None, a non-numeric entry left as the RAW STRING so the user sees it back;
        2. build the candidate on top of the STORED config, so settings this form does not draw
           (the cost-only parameters appendix A says are retained) survive;
        3. `validate()` — §7.3 checks 11 and 12;
        4. persist ONLY when nothing blocks. Warnings (check 12: band overlap) do not block, per
           §6.7, so an overlapping configuration IS saved and IS simulated;
        5. re-render the panel from the CANDIDATE either way. On failure that is what puts the
           user's own values back in the fields with the errors attached — re-rendering the
           STORED config instead would silently discard what they typed.

    Construction never raises whatever is submitted (that is `SimulationConfig`'s guarantee, and
    this route depends on it), so there is no 500 path here: a malformed body is a 400 from
    Starlette's form parser, and any other value becomes a field error. A data directory that
    cannot be written is not a 500 either — the panel comes back with a notice saying the values
    apply but were not stored (step 4 above).

    Response: the rendered `_panel_params.html`, with `X-Params-Valid: 1|0` so the browser knows
    whether to refresh panel ③ without parsing the HTML. A 200 is returned in both cases — an
    invalid submission is a rendered form, not a failed request.
    """
    try:
        form = await request.form()
    except Exception as exc:  # an unparseable body is a client error, not a server one
        raise HTTPException(status_code=400, detail=f"invalid form body: {exc}") from exc

    stored = simconfig_store.load()
    candidate = params_view.parse_form(form, stored)
    result = candidate.validate()
    save_error = False

    if not result.blocking:
        try:
            # `guard_submitted` reports whether THIS form drew the economic-guard checkbox, which
            # is the only way the store can tell an unticked box from an absent control — see
            # simconfig_store's carry-forward rule and appendix A's retention requirement.
            simconfig_store.save(
                candidate, guard_submitted=params_view.guard_was_submitted(form, stored)
            )
        except OSError as exc:
            # A save that silently did nothing would tell the user their parameters were stored
            # when they were not — so this is reported, never swallowed. But a data directory that
            # is read-only or full is a foreseeable local condition, not a bug in the server, and
            # a 500 would leave the panel showing the submitted values with no explanation. It is
            # surfaced instead as a panel-level notice beside the form, which is the same place
            # every other non-field problem is reported.
            log.warning("could not save parameters: %s", exc)
            save_error = True

    locale = i18n.resolve_locale(request)
    html = i18n.env_for(locale).get_template("_panel_params.html").render(
        params=params_view.params_view(candidate, result, save_error=save_error),
        cfg={
            "has_pv": candidate.has_pv,
            "has_battery": candidate.has_battery,
            "simulate_cost": candidate.simulate_cost,
        },
    )
    return HTMLResponse(html, headers={"X-Params-Valid": "0" if result.blocking else "1"})


@app.post("/results", response_class=HTMLResponse)
def results(request: Request, body: dict = Body(...)):
    """Recompute panel ③ over a requested window and return the rendered fragment (specs §3.2).

    The period/date picker in panel ③ POSTs here to recompute the ENERGY SAVINGS view-model over
    a sub-window without a full page reload. The response is the rendered `_panel_results.html`
    fragment (HTML, not JSON) so the browser swaps it in place (main.py: index() renders the same
    template as part of the page; here it is rendered standalone).

    Body (mutually exclusive):
        {"period": "<preset>"}            — one of results_view.PERIOD_DAYS, coverage-anchored, OR
        {"start": "<iso>", "end": "<iso>"} — an explicit range (tz-aware UTC, like _parse_window).

    Errors are clean 4xx/409, never a 500 stack trace:
        * no persisted dataset → 409 (the picker only appears once a dataset exists, so this is an
          edge case — e.g. the dataset was cleared in another tab);
        * a bad request (unknown preset, empty/out-of-coverage range, both period and range) →
          400 (resolve_window raises ValueError);
        * frames that yield no simulatable grid → 409 (results_from returns None).

    The §6.12 benchmark box is NOT computed here — see `results_benchmark`. The fragment carries a
    placeholder the browser fills in with a second request, so a range change repaints at ~0.13 s
    instead of waiting ~4.6 s for the DP.
    """
    loaded, window = _resolve_results_window(body)

    # The SAME persisted parameter set index() and /results/benchmark read, so the three cannot
    # disagree about which battery the panel is describing.
    result = results_view.results_from(loaded, window, cfg=simconfig_store.load())
    if result is None:
        raise HTTPException(status_code=409, detail="no simulatable data")

    # Render the fragment standalone from the request locale's environment (as index() does).
    # The fragment reads only `results.*`, so that is the whole context.
    locale = i18n.resolve_locale(request)
    html = i18n.env_for(locale).get_template("_panel_results.html").render(results=result)
    return HTMLResponse(html)


def _resolve_results_window(body: dict):
    """Turn a `POST /results`-shaped body into (loaded_dataset, window), or raise a clean 4xx.

    Shared by `POST /results` and `POST /results/benchmark` so the two cannot drift on which
    requests they accept or on which status code each failure gets. The contract, unchanged from
    what `/results` already had:

        {"period": "<preset>"}             — one of results_view.PERIOD_DAYS, coverage-anchored, OR
        {"start": "<iso>", "end": "<iso>"} — an explicit range (tz-aware UTC, like _parse_window).

    Errors are clean 4xx/409, never a 500 stack trace:
        * no persisted dataset → 409;
        * an unparseable date → 400;
        * an unknown preset, an empty/out-of-coverage range, or both period and range → 400
          (resolve_window raises ValueError).
    """
    loaded = dataset.load_latest()
    if loaded is None or not loaded.frames:
        raise HTTPException(status_code=409, detail="no dataset")

    # period XOR (start, end); resolve_window enforces the mutual exclusivity and validates, so we
    # just marshal the ISO datetimes here (tz-aware UTC, same convention as _parse_window/_as_utc).
    period = body.get("period")
    start_raw = body.get("start")
    end_raw = body.get("end")
    kwargs: dict = {}
    if period is not None:
        kwargs["period"] = period
    if start_raw is not None or end_raw is not None:
        try:
            if start_raw is not None:
                kwargs["start"] = _as_utc(datetime.fromisoformat(start_raw))
            if end_raw is not None:
                kwargs["end"] = _as_utc(datetime.fromisoformat(end_raw))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid date: {exc}") from exc

    try:
        window = results_view.resolve_window(loaded, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return loaded, window


@app.post("/results/benchmark", response_class=HTMLResponse)
def results_benchmark(request: Request, body: dict = Body(...)):
    """Compute §6.12's perfect-foresight benchmark over a window and return just that card.

    **This route exists because the DP is slow.** It costs ~2.3 s per pass on a year of hourly data
    — ~4.6 s for both export baselines — against ~0.12 s for everything else panel ③ shows, and
    running it inline made `GET /` take 4.72 s against 0.13 s without it. Cost scales linearly with
    window length (1 week 0.04 s, 30 days 0.19 s, 3 months 0.57 s, 1 year 2.29 s per DP), so only
    long windows are affected. The panel now paints from the §6.11 figures immediately and the
    browser fetches this afterwards, filling the `#benchmark-slot` placeholder in. Nothing is
    cached — that option was considered and lazy loading was chosen instead.

    Same request shape and the same clean 4xx/409 error conditions as `POST /results` (both go
    through `_resolve_results_window`), so a window the panel could render is never one the box
    rejects. The response body is `_benchmark_box.html`'s output, not the whole panel.

    **It returns BOTH boxes when cost simulation is on**, each wrapped in a container carrying the
    slot id it belongs in, and the browser distributes them. Runs D and E are both gated on
    `with_benchmark`, so this request pays for both DPs either way; returning one box and
    discarding the other would spend ~2.3 s and throw the result away. One route, one fetch, one
    DP bill. With cost simulation off the response is the energy box alone, unwrapped exactly as
    before, so nothing about the energy path's contract changes.

    A window with no simulatable grid → 409, exactly as `/results`. The benchmark key can also be
    absent when there WAS a grid but no intervals to simulate; that is a 409 too, since there is no
    box to return and the placeholder's failure path is the honest outcome.
    """
    loaded, window = _resolve_results_window(body)

    result = results_view.results_from(
        loaded, window, cfg=simconfig_store.load(), with_benchmark=True
    )
    if result is None or "benchmark" not in result:
        raise HTTPException(status_code=409, detail="no simulatable data")

    locale = i18n.resolve_locale(request)
    # The partial reads `benchmark.*` only (it is written to be renderable standalone), so that is
    # the whole context.
    box = i18n.env_for(locale).get_template("_benchmark_box.html")
    html = box.render(benchmark=result["benchmark"])

    # The money box rides along when there is one. Wrapped with its target slot id so the fetch
    # handler can place each box without the response needing to be JSON — the energy box keeps
    # its bare-HTML shape when it travels alone, which is what the existing handler expects.
    # `cost=True` is presentation only: it tints the money box's heading with .cost-label, the
    # same flag _panel_results.html passes when it renders this partial inline.
    cost_bench = result.get("cost_benchmark")
    if cost_bench is not None:
        html = (
            f'<div data-slot="benchmark-slot">{html}</div>'
            f'<div data-slot="cost-benchmark-slot">'
            f"{box.render(benchmark=cost_bench, cost=True)}</div>"
        )
    return HTMLResponse(html)


@app.post("/feature-interest/{feature_key}", status_code=204)
async def feature_interest(feature_key: str):
    """Record a thumbs-up for a pending control and fire the optional outbound report.

    Rejects any key outside the closed vocabulary (app/features.py) with 404. On a known key
    the local counter is upserted (once per key, installation-wide) and the outbound POST is
    scheduled fire-and-forget: the endpoint returns 204 regardless of whether that request
    succeeds, fails, or is disabled by an unset URL (§2.1, §5.1 invariants).

    This route stays FLAT — unscoped by workspace — where the rest are being re-rooted under
    `/w/{id}/…`. The counter records what this household wants, not what one analysis wants
    (specs/20-workspaces-ux.md §2′.10; see app/db.py for the invariant-1 exception).
    """
    if not features.is_known(feature_key):
        raise HTTPException(status_code=404, detail="unknown feature key")

    db.record_interest(feature_key)
    # Fire-and-forget: awaiting would tie the response to the outbound request, which the spec
    # forbids. report() no-ops when no endpoint is configured.
    asyncio.get_running_loop().create_task(interest.report(feature_key, CONFIG))
    return Response(status_code=204)


@app.websocket("/data/ingest/ws")
async def data_ingest_ws(ws: WebSocket):
    """Stream browser-fetched HA statistics rows in; normalise, persist, and report back.

    Protocol in app/ingest_ws.py: a `header`, then `series`/`rows` batches per mapped series,
    then `done`. The backend accumulates in an `IngestSession`, and on `done` builds SeriesFrames
    (app/domain), persists them (app/dataset.save_dataset), and returns a `result` frame with the
    dataset id, series count, ingest warnings, and the panel-① grid report (specs §6.2).

    A protocol or validation error is reported as an `error` frame and closes the socket without
    persisting — the LOAD_FAILED path (specs §3.2). No HA token is ever received here (§7.5).
    """
    await ws.accept()
    session = ingest_ws.IngestSession()
    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            try:
                if mtype == "header":
                    session.on_header(msg)
                elif mtype == "series":
                    session.on_series(msg)
                elif mtype == "rows":
                    total = session.on_rows(msg)
                    await ws.send_json({"type": "progress", "name": msg.get("name"), "rows": total})
                elif mtype == "backend_load":
                    session.on_backend_load(msg)
                elif mtype == "done":
                    ha_frames, warnings, window = session.finish()
                    # Reify the whole staged config into ONE dataset (specs §2.2, §3.5): the HA
                    # frames plus each staged backend-load slot, loaded server-side now. This is
                    # the only place a fetch's backend slots are loaded — the drawer no longer
                    # persists them on Confirm. Per-series provenance records where each came from.
                    sources_map: dict[str, str] = {f.name: "home_assistant" for f in ha_frames}
                    backend_frames = []
                    # All-or-nothing: load every backend slot BEFORE persisting. Any failure raises
                    # IngestError → LOAD_FAILED and nothing is written, so a fetch never yields a
                    # partial dataset.
                    for req in session.backend_loads.values():
                        frame = await asyncio.to_thread(
                            _load_backend_frame, req.name, req.source, req.window
                        )
                        backend_frames.append(frame)
                        sources_map[frame.name] = req.source

                    frames = ha_frames + backend_frames
                    # Persistence is I/O, so it runs off the event loop (specs §5.1 adapters).
                    dataset_id = await asyncio.to_thread(
                        dataset.save_dataset,
                        frames, window, session.source or "home_assistant", warnings, sources_map,
                    )
                    # A persisted fetch is the one event that advances the source generation
                    # (specs §2.2): it establishes new server-side authority, so any client's
                    # locally-saved source customization tagged with an older generation yields to
                    # the server after this. This is the ONLY bump site.
                    generation = await asyncio.to_thread(db.bump_source_generation)
                    # The setup-band answers this fetch carried (specs §2.1): persisted HERE,
                    # after the dataset, because the fetch button is what commits the whole data
                    # configuration and these two answers are part of it.
                    #
                    # Deliberately AFTER the save and outside its all-or-nothing guarantee: a
                    # failed fetch must leave the answers alone (nothing was loaded to describe),
                    # while a config that cannot be written must not discard a dataset that was.
                    # The mismatch it risks — a stored dataset whose answers did not persist — is
                    # self-correcting, since the next fetch writes both again.
                    await asyncio.to_thread(
                        _persist_setup_answers, session.setup_has_pv, session.setup_has_battery
                    )
                    report = normalize.grid_report(frames, window)
                    await ws.send_json(
                        {
                            "type": "result",
                            "dataset_id": dataset_id,
                            "series": len(frames),
                            "warnings": warnings,
                            "grid": _jsonable_grid(report),
                            "generation": generation,
                        }
                    )
                    await ws.close()
                    return
                else:
                    raise ingest_ws.IngestError(f"unknown message type: {mtype!r}")
            except ingest_ws.IngestError as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
                await ws.close()
                return
    except WebSocketDisconnect:
        # Client vanished mid-stream; nothing was persisted, nothing to clean up.
        return


def _persist_setup_answers(has_pv: bool | None, has_battery: bool | None) -> None:
    """Write the setup-band answers a fetch carried onto the stored config (specs §2.1).

    Called from the WS `done` handler on a worker thread (file I/O). Either answer may be None,
    meaning the header did not carry it — an older client — in which case the stored answer is
    left as it is rather than reset to a default.

    NEVER RAISES. It runs after the dataset has already been persisted and the source generation
    bumped, so an exception here would fail a fetch whose real work succeeded, and the browser
    would report LOAD_FAILED for a dataset that is on disk. A data directory that cannot be
    written is logged and the answers are simply not updated; the next fetch writes them again.

    `guard_submitted=False` is correct: this path draws no panel-② form at all, so it must take
    the store's carry-forward branch for `economic_guard` rather than claim the box was shown and
    left unticked (which would clear a setting appendix A says is retained).
    """
    if has_pv is None and has_battery is None:
        return
    try:
        stored = simconfig_store.load()
        if has_pv is not None:
            stored.has_pv = has_pv
        if has_battery is not None:
            stored.has_battery = has_battery
        # Re-clone before saving. has_pv drives forced invariants (§2.5: pv_coupling → None,
        # coupling → AC), and assigning the field above bypasses `__post_init__` — so a household
        # that just turned PV off would otherwise keep a stored DC coupling for an array it does
        # not have. `clone` reconstructs through the dataclass, which re-applies the forcing.
        simconfig_store.save(simconfig_store.clone(stored), guard_submitted=False)
    except Exception:  # pragma: no cover - defensive, see the docstring
        log.warning("could not persist setup answers after fetch", exc_info=True)


def _jsonable_grid(report: dict) -> dict:
    """Grid report → JSON-safe dict (grid_s and native_resolution_s are already ints/None)."""
    # normalize.grid_report already emits plain ints/strings/None; this is a pass-through guard
    # kept explicit so a future numpy leak is caught here rather than at ws.send_json.
    return report


# The one source kind this endpoint loads. browser_fetch sources (Home Assistant) are shown in
# the drawer but their frames arrive over WS /data/ingest/ws — asking to load one here is a
# client error, not something the backend can do (the HA token stays in the browser, specs §7.5).
_BACKEND_LOAD: SourceKind = "backend_load"


def _resolve_backend_source(slot_name: str, source_key: str):
    """Resolve (slot, source) for a backend-load of `slot_name` from `source_key`.

    Shared by the WS reify path and POST /data/slot/{slot}/load. Raises ValueError with a
    user-facing message on any of: unknown slot, unknown source, source not available for the
    slot, or a non-backend_load source (a browser_fetch source's data arrives over the WS, not a
    load). Each caller translates ValueError into its own error type (IngestError / HTTPException).
    """
    slot = SLOT_BY_NAME.get(slot_name)
    if slot is None:
        raise ValueError(f"unknown slot: {slot_name!r}")
    if not source_key:
        raise ValueError("missing source")
    try:
        source = registry.get_source(source_key)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not source.available_for(slot):
        raise ValueError(f"source {source_key!r} is not available for slot {slot_name!r}")
    if source.descriptor.kind != _BACKEND_LOAD:
        raise ValueError(
            f"source {source_key!r} is a {source.descriptor.kind!r} source; its data arrives "
            "over the ingest WebSocket, not a backend load"
        )
    return slot, source


def _load_backend_frame(slot_name: str, source_key: str, window) -> SeriesFrame:
    """Load one staged backend-load slot into a frame (WS reify path, specs §2.2).

    Runs on a worker thread (called via asyncio.to_thread). Raises ingest_ws.IngestError on any
    validation or load failure so the WS route reports LOAD_FAILED and persists nothing — the
    all-or-nothing reify contract. The window is normalised to tz-aware UTC like the endpoint.
    """
    try:
        slot, source = _resolve_backend_source(slot_name, source_key)
    except ValueError as exc:
        raise ingest_ws.IngestError(str(exc)) from exc
    win = (_as_utc(window[0]), _as_utc(window[1]))
    try:
        return source.load(slot, win)
    except Exception as exc:  # network down / rate-limited / parse failure
        raise ingest_ws.IngestError(
            f"could not load {slot_name!r} from {source_key!r}: {exc}"
        ) from exc


@app.post("/data/slot/{slot_name}/load")
async def load_slot(slot_name: str, body: dict = Body(...)):
    """Load one slot from a backend_load source and merge its series into the latest dataset.

    Body: {"source": "<source_key>", "window": {"start": "<iso>", "end": "<iso>"}}. The window is
    parsed like the WS ingest header (tz-aware ISO, end > start). The source is looked up in the
    registry, must offer this slot, and must be a backend_load source — a browser_fetch source
    (Home Assistant) is rejected here because its frame arrives over the ingest WS, not this call.

    The source's `load` and the `upsert_series` merge both do file/network I/O, so they run off the
    event loop (asyncio.to_thread). On success the response reports the dataset id, the series name,
    its resolution and interval count, and the panel-① grid report (the same shape the WS path
    returns) so the caller can re-render without a full reload. Unknown slot/source, an unavailable
    or wrong-kind source, and a load/network failure all return a clean 4xx/5xx JSON error rather
    than a 500 stack trace (specs §3.2 LOAD_FAILED).
    """
    # 1–3. Resolve and validate the (slot, source): unknown slot/source → 404, unavailable or
    # wrong-kind source → 400. Shared with the WS reify path via _resolve_backend_source.
    source_key = body.get("source")
    try:
        slot, source = _resolve_backend_source(slot_name, source_key)
    except ValueError as exc:
        msg = str(exc)
        status = 404 if msg.startswith("unknown ") else 400
        raise HTTPException(status_code=status, detail=msg) from exc

    # 4. Parse the window (same shape as ingest_ws.on_header: tz-aware ISO, end > start).
    window = _parse_window(body.get("window"))

    # 5. Load off the event loop (file + possible network I/O), then merge off the event loop.
    try:
        frame = await asyncio.to_thread(source.load, slot, window)
    except HTTPException:
        raise
    except Exception as exc:  # network down / rate-limited / parse failure → clean 502
        raise HTTPException(
            status_code=502,
            detail=f"could not load {slot_name!r} from {source_key!r}: {exc}",
        ) from exc

    dataset_id = await asyncio.to_thread(dataset.upsert_series, frame, source_key, window)
    report = normalize.grid_report([frame], window)
    return JSONResponse(
        {
            "dataset_id": dataset_id,
            "series": frame.name,
            "resolution_s": frame.resolution_s,
            "intervals": int(len(frame.values)),
            "grid": _jsonable_grid(report),
        }
    )


def _parse_window(raw) -> tuple[datetime, datetime]:
    """Parse a {"start","end"} ISO window; always tz-aware UTC; HTTPException(400) on error.

    A client may send an ISO instant with or without an offset. `datetime.fromisoformat` returns
    naive-or-aware faithfully, but the whole pipeline holds UTC (specs §4.4) and downstream code
    mixes this window with tz-aware datetimes read back from storage (dataset.upsert_series widens
    the stored window with min/max). Comparing a naive with an aware datetime raises TypeError, so
    a bare-offset window must not reach that code — normalise here: a naive instant is assumed UTC,
    an aware one is converted to UTC. This is the one boundary where the tz decision is made.
    """
    raw = raw or {}
    try:
        start = _as_utc(datetime.fromisoformat(raw["start"]))
        end = _as_utc(datetime.fromisoformat(raw["end"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid window: {exc}") from exc
    if end <= start:
        raise HTTPException(status_code=400, detail="window end must be after start")
    return start, end


def _as_utc(dt: datetime) -> datetime:
    """Attach UTC to a naive datetime, or convert an aware one to UTC (specs §4.4 UTC pipeline)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@app.get("/lang/{code}")
def set_language(code: str, request: Request):
    """Set the language cookie and redirect back to the referring page (or /)."""
    target = request.headers.get("referer") or "/"
    response = RedirectResponse(target, status_code=303)
    if code in i18n.SUPPORTED:
        # 1-year cookie; lax so a normal top-level navigation carries it.
        response.set_cookie(i18n.COOKIE_NAME, code, max_age=31_536_000, samesite="lax")
    return response
