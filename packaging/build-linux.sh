#!/usr/bin/env bash
# Build the Linux desktop bundle: an isolated environment, PyInstaller onedir, and a size gate.
#
# Usage:  packaging/build-linux.sh [--keep-venv]
# Output: dist/battery-sim/battery-sim  (plus dist/battery-sim/_internal/)
#
# Main steps:
#   1. create a BUILD-ONLY virtualenv, separate from the repo's .venv;
#   2. install the runtime dependencies without the dev group, plus PyInstaller;
#   3. run `packaging/battery-sim.spec`;
#   4. FAIL if the resulting directory exceeds MAX_SIZE_MB.
#
# ## Why a separate virtualenv rather than `uv sync --no-dev` in place
#
# `uv sync --no-dev` against the repo's `.venv` would UNINSTALL playwright, pytest and httpx from
# the environment the developer is working in, and the next `uv run pytest` would fail until
# someone re-synced. The dev group must be absent from the BUILD, not from the developer's
# machine, so the build gets its own throwaway environment under $BUILD_VENV. PyInstaller is
# installed there too, which is also why it is not in `pyproject.toml`: it is a build tool, not a
# dependency of the application.
#
# The spec's `excludes` list names the dev packages as well. That is intentional redundancy —
# this script makes them absent, the exclude list makes them unbundlable if someone runs
# `pyinstaller` by hand against the dev venv.
#
# ## Why the size gate is here and not a comment in the spec
#
# The repository contains `external_data/` (~429MB of gitignored development input) and
# `node_modules/` (~48MB, Tailwind build-time only). Neither can reach the bundle through the
# spec as written, but a future `datas` entry with a wrong path — or a hook that decides to
# collect a package wholesale — would pull one of them in, and the only symptom would be a build
# that still works and a download that is fifty times too large. A hard ceiling turns that into a
# failed build. The app's own assets are ~9MB and a CPython + numpy + fastapi runtime is roughly
# 60-100MB, so 150MB leaves headroom without leaving room for a leak.

set -euo pipefail

MAX_SIZE_MB=150

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Outside the repo by default so a stray `uv sync` or a test collector never sees it. Override
# with BUILD_VENV=... to keep it somewhere inspectable.
BUILD_VENV="${BUILD_VENV:-${TMPDIR:-/tmp}/battery-sim-build-venv}"
DIST="$ROOT/dist/battery-sim"

KEEP_VENV=0
for arg in "$@"; do
    case "$arg" in
        --keep-venv) KEEP_VENV=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

command -v uv >/dev/null || { echo "uv is required to build" >&2; exit 1; }

echo "==> build environment: $BUILD_VENV"
if [ "$KEEP_VENV" -eq 0 ] || [ ! -d "$BUILD_VENV" ]; then
    rm -rf "$BUILD_VENV"
    uv venv --python 3.12 "$BUILD_VENV"
fi

# `--no-dev` semantics without touching the repo's .venv: install this project (which pulls in
# `[project.dependencies]` and nothing from `[dependency-groups]`) plus the build tool.
VIRTUAL_ENV="$BUILD_VENV" uv pip install --python "$BUILD_VENV/bin/python" -e "$ROOT" pyinstaller

echo "==> cleaning previous output"
rm -rf "$ROOT/build" "$DIST"

# Stamp the build's commit SHA into app/_build_info.py, which the spec reads (for the Windows
# VERSIONINFO) and the AppImage's .desktop entry reads (for X-AppImage-Version).
#
# This WRITES INTO THE SOURCE TREE, which is why the restore below is a trap and not a line at
# the end of the script: a build that fails partway must not leave a developer's checkout with a
# modified, committed file. The trap fires on error and on interrupt as well as on success.
#
# `git checkout --` restores the committed placeholder rather than the previous working-tree
# contents. That is the intended behaviour — the file's committed state IS the placeholder, and a
# developer who had edited it by hand is doing something the file's own docstring warns against.
# Outside a git checkout (a source tarball), the restore is skipped; there is nothing to restore
# to, and build_info.py will have written "unknown" there anyway.
echo "==> stamping the build SHA"
# The `git ls-files --error-unmatch` check asks whether the file is TRACKED, which is not the
# same question as whether this is a git checkout. An untracked copy — someone building from a
# tarball inside an unrelated repository, or before the file was first committed — cannot be
# restored by `git checkout` and would otherwise produce a confusing error from the trap.
# The warning is deliberate: a restore that silently does nothing leaves a stamped, committed
# file in the working tree, which is exactly the state this trap exists to prevent.
restore_build_info() {
    if ! git -C "$ROOT" ls-files --error-unmatch app/_build_info.py >/dev/null 2>&1; then
        echo "note: app/_build_info.py is not tracked by git; leaving it as the build wrote it" >&2
        return
    fi
    if ! git -C "$ROOT" checkout -- app/_build_info.py; then
        echo "WARNING: could not restore app/_build_info.py; it still carries the build SHA." >&2
    fi
}
trap restore_build_info EXIT INT TERM
"$BUILD_VENV/bin/python" "$ROOT/packaging/build_info.py"

echo "==> running PyInstaller"
# `--noconfirm` so a rebuild does not stop on a prompt; the spec supplies everything else.
(cd "$ROOT" && "$BUILD_VENV/bin/pyinstaller" --noconfirm --clean packaging/battery-sim.spec)

[ -x "$DIST/battery-sim" ] || { echo "FAIL: $DIST/battery-sim was not produced" >&2; exit 1; }

echo "==> size gate"
SIZE_KB="$(du -sk "$DIST" | cut -f1)"
SIZE_MB=$(( SIZE_KB / 1024 ))
echo "    bundle: ${SIZE_MB}MB (ceiling ${MAX_SIZE_MB}MB)"
if [ "$SIZE_MB" -gt "$MAX_SIZE_MB" ]; then
    echo "" >&2
    echo "FAIL: the bundle is ${SIZE_MB}MB, over the ${MAX_SIZE_MB}MB ceiling." >&2
    echo "This almost always means something large leaked into the bundle. The usual" >&2
    echo "suspects are external_data/ and node_modules/. The ten largest entries:" >&2
    du -sh "$DIST"/_internal/* 2>/dev/null | sort -rh | head -10 >&2
    exit 1
fi

# Cheap assertion that the four asset directories `app/desktop.py::check_assets` requires at
# startup actually landed. Failing here names the missing directory; failing at startup on a
# user's machine would too, but several hundred megabytes later.
echo "==> asset check"
for d in templates static locales data; do
    [ -d "$DIST/_internal/app/$d" ] || { echo "FAIL: missing _internal/app/$d" >&2; exit 1; }
done
[ -d "$DIST/_internal/babel/locale-data" ] || {
    echo "FAIL: babel locale data was not collected (Dutch formatting would fail at runtime)" >&2
    exit 1
}
# The CLDR set is trimmed to app/i18n.py::SUPPORTED by packaging/hooks/hook-babel.py. Assert the
# app's own languages survived it: a keep-set that dropped one produces UnknownLocaleError and a
# 500 on that language's pages, and nothing before this point would notice.
#
# The list is READ from app/i18n.py rather than written out here, so adding a language does not
# leave this check silently guarding the old set. `root` is appended because the app never names
# it but every locale inherits from it.
LOCALES="$("$BUILD_VENV/bin/python" -c "
import sys; sys.path.insert(0, '$ROOT')
from app.i18n import SUPPORTED, DEFAULT_LOCALE
print(' '.join(sorted({*SUPPORTED, DEFAULT_LOCALE, 'root'})))
")"
[ -n "$LOCALES" ] || { echo "FAIL: could not read SUPPORTED from app/i18n.py" >&2; exit 1; }
for d in $LOCALES; do
    [ -f "$DIST/_internal/babel/locale-data/$d.dat" ] || {
        echo "FAIL: babel/locale-data/$d.dat is missing — the CLDR trim was too aggressive." >&2
        echo "See packaging/battery_sim_babel_locales.py; the keep-set is derived from" >&2
        echo "app/i18n.py::SUPPORTED and must cover every language the app serves." >&2
        exit 1
    }
done
# `global.dat` lives OUTSIDE locale-data/ and holds the territory and parent_exceptions tables
# Locale.parse needs for ANY locale. A filter that caught it would break all of them at once.
[ -f "$DIST/_internal/babel/global.dat" ] || {
    echo "FAIL: babel/global.dat is missing — the locale-data filter caught too much" >&2
    exit 1
}

echo ""
echo "built: $DIST/battery-sim (${SIZE_MB}MB)"
echo "smoke: $DIST/battery-sim --no-browser --port 8137"
