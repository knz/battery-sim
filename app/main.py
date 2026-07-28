"""FastAPI application entry point for the Home Battery Simulator.

This is the web layer described in specs/08-architecture.md §5.1. In this first increment it
did one thing: serve a single-page three-panel UI (specs/02-ux-wireframes.md) rendered from a
*static* sample view-model (app/sample_data.py). It has since grown a domain layer, persistence
and — through the workspaces restructure (specs/20-workspaces-ux.md) — four screens instead of
one. The sample view-model survives as the EMPTY STATE each screen falls back to before any data
is loaded.

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
from the user's own HA instance directly and streams the raw rows to
`WS /w/{id}/data/ingest/ws`; the backend normalises them into SeriesFrames (app/domain) and
persists them (app/dataset.py) so they survive a restart. No HA token ever reaches this backend —
it stays in the browser.

Beyond the browser-fetch path, this layer serves the slot-first **backend_load** sources
(specs/02-ux-wireframes.md §2.2, specs/06-home-assistant-ingestion.md §4.3): POST
/w/{id}/data/slot/{slot_name}/load loads one slot from a backend source (e.g. the preset
Energy-Charts spot price) and merges the resulting series into the latest dataset via
dataset.upsert_series — without a browser round-trip and without discarding the other series.
browser_fetch sources (Home Assistant) are NOT loaded here; their frames still arrive over WS
/w/{id}/data/ingest/ws.

Beyond panel ③, this layer serves **panel ② — the parameter form** (specs §2.3, §2.5, §3.2
`PARAMS_CHANGED`). POST /w/{id}/params coerces the submitted fields (app/params_view.py —
coercion is the form layer's job, `simconfig` rejects `str` on purpose), builds a
`SimulationConfig`, validates it against §7.3 checks 11/12, persists it ONLY when valid
(app/simconfig_store.py) and returns the re-rendered panel. An invalid submission re-renders with
the user's own values still in the fields and the errors bound inline per field. The persisted
config drives panel ③: index(), POST /w/{id}/results and POST /w/{id}/results/benchmark all read
the same one, so a parameter change moves the results.

On startup (the `lifespan` below) the app adopts the pre-index single workspace into the
`workspaces` table (app/workspaces.py, specs/20-workspaces-ux.md §2′.10). A FRESH installation is
left with an empty index deliberately, because the list screen expresses that state.

**`GET /` is the workspace list** (phase 2, §2′.2): one card per analysis, most recently updated
first, with `[ + New analysis ]` and the two deletions.

**`GET`/`POST /w/{id}/edit` are the edit-workspace screen** (phase 3, §2′.4): the household's
fixed facts — title, postcode, grid connection, contract. It is a SEPARATE route from
`POST /params` although the two write one document, because the response shapes differ (a full
page that redirects, against a panel fragment for a swap) and because `validate()` is
whole-config while this screen draws four fields. What they share is the parsing and persistence
layers — `params_view.parse_form`, `issue_message`, `simconfig_store.save` — so there is no
second copy of the coercion table. It is also the one caller that passes
`pricing_configured=True` (§2′.6), which is what unblocks the results screen's cost toggle.

**`GET /w/{id}/results` is the results screen** (phase 4.2, §2′.6). It was the three-panel page —
the setup band plus panels ①, ② and ③ — until phase 4 split it in two. What renders now is the
capacity-first battery box (`_panel_params.html`: usable capacity alone, then a collapsed
"More settings" pane holding three tabs) above the results block (`_panel_results.html`), on ONE
screen that scrolls together, which §2′.6 calls the equivalent of §3.4's "reopening panel ① or ②
does not collapse panel ③". The screen has NO footer buttons in either mode: it is the end of both
the card path and the wizard path, and it is left through the back link.

The **cost toggle** moved into the results block here (§2′.7 dissolved the setup band). It keeps
its name `setup.simulate_cost` and its `form="params-form"` association, so `params_view.parse_form`
reads it exactly as before; what is new is that it is **Blocked** — greyed, disabled, with an ⓘ
opening a dialog that links to the edit screen's Contract box — until
`simconfig_store.is_pricing_configured` is true. `POST /w/{id}/edit` is the one write that sets that
flag, and `index()` and `POST /w/{id}/results` are the only two reads.

**`GET`/`POST /w/{id}/data` are the configure-data screen** (phase 4.1, §2′.5): panel ① promoted to
a screen of its own — the slot roster, the source drawer, the HA connection modal, the data-quality
box and the glance, all unchanged and rendered from the SAME partials panel ① uses, plus §2′.5's
titled "About your household" box and §2′.8's footer in place of the old `[ Next: parameters → ]`
CTA. The POST writes only `has_pv` / `has_battery`, and writes them through `_write_setup_answers` —
the same body the ingest-WS path commits them with — rather than through `params_view.parse_form`,
which would mean choosing a `sections` marker for a form that draws no checkbox. It is also the
reason `app/static/ha_fetch.js` needed no change: that file gates on `#slot-roster` and resolves
everything else by id, so it runs unmodified on the new screen.

**The wizard is a MODE on those screens, not a fourth screen** (phase 5, §2′.8). `POST /workspaces`
redirects into `/w/{id}/edit?mode=wizard` and `?mode=wizard` threads through both edit and data,
selecting the `[ ← Previous ] [ Next → ]` footer and a "Step n of 3" label beside the title. The
results screen has no mode: it is the end of both paths. Step 2's `[ Next → ]` is **Blocked** until
the house load is reconstructable — grid import/export T1, solar if `has_pv`, the existing
battery's two series if `has_battery` — with the missing slots named. The condition is
`data_screen_view.load_gate`, evaluated over the loaded frames. The split is that the CLIENT
explains and the SERVER enforces: the rendered button stays clickable and says what is missing,
and `POST /w/{id}/data` persists the household answers then re-checks the gate, re-rendering step
2 instead of advancing when it is unmet.

**Routes are workspace-scoped** (phase 1). Everything that reads or writes one analysis's data
lives under `/w/{workspace_id}/…` and resolves its workspace through `deps.get_workspace`
(specs/08-architecture.md §5.1, §5.5 invariant 2) instead of defaulting to the module constant
`db.WORKSPACE_ID`. Four routes stay FLAT, each for its own reason:

  * `GET /` — the list. It is ABOUT every workspace, so it belongs to none.
  * `POST /workspaces` — creates one; there is no id to scope it by yet.
  * `POST /feature-interest/{key}` — installation-wide since phase 0 (§2′.10, app/db.py).
  * `GET /lang/{code}` — sets a cookie; there is nothing workspace-shaped about a language.

**The three state-changing routes are same-site only** (`app/csrf.py`). `POST /workspaces`,
`POST /w/{id}/delete` and `POST /w/{id}/data/delete` declare `csrf.require_same_site` and answer a
cross-site request with 403. The two deletions are the reason: a workspace migrated from a
pre-index installation has the shared constant id `local`, so before this check any page in any
tab could destroy the user's analysis with one forged form POST. It is a header check rather than
a token, which keeps the app's no-session/no-secret property — the reasoning, and the one case it
deliberately does not cover (`POST /w/{id}/params`), are in `app/csrf.py`.

The consequence for the browser: no path may be written as a literal any more. Each screen's
`<body>` carries `data-workspace-id`, and every `fetch()` on it plus the ingest WebSocket URL in
ha_fetch.js build their path from it. `localStorage`'s slot store is keyed per workspace for the
same reason (§2′.11) — see app/static/ha_fetch.js. The LIST screen needs none of that: every
action on it is a plain link or an ordinary form POST.

Routes:
    GET  /                              → the workspace list (workspaces.html)
    POST /workspaces                    → create a workspace; 303 into it
    GET  /w/{id}/edit                   → the edit-workspace screen (workspace_edit.html, §2′.4)
    POST /w/{id}/edit                   → validate + persist it; 303 on success
    GET  /w/{id}/data                   → the configure-data screen (workspace_data.html, §2′.5)
    POST /w/{id}/data                   → persist has_pv / has_battery; 303 on success
    GET  /w/{id}/results                → the results screen (workspace_results.html, §2′.6)
    POST /w/{id}/delete                 → delete the workspace and everything in it; 303 to /
    POST /w/{id}/data/delete            → delete its measurements, keep the config; 303 to /
    POST /w/{id}/params                 → validate + persist the battery box; return the fragment
    POST /w/{id}/results                → recompute the results block over a window; the fragment
    POST /w/{id}/results/benchmark      → the §6.12 perfect-foresight box (slow; lazy)
    WS   /w/{id}/data/ingest/ws         → stream browser-fetched HA rows in; persist SeriesFrames
    POST /w/{id}/data/slot/{name}/load  → load one slot from a backend_load source; merge + report
    GET  /lang/{code}                   → set the language cookie, redirect back
    POST /feature-interest/{key}        → record interest in a pending control; 204 on success
    /static/*                           → CSS, generated stylesheet, Plotly, topology SVGs

Run:  uv run uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import (
    config,
    csrf,
    data_screen_view,
    data_view,
    dataset,
    db,
    deps,
    features,
    i18n,
    ingest_ws,
    interest,
    params_view,
    results_screen_view,
    results_view,
    simconfig_store,
    summary_view,
    workspace_edit_view,
    workspace_list_view,
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
    """Startup work: adopt a pre-index installation into the workspace index. One step.

    `workspaces.migrate_local()` gives the PRE-INDEX single workspace a row: it inserts nothing
    once the index is non-empty, and nothing at all when `local` has no config and no dataset on
    disk — so running it on every start is a `SELECT COUNT(*)` in the ordinary case.

    **A fresh installation deliberately ends up with an EMPTY index, and that is now a state the
    UI expresses.** Phase 1 added a second step here that created `local` when it was missing,
    because `GET /` rendered the single-page UI for `local` and every control on that page 404'd
    without the row. Phase 2 removed it: `GET /` is the workspace list, an empty list draws its
    invitation to create the first analysis (§2′.2), and creating the row here would put a
    phantom analysis on that screen that the user never made. Followup I7, closed.

    A lifespan rather than import-time work beside `CONFIG`, because this step WRITES to the data
    directory. Importing `app.main` (a test collecting routes, a tooling import) must not create
    rows in whatever directory happens to be resolved at import time; a lifespan runs only when
    the app is actually served, which is when a data directory has been chosen deliberately. The
    consequence for tests: a `TestClient(app)` built OUTSIDE a `with` block never runs this, so a
    route test against a temp data dir creates the workspace itself
    (`tests/conftest.seed_workspace`).

    A failure is logged and swallowed: the app must still serve. What follows, stated plainly, is
    that a failed migration leaves a genuine pre-index installation looking like a fresh one — an
    empty list beside a `local/` directory that still holds its config and dataset. Nothing is
    lost, and the next successful start adopts it.
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
def workspace_list(request: Request):
    """The workspace list — the app's home screen (specs/20-workspaces-ux.md §2′.2).

    One card per workspace, most recently updated first. The ordering is
    `workspaces.list_summaries()`'s SQL (`ORDER BY updated_at DESC`), not anything decided here,
    and `updated_at` is the CONFIGURATION's save time — so loading data never reorders the list
    (§2′.10). `POST /w/{id}/params` is what advances it.

    **The empty list is a real state, not an error.** A fresh installation has no workspaces and
    the screen draws its invitation to create the first one. Phase 1's lifespan created a `local`
    row to keep the old single page working; that is gone (followup I7), because a phantom
    analysis on this screen is exactly what §2′.2 says must not happen.

    Cheap by construction: `list_summaries` reads the dataset facts from SQLite metadata alone,
    never from the `.npz` arrays, so a list of N cards is one query plus N small JSON config reads
    rather than N dataset loads. The run size that used to be derived (and wrong) here is now
    computed at save time and stored on the dataset row — `workspaces._data_facts`, followup I2.
    """
    locale = i18n.resolve_locale(request)
    return HTMLResponse(
        i18n.env_for(locale).get_template("workspaces.html").render(
            cards=workspace_list_view.cards(workspaces.list_summaries()),
            lang={
                "current": locale,
                "options": [{"code": c, "label": c.upper()} for c in i18n.SUPPORTED],
            },
        )
    )


@app.post("/workspaces", dependencies=[Depends(csrf.require_same_site)])
def create_workspace():
    """Create a workspace and redirect into it (§2′.2's `[ + New analysis ]`).

    **POST, not GET, and a redirect afterwards.** Creating writes, so it is not a navigation; and
    redirect-after-POST means a reload of the destination does not create a second workspace.

    Same-site only (`app/csrf.py`). An unchecked create lets any page in any tab fill the user's
    list with analyses they never made — noise rather than damage, unlike the two deletions, but
    prevented by the same one-line dependency, so there is no reason to leave it open.

    **Where it redirects.** §2′.2 sends `[ + New analysis ]` into §2′.8's three-step wizard, so the
    destination is step 1 — the edit screen in wizard mode. Not the results screen: a workspace
    created a moment ago has appendix-A defaults and no data, so results would be an empty screen
    with no indication of what to do next, and the wizard exists precisely to walk that user
    through the two screens that fill it in. The mode travels as a query parameter rather than as
    session state, so the wizard is a property of the URL and a reload of step 1 stays step 1.

    The title is `workspaces.DEFAULT_TITLE`, untranslated for the reason stated there: it is
    written to the database once and a stored string cannot follow the user's later language
    toggle. The user renames it on step 1, which is the first field there (§2′.4).
    """
    workspace_id = workspaces.create(workspaces.DEFAULT_TITLE)
    return RedirectResponse(f"/w/{workspace_id}/edit?mode=wizard", status_code=303)


@app.post("/w/{workspace_id}/delete", dependencies=[Depends(csrf.require_same_site)])
def delete_workspace(ws: Annotated[deps.Workspace | None, Depends(deps.get_optional_workspace)]):
    """Delete a workspace and everything in it, then return to the list (§2′.3).

    **POST rather than a browser `DELETE`.** An HTML form can only issue GET or POST, and this is
    submitted by a form inside the confirmation dialog — a `DELETE` would need a `fetch`, which
    would make the one destructive action on the screen the only thing that stops working when a
    script fails to load. Redirect-after-POST returns to the re-rendered list, which §2′.3
    requires ("After confirming, the user stays on the list, which re-renders").

    **Same-site only** (`app/csrf.py`). This route deletes the user's analysis irreversibly and
    the migrated workspace's id is the shared constant `local`, so without the check any page in
    any tab could destroy it with a single forged form POST. That was reproduced; see the module.

    **An already-deleted workspace redirects rather than 404ing** (`get_optional_workspace`). A
    second submission — a double-click on the dialog, Back-then-resubmit — has already achieved
    the end state it asked for, and §2′.3 says the user stays on the list. Answering it with a raw
    JSON 404 body was what the user actually saw before.

    `workspaces.delete` removes the workspace row, every row keyed by its id, and the whole
    directory. `feature_interest` is deliberately untouched: it is installation-wide since phase 0
    and records what this household wants, which survives the deletion of the analysis it was
    clicked from — including the deletion of the last one.
    """
    if ws is not None:
        workspaces.delete(ws.id)
    return RedirectResponse("/", status_code=303)


@app.post("/w/{workspace_id}/data/delete", dependencies=[Depends(csrf.require_same_site)])
def delete_workspace_data(
    ws: Annotated[deps.Workspace | None, Depends(deps.get_optional_workspace)],
):
    """Delete a workspace's loaded measurements, keeping its configuration (§2′.3).

    The card returns to its no-data state and the workspace survives with its CONFIGURATION
    intact: `simconfig.json` and the workspace row, so the connection, contract and battery
    settings are exactly as they were.

    **The per-slot source mapping does NOT survive for slots that were fetched**, and the dialog
    copy says so. `workspaces.delete_data` clears every `series_meta` row, and for a fetched slot
    that row is where the source key and the HA statistic id live — see `app/static/ha_fetch.js`'s
    header, branch 1 of "Two things carry a source choice across a reload". Only branch 2, a
    PRE-FETCH staged choice held in `localStorage`, is untouched by a backend delete. An earlier
    version of this docstring claimed the mapping lived in `localStorage` in general and was
    therefore safe; that was wrong for exactly the case the dialog was describing, and §2′.3 has
    been corrected alongside it.

    `source_generation` is still deliberately left alone — it is a monotonic counter the browser
    compares a staged mapping against, and resetting it would make a live staged choice look
    stale, which would discard branch 2 as well as branch 1.

    Same POST-and-redirect shape as `delete_workspace`, with the same same-site check and the same
    redirect-rather-than-404 on an already-deleted workspace, for the same reasons.

    `updated_at` is NOT advanced. §2′.10 makes a config save the one event that advances it, and
    this deletes data rather than saving configuration — bumping here would reorder the list
    behind a deletion, which is the same surprise a data LOAD reordering it would be.
    """
    if ws is not None:
        workspaces.delete_data(ws.id)
    return RedirectResponse("/", status_code=303)


def _edit_page(
    request: Request,
    ws: deps.Workspace,
    cfg,
    title: str,
    *,
    result=None,
    wizard: bool = False,
    save_error: bool = False,
) -> HTMLResponse:
    """Render `workspace_edit.html` for `cfg`. Shared by the GET and the POST's failure path.

    One renderer rather than two, so an invalid submission comes back as the same screen with the
    user's own values in it — the property `POST /params` step 5 states, and the one that a second
    render site would be free to drift from.
    """
    locale = i18n.resolve_locale(request)
    return HTMLResponse(
        i18n.env_for(locale).get_template("workspace_edit.html").render(
            view=workspace_edit_view.edit_view(
                cfg, title, result=result, wizard=wizard, save_error=save_error
            ),
            workspace_id=ws.id,
            lang={
                "current": locale,
                "options": [{"code": c, "label": c.upper()} for c in i18n.SUPPORTED],
            },
        )
    )


@app.get("/w/{workspace_id}/edit", response_class=HTMLResponse)
def edit_workspace(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    mode: str = "",
):
    """The edit-workspace screen: the household's fixed facts (§2′.4).

    Title, postcode, grid connection and contract — what the household IS, as opposed to what is
    being simulated about it. The title comes from the `workspaces` row and everything else from
    the config document, which is why one route writes both and why `POST /params` does not (it
    has no business touching the workspace row beyond `touch()`).

    `?mode=wizard` selects §2′.8's wizard footer (`[ ← Previous ] [ Next → ]`) instead of the
    card footer (`[ Cancel ] [ Save ]`). A query parameter rather than a second route: the two
    modes render the same screen and differ only in the footer and in where a successful save
    goes, so a second route would be a second copy of the render for two buttons.

    `simconfig_store.load` never raises — an unreadable document renders appendix-A defaults, so
    this page always renders, which is what lets a user repair a broken configuration from it.
    """
    cfg = simconfig_store.load(ws.id)
    return _edit_page(request, ws, cfg, ws.title, wizard=(mode == "wizard"))


@app.post("/w/{workspace_id}/edit", response_class=HTMLResponse)
async def save_workspace_edit(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    mode: str = "",
):
    """Validate and persist the edit-workspace screen, then redirect (§2′.4, §2′.6, §2′.8).

    **A separate route from `POST /params`, decided at the start of phase 3** (see
    `changelog/20260726-workspaces-phase3.md`). Parsing IS shared — the candidate is built by
    `params_view.parse_form` on top of the stored config, so every setting this screen does not
    draw is inherited and there is no second copy of the coercion table anywhere. What is not
    shared is the RESPONSE: `POST /params` returns a panel fragment for an `outerHTML` swap, while
    this is a full page that redirects on success; and `validate()` is whole-config, so this
    screen filters issues to the fields it actually draws (`workspace_edit_view.EDITED_FIELDS`)
    and surfaces any other blocking issue at page level rather than binding it to an input that
    does not exist.

    **No same-site check, matching `POST /params`.** `app/csrf.py` draws its line at "can this
    request destroy something the user cannot recreate", not at "is this a POST": the three routes
    it covers create or irreversibly delete. This one is an idempotent overwrite of one local
    workspace's title and four settings with values a forging page would be choosing blind and
    could not read back — the same shape as `POST /params`, and the same threat followups B6
    weighed and accepted. Adding the dependency here would be defensible, but it should be done
    for both parameter-writing routes at once and on purpose, not drifted into on one of them.

    The sequence:

        1. coerce the submission (`parse_form` on the STORED config, so untouched settings
           inherit) and read the two fields that are not in `FIELDS` — the title and the
           connection dropdown, which writes `grid.phases` and `grid.fuse_a` as a pair;
        2. `validate()`;
        3. on a blocking failure, re-render THIS screen with the submitted values, so the user's
           typing survives — never the stored config;
        4. otherwise persist: the config through `simconfig_store.save`, the title through
           `workspaces.rename`, then `workspaces.touch` (§2′.10) — after the write, so a save that
           raised leaves the "last saved" badge alone;
        5. redirect 303, to the list from a card and to the next wizard step in the wizard.

    **`pricing_configured=True` on every successful save here** (§2′.6). This is the screen that
    asks what the household pays, so saving it is what "the user has told us what they pay" means;
    it is what unblocks the cost toggle on the results screen. It is never passed False — the
    store's default of `None` means "carry forward", which is what makes the flag never cleared
    automatically by any other save.
    """
    try:
        form = await request.form()
    except Exception as exc:  # an unparseable body is a client error, not a server one
        raise HTTPException(status_code=400, detail=f"invalid form body: {exc}") from exc

    wizard = mode == "wizard" or str(form.get("mode") or "") == "wizard"

    stored = simconfig_store.load(ws.id)
    candidate = params_view.parse_form(form, stored)

    # The two controls that are not in `params_view.FIELDS`. The connection dropdown writes BOTH
    # grid fields from one token; an unreadable value leaves them as they were, for the reason
    # `parse_connection` gives.
    if "grid.connection" in form:
        pair = workspace_edit_view.parse_connection(form.get("grid.connection"))
        if pair is not None:
            candidate.grid.phases, candidate.grid.fuse_a = pair
    if "postcode" in form:
        # Stored as typed (§2′.4 leaves format validation open) — only the surrounding whitespace
        # a browser's autofill tends to add is removed.
        candidate.postcode = str(form.get("postcode") or "").strip()

    # The title lives on the workspaces row, not in the config. An empty submission keeps the
    # current title rather than storing a blank one: a card with no name is unusable on the list
    # screen, and there is nothing on this screen the user could be trying to express by it.
    title = str(form.get("title") or "").strip() or ws.title

    result = candidate.validate()
    if result.blocking:
        return _edit_page(
            request, ws, candidate, title, result=result, wizard=wizard, save_error=False
        )

    try:
        simconfig_store.save(
            candidate,
            ws.id,
            guard_submitted=params_view.guard_was_submitted(form, stored),
            # §2′.6: set here and only here. Never False — see the docstring.
            pricing_configured=True,
        )
        if title != ws.title:
            workspaces.rename(ws.id, title)
        # Only after something was actually stored, exactly as `POST /params` does it (§2′.10).
        workspaces.touch(ws.id)
    except OSError as exc:
        # Same treatment as `POST /params`: a read-only or full data directory is a foreseeable
        # local condition, not a server bug, and a 500 would leave the user with no explanation.
        # The screen comes back with the submitted values and a notice saying they were not
        # stored — and deliberately does NOT redirect, since redirecting would claim success.
        log.warning("could not save workspace settings: %s", exc)
        return _edit_page(
            request, ws, candidate, title, result=result, wizard=wizard, save_error=True
        )

    # §2′.8: `[ Save ]` returns to the list; `[ Next → ]` advances a step. Step 2 is the
    # configure-data screen, which phase 4.1 built — so this now points at the real destination
    # rather than skipping ahead to the results page as it did while step 2 did not exist.
    destination = f"/w/{ws.id}/data?mode=wizard" if wizard else "/"
    return RedirectResponse(destination, status_code=303)


def _data_page(
    request: Request,
    ws: deps.Workspace,
    *,
    wizard: bool = False,
    save_error: bool = False,
) -> HTMLResponse:
    """Render `workspace_data.html` for one workspace (§2′.5). Shared by the GET and the POST.

    Builds panel ①'s context exactly as `index()` does, from the same two sources — the persisted
    config for the scope answers, and the persisted dataset for the roster, the quality box and the
    glance — with the static sample as the empty state. It is the same view-model
    (`data_view.panel_data_from`, `summary_view.data_summary_from`) rather than a second one, so a
    slot roster on this screen and the one in panel ① cannot describe the workspace differently.

    `data_summary` is the "once data has loaded" gate §2′.5 puts on the quality box and the glance:
    present from DATA_READY onward, dropped in the empty state, and dropped again when the frames
    yield no simulatable grid. The template gates BOTH boxes on it.

    A corrupt dataset falls back to the sample rather than 500ing, for the reason `index()` gives:
    this screen is where a user goes to REPLACE the data, so it is the last screen that may refuse
    to render because the data is bad.
    """
    locale = i18n.resolve_locale(request)

    ctx = sample_view()
    ctx["workspace_id"] = ws.id

    cfg = simconfig_store.load(ws.id)
    # The household box and the roster's gating read these three off `cfg`, the same keys panel ①
    # is given. `simulate_cost` is included because the roster's two price-bracketing rows are
    # gated on it — this screen does not draw that control (§2′.6 puts it on the results screen)
    # but it must still honour the stored answer when deciding which rows to show.
    ctx["cfg"] = {
        "has_pv": cfg.has_pv,
        "has_battery": cfg.has_battery,
        "simulate_cost": cfg.simulate_cost,
    }

    # Two SEPARATE questions, and conflating them cost the quality box on this screen once
    # already. `has_dataset` is "the user has loaded something"; `data_summary` is "those frames
    # yield a simulatable grid", which `data_summary_from` returns None for. A price-only dataset
    # — the spot-price preset loads on its own, so this is a real intermediate state — is the case
    # where they differ: it must still get the quality box, because this is the screen a user
    # comes to in order to find out WHY their data is unusable.
    # `ctx` starts as `sample_view()`, so both keys arrive pre-populated with SAMPLE figures. Each
    # is therefore replaced-or-dropped explicitly below; letting a sample value survive is how the
    # empty state would come to show figures for data the user never supplied.
    has_dataset = False
    summary = None
    # The series the loaded dataset actually holds, for §2′.8's step-2 gate. Empty when nothing
    # loaded and empty when the load FAILED, which is the right answer in both cases: a page that
    # could not read the dataset cannot claim the house load is reconstructable from it.
    series_names: set[str] = set()
    try:
        loaded = dataset.load_latest(ws.id)
        if loaded is not None and loaded.frames:
            has_dataset = True
            series_names = {f.name for f in loaded.frames}
            ctx["data"] = data_view.panel_data_from(loaded)
            summary = summary_view.data_summary_from(loaded)
    except Exception:  # pragma: no cover - defensive: a corrupt dataset must not break the page
        pass
    if summary is not None:
        ctx["data_summary"] = summary
    else:
        ctx.pop("data_summary", None)

    ctx["lang"] = {
        "current": locale,
        "options": [{"code": c, "label": c.upper()} for c in i18n.SUPPORTED],
    }
    # Read by ha_fetch.js to reconcile a locally-staged mapping, and by this screen's dirty check
    # to decide whether anything is staged-but-unfetched (§2′.8, §2′.11).
    ctx["source_generation"] = db.source_generation(ws.id)
    # The quality box's own gate — see the `has_dataset` comment above. Separate from
    # `data_summary`, which gates only the glance.
    ctx["has_dataset"] = has_dataset
    ctx["view"] = data_screen_view.data_screen_view(
        cfg,
        ws.title,
        wizard=wizard,
        save_error=save_error,
        # §2′.8's gate, derived from the frames just loaded rather than from
        # `workspaces.DataFacts`: the frames are already in hand, and `DataFacts` answers only
        # three of the five roles (it has no existing-battery fields, and its one consumer — the
        # §2′.2 card — does not want them). See D1.
        missing_for_load=data_screen_view.load_gate(
            series_names, has_pv=bool(cfg.has_pv), has_battery=bool(cfg.has_battery)
        ),
    )
    return HTMLResponse(
        i18n.env_for(locale).get_template("workspace_data.html").render(**ctx)
    )


@app.get("/w/{workspace_id}/data", response_class=HTMLResponse)
def configure_data(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    mode: str = "",
):
    """The configure-data screen (§2′.5): panel ① promoted to a screen of its own.

    The slot roster, the source drawer and its staged-then-confirm behaviour, the HA connection
    modal, the data-quality box and "Your data at a glance" all keep their specified behaviour and
    their existing markup — the template includes the same partials panel ① does. What §2′.5 adds is
    the titled "About your household" box around the two scope answers and §2′.8's footer, which
    replaces panel ①'s `[ Next: parameters → ]` CTA.

    `?mode=wizard` selects §2′.8's wizard footer (`[ ← Previous ] [ Next → ]`) instead of the card
    footer (`[ Cancel ] [ Save ]`), the same query-parameter approach and the same reasoning as
    `GET /w/{id}/edit`.

    `simconfig_store.load` never raises — an unreadable document renders appendix-A defaults, so
    this page always renders.
    """
    return _data_page(request, ws, wizard=(mode == "wizard"))


@app.post("/w/{workspace_id}/data", response_class=HTMLResponse)
async def save_configure_data(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    mode: str = "",
):
    """Persist the configure-data screen's two scope answers, then redirect (§2′.5, §2′.8).

    **This route does NOT call `params_view.parse_form`, deliberately.** `parse_form` inherits every
    absent field from its base, which makes a partial POST safe — except checkboxes, which invert
    that rule and are gated on the hidden `sections` marker, and an over-claiming marker silently
    CLEARS a checkbox the form never drew (phase 3 shipped two such defects). This screen draws no
    checkbox at all, and `parse_form` has no `has_battery` branch to read anyway — only
    `setup.has_pv`, behind the `setup` gate, under a name these controls deliberately do not use.
    So the two radios are read directly here and the form carries no `sections` field: there is no
    marker on this path to get wrong. See `changelog/20260726-workspaces-phase4.md`.

    **No same-site check**, consistently with `POST /params` and `POST /w/{id}/edit`. `app/csrf.py`
    draws its line at "can this request destroy something the user cannot recreate", and this route
    is strictly weaker than either of those: it writes two booleans, each undone by clicking the
    other radio, and it touches neither the dataset, nor the slot mapping, nor the workspace row.
    Phase 3's standing note applies — if that judgement is revisited it should be revisited for all
    three parameter-writing routes together rather than drifted into on one of them.

    A missing radio is read as None and leaves the stored answer alone, rather than defaulting: an
    absent group means the control was not submitted, which is not the user answering "no".

    The write goes through `_write_setup_answers`, the RAISING variant — not the never-raises
    `_persist_setup_answers` the fetch path uses. A `[ Save ]` here has persisted nothing else, so a
    swallowed failure would render a screen claiming success with nothing on disk; instead the
    failure comes back as this screen with the save-error notice, exactly as `POST /params` and
    `POST /w/{id}/edit` report the same condition. It is not a 500 — an unwritable data directory is
    a foreseeable local condition rather than a server bug.

    There is no validation branch: two booleans cannot fail `validate()`, so there is nothing to
    re-render with errors and no invalid path to persist behind.
    """
    try:
        form = await request.form()
    except Exception as exc:  # an unparseable body is a client error, not a server one
        raise HTTPException(status_code=400, detail=f"invalid form body: {exc}") from exc

    wizard = mode == "wizard" or str(form.get("mode") or "") == "wizard"

    def answer(name: str) -> bool | None:
        """One radio group as a tri-state: True, False, or None for "not submitted".

        None rather than a default, so a submission that did not carry the group leaves the stored
        answer alone. `"1"` is the only true value, matching the template and `ha_fetch.js`'s
        `setupAnswer`.
        """
        if name not in form:
            return None
        return str(form.get(name)) == "1"

    has_pv, has_battery = answer("setup_haspv"), answer("setup_hasbattery")
    try:
        _write_setup_answers(ws.id, has_pv, has_battery)
    except OSError as exc:
        log.warning("could not save the household answers: %s", exc)
        return _data_page(request, ws, wizard=wizard, save_error=True)

    # §2′.10: a config save is what advances `updated_at`, and only after something was actually
    # stored — the same rule and the same ordering `POST /params` and `POST /w/{id}/edit` follow.
    #
    # "Actually stored" has to be checked HERE, not inferred from the call above returning without
    # raising: `_write_setup_answers` returns early when both answers are None (a body carrying
    # neither radio), and touching then would move the workspace to the top of the list, with its
    # "last saved" badge advanced, for a save that wrote nothing. A rendered form always submits
    # both radios, so this is reachable only by a hand-made POST — but the comment above claimed a
    # guarantee the code did not have, which is the shape of thing this project keeps finding.
    if has_pv is not None or has_battery is not None:
        workspaces.touch(ws.id)

    # §2′.8's step-2 gate. This is the ONLY enforcement of it — the rendered `[ Next → ]` stays
    # clickable and merely says what is missing, because a `disabled` one trapped the user on the
    # commonest first run (review finding R1 in `changelog/20260726-workspaces-phase5.md`: that
    # button is the only submitter of the form the `has_pv` radio lives in, so blocking it blocked
    # the answer that would clear the block). Server-side was always where the guarantee had to
    # live in any case — followup L3 is this project's live example of a crafted POST walking past
    # a `disabled` attribute into a state no affordance offers. Re-rendering step 2 is the honest
    # answer: the advance did not happen, so the user stays on the screen that says why, with a
    # freshly computed message.
    #
    # The answers above are persisted FIRST, and since the fix that ordering is load-bearing rather
    # than merely considerate. §2′.8 makes `[ Next → ]` a save that also advances, and refusing the
    # advance is not a reason to discard the save. It is also what springs the trap: the `cfg`
    # reloaded below sees the answers this request just wrote, so a user who says "no, I have no
    # solar" and clicks Next has that recorded and the gate re-evaluated against it — the click
    # that could not advance is the click that makes the next one able to.
    #
    # Only in the wizard. The card path's `[ Save ]` goes to the list and is not gated: §2′.8
    # blocks the wizard's forward step, and a save of two booleans has nothing to do with whether
    # the dataset is complete.
    if wizard:
        cfg = simconfig_store.load(ws.id)
        loaded = None
        try:
            loaded = dataset.load_latest(ws.id)
        except Exception:  # pragma: no cover - defensive, as in `_data_page`
            loaded = None
        names = {f.name for f in loaded.frames} if loaded is not None else set()
        if data_screen_view.load_gate(
            names, has_pv=bool(cfg.has_pv), has_battery=bool(cfg.has_battery)
        ):
            return _data_page(request, ws, wizard=True)

    # §2′.8: `[ Save ]` returns to the list; `[ Next → ]` advances to step 3, the results screen,
    # which is where the wizard ends (§2′.6 — that screen has no footer and is the end of both
    # paths).
    destination = f"/w/{ws.id}/results" if wizard else "/"
    return RedirectResponse(destination, status_code=303)


@app.get("/w/{workspace_id}/results", response_class=HTMLResponse)
def index(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
):
    """The RESULTS screen for one workspace, in the request's locale (§2′.6).

    **Phase 4.2 made this the screen §2′.6 specifies**, where before it was the whole three-panel
    page. Panel ① went to `/w/{id}/data` in 4.1 and the setup band is dissolved (§2′.7), so what
    renders now is two things that scroll together: the capacity-first battery box
    (`_panel_params.html`) and the results block (`_panel_results.html`). That they are ONE screen
    is the constraint §2′.6 is emphatic about — a capacity change and its effect have to be visible
    at once — which is why the parameters did not get a route of their own.

    **No `?mode=wizard`.** §2′.6 gives this screen no footer in either mode: it is the end of both
    the card path and the wizard path, so there is nothing for a mode to select. `POST /w/{id}/data`
    redirects here plainly for the same reason.

    `pricing_configured` is read here, and it is the only thing on this page that decides Blocked
    from live. §2′.6 makes the EDIT screen the one write that sets it; this is the one read.

    The id is threaded into the page (`data-workspace-id` on `<body>`) because every fragment this
    page fetches is scoped.
    """
    locale = i18n.resolve_locale(request)
    workspace_id = ws.id

    ctx = sample_view()
    # The browser builds every fetch path from this (`data-workspace-id`), so the page addresses
    # the same workspace it was rendered from.
    ctx["workspace_id"] = workspace_id

    # The battery box (§2.3, §2′.6) renders from the PERSISTED parameter set — appendix-A defaults
    # until the user submits the form, and appendix-A defaults again if the stored file is
    # unreadable (simconfig_store.load never raises, so the page always renders). `cfg` carries the
    # three answers the box's gates read; it used to be the static sample dict, and leaving it
    # would let the gates and the values disagree.
    cfg = simconfig_store.load(workspace_id)
    ctx["params"] = params_view.params_view(cfg)
    ctx["cfg"] = {
        "has_pv": cfg.has_pv,
        "has_battery": cfg.has_battery,
        "simulate_cost": cfg.simulate_cost,
    }
    # The cost toggle's two inputs. `simulate_cost` is the checked radio; `cost_toggle_blocked` is
    # §2′.6's Blocked state, and the two are independent — a workspace with cost simulation ON and
    # no contract configured is reachable (the §2′.10 migration sets the flag from `simulate_cost`,
    # but a hand-edited document need not), and it renders a checked toggle the user cannot change
    # from here until they visit the edit screen. That is the honest rendering: the answer IS yes,
    # and the screen that owns the precondition is one click away.
    ctx["simulate_cost"] = cfg.simulate_cost
    ctx["cost_toggle_blocked"] = not simconfig_store.is_pricing_configured(workspace_id)

    # If a real dataset has been fetched and persisted, the results block renders from it
    # (specs §3.5); otherwise it keeps the static sample as the empty state. A load failure falls
    # back to the sample rather than 500ing.
    #
    # The data glance repeated inside the results comes from `results.data_summary`, which
    # `results_from` computes over the selected window — NOT from the top-level `data_summary` key
    # panel ① used, which this screen no longer renders and which is therefore left alone here.
    try:
        loaded = dataset.load_latest(workspace_id)
        if loaded is not None and loaded.frames:
            # The COMPUTED energy-savings view-model over the default window (last_1_year,
            # coverage-anchored) instead of the static sample. `results_from` returns None when the
            # frames yield no simulatable grid — in that case the sample `ctx["results"]` stays as
            # the empty-state fallback.
            computed_results = results_view.results_from(
                loaded, results_view.resolve_window(loaded), cfg=cfg
            )
            if computed_results is not None:
                ctx["results"] = computed_results
    except Exception:  # pragma: no cover - defensive: a corrupt dataset must not break the page
        pass
    ctx["lang"] = {
        "current": locale,
        "options": [{"code": c, "label": c.upper()} for c in i18n.SUPPORTED],
    }
    ctx["view"] = results_screen_view.results_screen_view(
        cfg, ws.title, pricing_configured=not ctx["cost_toggle_blocked"]
    )
    return HTMLResponse(
        i18n.env_for(locale).get_template("workspace_results.html").render(**ctx)
    )


@app.post("/w/{workspace_id}/params", response_class=HTMLResponse)
async def params(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
):
    """Validate and persist the panel-② parameter set, and return the re-rendered panel (§3.2).

    Scoped by workspace (§5.1): both the config read and the config write name `ws.id`, so a
    submission against one workspace cannot reach another's document. `deps.get_workspace` has
    already 404'd an unknown or path-unsafe id before this body runs.

    **No same-site check here, deliberately** — unlike the three routes that carry
    `csrf.require_same_site`. This is an idempotent overwrite of one local parameter set with
    values a forging page would be choosing blind and could not read back, which is precisely the
    threat followups B6 weighed and accepted. What changed in phase 2, and what the check exists
    for, is IRREVERSIBLE DELETION — so the line is drawn at "can this destroy something the user
    cannot recreate", not at "is this a POST". The asymmetry is a decision; see `app/csrf.py`.

    **A successful save advances `updated_at`** (`workspaces.touch`, §2′.10). This is the one
    event that does: the list screen's "last saved" badge and its most-recently-updated-first
    ordering both read that field, and a data load deliberately does not touch it, or fetching
    history would reorder the list behind the user. Only a save that actually happened counts — a
    submission that fails validation, or one whose write raised, leaves the field alone, because
    the badge reports when the configuration was last STORED and neither of those stored anything.

    **Why a form POST returning a fragment, and not JSON.** Panel ② is a form of ~20 inputs whose
    re-render has to carry per-field errors next to the inputs that caused them. Sending JSON and
    re-rendering client-side would mean a second, JS-side copy of the label/gating/translation
    logic that `params_view` already owns; returning the rendered panel keeps ONE renderer. It is
    also the pattern already established for panel ③ (`POST /w/{id}/results` → fragment →
    `outerHTML` swap, delegated listeners in workspace_results.html), so the browser side is three
    lines.

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

    stored = simconfig_store.load(ws.id)
    candidate = params_view.parse_form(form, stored)
    result = candidate.validate()
    save_error = False

    if not result.blocking:
        try:
            # `guard_submitted` reports whether THIS form drew the economic-guard checkbox, which
            # is the only way the store can tell an unticked box from an absent control — see
            # simconfig_store's carry-forward rule and appendix A's retention requirement.
            simconfig_store.save(
                candidate,
                ws.id,
                guard_submitted=params_view.guard_was_submitted(form, stored),
            )
            # The config was stored, so this is a "last saved" event (§2′.10, docstring above).
            # After the save, never before: a bumped timestamp on a write that then failed would
            # put the workspace at the top of the list for a save that did not happen.
            workspaces.touch(ws.id)
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
        # The form's own action is scoped, and this render is standalone (a panel swap), so the
        # id has to come from here as well as from index()'s context — otherwise the swapped-in
        # form posts to `/w//params` and the no-JS fallback 404s.
        workspace_id=ws.id,
        cfg={
            "has_pv": candidate.has_pv,
            "has_battery": candidate.has_battery,
            "simulate_cost": candidate.simulate_cost,
        },
        # The "N changed from default" count on the advanced pane's summary (§2′.6). Built from the
        # CANDIDATE, like everything else in this render: the count has to describe the values the
        # swapped-in box is showing, and on an invalid submission those are the user's own.
        # `title` and `pricing_configured` are not read by the fragment — the header and the cost
        # toggle live outside it — and the defaults are what this render site can honestly supply.
        view=results_screen_view.results_screen_view(candidate, ws.title),
    )
    return HTMLResponse(html, headers={"X-Params-Valid": "0" if result.blocking else "1"})


@app.post("/w/{workspace_id}/results", response_class=HTMLResponse)
def results(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    body: dict = Body(...),
):
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
    loaded, window = _resolve_results_window(ws.id, body)

    # The SAME persisted parameter set index() and /results/benchmark read, so the three cannot
    # disagree about which battery the panel is describing. Scoped: this workspace's config, over
    # this workspace's dataset.
    cfg = simconfig_store.load(ws.id)
    result = results_view.results_from(loaded, window, cfg=cfg)
    if result is None:
        raise HTTPException(status_code=409, detail="no simulatable data")

    # Render the fragment standalone from the request locale's environment (as index() does).
    #
    # **The fragment reads four things beyond `results.*` since phase 4.2**, all because §2′.6
    # moved the cost toggle into it: the toggle's checked state, its Blocked flag, and the
    # workspace id the Blocked branch's link and the ⓘ dialog's destination are built from. Every
    # one of them is re-read here rather than carried on the request, so a swap lands the toggle in
    # the state the STORE is in — which matters, because the recompute that triggers this swap can
    # be the one the toggle itself just caused.
    locale = i18n.resolve_locale(request)
    html = i18n.env_for(locale).get_template("_panel_results.html").render(
        results=result,
        workspace_id=ws.id,
        simulate_cost=cfg.simulate_cost,
        cost_toggle_blocked=not simconfig_store.is_pricing_configured(ws.id),
    )
    return HTMLResponse(html)


def _resolve_results_window(workspace_id: str, body: dict):
    """Turn a `POST /w/{id}/results`-shaped body into (loaded_dataset, window), or a clean 4xx.

    Shared by `POST /w/{id}/results` and `POST /w/{id}/results/benchmark` so the two cannot drift
    on which requests they accept or on which status code each failure gets. `workspace_id` is the
    resolved `Workspace.id`, not raw path input — the caller has been through
    `deps.get_workspace`. The contract, otherwise unchanged from what `/results` already had:

        {"period": "<preset>"}             — one of results_view.PERIOD_DAYS, coverage-anchored, OR
        {"start": "<iso>", "end": "<iso>"} — an explicit range (tz-aware UTC, like _parse_window).

    Errors are clean 4xx/409, never a 500 stack trace:
        * no persisted dataset → 409;
        * an unparseable date → 400;
        * an unknown preset, an empty/out-of-coverage range, or both period and range → 400
          (resolve_window raises ValueError).
    """
    loaded = dataset.load_latest(workspace_id)
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


@app.post("/w/{workspace_id}/results/benchmark", response_class=HTMLResponse)
def results_benchmark(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    body: dict = Body(...),
):
    """Compute §6.12's perfect-foresight benchmark over a window and return just that card.

    **This route exists because the DP is slow.** It costs ~2.3 s per pass on a year of hourly data
    — ~4.6 s for both export baselines — against ~0.12 s for everything else panel ③ shows, and
    running it inline made `GET /` take 4.72 s against 0.13 s without it. Cost scales linearly with
    window length (1 week 0.04 s, 30 days 0.19 s, 3 months 0.57 s, 1 year 2.29 s per DP), so only
    long windows are affected. The panel now paints from the §6.11 figures immediately and the
    browser fetches this afterwards, filling the `#benchmark-slot` placeholder in. Nothing is
    cached — that option was considered and lazy loading was chosen instead.

    Same request shape and the same clean 4xx/409 error conditions as `POST /w/{id}/results`
    (both go through `_resolve_results_window`), so a window the panel could render is never one
    the box rejects. The response body is `_benchmark_box.html`'s output, not the whole panel.

    **It returns BOTH boxes when cost simulation is on**, each wrapped in a container carrying the
    slot id it belongs in, and the browser distributes them. Runs D and E are both gated on
    `with_benchmark`, so this request pays for both DPs either way; returning one box and
    discarding the other would spend ~2.3 s and throw the result away. One route, one fetch, one
    DP bill. With cost simulation off the response is the energy box alone, unwrapped exactly as
    before, so nothing about the energy path's contract changes.

    A window with no simulatable grid → 409, exactly as `/w/{id}/results`. The benchmark key can
    also be absent when there WAS a grid but no intervals to simulate; that is a 409 too, since
    there is no box to return and the placeholder's failure path is the honest outcome.
    """
    loaded, window = _resolve_results_window(ws.id, body)

    result = results_view.results_from(
        loaded, window, cfg=simconfig_store.load(ws.id), with_benchmark=True
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


@app.websocket("/w/{workspace_id}/data/ingest/ws")
async def data_ingest_ws(
    ws: WebSocket,
    workspace: Annotated[deps.Workspace, Depends(deps.get_workspace)],
):
    """Stream browser-fetched HA statistics rows in; normalise, persist, and report back.

    Protocol in app/ingest_ws.py: a `header`, then `series`/`rows` batches per mapped series,
    then `done`. The backend accumulates in an `IngestSession`, and on `done` builds SeriesFrames
    (app/domain), persists them (app/dataset.save_dataset), and returns a `result` frame with the
    dataset id, series count, ingest warnings, and the panel-① grid report (specs §6.2).

    A protocol or validation error is reported as an `error` frame and closes the socket without
    persisting — the LOAD_FAILED path (specs §3.2). No HA token is ever received here (§7.5).

    **An unknown or path-unsafe workspace fails the HANDSHAKE, not the protocol.** The dependency
    raises before `accept()`, and FastAPI answers a rejected WebSocket dependency with an ordinary
    HTTP 404 response instead of upgrading — so there is no socket on which to send an `error`
    frame, and the browser's `WebSocket` constructor reports a connection failure. That is the
    right shape: a bad workspace id is a bad *address*, not a bad message, and the client's
    existing "could not reach the app's ingest endpoint" path already covers it.
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
                        workspace.id,
                    )
                    # A persisted fetch is the one event that advances the source generation
                    # (specs §2.2): it establishes new server-side authority, so any client's
                    # locally-saved source customization tagged with an older generation yields to
                    # the server after this. This is the ONLY bump site.
                    generation = await asyncio.to_thread(
                        db.bump_source_generation, workspace.id
                    )
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
                        _persist_setup_answers,
                        workspace.id, session.setup_has_pv, session.setup_has_battery,
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


def _write_setup_answers(
    workspace_id: str, has_pv: bool | None, has_battery: bool | None
) -> None:
    """Write the two scope answers onto the stored config. RAISES on failure.

    The shared body of `_persist_setup_answers` (the fetch path, which must never raise) and
    `POST /w/{id}/data` (the configure-data screen's footer, which must REPORT a failure). The two
    callers need opposite error behaviour and identical write semantics, which is exactly what
    wanting a shared body and two wrappers means:

      * the fetch runs this AFTER the dataset is already persisted, so an exception would fail a
        fetch whose real work succeeded — it is swallowed there, deliberately;
      * the footer's `[ Save ]` has persisted nothing else, so a swallowed exception would show the
        user a saved screen with nothing saved. Phase 4.1 nearly shipped that by reusing the
        never-raises wrapper directly.

    Either answer may be None, meaning the caller did not carry it — an older ingest client — in
    which case the stored answer is left as it is rather than reset to a default.

    `guard_submitted=False` is correct on both paths: neither draws panel ②'s form, so both must
    take the store's carry-forward branch for `economic_guard` rather than claim the box was shown
    and left unticked (which would clear a setting appendix A says is retained).

    **`pricing_configured` is deliberately not passed**, so it defaults to `None` — "carry
    forward". That is relied upon, not incidental: §2′.6 makes the EDIT screen the one write that
    means "the user has told us what they pay", and setting the flag from here would unblock the
    results screen's cost toggle from a screen that never asked about money.
    """
    if has_pv is None and has_battery is None:
        return
    stored = simconfig_store.load(workspace_id)
    if has_pv is not None:
        stored.has_pv = has_pv
    if has_battery is not None:
        stored.has_battery = has_battery
    # Re-clone before saving. has_pv drives forced invariants (§2.5: pv_coupling → None,
    # coupling → AC), and assigning the field above bypasses `__post_init__`, so the in-memory
    # object is inconsistent until something reconstructs it; `clone` goes through the dataclass,
    # which re-applies the forcing.
    #
    # This is defence in depth, NOT the mechanism the stored result depends on — measured, not
    # assumed: `simconfig_store.save` normalises through `to_dict` on the write path, so dropping
    # the clone still stores AC/None. Keeping it means any caller that inspects the config between
    # the assignment and the save sees a consistent object, and it costs one call.
    simconfig_store.save(
        simconfig_store.clone(stored), workspace_id, guard_submitted=False
    )


def _persist_setup_answers(
    workspace_id: str, has_pv: bool | None, has_battery: bool | None
) -> None:
    """Write the setup-band answers a fetch carried onto the stored config (specs §2.1).

    `workspace_id` is the resolved `Workspace.id` the fetch was addressed to — the same one the
    dataset was just written under, so the answers describing that data land beside it.

    Called from the WS `done` handler on a worker thread (file I/O). Either answer may be None,
    meaning the header did not carry it — an older client — in which case the stored answer is
    left as it is rather than reset to a default.

    NEVER RAISES, and callers depend on that. It runs after the dataset has already been persisted
    and the source generation bumped, so an exception here would fail a fetch whose real work
    succeeded, and the browser would report LOAD_FAILED for a dataset that is on disk. A data
    directory that cannot be written is logged and the answers are simply not updated; the next
    fetch writes them again.

    **A caller that needs to REPORT a failure must use `_write_setup_answers` instead**, not this.
    `POST /w/{id}/data` does: its `[ Save ]` has nothing else persisted to protect, so silence
    there would mean telling the user their answers were stored when they were not.
    """
    try:
        _write_setup_answers(workspace_id, has_pv, has_battery)
    except Exception:  # pragma: no cover - defensive, see the docstring
        log.warning("could not persist setup answers after fetch", exc_info=True)


def _jsonable_grid(report: dict) -> dict:
    """Grid report → JSON-safe dict (grid_s and native_resolution_s are already ints/None)."""
    # normalize.grid_report already emits plain ints/strings/None; this is a pass-through guard
    # kept explicit so a future numpy leak is caught here rather than at ws.send_json.
    return report


# The one source kind this endpoint loads. browser_fetch sources (Home Assistant) are shown in
# the drawer but their frames arrive over WS /w/{id}/data/ingest/ws — asking to load one here is a
# client error, not something the backend can do (the HA token stays in the browser, specs §7.5).
_BACKEND_LOAD: SourceKind = "backend_load"


def _resolve_backend_source(slot_name: str, source_key: str):
    """Resolve (slot, source) for a backend-load of `slot_name` from `source_key`.

    Shared by the WS reify path and POST /w/{id}/data/slot/{slot}/load. Raises ValueError with a
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


@app.post("/w/{workspace_id}/data/slot/{slot_name}/load")
async def load_slot(
    slot_name: str,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    body: dict = Body(...),
):
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

    dataset_id = await asyncio.to_thread(
        dataset.upsert_series, frame, source_key, window, ws.id
    )
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
