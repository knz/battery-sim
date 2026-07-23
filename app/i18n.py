"""Internationalisation for the UI (English / Dutch).

The app is server-rendered (specs/08-architecture.md §5.1), so translation happens on the
server via gettext: templates call `_('...')`, and this module resolves the active locale per
request and installs the matching catalog on the Jinja environment before rendering.

Locale resolution precedence (see `resolve_locale`):
    1. an explicit `lang` cookie set by the header toggle,
    2. the browser's Accept-Language header,
    3. English as the fallback.

Translation catalogs live under app/locales/<lang>/LC_MESSAGES/messages.{po,mo}. The compiled
`.mo` files are committed, so running the app needs no extraction/compile step — only updating
translations does (README has the workflow). Catalogs are loaded once and cached here.

Public API:
    SUPPORTED           the language codes the UI offers, in toggle order
    DEFAULT_LOCALE      the fallback code ('en')
    resolve_locale()    pick the code for a request (cookie/header/default)
    get_translations()  the gettext.NullTranslations for a code (cached)
    install_for()       install a code's catalog onto a Jinja environment
"""

from __future__ import annotations

import gettext
from pathlib import Path

from babel import Locale, negotiate_locale
from starlette.requests import Request

LOCALE_DIR = Path(__file__).resolve().parent / "locales"
DOMAIN = "messages"

SUPPORTED = ("en", "nl")   # order is the header toggle order
DEFAULT_LOCALE = "en"
COOKIE_NAME = "lang"

# gettext.translations objects, cached by locale code. Built lazily on first use.
_catalogs: dict[str, gettext.NullTranslations] = {}


def get_translations(code: str) -> gettext.NullTranslations:
    """Return (and cache) the gettext catalog for a locale code.

    Falls back to an empty NullTranslations if the catalog is missing, so a not-yet-compiled
    language degrades to the source msgids (English) rather than crashing.
    """
    if code not in _catalogs:
        _catalogs[code] = gettext.translation(
            DOMAIN, localedir=str(LOCALE_DIR), languages=[code], fallback=True
        )
    return _catalogs[code]


def _accept_language_codes(header: str) -> list[str]:
    """Parse an Accept-Language header into an ordered list of base language codes.

    'nl-NL,nl;q=0.9,en;q=0.8' -> ['nl', 'nl', 'en']. Quality values only affect the order the
    browser already sends them in for our purposes, so we keep header order and let
    negotiate_locale pick the first supported one.
    """
    codes: list[str] = []
    for part in header.split(","):
        tag = part.split(";", 1)[0].strip()
        if not tag:
            continue
        base = tag.split("-", 1)[0].lower()
        codes.append(base)
    return codes


def resolve_locale(request: Request) -> str:
    """Pick the active locale for a request: cookie → Accept-Language → default."""
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie in SUPPORTED:
        return cookie

    header = request.headers.get("accept-language", "")
    if header:
        preferred = negotiate_locale(_accept_language_codes(header), SUPPORTED)
        if preferred:
            return preferred

    return DEFAULT_LOCALE


def install_for(env, code: str) -> None:
    """Install a locale's gettext catalog onto a Jinja2 environment (has ext.i18n)."""
    env.install_gettext_translations(get_translations(code), newstyle=True)


def language_name(code: str) -> str:
    """Human-readable endonym for a code, e.g. 'en' -> 'English', 'nl' -> 'Nederlands'."""
    try:
        return Locale.parse(code).get_display_name(code).capitalize()
    except Exception:
        return code.upper()
