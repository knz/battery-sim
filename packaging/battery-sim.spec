# PyInstaller spec for the Linux desktop build (phase 3 of desktop packaging).
#
# Run it through `packaging/build-linux.sh`, which creates the isolated build environment and
# enforces the size gate. `pyinstaller packaging/battery-sim.spec` on its own works too, but then
# nothing checks what ended up in the bundle.
#
# Main items:
#     ROOT                     the repository root, derived from this file rather than the CWD.
#     DATAS                    the asset directories, collected to their SOURCE-relative paths.
#     BABEL_LOCALE_KEEP        the CLDR locales to bundle (from packaging/battery_sim_babel_locales.py).
#                              The build aborts if it comes out degenerate.
#     HIDDENIMPORTS            modules uvicorn resolves by STRING, invisible to static analysis.
#     EXCLUDES                 dev-only and unused packages kept out of the bundle.
#     a / pyz / exe / coll     the standard PyInstaller Analysis → COLLECT onedir pipeline.
#
# Three decisions in here are load-bearing and are explained where they are made: the bundle is
# ONEDIR and not onefile (see `coll`), the asset directories are collected to paths that match
# the source tree exactly (see `DATAS`), and Babel's CLDR data is trimmed to the app's supported
# languages (see the Babel block below and `packaging/hooks/hook-babel.py`).

import sys
from pathlib import Path

# SPECPATH is set by PyInstaller to the directory holding this file. `__file__` is not reliable
# in a spec — PyInstaller `exec`s it — so the repo root is derived from SPECPATH instead.
PACKAGING_DIR = Path(SPECPATH).resolve()  # noqa: F821 - SPECPATH is injected by PyInstaller
ROOT = PACKAGING_DIR.parent

# `packaging/` on the path so this spec and `packaging/hooks/hook-babel.py` can share ONE copy of
# the keep-set derivation. The hook is imported by PyInstaller's own loader and cannot import from
# a spec, so the logic lives in a third module that both can reach.
sys.path.insert(0, str(PACKAGING_DIR))
from battery_sim_babel_locales import babel_locale_keep_set  # noqa: E402

# ── the Windows version resource ──────────────────────────────────────────────
#
# Generated HERE rather than committed, so the resource cannot disagree with `app.__version__`
# (see packaging/battery_sim_version_info.py for the full reasoning). It is written on every
# platform but referenced only by the `version=` argument below, which is None off Windows —
# generating it unconditionally keeps the code path exercised by a Linux build rather than
# leaving a Windows-only branch that nobody runs until release day.
#
# The build SHA it embeds comes from `app/_build_info.py`, which the packaging scripts refresh
# by running `packaging/build_info.py` first. A bare `pyinstaller` invocation skips that step and
# picks up whatever that file currently says — "unknown" in a clean checkout, which is correct
# for a build nobody stamped.
from battery_sim_version_info import LEGAL_COPYRIGHT, write_version_info  # noqa: E402

write_version_info()

# The app version, for the macOS bundle's Info.plist. Read from the same single source everything
# else uses — `app/__init__.py` — rather than restated here. `ROOT` is on sys.path via `pathex`
# below, but this import happens at spec-exec time and needs it explicitly.
sys.path.insert(0, str(ROOT))
from app import __version__  # noqa: E402

# The icon container each platform accepts. Linux gets one too, and PyInstaller discards it with
# a logged warning — harmless, and naming it here keeps the EXE() call free of a second
# conditional. Both files are rendered from packaging/icon/battery-sim.svg by that directory's
# render.py.
ICON_NAME = "battery-sim.icns" if sys.platform == "darwin" else "battery-sim.ico"

# The macOS bundle's user-facing name. It matches `_WINDOW_TITLE` in app/desktop.py and the
# `Name=` field the AppImage's .desktop entry carries, so the application is called the same
# thing in the Dock, in the window's title bar and in a Linux application menu. The EXECUTABLE
# inside the bundle stays `battery-sim` — that is what Contents/MacOS holds and what a terminal
# user types.
MACOS_APP_NAME = "Home Battery Simulator.app"

# Reverse-DNS, and STABLE: macOS keys per-app state (window positions, TCC privacy grants, the
# quarantine decision a user makes once) to this string, so changing it later makes the system
# treat the app as a different one and silently discards that state. Pick it once; do not tidy
# it up later.
#
# Derived from the repository host rather than a domain the project does not claim: pyproject.toml
# declares no homepage or author URL, so `github.com/knz/battery-sim` is the only identifier that
# is actually a fact about this project. If the project ever adopts its own domain, that is a
# reason to think about migration, not to silently rename this.
MACOS_BUNDLE_ID = "com.github.knz.battery-sim"

# ── the assets ────────────────────────────────────────────────────────────────
#
# Every one of these is found at runtime through `Path(__file__).resolve().parent`, from inside
# `app/` — `app.i18n` for templates and locales, the static mount in `app.main`, and the ENTSO-E
# source for `app/data`. Under PyInstaller, `app/__init__.py` lives at `<bundle>/_internal/app/`,
# so collecting each directory to the SAME relative path it has in the source tree makes those
# lookups resolve with no source change at all. `app/desktop.py::check_assets` asserts all four
# are present at startup, which is what turns a mis-specified entry here into a named startup
# error instead of a 500 on some page hours later.
DATAS = [
    (str(ROOT / "app" / "templates"), "app/templates"),
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / "app" / "locales"), "app/locales"),
    (str(ROOT / "app" / "data"), "app/data"),
    # `app/_build_info.py` is ALSO collected as data, in addition to being imported as a module.
    # The application reads it by importing it — that copy lives in the PYZ archive, compiled,
    # and is not a file anyone can look at. Packaging steps that run AFTER PyInstaller need to
    # read the SHA out of the finished bundle: `build-appimage.sh` puts it in the .desktop
    # entry's X-AppImage-Version, and it is the only way to ask "which commit is this bundle?"
    # of an artifact you have been handed.
    #
    # Measured, not assumed: the first version of this change had build-appimage.sh grep for
    # `_internal/app/_build_info.py`, and a real build produced no such file — the lookup found
    # nothing every time and silently fell back to a version string with no SHA in it.
    (str(ROOT / "app" / "_build_info.py"), "app"),
    # The third-party notices, at the top level of the bundle rather than under `app/` — nothing
    # in the application reads them, they are there for the person holding the artifact.
    #
    # These bundles carry the Python dependency set (section 2 of the notice), all of which is
    # permissive and therefore notice-only: MIT, BSD and Apache-2.0 each require the copyright
    # notice travel with the redistributed binary, which is what this collects. They do NOT carry
    # the LGPL GTK/WebKit stack — that is bundled only by the AppImage, whose own copy is made in
    # `packaging/build-appimage.sh` and which is where the `licenses/*.txt` texts matter.
    #
    # A missing entry here is not caught by `app/desktop.py::check_assets` (it asserts the four
    # asset directories above, not this file) and not caught by the notices CI gate, which
    # compares the document against its generator and knows nothing about packaging. So if this
    # line is removed, the omission is silent — the reason it is called out.
    (str(ROOT / "THIRD-PARTY-NOTICES.md"), "."),
]


# ── Babel's CLDR locale data, trimmed to the languages the app supports ───────
#
# The trim itself lives in `packaging/hooks/hook-babel.py`, which SHADOWS PyInstaller's bundled
# babel hook (that is what `hookspath` below is for). It has to be done there and not here: the
# stock hook does an unconditional `collect_data_files('babel')` and a hook's datas are merged
# independently of this list, so filtering `DATAS` leaves all 1083 files in place. Measured, not
# assumed — the first attempt filtered here and the bundle was byte-for-byte unchanged.
#
# What remains in the spec is the guard. It runs the same derivation the hook will run, so a
# broken keep-set stops the build here rather than producing a bundle that raises
# UnknownLocaleError on a user's machine.
BABEL_LOCALE_KEEP = babel_locale_keep_set()

if len(BABEL_LOCALE_KEEP) < 2:
    raise SystemExit(
        f"babel locale keep-set is degenerate ({sorted(BABEL_LOCALE_KEEP)}); refusing to build. "
        "Check that app/i18n.py still defines SUPPORTED."
    )

# Note that nothing is appended to DATAS for babel here, deliberately: the hook collects it, and a
# second `collect_data_files("babel")` at this level would re-add the very files the hook filtered
# out. Babel's `.dat` files are DATA rather than importable modules, so without a hook collecting
# them `Locale.parse("nl")` raises UnknownLocaleError — at runtime, in the packaged build only.

# ── the string-resolved imports ───────────────────────────────────────────────
#
# uvicorn stores its protocol implementations as import STRINGS and resolves them with
# `import_from_string` at Config time (`uvicorn/config.py`: WS_PROTOCOLS, HTTP_PROTOCOLS,
# LIFESPAN, and the loop-factory map). Nothing in the bytecode references these modules, so
# PyInstaller's static analysis cannot find them and the bundle would simply not contain them.
#
# `app/desktop.py` pins one value from each of those maps, and this list is the other half of
# that pin — the names below are the exact module halves of the strings uvicorn holds for
# ws="websockets-sansio", http="h11", loop="asyncio" and the default lifespan="auto".
#
# The WebSocket entry is the one with teeth. It is `websockets_sansio_impl`, NOT `websockets_impl`
# (uvicorn 0.51 deprecates the latter, which is why the launcher pins the sansio name). Getting
# this wrong breaks exactly one route — `WS /w/{id}/data/ingest/ws`, the Home Assistant ingest —
# while every HTTP test and every page stays green, so it is not a failure any ordinary check
# catches. `tests/test_packaged.py` opens a real ws:// against the built binary for that reason
# (it lives under tests/ so the ordinary pytest run collects and skips it rather than needing a
# separate command; it is gated on BATTERY_SIM_PACKAGED_BINARY).
HIDDENIMPORTS = [
    "uvicorn.protocols.websockets.websockets_sansio_impl",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    # The ASGI app itself. `app/desktop.py::_load_asgi_app` imports it inside a function, and
    # deliberately so (the data directory must be resolved first), which also hides it from the
    # module-level import graph.
    "app.main",
    # `optparse`, for PyGObject (phase 4). Nothing in the application imports it, so PyInstaller
    # does not collect it — but `packaging/build-appimage.sh` copies the SYSTEM `gi` package into
    # this bundle's `_internal/`, and `gi/_option.py` does `import optparse` at package import
    # time. Without it `import gi` raises ModuleNotFoundError, pywebview reports "GTK cannot be
    # loaded", and the launcher falls back to the browser — i.e. the AppImage silently loses the
    # native window it exists to provide. Measured: this was the second of two failures on the
    # first AppImage built here (the first being PYTHONPATH, which a frozen sys.path ignores).
    #
    # It is listed HERE and not in the AppImage script because hidden imports are a property of
    # the PyInstaller analysis, and the AppImage is assembled after PyInstaller has finished. The
    # cost to a non-AppImage bundle is one small stdlib module.
    "optparse",
]

# ── what stays out ────────────────────────────────────────────────────────────
#
# Two of these are correctness rather than size. `httptools` and `uvloop` are the implementations
# `ws`/`http`/`loop` would have probed for under "auto"; the launcher pins the pure-Python ones,
# so shipping the compiled alternatives would only add C extensions nothing loads.
#
# The dev group (playwright, pytest, httpx) is not installed in the build environment at all —
# `build-linux.sh` syncs without it — so those entries are belt-and-braces for anyone running
# `pyinstaller` directly against a dev venv.
#
# Not listed here, because they are not packages: `external_data/` (~429MB of gitignored dev
# input), `node_modules/` (~48MB, Tailwind build-time only), `tests/`, `specs/` and `changelog/`.
# None can reach the bundle, because the only paths PyInstaller copies are DATAS above plus what
# it traces from the entry script — but the size gate in `build-linux.sh` is what actually
# catches it if that ever stops being true.
EXCLUDES = [
    "playwright",
    "pytest",
    "_pytest",
    "httpx",
    "watchfiles",
    "uvloop",
    "httptools",
    "numpy.testing",
    "numpy.f2py",
]

# `tkinter` WAS excluded here and no longer is. `app/desktop.py::_show_fallback_dialog` uses it to
# show the app's URL when the native webview cannot open — the one moment when the user has no
# other way to reach the application, since stderr is invisible to a double-clicked bundle. An
# exclude would turn that dialog into the ImportError branch it already handles, silently, on
# exactly the machines it exists for.
#
# The cost is real but bounded, and MEASURED rather than estimated: the Windows release artifact
# went from 33,556,296 to 36,608,686 bytes across runs 31032747998 and 31036845955 — about 2.9MiB
# compressed. The Linux bundle stayed at 89MB against build-linux.sh's 150MB gate. If that gate
# ever fails after this change, the gate's limit is what to look at, not this decision.
#
# Un-excluding is NECESSARY BUT NOT SUFFICIENT, which cost this project a shipped feature.
# PyInstaller bundles only what it can import at build time, and the Linux job had no tkinter
# installed, so run 31094839305 logged "WARNING: tkinter installation is broken. It will be
# excluded from the application" and every AppImage before 2026-08-06 shipped without the dialog —
# silently, since the function's own ImportError branch is indistinguishable from the dialog being
# declined. The Linux size figure above was therefore measuring a bundle that never contained it.
#
# Fixed on two fronts: `python3-tk` in the release workflow's apt list, and a warning in
# build-linux.sh so a local build says so instead of producing a quietly lesser artifact. macOS
# and Windows were unaffected — their logs show hook-_tkinter and pyi_rth__tkinter with no warning.

a = Analysis(  # noqa: F821 - injected by PyInstaller
    [str(ROOT / "app" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDENIMPORTS,
    # `packaging/hooks/` FIRST, so its `hook-babel.py` shadows PyInstaller's bundled one and the
    # CLDR trim actually binds. Without this the stock hook collects all 1083 locales regardless
    # of anything in DATAS.
    hookspath=[str(PACKAGING_DIR / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821 - injected by PyInstaller

exe = EXE(  # noqa: F821 - injected by PyInstaller
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: the libraries live beside the executable, not inside it.
    name="battery-sim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX trades startup time for size and has a history of tripping AV heuristics.
    # False everywhere, as of 2026-08-06. A double-clicked desktop application does not open a
    # console window; one that does reads as a debug build. macOS was already False (a .app that
    # opens a Terminal beside itself on every Finder launch), and Windows followed.
    #
    # What replaced the console: `app/desktop.py::start_session_log` redirects stdout and stderr
    # into `<data_dir>/logs/session-<timestamp>.log` as soon as the data directory is resolved, on
    # every platform. The launcher's messages — the URL it is serving, the already-running notice,
    # the fallback reason — are preserved and are now in a file a bug report can attach, rather
    # than in a window that had to be open at the right moment. docs/en/troubleshooting.md is the
    # user-facing half of this.
    #
    # **This flag does nothing on Linux.** `console=` sets the PE subsystem on Windows and affects
    # the .app wrapper on macOS; PyInstaller ignores it for ELF. An AppImage launched from a file
    # manager has no terminal, and from a shell it inherits that shell's streams. So "the console
    # is off on all three platforms" is true in the sense that matters to a user, but it is the
    # log file, not this flag, that makes the three behave alike.
    #
    # PyInstaller's docs warn that windowed mode leaves `sys.stderr` as None (its CHANGES entry
    # ties this to matching `pythonw.exe`). That warning was Windows-scoped insurance while this
    # was True there; with the flip it describes a real shipping configuration.
    # `app/desktop.py::_ensure_std_streams` handles it and runs before any write.
    #
    # NOT verified on a real Windows machine at the time of the flip — accepted deliberately, on
    # the basis that output now reaches the log file regardless of whether a console exists.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows and macOS read this; PyInstaller ignores it on Linux, where the icon reaches the
    # user through the AppImage's .desktop entry instead (build-appimage.sh).
    #
    # The two platforms want different CONTAINER formats for the same artwork: Windows accepts
    # only `.ico`, macOS only `.icns`. Both are rendered from the one master SVG by
    # `packaging/icon/render.py`, so this is a packaging detail rather than two icons to keep in
    # step — edit `packaging/icon/battery-sim.svg` and re-run that script.
    icon=str(PACKAGING_DIR / ICON_NAME),
    # Windows-only, and None everywhere else. See packaging/battery_sim_version_info.py for why
    # the SHA lives in the string block rather than the numeric tuple.
    #
    # The `sys.platform` guard is belt-and-braces rather than strictly required: PyInstaller
    # clears `version` off Windows itself (building/api.py, "Ignoring version information;
    # supported only on Windows!"). Guarding here keeps that warning out of every Linux build,
    # where it would be noise the build script's output does not need. It also avoids handing
    # PyInstaller a path it would only discard — its versioninfo module imports `win32api` and
    # cannot even be imported on Linux, so the narrower the contact with it the better.
    version=str(PACKAGING_DIR / "version_info.txt") if sys.platform == "win32" else None,
)

# ONEDIR, and this is a decision rather than a default (changelog D6).
#
# `onefile` unpacks the whole bundle into a temporary directory on every launch and DELETES it on
# exit. `app/config.py` derives `_REPO_ROOT` from `Path(__file__).resolve().parent.parent` and
# `data_dir()` falls back to `_REPO_ROOT / "data"` — so under onefile the default data directory
# would land inside that temp directory and be destroyed with it, taking every workspace along.
# `app/config.py` carries a `sys.frozen` guard that redirects to the per-user location precisely
# to defend against this; onedir removes the trap instead of relying on the guard alone.
#
# The second reason is inspectability: with onedir, "what actually got bundled" is a directory
# anyone can list, which is how the size gate and the exclude list stay honest.
coll = COLLECT(  # noqa: F821 - injected by PyInstaller
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="battery-sim",
)

# ── the macOS .app bundle ─────────────────────────────────────────────────────
#
# Without this block the macOS build is a onedir DIRECTORY: runnable from a terminal, but not
# double-clickable, with no Dock icon and no Launchpad entry. BUNDLE wraps that same directory as
# `Home Battery Simulator.app` — `Contents/MacOS/battery-sim` is the very executable COLLECT just
# produced, so this adds a wrapper rather than changing what was built.
#
# **Bundling and SIGNING are independent.** This app is NOT signed with a Developer ID and is not
# notarized: `codesign_identity=None` on the EXE above, and CI logs `Code signing identity: None`.
# PyInstaller still applies an AD-HOC signature, which is what lets the binary execute at all on
# Apple silicon (arm64 macOS refuses completely unsigned binaries) — but Gatekeeper will still
# quarantine it when a browser downloads it. The documented `xattr -d com.apple.quarantine` /
# right-click-Open route is what users need, and that is a docs matter rather than a build one.
#
# Guarded on `sys.platform` because BUNDLE is a no-op elsewhere and evaluating it on Linux would
# add a confusing "no such file" for the .icns to every AppImage build.
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821 - injected by PyInstaller
        coll,
        name=MACOS_APP_NAME,
        icon=str(PACKAGING_DIR / "battery-sim.icns"),
        bundle_identifier=MACOS_BUNDLE_ID,
        # Shown in Finder's Get Info panel and by the App Store-style version readers. The build
        # SHA is deliberately NOT folded in here the way it is on Windows: CFBundleVersion and
        # CFBundleShortVersionString are specified as dot-separated NUMBERS, and Finder and
        # `softwareupdate` treat a non-conforming value as malformed rather than as free text.
        # The commit is still recoverable from the bundled app/_build_info.py.
        version=__version__,
        info_plist={
            # NSHighResolutionCapable: without it macOS runs the window through its 2x upscaler
            # and the whole UI looks blurry on any Retina display. It is a one-line difference
            # between "looks native" and "looks wrong" on essentially every modern Mac.
            "NSHighResolutionCapable": True,
            # LSBackgroundOnly=False and LSUIElement=False: this app owns a window and belongs in
            # the Dock and the app switcher. Stated rather than left to default because pywebview
            # creates its window from a process macOS would otherwise be entitled to treat as an
            # agent.
            "LSBackgroundOnly": False,
            "LSUIElement": False,
            # The two version strings Finder actually reads. Both are the plain version for the
            # reason given above.
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHumanReadableCopyright": LEGAL_COPYRIGHT,
        },
    )
