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
