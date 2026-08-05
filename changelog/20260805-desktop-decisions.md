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

---

## Open questions for the user

- **A3's `RuntimeError`** — keep for compatibility, or drop to tighten error surfacing?
- **U6's coverage gap** — is there a pytest marker separating the benchmarks, so a per-phase
  run can cover more than the targeted file?
- **Code signing** — deferred, but macOS is closer to required than optional if the audience is
  Dutch households: unsigned and quarantined will not open by double-click. USD 99/yr.
  Worth deciding before release rather than at it.
