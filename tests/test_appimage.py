"""Checks against the BUILT AppImage — the payload phase 4 adds on top of the PyInstaller bundle.

Skipped unless `BATTERY_SIM_APPIMAGE` points at the file `packaging/build-appimage.sh` produces:

    packaging/build-appimage.sh
    BATTERY_SIM_APPIMAGE=dist/Home-Battery-Simulator-x86_64.AppImage uv run pytest tests/test_appimage.py

Gated the same way and for the same reasons as `tests/test_packaged.py`: an ordinary run has no
AppImage to test, and building one takes minutes.

## What this file checks that `tests/test_packaged.py` cannot

`test_packaged.py` runs the binary and drives it over HTTP. Everything it covers — routes, assets,
locales, the WebSocket — is equally true of the plain onedir bundle, and it can all pass on an
AppImage whose GTK/WebKit payload is entirely missing, because `--no-browser` never touches the
renderer. That is exactly the outcome phase 4 exists to prevent, and it is not a hypothetical: the
first AppImage built here served every route correctly and still fell back to the browser.

So the checks below are about the payload and the environment, not about the app:

  * **the GObject typelibs are present.** They are DATA — no link-time reference, invisible to
    `ldd` and to PyInstaller's analysis — and `gi.require_version('WebKit2', '4.1')` reads them
    directly. A missing one is a `ValueError: Namespace WebKit2 not available` at the moment the
    window is created, and nothing before that notices.

  * **`gi` is INSIDE the frozen bundle's `_internal/`.** PyInstaller's bootstrap replaces
    `sys.path`, so an AppRun that put PyGObject on `PYTHONPATH` would have no effect at all. This
    happened; it produced `ModuleNotFoundError: No module named 'gi'` and a silent fall back to the
    browser. The assertion is on the LOCATION for that reason — "gi is somewhere in the AppDir" is
    not the property that matters.

  * **`optparse` is bundled.** `gi/_option.py` imports it at package-import time. Nothing in the
    application does, so PyInstaller does not collect it unless the spec names it. Its absence is
    the same silent browser fallback as above, one import deeper.

  * **WebKit's helper executables are present**, at the path libwebkit2gtk was compiled to look
    in. Without them the window opens WHITE and stays white: the UI process is fine and the web
    process never starts, which reads as an app bug rather than a packaging one.

  * **every bundled library's own dependencies are bundled too.** The one that reached a user: the
    phase 4 image was missing `libmanette-0.2.so.0` and nine others, because the build's exclusion
    pattern was anchored on the left only and `^libm` matched `libmanette`. It went unnoticed
    because AppRun PREPENDS to LD_LIBRARY_PATH, so the build machine's own /usr/lib supplied them
    all. See `test_the_library_closure_is_self_contained`.

  * **AppRun sets the environment variables** the stack resolves its data through.

Main items:
    APPIMAGE                the AppImage under test, or None when the gate is off.
    extracted               the AppDir, unpacked once per session via `--appimage-extract`.
    test_the_typelibs_are_bundled
    test_pygobject_is_inside_the_frozen_bundle
    test_optparse_is_bundled
    test_the_webkit_helper_processes_are_bundled
    test_the_library_closure_is_self_contained   every NEEDED entry resolves in the AppDir.
    test_apprun_exports_the_lookup_variables
    test_the_appimage_serves_over_http   the one end-to-end check, and its limits.
"""

import os
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

_ENV_APPIMAGE = "BATTERY_SIM_APPIMAGE"

_path = os.environ.get(_ENV_APPIMAGE)
APPIMAGE = Path(_path).resolve() if _path else None

pytestmark = pytest.mark.skipif(
    APPIMAGE is None,
    reason=f"set {_ENV_APPIMAGE} to the built AppImage to run the AppImage checks",
)

_ARCH_TRIPLET = "x86_64-linux-gnu"

_REQUIRED_TYPELIBS = (
    # The four the webview path names directly, plus the transitive ones a GTK window cannot
    # start without. Not the whole directory — the build copies all of it, but pinning the whole
    # list here would turn a harmless upstream addition into a test failure.
    "WebKit2-4.1",
    "JavaScriptCore-4.1",
    "Gtk-3.0",
    "Gdk-3.0",
    "Soup-3.0",
    "GLib-2.0",
    "GObject-2.0",
    "Gio-2.0",
    "GdkPixbuf-2.0",
    "Pango-1.0",
    "Atk-1.0",
    "cairo-1.0",
)


@pytest.fixture(scope="session")
def extracted(tmp_path_factory) -> Path:
    """The AppDir, unpacked with `--appimage-extract`. Session-scoped: it is ~300MB.

    Extraction rather than mounting, because mounting needs FUSE and a CI container often has
    none — and the properties under test are all about what is IN the image, which extraction
    answers just as well.
    """
    work = tmp_path_factory.mktemp("appdir")
    subprocess.run(
        [str(APPIMAGE), "--appimage-extract"],
        cwd=work,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    root = work / "squashfs-root"
    assert root.is_dir(), "--appimage-extract produced no squashfs-root"
    return root


def test_the_typelibs_are_bundled(extracted):
    """The fragile part of the whole phase — see the module docstring.

    Checked by NAME rather than by counting files, because "the directory is non-empty" is the
    shape of assertion that let a missing Dutch catalog through the phase-3 suite. A typelib set
    that is present but missing WebKit2 fails in exactly the way this test exists to catch.
    """
    typelib_dir = extracted / "usr" / "lib" / _ARCH_TRIPLET / "girepository-1.0"
    assert typelib_dir.is_dir(), f"no typelib directory at {typelib_dir}"

    present = {p.name.removesuffix(".typelib") for p in typelib_dir.glob("*.typelib")}
    missing = [name for name in _REQUIRED_TYPELIBS if name not in present]
    assert not missing, (
        f"typelibs missing from the AppImage: {missing}. "
        "gi.require_version() reads these directly; a missing one raises "
        "ValueError: Namespace ... not available when the window is created."
    )


def test_pygobject_is_inside_the_frozen_bundle(extracted):
    """`gi` must be on the FROZEN sys.path, which means inside `_internal/`.

    Asserting the location and not merely the presence, because the difference is the whole bug:
    a `gi` sitting elsewhere in the AppDir with `PYTHONPATH` pointing at it does nothing, since
    PyInstaller's bootstrap replaces `sys.path`. That configuration was built and measured here,
    and it fell back to the browser with `ModuleNotFoundError: No module named 'gi'`.
    """
    internal = extracted / "usr" / "bin" / "battery-sim-bundle" / "_internal"
    gi_dir = internal / "gi"
    assert gi_dir.is_dir(), (
        f"PyGObject is not at {gi_dir}. It must be inside the frozen bundle's _internal/ — "
        "PYTHONPATH does not reach package resolution in a PyInstaller process."
    )
    # The compiled extension, not just the Python half: `import gi` fails without it.
    assert list(gi_dir.glob("_gi.cpython-*.so")), "the compiled _gi extension is missing"
    assert (gi_dir / "overrides" / "Gtk.py").is_file(), "gi.overrides did not come along"


def test_optparse_is_bundled(extracted):
    """`gi/_option.py` imports it; the application does not, so the spec must name it.

    Cheap, and it guards a failure that is one import deeper than the one above and looks
    identical from the outside: pywebview reports "GTK cannot be loaded" and the launcher opens a
    browser instead of the window the AppImage exists to provide.
    """
    bundle = extracted / "usr" / "bin" / "battery-sim-bundle"
    internal = bundle / "_internal"

    # Where a pure-Python hidden import can legitimately land, in order of likelihood. Note the
    # EXECUTABLE: PyInstaller puts the PYZ archive inside the binary, and that is where `optparse`
    # actually is in this build — a check that only looked at `_internal/` reported it missing on
    # a bundle where it was present and working. Recorded because the wrong version of this test
    # was written first and its failure was indistinguishable from the real bug.
    if any(internal.glob("optparse.*")):
        return
    blz = internal / "base_library.zip"
    if blz.is_file():
        import zipfile

        with zipfile.ZipFile(blz) as z:
            if any(n.startswith("optparse.") for n in z.namelist()):
                return
    exe = bundle / "battery-sim"
    assert b"optparse" in exe.read_bytes(), (
        "optparse is not in the bundle (checked _internal/, base_library.zip and the PYZ inside "
        "the executable). gi/overrides/GLib.py does `from gi import _option`, which imports it, "
        "so `import gi` fails without it. It is a hiddenimport in packaging/battery-sim.spec."
    )


def test_the_webkit_helper_processes_are_bundled(extracted):
    """WebKit2GTK is multi-process and its helper path is compiled in, not configurable.

    There is no WEBKIT_EXEC_PATH — checked against the library's string table — so the AppDir has
    to reproduce the path libwebkit2gtk was built with. When the helpers are absent the window
    opens WHITE and stays white, which looks like an application bug and is a packaging one.
    """
    libexec = extracted / "usr" / "lib" / _ARCH_TRIPLET / "webkit2gtk-4.1"
    assert libexec.is_dir(), f"no WebKit helper directory at {libexec}"
    for helper in ("WebKitWebProcess", "WebKitNetworkProcess"):
        assert (libexec / helper).is_file(), f"{helper} is missing from the AppImage"
    assert (libexec / "injected-bundle" / "libwebkit2gtkinjectedbundle.so").is_file()


def test_the_webkit_and_gtk_libraries_are_bundled(extracted):
    """The renderer itself. Present so a stripped library set fails here and not on a user's box."""
    libdir = extracted / "usr" / "lib" / _ARCH_TRIPLET
    for lib in ("libwebkit2gtk-4.1.so.0", "libjavascriptcoregtk-4.1.so.0", "libgtk-3.so.0"):
        assert (libdir / lib).exists(), f"{lib} is missing from the AppImage"


def test_the_library_closure_is_self_contained(extracted):
    """Every NEEDED entry of every bundled ELF resolves in the AppDir or on the host allowlist.

    **This is the check that was missing, and its absence is what reached a user.** The phase 4
    image shipped without `libmanette-0.2.so.0` — a direct NEEDED entry of libwebkit2gtk, for
    gamepad support — along with nine others: libcairo, libcairo-gobject, libcap, libcom_err,
    libcurl-gnutls, libcrypto, libmd, libmount and librtmp. The build's exclusion pattern was
    anchored on the left only, so `^libm` matched `libmanette` as readily as `libm.so.6`.

    Nothing noticed for a whole phase, because `AppRun` PREPENDS the AppDir to LD_LIBRARY_PATH
    instead of replacing it: on the build machine every one of those libraries loaded from the
    host's /usr/lib and the window opened normally. The phase 4 self-containment check — the app
    under `unshare -m` with three named directories masked by tmpfs — passed for the same reason.
    The missing libraries were not in any of the three masked directories, so masking them changed
    nothing. A check that hides a hand-written list can only verify that list.

    This test enumerates from the ARTIFACT instead, so it has no such blind spot, and it shares its
    implementation with the build-time gate in `packaging/check-appdir-closure.py` — the build and
    the test cannot drift into disagreeing about what self-contained means.

    Its limit: dynamic linkage only. dlopen()ed plugins carry no NEEDED entry and are covered by
    the named assertions above instead.
    """
    import importlib.util

    checker = Path(__file__).resolve().parents[1] / "packaging" / "check-appdir-closure.py"
    assert checker.is_file(), f"the closure checker is missing at {checker}"

    # Loaded by path: the file is a build script with a hyphenated name, not an importable module.
    spec = importlib.util.spec_from_file_location("check_appdir_closure", checker)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    gaps = mod.check(extracted)
    by_soname: dict[str, list] = {}
    for elf, soname in gaps:
        by_soname.setdefault(soname, []).append(str(elf))

    assert not by_soname, (
        "libraries missing from the AppImage: "
        + ", ".join(f"{s} (needed by {by_soname[s][0]})" for s in sorted(by_soname))
        + ". These resolve from the host's /usr/lib on this machine because LD_LIBRARY_PATH is "
        "prepended, so the image can work here and still fail for a user — which is exactly what "
        "happened with libmanette-0.2.so.0 after phase 4."
    )


def test_apprun_exports_the_lookup_variables(extracted):
    """Every one of these corresponds to a lookup that would otherwise resolve against the host.

    Asserted on the AppRun text rather than by running it, because the failure this guards is an
    edit that drops a line — and most of the consequences (a missing GIO module, a missing pixbuf
    loader) are silent at startup and only appear on a page that needs them.

    PYTHONPATH is deliberately NOT in this list; see `test_pygobject_is_inside_the_frozen_bundle`.
    """
    apprun = (extracted / "AppRun").read_text(encoding="utf-8")
    for var in (
        "GI_TYPELIB_PATH",
        "LD_LIBRARY_PATH",
        "GDK_PIXBUF_MODULE_FILE",
        "GIO_MODULE_DIR",
        "GSETTINGS_SCHEMA_DIR",
        "XDG_DATA_DIRS",
    ):
        # `export VAR=` or the guarded `[ -d … ] && export VAR=` form, which several of these use
        # because the source directory may legitimately not exist on the build machine.
        assert re.search(rf"\bexport {var}=", apprun), f"AppRun no longer exports {var}"
    # The session bus. A GtkApplication whose registration cannot happen can return from run()
    # without ever firing `activate`, and pywebview then returns from start() with no window and
    # no error at all — the single most confusing failure in this stack. Observed during phase 4.
    assert "dbus-run-session" in apprun, "AppRun no longer provides a session bus fallback"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_appimage_serves_over_http(tmp_path):
    """The AppImage runs, from outside the repository, and serves.

    **Stated with its limit.** This uses `--no-browser`, so it does NOT exercise the window, the
    typelibs or WebKit at all — everything above is what covers those. What it adds is that the
    image itself launches (the runtime mounts or extracts, AppRun executes, the frozen binary
    starts) and that state lands in the per-user location rather than inside the read-only mount.

    `BATTERY_SIM_DATA_DIR` is removed and `XDG_DATA_HOME` redirected, the same combination
    `tests/test_packaged.py::packaged_server` uses and for the same reason: with the variable set,
    the `sys.frozen` branch of `app/config.py::data_dir` would never run.
    """
    port = _free_port()
    xdg = tmp_path / "xdg"
    xdg.mkdir()

    env = {k: v for k, v in os.environ.items() if k != "BATTERY_SIM_DATA_DIR"}
    env["XDG_DATA_HOME"] = str(xdg)

    proc = subprocess.Popen(
        [str(APPIMAGE), "--no-browser", "--port", str(port)],
        cwd=str(tmp_path),  # NOT the repository — a user runs this from anywhere.
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Longer than the onedir deadline: an AppImage mounts (or extracts) before it runs.
        deadline = time.time() + 40
        served = False
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"the AppImage exited early:\n{proc.stdout.read()}")
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
                    assert r.status == 200
                served = True
                break
            except Exception:
                time.sleep(0.3)
        assert served, "the AppImage did not answer within 40s"

        data_dir = xdg / "battery-sim"
        # `desktop.lock`, not `config.toml`. The latter was written by an import-time
        # `config.load()` that went with the feature-interest telemetry, leaving the app writing
        # no config file at all — so the old assertion tested for a file nothing produces.
        # `tests/test_packaged.py` moved to the lock for this reason; this test was missed.
        assert (data_dir / "desktop.lock").is_file(), (
            f"the AppImage did not write its state to {data_dir}"
        )

        # The assertion with teeth: state must land in the per-user directory and NOT inside the
        # AppImage mount, which is read-only. A pass above only shows a location was chosen.
        stray = list(APPIMAGE.parent.rglob("desktop.lock"))
        assert not stray, f"the AppImage wrote state into the bundle: {stray}"
    finally:
        # By this process's own handle. A pattern kill would be actively wrong: whoever runs these
        # tests very likely has their own copy of the app running on this machine.
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
