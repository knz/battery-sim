"""Make Python's HTTPS verify against the operating system's trust store.

**The problem this solves.** The app has two independent TLS paths, and they consult two
different trust stores:

  * the page's own requests (app/static/ha_fetch.js opens `wss://` to Home Assistant) run in the
    webview, on the renderer the OS provides, which reads the SYSTEM store;
  * the backend's requests (app/sources/energy_charts_api.py fetches spot prices over urllib)
    run in this process, on CPython's `ssl` over OpenSSL, which reads whatever CA file the
    interpreter was BUILT against.

In a packaged build the second store is typically empty or absent: the bundle carries a
uv-managed interpreter, `certifi` is a dev-only dependency and is excluded from the bundle, and
macOS keychain trust is invisible to OpenSSL. The result was every backend HTTPS request failing
with CERTIFICATE_VERIFY_FAILED "unable to get local issuer certificate" — on machines where the
same URL fetched fine with `curl`, which does use the keychain.

`truststore` closes the gap by delegating verification to the platform: keychain on macOS,
SChannel on Windows, OpenSSL elsewhere (where it is effectively a no-op, since that is the store
already in use). Chosen over bundling `certifi` because it honours certificates the user has
already installed — a private CA, or a corporate TLS-inspecting proxy — rather than shipping a
fixed CA list that ages with each release. See
changelog/20260806-backend-tls-system-trust.md.

**It patches globally, on purpose.** `truststore.inject_into_ssl()` replaces `ssl.SSLContext`,
and `urllib.request` builds its context at request time, so every existing and future call site
picks this up with no change. Passing an explicit context to each `urlopen` would work too, but
would have to be remembered at every new call site.

**It never raises.** Injection can fail on an unexpected interpreter, or if the macOS backend's
ctypes initialisation does. Letting that propagate would turn a certificate bug into an app that
will not start, which is strictly worse: without the patch HTTPS is no more broken than it was
before this module existed. The failure is printed instead, so a session log explains why a
machine is still hitting verification errors — silence would make that undiagnosable.

Main items:
    install_system_trust()   idempotent, never raises; True if `ssl` is now OS-backed.
"""

from __future__ import annotations

import sys

# Set once injection has been attempted, so the repeated calls below cost nothing after the
# first. There are three entry points into this application — the desktop launcher, the ASGI
# app imported directly (tests, any non-desktop host), and scripts/fetch_spot_prices.py — and
# each installs the patch because none of them can assume another ran first.
_installed: bool | None = None


def install_system_trust() -> bool:
    """Route `ssl` verification through the OS trust store. Idempotent; never raises.

    Returns True if the patch is in place, False if it could not be applied — in which case
    HTTPS keeps whatever CA set the interpreter was built with, and a line explaining the
    failure has gone to stderr (which the desktop launcher has already redirected into the
    session log by the time it calls this).
    """
    global _installed
    if _installed is not None:
        return _installed

    try:
        import truststore

        truststore.inject_into_ssl()
        _installed = True
    except Exception as exc:  # noqa: BLE001 - deliberately total; see the module docstring
        # Not a warning the user can act on, which is why it is one line and not a dialog: it
        # matters to whoever reads the log after a certificate failure gets reported.
        print(
            f"warning: could not use the system certificate store ({exc!r}); "
            "HTTPS will fall back to this interpreter's built-in certificates",
            file=sys.stderr,
        )
        _installed = False

    return _installed
