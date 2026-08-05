#!/usr/bin/env bash
# Run the built AppImage on a machine that does NOT have the GTK/WebKit stack, and prove a native
# window opens. The runtime half of the self-containment guard; the static half is
# packaging/check-appdir-closure.py, which the build runs on every invocation.
#
# Usage:  packaging/verify-appimage-isolated.sh [path/to/.AppImage] [output-dir]
# Needs:  docker. Exits 0 only if a window titled "Home Battery Simulator" appears.
#
# ## Why a container and not `unshare -m` with tmpfs masks
#
# Phase 4 verified self-containment by masking three directories — girepository-1.0,
# webkit2gtk-4.1, python3/dist-packages — with tmpfs inside a mount namespace, and it produced a
# window and a screenshot. The image was, at that moment, missing ten shared libraries, including
# libmanette-0.2.so.0, without which libwebkit2gtk does not load at all. The check passed anyway,
# because all ten lived in /usr/lib/x86_64-linux-gnu itself, which was not masked. AppRun PREPENDS
# the AppDir to LD_LIBRARY_PATH rather than replacing it, so the host quietly supplied every one.
#
# The failure is structural, not a slip: masking a hand-written list of paths can only ever verify
# that list. It cannot detect a dependency nobody thought to mask, which is exactly the bug class it
# is meant to catch. A user found the bug instead. See changelog/20260805-desktop-packaging.md §15.
#
# A pristine ubuntu:24.04 has no such blind spot. Nothing is hidden; the libraries were never there.
# The container installs ONLY what an AppImage is entitled to expect from any host — an X server,
# and the X11/Wayland/EGL/GL client libraries, which are deliberately not bundled because they must
# match the user's display server and graphics driver. Everything the image is supposed to carry —
# gtk3, webkit2gtk, javascriptcore, manette, cairo, soup, python3-gi, the typelibs — is absent, and
# the script asserts that absence before it starts, so the test bed cannot silently drift into
# helping.
#
# Main items:
#   IMAGE_TAG     the throwaway container image built here.
#   the Dockerfile heredoc — what the host provides vs. what the AppImage must.
#   the in-container runner — Xvfb, launch, wait for a window, screenshot, report.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPIMAGE="${1:-$ROOT/dist/Home-Battery-Simulator-x86_64.AppImage}"
OUTDIR="${2:-$ROOT/dist/isolation-check}"
IMAGE_TAG="battery-sim-isolation-check:latest"

[ -f "$APPIMAGE" ] || { echo "FAIL: no AppImage at $APPIMAGE" >&2; exit 2; }
command -v docker >/dev/null || { echo "FAIL: docker is required" >&2; exit 2; }

APPIMAGE="$(readlink -f "$APPIMAGE")"
mkdir -p "$OUTDIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/Dockerfile" <<'DOCKERFILE'
FROM ubuntu:24.04
# Installed: what ANY Linux desktop already has and the AppImage therefore does not bundle —
# an X server to draw into, capture tools, dbus, tzdata, and the X11 / Wayland / EGL / GL client
# libraries, which must match the user's display server and graphics driver rather than the build
# machine's.
#
# NOT installed, deliberately: libgtk-3, libwebkit2gtk-4.1, libjavascriptcoregtk, libmanette,
# libcairo, libsoup, python3-gi, gir1.2-*. Those are the AppImage's own payload. If a window opens
# here, it opened on that payload and nothing else.
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb xdotool imagemagick dbus-x11 ca-certificates tzdata \
      libx11-6 libxext6 libxrender1 libxi6 libxfixes3 libxdamage1 libxcomposite1 \
      libxcursor1 libxrandr2 libxinerama1 libxcb1 libxcb-render0 libxcb-shm0 \
      libwayland-client0 libwayland-cursor0 libwayland-egl1 libwayland-server0 \
      libegl1 libgl1 libglx0 libgles2 libgbm1 libdrm2 libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*
DOCKERFILE

echo "==> building the isolation test bed"
docker build -q -t "$IMAGE_TAG" -f "$WORK/Dockerfile" "$WORK" >/dev/null

cat > "$WORK/run.sh" <<'RUNNER'
#!/bin/bash
# Inside the container.
set -u
export HOME=/root APPIMAGE_EXTRACT_AND_RUN=1

# The test bed must not be quietly providing the payload. If any of these turn up, the container
# has drifted and a pass would mean nothing.
leaked="$(ls /usr/lib/x86_64-linux-gnu/ 2>/dev/null \
    | grep -E 'libwebkit2gtk|libgtk-3|libjavascriptcoregtk|libmanette|libsoup-3' || true)"
if [ -n "$leaked" ]; then
    echo "FAIL: the test bed itself has parts of the stack: $leaked" >&2
    exit 3
fi
[ -d /usr/lib/python3/dist-packages/gi ] && { echo "FAIL: test bed has python3-gi" >&2; exit 3; }
[ -d /usr/lib/x86_64-linux-gnu/girepository-1.0 ] && { echo "FAIL: test bed has typelibs" >&2; exit 3; }

Xvfb :99 -screen 0 1400x1000x24 >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
sleep 3
export DISPLAY=:99

cd /tmp
setsid /work/app.AppImage --port 8137 >/tmp/app.log 2>&1 &
APP_PID=$!

# Wait for the window, or for the launcher to give up and say so.
found=""
for _ in $(seq 1 60); do
    if xdotool search --name "Home Battery Simulator" >/dev/null 2>&1; then found=yes; break; fi
    if grep -q "native window unavailable" /tmp/app.log 2>/dev/null; then break; fi
    kill -0 $APP_PID 2>/dev/null || break
    sleep 1
done
sleep 5   # let WebKit paint before the capture

echo "===== processes ====="
ps -eo pid,comm | grep -iE "battery|WebKit" || echo "(none)"
echo "===== windows ====="
xdotool search --name . getwindowname %@ 2>/dev/null || echo "(none)"
echo "===== log ====="
cat /tmp/app.log
import -window root /out/isolated-window.png 2>/dev/null && echo "===== screenshot written ====="

status=0
if [ -z "$found" ]; then
    echo "FAIL: no native window appeared on a host without the GTK/WebKit stack." >&2
    echo "The AppImage is not self-contained: check the log above for" >&2
    echo "'cannot open shared object file'." >&2
    status=1
elif grep -q "cannot open shared object file" /tmp/app.log; then
    # A window can still appear while a non-fatal library is missing. Not tolerated: it is the
    # same silent-degradation that hid the phase 4 bug.
    echo "FAIL: a bundled library failed to load:" >&2
    grep "cannot open shared object file" /tmp/app.log >&2
    status=1
else
    echo "PASS: native window on a host with no WebKit/GTK installed."
fi

kill -KILL -$APP_PID 2>/dev/null
kill -KILL $XVFB_PID 2>/dev/null
exit $status
RUNNER
chmod +x "$WORK/run.sh"
cp "$APPIMAGE" "$WORK/app.AppImage"

echo "==> running the AppImage with no WebKit/GTK on the machine"
docker run --rm \
    -v "$WORK:/work:ro" \
    -v "$OUTDIR:/out" \
    "$IMAGE_TAG" bash /work/run.sh
rc=$?

echo ""
echo "screenshot: $OUTDIR/isolated-window.png"
exit $rc
