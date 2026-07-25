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

Each locale gets its OWN Jinja environment, built once and never mutated afterwards (`env_for`).
The earlier design installed the request's catalog onto one shared environment just before
rendering, which raced under concurrent mixed-locale load; see `env_for` for why per-locale
environments remove the race rather than narrowing it.

Translation and interpolation are two separate steps (`newstyle=False` — see `install_for`), so a
literal "%" in a translatable string is inert. Strings with genuine placeholders use `%(name)s`
and the `interpolate` filter.

The view-models do not format sentences themselves; they emit `(msgid, params)` pairs built by
`msg()` / `msg_n()` here, which `templates/_msg.html` renders (translate, then interpolate). Those
two live in this module rather than in a view because several view modules build the pairs and
importing between them would be circular — see `msg`'s docstring.

Public API:
    SUPPORTED           the language codes the UI offers, in toggle order
    DEFAULT_LOCALE      the fallback code ('en')
    resolve_locale()    pick the code for a request (cookie/header/default)
    get_translations()  the gettext.NullTranslations for a code (cached)
    configure()         point the per-locale envs at a template dir + shared globals (once)
    env_for()           the ready-to-render Jinja environment for a locale (cached)
    interpolate()       substitute %(name)s into an already-translated string
    install_for()       install a code's catalog onto a Jinja environment
    msg() / msg_n()     a view-model message as a (msgid, params) pair; msg_n adds the plural
"""

from __future__ import annotations

import gettext
import re
from pathlib import Path

from babel import Locale, negotiate_locale
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request

LOCALE_DIR = Path(__file__).resolve().parent / "locales"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DOMAIN = "messages"

SUPPORTED = ("en", "nl")   # order is the header toggle order
DEFAULT_LOCALE = "en"
COOKIE_NAME = "lang"

# gettext.translations objects, cached by locale code. Built lazily on first use.
_catalogs: dict[str, gettext.NullTranslations] = {}

# One Jinja environment per locale, built lazily and then never mutated — see env_for(). The
# template directory and shared globals arrive via configure() at import time.
_envs: dict[str, Environment] = {}
_template_dir: Path | None = None
_globals: dict = {}


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


def env_for(code: str) -> "Environment":
    """Return the Jinja environment for a locale, built once per locale and cached.

    Replaces the previous pattern of installing the request's catalog onto a single module-level
    environment immediately before rendering. That mutation was not atomic with the render, and
    the sync routes run in a threadpool, so two concurrent requests in different languages could
    interleave install-A / install-B / render-A and serve one locale's catalog under the other's
    render.

    Building one environment per supported locale removes the race by removing the mutation:
    after startup nothing writes to an environment, so there is nothing for a concurrent request
    to observe half-done. There are only two locales, so the cache is two entries.

    The template *directory* and every filter/global must therefore be configured here rather
    than on a shared env — `configure()` is the single place that happens. It defaults to this
    package's own `templates/`, so importing i18n alone is enough to render: nothing depends on
    app/main.py having been imported first.
    """
    if code not in _envs:
        env = Environment(
            loader=FileSystemLoader(str(_template_dir or TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            extensions=["jinja2.ext.i18n"],
        )
        env.filters["interpolate"] = interpolate
        for name, value in _globals.items():
            env.globals[name] = value
        install_for(env, code)
        _envs[code] = env
    return _envs[code]


def configure(template_dir=None, **globals_) -> None:
    """Override the template directory and register shared globals for every locale environment.

    Optional: `env_for` already defaults to this package's `templates/`, so the app renders without
    calling this at all. It exists for the two cases that need it — pointing at a different
    template tree (tests), and registering a global or filter the templates need. Registration has
    to go through here because `env_for` builds each locale's environment from scratch, so a late
    `env.globals[...] = ...` on one of them would apply to that locale alone.

    Clears the environment cache, since anything already built predates the new configuration.
    """
    global _template_dir
    if template_dir is not None:
        _template_dir = template_dir
    _globals.update(globals_)
    _envs.clear()


def install_for(env, code: str) -> None:
    """Install a locale's gettext catalog onto a Jinja2 environment (has ext.i18n).

    `newstyle=False` is deliberate. Newstyle gettext runs printf substitution on the *result* of
    every `_()` call, which makes a literal "%" in any translatable string a live hazard: "50%
    saved" renders as "50{}aved" (the "% s" is eaten as a %s conversion), and "50%z" raises
    ValueError — a 500 on the page the user is reading. Both were reachable from any string
    carrying a percentage, and the previous guard was a convention (write the fullwidth "％")
    rather than anything the code enforced.

    With newstyle off, `_()` returns the translated string untouched and a literal "%" is just a
    character. Genuine interpolation goes through `interpolate()` below, which is explicit at the
    call site about which strings carry placeholders.
    """
    env.install_gettext_translations(get_translations(code), newstyle=False)


def interpolate(template: str, /, **values) -> str:
    """Substitute %(name)s placeholders into an already-translated string.

    The counterpart to `install_for`'s `newstyle=False`: translation and interpolation are two
    steps rather than one, so only strings that actually carry placeholders are ever %-formatted.

    Templates call it as `_('… %(kw)s …') | interpolate(kw=value)`; Python callers building a
    (msgid, params) pair hand both to the template and let it do the same.

    `template` may be a `str` or a `Markup`, and which one it is decides the escaping. `_msg.html`
    passes Markup (`… | e | interpolate(…) | safe`), because `Markup.__mod__` escapes each
    substituted value exactly once — so a raw data value is escaped and an already-escaped nested
    render is passed through. With a plain `str` the substitution does no escaping and the caller's
    surrounding `{{ }}` escapes the whole result, which is right for a single flat substitution but
    escapes a nested render twice. Nothing here needs to branch on it; `%` does the right thing for
    each type, and this note exists so the two call shapes are not "cleaned up" into one.

    The two error cases are deliberately asymmetric, because they are different failures:

    * A **missing** key raises `KeyError`. The string carries `%(kw)s` and nobody supplied `kw`,
      so the alternative is shipping a literal "%(kw)s" to the user. That is a bug in the calling
      code, it fails the same way in every locale, and it will be caught the first time the branch
      renders — so failing loudly is right.
    * A **surplus** key is ignored. It means a TRANSLATION dropped a placeholder the English msgid
      has: the sentence is still readable, just missing a figure, and only in that one language.
      Raising would turn a wording defect in one catalog into a 500 on a page the user is reading,
      while the same page works in English. Degrading is the better trade. The catalogs are the
      place to catch it — `tests/test_i18n.py` asserts placeholder parity across locales for the
      strings that carry them.

    **A literal "%" is inert here, as it is everywhere else.** Only `%(name)s` is a placeholder;
    every other "%" is doubled before substitution, so it survives as itself. Without that, this
    function would re-open exactly the trap `install_for`'s `newstyle=False` was introduced to
    close, but for the subset of strings that carry placeholders: "50% saved" would render as
    "50{}aved" and "50%z" would raise. That matters most for the *translations* — a Dutch string
    saying "50% lager" is ordinary copy a translator has no reason to think twice about, and the
    failure would be a 500 on a page that renders fine in English.
    """
    # `re.sub` returns a plain str even for a Markup input, which would silently discard the
    # escaping semantics the Markup call shape depends on (and with them, the escaping of every
    # substituted value — an XSS hole, not a cosmetic regression). Rebuild the original type.
    escaped = _PLACEHOLDER_SAFE_PERCENT.sub("%%", str(template))
    return type(template)(escaped) % values


# Matches a "%" that does NOT begin a "%(name)s" placeholder — i.e. every literal percent sign.
# Doubling these before substitution is what makes a literal "%" safe in a msgid and, more
# importantly, in a translator's msgstr.
#
# Note this deliberately does NOT exempt "%%". Since every literal "%" is now escaped for the
# caller, there is no escape sequence left for a translator to know about: "50%" is fifty percent
# and "50%%" is fifty percent-percent, which is what someone typing it would expect. Exempting
# "%%" would mean the one rule this module exists to delete ("remember to double your percent
# signs") survives for exactly the strings most likely to be edited by a non-programmer.
_PLACEHOLDER_SAFE_PERCENT = re.compile(r"%(?!\((\w+)\)s)")


def msg(msgid: str, /, **params) -> dict:
    """A translatable message as a (msgid, params) pair: `{"msgid": ..., "params": {...}}`.

    The shape every user-facing *sentence* a view-model emits now takes, and the reason it exists:
    a display string built at runtime with an f-string is a msgid that no `pybabel extract` run can
    see, so the template's `_()` around it matches no catalog entry and the string renders in
    English on a Dutch page. Splitting the constant text from the runtime values makes the msgid a
    compile-time literal again — extractable, translatable, and reorderable by the translator,
    which fragment concatenation cannot express.

    The template does the two steps in order: `_(m.msgid) | interpolate(**m.params)` — translate,
    then substitute (see `interpolate` below, and `install_for`'s `newstyle=False`). `params` is
    always present, `{}` when the msgid carries no placeholders, so the template needs no branch.
    `templates/_msg.html`'s `msg()` macro is the renderer; it also accepts a bare string.

    `plural`/`n` are set by `msg_n` for the counted case; see there.

    It lives HERE rather than in a view module because more than one view-model builds these pairs
    (`results_view`, `data_view`) and `results_view` already imports from `data_view`, so defining
    it in either one would make the other's import circular. `i18n` is the module both already
    depend on transitively and the module that owns the other half of the mechanism
    (`interpolate`). Both views import it under the private aliases `_msg` / `_msg_n`, which are
    the names `babel.cfg`'s `-k` keywords list.
    """
    return {"msgid": msgid, "params": params}


def msg_n(singular: str, plural: str, n: int, /, **params) -> dict:
    """A COUNTED translatable message: the ngettext counterpart of `msg`.

    Carries both English forms and the count, so the template can call
    `ngettext(m.msgid, m.plural, m.n) | interpolate(**m.params)`. Needed because a language picks
    its plural form from the number, and "1 intervals" is wrong in every language that has one.

    `n` is passed in `params` too under its own name by the caller when the sentence prints it, so
    the count reaching gettext and the count reaching the text cannot drift apart.
    """
    return {"msgid": singular, "plural": plural, "n": n, "params": params}


def language_name(code: str) -> str:
    """Human-readable endonym for a code, e.g. 'en' -> 'English', 'nl' -> 'Nederlands'."""
    try:
        return Locale.parse(code).get_display_name(code).capitalize()
    except Exception:
        return code.upper()
