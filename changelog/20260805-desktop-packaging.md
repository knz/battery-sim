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
