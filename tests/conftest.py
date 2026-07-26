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

Main items:
    W                the `/w/local` prefix.
    w(suffix)        `W + suffix`; the workspace-scoped URL for the default workspace.
    seed_workspace() create the workspace row (idempotent), under the CURRENT data dir.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

WORKSPACE_ID = "local"
W = f"/w/{WORKSPACE_ID}"


def w(suffix: str = "") -> str:
    """The workspace-scoped URL for `suffix` under the default `local` workspace."""
    return W + suffix


def seed_workspace(workspace_id: str = WORKSPACE_ID, title: str = "Test workspace") -> str:
    """Create the workspace row so `deps.get_workspace` resolves it; return its id.

    Idempotent: returns the existing id when the row is already there, so a fixture may call it
    without checking. Imports `app.workspaces` lazily because the caller has usually just pointed
    `BATTERY_SIM_DATA_DIR` at a tmp path and the module resolves the data dir per call.
    """
    from app import workspaces

    if workspaces.get(workspace_id) is None:
        workspaces.create(title, workspace_id=workspace_id)
    return workspace_id
