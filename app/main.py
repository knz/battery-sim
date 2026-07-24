"""FastAPI application entry point for the Home Battery Simulator.

This is the web layer described in specs/08-architecture.md §5.1. In this first increment it
does one thing: serve the single-page three-panel UI (specs/02-ux-wireframes.md) rendered
from a *static* sample view-model (app/sample_data.py). No service layer, no domain logic,
no persistence yet — the page shows the intended shape of the product, not real results.

The UI is bilingual (English / Dutch). Translation is server-side gettext (app/i18n.py): the
active locale is resolved per request (cookie → Accept-Language → English) and its catalog is
installed on the Jinja environment before rendering. The header carries a language toggle that
posts to /lang/{code}, which sets the `lang` cookie.

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

Routes:
    GET  /                          → the full page (index.html)
    POST /results                   → recompute panel ③ over a window; return the HTML fragment
    GET  /lang/{code}               → set the language cookie, redirect back
    POST /feature-interest/{key}    → record interest in a pending control; 204 on success
    WS   /data/ingest/ws            → stream browser-fetched HA rows in; persist SeriesFrames
    POST /data/slot/{name}/load     → load one slot from a backend_load source; merge + report
    /static/*                       → CSS, generated stylesheet, Plotly, topology SVGs

Run:  uv run uvicorn app.main:app --reload
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import (
    config,
    data_view,
    dataset,
    db,
    features,
    i18n,
    ingest_ws,
    interest,
    results_view,
    summary_view,
)
from app.domain import normalize
from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SLOT_BY_NAME
from app.sample_data import sample_view
from app.sources import registry
from app.sources.base import SourceKind

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Home Battery Simulator")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Config is resolved once at import time. This also generates and persists the installation_id
# on first run (app/config.py) so it is stable across restarts.
CONFIG = config.load()

# Jinja with the i18n extension so templates can call _() / gettext(). The active catalog is
# installed per request in index(), since it depends on the request's resolved locale.
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.add_extension("jinja2.ext.i18n")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Render the whole page from the static sample view-model, in the request's locale."""
    locale = i18n.resolve_locale(request)
    i18n.install_for(templates.env, locale)

    ctx = sample_view()
    # If a real dataset has been fetched and persisted, panel ① renders from it (specs §3.5);
    # otherwise it keeps the static sample as the empty state. Params/results stay sample until
    # their own increments land. A load failure falls back to the sample rather than 500ing.
    #
    # The data summary band (§2.3a) is shown ONLY once data has loaded: before the first fetch
    # there is nothing to summarise, so it is absent (§3.4). sample_view() always carries a
    # `data_summary`, so drop it here in the empty state and replace it with the COMPUTED band
    # once a dataset exists — the real §6.3/§6.11 battery-free figures over the persisted frames
    # (app/summary_view.py), no longer the sample. data_summary_from returns None when the frames
    # yield no simulatable grid, in which case the band is omitted exactly as in the empty state.
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
                loaded, results_view.resolve_window(loaded)
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
    return templates.TemplateResponse(request, "index.html", ctx)


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
    """
    loaded = dataset.load_latest()
    if loaded is None or not loaded.frames:
        raise HTTPException(status_code=409, detail="no dataset")

    # Parse the request into resolve_window's kwargs. period XOR (start, end); resolve_window
    # enforces the mutual exclusivity and validates, so we just marshal the ISO datetimes here
    # (tz-aware UTC, same convention as _parse_window / _as_utc).
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

    result = results_view.results_from(loaded, window)
    if result is None:
        raise HTTPException(status_code=409, detail="no simulatable data")

    # Install the request locale on the Jinja env (as index() does), then render the template
    # standalone. templates.env already has jinja2.ext.i18n; install_for makes _() resolve.
    # (The shared-env gettext install is a per-request mutation of module-level state — a
    # pre-existing app-wide concern index() already has; not worsened in kind here. See the
    # changelog follow-up.) The fragment reads only `results.*`, so no other context is passed.
    locale = i18n.resolve_locale(request)
    i18n.install_for(templates.env, locale)
    html = templates.env.get_template("_panel_results.html").render(results=result)
    return HTMLResponse(html)


@app.post("/feature-interest/{feature_key}", status_code=204)
async def feature_interest(feature_key: str):
    """Record a thumbs-up for a pending control and fire the optional outbound report.

    Rejects any key outside the closed vocabulary (app/features.py) with 404. On a known key
    the local counter is upserted (once per workspace+key, §5.1) and the outbound POST is
    scheduled fire-and-forget: the endpoint returns 204 regardless of whether that request
    succeeds, fails, or is disabled by an unset URL (§2.1, §5.1 invariants).
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
