# PyInstaller hook OVERRIDE for babel — trims the CLDR locale data to the app's languages.
#
# This file shadows PyInstaller's own bundled `hook-babel.py` by being first on `hookspath`
# (see `hookspath=[str(ROOT / "packaging" / "hooks")]` in `packaging/battery-sim.spec`).
#
# ## Why an override rather than a filter in the spec
#
# The bundled hook does an unconditional `datas = collect_data_files('babel')`, and a hook's datas
# are merged into the build independently of anything the spec's own `datas` list says. So
# filtering in the spec has no effect at all: every one of the 1083 `.dat` files still arrives via
# the hook. This was measured — a spec-side filter left the bundle at 32MB of locale data,
# unchanged. Overriding the hook is the only place the decision actually binds.
#
# The `hiddenimports` below are copied verbatim from the bundled hook and must stay: unpickling
# `locale-data/root.dat` needs classes from those four modules, and dropping them would turn this
# size optimisation into an import error.
#
# Main items:
#     datas          babel's data files, minus the locales the app cannot reach.
#     hiddenimports  the modules root.dat's unpickling requires (unchanged from the stock hook).

import os

from PyInstaller.utils.hooks import collect_data_files

from battery_sim_babel_locales import babel_locale_keep_set

KEEP = babel_locale_keep_set()


def _keep(entry) -> bool:
    """Whether one `collect_data_files("babel")` entry belongs in the bundle.

    Only `.dat` files directly under `locale-data/` are filtered. Everything else babel ships is
    kept untouched — `global.dat` in particular, which lives OUTSIDE `locale-data/` and carries
    the territory and `parent_exceptions` tables `Locale.parse` needs for any locale at all.
    `LICENSE.unicode` sits inside `locale-data/` and is kept for the obvious reason.
    """
    source, dest = entry[0], entry[1]
    if not dest.replace("\\", "/").rstrip("/").endswith("babel/locale-data"):
        return True
    name = os.path.basename(source)
    if not name.endswith(".dat"):
        return True
    return name[: -len(".dat")] in KEEP


datas = [entry for entry in collect_data_files("babel") if _keep(entry)]

hiddenimports = [
    "babel.dates",
    "babel.localedata",
    "babel.plural",
    "babel.numbers",
]
