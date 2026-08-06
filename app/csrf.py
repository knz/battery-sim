"""Same-site enforcement for the routes that destroy or create state.

## What this defends against, and why it was needed

Every route in this app is unauthenticated: there is no session, no token and no login, because
the app is served on the user's own machine against the user's own data. That is a coherent
position for reads, and it was assumed to be a coherent position for writes too — followups B6
recorded exactly that, reasoning that the worst a forged request could do was rewrite a local
parameter set with values the attacker could not see.

Phase 2 made that false. `POST /w/{id}/delete` deletes a workspace's rows, its `simconfig.json`
and its whole directory, and a workspace migrated from a pre-index installation always has the
id `local` — a constant, not a secret. So any page in any tab could submit a form to
`http://localhost:8000/w/local/delete` and irreversibly destroy the user's analysis, with no
guess and no read-back required. That was reproduced before this module existed.

## The check, and why it is headers rather than a token

A CSRF token is the textbook answer and is deliberately NOT what this is. A token needs somewhere
to live — a session cookie, a signed secret, server-side state — and introducing that surface is
the specific thing B6 declined. The browser already tells the server what it needs to know, in
headers that page script cannot forge, so a same-site check gets the same protection for the three
routes that matter with no new state at all.

Two headers, in this order:

  * **`Sec-Fetch-Site` when present.** It is the reliable modern signal: the browser sets it on
    every request it makes, page script cannot override it (it is a forbidden header name), and it
    names the relationship directly — `same-origin`, `same-site`, `cross-site` or `none`.
    `same-origin` and `none` are accepted; `none` is a user-initiated navigation such as a
    bookmark or a typed URL, which is not an attack shape. `same-site` is accepted too: this app
    is served on a bare host with no sibling subdomains, so it is same-origin in practice, and
    rejecting it would break a deployment behind a local reverse proxy for no gain.
  * **`Origin`, when `Sec-Fetch-Site` is absent.** Compared against the host the request was
    addressed to, so a form POST from the app's own page passes and one from anywhere else does
    not. Note `Origin` is what carries the check for a same-origin form POST on browsers that
    predate `Sec-Fetch-*`, which is why both are consulted rather than just the newer one.

## What happens when BOTH headers are absent, and the risk that leaves

The request is **allowed**. This is the one deliberate hole in the check and it is stated rather
than hidden, because "reject everything unlabelled" and "accept everything unlabelled" are both
defensible and only one of them keeps the app working.

The reasoning: a browser attack cannot reach this branch. Any browser new enough to run this
app's `<dialog>`, `fetch` and WebSocket code sends `Sec-Fetch-Site` on every request, and every
browser that has ever implemented cross-origin form POSTs sends `Origin` on them. A cross-site
POST arriving with neither header is not something a browser produces. What DOES arrive with
neither is `curl`, a test client, a scripted local tool, or a proxy configured to strip headers —
all of which are the user acting on their own machine.

The residual risk, stated plainly: a non-browser client on the same machine, or a proxy in front
of the app that strips both headers, can still issue these requests. Closing that would require a
token, which is the option the design decision excluded. If the app ever stops being local-only,
this branch is the first thing that has to change — and by then it would need a session anyway.

## Which routes are covered, and why `POST /w/{id}/params` is not

Covered: `POST /workspaces`, `POST /w/{id}/delete`, `POST /w/{id}/data/delete` — the three that
create or destroy. The two deletions are the reason this module exists; `POST /workspaces` is here
because an unchecked create lets a page fill the user's list with junk analyses, which is noise
rather than damage but is trivially prevented by the same dependency.

Also covered, added with the CSV-import upload routes (specs §4.2a):
`POST /w/{id}/data/uploads` and `DELETE /w/{id}/data/uploads/{upload_id}` — the same
destroy-or-create line applied to a new resource. The DELETE removes a file the user cannot
recreate without re-uploading it, and will additionally clear any slot binding referencing it;
the POST creates persistent per-workspace state. `GET /w/{id}/data/uploads` is a read and is not
covered.

**`POST /w/{id}/params` is deliberately NOT covered, and that asymmetry is a decision.** It is an
idempotent overwrite of one workspace's parameter set with values the forging page chose blind and
cannot read back — which is precisely the threat followups B6 weighed and accepted, and nothing
about phase 2 changed it. Deletion is what changed: it is irreversible and it destroys data the
user cannot recreate. So the line is drawn at "can this request destroy something", not at "is
this request a POST". If that judgement is revisited, add the dependency to `params` too — it is
one line — but it should be revisited on purpose rather than drifted into.

Main items:
    require_same_site()   FastAPI dependency; 403 on a cross-site request, otherwise no-op.
    is_same_site(request) the predicate alone, for callers that are not routes.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

_ALLOWED_FETCH_SITES = frozenset({"same-origin", "same-site", "none"})
"""`Sec-Fetch-Site` values that are not a cross-site request (module docstring).

`cross-site` is the only value rejected. `none` means the request had no initiating document — a
typed URL, a bookmark, a browser-restored tab — which is the user acting directly.
"""


def is_same_site(request: Request) -> bool:
    """Is this request same-site, as far as its headers can say?

    True when `Sec-Fetch-Site` says so, or — when that header is absent — when `Origin` matches the
    host the request was addressed to. Also true when NEITHER header is present, which is the
    documented gap in the module docstring: no browser produces a cross-origin POST without one of
    them, so that branch is for non-browser clients rather than for attacks.

    The `Origin` comparison is against `Host`/`X-Forwarded-Host` as the request itself carries it,
    not against a configured origin. This app is served on whatever host and port the user starts
    it on — `localhost`, `127.0.0.1`, a LAN address — and a configured allowlist would be one more
    thing to get wrong for no security gained: an attacker who can set the `Host` header is not
    coming through a browser, and is already past the check in the branch below.
    """
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site.lower() in _ALLOWED_FETCH_SITES

    origin = request.headers.get("origin")
    if origin is None:
        # Neither header. Allowed — see the module docstring for why, and for what it leaves open.
        return True
    if origin.lower() == "null":
        # An opaque origin: a sandboxed iframe or a `file://` document. Not the app's own page.
        return False

    # `request.url` already reflects the forwarded host when a proxy sets it and Starlette's
    # ProxyHeaders middleware is in play; without a proxy it is the address the client used.
    expected = f"{request.url.scheme}://{request.url.netloc}"
    return origin.rstrip("/").lower() == expected.rstrip("/").lower()


def require_same_site(request: Request) -> None:
    """FastAPI dependency: reject a cross-site request with 403 (module docstring).

    Declared by the three state-changing routes rather than written into each of their bodies, for
    the same reason `deps.get_workspace` is a dependency: it runs before the route body, so no
    route can forget it and no destructive work can begin behind a failed check. It is a separate
    dependency from `get_workspace` because the two answer different questions — "may this request
    be made at all" and "which workspace is it about" — and one route (`POST /workspaces`) needs
    the first without the second.

    403 rather than 404: unlike an unknown workspace id, there is nothing to conceal here. The
    request named something real and was refused for being cross-site, and saying so is what makes
    the refusal debuggable when it fires on a legitimate client.
    """
    if not is_same_site(request):
        raise HTTPException(status_code=403, detail="cross-site request rejected")
