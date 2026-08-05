"""InterestReporter — the outbound feature-interest POST (specs/08-architecture.md §5.1, §7.5).

This is the *only* component in the app that sends anything to a host the user did not nominate
as a data source, and its posture is deliberately conservative:

  * The request fires only when `feature_interest_url` is set. Empty (the stock default) → no
    request, ever.
  * The body is exactly three fields and no more (§7.5): the feature key, the app version, and
    the installation id. No energy data, parameters, results, hostname, or anything else.
  * It is fire-and-forget: a timeout, refused connection, DNS failure or non-2xx response are
    all abandoned silently. No retry, no queue, no user-visible error. The dialog has already
    acknowledged before this resolves and never revises that (§2.1 invariant 1).

Implemented with stdlib `urllib.request` in a worker thread (via asyncio's default executor)
so the request never blocks the event loop and no HTTP-client dependency is added.

Main item:
    report(feature_key, cfg)  schedule the fire-and-forget POST; returns immediately.
"""

import asyncio
import json
import logging
import urllib.request

from app.config import Config

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5


def _post_blocking(url: str, body: dict) -> None:
    """Perform the POST synchronously, swallowing every error (runs off the event loop)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS):
            pass  # response body is ignored; a 2xx and a 5xx are treated the same
    except Exception:  # noqa: BLE001 — every failure is intentionally invisible (§5.1 inv. 1)
        log.debug("feature-interest POST failed (ignored)", exc_info=True)


async def report(feature_key: str, cfg: Config) -> None:
    """Fire the interest POST if an endpoint is configured; otherwise do nothing.

    Runs the blocking request in the default thread-pool executor so it never blocks the loop.
    Awaiting this is optional: the caller may schedule it and return immediately, since the
    result is never inspected.
    """
    if not cfg.feature_interest_url:
        return  # unset endpoint disables the request and nothing else (§5.1 invariant 3)
    body = {
        "feature_key": feature_key,
        "app_version": cfg.app_version,
        "installation_id": cfg.installation_id,
    }
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _post_blocking, cfg.feature_interest_url, body)
