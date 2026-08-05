# Desktop packaging — decision inventory

Running record of decisions taken while working through the desktop-packaging phases,
kept so the user can review autonomous choices in one place rather than reconstructing
them from the phase changelog. Detail lives in `20260805-desktop-packaging.md`; this
file is the index of *what was decided and by whom*.

Each entry: what was decided, who decided it, why, and what would reverse it.

## Legend

- **U** — decided by the user
- **A** — decided autonomously by the assistant; reversible, flagged here for review

---

## U1 — Desktop packaging over hosted multi-user

Hosting was investigated and shelved. The deciding factor was architectural rather than
budgetary: the Home Assistant fetch runs in the browser with the token in `localStorage`,
and an HTTPS-hosted page cannot open `ws://` to a plain-HTTP LAN Home Assistant. Keeping
the page on `http://127.0.0.1:<port>` restores that. Findings kept in
`20260804-hosted-multi-user.md`.

## U2 — Native window via pywebview, not a browser tab

## U3 — Linux ships as an AppImage bundling WebKit2GTK; Linux built first

## U4 — Commits land on the current branch (`feat/pending-affordance-backend`)

## U5 — localStorage survives window close

Confirmed desirable "in case of crash": the HA token is not re-entered every launch.
Accepted consequence: the token is written to disk under the app data dir, so the medium
shifts from browser-managed to app-managed. Clearing browser site data no longer clears it.

## U6 — Do not run the full pytest suite during development

It contains benchmarks and is slow. Targeted tests only, per phase. Known gap: this does
not cover regressions outside the targeted files. Open question — whether a marker exists
to separate benchmarks out, which would give a better per-phase check.

## U7 — The native window is first tested in Phase 4, not worked around in Phase 3

Rejected the dev-machine workarounds (system-site-packages for `gi`, or the Qt backend)
because they prove nothing about the shipped artifact — Qt renders with Chromium, not the
WebKit the AppImage will carry. Consequence: Phase 3 packages a window nobody has seen,
and two risks land together in Phase 4 (GObject typelibs, and Plotly under WebKit2GTK).

## U8 — Ship only the locales the app supports

Babel's other locale data is dropped. Safe because `resolve_locale` returns only a member
of `SUPPORTED` or `DEFAULT_LOCALE`, so an arbitrary `Accept-Language` header never reaches
`Locale.parse`. Measured: babel 32MB → 1.5MB, bundle 120MB → 89MB.

---

## A1 — Verification and review delegated to sub-agents, not done inline

Every phase is implemented by one agent and reviewed adversarially by a second that did not
write the code. The orchestrator holds conclusions, not transcripts.

Justified by outcome so far: the review caught a Ctrl-C shutdown regression in Phase 2 and a
silent locale-catalog test gap in Phase 3, both of which the implementing agent had reported
as clean.

## A2 — pywebview arguments corrected against the installed signatures, not the docs alone

`private_mode` / `storage_path` belong on `webview.start()`, not `create_window()`. Confirmed
against both Context7 docs and `inspect.signature` on the installed 6.2.1.

## A3 — The window fallback catches known environment failures only

`ImportError`, `WebViewException`, `RuntimeError` fall back to the browser; `TypeError` is
re-raised. The previous catch-all disguised a coding error of ours as a missing renderer,
which is why the bad `create_window` call shipped.

Residual: `RuntimeError` is broader than 6.2.1 strictly needs, kept for older versions and
alternate backends. It is the one remaining place our own error could be absorbed. Reversible
by dropping it from the tuple.

## A4 — Server completion is signalled by a `threading.Event`, never `Thread.is_alive()`

A signal interrupting `Thread.join()` makes CPython mark the thread stopped, so liveness reads
False while the server still runs. Trusting it skipped the ASGI lifespan shutdown on Ctrl-C.

## A5 — onedir, not onefile

onefile unpacks to a temp directory each launch and deletes it on exit — a data-loss trap, and
the reason the `sys.frozen` guard exists. onedir is also inspectable when debugging what got
bundled.

## A6 — The build uses a throwaway venv

`uv sync --no-dev` in place would have uninstalled playwright, pytest and httpx from the
working `.venv`.

## A7 — A hard size gate fails the build above 150MB

A blown ceiling nearly always means `external_data/` (429MB) or `node_modules/` (48MB) leaked
in. Verified by execution to exit 1, not merely by reading the script.

## A8 — Test non-vacuity is verified by sabotage

Bundles are deliberately broken to confirm the suite notices. This is what surfaced the locale
gap: deleting the entire Dutch catalog left the suite green.

## A9 — Phase 4 built natively rather than in Docker

The plan called for building against an older glibc for portability. Docker was available,
but the build was done natively anyway, to vary one thing at a time: the open question was
whether the window works at all, and adding an unfamiliar distro's WebKit stack to that
question would have made a failure ambiguous.

Consequence, stated rather than buried: the artifact is built against glibc 2.39 and will
not run on Debian 12 or older. **It is not yet shippable to arbitrary users.** Portability
is the top follow-up, and now cheap to test, since a working reference build exists to
compare against.

## A10 — A separate `tests/test_appimage.py`, rather than extending the packaged tests

The phase 3 tests run `--no-browser`, so they pass on an AppImage with the entire WebKit
stack missing — the first build here did exactly that. Window-dependent assertions need
their own file and their own gate.

## A11 — WebKit's helper-process path patched in the copied library

WebKit compiles the path to its network and web processes into the library, with no
environment override. Copying the helpers into the AppDir changes nothing: the library
still uses the host's, so the AppImage would only run where WebKit2GTK was already
installed — which defeats the point.

The two NUL-terminated strings are patched to a fixed `/tmp` path, a symlink AppRun
repoints per launch. **Known limitation, recorded rather than hidden:** the name is shared
across users, so a second concurrent user on the same machine falls back to the browser
instead of being pointed at the first user's mount. Acceptable for a single-user desktop
app; would need revisiting for a multi-seat machine.

## U9 — The GStreamer `appsink` warning stays

Left as-is. It is one line of stderr on startup, from WebKit's media pipeline probing for
plugins that are not there; nothing in the app is degraded by it.

The investigation behind the decision is worth keeping, because it rules out the obvious fixes:

- **Disabling the media backend does not work.** The warning is emitted by WebKitWebProcess at
  0.001s, before any `WebKitSettings` property or runtime-feature setting reaches it over IPC.
  `enable-media`, the feature registry, and environment variables were each implemented,
  rebuilt and re-run; the warning survived all three. The changes were reverted, so no
  application source was touched.
- **The cause is our own bundling.** The AppImage ships GStreamer's shared libraries, which
  `libwebkit2gtk` links against, but not its plugins, which are `dlopen`ed and therefore
  invisible to the closure checker. Shipping the libraries is precisely what redirects
  GStreamer's plugin search away from the host's working copies. Bundling
  `gstreamer1.0-plugins-base` would address the cause, at the cost of size — available if the
  warning ever becomes worth removing.
- **Rejected:** pointing `GST_PLUGIN_SYSTEM_PATH` at the host's plugins. Clean on this machine,
  but it hardcodes Debian paths and reproduces the warning on any host without the plugins
  installed — a fix that looks like one without being one.

Related and still open: the closure checker is structurally blind to every `dlopen`ed
subsystem, not only GStreamer. Nothing else was investigated.

---

## R1 — CLOSED, 2026-08-05: the premise holds

The user ran the packaged AppImage with `--browser` against their own Home Assistant and
**retrieved data without problem**. A page served at `http://127.0.0.1:8137` opened a
WebSocket to their HA and its origin check accepted that origin.

This is the question the whole desktop direction rests on, and it was the last substantive
unknown. `--browser` serves the same origin and scheme as the native window, so the result
transfers to window mode; what it does not exercise is the WebKit renderer, which phase 4
covered separately.

Scope of the claim: verified against **one** HA instance, on one machine. Whether that HA was
reached over plain `http://` or `https://` was not recorded, so the specific plain-HTTP LAN
case in `20260805-ha-verification-procedure.md` may still be open. The origin question — the
part that could have invalidated the direction — is settled either way, since the page origin
is `http://127.0.0.1:<port>` regardless of how HA itself is served.

## A12 — Phase 4's self-containment claim was overstated, and the method is being fixed

The same user run failed in window mode: `libmanette-0.2.so.0`, a transitive dependency of
WebKit, is missing from the AppImage, so `libwebkit2gtk` fails to load and the typelib cannot
resolve `webkit_get_major_version`.

The significant part is not the missing library but that **phase 4's masked-namespace test
passed while this bug was present**. The `unshare -m` masking covered the webkit-specific
directories but evidently not the general library path, so the screenshot proved less than it
was presented as proving. A negative result from an incomplete isolation looks identical to a
genuine pass.

Being fixed by computing the full transitive closure at build time rather than maintaining a
hand-written library list, plus a static check that every `NEEDED` entry of every bundled
library resolves inside the AppDir. A static check needs no display, no container and no X
server, and would have caught this at build time.

---

## Open questions for the user

- **A3's `RuntimeError`** — keep for compatibility, or drop to tighten error surfacing?
- **U6's coverage gap** — is there a pytest marker separating the benchmarks, so a per-phase
  run can cover more than the targeted file?
- **Code signing** — deferred, but macOS is closer to required than optional if the audience is
  Dutch households: unsigned and quarantined will not open by double-click. USD 99/yr.
  Worth deciding before release rather than at it.
