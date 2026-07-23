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

Routes:
    GET  /                          → the full page (index.html)
    GET  /lang/{code}               → set the language cookie, redirect back
    POST /feature-interest/{key}    → record interest in a pending control; 204 on success
    /static/*                       → CSS, generated stylesheet, Plotly, topology SVGs

Run:  uv run uvicorn app.main:app --reload
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config, db, features, i18n, interest
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


@app.get("/lang/{code}")
def set_language(code: str, request: Request):
    """Set the language cookie and redirect back to the referring page (or /)."""
    target = request.headers.get("referer") or "/"
    response = RedirectResponse(target, status_code=303)
    if code in i18n.SUPPORTED:
        # 1-year cookie; lax so a normal top-level navigation carries it.
        response.set_cookie(i18n.COOKIE_NAME, code, max_age=31_536_000, samesite="lax")
    return response
