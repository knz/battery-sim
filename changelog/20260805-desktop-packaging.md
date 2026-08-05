# Desktop packaging — investigation, decisions, and phase plan

> **Status:** Phase 0 (this changelog) complete. Phase 1 (launcher) not started. The plan below was
> presented to the user and approved. No source files changed yet.
>
> Supersedes the direction in `changelog/20260804-hosted-multi-user.md`, which is now an
> "investigated, not chosen" record. Its findings remain valid and are the reason for this file.

## 1. Task specification

### The user's prompts, verbatim

1. *"in the past we've discussed making the app multi-user with the idea to host it in the cloud.
   however operationally this seems expensive. is there a way instead to package it as a desktop
   application? something that would work on mac, linux and windows?"*

### What the follow-up questions settled

Asked how the packaged app should present its UI, and specifically whether the goal was a
self-contained binary requiring no install steps, the user chose:

- a **native window** (pywebview), not the user's default browser;
- Linux shipping as an **AppImage that bundles WebKit2GTK**, so no `apt install` is required;
- **Linux built first**;
- the hosted plan **shelved, with its findings kept**.

Scope of this file: record the reasoning, the decisions, the unverified risks, and the phase plan.
It is not an implementation.

## 2. Why desktop packaging — two separate reasons, both real

The user's stated motivation is operational cost. There is a second, independent reason that comes
out of finding F1 in `changelog/20260804-hosted-multi-user.md`, and the two should not be collapsed
into one.

### 2.1 The architectural reason (from F1)

The Home Assistant fetch runs in the **browser**, not the backend. The long-lived token lives in
`localStorage` and never reaches the server (`app/static/ha_fetch.js`; keys `ha.base_url` and
`ha.token` at `:127-128`). `specs/06-home-assistant-ingestion.md:21` states the premise directly:
the browser on the user's machine can reach the household's HA, and "A hosted backend cannot."

Hosting serves the page over `https:`. An HTTPS page may not open `ws://`, and a plain-HTTP LAN
Home Assistant — the common default — is exactly what a household has. The scheme derivation is in
the code: `app/static/ha_fetch.js:781` reads

```
var proto = location.protocol === "https:" ? "wss:" : "ws:";
```

Verified at that line. So hosting removes a property the app has today, and the fix would have been
user-facing preconditions (expose HA over TLS, or a tunnel) rather than a backend change.

Desktop packaging resolves this by keeping the page on `http://127.0.0.1:<port>`, where `ws://` to
a LAN host is permitted by the browser's mixed-content rules. It restores the property hosting
removed, and requires no change to `ha_fetch.js`.

### 2.2 The operational reason (the user's)

Hosting means TLS termination, per-tenant backup, and a GDPR posture on household consumption data
(F6 of the hosted file) — recurring cost and recurring obligation. Desktop packaging has neither.

## 3. Why the app suits freezing — verified

Checked against the tree on `feat/pending-affordance-backend`:

- **6 runtime dependencies** (`pyproject.toml`): babel, fastapi, jinja2, numpy, python-multipart,
  uvicorn[standard]. Playwright/pytest/httpx are dev-group only.
- **No Node at runtime.** The Tailwind output `app/static/app.css` is committed and tracked.
- **Standard-library `sqlite3`, not SQLAlchemy** (`app/db.py:91`; `app/db.py:5` says as much).
- **No `multiprocessing` anywhere** in `app/`, `tests/`, or `scripts/` — checked by grep. This
  matters because `multiprocessing` under PyInstaller needs `freeze_support()` and is a common
  source of process-spawn loops in frozen apps.
- **Shipped payload is small.** Tracked files excluding `external_data/` and `node_modules/`
  measure ~14MB, of which `app/` is ~11MB (`app/static` 4.6MB, committed spot-price data 4.2MB
  across `app/data/spot_prices` and `app/data/spot_prices_entsoe`). An earlier ~26MB estimate was
  discussed; the difference is most likely site-packages and the interpreter, which the measurement
  above excludes — treat the final bundle size as not yet measured.
- **`BATTERY_SIM_DATA_DIR` already exists** as a complete seam for relocating writable state
  (`app/config.py:48` `data_dir()`, env var defined `:32`). A packaged app can point it at the OS
  per-user data directory without touching any call site.

## 4. The webview constraint — verified, and it drives the Linux decision

pywebview deliberately does **not** bundle a web renderer; it uses the OS one. That is how frozen
pywebview apps stay small, and it is stated in pywebview's own documentation. The consequence
differs per platform:

- **macOS** — WKWebView is part of the OS. Nothing to ship.
- **Windows** — needs the WebView2 runtime. Present by default on Windows 11 and on most Windows 10
  installs, with an MSHTML fallback path available.
- **Linux** — the distribution does **not** ship WebKit2GTK as part of a base install.

### Evidence gathered on the dev machine (Ubuntu 24.04)

`python3 -c "import gi"` succeeds, so PyGObject is present. At the time the investigation was run,
`apt-cache policy gir1.2-webkit2-4.1` reported `Installed: (none)` with
`Candidate: 2.52.3-0ubuntu0.24.04.1` — i.e. available in the archive but absent from the machine.

*Correction on re-check:* running `apt-cache policy gir1.2-webkit2-4.1` again while writing this
file reports `Installed: 2.52.3-0ubuntu0.24.04.1`. The package appears to have been installed
between the two checks. This does not change the decision — the point is that WebKit2GTK is not
present by default on a clean Ubuntu 24.04 and a user would have to install it — but the "not
installed" observation should be read as a snapshot, not as the machine's current state.

Hence the AppImage decision for Linux: the AppImage bundles the GTK/WebKit stack, and is built in
Docker against an older glibc, because glibc is forward- but not backward-compatible (a binary
linked against a newer glibc will not run on an older one).

## 5. High-level decisions

### D1 — Desktop packaging instead of hosted multi-tenant

Rationale: §2. Both the cost argument and the architectural argument point the same way.

### D2 — Native window via pywebview, not the default browser

The user chose the native window for the app-like experience. Recorded honestly: opening the user's
default browser was the **lower-risk** option and was the one recommended during planning — it has
no renderer dependency at all, so Linux would need no bundled WebKit and the Plotly rendering path
would be the same Chromium the tests already use. The native window buys presentation at the cost of
the Linux renderer problem (§4) and the Plotly risk (R5). That trade-off was made deliberately by
the user; it is not a claim that the native window is risk-free.

### D3 — Linux ships as an AppImage with WebKit2GTK bundled

This appears to be the only route to a genuine no-install, self-contained native window on Linux.

Alternatives considered and rejected:

- **Require `sudo apt install gir1.2-webkit2-4.1`** — breaks the "no install steps" requirement,
  and is distro-specific.
- **Use the browser on Linux only, native window elsewhere** — inconsistent behaviour across
  platforms; the app would look like a different product depending on the OS.

### D4 — Linux first

It is the development machine, so the iteration loop is shortest. Under D3 it is also the hardest
of the three targets, so building it first surfaces the bundling problems while the plan is still
cheap to change.

### D5 — The hosted plan is shelved, not deleted

`changelog/20260804-hosted-multi-user.md` keeps all its findings. The owner-scoping work already
landed (commits `6273d23`..`7a92950`) stays untouched: it remains harmless single-principal scoping
today, and it is the seam a future account system would use if the hosted direction is ever
revisited. No revert.

### D6 — PyInstaller `onedir`, not `onefile`

`onefile` unpacks to a temporary directory that is deleted on exit. `app/config.py:36` derives
`_REPO_ROOT` from `Path(__file__).resolve().parent.parent`, and `data_dir()` defaults to
`_REPO_ROOT / "data"`, so under `onefile` the default data directory would land inside the
temp unpack directory and be destroyed when the app closes. That is a data-loss shape, and while
D-plan sets `BATTERY_SIM_DATA_DIR` explicitly to avoid it, `onedir` removes the trap rather than
relying on the override always being set.

## 6. Risks and open questions — UNVERIFIED

Everything in this section is inference or plan, not measurement. It is listed separately from §3
and §4 for that reason.

### R1 — Does Home Assistant's origin check accept `http://127.0.0.1:<port>`? (PARTIALLY VERIFIED)

The whole direction rests on the browser in the packaged window being able to open a WebSocket to
the household's HA. HA restricts which origins may use its WebSocket API (F1.3 of the hosted file).

**Probed 2026-08-05, and it succeeded.** The user ran the fetch from a browser at
`http://127.0.0.1:8000` against their own Home Assistant, and it completed. This was moved ahead of
the packaging phases deliberately, on the reasoning that phases 1-4 would largely be wasted work if
HA rejected the origin.

What that establishes: HA accepts a page origin of `http://127.0.0.1:<port>`. This was the risk
that could have invalidated the direction, and it did not.

What it does **not** establish: the HA reached in the probe was served over **`https://`**, so the
connection exercised was `wss://`, not `ws://`. The plain-HTTP LAN case — an HA on bare `http://`,
which F1.1 of the hosted file identifies as the common default and as the specific configuration
hosting broke — remains untested. Desktop packaging is expected to handle it, because a page on
`http://127.0.0.1` may open `ws://` where an HTTPS page may not, but that expectation is now
supported by the browser's documented mixed-content rule rather than by a measurement here.

Two things still worth checking, neither blocking: whether the origin check still passes on a port
other than 8000 (the packaged launcher defaults to 8137 and falls back to an ephemeral port), and
the plain-HTTP case above, if an HA reachable that way becomes available.

### R2 — The `ws="auto"` trap (UNVERIFIED, but a known PyInstaller failure mode)

uvicorn's default `ws="auto"` selects a WebSocket protocol implementation by probing at runtime.
That probe is invisible to PyInstaller's static import analysis, so the implementation module can
simply be absent from the bundle. The consequence would be that `WS /w/{workspace_id}/data/ingest/ws`
(`app/main.py:1156`) fails **only** in packaged builds, while every test that does not exercise a
real HA fetch continues to pass.

Planned defence: pin `ws="websockets"` explicitly in the launcher, and add a raw WebSocket-upgrade
test that runs against the packaged binary rather than against the source tree. Not yet written.

### R3 — Import-order constraint in the planned `app/desktop.py` (UNVERIFIED)

`app/main.py:238` runs `CONFIG = config.load()` at import time, and the comment there records that
this call *writes* `installation_id` into the data directory on first run. So the launcher must
resolve and set `BATTERY_SIM_DATA_DIR` **before** importing `app.main`.

Get this wrong and it breaks invisibly: on a developer machine the repo-relative `data/` directory
already exists and is writable, so nothing appears wrong. The symptom would appear only in a
packaged build on a clean machine.

### R4 — AppImage plus GObject-introspection typelibs is the known-fragile part (UNVERIFIED)

GI typelibs and their `GI_TYPELIB_PATH` / `LD_LIBRARY_PATH` resolution are the part of the Linux
bundle most likely to need iteration. Flagged as the expected time sink in the AppImage phase; no
estimate offered.

### R5 — Plotly under WebKit2GTK (UNVERIFIED)

The Playwright suite runs against Chromium. WebKit2GTK is a different engine and renders Plotly
differently. Whether the results screen renders correctly in the packaged Linux window is untested.

## 7. macOS and Windows code signing — a deferred decision, not settled

Recorded now because it affects release, not because it is decided.

- **macOS.** An unsigned app will not open by double-click on current macOS versions (Gatekeeper).
  The user's workaround is System Settings → Privacy & Security → "Open Anyway". The Apple Developer
  Program is USD 99/yr and is the route to notarization.
- **Windows.** SmartScreen warns on unsigned executables. Since 2023, OV certificates require a
  hardware token or a cloud HSM, which raises both cost and setup effort.

If the intended audience is Dutch households rather than developers, macOS signing looks closer to
required than optional — a household is unlikely to find the "Open Anyway" path unaided. That is an
argument, not a decision. Options include: sign macOS only; sign both; ship unsigned with printed
instructions; or defer packaging for macOS/Windows entirely until there is demand. Worth deciding
before any public release, and not before.

## 8. Requirements changes

- The multi-user/hosted direction recorded in `changelog/20260804-hosted-multi-user.md` (option B)
  is withdrawn as the active plan. That file's §4 said the plan awaited a user decision; the
  decision went to desktop packaging instead.
- The owner-scoping work is explicitly **not** reverted (D5).
- Within this conversation the UI question moved from open to settled: native window, not browser
  (D2), with Linux as a bundled AppImage (D3).

## 9. Files modified

None. This is Phase 0 and the only file written is this changelog, plus a status edit to
`changelog/20260804-hosted-multi-user.md` recording that its direction was not chosen.

### Planned phases (not started)

1. **Launcher from source** — an `app/desktop.py` that resolves `BATTERY_SIM_DATA_DIR` before
   importing `app.main`, picks a free port, and runs uvicorn with `ws="websockets"`.
2. **pywebview window** — native window pointed at `http://127.0.0.1:<port>`.
3. **PyInstaller `onedir` build on Linux.**
4. **AppImage** bundling the GTK/WebKit stack, built in Docker against an older glibc.
5. **Packaged HA WebSocket verification** — the R1/R2 checks against a real Home Assistant and
   against the built binary.
6. **CI matrix** for macOS and Windows builds.
7. **Deferred:** installers and code signing (§7).

Phases 5 and 6 are ordered that way deliberately: R1 is the assumption the direction rests on, so it
is checked before the matrix work is paid for.

**Amended 2026-08-05.** The R1 origin probe was pulled ahead of phase 1 rather than left at phase 5,
after a review observed that phases 1-4 would largely be wasted if HA rejected the origin. It passed
(see R1), so the remaining phase-5 work is the packaged-binary checks (R2, and the raw WebSocket
upgrade test) rather than the premise itself.

## 10. Current status

- Phase 0 (this changelog): complete.
- R1 origin probe: passed against a real HA over `https://`; the plain-HTTP LAN case is still
  untested (see R1).
- Phase 1 (launcher): **complete and verified.** Created `app/__init__.py` (`__version__`, the
  single source hatchling also reads), `app/__main__.py`, `app/desktop.py`, `tests/test_desktop.py`
  (27 tests). Modified `app/config.py` (`APP_VERSION` from `app.__version__`; new `user_data_dir()`;
  frozen guard on `data_dir()`) and `pyproject.toml` (hatchling `[build-system]`, dynamic version,
  `[project.scripts]`). `uv.lock` was relocked by uv itself — adding `[build-system]` reclassifies
  the project from `virtual` to `editable`; no dependency changed.

  Verified independently of the implementing agent: suite at **1306 passed / 2 skipped** (baseline
  1279/2, so the 27 new tests are the whole delta); `python -m app --no-browser --port N` serves
  HTTP 200; data lands in `~/.local/share/battery-sim` (config.toml, feature_interest.db, workspace
  dir, desktop.lock recording `{"port", "pid"}`) with the repo's `./data` untouched; and a real
  `websockets.connect` to `ws://127.0.0.1:<port>/w/<id>/data/ingest/ws` completed the handshake and
  returned `{"type":"progress","name":"grid_import_t1","rows":2}`.

  One deviation from the plan: uvicorn 0.51.0 deprecates `ws="websockets"` in favour of
  `ws="websockets-sansio"`, so the launcher pins the latter. Same underlying `websockets` package
  and the same property the pin exists for — making the dependency visible to PyInstaller's static
  analysis rather than left to a runtime probe.

  Worth noting for R2: an unknown or path-unsafe workspace id fails the WebSocket **handshake**
  with an HTTP 404 rather than an in-protocol error, by design (documented on the route in
  `app/main.py`). A packaged-build WebSocket test must therefore seed a real workspace first, or a
  correct server looks like a broken one.
- Plan approved by the user.
- Phase 2 (native window): implemented, reviewed, and one defect found and fixed. See §11, and
  §11.7 for the correction.

## 11. Phase 2 — the pywebview window

### 11.1 What was asked

Replace the browser tab with a native pywebview window, still running from source. No PyInstaller
(that is phase 3). Three UI modes on the CLI; a fallback to the browser when pywebview cannot
produce a window; the readiness poll, the single-instance lock, `BIND_HOST`, and the
data-dir-before-import ordering all preserved.

### 11.2 The threading inversion — the one structural change

Phase 1 ran uvicorn on the main thread (`server.run()`) and opened the browser from a short-lived
daemon thread. pywebview's `webview.start()` is a blocking GUI loop that must own the **main**
thread — GTK and Cocoa both require their event loop there — so the two swap places:

- uvicorn now runs on a **background daemon thread** (`_ServerThread`), started via
  `server.run()` inside that thread;
- the main thread does the readiness poll and then calls the UI function;
- when the UI function returns (window closed, or `webbrowser.open` returning immediately in
  `--browser` mode), the main thread sets `uvicorn.Server.should_exit = True` and **waits for the
  server to confirm it has finished**, with a timeout.

The wait is the point. `daemon=True` alone would let the interpreter exit with the server thread
mid-request — no ASGI shutdown event, no chance to close the SQLite connection cleanly. `should_exit`
is uvicorn's cooperative-stop flag: its serve loop checks it each tick and runs the normal shutdown
path. The daemon flag is kept as a backstop for the case where the wait times out
(`_SHUTDOWN_TIMEOUT_S`, 10s) rather than as the primary mechanism.

**The first version of this used `Thread.join()` for that wait, and it was wrong on the Ctrl-C
path.** See §11.7 — the correction is a completion `Event`, not a join.

`--browser` and `--no-browser` differ in *when* the main thread stops waiting:

- `--browser`: `webbrowser.open` returns immediately, so the launcher must NOT shut down on
  return. It blocks on the server thread instead (phase 1's behaviour, just inverted), and the
  server is stopped by Ctrl-C / SIGTERM as before.
- native window: `webview.start()` returns when the last window closes, and that return **is** the
  quit signal, so shutdown follows immediately.
- `--no-browser`: no UI at all; block on the server thread.

That difference is expressed as `_show_ui(url, mode)` returning a bool — whether the UI call was a
"blocking, owns the session" call or a fire-and-forget one — rather than as three separate code
paths in `run`. The mode itself is the `UiMode` enum, one value per CLI flag.

### 11.3 The fallback, and why it is not optional here

`webview.create_window()` succeeds on this machine, but `webview.start()` then raises
`webview.errors.WebViewException("You must have either QT or GTK with Python extensions
installed…")`. **Verified directly** — the dev machine has `gir1.2-webkit2-4.1` installed at the
system level, but the uv-managed virtualenv does not see the system `gi` module, so
`import webview.platforms.gtk` fails with `ModuleNotFoundError: No module named 'gi'` and the QT
path fails too. So on this checkout, today, the native window does not start.

This makes the fallback the path actually exercised in development rather than a defensive
afterthought. It is written to catch **both** the missing-import case and the start-failure case,
around the whole of create+start, and to fall through to `webbrowser.open` with a single line on
stderr naming the reason. `BaseException` is deliberately not caught — a `KeyboardInterrupt`
during the GUI loop is a quit, not a renderer failure.

Note the shape this imposes: a fallback that opened the browser and returned immediately would,
under the rule in §11.2, look like a native window that had just been closed and would shut the
server down instantly. So the fallback also downgrades the answer from blocking to non-blocking —
`_show_ui` returns False on the fallback path, the same as it does for `UiMode.BROWSER`.

### 11.3a The HA token now persists to app-managed disk storage — deliberate

`_show_window` passes `private_mode=False` and `storage_path=<data_dir>/webview`. pywebview
defaults to a private session, which discards localStorage when the window closes;
`app/static/ha_fetch.js` keeps `ha.base_url` and `ha.token` there, so the default would make the
user re-enter their long-lived Home Assistant token on every launch.

Recording the consequence rather than only the fix, because it is a change in kind and not just in
location. `specs/15-data-quality-and-limits.md` §7.5 says the token "never leaves the browser". The
webview **is** the browser here, so the letter of that still holds — the token does not reach the
server, is not sent anywhere, and the architectural property from F1 is untouched. What changes is
the storage medium: previously the token sat in a browser-managed profile that the user's browser
owned and could clear through its own UI; now it sits in a directory this app creates and manages,
under the app's data directory. A user clearing their browser's site data no longer clears it.

Accepted as the better of the two options — the alternative is re-entering the token on every
launch, which is worse for the user and would likely push them to store it somewhere less
protected. Recorded as a decision so it is not later mistaken for an oversight. No permission
hardening on that directory was added; whether it should be is left open rather than settled here.

### 11.4 Files modified

- `app/desktop.py` — docstring rewritten for the new structure; `_show_ui` replaced by
  `_show_window` (pywebview), `_show_browser`, and `_show_ui(url, mode)` dispatching over the
  three modes and reporting back whether it blocked; `_ServerThread` added; `run()` reworked to
  own the shutdown handshake; `--browser` flag added to `main()`.
- `pyproject.toml` — `pywebview>=6.2.1` added to `[project.dependencies]`.
- `uv.lock` — relocked by `uv add`; **14 new package entries**. Only three of them install on
  Linux (`pywebview`, `bottle`, `proxy-tools` — verified against `uv pip list` after `uv sync`).
  The other eleven are platform-markered transitives that the resolver records but does not
  install here: the `pyobjc-*` set for macOS, `pythonnet`/`clr-loader`/`cffi`/`pycparser` for the
  Windows backend, and `qtpy` for pywebview's QT path. They will matter at phases 3 and 6, when
  the macOS and Windows builds are actually made.
- `tests/test_desktop.py` — extended with the phase-2 tests (flag dispatch, the three UI modes,
  both fallback paths, the shutdown handshake, and the §11.7 regression).

### 11.5 Obstacles

- **No GUI backend in the venv** (§11.3). Not worked around: the fallback is the designed response,
  and phase 4's AppImage is where the bundled GTK stack arrives. Worth carrying forward as a phase-3
  input — a PyInstaller build on this machine will inherit the same missing `gi`.
- **No display for tests.** Every pywebview interaction in the suite is mocked via a fake module
  installed into `sys.modules`; no test opens a window.

### 11.6 Current status and what is NOT verified

Implemented. `tests/test_desktop.py` is at **54 passed** (phase 1 left it at 27). The full suite
was run once, before the §11.7 correction, at 1327 passed / 2 skipped against a phase-1 baseline of
1306/2; it has **not** been re-run since, on a standing instruction not to run it (it carries slow
benchmarks). So the whole-suite number above is stale by the §11.7 diff, which touches only
`app/desktop.py` and `tests/test_desktop.py`.

`uv run python -m app --no-browser --port 8199` was started, answered `HTTP 200` on `GET /`, and
released the port when sent SIGTERM. Stated precisely, because an earlier draft of this file
overclaimed it: SIGTERM raises no `KeyboardInterrupt`, so that run exercised the interpreter's
default terminate-on-SIGTERM and **not** the `except KeyboardInterrupt` branch. It shows the
server starts, serves, and does not survive a terminate. It says nothing about the shutdown path
under Ctrl-C — that is covered separately, and by a different check, in §11.7.

Not verified, and it should not be read as working:

- **Whether the window renders at all.** No GUI backend is available in this environment (§11.3),
  so `webview.start()` has never successfully run here. Every native-window assertion in the tests
  is against a mock. The first real evidence will come from a machine or bundle with a working
  WebKit2GTK plus `gi` binding.
- **R5 (Plotly under WebKit2GTK)** is untouched and remains open — it cannot be probed until the
  above works.
- **The window-close shutdown path.** The Ctrl-C path is now verified end to end (§11.7), but the
  window path reaches the same `_stop_or_warn` only after `webview.start()` returns, and
  `webview.start()` has never run here. Unit-tested against a fake; not observed against a real
  window close.

### 11.7 Correction: the interrupted-join defect, found in review

An independent review found a real defect in the first version of §11.2's shutdown, on the
`--browser` / `--no-browser` path specifically. Recorded rather than quietly fixed, because the
mechanism is non-obvious and the wrong version looked correct.

**What was wrong.** `run` waited with `Thread.join()` and, on `KeyboardInterrupt`, called
`stop()`, which set `should_exit` and then did `Thread.join(timeout)` and checked `is_alive()`.
When a signal interrupts a `Thread.join()`, CPython's `_wait_for_tstate_lock` catches the
exception and calls `self._stop()`, permanently marking the **Thread object** stopped while the OS
thread keeps running (bpo-45274). Every later `join(timeout=…)` then returns in about a
millisecond and `is_alive()` answers False. So `stop()` reported a clean shutdown immediately,
at precisely the moment the user pressed Ctrl-C and uvicorn had not yet run the ASGI lifespan
shutdown — and the "did not stop within 10s" warning could never fire, because the false answer
arrives before a true one is possible.

Reproduced directly before fixing: after an interrupted join, `join(timeout=10)` returned in
0.0 ms, `is_alive()` was False, and a completion `Event` set in the target's `finally` was still
unset — the thread had not reached it.

**Why a re-poll would not have worked.** The Thread object's state is already corrupted at the
moment the handler runs, so no amount of waiting and re-checking `is_alive()` recovers the truth.
The answer has to come from somewhere the interrupt cannot touch.

**The fix.** `_ServerThread` now wraps the target in its own `_run`, which sets a
`threading.Event` in a `finally` once `server.run()` has returned. `stop()` returns
`self._finished.wait(timeout)`; `is_alive()` returns `not self._finished.is_set()`. Neither
consults `Thread.is_alive()` nor `Thread.join()` at all — including as a conjunct, which was an
error in an intermediate version of the fix and which the regression test caught: ANDing the
corrupted value in carries the same lie through. `run`'s wait is now `_ServerThread.wait()`
(`Event.wait`), so the Thread object is never poisoned in the first place, and both shutdown
paths go through one `_stop_or_warn` helper so the warning cannot be present on one and missing
on the other. `finally` rather than `else`, so a server that dies on `bind()` also counts as
finished instead of costing a full ten-second wait.

**Verified end to end, out of process.** The real launcher under `UiMode.NONE`, sent a genuine
`SIGINT` while sitting in the wait, with the ASGI app wrapped to observe lifespan messages:
`lifespan.startup` → `lifespan.shutdown` → `server.run()` returned → `stop() -> True after 105ms`
→ `run()` returned 0. Both the shutdown firing and `stop()` having genuinely waited are what the
old code failed to do.

**On the regression test.** The corrupted state is induced in-process the same way CPython induces
it — clear `_tstate_lock`, then call `Thread._stop()` — on a thread that is genuinely still
running, so it exercises the real mechanism rather than a proxy for it. The test asserts the
premise first (the Thread object really does report False and return from `join` instantly) and
only then requires `stop()` to disagree, so it cannot pass vacuously if a future CPython changes
this behaviour — it would fail on the premise instead. Driving it with an actual signal inside
pytest was rejected: it needs the signal to land while the main thread is in `join()`, which means
racing the test runner for the main thread. That check was done out of process instead, above.

## The native window never opened: wrong pywebview arguments, hidden by the fallback

**The symptom.** Running the app printed, on stderr:

    native window unavailable (TypeError: create_window() got an unexpected keyword argument
    'private_mode'); opening in your browser instead

so the WINDOW mode had never actually produced a window on any machine — it had been falling
back to the browser every time, for a reason that had nothing to do with the machine.

**The cause.** `_show_window` passed `private_mode=False` and `storage_path=...` to
`webview.create_window()`. Neither is an argument of that function. Verified two ways rather than
assumed: the pywebview API docs list both under `webview.start`, and `inspect.signature` on the
installed pywebview 6.2.1 confirms it — `create_window` has no such parameters, `start` has
`private_mode: bool = True` and `storage_path: str | None = None`. This is coherent with what
they mean: session persistence is a property of the webview profile for the process, not of an
individual window.

**Why nothing caught it.** Two independent gaps, and the second is the one that matters.

The tests asserted the wrong thing. `tests/test_desktop.py` fakes `webview` into `sys.modules`,
and the fake's `create_window(self, title, url, **kwargs)` accepts any keyword at all. The test
then asserted `kwargs["private_mode"] is False` — i.e. that we made the call we intended, never
that it was a call the real library would accept. 54 tests passed with the bug in place.

The `except Exception` in `_show_ui` then hid it at runtime. That clause was written for the
environment cases — no pywebview, or no WebKit2GTK — and it caught our TypeError too, printed it
in the same "native window unavailable … opening in your browser instead" sentence, and returned
normally. On this machine, which genuinely lacks the `gi` bindings and so genuinely does fall
back, the output was indistinguishable from the expected outcome. That is why manual review of
the running app did not flag it either: the bug was wearing the costume of the expected path.

**The fix.** `create_window()` now gets only the window geometry; `private_mode=False` and
`storage_path=<data_dir>/webview` moved to `webview.start()`. Intent unchanged and confirmed with
the user: localStorage must survive window close, so the Home Assistant token in `ha.base_url` /
`ha.token` is not re-entered every launch, and the storage lives under the app data dir rather
than pywebview's `~/.pywebview` default or anywhere inside the bundle (read-only on macOS, a temp
directory deleted on exit under PyInstaller onefile).

**The narrowed fallback.** `_show_ui` no longer catches `Exception`. It now has two clauses:

- `except TypeError: raise` — explicit, first, and commented with the incident. A TypeError out
  of `_show_window` is our own call being wrong, not a missing package, and nothing the user can
  act on. Written as a re-raising clause rather than simply omitting it from the tuple, because
  the point is to be read: it documents at the call site why this one specific exception is not
  an environment problem.
- `except _webview_exception_types() as exc:` — `ImportError`, `RuntimeError`, and pywebview's
  own `WebViewException` when pywebview is importable. Those are the genuine "this machine cannot
  render a window" cases. `RuntimeError` is kept alongside `WebViewException` because older
  pywebview versions and some backends raise the bare form for the same condition, and
  `WebViewException` does not subclass it.

Everything else propagates, which is the actual change in policy: the fallback is now a list of
known environment failures rather than a catch-all. `_webview_exception_types()` resolves the
class at call time, since pywebview may not be installed at all — the very case the fallback
exists for.

**Tests.** `test_our_pywebview_arguments_are_accepted_by_the_installed_pywebview` records the
args `_show_window` passes and binds them against `inspect.signature(webview.create_window)` and
`inspect.signature(webview.start)` of the real installed package. `Signature.bind` performs the
same check CPython does when calling, so a misplaced keyword fails there — no display, no window,
nothing invoked. Confirmed it is a real regression guard by restoring the old `desktop.py` and
watching it fail with `TypeError: got an unexpected keyword argument 'private_mode'`.
`test_a_bad_call_into_pywebview_is_not_disguised_as_a_missing_renderer` asserts the TypeError
propagates from both call sites, and the existing fallback test gained a `WebViewException` case
next to the `RuntimeError` one. `uv run pytest tests/test_desktop.py -q`: 58 passed (was 54).

**What was verified, and what was not.** Verified: the launcher on port 8216 with a scratch data
dir no longer raises TypeError; the message the user now sees is `native window unavailable
(WebViewException: You must have either QT or GTK with Python extensions installed in order to
use pywebview.); opening in your browser instead`, preceded by pywebview's own diagnostics naming
the missing `gi` and `qtpy` modules — a genuine environment cause, not a coding error in disguise.
The server answered 200 and `<data_dir>/webview/` was created, so `storage_path` did reach
pywebview.

Not verified: **the native window still has not rendered on this machine.** This venv cannot see
the system `gi` bindings, so `webview.start()` raises `WebViewException` and falls back to the
browser as before. What changed is only that the fallback is now for the real reason. That the
window opens, is sized correctly, and that localStorage actually persists across a close/reopen
cycle all remain untested on any machine, and need a box with WebKit2GTK (or macOS/Windows) to
check.

## 12. Phase 3 — the PyInstaller `onedir` build

Implemented 2026-08-05. A `onedir` Linux bundle builds, runs, serves, and passes a packaged
end-to-end suite. **The native window is still not verified and is deferred to phase 4** — see
§12.8, which should be read before this section is taken as evidence that the app "works".

### 12.1 What was built

`packaging/battery-sim.spec` and `packaging/build-linux.sh`, producing `dist/battery-sim/` — a
`onedir` bundle of **89MB** (120MB before the Babel trim of D11; measured by `du -sk`, which the
script's gate reads and integer-divides). Entry point is `app/__main__.py`, so the frozen
binary takes the same `--port` / `--browser` / `--no-browser` flags as `python -m app`.

A spec file rather than a long command line, as asked. It is also the only practical place to put
the reasoning: three of its entries exist to defend against failures that no test outside a
packaged build can observe, and those notes would be lost in a shell invocation.

### 12.2 Decisions

**D7 — `onedir`, confirming D6.** Nothing found during the build argued against it. Two properties
were used in anger: the bundle is a directory that can be listed (§12.5 and §12.6 both depend on
that), and no temp directory is created or destroyed per launch, so the `sys.frozen` guard is a
backstop rather than the only thing standing between the user and data loss.

**D8 — assets collected to their SOURCE-relative paths.** `("app/templates", "app/templates")` and
the three siblings. Templates, static files, locale catalogs and the shipped spot-price CSVs are
all found through `Path(__file__).resolve().parent` from inside `app/`, and under PyInstaller
`app/__init__.py` lands at `<bundle>/_internal/app/`. Matching the relative path exactly means
those lookups resolve with **zero source changes**, which is the outcome that was wanted. Verified
rather than assumed — see §12.5.

**D9 — a separate build virtualenv, not `uv sync --no-dev` in place.** The task allowed either.
`uv sync --no-dev` against the repo's `.venv` would uninstall playwright, pytest and httpx from
the environment the developer is working in, and the next `uv run pytest` would fail until someone
re-synced. `build-linux.sh` therefore creates a throwaway venv (default
`${TMPDIR}/battery-sim-build-venv`, override with `BUILD_VENV=`) and does
`uv pip install -e . pyinstaller` into it — `[project.dependencies]` only, no dependency group.
The dev packages are *also* in the spec's `excludes`, which is deliberate redundancy: the script
makes them absent, the exclude list makes them unbundlable for anyone who runs `pyinstaller`
by hand against the dev venv. Confirmed after the build that `playwright`, `pytest` and `httpx`
are still importable from the repo's `.venv`.

PyInstaller is intentionally **not** added to `pyproject.toml`. It is a build tool, not a
dependency of the application, and putting it in the dev group would place it in every
contributor's environment for no benefit.

**D10 — the size ceiling is a build-script gate, not a comment.** 150MB, in `build-linux.sh`. On
breach it prints the ten largest `_internal/` entries and exits non-zero, because the failure it
anticipates has one overwhelmingly likely cause and naming it saves the reader a `du`. After D11
the bundle is **89MB** against the 150MB ceiling. The largest contributors are now `numpy.libs`
27MB, numpy 14MB, `app/` 9.3MB, `libpython3.12.so` 8.7MB.

**D11 — Babel's CLDR data is trimmed to the languages the app supports.** IMPLEMENTED, on the
user's instruction ("we don't need to keep other locales than those supported in the app"). An
earlier draft of this section deferred it and, in doing so, **overstated the risk** — the
correction is worth recording because the wrong version would have discouraged a safe change.

That draft said trimming risked "a locale needed by `negotiate_locale` for some user's
`Accept-Language` header going missing". That cannot happen as the code stands. `app/i18n.py:70`
defines `SUPPORTED = ("en", "nl")`, and `resolve_locale` (`:113-126`) returns a member of
`SUPPORTED` or `DEFAULT_LOCALE` and nothing else: `negotiate_locale` given `de,fr` returns None
and the app falls back to English. So an arbitrary header locale never reaches `Locale.parse`, and
the set of locales the app can ask Babel about is exactly `SUPPORTED`. The real risk is narrower
and entirely internal — a keep-set that fails to cover the app's *own* languages — and that is
what the guards below are for.

Measured: **1083 `.dat` files → 3** (`en`, `nl`, `root`); babel **32MB → 876KB**; the bundle
**120MB → 89MB**. A 26% reduction, and Babel goes from the single largest entry to a rounding
error.

Three things about how it is implemented:

- **The keep-set is derived from `app/i18n.py::SUPPORTED`, not hardcoded**
  (`packaging/battery_sim_babel_locales.py`). A literal `{"en", "nl", "root"}` would mean that
  adding a language later ships a bundle that cannot format it — and the symptom is a wrong number
  format or a 500, not a build error. The parent chain is walked the same way
  `babel.localedata.load` walks it (consult `parent_exceptions`, else strip the last `_` segment,
  else `root`), so a future `pt_BR` pulls in `pt` and an `en_GB` pulls in `en_001` unaided. Checked
  against both of those hypothetical entries.
- **`root` is always kept**, because every locale inherits from it, and **`global.dat` is
  untouched** — it lives outside `locale-data/` and carries the territory and `parent_exceptions`
  tables `Locale.parse` needs for any locale at all.
- **It had to be a hook override, not a spec-side filter.** This was the one real obstacle. The
  first attempt filtered the spec's own `datas` and the bundle came back byte-for-byte unchanged
  at 120MB, because PyInstaller's bundled `hook-babel.py` does an unconditional
  `collect_data_files('babel')` and a hook's datas are merged independently of the spec's list. The
  fix is `packaging/hooks/hook-babel.py`, which shadows the stock hook via
  `hookspath=[packaging/hooks]`. Its `hiddenimports` are copied verbatim from the stock hook and
  must stay: unpickling `root.dat` needs those four modules.

Guards, because a too-aggressive keep-set is a runtime-only failure: the spec aborts the build if
the keep-set comes out with fewer than two entries, and `build-linux.sh` asserts after the build
that a `.dat` exists for every language it reads out of `app/i18n.py` (plus `root`), and that
`global.dat` survived. `tests/test_packaged.py::test_babel_locale_data_is_bundled` is the
end-to-end backstop — see §12.11.

### 12.3 The hidden imports, and which of them were actually necessary

The task's list was checked against the installed uvicorn 0.51.0 rather than trusted. All four
named entries are real and all are resolved by **string**, in `uvicorn/config.py`:

```
WS_PROTOCOLS   {'websockets-sansio': 'uvicorn.protocols.websockets.websockets_sansio_impl:…', …}
HTTP_PROTOCOLS {'h11': 'uvicorn.protocols.http.h11_impl:H11Protocol', …}
LIFESPAN       {'auto': 'uvicorn.lifespan.on:LifespanOn', …}
(loop map)     {'asyncio': 'uvicorn.loops.asyncio:asyncio_loop_factory', …}
```

`import_from_string` calls `importlib.import_module` on the left half at Config time. Nothing in
the bytecode references these modules, so PyInstaller's static analysis genuinely cannot see them.
The task's warning about `websockets-sansio` versus `websockets` is correct — the launcher pins
the sansio name (phase 1, §10) and `websockets_sansio_impl` is the module that matches it.

`app.main` is the fifth entry and is needed for a different reason: `_load_asgi_app` imports it
**inside a function**, deliberately (the data directory must be resolved first), which also keeps
it out of the module-level import graph.

**`app/sources/registry.py` needed nothing.** The task flagged it as a possible string-lookup
site. It was read, and its `_BY_KEY` map holds already-**instantiated** objects built from three
ordinary top-level imports (`HomeAssistantSource`, `EnergyChartsSource`, `EntsoeSource`); `get_source`
looks up an instance, not a module. A grep for `import_module` / `__import__` / `importlib` across
all of `app/` returns exactly one hit, and it is a comment in `app/__init__.py`. So there is no
dynamic module resolution anywhere in the application — the string-lookup problem is entirely
uvicorn's.

PyInstaller's bundled `hook-uvicorn.py`, `hook-websockets.py` and `hook-babel.py` all ran. It is
therefore **not established** that every one of the five entries is load-bearing today; the hooks
may already cover some. They are kept because the hooks are third-party and versioned
independently, and because the cost is nil. What *is* established is that at least the WebSocket
entry matters — §12.6 removed it and the build broke.

### 12.4 Excludes

As specified: playwright, pytest, `_pytest`, httpx, watchfiles, uvloop, httptools, tkinter,
`numpy.testing`, `numpy.f2py`. `uvloop` and `httptools` are correctness as much as size — they are
what `ws`/`http`/`loop` would have probed for under `"auto"`, and the launcher pins the pure-Python
alternatives, so bundling them would ship C extensions nothing loads. PyInstaller's warning file
confirms both were excluded rather than merely absent.

`external_data/` (~429MB), `node_modules/` (~48MB), `tests/`, `specs/` and `changelog/` are not
packages and cannot be reached by the spec as written; `test_the_bundle_carries_no_development_directories`
asserts it by name and the size gate catches it by weight.

### 12.5 What was verified, and how

All against the built binary, `dist/battery-sim/battery-sim`, on port 8220, `--no-browser`.

- **HTTP 200 on `GET /`.** The workspace list renders.
- **The data directory lands per-user, not in the bundle.** This is the check the phase exists
  for, and it was run the only way that actually tests the guard: `BATTERY_SIM_DATA_DIR`
  **unset** (so `resolve_data_dir` cannot pre-empt the decision) and `XDG_DATA_HOME` pointed at a
  scratch directory. `config.toml`, `feature_interest.db`, `desktop.lock` and the workspace
  directory all appeared under `<scratch>/battery-sim/`. Separately confirmed that **no file
  under `dist/` was modified after the launch** (compared against the mtime of the freshly
  written `config.toml`), and that the repo's own `./data` was untouched. `desktop.lock` held
  `{"port": 8220, "pid": 1383288}`.
- **The WebSocket route works.** A raw `websockets.connect` to
  `ws://127.0.0.1:8220/w/<id>/data/ingest/ws`, against a workspace seeded first — the documented
  404-on-handshake trap from §10 was heeded. The handshake completed and a header/series/rows
  exchange returned `{"type":"progress","name":"grid_import_t1","rows":2}`, byte-identical to what
  the phase-1 source run produced. So the pinned `websockets-sansio` implementation is present and
  carrying frames in both directions, not merely importable.
- **Templates, static, locales and `app/data`.** `/static/app.css` 200 (165KB), `/static/ha_fetch.js`
  200 (60KB), the configure-data screen 200 (39KB) and the results screen 200 (61KB) — the last of
  which prices its counterfactual off the shipped spot-price CSVs, so it exercises `app/data`.
  Both `.mo` catalogs are in the bundle and genuinely translate: the same page renders "Nieuwe
  analyse" under `Accept-Language: nl` and "New analysis" under `en`.
- **Babel's CLDR data is loaded inside the frozen process.** Asserted on the number *format*
  rather than on any translated word, because that is what isolates Babel from the gettext
  catalogs: the results screen renders `34,2 %` / `2.410 kWh` in Dutch and `34.2 %` / `2,410 kWh`
  in English. Only Babel's locale data can produce the Dutch grouping, and it is data rather than
  an importable module, so nothing in the import graph would have pulled it in.

### 12.6 The sabotage check — the tests are not vacuous

A green packaged suite is worth little if it would also be green on a broken bundle, so a
deliberately broken one was built: `websockets_sansio_impl` removed from `hiddenimports`, the
babel `collect_data_files` removed, and `websockets` added to `excludes`. `tests/test_packaged.py`
went from 8 passed to **1 passed / 7 errors** against it. The bundle and its build directory were
deleted afterwards and the spec restored from a backup; the good bundle was then rebuilt from the
restored spec and re-tested at 8 passed.

**This produced the phase's one genuinely surprising finding, and it is good news for R2.** The
broken bundle did not lose one route quietly — it failed to **start**, with
`ModuleNotFoundError: No module named 'websockets'` raised from `uvicorn/config.py:487`
`import_from_string` during `Server.serve`, followed by "the server did not become ready in time".

R2 (§6) predicted the opposite: that a missing WebSocket implementation would break only
`WS /w/{id}/data/ingest/ws` while everything else stayed green. That prediction was written for
`ws="auto"`, which *probes* and silently degrades to "no WebSocket support". Because phase 1
pinned the protocol instead, uvicorn resolves the name eagerly and a missing module is a hard,
immediate, loud failure. So the phase-1 pin turned out to be a stronger defence than it was
credited with — it converts R2's silent trap into a crash on launch that no one could ship past.

Stated with its limit: this was observed for the WebSocket implementation specifically, in
uvicorn 0.51.0. The same eager-resolution reasoning applies to the `http` and `loop` pins, but
those were not separately sabotaged. `tests/test_packaged.py::test_the_websocket_route_works`
remains worth keeping regardless — a crash-on-launch is only self-evident to someone who launches
the packaged build, which is exactly what CI would otherwise not do.

### 12.7 Files added and modified

Added:

- `packaging/battery-sim.spec` — the PyInstaller spec. `datas`, `hiddenimports`, `excludes`, and
  `EXE`/`COLLECT` for onedir. Carries the reasoning for the three entries whose absence is a
  runtime-only failure.
- `packaging/build-linux.sh` — build script (executable). Isolated venv, `--no-dev` install,
  PyInstaller run, the 150MB gate, and a post-build assertion that the four asset directories and
  `babel/locale-data` are present. `--keep-venv` reuses the build environment across runs.
- `tests/test_packaged.py` — 9 tests, skipped unless `BATTERY_SIM_PACKAGED_BINARY` names the built
  executable. Covers serving, the data-dir location, the lock file, static, templates+`app/data`,
  the Dutch message catalog, Babel's CLDR data, the WebSocket exchange, and the absence of dev
  directories from the bundle.
- `packaging/battery_sim_babel_locales.py` — the CLDR keep-set, derived from
  `app/i18n.py::SUPPORTED` (D11). Its own module because a PyInstaller spec is `exec`'d and a hook
  is imported by PyInstaller's loader, so neither can import from the other.
- `packaging/hooks/hook-babel.py` — shadows PyInstaller's bundled babel hook and applies the trim.
  The only place the trim can bind; see D11.

Modified:

- `.gitignore` — added `/dist/` and `/build/`, PyInstaller's output and work directories. They
  were untracked and unignored before, so a `git add -A` would have staged the whole bundle.
- `changelog/20260805-desktop-packaging.md` — this section.

No application source was changed. That was the point of D8, and it held: `app/`, `pyproject.toml`
and `uv.lock` are all untouched by this phase.

On the test-file location: `tests/test_packaged.py` rather than `packaging/test_packaged.py`, so
it is collected by the same `pytest` invocation as everything else and skips itself rather than
needing a separate command to be remembered.

### 12.8 What is NOT verified — read this before trusting §12.5

**The native window did not run, and a green phase 3 is not evidence that it works.** This
machine's uv venv cannot see the system `gi` (PyGObject) bindings, so `webview.start()` raises
`WebViewException` and the launcher falls back to the browser — exactly as §11.3 and the phase-2
correction describe. The frozen build **inherits this**: PyInstaller collected `webview` and its
`webview.platforms.gtk` module, but the GTK/WebKit stack those need is not in the bundle and is
not visible from it. Every check in §12.5 was performed with `--no-browser`, i.e. driving the
server over HTTP, so what was exercised is the **server and the browser path**, not the window.

That is expected rather than a defect: bundling the GTK/WebKit stack is phase 4's job (D3). But it
means R5 (Plotly under WebKit2GTK) is still untouched, the window-close shutdown path is still
only unit-tested against a mock, and nothing here says the app looks right in a native window.

Also not verified:

- **Any platform but Linux.** No macOS or Windows build was attempted; the spec is written to be
  portable but that is an intention, not a measurement.
- **Any machine but this one.** The bundle links against this box's glibc. Running it on an older
  distribution is precisely what the phase-4 Docker build exists to fix, and is untested.
- **Startup time.** Not measured. The bundle takes noticeably longer than a source run to answer
  its first request (the readiness poll's 20s budget was ample, but no number was taken).
- **A full simulation run** in the packaged build. The results screen renders, which needs numpy
  and the shipped prices, but no long run was driven end to end.
- **Whether all five hidden imports are individually required** — see §12.3.

### 12.9 Test numbers

Final figures, after the §12.11 review fixes and the D11 trim:

- `uv run pytest tests/test_desktop.py -q` → **58 passed** in 12.33s. Unchanged from phase 2, as
  expected: this phase touched no application source.
- `uv run pytest tests/test_packaged.py -q` with the gate unset → **9 skipped** in 0.04s.
- `BATTERY_SIM_PACKAGED_BINARY=dist/battery-sim/battery-sim uv run pytest tests/test_packaged.py -q`
  → **9 passed** in 1.36s. (8 before §12.11 split the locale test in two.)
- Against the deliberately broken bundle of §12.6 → **1 passed / 7 errors**.
- Against each of the three locale sabotages of §12.11 → 1, 2 and 2 failures respectively.

The full suite was **not** run, on the standing instruction that it carries slow benchmarks. Its
last recorded figure (§11.6) is stale and this phase does not update it; no application source
changed, so no change to it is expected, but that is an inference and not a measurement.

### 12.10 Status and what is open

Phase 3 is complete for Linux: the bundle builds, is gated on size, runs, serves, keeps its data
in the right place, and its WebSocket route works. Changes are left unstaged and uncommitted.

Open, in no particular order and with no recommendation attached:

- **Phase 4 (AppImage + bundled GTK/WebKit)** is the direct continuation and the only route to
  testing the native window at all (D3, R4, R5).
- **Wiring the packaged suite into CI**, which is where a crash-on-launch would otherwise go
  unnoticed until a release. More valuable after §12.11 than before it: the suite now catches a
  failure mode that a green source-tree run cannot.
- **Trimming `app/static`** (4.6MB) or the shipped spot-price CSVs (4.1MB) are the next size items
  after D11, and both are far smaller wins than the Babel trim was. Neither looks worth the risk
  today; noted only so the next person does not have to re-measure.
- **A `--onefile` variant** is deliberately not offered; D6/D7 explain why.

### 12.11 Independent review: three findings, and the hole in the packaged suite

An independent review of the phase-3 work re-tested the suite's non-vacuity by building its own
sabotaged bundles. It confirmed most of §12.5 and §12.6 as written — the size gate genuinely fails
the build, the excludes genuinely exclude, `app/sources/registry.py` genuinely needs no hidden
import, and `build-linux.sh` cannot damage the developer's `.venv` on any path. It also found one
real gap. Recorded here rather than quietly patched, because the gap is instructive: the test that
missed it *looked* like it covered the case, and its own docstring said so.

**Finding 1 — the packaged suite passed on a bundle with the entire Dutch catalog missing.**

The reviewer deleted `_internal/app/locales/nl/` from a built bundle. The suite stayed at 8 passed.
That bundle serves "New analysis" to an `Accept-Language: nl` request where the good bundle serves
"Nieuwe analyse" — i.e. a Dutch-only product shipping fully untranslated, with a green suite.

The cause is that the single test covering locales asserted only on NUMBER SEPARATORS, and those
come from Babel's CLDR data, not from the `.mo` catalogs. Its docstring claimed it covered "two
separate bundle entries"; it covered one. `check_assets` did not backstop it either — `_ASSET_DIRS`
asks whether `locales/` is a non-empty directory, which stays true when only the `nl/` subtree is
removed.

Two lessons worth carrying forward. First, one assertion cannot cover two independent bundle
entries just because both happen to be about "locales" — the failure modes are different
(untranslated text vs wrong number format) and need separate checks. Second, a docstring asserting
coverage is not coverage; this one was wrong for as long as it existed and nothing contradicted it.

**The fix.** The test is split in two, one per bundle entry:

- `test_the_dutch_message_catalog_is_bundled` asserts on actually-translated text — three
  msgid/msgstr pairs verified against `app/locales/nl/LC_MESSAGES/messages.mo` and rendered as
  section headings. Two-sided: the Dutch heading must be present AND the English source string
  absent, so a catalog that is bundled but not consulted also fails.
- `test_babel_locale_data_is_bundled` keeps the separator assertion and gains a month-name one
  (below).

One wrinkle, found while writing it: the first version compared against the raw HTML and failed on
the good bundle, because the results screen carries an inline `<script>` whose English *comment*
contains the word "Battery". The assertions now run against the page's `<h1>`..`<h6>` text, which
is markup the translation actually owns. Worth recording as a caution — the naive check produces a
false positive that reads exactly like a translation failure.

**Finding 2 — §12.2 overstated the risk of trimming Babel, in the cautious direction.** Corrected
in D11, which now states the accurate reason trimming is safe (`resolve_locale` returns only a
member of `SUPPORTED` or `DEFAULT_LOCALE`, so an arbitrary `Accept-Language` never reaches
`Locale.parse`) and carries the measured figures. On the user's instruction the trim was then
**implemented** rather than left deferred. A miscalibration in the cautious direction is still a
miscalibration: it argued against a change that was both safe and worth 31MB.

**Finding 3 — a stale path in `packaging/battery-sim.spec`**, referring to
`packaging/test_packaged.py` when the file is at `tests/test_packaged.py`. Fixed, with the reason
for the location noted inline.

**Re-verified by sabotage, after the fixes.** Three bundles, each breaking one thing, run against
the corrected suite. The real `dist/` was never modified — each sabotage was a copy, deleted
afterwards.

| sabotage | result | which test failed |
|---|---|---|
| `_internal/app/locales/nl/` deleted | 1 failed / 8 passed | the catalog test only — Babel's test correctly still passes, since number formatting is unaffected |
| `_internal/babel/locale-data/nl.dat` deleted | 2 failed / 7 passed | the Babel test; the nl page 500s with `UnknownLocaleError: unknown locale 'nl'` |
| `_internal/babel/locale-data/en.dat` deleted | 2 failed / 7 passed | the Babel test; the en page 500s with `UnknownLocaleError: unknown locale 'en'` |

The first row is the hole from Finding 1, now closed. That the catalog sabotage fails *only* the
catalog test, and the CLDR sabotage *only* the Babel test (plus the page-render test that shares
the route), is the point: the two failure modes are now distinguished rather than conflated.

**On the `root` fallback, and why the month-name assertion exists.** `root` and `en` format
numbers identically, so a trim that dropped `en.dat` while keeping `root` could in principle
satisfy the separator check while serving `M01 M02 M03` where a reader expects `Jan Feb Mar`. In
practice it does not — `Locale.parse("en")` raises rather than falling back, as the table shows —
but the assertion is cheap and the reasoning was not obvious enough to leave unguarded. Verified
positively on the trimmed bundle: English renders `Jan Feb Mar …` and Dutch `jan feb mrt mei okt`,
so both locales load their real CLDR data and neither has silently degraded to `root`.

**Application source: still untouched.** The reviewer raised whether `check_assets` should verify
the expected locale SUBDIRECTORIES rather than just a non-empty `locales/`. Judged not worth it
here, and the judgement is recorded rather than the change made. `check_assets` is a startup check
whose stated purpose is to name a missing bundle DIRECTORY early; teaching it the app's language
list would put a second, duplicate source of truth beside `SUPPORTED`, and it would fire on a
developer mid-translation who has not yet compiled a catalog. The packaged test now covers the case
directly, at build time, where a fix is free — which is the better place for it. So phase 3 ends
where it started: `app/`, `pyproject.toml` and `uv.lock` are untouched, and every change is in
`packaging/`, `tests/`, `.gitignore` and this file.

## 13. Phase 4 — the Linux AppImage with WebKit2GTK bundled

Implemented 2026-08-05. **Both risks the phase existed to separate came back positive, with
screenshots.** Risk A (does the window open at all — the typelib bundling) and Risk B (does Plotly
render under WebKit2GTK rather than the Chromium the suite uses) are reported separately in §13.6
and §13.7, because a blank window would have been undiagnosable if they had been checked together.

The AppImage is **105MB** (109,738,488 bytes). It is built against this machine's glibc 2.39 and is
therefore **not portable to older distributions** — see §13.3, which is a deliberate trade rather
than an omission.

### 13.1 What was built

- `packaging/build-appimage.sh` — lays out an AppDir from the phase-3 onedir bundle plus the GI /
  GTK3 / WebKit2GTK stack collected from the host, writes AppRun and the desktop entry, and runs
  `appimagetool`. Output `dist/Home-Battery-Simulator-x86_64.AppImage`.
- `tests/test_appimage.py` — 7 tests, gated on `BATTERY_SIM_APPIMAGE`. §13.9.
- One line added to `packaging/battery-sim.spec`: `optparse` as a hidden import (§13.5).

No application source changed. `app/`, `pyproject.toml` and `uv.lock` are untouched by this phase,
as they were by phase 3.

### 13.2 Environment as found

- Docker: **available**. Not used — see §13.3.
- `Xvfb`, `openbox`, `xdotool`: **not installed**; installed via apt during the phase (the machine
  has passwordless sudo). Without a virtual display none of the verification below is possible.
- `appimagetool`: fetched as the continuous build; the script fetches it into `dist/` if absent.
- glibc 2.39 (Ubuntu 24.04). System PyGObject 3.48.2 at `/usr/lib/python3/dist-packages/gi`.
- **The venv's Python is 3.12.3, the same minor version as `/usr/bin/python3`.** That is what makes
  copying the system `gi` into the bundle viable at all: the compiled `_gi` extension is built for
  a specific CPython ABI. The build script now asserts the two agree and fails if they do not,
  because a mismatch is an undefined-symbol error at the user's launch rather than at build time.

### 13.3 Decision D12 — build natively and accept non-portability, rather than stall on Docker

Docker **is** available here, so the plan's container build was possible. It was not done, and the
reasoning should be read as a trade rather than as a shortcut:

The phase's stated purpose is to find out whether the native window works at all — R4 (typelibs)
and R5 (Plotly), both open since phase 2 and both untestable without a bundled GTK stack. A
container build against an older glibc would have added a second, independent variable (an
older Ubuntu's WebKit2GTK, a different typelib set, a different PyGObject) to a phase whose whole
value is isolating which of two things broke. Building natively kept the variable count at one.

**The consequence, stated plainly: the AppImage produced here runs on glibc 2.39 or newer and will
not run on Debian 12 or any older distribution.** glibc is forward- but not backward-compatible.
Portability is therefore **unverified and remains a follow-up**, and the container build is the
obvious next step now that the renderer questions are answered. A working-but-not-portable AppImage
was judged more valuable than no AppImage, because it is the only way to test the window at all —
but it is not a shippable artifact for arbitrary users yet, and should not be described as one.

### 13.4 The three obstacles, and what each of them actually was

All three were found by measurement. Each produced the SAME user-visible symptom — pywebview
reporting "GTK cannot be loaded" and the launcher quietly opening a browser — which is why they had
to be peeled apart one at a time rather than guessed at.

**Obstacle 1 — `PYTHONPATH` does not reach a frozen `sys.path`.** The first AppImage put PyGObject
at `usr/lib/python-gi` and exported `PYTHONPATH` from AppRun. It had no effect whatsoever:
PyInstaller's bootstrap REPLACES `sys.path` with the bundle's own entries, so `PYTHONPATH` is not
consulted for package resolution in a frozen process. The run failed with `ModuleNotFoundError: No
module named 'gi'`, served every HTTP route correctly, and fell back to the browser.

*The fix* is to copy the `gi` package into the bundle's own `_internal/`, which IS on the frozen
`sys.path`. No loader tricks, no runtime hook. `tests/test_appimage.py` asserts the LOCATION rather
than mere presence, because that distinction is the entire bug.

**Obstacle 2 — `optparse` was not in the bundle.** With `gi` importable, the next failure was
`ModuleNotFoundError: No module named 'optparse'`, from `gi/overrides/GLib.py`'s
`from gi import _option`. Nothing in the application imports `optparse`, so PyInstaller correctly
did not collect it. Added as a hidden import in `packaging/battery-sim.spec`, with the incident
recorded inline; the cost to a non-AppImage bundle is one small stdlib module.

**Obstacle 3 — WebKit's helper-process path is compiled in, and copying the helpers does not
help.** This is the one that would have shipped silently, and it was found only because of a check
that was almost not run.

WebKit2GTK runs its renderer, network and GPU work in separate processes and looks for those
executables at an absolute path baked into `libwebkit2gtk` at build time —
`/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1` here. There is no environment variable to redirect it:
the library's string table carries `WEBKIT_INJECTED_BUNDLE_PATH` but nothing for the exec path
(checked directly against the binary). So an AppImage that copies the helpers into its AppDir does
not use them — **it uses the host's**, and works only on a machine that already has WebKit2GTK
installed, which is precisely the opposite of the point.

On this machine, which does have WebKit2GTK, everything looked correct. The problem surfaced only
when the host's `girepository-1.0`, `webkit2gtk-4.1` and `dist-packages` were masked with tmpfs
mounts inside a `unshare -m` namespace, at which point the process died with:

    ERROR: Unable to spawn a new child process: Failed to spawn child process
    "/usr/lib/x86_64-linux-gnu/WebKitNetworkProcess" (No such file or directory)

*The fix* rewrites the two occurrences of that path inside the COPIED library. Both are
NUL-terminated C strings in `.rodata`, so a shorter replacement NUL-padded to the original length
needs no relocation and no `patchelf`. The replacement is `/tmp/.battery-sim-webkit`, which AppRun
creates as a symlink to the live mount — the indirection is necessary because the AppImage mount
point is randomised per launch (`/tmp/.mount_XXXXXX`) while the patched string must be a
compile-time constant.

**A known limitation of that fix, recorded rather than hidden:** the symlink name is shared across
users on one machine. The patched string cannot carry the UID, since WebKit uses it as a literal
path with no expansion. AppRun therefore replaces the link only when it does not exist or is one
this user owns; a second user on the same machine falls back to the browser rather than being
pointed at the first user's mount. Acceptable for a single-user desktop app. A path under
`$XDG_RUNTIME_DIR` would be per-user by construction and is the clean fix, but it is not knowable
at build time either and a typical `/run/user/<uid>/…` exceeds the 40-byte budget. Left open.

### 13.5 The environment AppRun sets, and why each entry is there

Each corresponds to a lookup that would otherwise resolve against the host and find the wrong
version or nothing at all. Investigated against the binaries rather than guessed:

| variable | what it resolves | symptom when missing |
|---|---|---|
| `GI_TYPELIB_PATH` | the `.typelib` blobs `gi.require_version` reads | `ValueError: Namespace WebKit2 not available` at window creation |
| `LD_LIBRARY_PATH` | the bundled GTK/WebKit `.so` set | the host's versions, or none |
| `GDK_PIXBUF_MODULE_FILE` | `loaders.cache`, for the dlopen()ed image loaders | icons and images silently fail to decode |
| `GIO_MODULE_DIR` | GIO extension modules (TLS via gnutls, proxy) | `https://` inside the webview fails |
| `GSETTINGS_SCHEMA_DIR` | the compiled schemas | `abort()`, not an exception |
| `XDG_DATA_DIRS` | icon theme lookup | missing icons |
| `WEBKIT_DISABLE_COMPOSITING_MODE` | forces the non-GL paint path | see below |

`PYTHONPATH` is deliberately **absent** — obstacle 1. `WEBKIT_DISABLE_COMPOSITING_MODE=1` is set
because the bundled WebKit renders through the HOST's GL/EGL stack, which may be a different Mesa
than it was built against; the compositing path is what trips on that mismatch and it is not needed
for a document UI. Under Xvfb the run logs `libEGL warning: DRI3 error` and renders correctly
regardless, so this is a precaution rather than something measured to be required.

**The typelibs are copied wholesale rather than hand-picked.** The whole directory is ~1MB and the
dependency graph between them (WebKit2 → Soup, JavaScriptCore; Gtk → Gdk → GdkPixbuf → GObject →
GLib) is not worth encoding when the cost is less than one PNG.

### 13.6 RISK A — the window opens. VERIFIED, with screenshots

`webview.start()` had never successfully run on this machine before this phase (§11.3, §12.8).
It now does, from the AppImage, with no packages installed.

Method: `Xvfb :N` plus `openbox`, the AppImage copied to a directory **outside the repository**,
`BATTERY_SIM_DATA_DIR` unset, `XDG_DATA_HOME` pointed at a scratch directory, screenshots by
`import -window root`.

- The window is present in the X tree as `"Home Battery Simulator" 1280x860` — the size
  `_WINDOW_SIZE` specifies, so the geometry passed through pywebview correctly.
- The page renders the real UI: the workspace list, the Tailwind stylesheet, the EN/NL switch, the
  "+ New analysis" button. Screenshot: `40-final-riskA.png`.
- **Self-containment proven, not assumed.** Repeated inside `unshare -m` with the host's
  `girepository-1.0`, `webkit2gtk-4.1` and `python3/dist-packages` masked by tmpfs. The window
  still opens and still renders. Screenshot: `30-isolated-window.png`. This is the check that
  matters, and it is what exposed obstacle 3 — without it the phase would have concluded "works"
  on a bundle that was quietly using the host's WebKit.

**A window manager is required for any of this to be observable.** Bare `Xvfb` with no WM produced
a black root window and no mapped GTK window; with `openbox` running the window maps normally. That
is a property of the test harness, not of the app.

**A session bus is also required, and its absence is silent.** Without one — or with a stale
inherited `DBUS_SESSION_BUS_ADDRESS` — `gtk.Application.run()` can return WITHOUT ever firing
`activate`, and pywebview then returns from `webview.start()` with no window, no error and no
traceback. Measured: 3/3 windows with `dbus-run-session`, 1/2 without, on otherwise identical runs.
This was the single most confusing failure encountered and cost the most time, because it looks
exactly like success. AppRun starts `dbus-run-session` when no bus is present; a normal desktop
session keeps its own.

### 13.7 RISK B — Plotly renders under WebKit2GTK. VERIFIED, with a screenshot

R5 has been open since phase 2 and is now closed **positively**.

Driven against a workspace seeded through the app's own `POST /workspaces` route, whose `/results`
screen carries 12 months of `monthly-data` JSON priced off the shipped spot-price CSVs, and which
calls `Plotly.newPlot('monthly-chart', …)`.

The webview was pointed at that URL using the AppImage's **own extracted** GI/GTK/WebKit stack, so
what rendered is the bundled engine and not the host's. Evidence is both programmatic and visual:

    JSPROBE: {"plotly":"object","svg":3,"traces":1,"bars":12}

`Plotly` is a live object, three SVG elements were produced, one trace, and twelve bar paths — one
per month, matching the data exactly. The screenshot `41-final-riskB-plotly.png` shows the chart
drawn correctly: 12 bars, y-axis ticks at 0/50/100/150, the `kWh` axis label, month labels
Aug–Jul, the purple fill from the template, plus the benchmark bar rows and the caveat panel above
and below it. No JavaScript errors were logged.

So the concern behind D2 — that a different engine from the test suite's Chromium would render the
results screen badly — did not materialise for this chart. **Stated with its limits:** one page and
one chart type (a bar chart) were checked. The `SoC + price` and `Energy flows` tabs, and any chart
that appears only after a full simulation run, were not.

### 13.8 Also verified

- **Runs from outside the repository, writes state to the per-user location.** The AppImage was
  copied to a scratch directory, run with `BATTERY_SIM_DATA_DIR` unset and `XDG_DATA_HOME`
  redirected. `config.toml`, `feature_interest.db`, `desktop.lock`, `local/` and `webview/` all
  appeared under `<scratch>/battery-sim/`. Nothing was written inside the mount, which is
  read-only in any case.
- **The WebSocket route works.** `tests/test_packaged.py` — including
  `test_the_websocket_route_works`, a raw `ws://` upgrade plus an in-protocol exchange against a
  workspace **seeded first**, heeding the documented 404-on-handshake trap — passes 9/9 against the
  AppImage's extracted binary as well as against the plain onedir bundle.
- **Window close shuts the server down cleanly.** This closes a gap open since phase 2, where the
  path had only ever been mock-tested (§11.6). Driven under Xvfb with
  `xdotool windowclose`: the process exited within ~1s and the port stopped answering. Measured on
  two separate builds. The stderr shows GTK teardown warnings from `gi/overrides/Gio.py`
  (`invalid (NULL) pointer instance`, a `Gdk-CRITICAL` about the frame clock) — cosmetic, on the
  way out, after the decision to exit; worth a look eventually but not a defect in the shutdown
  handshake, which did what §11.2 says it should.

### 13.9 The tests, and the sabotage check

`tests/test_appimage.py`, 7 tests, gated on `BATTERY_SIM_APPIMAGE`. They exist because
`tests/test_packaged.py` **cannot** catch a broken GTK payload: it drives the binary with
`--no-browser`, so every one of its checks passes on an AppImage whose entire WebKit stack is
missing. That is not hypothetical — the first AppImage built here did exactly that.

The tests assert on the payload: the typelibs by NAME (not by counting files — that is the shape of
assertion that let a missing Dutch catalog through in phase 3), `gi` inside `_internal/`
specifically, `optparse`, WebKit's helper executables, the WebKit/GTK libraries, and the variables
AppRun exports.

**Sabotage-checked, three bundles, each breaking one thing.** Each was a copy repacked into its own
AppImage and deleted afterwards; `dist/` was never modified.

| sabotage | result | which test failed |
|---|---|---|
| `WebKit2-4.1.typelib` removed | 1 failed / 6 passed | the typelib test only |
| `_internal/gi` removed | 1 failed / 6 passed | the PyGObject-location test only |
| `WebKitWebProcess` removed | 1 failed / 6 passed | the helper-process test only |

Each sabotage fails exactly one test and the right one, so the checks are discriminating rather
than merely non-vacuous.

**One of the tests was wrong when first written, and the failure is instructive.**
`test_optparse_is_bundled` looked in `_internal/` and `base_library.zip` and reported optparse
missing on a bundle where it was present and working — PyInstaller had put it in the PYZ archive
*inside the executable*. A test that reports a missing dependency when the dependency is there is
worse than no test, because its failure is indistinguishable from the real bug it guards. The
corrected version checks all three locations, and says so.

**A second correction, also worth recording.** The first AppRun assertion used a regex anchored to
line start, which missed the `[ -d … ] && export VAR=` form that several variables legitimately
use. It failed on a correct AppRun. Same category of error as the first: the test was wrong, the
artifact was right.

### 13.10 Test numbers

- `uv run pytest tests/test_desktop.py -q` → **58 passed** in 12.51s. Unchanged from phase 2/3, as
  expected: no application source changed.
- `uv run pytest tests/test_packaged.py -q` with the gate unset → **9 skipped**.
- `BATTERY_SIM_PACKAGED_BINARY=dist/battery-sim/battery-sim …` → **9 passed** in 1.46s.
- The same suite against the AppImage's extracted binary → **9 passed** in 1.33s.
- `uv run pytest tests/test_appimage.py -q` with the gate unset → **7 skipped**.
- `BATTERY_SIM_APPIMAGE=dist/Home-Battery-Simulator-x86_64.AppImage …` → **7 passed** in 2.28s.
- Against each of the three sabotaged AppImages → 1 failed / 6 passed, each time a different test.

The full suite was **not** run, on the standing instruction that it carries slow benchmarks. Its
last recorded figure (§11.6) remains stale and this phase does not update it.

### 13.11 What is NOT verified

- **Portability to any other machine.** The single biggest gap, and the direct consequence of D12.
  Built against glibc 2.39; will not run on anything older. Untested on any distribution but this
  one. The container build is the follow-up.
- **Anything but a bar chart, on anything but the monthly-grid-import tab.** Risk B is answered for
  the chart that is drawn on page load. The `SoC + price` and `Energy flows` tabs were not opened.
- **A full simulation run inside the AppImage.** The results screen renders and prices off the
  shipped CSVs, which is what makes the chart real, but no long run was driven end to end.
- **localStorage persistence across a close/reopen cycle.** `storage_path` reaches pywebview and
  `<data_dir>/webview/` is created and populated, but that the Home Assistant token actually
  survives a restart (the reason for `private_mode=False`, §11.3a) was not checked.
- **The Home Assistant fetch from inside the AppImage window.** R1 was probed from an ordinary
  browser at `http://127.0.0.1:8000`, not from this window at its own port. That is phase 5.
- **Multi-user behaviour of the `/tmp` symlink** (§13.4). Reasoned about, not tested.
- **macOS and Windows.** Untouched.
- **Startup time.** Still not measured. The AppImage is noticeably slower to first answer than the
  onedir bundle (it mounts first); the 40s deadline in `tests/test_appimage.py` is generous rather
  than tight, and no number was taken.
- **Whether the AppImage works without FUSE.** All runs here either mounted normally or used
  `--appimage-extract`. A machine without FUSE needs `--appimage-extract-and-run`, untested.

### 13.12 Status and what is open

Phase 4 is complete for Linux on this machine: the AppImage builds, runs from anywhere, opens a
native window, renders the app and its Plotly chart, keeps its data per-user, serves its WebSocket
route, and shuts down cleanly on window close. Changes are left **unstaged and uncommitted**.

Open, with no recommendation attached:

- **The container build for portability** (D12). Now the cheapest it will ever be, because the
  renderer questions are answered and a container build only has to reproduce a known-good result
  against an older glibc.
- **Phase 5 (packaged HA verification)** — R1 from inside this window, at the launcher's own port,
  and the plain-HTTP LAN case. The window now exists to test it in.
- **The remaining chart tabs**, if Risk B is to be considered fully closed rather than closed for
  the default view.
- **The `$XDG_RUNTIME_DIR` variant of the WebKit symlink** (§13.4), if multi-user matters.
- **Wiring both packaged suites into CI**, carried over from §12.10 and now covering two artifacts.
- **The GTK teardown warnings on window close** (§13.8) — cosmetic, but they are the kind of thing
  that masks a real one later.

## 14. Phase 5 — packaged Home Assistant WebSocket verification

Implemented 2026-08-05 for levels 1 and 2. **Level 3 is written but NOT RUN**, and with it the
premise the whole desktop direction rests on remains unverified — see §14.6, which should be read
before this section is taken as closing R1.

Three levels, as scoped:

1. raw `ws://` against both packaged artifacts (automated);
2. a recorded HA row batch replayed against the packaged server (automated);
3. a run against the user's real Home Assistant (a written procedure, to be run by the user).

### 14.1 What was added

- `tests/test_packaged_ingest.py` — 5 tests, parametrized over each artifact the environment names,
  so a run with both gates set executes 10. Gated on `BATTERY_SIM_PACKAGED_BINARY` **and/or**
  `BATTERY_SIM_APPIMAGE`, the same env-var idiom as the two packaged files beside it.
- `changelog/20260805-ha-verification-procedure.md` — the level-3 procedure.

No application source changed. `app/`, `packaging/`, `pyproject.toml` and `uv.lock` are untouched
by this phase, as they were by phases 3 and 4. Changes are left **unstaged and uncommitted**.

### 14.2 D13 — one file parametrized over both artifacts, rather than a file per artifact

The task described level 1 as running against "both the onedir binary and the AppImage". That could
have been two files, or an addition to each of the two existing ones. It is one file with a
`params`-ed fixture instead, for a reason that turned out to be load-bearing rather than cosmetic:
**the AppImage had never had a WebSocket opened against it at all.**

`tests/test_appimage.py` asserts on the *payload* — typelibs, `gi`'s location, WebKit's helpers —
and its single end-to-end check drives the image with `--no-browser` over HTTP. `tests/test_packaged.py`
does open a raw `ws://`, but only ever against the onedir bundle. So the AppImage's repack — a
different `sys.path`, a relocated `_internal/`, an AppRun that rewrites the environment — sat
between a working ingest route and the artifact the user is actually given, with nothing checking
it. That gap is now measured rather than argued: see §14.4, where a deliberately broken AppImage
passes `tests/test_appimage.py` 7/7.

The parametrization keeps the artifact label in the pytest id, so a failure names which artifact
broke without anyone decoding a path.

### 14.3 Level 1 — how much it is actually worth, stated honestly

The task asked whether level 1 still adds value beyond the phase-3 finding that pinning
`ws="websockets-sansio"` turns a missing WebSocket module into a hard `ModuleNotFoundError` at
startup. **It is partly redundant, and the redundancy was measured rather than reasoned about.**

A bundle was rebuilt with `uvicorn.protocols.websockets.websockets_sansio_impl` dropped from
`hiddenimports` and `websockets` added to `excludes` — phase 3's sabotage, reproduced. The result
against `tests/test_packaged_ingest.py` was **5 errors, all at the fixture**:

```
uvicorn/config.py:487 → import_from_string → websockets_sansio_impl.py:15
ModuleNotFoundError: No module named 'websockets'
the server did not become ready in time
```

So for *that* failure mode level 1 adds nothing: the server does not start, and every test in every
packaged file fails first. §12.6's conclusion holds and this phase confirms it independently.

**What level 1 does still cover is narrower, and it is real.** The failure it uniquely guards is an
implementation that imports and upgrades but cannot carry a frame *outbound*. A bundle was built
with the route's two `ws.send_json` calls suppressed (the `progress` frame and the `error` frame),
leaving everything else intact. Results:

| suite | onedir | AppImage |
|---|---|---|
| `tests/test_packaged.py` | 1 failed / 8 passed | (n/a — no AppImage gate) |
| `tests/test_appimage.py` | (n/a) | **7 passed** |
| `tests/test_packaged_ingest.py` | 3 failed / 2 passed | **3 failed / 2 passed** |

The middle row is the finding. **An AppImage whose ingest protocol cannot answer passes the entire
existing AppImage suite.** On the onedir bundle `tests/test_packaged.py::test_the_websocket_route_works`
does catch it, so level 1's contribution there is duplicated coverage rather than new coverage —
worth saying plainly. On the AppImage it is the only thing watching.

Note also which two tests survived that sabotage: the upgrade test and the 404-handshake test both
passed, because the handshake was never broken. That is the intended discrimination — a handshake
check and a frame check answer different questions, and folding them into one assertion would have
lost exactly the distinction phase 3 §12.11 warns about.

**A third, cheaper sabotage was attempted first and did not work**, which is worth recording so it
is not retried. Moving `_internal/websockets/` aside in a bundle copy changed nothing — 5 passed.
That directory holds only the compiled `speedups` extension; the pure-Python `websockets` modules
live in the PYZ archive inside the executable. File-removal sabotage does not reach them, and a
rebuild from a modified spec is the only way to sabotage an import in this bundle layout.

### 14.4 Level 2 — replay, and the read-back that is the point of it

`tests/test_ingest_ws.py::_drive_valid_ingest` already replays a recorded HA row batch, so the DATA
was reused: the same three hourly series (a cumulative import register, a cumulative export
register, a spot price) over the same two-hour window, and the same `stat_id`. The *driver* was not
reusable — that helper drives a FastAPI `TestClient` with synchronous `send_json`/`receive_json`,
which speaks ASGI directly and performs no HTTP upgrade at all, while level 2 needs an async
`websockets` client against a separate frozen process. So the batch is copied with a comment saying
why, and the assertions on the `result` frame mirror
`test_valid_ingest_persists_and_reports` deliberately: the packaged build must produce the same
answer the source tree does, and the source tree's expectation is pinned by a test that runs on
every ordinary pytest invocation.

The second level-2 test is the one that earns its place. It re-reads the persisted dataset out of a
**separate HTTP request** to the configure-data screen, so two independent code paths have to agree
and the write must have reached disk in the frozen process's per-user data directory rather than
only an in-memory session.

**Sabotage-checked, and it discriminates cleanly.** A bundle was built with `stat_id` forced to
`None` on persistence — frames still flow, the `result` frame is still correct, only the read-back
is wrong:

| suite | result |
|---|---|
| `tests/test_packaged.py` | **9 passed** |
| `tests/test_packaged_ingest.py` | **1 failed** / 4 passed — the read-back test, alone |

Exactly one test fails and it is the right one. This is the failure class no other packaged test
observes: the socket exchange succeeds and reports success, and the data is quietly wrong.

The workspace fixture here is **function-scoped**, unlike the module-scoped one in
`tests/test_packaged.py`. Level 2 persists a dataset and then asserts on the screen that renders
it; sharing one workspace across tests would let an earlier ingest satisfy a later assertion.

### 14.5 The 404 trap, now pinned in executable form

§10 recorded that an unknown workspace id fails the ingest route's **handshake** with an HTTP 404
rather than with an in-protocol error, and warned that a test which skipped seeding would report a
packaging bug that is not there. `test_level1_an_unknown_workspace_fails_the_handshake` now asserts
that behaviour directly, and asserts on the **status code** rather than merely on "it failed" — a
bundle genuinely lacking WebSocket support also fails that connection, but with a different shape.
The intent is that the next person to meet this reads a passing test instead of rediscovering it.

### 14.6 Level 3 — WRITTEN, NOT RUN

`changelog/20260805-ha-verification-procedure.md`. It is a checklist for the user to run against
their own Home Assistant, and **nothing in it has been executed**.

The question it exists to answer:

> Does `ws://` from a page served at `http://127.0.0.1:<port>` reach a **plain-HTTP** LAN Home
> Assistant, and does HA's origin check accept that origin?

**R1 remains PARTIALLY verified and this phase does not change that.** The earlier probe succeeded
but ran against an HA served over `https://`, so what it exercised was `wss://`. The plain-HTTP LAN
case — the configuration §2.1 identifies as the common default and as the specific thing hosting
broke — is still untested. Levels 1 and 2 do not touch it: they prove our own ingest socket works
in the packaged artifacts, which is the *backend* half. The HA half runs in the browser and needs a
real HA.

Two things the procedure had to get right, and they are the reason it is not shorter:

- **Which case the user is exercising is not obvious from the UI.** `app/static/ha_fetch.js`
  derives the HA scheme from what is typed into the base-URL field, and a **bare** host silently
  becomes `https://` (around line 331). So a user who types `192.168.x.x:8123` gets `wss://` and
  would report a pass on the case that was already proven. Step 0 makes them check with `curl`
  first and record which case they ran, and says what to do when HA is https-only — including that
  the decisive case may not be testable without reconfiguring HA, in which case the honest outcome
  is "still unverified" rather than a substituted `wss://` result.

- **The failure is otherwise unobservable.** The HA fetch runs in the browser/webview, so its
  console is inside the pywebview window.

### 14.7 How JS console output can be observed — investigated

- **`--browser` mode is the practical answer**, and the procedure says so. It opens the user's
  normal browser with full devtools and a network pane that shows the WebSocket frames.
  **Verified**: the AppImage was run with `--browser` and printed
  `Home Battery Simulator on http://127.0.0.1:8231/`, answering 200. So `--browser` serves the
  **same origin and the same scheme** as the native window, which makes it a valid proxy for the
  origin question — the only thing it does not exercise is the WebKit renderer itself. (The probe
  process was terminated by its exact PID.)

- **The shipped pywebview window has no inspector.** pywebview supports one — `webview.start()`
  takes `debug: bool = False`, and pywebview 6.2.1's `webview/platforms/gtk.py` sets
  `enable_developer_extras = True` under it and, with its default `OPEN_DEVTOOLS_IN_DEBUG`, calls
  `get_inspector().show()`. But `app/desktop.py::_show_window` does not pass `debug` and there is
  no CLI flag for it, so right-click → Inspect Element is not available today. **Verified by
  reading both sources; NOT verified by opening an inspector** (this venv cannot import `gi`).
  AppRun forwards `"$@"` to the frozen launcher, so a future `--debug` flag would reach the
  AppImage unchanged. Adding one is a small change and was deliberately **not** made here — it is
  application source, and this phase changed none.

- **Environment variables do not substitute.** The inspector is gated on the
  `enable_developer_extras` WebKitSettings property, which is what `debug=True` sets; there is no
  env var that flips it. The inspector UI is compiled into `libwebkit2gtk` on this build (no
  separate gresource file was found), so it would travel with the AppImage if it were enabled.

- **stderr works in both modes** and carries the launcher's own output, but never JS console
  output.

### 14.8 Test numbers

Measured, per file. The full suite was **not** run, on the standing instruction that it carries
slow benchmarks; §11.6's figure remains stale and this phase does not update it.

Good artifacts:

- `uv run pytest tests/test_packaged_ingest.py -q`, both gates unset → **5 skipped** in 0.02s.
- `BATTERY_SIM_PACKAGED_BINARY=dist/battery-sim/battery-sim …` → **5 passed** in 1.40s.
- `BATTERY_SIM_APPIMAGE=dist/Home-Battery-Simulator-x86_64.AppImage …` → **5 passed** in 1.27s.
- both gates together → **10 passed** in 2.62s.
- `BATTERY_SIM_PACKAGED_BINARY=… uv run pytest tests/test_packaged.py -q` → **9 passed** in 1.31s.
- `BATTERY_SIM_APPIMAGE=… uv run pytest tests/test_appimage.py -q` → **7 passed** in 1.86s.
- `uv run pytest tests/test_desktop.py tests/test_ingest_ws.py -q` → **75 passed** in 13.65s
  (58 + 17; both unchanged, as expected — no application source changed).

Sabotaged artifacts (each rebuilt, tested, then deleted; the spec and `app/` were restored and
`git status` confirmed clean before the good bundle was rebuilt):

| sabotage | `test_packaged.py` | `test_appimage.py` | `test_packaged_ingest.py` |
|---|---|---|---|
| WebSocket impl dropped from the spec | — | — | 5 errors (server will not start) |
| outbound `progress`+`error` frames suppressed | 1 failed / 8 passed | **7 passed** | 3 failed / 2 passed (both artifacts) |
| `stat_id` dropped on persistence | **9 passed** | — | **1 failed** / 4 passed |
| `_internal/websockets/` moved aside | — | — | 5 passed (does not sabotage — see §14.3) |

The two bold cells are what justifies the file: an existing suite fully green on an artifact that is
broken in a way this phase's tests catch.

### 14.9 What is NOT verified

- **The plain-HTTP LAN Home Assistant premise.** The headline gap. Level 3 is unrun; R1 stays
  PARTIALLY verified, on a `wss://` probe. Everything phases 1-5 built assumes a browser rule
  (an `http://127.0.0.1` page may open `ws://` to a LAN host) that has been read from
  documentation here and never measured against a real HA.
- **The HA fetch from inside the pywebview window**, at the launcher's own port. Levels 1 and 2
  drive the artifacts with `--no-browser`; nothing here opened the native window.
- **That the inspector actually opens under `debug=True`.** Reasoned from two sources, not run.
- **Whether the earlier probe's origin acceptance survives a non-8000 port.** The procedure will
  answer this incidentally (the launcher defaults to 8137), but it has not been answered.
- **Everything §13.11 lists** — portability off this machine, the other chart tabs, a full
  simulation run in the packaged build, localStorage persistence across a restart, macOS and
  Windows, startup time, FUSE-less operation. Phase 5 touched none of them.

### 14.10 Status and what is open

Levels 1 and 2 are complete: both packaged artifacts accept a raw `ws://` upgrade, answer a
server-originated frame, replay a recorded HA row batch, and persist it where a separate HTTP
request can read it back. The tests are sabotage-checked and discriminate between failure modes
rather than merely being non-vacuous. Changes are **unstaged and uncommitted**.

Open, with no recommendation attached:

- **Running level 3.** It needs the user's own Home Assistant and it is the only item here that
  bears on whether the direction is sound.
- **A `--debug` flag on the launcher**, passing `debug=True` to `webview.start()`, if the native
  window is ever to be diagnosable on its own terms rather than through `--browser`. Small; it is
  application source, so it was not done unasked.
- **Wiring all three packaged suites into CI**, carried forward from §12.10 and §13.12 and now
  covering a third file.
- **The container build for portability** (D12), unchanged from §13.12.

## 15. Phase 6 — a user-reported missing library, and why phase 4's verification did not catch it

### 15.1 The report

The user ran the phase 4 AppImage on their own machine (Ubuntu 24.04, the same box the image was
built on) without `--browser`, and got a browser instead of a window:

    WARNING **: Failed to load shared library 'libwebkit2gtk-4.1.so.0' referenced by the typelib:
    libmanette-0.2.so.0: cannot open shared object file: No such file or directory
    native window unavailable (Error: g-invoke-error-quark: Could not locate
    webkit_get_major_version: ... undefined symbol: webkit_get_major_version (1))

`libmanette-0.2.so.0` — WebKit's gamepad support — is a direct `NEEDED` entry of
`libwebkit2gtk-4.1.so.0` and was absent from the AppDir. The `undefined symbol` message is a
consequence, not a second fault: when `libwebkit2gtk` fails to load, the typelib's introspection
call resolves against `libjavascriptcoregtk` alone, which does not define
`webkit_get_major_version`.

### 15.2 Root cause: an unanchored alternation in EXCLUDE_RE

The build's library collector walks `ldd` transitively and drops anything matching

    EXCLUDE_RE='^(ld-linux|libc|libm|libdl|...|libwayland)'

Every alternative is anchored at the left and **not at the right**. `^libm` therefore matches
`libmanette-0.2.so.0`, `libmount.so.1` and `libmd.so.0` as readily as `libm.so.6`; `^libc` matches
`libcairo.so.2` and `libcrypto.so.3`; `^librt` matches `librtmp.so.1`. The intent was to leave a
short list of host-supplied libraries (libc, libm, the GL and X stacks) out of the image. The
effect was to also drop ten libraries that the bundle genuinely needs.

This was a single-character-class mistake, not a design flaw in the collection approach. The
approach — transitive `ldd` closure from a root set — was already right. What was missing was any
check that its OUTPUT was complete.

### 15.3 The full set of wrongly excluded libraries

Computed as the transitive `NEEDED` closure by SONAME over the same root set the build uses,
compared against the AppDir's actual contents. Ten, of which the user's report surfaced one:

    libcairo.so.2            libcairo-gobject.so.2     libcap.so.2
    libcom_err.so.2          libcrypto.so.3            libcurl-gnutls.so.4
    libmanette-0.2.so.0      libmd.so.0                libmount.so.1
    librtmp.so.1

That `libcairo` was missing and the image still rendered anything at all is worth noting: the host
supplied it, because the AppImage prepends its own directory to `LD_LIBRARY_PATH` rather than
replacing it. Every one of these was being satisfied by the host on the build machine. On a machine
without them the failures would have been assorted and confusing.

### 15.4 The verification failure — the more important half

Phase 4 (§13) claimed self-containment was verified by running the image under `unshare -m` with
the host's `girepository-1.0`, `webkit2gtk-4.1` and `python3/dist-packages` masked by tmpfs, and
presented a screenshot as evidence. **That claim was overstated and the screenshot proved less than
it appeared to.**

The masking covered three specific subdirectories. It did not cover
`/usr/lib/x86_64-linux-gnu` itself, which is where all ten of the missing libraries live. So the
masked run resolved `libmanette`, `libcairo`, `libcrypto` and the rest from the host exactly as an
unmasked run would, produced a window, and produced a screenshot — while the image was, at that
moment, unable to run on a machine lacking those libraries. The screenshot is real; what it
demonstrates is narrower than "the AppImage carries its own WebKit stack". It demonstrates that the
image carries its own typelibs, its own PyGObject and its own WebKit helper processes — the three
things that were masked.

The general lesson, recorded because it is the reusable part: a negative test that masks a
hand-picked list of paths verifies only that list. It cannot discover a dependency nobody thought
to mask, which is precisely the class of bug it is supposed to catch.

### 15.5 D14 — a static closure check at build time, as the primary guard

Chosen over strengthening the runtime masking as the main defence, though both are done.

The check: for every ELF file in the AppDir, read its `NEEDED` entries, and require that each one
either resolve inside the AppDir or appear on an explicit, exact-match allowlist of libraries the
image deliberately leaves to the host. It runs in `build-appimage.sh` before `appimagetool`, so a
missing library fails the build rather than the user's launch.

Why this over the runtime check as primary:

  * It needs no display, no X server, no container and no `unshare` privileges, so it can run
    anywhere, including CI, and it costs about a second.
  * It is exhaustive by construction rather than by the author's imagination. It cannot miss a
    library because nobody thought to mask its directory — the failure mode of §15.4.
  * It fails at BUILD time, on the machine that has the information, rather than at run time on a
    machine that does not.

Its limit, stated: it verifies the dynamic-link closure only. Anything `dlopen`ed by name at
runtime — the gdk-pixbuf loaders, the GIO modules, the typelibs — carries no `NEEDED` entry and is
invisible to it. Those remain covered by the existing per-item assertions in `tests/test_appimage.py`
and by the runtime check below.

The exclusion list is now expressed as exact SONAME prefixes matched against a `[.-]` boundary, so
`libm` matches `libm.so.6` and no longer matches `libmanette-0.2.so.0`. Both the build and the test
derive the allowlist from the same shape of rule.

### 15.6 The runtime check, strengthened, as a secondary

The `unshare -m` run now masks the whole of `/usr/lib/x86_64-linux-gnu` (plus `/lib/x86_64-linux-gnu`
and the same three subdirectories as before), leaving only the loader itself reachable, and the
image is launched with the host's library path deliberately unavailable. This is what §13's check
should have been. It is kept as a secondary guard because it exercises the actual load, which the
static check cannot: it catches a library that is present but wrong, and it catches the `dlopen`
paths the static check is blind to.

### 15.7 Files modified

  * `packaging/build-appimage.sh` — the `EXCLUDE_RE` anchoring fix, and a new closure-verification
    step that fails the build.
  * `tests/test_appimage.py` — a new test asserting the same closure property against the built
    image, gated as the rest of the file is.
  * `packaging/check-appdir-closure.py` — NEW. The static closure check, shared by the build and
    the test so the two cannot disagree about what self-contained means.
  * `packaging/verify-appimage-isolated.sh` — NEW. The runtime check, rewritten as a container run
    rather than a tmpfs mask (see §15.9).

### 15.8 Fails-then-passes, both guards

Demonstrated in that order, against the actual phase 4 artifact and then the rebuilt one. The
broken layout was reconstructed exactly — the fixed AppDir with the ten dropped libraries removed —
and repackaged with appimagetool so both guards saw a real AppImage rather than a directory.

| guard | phase 4 (broken) | rebuilt (fixed) |
|---|---|---|
| `check-appdir-closure.py` | exit 1, names 8 missing sonames incl. `libmanette-0.2.so.0` | exit 0, "library closure is self-contained" |
| `verify-appimage-isolated.sh` | exit 1, no window, `libcairo.so.2: cannot open shared object file` | exit 0, window titled "Home Battery Simulator" |
| `test_the_library_closure_is_self_contained` | 1 failed, missing libraries listed | 1 passed |

The closure check reports 8 rather than 10 because `libcrypto` and `librtmp` are reached only
through `libcurl-gnutls`, which was itself absent — they surface once it is bundled, and the
rebuilt image carries all ten.

### 15.9 The runtime check is now a container, not a mask

Replacing the `unshare -m` + tmpfs approach outright. A pristine `ubuntu:24.04` has no GTK, no
WebKit, no libmanette, no python3-gi and no typelibs — not hidden, simply never installed — so
there is nothing to overlook masking. The container installs only what an AppImage is entitled to
expect from any host: an X server, and the X11/Wayland/EGL/GL client libraries the build
deliberately does not bundle because they must match the user's display server and driver. The
script asserts that absence before it runs, so the test bed cannot drift into quietly helping.

Note on why the mask approach was not merely tightened: `unshare` and `bwrap` both need
unprivileged user namespaces, which are restricted by AppArmor on this machine
(`kernel.apparmor_restrict_unprivileged_userns = 1`), so the phase 4 method could not be reproduced
here at all. Also checked and rejected: `ld.so --inhibit-cache --library-path`, which looked like it
would give a hermetic search path but does not — the loader still falls back to its BUILTIN default
directories, and the broken layout resolved `libmanette` from `/lib/x86_64-linux-gnu` under it.
That near-miss is worth recording: it is the same shape of incomplete isolation as the original.

### 15.10 Verification actually performed

- **Rebuilt** with the fixed collector. All ten previously-dropped libraries present. 119 libraries
  in the AppDir, up from 109. **106 MB** (110,914,040 bytes), up from ~105 MB.
- **The user's own scenario, on this machine**: the AppImage launched under Xvfb with no
  `--browser`. Window "Home Battery Simulator" opened; the log is clean — no libmanette warning, no
  "native window unavailable", no browser fallback. Screenshot shows the rendered workspace list.
- **The stronger case**: the same AppImage in the clean container. Window opened, with
  `WebKitWebProcess` and `WebKitNetworkProcess` both running off the bundled payload on a machine
  with no WebKit installed at all. This is the claim phase 4 made and did not establish.
- **Test numbers.** Targeted files only; the full suite was not run, per the standing instruction.
  - `tests/test_appimage.py` with the gate on → **8 passed** in 2.72s (was 7; the new test is the eighth).
  - `tests/test_desktop.py` → **58 passed** in 12.30s (unchanged; no application source changed).
  - `tests/test_packaged.py` with the gate on → **9 passed** in 1.45s.
  - `tests/test_packaged_ingest.py`, both gates on → **10 passed** in 2.86s.
  - All three gated files with gates off → **22 skipped** in 0.05s.

### 15.11 Two incidental findings, neither fixed

Both surfaced from running in a genuinely bare container and are recorded rather than acted on,
because neither is the reported bug and neither affects a normal desktop.

- **`tzdata` is not bundled.** On a container without the system tzdata the app dies at import with
  `ZoneInfoNotFoundError: 'No time zone found with key Europe/Amsterdam'`. Every real desktop has
  tzdata, so this is not a user-facing bug today; it does mean the AppImage is not self-contained
  with respect to the timezone database, which for an app whose pricing logic is
  Europe/Amsterdam-specific is arguably a gap worth closing. Not done here — it is outside the
  reported fault and would change what the bundle carries.
- **`libGLESv2.so.2` and a GStreamer element are looked up and missing** in a bare container
  (`GStreamer element appsink not found`). Both are non-fatal: the window opens and renders. The
  GLES lookup is compositing, already disabled via `WEBKIT_DISABLE_COMPOSITING_MODE`; appsink is
  HTML5 media, which this UI does not use.

### 15.12 What is NOT verified

- **That the closure is right on a machine other than this one.** The build still collects from the
  build host, so D12 (a container build for portability) is unchanged and still open.
- **`dlopen`ed dependencies.** The static check is blind to them by construction. The gdk-pixbuf
  loaders, GIO modules and typelibs have their own named assertions, but a plugin that appears
  upstream later would be caught by neither.
- **Whether the ten libraries were the only fallout of the anchoring bug.** The closure check says
  the dynamic-link graph is now complete, which is a stronger statement than a hand review, but it
  is a statement about NEEDED entries only.
- **The user's actual desktop session.** Verified under Xvfb here, not against a real compositor
  with their own graphics driver.

### 15.13 Status

The reported bug is fixed and the fix is guarded at build time, in the test suite, and by a runtime
check that would have caught it. Changes are **unstaged and uncommitted**.

The honest summary of this phase: the bug itself was a one-character regex mistake, and the
substantive work was establishing why a whole phase of verification did not notice it. The build
now computes its own closure and fails on a gap, rather than depending on the exclusion list being
written correctly.

## 16. Phase 7 — the GStreamer `appsink` warning on startup

### 16.1 The report

The user launches the AppImage and, before anything else, sees on stderr:

    GStreamer element appsink not found. Please install it.

The app works — the window opens, everything renders — but the line reads as a fault to a
non-technical user, which is the audience. `appsink` lives in `gstreamer1.0-plugins-base`; WebKitGTK
probes for it when it initialises its media backend. The app has no `<video>`, `<audio>` or WebRTC:
it is server-rendered HTML, plain DOM JavaScript, and Plotly.

### 16.2 The approach chosen, and the one rejected

Rejected: filtering the line out of stderr. stderr is a working diagnostic channel in this project —
the phase 6 libmanette failure and an earlier pywebview `TypeError` both surfaced there — and a
filter risks swallowing the next genuine error. Also rejected, per instruction: bundling
`gstreamer1.0-plugins-base`, which adds weight for a capability the app never uses.

Chosen: stop WebKit initialising the media backend at all, so the probe never runs.

### 16.3 Root cause, found before anything was tried

Running the AppImage under Xvfb with `GST_DEBUG=GST_REGISTRY:5` and correlating the emitting PID
against `ps` gives the mechanism directly:

- The line comes from the **WebKitWebProcess**, not from the launcher or the main app process.
- It is emitted at timestamp `0:00:00.001`, i.e. in the web process's first millisecond.
- GStreamer locates its own library with `dladdr()`, finds it at
  `/tmp/appimage_extracted_<hash>/usr/lib/x86_64-linux-gnu`, and therefore scans **only**
  `<that dir>/gstreamer-1.0` for plugins — a directory the AppDir does not have. `GST_PLUGIN_PATH`
  and `GST_PLUGIN_SYSTEM_PATH` are unset, so nothing else is scanned. The host's own 109 plugins in
  `/usr/lib/x86_64-linux-gnu/gstreamer-1.0` are never looked at.

So the AppImage bundles the GStreamer *shared libraries* — `libgstreamer-1.0`, `libgstapp-1.0` and
eight more, pulled in because `libwebkit2gtk` lists them as `NEEDED` — but not the *plugins*, which
are `dlopen`ed and therefore invisible to the closure collector (the blind spot §15.12 already
names). Bundling the libraries is what redirects the plugin search away from the host's plugins.

The precise call site was located by disassembly: `Source/WebCore/platform/graphics/gstreamer/
GStreamerSinksWorkarounds.cpp`, which calls `gst_element_factory_find("appsink")` and, on NULL,
calls `WTFLogAlways` with this message. It is a probe for a GStreamer bug fixed in 1.24, not a
media feature the page asked for.

### 16.4 What was tried, and the result: NEGATIVE

**Avenue 1 — WebKitSettings properties.** Introspected rather than assumed. WebKit2GTK 2.52.3 on
this machine does have `enable-media` (2.38+), plus `enable-media-stream`, `enable-mediasource`,
`enable-webaudio`, `enable-media-capabilities`, `enable-encrypted-media`. pywebview 6.2.1 exposes
none of them and its GTK backend sets three of them to True itself, so reaching them needs a
monkeypatch of `BrowserView.__init__` — the URL is loaded at the end of that method, so every
pywebview event hook (`initialized`, `before_show`, `loaded`) runs too late.

Implemented in `app/desktop.py`, AppImage rebuilt, run under Xvfb: **the warning is still there.**

**Avenue 1b — WebKit runtime features.** WebKit 2.52 also carries a feature registry separate from
the settings properties (`webkit_settings_get_all_features` / `set_feature_enabled`), including a
`GStreamer` feature and a `Media` feature, both defaulting to True. Both are settable. Added to the
same patch, rebuilt, rerun: **the warning is still there.**

Both results are consistent with the timing evidence. The web process brings GStreamer up in its
first millisecond, before any settings have been delivered over IPC, so no setting on the UI-process
side can gate it.

**Avenue 2 — an environment variable.** No `WEBKIT_DISABLE_MEDIA` or equivalent exists. The
library's string table was dumped and every `WEBKIT_*` string inspected; the media-related ones are
all `WEBKIT_GST_*` tuning knobs, none of which is a master switch. The closest,
`WEBKIT_GST_WORKAROUND_BASE_SINK_POSITION_FLUSH`, belongs to the very function that emits the
message — but the disassembly shows the env var is read *after* the `appsink` lookup, on the branch
taken only when the element was found. Tested anyway with `Never` and `Always`: **warning still
present in both.** Inventing a plausible-looking variable would have been a false fix; this one is
real and simply cannot help.

**Avenue 3 — bundling `gstreamer1.0-plugins-base`.** Not attempted, per instruction.

**Not adopted — pointing GStreamer at the host's plugins.** Setting `GST_PLUGIN_SYSTEM_PATH` and
`GST_PLUGIN_SCANNER` in AppRun to the host's Debian paths does produce a completely clean log on
this machine. It is rejected as a fix: it hardcodes a Debian-specific layout, and on a host without
`gstreamer1.0-plugins-base` installed it degrades to exactly the warning being fixed. It would look
like a fix here and not be one on the machines that matter.

### 16.5 Application source: reverted, nothing changed

`app/desktop.py` was modified during the investigation (a `_disable_webkit_media` helper wrapping
pywebview's GTK `BrowserView.__init__`) and **reverted**, because it did not achieve its purpose.
Carrying a monkeypatch of another library's internals that changes WebKit's media behaviour for no
measured benefit is not justified. `git diff -- app/` is empty. The AppImage was rebuilt after the
revert and is byte-for-byte the same size as before this phase: **110,914,040 bytes (106 MB)**.

### 16.6 Verification performed

- **BEFORE**: the pre-existing AppImage under Xvfb → `app.log` is two lines, the second being
  `GStreamer element appsink not found. Please install it.`
- **AFTER each candidate**: same command, same harness, same host. Warning present in all of them.
- **The app still works**, on the rebuilt image: window "Home Battery Simulator" opens; the
  workspace list renders.
- **Plotly still renders.** A year of hourly rows (8,760 intervals × 3 series) was replayed into a
  fresh workspace over the packaged build's own ingest WebSocket, and the results screen was driven
  in the native window. The monthly chart draws 12 bars Jan–Dec with y-axis ticks at 0/50/100/150
  and the `kWh` axis label. Screenshot in the scratchpad as `plot3/03-results-scrolled.png`.
- **Tests.** Targeted only, per the standing instruction. `tests/test_appimage.py` +
  `tests/test_desktop.py` with the AppImage gate on → **66 passed** in 14.58s.
  `tests/test_packaged.py` with its gate on → **9 passed** in 1.32s.

### 16.7 Status: not cleanly fixable without bundling or patching

Reported plainly rather than forced. The warning cannot be removed by configuration from the
embedding side: it is emitted by the web process before any configuration reaches it, and the only
environment variable in the neighbourhood is consulted after the failing lookup.

What remains, none of them adopted here:

- **Bundle `gstreamer1.0-plugins-base`** into `<AppDir>/usr/lib/x86_64-linux-gnu/gstreamer-1.0`.
  This is the one option that addresses the actual cause — the plugin directory GStreamer looks in
  is empty — and it would very likely also fix whatever else silently degrades from having the
  GStreamer libraries without their plugins. Cost is size and carrying a media stack the app does
  not use. Explicitly ruled out for this phase.
- **Filter stderr** in the launcher. Cheap and effective, and the objection to it stands: stderr is
  where the libmanette failure and the pywebview `TypeError` surfaced, and a filter is a place for
  the next one to disappear. A filter narrowed to this exact literal string would be a much smaller
  risk than a general one, if it is revisited.
- **Leave it.** The app is correct and the line is one cosmetic message.

### 16.8 Not verified

- **That no OTHER dlopen-based subsystem is in the same state.** GStreamer's plugins are missing for
  a structural reason — the closure check cannot see `dlopen` — and the same reasoning applies to
  any other plugin directory WebKit or GTK reaches for. Only GStreamer was investigated.
- **Whether the missing plugins cost anything beyond the message.** The app has no media, so
  probably not, but nothing was measured; the claim here is only that the window opens and the
  results screen renders.
- **The user's real desktop.** Everything above is Xvfb on this build host.
