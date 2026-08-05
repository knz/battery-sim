"""The Windows VERSIONINFO resource embedded in `battery-sim.exe`.

Main items:
    version_tuple()         "0.1.0" -> (0, 1, 0, 0), the 4-integer form Windows requires.
    product_version_string() the human-readable version, with the build SHA when there is one.
    render_version_info()   the VSVersionInfo literal PyInstaller's `version=` reads.
    write_version_info()    render + write `packaging/version_info.txt`.

This is the block Windows shows under a file's Properties → Details, and it is what makes an
executable identifiable once it has been downloaded and renamed. Without it the file reports no
publisher, no product and no version at all.

## Why the SHA is in the string block and not the numeric one

Windows carries TWO version representations, and they are not interchangeable:

    FILEVERSION / PRODUCTVERSION    four 16-bit INTEGERS. This is what the OS compares when it
                                    reasons about versions. It cannot hold a hex SHA, and there
                                    is no encoding trick worth attempting — a SHA is not
                                    ordered, and putting one where Windows expects a comparable
                                    number would produce meaningless comparisons.
    StringFileInfo                  free-text fields, shown to humans and never compared.

So the numeric tuple carries `(major, minor, patch, 0)` derived from `app.__version__`, and the
SHA rides in the `ProductVersion` STRING as `0.1.0+g1a2b3c4` — the `+`-suffix form from semver's
build-metadata rule, which is explicitly defined as not participating in precedence. A reader
gets the exact commit; the OS still gets a number it can order.

The fourth integer is 0 rather than a build counter: nothing in this project produces a
monotonic build number, and a field that is always 0 is more honest than one that restarts at 1
on every machine.

## Why this is generated rather than committed

PyInstaller's `version=` wants a file containing a `VSVersionInfo(...)` Python literal. Writing
that by hand would restate the version string a fourth time (after `app/__init__.py`,
pyproject.toml's dynamic lookup and `app.config.APP_VERSION`) in a file nothing validates —
precisely the drift `app/__init__.py` exists to prevent. Generating it means the resource cannot
disagree with the source.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = Path(__file__).resolve().parent / "version_info.txt"

# `app` is imported for its version rather than re-parsed, so this file has no second copy of the
# regex that reads it. The import is cheap: app/__init__.py holds only the version string.
sys.path.insert(0, str(ROOT))

from app import __version__  # noqa: E402
from app._build_info import BUILD_SHA  # noqa: E402

UNKNOWN = "unknown"

COMPANY_NAME = "Home Battery Simulator"
PRODUCT_NAME = "Home Battery Simulator"
FILE_DESCRIPTION = "Home Battery Simulator"
INTERNAL_NAME = "battery-sim"
ORIGINAL_FILENAME = "battery-sim.exe"

# GPL-3.0-or-later, per the LICENSE file at the repository root.
LEGAL_COPYRIGHT = "Licensed under the GNU General Public License v3.0 or later"

# 0x0409 = US English, 1200 = the UTF-16 codepage. This pair is the conventional default and is
# what the `040904B0` block name below encodes (`04B0` is 1200 in hex).
LANG_ID = 0x0409
CODEPAGE = 1200


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """Return the 4-integer Windows form of a `major.minor.patch` version string.

    Raises ValueError on anything that is not three dot-separated integers. That strictness is
    deliberate: a version this cannot parse means `app/__init__.py` has taken a form nobody
    considered here, and silently substituting zeroes would ship an executable claiming version
    0.0.0.0 while the release around it says otherwise.
    """
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(
            f"cannot express version {version!r} as a Windows version tuple; "
            "expected exactly major.minor.patch (three integers). "
            "Update packaging/battery_sim_version_info.py if the scheme has changed."
        )
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch, 0


def product_version_string(version: str, sha: str) -> str:
    """Return the human-readable product version, with build metadata when the SHA is known.

    `0.1.0+g1a2b3c4` when built from a known commit, plain `0.1.0` otherwise. The `g` prefix is
    git's own convention for "this is a git hash" (as in `git describe` output), which keeps the
    string self-describing.
    """
    if sha and sha != UNKNOWN:
        return f"{version}+g{sha}"
    return version


def render_version_info(version: str, sha: str) -> str:
    """Return the text of the VSVersionInfo file PyInstaller's `version=` parameter reads."""
    filevers = version_tuple(version)
    product_version = product_version_string(version, sha)

    return f'''# GENERATED by packaging/battery_sim_version_info.py — do not edit by hand.
#
# The Windows VERSIONINFO resource for battery-sim.exe. See the generator for why the numeric
# tuple below carries no SHA and the ProductVersion string does.
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers={filevers!r},
        prodvers={filevers!r},
        # 0x3f: all six FILEFLAGS bits are valid for masking. 0x0: none of them set — this is
        # not a debug, patched or prerelease build.
        mask=0x3F,
        flags=0x0,
        # 0x40004 = VOS_NT_WINDOWS32 (VOS_NT 0x40000 | VOS__WINDOWS32 0x4). 0x1 = VFT_APP, an
        # application rather than a DLL or a driver.
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "{LANG_ID:04X}{CODEPAGE:04X}",
                    [
                        StringStruct("CompanyName", {COMPANY_NAME!r}),
                        StringStruct("FileDescription", {FILE_DESCRIPTION!r}),
                        StringStruct("FileVersion", {version!r}),
                        StringStruct("InternalName", {INTERNAL_NAME!r}),
                        StringStruct("LegalCopyright", {LEGAL_COPYRIGHT!r}),
                        StringStruct("OriginalFilename", {ORIGINAL_FILENAME!r}),
                        StringStruct("ProductName", {PRODUCT_NAME!r}),
                        StringStruct("ProductVersion", {product_version!r}),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [{LANG_ID}, {CODEPAGE}])]),
    ],
)
'''


def write_version_info() -> Path:
    """Write `packaging/version_info.txt` from the current version and build SHA."""
    TARGET.write_text(render_version_info(__version__, BUILD_SHA), encoding="utf-8")
    return TARGET


def main() -> int:
    target = write_version_info()
    print(
        f"version info: {product_version_string(__version__, BUILD_SHA)} "
        f"{version_tuple(__version__)} -> {target.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
