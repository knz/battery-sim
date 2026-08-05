"""Pytest bootstrap: repo root on sys.path, plus the workspace-scoped URL helpers.

The frontend smoke test launches uvicorn as a subprocess (cwd=repo root), so it never needs
`app` importable in the test process. The unit tests, by contrast, import `app.config` /
`app.db` / `app.workspaces` directly. Prepending the repo root here makes those imports resolve
without a src layout or an editable install.

Beyond that, this module holds the two things every route test now needs, since the data routes
moved under `/w/{workspace_id}/…` (docs/specs/08-architecture.md §5.1, changelog phase 1):

  * `W` / `w(suffix)` — the scoped path prefix for the default `local` workspace, so a test says
    `client.post(w("/results"), …)` rather than repeating the prefix at ~90 call sites and
    rewriting them all again the next time the layout moves.
  * `seed_workspace()` — insert the workspace row a route's `deps.get_workspace` resolves.
    `TestClient(app)` used outside a `with` block does not run the FastAPI lifespan, so the
    startup `migrate_local()` never fires in these fixtures; the row has to be created
    explicitly. It is created rather than migrated on purpose — a fixture that seeds its own
    dataset before the client exists has no "pre-index workspace" to adopt, and depending on
    migration behaviour here would couple every route test to phase 0's adoption rules.

Both are plain module-level functions rather than fixtures because most call sites are inside
`_form(...)`-style helpers and parametrize lists, where a fixture argument does not reach.

Finally, this module points `BATTERY_SIM_DATA_DIR` at a throwaway directory for the whole
session, so that running the suite never writes into the developer's real `./data`. See
`_isolate_data_dir` below for why that has to happen here, at import time.

Phase 2 adds one more, for the same reason: `GET /` became the workspace list and the three-panel
page moved to `GET /w/{id}/results`, so a test that wants "the page" asks `page()` for it rather
than writing a literal that will move again when phase 4 splits that screen in two.

Main items:
    W                the `/w/local` prefix.
    w(suffix)        `W + suffix`; the workspace-scoped URL for the default workspace.
    page(id)         the URL of the three-panel page for a workspace (`GET /w/{id}/results`).
    seed_workspace() create the workspace row (idempotent), under the CURRENT data dir, for a
                     given owner (default "local").
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _isolate_data_dir() -> None:
    """Point the data dir at a temp directory for the whole session, unless one is already set.

    Without this, running the suite WRITES to the developer's real `./data`: the first request
    through any unredirected client creates the directory, `feature_interest.db` and the `local/`
    workspace.

    Importing `app.main` used to be enough on its own, via a module-level `CONFIG = config.load()`
    that persisted an `installation_id` into `data/config.toml`. That line went with the
    feature-interest telemetry, so import alone no longer writes — but the first request still
    does, and several test modules construct a client without redirecting.

    It still has to run HERE, at conftest import, rather than in a fixture: pytest imports every test
    module before the first fixture runs, and several of them do `from app.main import app` at
    module level. By the time a session-scoped autouse fixture executed, the write would already
    have happened.

    `setdefault`, not an unconditional set: a developer or CI job that deliberately points
    `BATTERY_SIM_DATA_DIR` somewhere keeps that choice. Individual tests still redirect to their
    own `tmp_path` as before; this only catches the ones that never redirect at all, which would
    otherwise share one directory for the session.
    """
    if os.environ.get("BATTERY_SIM_DATA_DIR"):
        return
    d = tempfile.mkdtemp(prefix="battery-sim-tests-")
    os.environ["BATTERY_SIM_DATA_DIR"] = d
    # Registered rather than left to the OS so a long-lived dev machine does not accumulate one
    # of these per test run. `ignore_errors` because a test may have already removed it.
    atexit.register(shutil.rmtree, d, ignore_errors=True)


_isolate_data_dir()

WORKSPACE_ID = "local"
W = f"/w/{WORKSPACE_ID}"


def w(suffix: str = "") -> str:
    """The workspace-scoped URL for `suffix` under the default `local` workspace."""
    return W + suffix


def page(workspace_id: str = WORKSPACE_ID) -> str:
    """The URL of the RESULTS screen for `workspace_id` (`GET /w/{id}/results`).

    Named for what the tests wanted — "the page" — when it was the app's one screen at `/`. Phase 2
    moved it here and phase 4 split it: what this URL renders is now the battery box and the results
    (§2′.6), and everything about configuring data is at `data_page()` below.

    GET and POST on `/w/{id}/results` are different routes: the GET renders the whole screen, the
    POST returns the period card and the results fragment (see `split_panels`).
    """
    return f"/w/{workspace_id}/results"


def split_panels(html: str) -> tuple[str, str]:
    """Split a `POST /w/{id}/results` response into (period card, results panel).

    The route returns TWO fragments joined by `main.PANEL_SPLIT` — `_panel_interval.html` then
    `_panel_results.html` — because a range change repaints both: the card states the resolved
    window (the active preset, the "dates · N days" line), the panel states the figures. The
    browser splits on the marker and swaps each into its own root.

    Tests use this when an assertion is about ONE of the halves. That matters most for NEGATIVE
    assertions: "no card frame in panel ③" reads as false against the whole response, because the
    period card is a card. Asserting over `r.text` is still right when the claim is about the
    response as a whole (that an anchor and its target both ship in one swap, say).
    """
    from app.main import PANEL_SPLIT

    card, _, panel = html.partition(PANEL_SPLIT)
    return card, panel


def ids_inside(html: str, container_id: str) -> set[str]:
    """Every `id` on an element NESTED INSIDE the element carrying `container_id`.

    For assertions about containment, where source order is not enough: an element that merely
    follows another's opening tag is not inside it, and that difference is exactly what decides
    whether a `hidden` class on the container also hides the element. There is no HTML parser in
    this project's dependencies and the fragments are not well-formed XML (void elements like
    `<input>` are not self-closed), so this tracks open/close depth with the stdlib parser.

    Returns an empty set when the container is absent — callers assert on membership, so a missing
    container fails the assertion rather than passing vacuously.
    """
    from html.parser import HTMLParser

    # Void elements never nest; HTMLParser reports them via handle_starttag with no end tag.
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    class _Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.stack: list[str | None] = []
            self.depth_of_container: int | None = None
            self.found: set[str] = set()

        def handle_starttag(self, tag, attrs):
            ident = dict(attrs).get("id")
            if tag in void:
                if self.depth_of_container is not None and ident:
                    self.found.add(ident)
                return
            if ident == container_id and self.depth_of_container is None:
                self.depth_of_container = len(self.stack)
            elif self.depth_of_container is not None and ident:
                self.found.add(ident)
            self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in void or not self.stack:
                return
            self.stack.pop()
            if self.depth_of_container is not None and len(self.stack) <= self.depth_of_container:
                self.depth_of_container = None   # the container closed; stop collecting

    c = _Collector()
    c.feed(html)
    return c.found


def data_page(workspace_id: str = WORKSPACE_ID) -> str:
    """The URL of the CONFIGURE-DATA screen for `workspace_id` (`GET /w/{id}/data`, §2′.5).

    The other half of what `page()` used to render. The slot roster, the source drawer, the HA
    connection modal, the data-quality box and the glance are all here and only here since phase
    4.2 deleted panel ①, so a test about any of those asks for this URL.
    """
    return f"/w/{workspace_id}/data"


def seed_workspace(
    workspace_id: str = WORKSPACE_ID, title: str = "Test workspace", owner_id: str = "local"
) -> str:
    """Create the workspace row so `deps.get_workspace` resolves it; return its id.

    Idempotent: returns the existing id when the row is already there, so a fixture may call it
    without checking. Imports `app.workspaces` lazily because the caller has usually just pointed
    `BATTERY_SIM_DATA_DIR` at a tmp path and the module resolves the data dir per call.

    `owner_id` defaults to `"local"` — `get_principal()`'s hard-coded principal (changelog
    20260804-owner-scoping.md) — so every existing caller keeps seeding a workspace the default
    principal can see. A caller exercising cross-owner behaviour passes a different one.
    """
    from app import workspaces

    if workspaces.get(workspace_id) is None:
        workspaces.create(title, workspace_id=workspace_id, owner_id=owner_id)
    return workspace_id
