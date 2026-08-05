# Windows packaging and release parameters

## Task Specification

Improve the packaging and release parameters for the Windows desktop target. The user's
starting premise was a recollection that "the release artifact is not an executable" on
Windows. Investigation (below) showed that premise to be partly wrong — an executable IS
produced — and the scope was then set from the real gaps, with per-item direction from the
user.

Work happens in the git worktree `.claude/worktrees/packaging-release-params` on branch
`worktree-packaging-release-params`.

### Scope, as directed by the user

1. **Icon** — use the `.ico` already committed in `packaging/`. IN SCOPE.
2. **Console window / fallback UX** — replace the stderr-only browser fallback with a native
   dialog showing the URL as copiable text plus an "open in browser" button. IN SCOPE.
3. **VERSIONINFO** — link the project version metadata into the Windows exe resource. IN SCOPE.
4. **Code signing** — explicitly OUT of scope; users are referred to documentation instead.
5. **Installer (MSI/NSIS/Inno)** — explicitly OUT of scope for now.
6. **Windows-on-ARM** — noted, no action.

## Findings from the investigation (before any code changes)

Established by reading the workflow, the spec, and the logs of the one real run — not assumed.

- **The premise was inaccurate in an important way.** `packaging/battery-sim.spec` has a normal
  `EXE(...)` block, so PyInstaller emits `battery-sim.exe` on Windows. The release attaches a
  ZIP of the onedir tree (`battery-sim.exe` + `_internal/`). It is a working executable, just
  not an installer and not something a Windows user recognises as a normal download.
- **The workflow header is out of date.** `.github/workflows/release.yml` says the non-Linux
  jobs "have never run". They have: `workflow_dispatch` run 31032747998 (2026-08-05) ran all
  three, and all three reported success. The Windows job took 57s.
- **The Windows build genuinely succeeds.** Log evidence from run 31032747998, job 92397267435:
  `Building EXE from EXE-00.toc completed successfully`, `Building COLLECT COLLECT-00.toc
  completed successfully`, artifact `bundle-windows-x86_64` uploaded at 33,556,296 bytes
  (~32 MiB). So this is a polish task, not a repair task.
- **pywebview IS collected on Windows.** `pywebview==6.2.1`, `pythonnet==3.1.0` and
  `clr-loader==0.3.1` install, and PyInstaller processes `hook-webview.py` and `hook-clr.py`.
  The native-window path is therefore live on Windows, not dead code.
- **Benign build warnings**, recorded so they are not rediscovered as new: `Hidden import
  "pycparser.lextab" not found`, `"pycparser.yacctab" not found`, `"tzdata" not found`.
- **A renderer subtlety that changes the design of item 2** (from pywebview docs, Context7):
  on Windows the renderer order is `edgechromium` → `mshtml`. WebView2 Runtime is required for
  edgechromium; when it is absent pywebview falls back to MSHTML (deprecated, IE-era) rather
  than raising. **Hypothesis, not yet verified:** on a Windows machine without WebView2, the
  app may open a window that renders badly instead of raising `WebViewException` and taking the
  fallback path. If so, a dialog attached only to the exception path would never appear on the
  machines that most need it. This needs verification on a real Windows host before the item 2
  design is fixed.

## High-Level Decisions

- D1. Treat this as polish on a working build, since the Windows job is green and produces a
  runnable exe. No repair work is warranted by current evidence.
- D2. Correct the stale "have never run" comment in the release workflow header as part of this
  work; a comment that misstates CI history misleads the next reader.

## Requirements Changes

- Initial user premise ("not an executable") revised after log evidence; scope re-derived from
  the six findings and confirmed item-by-item by the user.

## Files Modified

- `changelog/20260805-windows-packaging-release-params.md` — this file (created).

## Obstacles and Solutions

- Job-level "success" is uninformative while the matrix is `continue-on-error` — read the
  per-job conclusions and the build log instead of the run summary.

## Requirements Changes (round 2)

- **WebView2 detection: DEFERRED** by the user. The item-2 dialog is wired to the existing
  exception path only. The MSHTML-degradation hypothesis above remains unverified and is
  recorded as a follow-up, not a blocker.
- **`console=True`: UNCHANGED** for now. The user will test the resulting build before deciding.
  This keeps the launcher's stderr channel intact while the dialog is introduced.
- **NEW: build provenance.** Include the short commit SHA the artifact was built from — in the
  Windows VERSIONINFO resource, and in the equivalent version fields for the Linux and macOS
  builds.

## Findings for the SHA request

- `app/__init__.py::__version__` is a plain literal (`"0.1.0"`) with three readers: hatchling
  (via dynamic version in pyproject.toml), `app.config.APP_VERSION`, and the release
  version-gate. It has NO build-time component today.
- `APP_VERSION` has exactly one runtime consumer: `app/interest.py:57`, which sends
  `app_version` in the feature-interest POST body. A SHA added to that string would start
  flowing to that endpoint — a behavioural change, not just a packaging one.
- The Linux path stamps no version into the artifact at all. `packaging/build-appimage.sh:383`
  writes a `[Desktop Entry]` with `Name`/`Comment`/`Exec` and no version field; the AppImage
  FILENAME is versioned by the CI rename step (`release.yml:233`), not by the build.
- Consequence: for Linux/macOS there is no existing "version field" to extend — carrying a SHA
  there means introducing a field, not editing one.

## D3. Build provenance: generated module + native fields (option B, user-selected)

Chosen over "platform-native fields only" (option A) because A leaves macOS with nowhere to put
the SHA — macOS has no `BUNDLE(...)` block and therefore no `Info.plist` — and because a
provenance value the application itself cannot read is only half useful.

Design:

- `app/_build_info.py`, GENERATED at build time, holding the short SHA and a source marker.
  A committed default keeps a plain `git clone` + `python -m app` working, so the file is
  NOT gitignored; the build overwrites it and the working tree is restored afterwards. (An
  ignored, generated-only file would make a source checkout raise ImportError — worse than a
  stale default.)
- Resolution order: `GITHUB_SHA` (CI) → `git rev-parse --short HEAD` (local) → the literal
  `"unknown"`. A build from a tarball with neither git nor CI must still succeed, but must not
  claim a SHA it does not have.
- `__version__` is NOT touched. Two reasons, both concrete: the release version-gate compares
  the tag to it by exact string equality (`release.yml:127`), and `app/interest.py:57` sends
  it to a network endpoint. Provenance is a separate value.
- Windows: SHA into the VERSIONINFO STRING block (`ProductVersion` as text, e.g.
  `0.1.0+g1a2b3c4`). The numeric `FileVersion`/`ProductVersion` tuples stay `(0,1,0,0)` —
  they are 4 integers and cannot hold hex.
- Linux: `X-AppImage-Version` in the `[Desktop Entry]` written at `build-appimage.sh:383`.
- macOS: covered by the generated module only, until a bundle exists.

Note: neither `build-appimage.sh` nor `build-linux.sh` invokes git today, so the SHA lookup is
new plumbing in both.

## Files Modified (implementation)

- `packaging/battery-sim.spec` — `icon=` and Windows-only `version=` on `EXE(...)`; generates the
  version resource at spec-exec time; `tkinter` REMOVED from `EXCLUDES` (the fallback dialog
  needs it).
- `packaging/battery_sim_version_info.py` — NEW. Renders the VERSIONINFO resource from
  `app.__version__` + the build SHA.
- `packaging/build_info.py` — NEW. Resolves the SHA and writes `app/_build_info.py`.
- `app/_build_info.py` — NEW, committed with placeholder values.
- `app/desktop.py` — `_show_fallback_dialog()` added and wired into the webview exception path.
- `packaging/build-linux.sh` — stamps the SHA before PyInstaller; restores it on a trap.
- `packaging/build-appimage.sh` — `X-AppImage-Version` in the `.desktop` entry, read from the
  BUNDLE rather than the source tree.
- `.github/workflows/release.yml` — SHA stamp step on the desktop-bundle matrix; header comments
  corrected.
- `.gitignore` — `/packaging/version_info.txt`.
- `tests/test_desktop.py` — two existing fallback tests now patch the dialog; five new tests.
- `tests/test_packaging_metadata.py` — NEW, 21 tests over both generators.

## Obstacles and Solutions (implementation)

- Referenced `WINDOW_TITLE`; the constant is `_WINDOW_TITLE` — would have been a NameError on
  exactly the degraded path the dialog exists for. Fixed before any test ran.
- Wrote a `--print-version` fallback into build-appimage.sh for a flag that does not exist;
  removed rather than left as dead code that masks its own failure.
- The two existing fallback tests passed only because this machine has no tkinter. On a
  developer machine with Tk they would have opened a real window and blocked, violating the
  suite's own "no test opens a real window" rule. Both now patch `_show_fallback_dialog`.
- The restore trap silently did nothing on the first real build: `app/_build_info.py` was still
  untracked, so `git checkout --` failed and `|| true` swallowed it. Rewritten to test for
  TRACKED (`git ls-files --error-unmatch`) and to warn rather than swallow.
- **The AppImage would have shipped without its SHA, silently.** `build-appimage.sh` read
  `_internal/app/_build_info.py` as a file, but PyInstaller compiles imported modules into the
  PYZ archive and writes no such file — the lookup found nothing on every build and fell back to
  a version string with no SHA. Found by inspecting a real bundle, not by a failing test: nothing
  failed, the label was just quietly wrong. Fixed by ALSO collecting the module via the spec's
  DATAS list; the script now says so loudly when the path is absent, and
  `tests/test_packaged.py::test_the_build_info_module_is_readable_as_a_FILE_in_the_bundle`
  fails if the collection is ever removed (verified by deleting the file and watching it fail).
- PyInstaller's `versioninfo` module imports `win32api` and cannot be imported on Linux at all,
  so the rendered resource cannot be parse-validated off Windows. Tests assert its structure and
  compile it as a Python expression instead; full validation waits for a Windows run.

## Verification performed

- `packaging/build-linux.sh`: full build succeeded. Bundle **89MB against the 150MB ceiling** —
  so removing `tkinter` from EXCLUDES did not threaten the size gate (the earlier "roughly 10MB"
  figure in the spec comment was an estimate; 89MB is the measurement, with the pre-change
  baseline not separately recorded).
- PyInstaller logged `Ignoring icon; supported only on Windows and macOS!` on Linux, confirming
  the icon is correctly a no-op there rather than an error.
- `tests/test_desktop.py`: 63 passed. `tests/test_packaging_metadata.py`: 21 passed.
- `packaging/build_info.py` exercised on all three paths: CI (`GITHUB_SHA` truncated to 7),
  git (`c3ceef3`), and a non-repo directory (`unknown`, exit 0).
- **The stamp/restore cycle, end to end.** A build stamps `028361c` into the bundle while
  `git status` afterwards is clean and the source tree reads `"unknown"` again — the split the
  design depends on. The trap was also confirmed to have been broken before the file was
  tracked, which is what prompted rewriting it to warn instead of swallowing the failure.
- **A real AppImage**, built and inspected: the packaged `.desktop` entry carries
  `X-AppImage-Version=0.1.0+g028361c`, and appimagetool (which runs `desktop-file-validate`)
  accepted it.
- The packaged verification suites against that artifact: `tests/test_appimage.py`,
  `tests/test_packaged.py`, `tests/test_packaged_ingest.py` — 27 passed, no skips.
- Full suite: 1367 passed, 24 skipped.

## NOT verified (needs a Windows host)

- That the VERSIONINFO resource is accepted by the Windows resource compiler and shows the
  expected fields in file properties. Only its structure and syntax are checked here.
- That the icon is embedded and rendered correctly.
- The fallback dialog's appearance and behaviour — it has never been drawn on any platform, as
  this machine has no tkinter. Its logic is tested through injection only.
- Whether a WebView2-less Windows machine reaches the dialog at all (the MSHTML hypothesis).

## Current Status

Plan approved and implemented. All five items are done: icon, VERSIONINFO, build provenance
(option B), the fallback dialog, and the stale workflow comments. Tests pass and a full Linux
build succeeds.

Next steps, in no fixed order — these are options, not a decided sequence:

- **Get a Windows run.** `workflow_dispatch` on this branch would exercise the icon and the
  VERSIONINFO resource for the first time. This is the only way to close the "NOT verified" list
  above, and it is cheap (the Windows job took 57s).
- **Look at the dialog.** It needs a human on a Windows or macOS machine; nothing here can draw
  it. Its layout is a first attempt and will probably want adjusting.
- **Decide `console=False`.** Deferred by the user pending a look at the built result. The
  dialog now covers the case that made `console=True` load-bearing, so the two are linked.
- **The WebView2 question.** If a WebView2-less machine degrades to MSHTML instead of raising,
  the dialog never appears there and a positive check would be needed. Unverified hypothesis.
- **macOS remains untouched.** No `BUNDLE(...)`, so no `.app`, no icon, no `Info.plist` version.
  It gets the SHA only through the generated module.
