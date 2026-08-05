#!/usr/bin/env python3
"""Verify that an AppDir's shared-library closure is self-contained.

    packaging/check-appdir-closure.py dist/AppDir        # exits non-zero and lists the gaps

Run by `packaging/build-appimage.sh` before appimagetool, and by
`tests/test_appimage.py::test_the_library_closure_is_self_contained` against the extracted image.
Both use the SAME code, so the build and the test cannot disagree about what "self-contained" means.

## What it checks, and why this shape

Every ELF file in the AppDir is read for its DT_NEEDED entries. Each entry must resolve either to a
file inside the AppDir, or to a SONAME on HOST_PROVIDED below. Anything else is a gap: a library the
image links against and does not carry.

The check exists because the property is not observable at run time on the build machine.
`AppRun` PREPENDS the AppDir to LD_LIBRARY_PATH rather than replacing it, so a missing library is
silently satisfied by the host's own /usr/lib/x86_64-linux-gnu and the app works — on that machine.
Phase 4 shipped ten missing libraries this way, and a runtime self-containment check passed the
whole time, because that check masked three named subdirectories and the missing libraries were not
in them. See changelog/20260805-desktop-packaging.md §15.

A static check is not vulnerable to that. It enumerates from the artifact rather than from a
hand-written list of things to hide, so it cannot overlook a dependency nobody anticipated.

## What it does NOT check

Dynamic linkage only. Anything dlopen()ed by name — the gdk-pixbuf loaders, the GIO modules, the
GObject typelibs — carries no NEEDED entry and is invisible here. Those have their own named
assertions in tests/test_appimage.py. This file is one guard among several, not the whole of it.

Main items:
    HOST_PROVIDED   SONAME prefixes deliberately left to the host, with the reason for each group.
    is_host_provided(soname)
    needed_entries(path)    DT_NEEDED, read without pyelftools.
    check(appdir)           -> list of (elf_path, missing_soname), empty when self-contained.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Libraries the AppImage deliberately does NOT carry, because they must match the user's machine
# rather than the build machine:
#
#   the loader and the C runtime  — bundling these against a host with a different kernel or a
#                                   different glibc is how an AppImage breaks rather than helps;
#   the GL / EGL / DRI stack      — must match the user's graphics driver;
#   X11 and Wayland client libs   — must match the user's display server.
#
# Matched against a `[.-]` boundary, never as a bare prefix. A SONAME is `<name>.so.<n>` or
# `<name>-<version>.so.<n>`, so the boundary is what separates the name from the version. Without
# it `libm` matches `libmanette-0.2.so.0` — which is precisely the bug this file was written for.
HOST_PROVIDED = (
    # loader and C runtime
    "ld-linux-x86-64",
    "ld-linux",
    "libc",
    "libm",
    "libdl",
    "libpthread",
    "librt",
    "libresolv",
    "libnsl",
    "libutil",
    "libstdc++",
    "libgcc_s",
    # graphics
    "libGL",
    "libGLX",
    "libGLdispatch",
    "libEGL",
    "libgbm",
    "libdrm",
    # display server
    "libX11",
    "libX11-xcb",
    "libxcb",
    "libxcb-render",
    "libxcb-shm",
    "libXext",
    "libXrender",
    "libXi",
    "libXfixes",
    "libXdamage",
    "libXcomposite",
    "libXcursor",
    "libXrandr",
    "libXinerama",
    "libxshmfence",
    "libwayland",
    "libwayland-client",
    "libwayland-cursor",
    "libwayland-egl",
    "libwayland-server",
)

_HOST_RE = re.compile(
    "^(" + "|".join(re.escape(n) for n in HOST_PROVIDED) + r")[.-]"
)


def is_host_provided(soname: str) -> bool:
    """True when this SONAME is one the image intentionally leaves to the host."""
    return bool(_HOST_RE.match(soname))


_NEEDED_RE = re.compile(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]")


def needed_entries(path: Path) -> list[str]:
    """The DT_NEEDED SONAMEs of an ELF file, or [] if it is not an ELF.

    `readelf -d` rather than pyelftools, so the build has no Python dependency beyond the stdlib.
    A non-ELF file makes readelf fail, which is not an error here — the AppDir holds plenty of
    data files and this walks all of them.
    """
    try:
        out = subprocess.run(
            ["readelf", "-d", str(path)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return []
    return _NEEDED_RE.findall(out)


def _is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def check(appdir: Path) -> list[tuple[Path, str]]:
    """Every (elf, soname) pair the AppDir needs and neither carries nor delegates to the host.

    Resolution is by BASENAME across the whole AppDir, not by directory: the loader finds these
    through the LD_LIBRARY_PATH that AppRun sets, and a library sitting in the bundle's `_internal/`
    is as reachable as one in `usr/lib/`. Checking the exact directory would report false gaps.
    """
    appdir = Path(appdir)
    elves = [p for p in appdir.rglob("*") if p.is_file() and not p.is_symlink() and _is_elf(p)]
    # Symlinks count as present — the AppDir legitimately holds `libfoo.so.1 -> libfoo.so.1.2.3`.
    available = {p.name for p in appdir.rglob("*") if p.is_file() or p.is_symlink()}

    gaps: list[tuple[Path, str]] = []
    for elf in elves:
        for soname in needed_entries(elf):
            if soname in available or is_host_provided(soname):
                continue
            gaps.append((elf.relative_to(appdir), soname))
    return gaps


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <appdir>", file=sys.stderr)
        return 2
    appdir = Path(argv[1])
    if not appdir.is_dir():
        print(f"FAIL: {appdir} is not a directory", file=sys.stderr)
        return 2

    gaps = check(appdir)
    if not gaps:
        print("    library closure is self-contained")
        return 0

    # Grouped by the missing library rather than by the file that wants it: one absent SONAME
    # typically has many referrers, and the library is the thing to act on.
    by_soname: dict[str, list[Path]] = {}
    for elf, soname in gaps:
        by_soname.setdefault(soname, []).append(elf)

    print(
        f"FAIL: {len(by_soname)} librar{'y is' if len(by_soname) == 1 else 'ies are'} "
        f"missing from {appdir}:",
        file=sys.stderr,
    )
    for soname in sorted(by_soname):
        referrers = sorted(by_soname[soname])
        shown = ", ".join(str(p) for p in referrers[:3])
        more = f" (+{len(referrers) - 3} more)" if len(referrers) > 3 else ""
        print(f"  {soname}\n      needed by: {shown}{more}", file=sys.stderr)
    print(
        "\nThese are NEEDED entries that resolve neither inside the AppDir nor to a library on the\n"
        "host allowlist. On this machine they may still load from /usr/lib — LD_LIBRARY_PATH is\n"
        "prepended, not replaced — which is why the image can appear to work here and fail for a\n"
        "user. Either the collector's EXCLUDE_RE is dropping them (check it is anchored with the\n"
        "[.-] boundary) or they belong in HOST_PROVIDED in this file.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
