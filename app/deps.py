"""Request-scoped dependencies: who is asking, and which workspace they are asking about.

This is the seam specs/08-architecture.md §5.1 names in its diagram — `deps.py` with
`get_principal()` and `get_workspace(principal, id)` — and §5.5 invariant 2 requires: *"`Workspace`
is resolved via a FastAPI dependency, never read from a global. In v1 `get_principal()` returns a
hard-coded `Principal(id="local")` and `get_workspace()` returns the single workspace. Adding auth
means replacing exactly these two functions."*

Phase 0 built the `workspaces` table and the service that writes it; phase 1 (this module and the
re-rooted routes in `app/main.py`) is what makes a route's workspace come from the REQUEST rather
than from `db.WORKSPACE_ID`. Before it, every route operated on the module constant, and the
workspace-id parameter that `simconfig_store`, `dataset` and `db` have carried all along was always
defaulted. Now the id arrives in the path (`/w/{workspace_id}/…`) and is passed down explicitly.

## Why a dependency and not a helper the routes call

FastAPI resolves a dependency before the route body runs, which is what makes the 404 for an
unknown workspace uniform: no route can forget the check, and no route body ever runs against a
workspace that does not exist. It also makes the authentication story a replacement rather than an
edit — §5.5's promise above — because `get_principal` is the only thing that would learn about
sessions, and `_authorize` is the only thing that would learn about ownership.

## Two rejections, in this order, and why traversal is checked HERE

`resolve_workspace_id` runs the syntactic check; `get_workspace` runs the existence check.

The syntactic one duplicates a rule the storage layer already enforces:
`simconfig_store._workspace_dir`, `dataset._series_dir` and `workspaces._workspace_dir` each reject
a `workspace_id` containing a separator or equal to `.`/`..` (§5.5 invariant 4). That is the real
guarantee and it stays where it is — this is defence at the edge, not a replacement for it.

It is here anyway because of what the storage layer raises: a `ValueError`, which an unguarded
route turns into a 500 and a stack trace. A path segment is client input, so `/w/..%2F..%2Fetc/params`
is a bad *request*, not a server fault. Checking at the edge makes it a 404 — the same answer an
unknown-but-well-formed id gets, which is also the answer that leaks least: a caller probing for
filesystem shapes learns nothing the "no such workspace" answer does not already tell them.

Note that FastAPI/Starlette's router already resolves `/w/../params` at the routing layer (it never
matches this route), so what actually reaches here is the percent-encoded and multi-segment
variants. The check is written against the id VALUE rather than against any URL spelling, so it does
not depend on which of those the router happens to normalise.

Main items:
    Principal              who is asking. v1: always `Principal(id="local")`.
    Workspace              the resolved workspace row, as passed to a route.
    get_principal()        FastAPI dependency; the hard-coded local principal (§5.5 invariant 2).
    resolve_workspace_id() the syntactic check alone, for callers that are not routes.
    get_workspace()        FastAPI dependency; path id → `Workspace`, or 404.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Path

from app import workspaces


@dataclass(frozen=True)
class Principal:
    """Who is making the request.

    There is no authentication in this build and no second identity: `get_principal` always
    returns `Principal(id=workspaces.OWNER_ID)`. The type exists so the authorization seam is
    already drawn — `_authorize` below takes one, and adding accounts means populating this from a
    session rather than threading a new argument through every route.
    """

    id: str


@dataclass(frozen=True)
class Workspace:
    """A resolved workspace, as a route receives it.

    A thin typed view of the `workspaces` row (`app/workspaces.get`). It carries identity and the
    two timestamps and nothing else — deliberately NOT the configuration or the dataset. A route
    that needs those loads them by id, so resolving a workspace stays a single indexed read even
    on paths (the ingest WebSocket, `/results/benchmark`) that never look at the config.
    """

    id: str
    owner_id: str
    title: str
    created_at: datetime
    updated_at: datetime


def get_principal() -> Principal:
    """The requesting principal. v1: always the local one (§5.5 invariant 2).

    A FastAPI dependency so routes declare `principal: Principal = Depends(get_principal)` rather
    than reading a constant. Adding authentication replaces this function's body — reading a
    session cookie, say — and nothing else.
    """
    return Principal(id=workspaces.OWNER_ID)


def resolve_workspace_id(workspace_id: str) -> str:
    """Reject a path-unsafe workspace id with 404; return it unchanged otherwise.

    See the module docstring for why this lives at the edge as well as in the storage layer. The
    rule is deliberately the SAME one the three `_workspace_dir` helpers apply, so an id this
    accepts is one they accept: no separator, and not `""`, `.` or `..`. A null byte is rejected
    too — it cannot appear in a decoded path segment through Starlette, but it is the one other
    value that means something to a filesystem call.

    404 rather than 400: an id that cannot name a directory cannot name a workspace either, and
    answering "no such workspace" for both keeps the two indistinguishable from outside.
    """
    if (
        not workspace_id
        or "/" in workspace_id
        or "\\" in workspace_id
        or "\x00" in workspace_id
        or workspace_id in (".", "..")
    ):
        raise HTTPException(status_code=404, detail="no such workspace")
    return workspace_id


def _authorize(principal: Principal, row: dict) -> bool:
    """May this principal use this workspace?

    v1 is single-user, so this is `owner_id` equality against the one principal there is, which is
    always true for anything `workspaces.create` wrote. It is a named function rather than an
    inline comparison because it is the whole of the authorization surface: adding accounts means
    changing this and `get_principal`, per §5.5 invariant 2.

    A failure is reported as 404, not 403 — a workspace you may not use should not be
    distinguishable from one that does not exist.
    """
    return row.get("owner_id") == principal.id


def get_workspace(
    principal: Annotated[Principal, Depends(get_principal)],
    workspace_id: Annotated[str, Path()],
) -> Workspace:
    """Resolve `/w/{workspace_id}/…` to a `Workspace`, or 404 (§5.1, §5.5 invariant 2).

    Two checks, both 404 (see the module docstring and `_authorize` for why neither is a 400 or a
    403): the id must be path-safe, and the row must exist and belong to this principal.

    Declared by every workspace-scoped route as
    `ws: Workspace = Depends(deps.get_workspace)`, which is also what puts `{workspace_id}` in the
    OpenAPI schema for those routes without each of them naming it.
    """
    workspace_id = resolve_workspace_id(workspace_id)
    row = workspaces.get(workspace_id)
    if row is None or not _authorize(principal, row):
        raise HTTPException(status_code=404, detail="no such workspace")
    return Workspace(
        id=row["id"],
        owner_id=row["owner_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
