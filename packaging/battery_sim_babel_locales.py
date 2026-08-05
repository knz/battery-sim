"""Which Babel CLDR locales the packaged app needs — derived from `app/i18n.py::SUPPORTED`.

Imported by `packaging/hooks/hook-babel.py`, which is where the trim actually binds, and by
`packaging/battery-sim.spec` for the build-time sanity check. It lives in its own module rather
than inside either of them because a PyInstaller spec is `exec`'d and a hook is imported by
PyInstaller's own loader, so neither can import from the other.

## What this is for

Babel ships 1083 `.dat` files, about 32MB — by a wide margin the largest single thing in the
bundle — and this app can only ever use two of them.

Trimming is safe because an arbitrary `Accept-Language` never reaches `Locale.parse`.
`app/i18n.py::resolve_locale` returns a member of `SUPPORTED` or `DEFAULT_LOCALE` and nothing
else: a header of `de,fr` makes `negotiate_locale` return None and the app falls back to English.
So the set of locales the app can ask Babel about is precisely `SUPPORTED`, and everything else
is weight.

Main items:
    babel_locale_keep_set()  the bare locale names (no `.dat`) to bundle, `root` always included.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
"""The repository root — this file sits in `packaging/`."""


def babel_locale_keep_set() -> set[str]:
    """The CLDR locale names to bundle, as bare names without the `.dat` suffix.

    **Read out of `app/i18n.py`, never hardcoded.** Adding a language to `SUPPORTED` must not
    silently produce a bundle that cannot format it, and that is exactly what a literal
    `{"en", "nl", "root"}` would do — the symptom is a wrong NUMBER FORMAT rather than an error,
    visible only to someone reading the new language.

    `root` is always included: it is the top of Babel's inheritance chain, and
    `babel.localedata.load` merges it underneath every other locale, so dropping it breaks all of
    them at once rather than one.

    The parent chain is WALKED rather than assumed, mirroring `babel.localedata.load`: consult
    Babel's `parent_exceptions` table first, otherwise strip the last `_`-separated segment, and
    treat a name with no `_` as inheriting directly from root. For the bare codes this app uses
    today (`en`, `nl`) that terminates immediately, but writing it generally means a future
    `pt_BR` pulls in `pt`, and `en_GB` pulls in `en_001`, without anyone having to remember to.
    """
    from babel.core import get_global

    # `app` is importable from the repo root, which is not necessarily on the path: a hook runs
    # inside PyInstaller's own process, from whatever directory the build was started in.
    sys.path.insert(0, str(ROOT))
    try:
        from app.i18n import DEFAULT_LOCALE, SUPPORTED
    finally:
        sys.path.pop(0)

    parent_exceptions = get_global("parent_exceptions")

    keep = {"root"}
    for code in (*SUPPORTED, DEFAULT_LOCALE):
        name = str(code)
        while name and name != "root" and name not in keep:
            keep.add(name)
            parent = parent_exceptions.get(name)
            if not parent:
                parts = name.split("_")
                parent = "root" if len(parts) == 1 else "_".join(parts[:-1])
            name = parent
    return keep
