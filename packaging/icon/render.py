#!/usr/bin/env python3
"""Render the master icon SVG to every PNG the project ships.

This is a DEVELOPMENT-TIME script. Nothing at build time or run time imports it:
the PNGs it produces are committed, so `packaging/build-appimage.sh` and the web
app both work on a machine with no image toolchain at all. Run it only after
editing `packaging/icon/battery-sim.svg`, then commit the regenerated PNGs.

Outputs (all derived from the one SVG, never hand-edited):

  packaging/battery-sim.png    256x256  the AppImage icon. `build-appimage.sh`
                                        copies this path into the AppDir if it
                                        exists, so its presence is the whole
                                        Linux integration — no script change.
  packaging/battery-sim.icns            macOS bundle icon (CFBundleIconFile).
  packaging/battery-sim.ico             Windows executable / shortcut icon.
  app/static/favicon-32.png     32x32   browser-tab fallback for engines that
                                        do not take an SVG favicon.
  app/static/favicon-180.png   180x180  apple-touch-icon.
  app/static/favicon.svg               a byte copy of the master, served as the
                                        preferred favicon.

The macOS and Windows packaging does not exist yet; these two files are built
ahead of it so the artwork is not the thing blocking either port.

Renderer: cairosvg if importable, otherwise `rsvg-convert` or `inkscape` from
PATH. ImageMagick's `convert` is deliberately NOT used as a fallback: its
built-in MSVG renderer misplaces geometry in ways that are easy to miss, and
when it does delegate to rsvg we would rather call rsvg directly.

Pillow is required for the .icns and .ico containers, and ONLY for those — the
PNG targets need a renderer alone. Writing both formats with Pillow avoids
depending on `iconutil` (macOS-only, so the icns could not be built here) or on
`png2icns`/`icnsutils` (another system package). Every member image is rendered
from the SVG at its own size rather than downscaled from one raster, so each is
crisp at the size it will actually be shown.

Usage:  python3 packaging/icon/render.py [--check]

  --check  render to a temporary directory and compare against the committed
           outputs, exiting non-zero if they differ. For CI, to catch an SVG
           edit whose generated files were never regenerated.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "packaging" / "icon" / "battery-sim.svg"

# (destination relative to ROOT, pixel size). Square renders only.
TARGETS: list[tuple[str, int]] = [
    ("packaging/battery-sim.png", 256),
    ("app/static/favicon-32.png", 32),
    ("app/static/favicon-180.png", 180),
]

# The master is also served verbatim as the preferred favicon.
SVG_COPY = "app/static/favicon.svg"

ICNS_OUT = "packaging/battery-sim.icns"
ICO_OUT = "packaging/battery-sim.ico"

# Sizes embedded in the Windows .ico. 16-48 are the shell's list/detail/tile views;
# 256 is what Explorer's extra-large view and the Vista+ PNG-compressed entry use.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Pillow's ICNS writer derives the whole chunk set (ic07..ic14, 16px through
# 1024px retina) from a single 1024x1024 source, so one render is enough here.
ICNS_SIZE = 1024


def _render_cairosvg(svg: Path, out: Path, size: int) -> bool:
    try:
        import cairosvg  # type: ignore
    except ImportError:
        return False
    cairosvg.svg2png(
        url=str(svg), write_to=str(out), output_width=size, output_height=size
    )
    return True


def _render_rsvg(svg: Path, out: Path, size: int) -> bool:
    exe = shutil.which("rsvg-convert")
    if exe is None:
        return False
    subprocess.run(
        [exe, "-w", str(size), "-h", str(size), "-o", str(out), str(svg)],
        check=True,
    )
    return True


def _render_inkscape(svg: Path, out: Path, size: int) -> bool:
    exe = shutil.which("inkscape")
    if exe is None:
        return False
    subprocess.run(
        [
            exe,
            str(svg),
            f"--export-filename={out}",
            f"--export-width={size}",
            f"--export-height={size}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


RENDERERS = (_render_cairosvg, _render_rsvg, _render_inkscape)


def render(svg: Path, out: Path, size: int) -> None:
    """Render `svg` to `out` at size x size, trying each renderer in turn."""
    out.parent.mkdir(parents=True, exist_ok=True)
    for fn in RENDERERS:
        if fn(svg, out, size):
            return
    sys.exit(
        "no SVG renderer available. Install one of:\n"
        "  pip install cairosvg      (or: uv pip install cairosvg)\n"
        "  apt install librsvg2-bin  (provides rsvg-convert)\n"
        "  apt install inkscape"
    )


def _require_pillow():
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        sys.exit(
            "Pillow is required for the .icns and .ico containers. Install it with:\n"
            "  pip install pillow        (or: uv pip install pillow)\n"
            "The PNG targets do not need it."
        )
    return Image


def build_icns(svg: Path, out: Path, workdir: Path) -> None:
    """Write a macOS .icns from a single 1024px render of `svg`."""
    Image = _require_pillow()
    src = workdir / "icns-1024.png"
    render(svg, src, ICNS_SIZE)
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im.convert("RGBA").save(out, format="ICNS")


def build_ico(svg: Path, out: Path, workdir: Path) -> None:
    """Write a Windows .ico embedding every size in ICO_SIZES.

    Each member is rendered from the SVG at its own size and passed via
    `append_images`, rather than letting Pillow downscale one raster: at 16 and
    24px the difference between a fresh render and a downsample is visible.
    """
    Image = _require_pillow()
    out.parent.mkdir(parents=True, exist_ok=True)
    members = []
    for size in sorted(ICO_SIZES):
        png = workdir / f"ico-{size}.png"
        render(svg, png, size)
        members.append(Image.open(png).convert("RGBA"))
    try:
        # The largest is the base image; the rest ride along as append_images.
        base = members[-1]
        base.save(
            out,
            format="ICO",
            sizes=[(s, s) for s in sorted(ICO_SIZES)],
            append_images=members[:-1],
        )
    finally:
        for im in members:
            im.close()


def build_containers(svg: Path, icns: Path, ico: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        build_icns(svg, icns, work)
        build_ico(svg, ico, work)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify the committed PNGs match the SVG; do not write",
    )
    args = ap.parse_args()

    if not MASTER.is_file():
        sys.exit(f"master icon not found: {MASTER}")

    if args.check:
        stale: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            for rel, size in TARGETS:
                fresh = Path(tmp) / Path(rel).name
                render(MASTER, fresh, size)
                committed = ROOT / rel
                if not committed.is_file() or not filecmp.cmp(
                    fresh, committed, shallow=False
                ):
                    stale.append(rel)

            fresh_icns = Path(tmp) / "check.icns"
            fresh_ico = Path(tmp) / "check.ico"
            build_containers(MASTER, fresh_icns, fresh_ico)
            for rel, fresh in ((ICNS_OUT, fresh_icns), (ICO_OUT, fresh_ico)):
                committed = ROOT / rel
                if not committed.is_file() or not filecmp.cmp(
                    fresh, committed, shallow=False
                ):
                    stale.append(rel)

        if (ROOT / SVG_COPY).read_bytes() != MASTER.read_bytes():
            stale.append(SVG_COPY)
        if stale:
            print("stale, re-run packaging/icon/render.py:", file=sys.stderr)
            for rel in stale:
                print(f"  {rel}", file=sys.stderr)
            return 1
        print("icons up to date")
        return 0

    for rel, size in TARGETS:
        dest = ROOT / rel
        render(MASTER, dest, size)
        print(f"wrote {rel} ({size}x{size})")

    dest = ROOT / SVG_COPY
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MASTER, dest)
    print(f"wrote {SVG_COPY}")

    build_containers(MASTER, ROOT / ICNS_OUT, ROOT / ICO_OUT)
    print(f"wrote {ICNS_OUT} (up to {ICNS_SIZE}x{ICNS_SIZE})")
    print(f"wrote {ICO_OUT} ({', '.join(str(s) for s in sorted(ICO_SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
