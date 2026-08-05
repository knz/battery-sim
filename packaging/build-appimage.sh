#!/usr/bin/env bash
# Build the Linux AppImage: the PyInstaller onedir bundle plus the GTK3 / WebKit2GTK stack,
# so a user gets a native window from one `chmod +x` file with nothing installed (phase 4).
#
# Usage:  packaging/build-appimage.sh
# Input:  dist/battery-sim/            (produced by packaging/build-linux.sh; built here if absent)
# Output: dist/Home-Battery-Simulator-x86_64.AppImage
#
# Main steps:
#   1. build (or reuse) the PyInstaller onedir bundle;
#   2. lay out an AppDir: the bundle under usr/, plus the GI stack collected from the host;
#   3. copy PyGObject, the girepository TYPELIBS, the GTK/WebKit shared libraries, the
#      gdk-pixbuf loaders and the GIO modules;
#   4. write AppRun, the .desktop file and the icon;
#   5. run appimagetool.
#
# ## The three things that make this different from an ordinary "copy the .so files" AppImage
#
# **Typelibs are data, and nothing collects them for you.** `gi.require_version('WebKit2','4.1')`
# reads `/usr/lib/x86_64-linux-gnu/girepository-1.0/WebKit2-4.1.typelib` — a binary blob, not a
# shared library and not a Python module. PyInstaller's analysis cannot see it and `ldd` will
# never name it. They are copied wholesale here and found at runtime through GI_TYPELIB_PATH,
# which AppRun sets. A missing typelib is a `ValueError: Namespace WebKit2 not available` at the
# moment the window is created, and nothing earlier notices.
#
# **WebKit2GTK is multi-process, and its helper path is COMPILED IN.** libwebkit2gtk-4.1 spawns
# `WebKitWebProcess` / `WebKitNetworkProcess` / `WebKitGPUProcess` and looks for them at the
# absolute path it was built with — `/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1` on Ubuntu. There is
# no WEBKIT_EXEC_PATH escape hatch (checked: the library's string table has
# WEBKIT_INJECTED_BUNDLE_PATH but no exec-path variable), so copying the helpers into the AppDir
# is NOT sufficient — the library keeps using the host's, and the AppImage then only works on a
# machine that already has WebKit2GTK, which defeats the purpose. This build therefore PATCHES the
# path inside the copied library and AppRun points a fixed symlink at the live mount. See the
# "repointing WebKit's helper path" step. The failure mode when it is wrong is a hard
# "Failed to spawn child process" at first page load.
#
# **A private D-Bus session.** WebKit2GTK's sandbox helper and GTK's GtkApplication both talk to
# the session bus. On a machine with no bus, or a stale one, `gtk.Application.run()` can return
# immediately without ever firing `activate`, and pywebview's `webview.start()` then returns with
# no window and no error. AppRun starts `dbus-run-session` when no usable bus is present. This was
# observed directly during phase 4 — see the changelog — and is the single most confusing failure
# in the stack, because it produces silence rather than a traceback.
#
# ## Portability
#
# This script builds against the HOST's glibc. The libraries it copies come from the machine it
# runs on, so the resulting AppImage runs on that glibc version or newer and NOT on anything
# older. Building in a container against an older glibc is the portable route and is not done
# here; see the changelog for the current status of that.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
BUNDLE="$DIST/battery-sim"
APPDIR="$DIST/AppDir"
ARCH_TRIPLET="x86_64-linux-gnu"
OUT="$DIST/Home-Battery-Simulator-x86_64.AppImage"

# appimagetool is fetched rather than vendored — it is a build tool and a large binary. Override
# with APPIMAGETOOL=/path/to/appimagetool if the machine has no network.
APPIMAGETOOL="${APPIMAGETOOL:-}"

SYS_LIB="/usr/lib/$ARCH_TRIPLET"
SYS_TYPELIB="$SYS_LIB/girepository-1.0"
# Debian/Ubuntu put PyGObject in the SYSTEM python's dist-packages, which is exactly why a uv
# virtualenv cannot see it. Overridable because other distributions put it elsewhere.
SYS_GI="${SYS_GI:-/usr/lib/python3/dist-packages/gi}"

# ── preconditions ─────────────────────────────────────────────────────────────

for d in "$SYS_TYPELIB" "$SYS_GI" "$SYS_LIB/webkit2gtk-4.1"; do
    [ -e "$d" ] || {
        echo "FAIL: $d is missing." >&2
        echo "Install: sudo apt install gir1.2-webkit2-4.1 python3-gi" >&2
        exit 1
    }
done

if [ ! -x "$BUNDLE/battery-sim" ]; then
    echo "==> onedir bundle absent; building it"
    "$ROOT/packaging/build-linux.sh"
fi

# ── AppDir layout ─────────────────────────────────────────────────────────────

echo "==> laying out $APPDIR"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/$ARCH_TRIPLET" "$APPDIR/usr/bin"

# The PyInstaller bundle, wholesale. `usr/bin/battery-sim` plus its `_internal/`.
cp -a "$BUNDLE" "$APPDIR/usr/bin/battery-sim-bundle"

# PyGObject, copied straight INTO the frozen bundle's `_internal/` rather than onto PYTHONPATH.
#
# That placement is the fix for a real failure, not a shortcut. PyInstaller's bootstrap REPLACES
# `sys.path` with the bundle's own entries; `PYTHONPATH` is not consulted for package resolution
# in a frozen process. An AppRun that exported PYTHONPATH and nothing else produced exactly the
# error this whole phase exists to remove — `ModuleNotFoundError: No module named 'gi'`, followed
# by the browser fallback — measured, on the first AppImage built here. `_internal/` IS on the
# frozen `sys.path`, so dropping the package there makes `import gi` resolve with no loader
# tricks and no runtime hook.
#
# The package is copied rather than pip-installed because the compiled `_gi` extension is built
# against a specific CPython ABI. The frozen interpreter's version and the system PyGObject's
# must agree, and a mismatch is an undefined-symbol error at import time — checked here so the
# build fails rather than the user's launch.
BUNDLE_PY_ABI="$(ls "$BUNDLE/_internal" | grep -oE 'python3\.[0-9]+' | head -1 || true)"
GI_ABI_TAG="$(ls "$SYS_GI"/_gi.cpython-*.so 2>/dev/null | grep -oE 'cpython-3[0-9]+' | head -1 || true)"
echo "    bundle interpreter: ${BUNDLE_PY_ABI:-unknown}   system gi: ${GI_ABI_TAG:-unknown}"
if [ -n "$BUNDLE_PY_ABI" ] && [ -n "$GI_ABI_TAG" ]; then
    want="cpython-3${BUNDLE_PY_ABI#python3.}"
    if [ "$GI_ABI_TAG" != "$want" ]; then
        echo "FAIL: the frozen interpreter is $BUNDLE_PY_ABI but the system PyGObject is built" >&2
        echo "for $GI_ABI_TAG. The compiled _gi extension would not import. Build the onedir" >&2
        echo "bundle with the same Python minor version as /usr/bin/python3." >&2
        exit 1
    fi
fi

GI_DEST="$APPDIR/usr/bin/battery-sim-bundle/_internal/gi"
cp -a "$SYS_GI" "$GI_DEST"
# `gi.overrides` (the Gtk/Gdk Python shims) comes along inside the package; nothing else of
# python3-gi is needed at runtime. The bytecode cache is stripped because it records absolute
# source paths from the build machine.
find "$GI_DEST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# The typelibs. All of them, not a hand-picked list: they are ~1MB total, and the dependency
# graph between them (WebKit2 → Soup, JavaScriptCore, Gtk → Gdk → GdkPixbuf → GObject → GLib …)
# is not worth encoding here when the whole directory costs less than one PNG.
cp -a "$SYS_TYPELIB" "$APPDIR/usr/lib/$ARCH_TRIPLET/girepository-1.0"

# WebKit's helper executables. Copied to the same relative location for tidiness, but note that
# the copy alone is NOT what makes them findable — see the patch step further down. This was
# measured: with the host's `/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1` masked, an AppImage that
# only copied the directory here died with
#   ERROR: Unable to spawn a new child process: Failed to spawn child process
#   "/usr/lib/x86_64-linux-gnu/WebKitNetworkProcess" (No such file or directory)
# i.e. it had been silently using the HOST's helpers all along.
cp -a "$SYS_LIB/webkit2gtk-4.1" "$APPDIR/usr/lib/$ARCH_TRIPLET/webkit2gtk-4.1"

# gdk-pixbuf loaders and the GIO modules. Both are dlopen()ed plugin directories, so ldd is blind
# to them; both are located by an environment variable AppRun sets.
if [ -d "$SYS_LIB/gdk-pixbuf-2.0" ]; then
    cp -a "$SYS_LIB/gdk-pixbuf-2.0" "$APPDIR/usr/lib/$ARCH_TRIPLET/gdk-pixbuf-2.0"
fi
if [ -d "$SYS_LIB/gio/modules" ]; then
    mkdir -p "$APPDIR/usr/lib/$ARCH_TRIPLET/gio"
    cp -a "$SYS_LIB/gio/modules" "$APPDIR/usr/lib/$ARCH_TRIPLET/gio/modules"
fi

# ── the shared libraries ──────────────────────────────────────────────────────
#
# Collected by walking `ldd` transitively from a set of roots: the GI extension, the WebKit and
# GTK libraries, every typelib's corresponding .so, and the plugin modules. `ldd` on each root and
# then on everything it names, to a fixed point.
#
# The EXCLUDE list is the important half. An AppImage that ships libc, libstdc++, libGL or the
# GLX/DRI stack breaks on the user's machine rather than helping: those must come from the host so
# they match the host's kernel, its graphics driver and its dynamic loader. This is the standard
# AppImage exclusion set, narrowed to what is actually loaded here.

echo "==> collecting shared libraries"

LIB_ROOTS=(
    "$SYS_GI"/_gi.cpython-*.so
    "$SYS_LIB/libwebkit2gtk-4.1.so.0"
    "$SYS_LIB/libjavascriptcoregtk-4.1.so.0"
    "$SYS_LIB/libgtk-3.so.0"
    "$SYS_LIB/libgdk-3.so.0"
    "$SYS_LIB/libgirepository-1.0.so.1"
)
# Every plugin module is a root too — they pull in libraries nothing else references.
while IFS= read -r m; do LIB_ROOTS+=("$m"); done < <(
    find "$SYS_LIB/gdk-pixbuf-2.0" "$SYS_LIB/gio/modules" "$SYS_LIB/webkit2gtk-4.1" \
         -name '*.so' 2>/dev/null || true
)

# Left to the host, deliberately. See the note above.
#
# **Every alternative must be followed by the `[.-]` boundary below.** The first version of this
# pattern was anchored on the left only, and `^libm` then matched `libmanette-0.2.so.0` (WebKit's
# gamepad dependency), `libmount.so.1` and `libmd.so.0`; `^libc` matched `libcairo.so.2` and
# `libcrypto.so.3`; `^librt` matched `librtmp.so.1`. Ten libraries the bundle genuinely needs were
# silently dropped. It was not caught for a whole phase because the build machine's own
# /usr/lib/x86_64-linux-gnu supplied them all — LD_LIBRARY_PATH is PREPENDED, not replaced — so the
# image worked everywhere it was tested and failed on the first machine that mattered.
# A SONAME is `<name>.so.<n>` or `<name>-<version>.so.<n>`, so `[.-]` is the boundary that
# separates the library name from everything after it. The closure check further down is the
# backstop that makes a mistake here fail the build instead of the user's launch.
EXCLUDE_RE='^(ld-linux|libc|libm|libdl|libpthread|librt|libresolv|libnsl|libutil|libstdc\+\+|libgcc_s|libGL|libGLX|libGLdispatch|libEGL|libgbm|libdrm|libX11|libX11-xcb|libxcb|libxcb-render|libxcb-shm|libXext|libXrender|libXi|libXfixes|libXdamage|libXcomposite|libXcursor|libXrandr|libXinerama|libxshmfence|libwayland|libwayland-client|libwayland-cursor|libwayland-egl|libwayland-server)[.-]'

collect() {
    local seen="$APPDIR/.seen"
    : > "$seen"
    local queue=("$@")
    while [ ${#queue[@]} -gt 0 ]; do
        local item="${queue[0]}"; queue=("${queue[@]:1}")
        [ -e "$item" ] || continue
        while IFS= read -r line; do
            local path
            path="$(awk '{for(i=1;i<=NF;i++) if($i=="=>") {print $(i+1); exit}}' <<<"$line")"
            [ -n "$path" ] && [ -f "$path" ] || continue
            local base; base="$(basename "$path")"
            [[ "$base" =~ $EXCLUDE_RE ]] && continue
            grep -qxF "$path" "$seen" && continue
            echo "$path" >> "$seen"
            queue+=("$path")
        done < <(ldd "$item" 2>/dev/null)
    done
    sort -u "$seen"
    rm -f "$seen"
}

mapfile -t LIBS < <(collect "${LIB_ROOTS[@]}")
echo "    ${#LIBS[@]} libraries"
for lib in "${LIBS[@]}"; do
    cp -Ln "$lib" "$APPDIR/usr/lib/$ARCH_TRIPLET/" 2>/dev/null || true
done
# The roots themselves (ldd does not list the object it is asked about).
for r in "${LIB_ROOTS[@]}"; do
    case "$r" in
        "$SYS_LIB"/*.so.*) cp -Ln "$r" "$APPDIR/usr/lib/$ARCH_TRIPLET/" 2>/dev/null || true ;;
    esac
done

# ── WebKit's compiled-in helper path ──────────────────────────────────────────
#
# WebKit2GTK runs its renderer, network and GPU work in SEPARATE PROCESSES, and it looks for those
# executables at an absolute path baked into libwebkit2gtk at build time — on Ubuntu,
# `/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1`. There is no environment variable to redirect it: the
# library's string table has WEBKIT_INJECTED_BUNDLE_PATH but nothing for the exec path (checked).
#
# So an AppImage that merely copies the helpers into its AppDir does not use them. It uses the
# HOST's, and therefore only works on a host that already has WebKit2GTK installed — which is the
# exact opposite of the point. This is not a theory: masking the host directory made an otherwise
# working AppImage die with "Failed to spawn child process … (No such file or directory)".
#
# The fix is to rewrite the two occurrences of that path inside the COPIED library. Both are
# NUL-terminated C strings in .rodata (verified by inspection), so a shorter replacement padded
# with NULs is safe and needs no relocation, no rebuild and no patchelf.
#
# The replacement is a fixed path in /tmp which AppRun creates as a SYMLINK to wherever the image
# happens to be mounted. It has to be indirect like this because the AppImage mount point is
# randomised per launch (`/tmp/.mount_XXXXXX`) and cannot be known at build time, while the
# patched string must be a compile-time CONSTANT — it cannot carry the UID, since WebKit uses it
# as a literal path with no expansion.
#
# **A shared name in /tmp is a known limitation of this approach, not an oversight.** On a
# multi-user machine the first user to launch owns the symlink and a second user's AppRun cannot
# replace it, so the second launch would be pointed at the first user's mount — which fails once
# that mount goes away. AppRun detects the case and refuses to repoint someone else's symlink
# rather than racing for it; the consequence is that the second user falls back to the browser
# instead of getting a window. Acceptable for a single-user desktop app and recorded so it is not
# rediscovered as a bug. The clean fix is a path under $XDG_RUNTIME_DIR, which is already
# per-user — but that path is not knowable at build time either, and it is longer than the 40-byte
# budget for a typical `/run/user/<uid>/…`. Left as a follow-up.
echo "==> repointing WebKit's helper path"
WEBKIT_LINK_PATH="/tmp/.battery-sim-webkit"   # 24 bytes; must stay <= 40 and match AppRun exactly
python3 - "$APPDIR/usr/lib/$ARCH_TRIPLET/libwebkit2gtk-4.1.so.0" "$WEBKIT_LINK_PATH" <<'PY'
import sys
from pathlib import Path

lib = Path(sys.argv[1]).resolve()
new = sys.argv[2].encode()
old = b"/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1"

if len(new) > len(old):
    raise SystemExit(f"replacement path is {len(new)}B, over the {len(old)}B budget")

data = bytearray(lib.read_bytes())
count = data.count(old)
if count == 0:
    raise SystemExit(f"{lib} does not contain {old.decode()} — has the layout changed?")

# NUL-padded to the original length, so every byte after the string keeps its offset. Anything
# that shifts offsets in a shared library would corrupt it.
data = bytearray(data.replace(old, new + b"\x00" * (len(old) - len(new))))
lib.write_bytes(bytes(data))
print(f"    patched {count} occurrence(s) -> {new.decode()}")
PY

# The GTK icon theme and the settings schemas. Without the compiled schema an application that
# reads a GSettings key aborts with "Settings schema org.gtk.Settings.* is not installed", which
# is a hard abort() rather than an exception.
if [ -d /usr/share/glib-2.0/schemas ]; then
    mkdir -p "$APPDIR/usr/share/glib-2.0"
    cp -a /usr/share/glib-2.0/schemas "$APPDIR/usr/share/glib-2.0/schemas"
fi
for theme in Adwaita hicolor; do
    if [ -d "/usr/share/icons/$theme" ]; then
        mkdir -p "$APPDIR/usr/share/icons"
        cp -a "/usr/share/icons/$theme" "$APPDIR/usr/share/icons/$theme"
    fi
done

# ── AppRun ────────────────────────────────────────────────────────────────────

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
# AppRun — the AppImage entry point. Points the GI/GTK/WebKit stack at the mounted AppDir and
# then execs the frozen launcher.
#
# Every variable set here corresponds to a lookup that would otherwise resolve against the HOST
# and find either the wrong version or nothing at all:
#
#   GI_TYPELIB_PATH        where `gi.require_version` reads the .typelib blobs. Nothing else
#                          finds them; they are data files with no link-time reference.
#   LD_LIBRARY_PATH        the bundled GTK/WebKit .so set. Prepended, not replaced, so the host
#                          still supplies libGL/libc, which the bundle deliberately omits.
#   GDK_PIXBUF_MODULE_FILE the loaders.cache. GTK dlopen()s image loaders through it; without it
#                          icons and any PNG/SVG in the UI silently fail to decode.
#   GIO_MODULE_DIR         the GIO extension modules (TLS via gnutls, proxy resolution). Missing
#                          them shows up as https:// fetches failing inside the webview only.
#   GSETTINGS_SCHEMA_DIR   the compiled schemas. A missing schema is an abort(), not an exception.
#   XDG_DATA_DIRS          icon theme lookup.
#
# WEBKIT_DISABLE_COMPOSITING_MODE is set because the bundled WebKit renders through the HOST's
# GL/EGL stack, which may be a different Mesa version than the one it was built against; the
# compositing path is the one that trips on that mismatch and it is not needed for a document UI.
set -euo pipefail

HERE="$(dirname "$(readlink -f "${0}")")"
LIBDIR="$HERE/usr/lib/x86_64-linux-gnu"

export GI_TYPELIB_PATH="$LIBDIR/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
export LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
# NOTE: no PYTHONPATH for `gi`. PyInstaller's bootstrap replaces sys.path, so PYTHONPATH does not
# reach package resolution in a frozen process; the `gi` package is copied into the bundle's own
# `_internal/` at build time instead. Setting it here would look like it worked and would not.

if [ -f "$LIBDIR/gdk-pixbuf-2.0/2.10.0/loaders.cache" ]; then
    export GDK_PIXBUF_MODULE_FILE="$LIBDIR/gdk-pixbuf-2.0/2.10.0/loaders.cache"
    export GDK_PIXBUF_MODULEDIR="$LIBDIR/gdk-pixbuf-2.0/2.10.0/loaders"
fi
[ -d "$LIBDIR/gio/modules" ] && export GIO_MODULE_DIR="$LIBDIR/gio/modules"
[ -d "$HERE/usr/share/glib-2.0/schemas" ] && \
    export GSETTINGS_SCHEMA_DIR="$HERE/usr/share/glib-2.0/schemas"
export XDG_DATA_DIRS="$HERE/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

export WEBKIT_DISABLE_COMPOSITING_MODE=1

# WebKit's helper processes. libwebkit2gtk was patched at build time to look for them at this
# fixed path instead of the compiled-in `/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1` — see the build
# script for why there is no environment variable that could do this. The indirection exists
# because the AppImage mount point is randomised per launch and the patched string has to be a
# constant, so the constant points at a symlink that AppRun repoints on every start.
#
# Without this the process dies at the moment the first page loads, with
# "Failed to spawn child process ... (No such file or directory)", on any machine that does not
# already have WebKit2GTK installed — i.e. exactly the machines this AppImage is for.
#
# The name is shared across users on one machine, which is a limitation rather than a design (see
# the build script). Only a symlink WE own is replaced: silently repointing another user's link
# would break their running instance, and racing for it would make which app works depend on who
# launched last. If it belongs to someone else this launch simply does not get a window and falls
# back to the browser, which is the failure the launcher already handles gracefully.
WEBKIT_LINK="/tmp/.battery-sim-webkit"
if [ ! -e "$WEBKIT_LINK" ] || { [ -L "$WEBKIT_LINK" ] && [ -O "$WEBKIT_LINK" ]; }; then
    ln -sfn "$LIBDIR/webkit2gtk-4.1" "$WEBKIT_LINK" 2>/dev/null || true
fi
export WEBKIT_INJECTED_BUNDLE_PATH="$LIBDIR/webkit2gtk-4.1/injected-bundle"

BIN="$HERE/usr/bin/battery-sim-bundle/battery-sim"

# A session bus, if the machine has none. GtkApplication registers on the session bus, and when
# registration cannot happen `Application.run()` can return WITHOUT firing `activate` — pywebview
# then returns from `webview.start()` with no window and no error at all. Observed directly
# during development. `dbus-run-session` is only used when there is no usable bus, so a normal
# desktop session keeps its own.
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v dbus-run-session >/dev/null 2>&1; then
    exec dbus-run-session -- "$BIN" "$@"
fi
exec "$BIN" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ── desktop entry and icon ────────────────────────────────────────────────────
#
# appimagetool requires both, at the AppDir root, with matching names.

# The version line carries the app version and, when it is known, the commit the bundle was
# built from — `0.1.0+g1a2b3c4`. `X-AppImage-Version` is the field appimagetool and the AppImage
# ecosystem read; the freedesktop `Version=` key means something else entirely (the spec version
# of the .desktop format itself), so writing the app's version there would be wrong.
#
# **Both values are read out of the BUNDLE, not the source tree.** That is deliberate. The
# bundle is what ships, `build-linux.sh` restores app/_build_info.py to its committed placeholder
# when it finishes, and this script does not rebuild when dist/battery-sim already exists — so
# the source tree may legitimately say "unknown" while the bundle carries a real SHA. Reading the
# bundle means the label describes the artifact rather than the checkout that happens to be
# around it.
# The version string comes from the source rather than the bundle: unlike the SHA it cannot
# drift (the release version-gate compares it against the tag) and the launcher has no
# --version flag to ask the bundle directly.
APP_VERSION="$(
    grep -oE '__version__ *= *"[^"]+"' "$ROOT/app/__init__.py" | grep -oE '"[^"]+"' | tr -d '"'
)"
# `_build_info.py` is collected as DATA by the spec precisely so it can be read here — the
# imported copy is compiled into the PYZ archive and is not a file. If this path is ever missing,
# that collection has been removed or renamed, and the message below is the thing that says so
# rather than a version string that quietly loses its SHA.
BUNDLED_BUILD_INFO="$BUNDLE/_internal/app/_build_info.py"
BUILD_SHA=""
if [ -f "$BUNDLED_BUILD_INFO" ]; then
    BUILD_SHA="$(
        grep -oE "BUILD_SHA *= *['\"][^'\"]+['\"]" "$BUNDLED_BUILD_INFO" |
            grep -oE "['\"][^'\"]+['\"]" | tr -d "'\"" || true
    )"
else
    echo "    note: $BUNDLED_BUILD_INFO is absent; the desktop entry will carry no commit SHA." >&2
    echo "          (the spec's DATAS list is what collects it — check that it still does)" >&2
fi

if [ -n "$BUILD_SHA" ] && [ "$BUILD_SHA" != "unknown" ]; then
    DESKTOP_VERSION="${APP_VERSION}+g${BUILD_SHA}"
else
    DESKTOP_VERSION="${APP_VERSION}"
fi
echo "    desktop entry version: $DESKTOP_VERSION"

cat > "$APPDIR/battery-sim.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Home Battery Simulator
Comment=What a home battery would have saved, on your own data
Exec=battery-sim
Icon=battery-sim
Categories=Utility;Science;
Terminal=false
X-AppImage-Version=${DESKTOP_VERSION}
DESKTOP

# The icon. `packaging/battery-sim.png` is committed and is what ships; it is RENDERED from the
# master `packaging/icon/battery-sim.svg` by `packaging/icon/render.py`, so edit the SVG and
# re-run that script rather than touching the PNG. The artwork is a placeholder — replacing it
# means replacing the SVG and re-rendering; nothing here changes.
#
# The inline generator below stays as a last resort: appimagetool refuses to build without an
# icon, and this keeps the build working if the PNG is ever missing from a checkout.
if [ -f "$ROOT/packaging/battery-sim.png" ]; then
    cp "$ROOT/packaging/battery-sim.png" "$APPDIR/battery-sim.png"
else
    python3 - "$APPDIR/battery-sim.png" <<'PY'
import struct, sys, zlib
# A 256x256 solid-green PNG, written by hand so the build needs no image library.
w = h = 256
raw = b"".join(b"\x00" + bytes((0x16, 0x6f, 0x3d)) * w for _ in range(h))
def chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
png = (b"\x89PNG\r\n\x1a\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(raw, 9))
       + chunk(b"IEND", b""))
open(sys.argv[1], "wb").write(png)
PY
fi

# ── build ─────────────────────────────────────────────────────────────────────

if [ -z "$APPIMAGETOOL" ]; then
    APPIMAGETOOL="$DIST/appimagetool.AppImage"
    if [ ! -x "$APPIMAGETOOL" ]; then
        echo "==> fetching appimagetool"
        curl -fsSL -o "$APPIMAGETOOL" \
            https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
        chmod +x "$APPIMAGETOOL"
    fi
fi

# ── the closure check ─────────────────────────────────────────────────────────
#
# Every NEEDED entry of every ELF file in the AppDir must resolve either INSIDE the AppDir or to a
# library on the host allowlist. Anything else means the image is incomplete and will fail on the
# user's machine — or, worse, will NOT fail on this one, because LD_LIBRARY_PATH is prepended and
# the build host quietly supplies the gap.
#
# This is the primary self-containment guard, and it replaced a runtime check that had passed while
# the image was broken. That check masked three named directories (girepository-1.0, webkit2gtk-4.1,
# python3/dist-packages) with tmpfs and ran the app under unshare; the ten libraries it was missing
# all lived in /usr/lib/x86_64-linux-gnu itself, which was not masked, so they resolved from the
# host and the window opened. A mask-a-list check verifies only that list — it cannot discover a
# dependency nobody thought of, which is the exact class of bug it is meant to catch.
#
# A static check has none of that failure mode: it enumerates from the ARTIFACT rather than from
# the author's list, needs no display, no X server and no container, and runs in about a second.
#
# Its limit, stated: it sees dynamic linkage only. Whatever is dlopen()ed by name at runtime — the
# gdk-pixbuf loaders, the GIO modules, the typelibs — has no NEEDED entry and is invisible here.
# Those are covered by the named assertions in tests/test_appimage.py.
echo "==> verifying the library closure"
python3 "$ROOT/packaging/check-appdir-closure.py" "$APPDIR"

echo "==> AppDir size: $(du -sh "$APPDIR" | cut -f1)"
echo "==> running appimagetool"
rm -f "$OUT"
# ARCH is not inferable from the AppDir alone; appimagetool asks for it explicitly.
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUT"

[ -f "$OUT" ] || { echo "FAIL: no AppImage produced" >&2; exit 1; }
chmod +x "$OUT"

echo ""
echo "built: $OUT ($(du -h "$OUT" | cut -f1))"
echo "run:   $OUT --no-browser --port 8137"
