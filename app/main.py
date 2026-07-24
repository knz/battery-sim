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

Routes:
    GET  /                          → the full page (index.html)
    GET  /lang/{code}               → set the language cookie, redirect back
    POST /feature-interest/{key}    → record interest in a pending control; 204 on success
    WS   /data/ingest/ws            → stream browser-fetched HA rows in; persist SeriesFrames
    /static/*                       → CSS, generated stylesheet, Plotly, topology SVGs

Run:  uv run uvicorn app.main:app --reload
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config, data_view, dataset, db, features, i18n, ingest_ws, interest
from app.domain import normalize
from app.sample_data import sample_view

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
    try:
        loaded = dataset.load_latest()
        if loaded is not None and loaded.frames:
            ctx["data"] = data_view.panel_data_from(loaded)
    except Exception:  # pragma: no cover - defensive: a corrupt dataset must not break the page
        pass
    ctx["lang"] = {
        "current": locale,
        "options": [{"code": c, "label": c.upper()} for c in i18n.SUPPORTED],
    }
    return templates.TemplateResponse(request, "index.html", ctx)


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
                elif mtype == "done":
                    frames, warnings, window = session.finish()
                    # Persistence is I/O, so it runs off the event loop (specs §5.1 adapters).
                    dataset_id = await asyncio.to_thread(
                        dataset.save_dataset, frames, window, session.source or "home_assistant", warnings
                    )
                    report = normalize.grid_report(frames, window)
                    await ws.send_json(
                        {
                            "type": "result",
                            "dataset_id": dataset_id,
                            "series": len(frames),
                            "warnings": warnings,
                            "grid": _jsonable_grid(report),
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


@app.get("/lang/{code}")
def set_language(code: str, request: Request):
    """Set the language cookie and redirect back to the referring page (or /)."""
    target = request.headers.get("referer") or "/"
    response = RedirectResponse(target, status_code=303)
    if code in i18n.SUPPORTED:
        # 1-year cookie; lax so a normal top-level navigation carries it.
        response.set_cookie(i18n.COOKIE_NAME, code, max_age=31_536_000, samesite="lax")
    return response
