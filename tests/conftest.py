"""Pytest bootstrap: repo root on sys.path, plus the workspace-scoped URL helpers.

The frontend smoke test launches uvicorn as a subprocess (cwd=repo root), so it never needs
`app` importable in the test process. The feature-interest unit tests, by contrast, import
`app.config` / `app.db` / `app.interest` directly. Prepending the repo root here makes those
imports resolve without a src layout or an editable install.

Beyond that, this module holds the two things every route test now needs, since the data routes
moved under `/w/{workspace_id}/…` (specs/08-architecture.md §5.1, changelog phase 1):

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

    Without this, running the suite WRITES to the developer's real `./data`: `app/main.py` does
    `CONFIG = config.load()` at import time, and `config.load()` generates and persists an
    `installation_id` into `data/config.toml` on first run — so merely importing `app.main`
    creates the directory and puts a pseudonymous identity in it. The first request through any
    unredirected client then adds `feature_interest.db` and the `local/` workspace.

    That was never intentional. `app/main.py`'s lifespan carries a comment explaining that its
    workspace creation lives there rather than at import time precisely so it does not "create
    rows in whatever directory happens to be resolved at import time" — but `CONFIG` itself is
    resolved at import time and does exactly that.

    It has to run HERE, at conftest import, rather than in a fixture: pytest imports every test
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
    POST returns just the results fragment.
    """
    return f"/w/{workspace_id}/results"


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
