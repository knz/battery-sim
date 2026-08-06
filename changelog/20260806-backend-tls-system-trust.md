# Backend HTTPS fails to verify certificates (system trust store)

## Task Specification

On macOS, loading the `price_spot` slot from the `energy_charts` source fails:

```
could not load 'price_spot' from 'energy_charts': <url open error [SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: unable to get local issuer certificate (_ssl.c:1010)
```

This is on a machine where the earlier Home Assistant certificate problem was already fixed by
adding a private root CA to the macOS keychain and marking it trusted (see
`changelog/20260806-tls-troubleshooting-docs.md`). The user's hypothesis — that server-driven
HTTP requests do not go through the webview and have their own certificate checking — is correct.

Requested: investigate, then fix it using `truststore`, and give the failure a pointer to the
troubleshooting page.

## Investigation

Two independent TLS paths exist, with two different trust stores:

1. **Browser/webview** — `app/static/ha_fetch.js` opens `wss://` to Home Assistant from the page.
   In the packaged app that is a pywebview window on the OS renderer (WKWebView on macOS), which
   reads the **macOS keychain**. This is the path the keychain fix repaired.
2. **Python backend** — `app/sources/energy_charts_api.py:93` calls `urllib.request.urlopen` in
   the FastAPI process (via `app/main.py::_load_backend_frame`, on a worker thread). This is
   CPython `ssl` over OpenSSL. It never consults the keychain; its CA set comes from OpenSSL's
   compiled-in `SSL_CERT_FILE` / `SSL_CERT_DIR` paths.

The keychain fix cannot reach path 2 by construction — the same shape as the earlier
webview-versus-browser split, with a different pair of stores.

Three findings that explain why path 2 has no usable CA set in the packaged macOS app:

- **Nothing in the app configures TLS.** No `SSLContext`, `certifi`, `SSL_CERT_FILE`,
  `truststore` or `load_default_certs` anywhere under `app/`. `urlopen` gets the bare default.
- **`certifi` is not in the bundle.** It appears in `uv.lock` only transitively under `httpx`,
  which is in the `dev` dependency group (`pyproject.toml:54`), and `httpx` is named in
  `EXCLUDES` (`packaging/battery-sim.spec:207`). The release workflow also syncs without the dev
  group.
- **The macOS bundle uses a uv-managed CPython 3.12** (`astral-sh/setup-uv@v7`,
  `.github/workflows/release.yml:342`), not the python.org installer — so the
  `Install Certificates.command` that would otherwise wire up `certifi` never runs, and whatever
  OpenSSL cert path the interpreter was built against does not exist on the user's machine.

`unable to get local issuer certificate` for `api.energy-charts.info` — a **public** host with an
ordinary public certificate, where the user's private HA root CA is irrelevant — points to no
usable CA store rather than to a present-but-untrusted chain.

**Confirmed by the user:** `curl` against the same URL succeeds on the failing machine. Since
curl uses the keychain on macOS, the system trusts the host fine and only the bundled Python does
not. That is the distinction the fix is chosen against.

## High-Level Decisions

**`truststore`, not `certifi`** (user's choice, option A of two offered). `truststore` makes
Python's `ssl` delegate to the OS store — keychain on macOS, SChannel on Windows, OpenSSL
elsewhere. It matches what a user who has just fixed their keychain expects, and it covers the
corporate TLS-inspecting-proxy case that a bundled CA list would not. The rejected alternative
was bundling `certifi` and pointing `SSL_CERT_FILE` at it: deterministic and conventional, but it
deliberately ignores the system store and adds a CA list that ages with each release.

**No `certifi` fallback** (option A over option B). A fallback would only help in a failure mode
there is no evidence of — `truststore` failing to initialise on a mainstream desktop OS — and it
would add a second trust store needing its own staleness story. If such a report arrives, it can
be addressed with evidence then.

**Injection must not be able to prevent startup.** `inject_into_ssl()` can raise `ImportError` on
an unexpected interpreter, and the macOS backend raises it if ctypes initialisation fails
(`truststore/_macos.py:209`). Letting that propagate would turn a TLS bug into an app that does
not start — worse than the bug. It is therefore wrapped, and the failure is logged: a machine
that cannot use truststore silently reverts to today's broken behaviour, so the log line is what
makes that diagnosable.

**Pointer to the troubleshooting page on the failure** (user's request). Unlike the HA case, this
is not a failure the user can fix by trusting something — so the text points at the page and asks
for a report rather than prescribing a remedy.

## Rationales and Alternatives

*Why `inject_into_ssl()` rather than passing an explicit context?* The global patch replaces
`ssl.SSLContext`, and `urllib.request` calls `ssl.create_default_context()` at request time, so
the existing `urlopen` call site picks it up unchanged. Passing a `truststore.SSLContext`
explicitly to `urlopen` would work too, but would have to be repeated at every future call site
and would leave any library making its own HTTPS request unprotected.

*Where to inject.* The call must run before any TLS request, in the process that makes it. There
is one process (uvicorn on a background thread, `app/desktop.py:680`), but `app/desktop.py::main`
is only the desktop entry point — `scripts/fetch_spot_prices.py` uses `energy_charts_api`
directly, and the tests import `app.main` without going through `desktop.py`. So the injection
belongs somewhere all three reach, not in `main()` alone.

*PyInstaller risk.* `truststore` selects its backend at runtime via `platform.system()`
(`truststore/_api.py:19-24`), which static analysis cannot follow. All three backend modules
therefore need to be `hiddenimports` in the spec, or the packaged app raises `ModuleNotFoundError`
at first use — a runtime failure on the user's machine, not a build failure in CI. The macOS
backend loads `Security.framework` and `CoreFoundation` by `ctypes.CDLL` from absolute system
paths, which are OS frameworks and need no collection.

## Files Modified

- `app/net_trust.py` — **new.** `install_system_trust()`: idempotent, never raises, prints one
  line to stderr when it cannot apply the patch.
- `pyproject.toml`, `uv.lock` — `truststore>=0.10.4` as a runtime dependency, with a comment on
  why it is not optional.
- `app/main.py` — calls `install_system_trust()` at import (not in `lifespan`; see below); new
  `_load_failed_message()` helper adding the docs pointer to a certificate failure, used by both
  `_load_backend_frame` (WS reify) and the `load_slot` route (HTTP 502).
- `app/desktop.py` — calls `install_system_trust()` in `run()`, immediately after
  `start_session_log()` so its warning is captured in the log.
- `scripts/fetch_spot_prices.py` — calls it too; the script reaches the API without importing
  `app.main`.
- `packaging/battery-sim.spec` — all three `truststore` platform backends added to
  `HIDDENIMPORTS`.
- `docs/en/troubleshooting.md`, `docs/nl/probleemoplossing.md` — new "Loading prices fails with a
  certificate error" section, nav entry, and maintainer notes in the header comments.
- `tests/test_net_trust.py` — **new**, 5 tests: the patch lands, `create_default_context()` picks
  it up, idempotence, a failure is swallowed and reported, a failure is not retried.
- `tests/test_slot_load.py` — 4 tests: the pointer survives urllib's `URLError` wrapping, an
  ordinary failure keeps the plain text, a looping cause chain terminates, and the route returns
  502 with the link.
- `tests/test_packaging_metadata.py` — 3 parametrised tests asserting the spec names each
  backend.
- `THIRD-PARTY-NOTICES.md` — regenerated; one row, `truststore` 0.10.4, MIT.

## Obstacles and Solutions

- Context7 has no index for the Python `truststore` package (it resolves to an unrelated Akamai
  product) — read the API off the installed 0.10.4 source instead.
- `lifespan` looked like the natural place for the injection but is wrong: its docstring records
  that it is for work that WRITES, and a `TestClient(app)` built outside a `with` block never runs
  it. Moved to module import scope, which is reached by every route into `app.main` and writes
  nothing.
- The heredoc appending tests to a file was refused by the worktree isolation guard — used
  Read + Edit instead.

## Current Status

Implemented. Full suite green: **1446 passed, 23 skipped** (the skips are the live-HA suite,
excluded with `--ignore=tests/test_ha_live.py`), up from 1434 by the 12 tests added here.

Verified:

- the two-path diagnosis, the absence of any TLS configuration in the app, `certifi`'s absence
  from the bundle, and the user's `curl`-succeeds result;
- `install_system_trust()` patches `ssl.SSLContext` and is idempotent, and
  `ssl.create_default_context()` returns a truststore context afterwards;
- a real `fetch_prices()` call against the live API succeeds through the patched context on Linux
  — i.e. no regression on the platform that already worked;
- the docs pointer is produced for an `SSLCertVerificationError` wrapped in a `URLError`, which is
  the shape urllib actually raises, and matches the error text the user reported.

Not verified:

- **that this fixes the reported failure.** It needs a packaged macOS build on the affected
  machine. The reasoning is that truststore delegates to the keychain, which `curl` already
  proved trusts the host — but that chain has not been observed end to end.
- the `hiddenimports` requirement, which is reasoned from truststore's runtime `platform.system()`
  dispatch rather than observed in a failing bundle. Being wrong here is harmless; omitting it if
  right would break only the packaged app.
- Windows behaviour generally: `truststore` uses SChannel there, untested by this work.

### Possible follow-ups (not decided)

- Nothing verifies the packaged app can actually complete an HTTPS fetch. `tests/test_packaged.py`
  already drives a built binary and could gain a case for it, which would turn the
  `hiddenimports` assumption above into something observed.
- The backend's error strings on this path are English-only f-strings, outside the catalogs. That
  predates this change and was left alone; translating the path is its own piece of work.
