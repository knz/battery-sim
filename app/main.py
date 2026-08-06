"""FastAPI application entry point for the Home Battery Simulator.

This is the web layer described in docs/specs/08-architecture.md §5.1. In this first increment it
did one thing: serve a single-page three-panel UI (docs/specs/02-ux-wireframes.md) rendered from a
*static* sample view-model (app/sample_data.py). It has since grown a domain layer, persistence
and — through the workspaces restructure (docs/specs/20-workspaces-ux.md) — four screens instead of
one. The sample view-model survives as the EMPTY STATE each screen falls back to before any data
is loaded.

The UI is bilingual (English / Dutch). Translation is server-side gettext (app/i18n.py): the
active locale is resolved per request (cookie → Accept-Language → English) and the matching
per-locale Jinja environment renders the response. Environments are built once per locale and
never mutated, so mixed-locale concurrent requests cannot cross-contaminate. The header carries
a language toggle that posts to /lang/{code}, which sets the `lang` cookie.

The pending affordance (docs/specs/02-ux-wireframes.md §2.1) has no back end here: its dialog
links straight to a pre-filled GitHub issue form, composed in app/features.py. Nothing about a
feature request is recorded locally, so this layer neither serves nor stores one.

This layer serves the Home Assistant **data import**
(docs/specs/06-home-assistant-ingestion.md, browser-fetch increment). The browser fetches statistics
from the user's own HA instance directly and streams the raw rows to
`WS /w/{id}/data/ingest/ws`; the backend normalises them into SeriesFrames (app/domain) and
persists them (app/dataset.py) so they survive a restart. No HA token ever reaches this backend —
it stays in the browser.

Beyond the browser-fetch path, this layer serves the slot-first **backend_load** sources
(docs/specs/02-ux-wireframes.md §2.2, docs/specs/06-home-assistant-ingestion.md §4.3): POST
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
`workspaces` table (app/workspaces.py, docs/specs/20-workspaces-ux.md §2′.10). A FRESH installation is
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
"More settings" pane holding three tabs) BESIDE the period card (`_panel_interval.html`: the preset
buttons, the date-range picker, the window line and the cost toggle), the two of them over the
results block (`_panel_results.html`), on ONE screen that scrolls together, which §2′.6 calls the
equivalent of §3.4's "reopening panel ① or ② does not collapse panel ③". The screen has NO footer
buttons in either mode: it is the end of both the card path and the wizard path, and it is left
through the back link.

The period card is a fragment of its own because the two POSTs that refresh this screen carry
different context: `POST /w/{id}/params` re-renders the battery box with no `results` key, so the
card cannot live inside it. `POST /w/{id}/results` returns the card and the results block together,
joined by `PANEL_SPLIT`.

The **cost toggle** moved into the setup band's place here (§2′.7 dissolved the band), and travels
with the period controls it sat under, into the period card. It keeps
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
(docs/specs/08-architecture.md §5.1, §5.5 invariant 2) instead of defaulting to the module constant
`db.WORKSPACE_ID`. Three routes stay FLAT, each for its own reason:

  * `GET /` — the list. It is ABOUT every workspace, so it belongs to none — but it is still
    scoped to the requesting principal (`Depends(deps.get_principal)`), which
    `workspaces.list_summaries(owner_id)` filters by (owner-scoping phase 1).
  * `POST /workspaces` — creates one; there is no id to scope it by yet, but the created row is
    owned by the requesting principal, the same dependency passed to `workspaces.create`.
  * `GET /lang/{code}` — sets a cookie; there is nothing workspace-shaped about a language.

**The five state-changing routes are same-site only** (`app/csrf.py`). `POST /workspaces`,
`POST /w/{id}/delete`, `POST /w/{id}/data/delete`, `POST /w/{id}/data/uploads` and
`DELETE /w/{id}/data/uploads/{upload_id}` declare `csrf.require_same_site` and answer a
cross-site request with 403. The two workspace deletions are the reason the check exists: a
workspace migrated from a pre-index installation has the shared constant id `local`, so before this
check any page in any tab could destroy the user's analysis with one forged form POST. The two
upload routes joined the list on the same rule — the DELETE removes a file the user cannot recreate
without re-uploading it, and the POST creates persistent per-workspace state. It is a header check
rather than a token, which keeps the app's no-session/no-secret property — the reasoning, and the
one case it deliberately does not cover (`POST /w/{id}/params`), are in `app/csrf.py`.

**Uploaded wide CSVs are a resource of their own** (§4.2a, §2.2 "The CSV source"), which is why
they get three routes rather than riding along with a fetch: uploading a file and binding a slot to
one of its columns are two separate user actions, since a wide export holds many measurements and
one file feeds many slots. `app/uploads.py` persists them and `app/domain/csv_wide.py` parses them;
neither calls the other, and the join lives in `create_upload` on purpose — the store cannot reject
a file it never looks inside, so "a rejected upload writes nothing" is a property of that route's
ordering (parse first, write only with a summary in hand).

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
    POST /w/{id}/data/uploads           → upload one wide CSV (§4.2a); 201 with the parse summary
    GET  /w/{id}/data/uploads           → list this workspace's uploads, newest first
    DELETE /w/{id}/data/uploads/{uid}   → remove one upload's row and file
    GET  /lang/{code}                   → set the language cookie, redirect back
    /static/*                         → CSS, generated stylesheet, Plotly, topology SVGs

Run:  uv run uvicorn app.main:app --reload
"""

import asyncio
import csv
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
from starlette.requests import ClientDisconnect

from app import (
    csrf,
    data_screen_view,
    data_view,
    dataset,
    db,
    deps,
    i18n,
    ingest_ws,
    params_view,
    results_screen_view,
    results_view,
    simconfig_store,
    summary_view,
    uploads,
    workspace_edit_view,
    workspace_list_view,
    workspaces,
)
from app.domain import csv_wide, normalize
from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SLOT_BY_NAME
from app.sample_data import sample_view
from app.sources import registry
from app.sources.base import SourceKind
from app.sources.csv_source import CsvBinding, CsvBindingError, CsvSource

BASE_DIR = Path(__file__).resolve().parent

# Separates the two fragments POST /w/{id}/results returns — `_panel_interval.html` (the period
# card) then `_panel_results.html` — which the browser splits on before swapping each into its own
# root. An HTML COMMENT so that a response rendered into a page by anything that does not split it
# is still valid markup showing both halves in order. The literal is duplicated in the
# `recompute()` handler in workspace_results.html; changing it means changing both.
PANEL_SPLIT = "<!--panel-split-->"

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

# Jinja environments live in app/i18n.py: one per locale, built on first use from this package's
# templates/ directory and never mutated afterwards, so concurrent requests in different languages
# cannot interleave a catalog install with someone else's render (see i18n.env_for). Routes render
# via `i18n.env_for(locale).get_template(...)`; there is no shared mutable environment here.


@app.get("/", response_class=HTMLResponse)
def workspace_list(
    request: Request, principal: Annotated[deps.Principal, Depends(deps.get_principal)]
):
    """The workspace list — the app's home screen (docs/specs/20-workspaces-ux.md §2′.2).

    One card per workspace OWNED BY THE REQUESTING PRINCIPAL, most recently updated first. The
    ordering is `workspaces.list_summaries(owner_id)`'s SQL (`ORDER BY updated_at DESC`), not anything
    decided here, and `updated_at` is the CONFIGURATION's save time — so loading data never
    reorders the list (§2′.10). `POST /w/{id}/params` is what advances it.

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
            cards=workspace_list_view.cards(workspaces.list_summaries(principal.id)),
            lang={
                "current": locale,
                "options": [{"code": c, "label": c.upper()} for c in i18n.SUPPORTED],
            },
        )
    )


@app.post("/workspaces", dependencies=[Depends(csrf.require_same_site)])
def create_workspace(principal: Annotated[deps.Principal, Depends(deps.get_principal)]):
    """Create a workspace owned by the requesting principal and redirect into it
    (§2′.2's `[ + New analysis ]`).

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
    workspace_id = workspaces.create(workspaces.DEFAULT_TITLE, owner_id=principal.id)
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
    directory.
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
    # The household box and the roster's gating read these two off `cfg`, the same keys panel ① is
    # given. They are the only two scope answers this screen renders anything from: the roster gates
    # its solar row on `has_pv` and its two existing-battery rows on `has_battery`, and the
    # household box draws a radio pair for each.
    #
    # `simulate_cost` used to be carried here as well, for the two price-bracketing roster rows
    # that were gated on it. Those slots are gone (the §6.16 bracket is derived from `price_spot`
    # rather than asked for), and no template reachable from this route reads the key any more —
    # `_data_household.html` says in as many words that the cost toggle is NOT drawn here (§2′.6
    # puts it on the results screen). So the key is not passed. The results route builds its own
    # `ctx["cfg"]` and still carries it, which is where the toggle actually lives.
    ctx["cfg"] = {
        "has_pv": cfg.has_pv,
        "has_battery": cfg.has_battery,
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

    # The same replaced-or-dropped rule, applied to the roster's per-slot PROVENANCE. The sample's
    # mapping rows carry a source and a statistic id for the slots it depicts as fetched
    # (`sensor.electricity_meter_import_t1` and friends). Those are illustrations of a filled
    # screen; on an empty one they are claims about data the user never supplied, and the drawer
    # believes them: it seeds `draft.statId` from `data-slot-stat-id`, which suppresses the entity
    # guess and leaves the picker showing an id that exists on no real Home Assistant.
    #
    # Only the provenance is cleared, not the rows: the roster still has to render every slot with
    # its role, requirement marker and offered sources. `has_dataset` is the gate rather than
    # `summary`, because a price-only dataset is real data and must keep whatever it mapped.
    if not has_dataset:
        ctx["data"] = dict(ctx["data"])
        ctx["data"]["mapping"] = [
            {**row, "source": None, "stat_id": None, "entity": None}
            for row in ctx["data"].get("mapping", [])
        ]

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
    renders now is a row of two control cards — the capacity-first battery box
    (`_panel_params.html`) beside the period card (`_panel_interval.html`) — over the results block
    (`_panel_results.html`), all scrolling together. That they are ONE screen is the constraint
    §2′.6 is emphatic about — a capacity change and its effect have to be visible at once — which is
    why the parameters did not get a route of their own.

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
            # The COMPUTED energy-savings view-model over the OPENING window — the user's
            # remembered choice if they have made one, else the data-derived default (see
            # `_opening_window`) — instead of the static sample. `results_from` returns None when
            # the frames yield no simulatable grid, in which case the sample `ctx["results"]` stays
            # as the empty-state fallback.
            window, custom, selected = _opening_window(ws.id, loaded)
            computed_results = results_view.results_from(
                loaded, window, cfg=cfg, custom_range=custom, period_selected=selected
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
    """Recompute the results over a requested window and return the rendered fragments (§3.2).

    The period/date picker POSTs here to recompute the ENERGY SAVINGS view-model over a sub-window
    without a full page reload. The response is HTML, not JSON: `_panel_interval.html` (the period
    card) and `_panel_results.html`, joined by `PANEL_SPLIT`, which the browser splits before
    swapping each into its own root. index() renders both templates as part of the page; here they
    are rendered standalone.

    The period card is in the response because it states the resolved window — the active preset
    and the "dates · N days · N intervals" line — which only this handler knows after clamping.

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
    # Whether this window came from the date fields rather than a preset — read off the REQUEST,
    # because the resolved window cannot say (see results_from's `custom_range`). It decides which
    # button the selector highlights and whether the date fields stay open, so an applied range
    # comes back as "custom" with the fields showing instead of snapping to the nearest preset.
    custom_range = body.get("start") is not None or body.get("end") is not None
    # Remember the choice for the next `GET /w/{id}` (`_opening_window`). Written here rather than
    # in `_resolve_results_window` because the benchmark route shares that helper and re-sends the
    # ALREADY-RESOLVED window as an explicit start/end — recording that would silently convert a
    # preset the user picked into a frozen custom range the moment the benchmark box loaded.
    #
    # A preset stores its TOKEN; a range stores the EFFECTIVE window (post-clamp), so what comes
    # back is what was actually simulated rather than what was typed past the edge of the data.
    if custom_range:
        simconfig_store.save_results_period(
            ws.id,
            {"start": window[0].isoformat(), "end": window[1].isoformat()},
        )
    elif body.get("period") is not None:
        simconfig_store.save_results_period(ws.id, {"preset": body["period"]})
    # The "default" button is the one request whose resolved window cannot be recognised after the
    # fact — it is a plain pair of datetimes, and `_period_selected_for` would map it to whichever
    # preset happens to be nearest in length, highlighting a button the user did not press.
    selected = (
        results_view.PERIOD_DEFAULT
        if body.get("period") == results_view.PERIOD_DEFAULT
        else None
    )
    result = results_view.results_from(
        loaded, window, cfg=cfg, custom_range=custom_range, period_selected=selected
    )
    if result is None:
        raise HTTPException(status_code=409, detail="no simulatable data")

    # Render the fragments standalone from the request locale's environment (as index() does).
    #
    # **TWO fragments, in one response.** A range change repaints the period card as well as the
    # results: the card carries the answers the picker just produced — which preset is active and
    # the "dates · N days · N intervals" line — and those are computed from the resolved window,
    # not known to the browser that asked. They are returned together, joined by a marker comment
    # the client splits on, because they are no longer siblings in the DOM (the card is in the
    # two-column row at the top of the screen, the panel spans the full width below it) and so no
    # single container encloses just them. One request rather than two, so the two halves cannot
    # end up describing different windows.
    #
    # **Both fragments read four things beyond `results.*`**, all because the cost toggle travels
    # with the period controls: the toggle's checked state, its Blocked flag, and the workspace id
    # the Blocked branch's link and the ⓘ dialog's destination are built from. Every one of them is
    # re-read here rather than carried on the request, so a swap lands the toggle in the state the
    # STORE is in — which matters, because the recompute that triggers this swap can be the one the
    # toggle itself just caused.
    locale = i18n.resolve_locale(request)
    env = i18n.env_for(locale)
    context = {
        "results": result,
        "workspace_id": ws.id,
        "simulate_cost": cfg.simulate_cost,
        "cost_toggle_blocked": not simconfig_store.is_pricing_configured(ws.id),
    }
    html = (
        env.get_template("_panel_interval.html").render(**context)
        + PANEL_SPLIT
        + env.get_template("_panel_results.html").render(**context)
    )
    return HTMLResponse(html)


def _derived_default(loaded) -> tuple[tuple[datetime, datetime], bool, str | None]:
    """The data-derived opening window, as `(window, custom_range, period_selected)`.

    Shared by the "nothing remembered" case, the explicit `default` button and every fallback, so
    the rule lives in one place. `period_selected` is `PERIOD_DEFAULT` — the "default" button is
    what is highlighted whenever this window is in force, including on a first visit where the user
    has not pressed it, because that is exactly what the screen is showing.
    """
    w_start, w_end, is_preset = results_view.default_window(loaded)
    return (w_start, w_end), not is_preset, results_view.PERIOD_DEFAULT


def _opening_window(
    workspace_id: str, loaded
) -> tuple[tuple[datetime, datetime], bool, str | None]:
    """The window `GET /w/{id}` opens on: `(window, custom_range, period_selected)`.

    Four cases, in order:

      * **Nothing remembered** — the user has not touched the ribbon on this workspace. The window
        is `results_view.default_window`: the trailing year ∩ grid coverage, then ∩ PV coverage
        when a solar series is mapped. Nothing is written back: the default is derived from the
        data and must stay free to move when the data does.

      * **The remembered `default` TOKEN** — the user pressed the "default" button, which is a
        standing instruction to re-derive rather than a window. Recomputed on every load, exactly
        like the case above; the only difference is that the choice is now explicit and survives
        until they pick something else.

      * **A remembered SPAN PRESET** — re-resolved against CURRENT coverage on every load, so
        re-fetching a dataset that reaches further back moves the window. That is the point of
        storing the token rather than the dates it resolved to.

      * **A remembered RANGE** — kept verbatim, because the user typed it. `resolve_window` clamps
        it to coverage, so a re-fetch that shortened the data yields the overlapping part rather
        than an error. When it no longer overlaps AT ALL there is nothing to show, and the screen
        falls back to the `last_1_year` preset AND rewrites the stored value to that preset, so the
        fallback is sticky rather than re-derived (and re-failing) on every subsequent load.

    Never raises: any failure to resolve a remembered period falls back to the computed default.
    The results screen must render.
    """
    stored = simconfig_store.load_results_period(workspace_id)

    if stored is None or stored.get("preset") == results_view.PERIOD_DEFAULT:
        return _derived_default(loaded)

    if "preset" in stored:
        try:
            return results_view.resolve_window(loaded, period=stored["preset"]), False, None
        except ValueError:
            return _derived_default(loaded)

    try:
        return (
            results_view.resolve_window(
                loaded,
                start=_as_utc(datetime.fromisoformat(stored["start"])),
                end=_as_utc(datetime.fromisoformat(stored["end"])),
            ),
            True,
            None,
        )
    except (TypeError, ValueError):
        # The stored range no longer overlaps the data (or is unparseable). Flip to the preset and
        # make that the remembered choice, per the decision recorded in changelog
        # 20260805-results-period-default-and-coverage-warning.md.
        simconfig_store.save_results_period(
            workspace_id, {"preset": results_view.DEFAULT_PERIOD}
        )
        try:
            return (
                results_view.resolve_window(loaded, period=results_view.DEFAULT_PERIOD),
                False,
                None,
            )
        except ValueError:
            return _derived_default(loaded)


def _resolve_results_window(workspace_id: str, body: dict):
    """Turn a `POST /w/{id}/results`-shaped body into (loaded_dataset, window), or a clean 4xx.

    Shared by `POST /w/{id}/results` and `POST /w/{id}/results/benchmark` so the two cannot drift
    on which requests they accept or on which status code each failure gets. `workspace_id` is the
    resolved `Workspace.id`, not raw path input — the caller has been through
    `deps.get_workspace`. The contract, otherwise unchanged from what `/results` already had:

        {"period": "<preset>"}             — one of results_view.PERIOD_DAYS, coverage-anchored, OR
        {"period": "default"}              — re-derive the opening window (results_view
                                             .PERIOD_DEFAULT); a RULE, not a span, so it is
                                             resolved here rather than by `resolve_window`, OR
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

    # The "default" button: a rule rather than a span, so it is answered here and never reaches
    # `resolve_window` (which knows only PERIOD_DAYS and would reject it). Combining it with a
    # range is still an error, and is caught by the same mutual-exclusivity check as any preset —
    # hence the explicit test rather than an early return above the marshalling.
    if period == results_view.PERIOD_DEFAULT:
        if start_raw is not None or end_raw is not None:
            raise HTTPException(
                status_code=400,
                detail="give either a preset period or an explicit start/end range, not both",
            )
        w_start, w_end, _ = results_view.default_window(loaded)
        return loaded, (w_start, w_end)

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
                        # `workspace.id` and `req.binding` are what a CSV slot needs beyond
                        # (slot, window) — D-BIND. The binding travelled on this very message
                        # (`app/ingest_ws.py`) because it lives browser-side, so `workspace.id` is
                        # also what scopes the `uploads.get` that validates the client's upload id:
                        # a foreign id fails here and takes the whole fetch with it, which is the
                        # all-or-nothing contract doing the right thing rather than a special case.
                        frame, load_warnings = await asyncio.to_thread(
                            _load_backend_frame,
                            req.name,
                            req.source,
                            req.window,
                            workspace_id=workspace.id,
                            binding=req.binding,
                        )
                        backend_frames.append(frame)
                        sources_map[frame.name] = req.source
                        # §7.3's data-quality box reports these (gap cells, the October ambiguous
                        # hour), counted against this fetch's window. Stamped with the series name
                        # the same way `build_frames` stamps the HA warnings, so the box can name
                        # the slot rather than an anonymous count.
                        for warn in load_warnings:
                            warn["series"] = frame.name
                        warnings.extend(load_warnings)

                    frames = ha_frames + backend_frames
                    # Persistence is I/O, so it runs off the event loop (specs §5.1 adapters).
                    dataset_id = await asyncio.to_thread(
                        dataset.save_dataset,
                        frames, window, session.source or "home_assistant", warnings, sources_map,
                        workspace_id=workspace.id,
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

# The one source whose `load` needs more than `(slot, window)`: an uploaded wide CSV holds many
# columns and a workspace holds many uploads, so a CSV slot carries a `(upload_id, column, unit)`
# binding (D-BIND of the CSV-import brief). Both backend-load call sites below pass the binding
# extras ONLY for this key.
#
# Why a key comparison and not "pass the extras to everyone": the `DataSource` protocol is
# `load(slot, window)` and each source's extras are keyword-only additions of its own
# (`app/sources/base.py`). `EnergyChartsSource.load` takes `opener`/`now`, so a blanket
# `binding=None` would raise `TypeError` there — the narrowness of the protocol is deliberate and
# its price is that the caller must know whose extras it is holding.
#
# Read off `csv_source`'s own descriptor rather than spelled `"csv_upload"` here, so the two cannot
# drift; the key is persisted with a slot's chosen source and is stable by contract (§2.2).
_CSV_SOURCE_KEY = CsvSource().descriptor.key


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


def _load_backend_frame(
    slot_name: str,
    source_key: str,
    window,
    *,
    workspace_id: str | None = None,
    binding: dict | None = None,
) -> tuple[SeriesFrame, list[dict]]:
    """Load one staged backend-load slot into a frame + its warnings (WS reify path, specs §2.2).

    Runs on a worker thread (called via asyncio.to_thread). Raises ingest_ws.IngestError on any
    validation or load failure so the WS route reports LOAD_FAILED and persists nothing — the
    all-or-nothing reify contract. The window is normalised to tz-aware UTC like the endpoint.

    **Returns `(frame, warnings)`, not a bare frame** (changed in step 5 of the CSV-import brief).
    Only the CSV source produces warnings on this path, and §7.3's data-quality box wants them: how
    many cells were gaps and which days the October DST fold touched, counted against the WINDOW
    this fetch asked for. A bare-frame return would have silently dropped them for every CSV slot,
    which is why the second element is not optional — `energy_charts` simply returns an empty list.

    `workspace_id` and `binding` are the per-slot extras a CSV slot needs (D-BIND). They are passed
    on to `load_with_warnings` ONLY for the CSV source, and that condition is not defensive tidiness:
    `EnergyChartsSource.load`'s keyword-only extras are `opener` and `now`, so handing it a
    `binding=` raises `TypeError: unexpected keyword argument` and would break the price path. The
    `DataSource` protocol is deliberately narrow (`app/sources/base.py`) precisely so that each
    source's extras are its own business, and that means the caller has to know whose extras it
    holds. Keyed on the descriptor key rather than `isinstance`, because the key is the stable
    persisted identity of a source and is what the client sent.

    `binding` arrives as the raw dict from the WS message and is converted here. Two things make
    that conversion the security boundary rather than a formality:

      * the `upload_id` is **client-supplied** (the binding lives in browser localStorage under
        D-BIND, and the WS message is its only path to the server), so `uploads.get` is what decides
        whether this workspace actually has that upload;
      * `uploads.get` is **workspace-scoped** — it filters on `workspace_id`, so an id belonging to
        another workspace resolves to None exactly like one that never existed, and `CsvSource`
        raises rather than reading it. Guessing another workspace's id therefore buys nothing.

    The existence check is left to `CsvSource.load_with_warnings`, which already performs it and
    raises `CsvBindingError` naming the file — doing it here as well would be a second copy of the
    same query with the same answer.

    D-SEQ holds by construction on this path: the load (and the `uploads.get` inside it) runs to
    completion before the caller opens `dataset`'s transaction to persist, so the two writers never
    nest. Anyone moving this call inside a `dataset.connect()` block would deadlock on
    "database is locked".
    """
    try:
        slot, source = _resolve_backend_source(slot_name, source_key)
    except ValueError as exc:
        raise ingest_ws.IngestError(str(exc)) from exc
    win = (_as_utc(window[0]), _as_utc(window[1]))
    try:
        if source.descriptor.key == _CSV_SOURCE_KEY:
            return source.load_with_warnings(
                slot,
                win,
                workspace_id=workspace_id,
                binding=_csv_binding(binding),
            )
        return source.load(slot, win), []
    except CsvBindingError as exc:
        # Its own branch so the message says "this slot is not configured" rather than reading like
        # a transport failure. The WS protocol has exactly one error shape (an `error` frame), so it
        # still becomes an IngestError — but the wording is what the user sees, and "could not load
        # X from csv_upload: …" would blame the file for a choice that was never made.
        raise ingest_ws.IngestError(
            f"slot {slot_name!r} is not fully configured: {exc}"
        ) from exc
    except Exception as exc:  # network down / rate-limited / parse failure
        raise ingest_ws.IngestError(
            f"could not load {slot_name!r} from {source_key!r}: {exc}"
        ) from exc


def _csv_binding(binding: dict | None) -> CsvBinding | None:
    """The WS/JSON binding dict as a `CsvBinding`, or None when the client sent none.

    None is passed through rather than turned into an error here so that the SOURCE reports the
    missing binding: `CsvSource.load_with_warnings` raises `CsvBindingError` naming the slot and
    telling the user what to choose in the drawer, which is a better message than anything this
    function knows enough to write.

    `unit` defaults to `CsvBinding`'s own default (kWh, the drawer's default radio) when absent, so
    an older or minimal client that sends only `{upload_id, column}` gets the documented default
    rather than a rejection. An unknown unit is NOT rejected here: `CsvSource` checks it against
    `csv_wide.UNIT_FACTORS` before reading the file and raises `bad_unit` naming the accepted
    values, and a second copy of that vocabulary here would be one more place to update.

    The fields' shapes were already checked by `ingest_ws._check_binding_shape` on the WS path.
    `load_slot` calls this on a hand-written request body that has had no such check, so this
    function has to be safe on its own. Two halves to that, and only the second was here at first:

      * the `.get`-plus-`str` spelling handles a missing or oddly-typed FIELD — a missing key becomes
        `""`, which `CsvSource` reports as a missing/unknown column rather than raising;
      * the isinstance check handles a binding that is not an object at all. `"binding": "a string"`
        used to reach `.get` and raise `AttributeError: 'str' object has no attribute 'get'`, which
        `load_slot`'s bare `except Exception` reported as a 502 with that text in it. A non-dict
        binding is malformed client input, so it is a `CsvBindingError` and therefore a 400 — the
        same answer, and the same reasoning, as a malformed `upload_id` inside a well-shaped one.
        `ingest_ws._check_binding_shape` already rejects it with its own message on the WS path, so
        this branch is reachable only from `load_slot`.
    """
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise CsvBindingError(
            f"the CSV binding must be an object with 'upload_id' and 'column', "
            f"not {type(binding).__name__}."
        )
    unit = binding.get("unit")
    return CsvBinding(
        upload_id=str(binding.get("upload_id") or ""),
        column=str(binding.get("column") or ""),
        **({"unit": str(unit)} if unit is not None else {}),
    )


@app.post("/w/{workspace_id}/data/slot/{slot_name}/load")
async def load_slot(
    slot_name: str,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
    body: dict = Body(...),
):
    """Load one slot from a backend_load source and merge its series into the latest dataset.

    Body: {"source": "<source_key>", "window": {"start": "<iso>", "end": "<iso>"}}, plus an optional
    `"binding": {"upload_id": …, "column": …, "unit": …}` for a source that needs one (today only
    `csv_upload` — D-BIND of the CSV-import brief). The window is
    parsed like the WS ingest header (tz-aware ISO, end > start). The source is looked up in the
    registry, must offer this slot, and must be a backend_load source — a browser_fetch source
    (Home Assistant) is rejected here because its frame arrives over the ingest WS, not this call.

    The source's `load` and the `upsert_series` merge both do file/network I/O, so they run off the
    event loop (asyncio.to_thread). On success the response reports the dataset id, the series name,
    its resolution and interval count, any load warnings (§7.3: the CSV path's gap and DST-ambiguity
    counts, empty for every other source), and the panel-① grid report (the same shape the WS path
    returns) so the caller can re-render without a full reload. Unknown slot/source, an unavailable
    or wrong-kind source, and a load/network failure all return a clean 4xx/5xx JSON error rather
    than a 500 stack trace (specs §3.2 LOAD_FAILED).

    **`CsvBindingError` is 400, and that is a fix rather than an addition** (step 5 of the brief).
    The bare `except Exception` below maps every load failure to 502, and an unconfigured slot — no
    file and column chosen yet, or a binding naming an upload this workspace does not have — was
    therefore reported as a bad gateway. There is nothing upstream of this app to be a bad gateway;
    the condition is "you have not told us what to load", which is the client's input and a 400. The
    branch is ordered above the generic one deliberately, since `CsvBindingError` is a `ValueError`
    and would otherwise be swallowed by it (`CsvBindingError`'s own docstring records this).

    **Every malformed binding takes that same 400 branch**, which is a review fix rather than the
    original behaviour. Two shapes reached the generic 502 instead: a `binding` that is not an object
    (`"binding": "a string"` answered 502 with `'str' object has no attribute 'get'`) and an
    `upload_id` that is not 32 lowercase hex (`../../etc/passwd` answered 502, because the traversal
    guard in `uploads._check_upload_id` raises a plain `ValueError`). Both are client input, so both
    are 400 now — see `_csv_binding` and `CsvSource.load_with_warnings` for where each is translated,
    and note that neither fix touched the guard itself.

    **The `upload_id` in a binding is client-supplied and is validated server-side**, which on this
    route is the only thing standing between a guessed id and another workspace's file. The check is
    `uploads.get(ws.id, upload_id)` inside `CsvSource`, scoped to the workspace the URL named and the
    principal `deps.get_workspace` already authorised — so a foreign id is indistinguishable from a
    nonexistent one and neither loads. Nothing is persisted on that path: the `upsert_series` call is
    strictly after the load.

    Note this route is not what the drawer uses — the fetch reifies staged slots over the WS instead
    (`ha_fetch.js`'s "Staged-then-confirm" comment) — but it is a real route with the same exposure,
    so it gets the same validation rather than relying on being unused.
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
    #    The CSV source takes the per-slot binding extras; every other source must NOT be handed
    #    them (see `_CSV_SOURCE_KEY` on why a blanket pass raises TypeError in energy_charts).
    binding = body.get("binding")
    try:
        if source.descriptor.key == _CSV_SOURCE_KEY:
            frame, load_warnings = await asyncio.to_thread(
                _load_csv_for_endpoint, source, slot, window, ws.id, binding
            )
        else:
            frame, load_warnings = await asyncio.to_thread(source.load, slot, window), []
    except HTTPException:
        raise
    except CsvBindingError as exc:
        # 400, not the 502 below: an unconfigured slot is bad input, not a failed upstream call.
        # See the docstring.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # network down / rate-limited / parse failure → clean 502
        raise HTTPException(
            status_code=502,
            detail=f"could not load {slot_name!r} from {source_key!r}: {exc}",
        ) from exc

    dataset_id = await asyncio.to_thread(
        dataset.upsert_series, frame, source_key, window, workspace_id=ws.id
    )
    report = normalize.grid_report([frame], window)
    return JSONResponse(
        {
            "dataset_id": dataset_id,
            "series": frame.name,
            "resolution_s": frame.resolution_s,
            "intervals": int(len(frame.values)),
            "warnings": load_warnings,
            "grid": _jsonable_grid(report),
        }
    )


def _load_csv_for_endpoint(source, slot, window, workspace_id: str, binding: dict | None):
    """`CsvSource.load_with_warnings` with the endpoint's binding extras. Runs on a worker thread.

    A named function rather than a lambda or a `functools.partial` inside the `to_thread` call
    because `asyncio.to_thread` forwards keyword arguments to the CALLABLE, and reading a
    five-argument `to_thread(...)` line correctly requires knowing that — a `partial` there would
    put the same knowledge one level further away. It exists only to hold that signature; every
    decision it embodies is documented at `_load_backend_frame` and `_csv_binding`.
    """
    return source.load_with_warnings(
        slot, window, workspace_id=workspace_id, binding=_csv_binding(binding)
    )


# --- uploaded wide CSVs (specs §4.2a, §2.2 "The CSV source") --------------------------------
#
# Three routes, one resource: the wide CSV files a workspace has uploaded. They exist because
# uploading a file and binding a slot to one of its columns are TWO separate user actions (§2.2) —
# a wide export holds many measurements, so one upload feeds many slots and cannot be part of a
# fetch without forcing a re-upload per run. The upload dialog drives all three: POST adds a file,
# GET lists what is there, DELETE removes one.
#
# Persistence is `app/uploads.py` and parsing is `app/domain/csv_wide.py`. Neither calls the other,
# and the join is here on purpose: `uploads.create` does not parse and therefore cannot reject, so
# "a rejected upload writes nothing" (§4.2a "Validation and failure", harness fixture 22) is a
# property of THIS route's ordering — parse first, write only with a summary in hand.


def _upload_json(upload, summary=None) -> dict:
    """One `uploads.Upload` as the dialog's JSON, optionally enriched with a fresh parse summary.

    The stored row is the common part: identity, the user's filename, the declared zone, the
    header, and the coverage the dialog and the drawer's file selector display (§2.2's
    "uploaded 2026-08-05 · 8,760 rows · hourly" line and the file list's
    "8,760 rows · hourly · 4 columns").

    `columns` includes the timestamp column at index 0, exactly as `Upload.columns` holds it, and
    the drawer's column selector offers `columns[1:]` — see `uploads.Upload`. Sending the whole
    list rather than the tail keeps a column's index in this array equal to its position in the
    file, which is what `csv_wide` is asked for by name and what a step-6 reader will assume.

    **`columns[0]` is NOT uniquified and may be empty or a duplicate — a trap for index-based
    code.** `csv_wide._value_column_names` runs its de-duplication over `header[1:]` only, so the
    timestamp name never participates: header `,A,B` yields `["", "A", "B"]` and header
    `Tijdstip,Tijdstip` yields `["Tijdstip", "Tijdstip"]` (both verified, both stored, both 201).
    Name-based resolution is unaffected, which is why this is a trap and not a live bug —
    `parse_column_values` looks the name up in `wide.cells`, which is keyed by the uniquified
    value-column names alone and returns the right column. What breaks is INDEX arithmetic over this
    array: `columns.indexOf(name)` can return 0, i.e. the timestamp column, on the duplicate case.
    Step 6 should populate the selector by slicing (`columns.slice(1)`) and send the NAME back, never
    an index derived by searching this list.

    `cumulative_columns` is on BOTH the POST and the LIST, and that is the whole reason it is a
    stored column rather than a fresh-parse extra like the two fields below. The drawer fills its
    file cache from the LIST route (`ha_fetch.js` `refreshCsvUploads`), so a verdict carried only by
    the POST response would annotate the column picker right after an upload and then silently
    disappear on the next page load — the worst shape for a warning, since its absence reads as "this
    column is fine". `null` means the row predates the column and no verdict was ever computed; `[]`
    means computed and nothing flagged. The client must keep those apart, because only the second
    licenses "no warning".

    `summary` is passed only by the POST, which has just parsed the file and therefore holds two
    fields the ROW does not carry: `ambiguous_rows` (how many samples the October fold resolution
    touched — §7.3's data-quality box reports it) and `timestamp_name` (row 1's first cell, so the
    dialog can echo which column it treated as the timestamp). Neither is persisted: the `uploads`
    table has no column for either and both are recomputable by re-parsing the stored file, so a
    column would be a cache rather than a fact. The consequence, stated because it is the kind of
    asymmetry a later reader trips over: the GET list does not report them, because it reads rows
    and never opens a file.

    Timestamps are ISO-8601 with an explicit offset (they are tz-aware UTC by the time they reach
    here — `uploads._parse_ts`), which is what `Date.parse` in the browser accepts unambiguously.
    """
    payload = {
        "id": upload.id,
        "filename": upload.filename,
        "tz": upload.tz,
        "columns": list(upload.columns),
        "rows": upload.rows,
        "resolution_s": upload.resolution_s,
        "first_ts": upload.first_ts.isoformat() if upload.first_ts else None,
        "last_ts": upload.last_ts.isoformat() if upload.last_ts else None,
        "uploaded_at": upload.uploaded_at.isoformat(),
        "cumulative_columns": (
            None
            if upload.cumulative_columns is None
            else list(upload.cumulative_columns)
        ),
    }
    if summary is not None:
        payload["ambiguous_rows"] = summary.ambiguous_rows
        payload["timestamp_name"] = summary.timestamp_name
    return payload


def _cumulative_columns(wide) -> list[str]:
    """The value columns of a parsed wide CSV that look like cumulative meter registers.

    Run once at upload and stored on the row (`uploads.Upload.cumulative_columns`), so the drawer can
    print small print beside its column picker on any later page load without re-parsing the file.
    The verdict is `csv_wide._looks_cumulative`'s and is deliberately not re-derived here — this
    function only decides WHICH columns to ask about and how to handle the ones it cannot ask about.

    **A column that does not parse as numbers is skipped, not reported and not raised on.** §4.2a
    puts the numeric check at SELECTION, not at upload: a file with one text column and five good
    ones is a legitimate upload whose other columns must stay bindable, and the whole reason
    `WideCsv` keeps cells as strings is that no single column may invalidate the file. So a
    `CsvFormatError` here means "no verdict for this column", which is the same answer as "not
    flagged" from the picker's point of view — the user selecting that column gets the non-numeric
    rejection at fetch time, which is the message that actually helps them.

    Cost: one float parse per cell of every value column, on top of the parse that just ran. On the
    expected shape (a year of quarter-hourly readings across ten columns) that is the same order of
    work as the timestamp parsing already done, and it happens once per upload rather than per fetch.
    Called from a worker thread for that reason.
    """
    flagged: list[str] = []
    for column in wide.columns:
        try:
            values = csv_wide.parse_column_values(wide, column)
        except csv_wide.CsvFormatError:
            continue
        if csv_wide._looks_cumulative(values):
            flagged.append(column)
    return flagged


async def _read_capped_body(request: Request, limit: int) -> bytes:
    """Read a request body, refusing anything over `limit` bytes. 413 on either check.

    **This is where `uploads.MAX_UPLOAD_BYTES` is actually enforced**, and the reason it is a
    hand-rolled stream read rather than a FastAPI `UploadFile` parameter is worth stating, because
    the obvious spelling does not work. Declaring `file: UploadFile = File(...)` makes Starlette
    parse the WHOLE multipart body before the handler's first statement runs, so any size check
    written in the handler is a check after the memory has already been spent — precisely the
    mistake `uploads.MAX_UPLOAD_BYTES`' own comment warns about one layer down ("rejecting here
    would be too late to have protected anything"). Taking the raw `Request` is what puts the check
    genuinely at the edge.

    Two checks, and both are needed:

      * **`Content-Length`, when present.** The cheapest possible answer: the client has told us
        the size, so an oversized upload is refused before a single body byte is read. Not
        sufficient on its own — the header is client-supplied and can lie, and it is absent
        entirely under chunked transfer encoding.
      * **The accumulated byte count while streaming.** Authoritative, and it aborts the read the
        moment the total exceeds the cap rather than after the body finishes, so a 10 GB upload
        costs `limit` bytes of memory and not 10 GB. This is the check that holds when the header
        is missing or false.

    413 (Payload Too Large) rather than 400: the request is well-formed and the client's mistake is
    the size, which is the one thing this status names. `app/main.py`'s 404/400/502 convention
    covers unknown / bad input / load failure and has no opinion here.

    **The buffered bytes are written back to `request._body` on success**, which is what lets the
    caller then call `await request.form()` to parse the multipart. Draining `stream()` by hand sets
    Starlette's `_stream_consumed` flag WITHOUT populating `_body` (only `Request.body()` does
    that), so a later `form()` raises `RuntimeError("Stream consumed")` — reproduced, and the reason
    this assignment is not merely an optimisation. Reaching for a private attribute is the cost of
    doing the size check before the parse; `Request.body()` is the public spelling and it has no
    limit parameter, so the alternative is to read the whole body unbounded first, which is the one
    thing this function exists to avoid.

    It works because `Request.stream()` opens with `if hasattr(self, "_body")` and yields it, so the
    assignment BYPASSES the `_stream_consumed` guard rather than defeating it. That is a private
    attribute on a pinned version (Starlette 1.3.1), and the tests here pin only the EFFECT — that
    `form()` parses after a capped read — not the mechanism. So an upgrade that renamed `_body` or
    reordered that check would fail these tests loudly rather than silently, which is the property
    that matters, but the coupling is real and this is where a reader should learn about it.

    **A client that vanishes mid-body answers 400, and that is a regression this function had to
    repair rather than an improvement it invented.** `request.stream()` raises
    `starlette.requests.ClientDisconnect` when it receives an `http.disconnect`, and a stock
    `file: UploadFile = File(...)` route on the pinned stack answers 400 for that same request —
    verified side by side. Taking the raw `Request` therefore moved an ordinary network event (the
    user hit Escape, the laptop's wifi dropped mid-upload) from a handled 400 into an unhandled
    exception and a logged traceback. Nothing reaches the client either way, since the client is
    what left; the cost was purely a spurious traceback in the log for a non-event. Caught and
    answered 400 to match the stack's own behaviour.

    ## What the cap does and does not bound — measured

    The cap bounds the BODY, not the peak memory of handling it, and the ratio between them depends
    on the file's SHAPE rather than its size. Measured on the pathological shape: a 30.02 MiB body
    (under the 32 MiB cap), 2618 rows × 2000 columns, declared `Europe/Amsterdam` → peak RSS
    **727 MB** over 2.23 s, roughly **19x** the body. The multiplier is three live representations
    with different overheads — the raw bytes, the decoded `str`, and then one small Python `str`
    object per cell out of `csv.reader`, where a 5-byte cell costs ~54 bytes of object header.

    `MAX_UPLOAD_BYTES`' own docstring reasons from the EXPECTED shape ("a year of quarter-hourly
    readings across ten columns is roughly 4 MB"), which is true and is the right basis for sizing
    the cap, but it does not bound the pathological one — so the cap should not be read as a memory
    bound, which is how a docstring calling it a DoS control invites it to be read. Severity is
    genuinely limited rather than merely assumed to be: the app is localhost, single-user, and both
    mutating upload routes are same-site checked, so the only principal who can reach this is the
    user themselves, spending their own RAM on their own machine. Recorded rather than fixed for that
    reason. If it ever needs bounding, a column-count limit checked at the header is the cheap lever,
    since the count is known before any cell is allocated.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"file too large: {declared} bytes, limit is {limit}",
                )
        except ValueError:
            # An unparseable Content-Length is not a size problem; let the streaming check decide.
            # Rejecting here would answer 400 for a header the request may not even have needed.
            pass

    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                # Deliberately worded WITHOUT a byte count, so it cannot be confused with the
                # header branch above — which names the declared size. That difference is what
                # lets a test tell the two branches apart; a shared message made deleting the
                # header check entirely a silent mutation (review item M3).
                raise HTTPException(
                    status_code=413,
                    detail=f"file too large: over the limit of {limit} bytes",
                )
            chunks.append(chunk)
    except ClientDisconnect as exc:
        # The client went away mid-body. 400 to match what a stock UploadFile route answers for
        # the identical request (see the docstring); no response actually reaches anyone.
        raise HTTPException(
            status_code=400, detail="the upload was interrupted before the body finished"
        ) from exc
    body = b"".join(chunks)
    request._body = body  # see the docstring: without this, `request.form()` cannot re-read it
    return body


@app.post(
    "/w/{workspace_id}/data/uploads", dependencies=[Depends(csrf.require_same_site)]
)
async def create_upload(
    request: Request,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
):
    """Upload one wide CSV: parse it, store it, and return the dialog's summary (§4.2a, §2.2).

    Multipart form with two fields: `file` (the CSV) and `tz` (one of `csv_wide.TZ_KEYS` —
    `Europe/Amsterdam` or `UTC`, decision D-TZ). The zone is asked per file because the format
    carries no offset, and it is applied HERE, once: the parser converts to UTC and nothing
    downstream of this route ever sees a naive timestamp.

    **The ordering is the contract, not an implementation detail.** §4.2a and harness fixture 22
    both require that a rejected upload leaves no row and no file, and `uploads.create` cannot
    provide that — it never looks inside a file, so it cannot reject one. So every check runs
    strictly above the `uploads.create` call: size, then decode, then the declared zone, then the
    full parse. Only a file that has already yielded a summary is written. `_cumulative_columns`
    also runs above the write, and is not a check — it can only produce a verdict, never a
    rejection.

    Statuses, following the convention at `load_slot` above (404 unknown, 400 bad input, 502 load
    failure), plus one this path adds:

      * **413** — over `uploads.MAX_UPLOAD_BYTES` (see `_read_capped_body`).
      * **400** — a missing field, an undecodable file, an unknown zone, or any
        `CsvFormatError` from the file-level parse. The response body carries the parser's
        machine-readable `code` and its 1-based `row` alongside the English message, so the dialog
        can render its own translated wording and name the offending row (§4.2a: say what was
        expected, what was found, and where). See the note on i18n below.
      * **404** — an unknown or unowned workspace, from `deps.get_workspace`.

    **i18n: the `detail` message is English and that is deliberate for this increment.**
    `CsvFormatError`'s messages are built in `app/domain/`, which is pure and has no i18n plumbing,
    and translating them at the boundary means a code→string table that belongs with the code that
    renders it. The established shape for exactly this is already in the drawer: `drawer_i18n`
    holds `ingest_rejected` as a translated envelope around an untranslated server reason. Step 6
    owns the table.

    **What step 6 can rely on, stated precisely, because an earlier version of this note overclaimed
    it.** Every 4xx these three routes RAISE THEMSELVES answers with
    `detail = {"code", "message", "row"}` — the parser's codes, plus `unreadable_csv`,
    `bad_encoding`, `no_file`, `bad_timezone` and `bad_upload_id`. That is a
    guarantee about this module's own rejections and nothing more. It does **not** cover a 400 raised
    by the stack BEFORE this handler runs: python-multipart enforces its own field/part limits and
    answers with a bare string (`"Too many fields. Maximum number of fields is 1000."`, verified),
    and Starlette owns that response. So step 6's handler must treat `detail` as
    `dict | str`: key off `detail.code` when it is a dict, and fall back to a generic
    "could not read that upload" message when it is not. Reshaping Starlette's own error into this
    envelope would mean an exception handler intercepting every route in the app to fix a message on
    one of them, which is a worse trade than a two-line fallback in the caller.

    The parse runs on a worker thread: a year of quarter-hourly readings across ten columns is
    tens of thousands of `strptime` calls, which is enough to stall the event loop.
    """
    # The size check happens HERE, before anything is parsed. The return value is discarded because
    # what matters is the side effect: the bytes are buffered onto the request, which is what lets
    # `form()` below parse the multipart it can no longer re-read from the stream.
    await _read_capped_body(request, uploads.MAX_UPLOAD_BYTES)

    # Multipart parsed from the buffered body (`_read_capped_body`'s docstring on `request._body`).
    form = await request.form()
    tz = str(form.get("tz") or "")
    upload_file = form.get("file")

    # The `str` half of this check is not defensive padding: Starlette's multipart parser classifies
    # a part by whether its Content-Disposition carries a `filename=`, and a `file` part without one
    # arrives as a plain string form value with no bytes to read. Both shapes are "no file".
    if upload_file is None or isinstance(upload_file, str):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_file",
                "message": "No file was submitted (expected a 'file' part).",
                "row": None,
            },
        )
    # A stored name is DISPLAY-only (`uploads.Upload.filename`) and never a path component, so a
    # missing one is not worth a rejection — it gets a placeholder instead.
    filename = getattr(upload_file, "filename", None) or "upload.csv"
    content = await upload_file.read()

    # The zone is validated against `TZ_KEYS` here as well as in the parser. The parser's own
    # rejection (`code="bad_timezone"`) is a backstop for a programming error; this one is the
    # user-facing check on a submitted form value, and doing it before the decode means a
    # mis-declared zone is not reported as an encoding problem.
    # An ABSENT `tz` lands here too, as `""` — `form.get("tz") or ""` collapses both, and they are
    # the same mistake from the dialog's point of view (the radio has a default, so neither shape
    # should ever be sent). The code does not distinguish them; the message names what was expected.
    if tz not in csv_wide.TZ_KEYS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_timezone",
                "message": (
                    f"Unknown timezone {tz!r}. Expected one of: "
                    f"{', '.join(csv_wide.TZ_KEYS)}."
                ),
                "row": None,
            },
        )

    # Decoding is the ROUTE's job — `csv_wide.parse_and_summarise` takes `str`, and the parser
    # strips a UTF-8 BOM from the timestamp column name itself. A Dutch supplier export saved as
    # Latin-1 is a real possibility and raises here; answered as a 400 with its own code rather
    # than a 500, and deliberately NOT retried under a fallback encoding: guessing would store a
    # file whose column names are silently mojibake, and the binding keys on those names.
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_encoding",
                "message": (
                    "The file is not valid UTF-8 text, so its contents could not be read. "
                    "Save or export it as UTF-8 and upload it again."
                ),
                "row": None,
            },
        ) from exc

    try:
        wide, summary = await asyncio.to_thread(csv_wide.parse_and_summarise, text, tz)
    except csv_wide.CsvFormatError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc), "row": exc.row},
        ) from exc
    except csv.Error as exc:
        # `csv.Error` is NOT a `CsvFormatError` and NOT even a `ValueError` — it derives straight
        # from `Exception` — so catching the parser's own error type alone let it escape as a 500.
        # The reachable case is a single cell over the csv module's 128 KiB field limit
        # (`_csv.Error: field larger than field limit (131072)`), which a ~200 KB body produces
        # nowhere near `MAX_UPLOAD_BYTES`. Caught here rather than in `csv_wide`: the parser is pure
        # and `csv.Error` is a fact about the stdlib reader it happens to use, not about the wide
        # format, so translating it is the adapter's job. Given its own code so step 6's table can
        # word it without string-matching, and no `row` — the reader fails before it yields one, and
        # inventing a number would point the user at the wrong line.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unreadable_csv",
                "message": (
                    f"The file could not be read as CSV: {exc}. A single value or column name "
                    f"is probably far longer than expected — check that the file is really "
                    f"comma-separated text and not a spreadsheet or an archive."
                ),
                "row": None,
            },
        ) from exc

    # The per-column cumulative verdict, computed here because this is where the file is already
    # parsed. It cannot fail the upload — `_cumulative_columns` swallows the per-column rejections
    # for exactly the reason §4.2a defers them to selection — so it stays above the write with
    # everything else and adds no failure mode of its own.
    cumulative = await asyncio.to_thread(_cumulative_columns, wide)

    # Nothing above this line wrote anything. Everything the store needs is now a parsed fact.
    upload = await asyncio.to_thread(
        uploads.create,
        ws.id,
        filename=filename,
        tz=summary.tz,
        content=text,
        columns=[summary.timestamp_name, *summary.columns],
        rows=summary.rows,
        resolution_s=summary.resolution_s,
        first_ts=summary.first_ts,
        last_ts=summary.last_ts,
        cumulative_columns=cumulative,
    )
    return JSONResponse({"upload": _upload_json(upload, summary)}, status_code=201)


@app.get("/w/{workspace_id}/data/uploads")
async def list_uploads(ws: Annotated[deps.Workspace, Depends(deps.get_workspace)]):
    """Every wide CSV this workspace has uploaded, newest first (§2.2's "Uploaded files" list).

    Feeds two controls: the upload dialog's file list with its `[ remove ]` links, and the drawer's
    **File** select. Ordering is `uploads.list_for`'s — most recent first, because the dialog's list
    is a history and the file a user just added is the one they are looking for.

    A read, so no same-site check (`app/csrf.py` draws its line at destroy-or-create). An empty
    list is a 200 with `{"uploads": []}`, not a 404: "this workspace has no uploads" is an ordinary
    resting state and the dialog renders its own empty list from it.
    """
    rows = await asyncio.to_thread(uploads.list_for, ws.id)
    return JSONResponse({"uploads": [_upload_json(u) for u in rows]})


@app.delete(
    "/w/{workspace_id}/data/uploads/{upload_id}",
    dependencies=[Depends(csrf.require_same_site)],
)
async def delete_upload(
    upload_id: str,
    ws: Annotated[deps.Workspace, Depends(deps.get_workspace)],
):
    """Remove one uploaded file and its row (§2.2's `[ remove ]`). **Idempotent.**

    Same-site checked: this destroys data the user cannot recreate without re-uploading, which is
    the line `app/csrf.py` draws.

    Statuses:

      * **200** — the upload is gone. Returned whether this call is what removed it or whether it
        was already absent, which is the idempotence below.
      * **400** — a malformed `upload_id`, code `bad_upload_id`. The store validates the id's SHAPE
        (32 lowercase hex) before it becomes a path component and raises `ValueError` on anything
        else; caught here so a hand-typed URL segment answers 400 rather than escaping as a 500.
        **The message deliberately does NOT echo the submitted segment.** `uploads._check_upload_id`
        builds its `ValueError` as `f"unsafe upload_id: {upload_id!r}"`, so forwarding `str(exc)`
        reflected raw user input straight back — verified with a `%00` segment, which came back as
        `unsafe upload_id: '\\x00abc'`. That is not an XSS hole at the HTTP layer (the body is JSON
        and the id never reaches a path), but reflecting attacker-chosen bytes buys nothing here: the
        client already knows what it sent, and the only consumer is a dialog whose list it generated
        itself. A fixed message removes the question entirely. **Step 6 must still not `innerHTML`
        any server `message`** — use `textContent` — because the parser's messages legitimately quote
        column names and cell values that came from the user's file.

    ## Why deleting an absent upload succeeds (user decision, 2026-08-06)

    There is no 404 on this route. A DELETE of an upload that is already gone has already achieved
    the end state it asked for, so answering it with an error answers a question nobody asked — the
    same argument `deps.get_optional_workspace` makes for the two workspace-deletion routes, and this
    route previously contradicted it for no reason anyone had decided on. The concrete cost of the
    strict version was a double-click on the dialog's `[ remove ]` link putting an error in front of
    a user whose file is, in fact, removed.

    `response["deleted"]` is the id either way; `response["existed"]` distinguishes the two, `true`
    when this call is what removed the row and `false` when there was nothing to remove. The drawer
    does not need to branch on it — the end state is identical, which is the point — but a caller
    reconciling a stale list can use it to tell "my list was out of date" from "I just did that", and
    a body that answered "deleted" for a no-op with no way to tell would be quietly lying about what
    happened.

    ## What this does NOT weaken: workspace scoping

    Worth stating explicitly, because "make delete idempotent" and "keep foreign ids unreachable"
    sound like they conflict here. They do not, and the reason is that the two guarantees live in
    different places:

      * **A workspace belonging to another PRINCIPAL is 404'd by `deps.get_workspace` before this
        function runs** — verified: `DELETE /w/{someone-elses-ws}/data/uploads/{id}` answers 404 from
        the dependency, and the store is never consulted. That is the whole cross-owner guarantee and
        nothing here touches it.
      * **An id belonging to another workspace of the SAME owner is never acted on**, because
        `uploads.delete` filters on `workspace_id` in its `DELETE ... WHERE workspace_id = ? AND
        id = ?`. It returns False and the other workspace's row and file are untouched — which is
        the property the tests assert, and it is unchanged. What changed is only the STATUS reported
        for that no-op, and only for a requester who owns both workspaces and therefore already knows
        the id, since they are the one who supplied it. A 200 tells them "this workspace has no such
        upload", which is true, and is exactly what they would learn from a 200 on an id that never
        existed anywhere.

    The information-leak argument the old 404 rested on ("distinguishing them would confirm the id
    exists") was aimed at a cross-tenant threat that `deps.get_workspace` already handles. Between two
    workspaces of one owner there is no confidentiality boundary to defend.

    Note the store CANNOT distinguish "never existed" from "exists in another workspace" through its
    public API — `get` returns None and `delete` returns False for both, deliberately, since it has no
    function that answers an unscoped question (`app/uploads.py`, "Owner scoping"). So this route
    could not have kept a 404 for only the foreign case without an unscoped read, and adding one to
    produce a *better error message* would trade the store's central invariant for cosmetics. The
    choice made instead is that both are 200, and neither acts on data outside the workspace.

    ## There is no binding cascade here, and its absence is a decision, not an omission

    §2.2 and harness fixture 22 both say deleting an upload a slot references clears that slot's
    binding. An earlier revision of this docstring carried a `TODO (step 5)` planning that cascade.
    **Step 5 decided the binding lives in the BROWSER** (`localStorage ha.slots.<workspace>`, beside
    the HA statistic id — decision D-BIND, candidate E), so there is nothing server-side to clear:
    this route has no access to it, and no server write could reach it.

    What happens instead, which satisfies the same requirement by a different route:

      * the delete removes the row and the file, unconditionally, as it always did;
      * a local binding still naming that id becomes stale. It reaches the server only on the next
        fetch, where `uploads.get(workspace_id, upload_id)` returns None and `CsvSource` raises
        `CsvBindingError` — the same failure a foreign id gets, since the store cannot tell the two
        apart and does not need to;
      * the drawer drops local entries whose upload is no longer listed (step 6's obligation), so the
        slot returns to "Choose source…" in the UI rather than only failing at fetch time.

    The cost, stated because it is real: the user-facing error arrives at FETCH time rather than at
    delete time for anyone whose drawer has not re-listed the uploads in between. That is the same
    class of staleness the `source_generation` number already handles for a pre-fetch HA choice, and
    it is the trade candidate E was chosen with open eyes (the brief's D-BIND section records the
    alternatives, B and D, that would have made the binding server state and therefore cascadable).

    The retracted plan's one durable rule is kept on record in the brief in case the binding ever
    moves server-side: such a cascade must run **unconditionally, not gated on `existed`**, because
    the retry after a crash between the two writes is exactly the call where `existed` is false.
    """
    try:
        removed = await asyncio.to_thread(uploads.delete, ws.id, upload_id)
    except ValueError as exc:
        # Fixed message, NOT `str(exc)` — see the docstring on why the submitted segment is not
        # echoed back.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_upload_id",
                "message": "That is not a valid upload id.",
                "row": None,
            },
        ) from exc
    # No 404 branch: an absent upload is the end state this request asked for (see the docstring).
    # `existed` reports which of the two happened without changing the outcome of either.
    return JSONResponse({"deleted": upload_id, "existed": removed})


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
