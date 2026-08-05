"""Internationalisation for the UI (English / Dutch).

The app is server-rendered (docs/specs/08-architecture.md §5.1), so translation happens on the
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

**Nor do they format FIGURES** (A6). Dutch swaps both number separators against English — 3.924 kWh
and 0,094 €/kWh against 3,924 kWh and 0.094 €/kWh — and a view-model runs before the request's
locale is known, so a figure formatted there is a figure formatted in the wrong language. A
view-model emits `num(value, kind)`; `templates/_msg.html` formats it at render time through the
per-locale `numfmt` filter. `format_num` is the formatter and requires a locale, so no call site
can quietly leave one out; `num()` is the only locale-free spelling and it does not format. Month
names work the same way (`month_abbr`, the `monthname` filter). The conventions live in one table
(`_NUM_KINDS`), so "how the app writes a kWh figure" has a single definition.

Public API:
    SUPPORTED           the language codes the UI offers, in toggle order
    DEFAULT_LOCALE      the fallback code ('en')
    MINUS               U+2212, the app's minus glyph for every negative figure
    resolve_locale()    pick the code for a request (cookie/header/default)
    get_translations()  the gettext.NullTranslations for a code (cached)
    configure()         point the per-locale envs at a template dir + shared globals (once)
    env_for()           the ready-to-render Jinja environment for a locale (cached)
    interpolate()       substitute %(name)s into an already-translated string
    install_for()       install a code's catalog onto a Jinja environment
    msg() / msg_n()     a view-model message as a (msgid, params) pair; msg_n adds the plural
    num()               a view-model FIGURE as a (value, format-kind) pair, formatted at render
    format_num()        format such a figure in an explicit locale (the `numfmt` filter's body)
    month_abbr()        a calendar month's abbreviated name in a locale (the `monthname` filter)
"""

from __future__ import annotations

import gettext
import re
from pathlib import Path

from babel import Locale, negotiate_locale
from babel.numbers import format_decimal
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request

from . import features

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
        # `numfmt` is BOUND TO THIS LOCALE, which is the whole point of per-locale environments
        # doing double duty here: the template writes `{{ v | numfmt }}` with no locale argument,
        # and it cannot be rendered against the wrong one because there is no shared environment
        # to install a different locale onto (see this function's docstring). A view-model's
        # `num()` dict is locale-free until it reaches here.
        env.filters["numfmt"] = lambda m, _code=code: format_num(m["num"], m["fmt"], _code)
        env.filters["monthname"] = lambda m, _code=code: month_abbr(m, _code)
        env.globals["locale_code"] = code
        # The pending affordance's GitHub link (app/features.py). Registered here rather than
        # passed per-render because all three screens carrying the dialog would otherwise have
        # to thread the same locale-independent map through three separate view models.
        env.globals["feature_issue_url"] = features.issue_url
        env.globals["feature_keys"] = features.FEATURE_KEYS
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


# ── Locale-aware numbers (A6) ────────────────────────────────────────────────────────────────
#
# Dutch swaps both separators against English: 3,924 kWh is 3.924 kWh and 0.094 €/kWh is
# 0,094 €/kWh. Every figure used to be formatted with `f"{x:,.0f}"` while the view-model was being
# BUILT, which is before the locale is known — so the Dutch page showed English conventions.
#
# The fix mirrors what `msg()` did for sentences. A view-model emits the NUMBER and a format KIND
# (`num(3924.5, "kwh")`) and the rendering formats it, because rendering is where the locale is.
# The alternative — threading a `locale` argument down through `results_from` into each helper —
# was considered and rejected: it puts the display language into the signature of the module that
# runs the simulation, and nothing enforces it, so a new call site that forgets the argument
# reproduces exactly this defect while still compiling.
#
# The kinds are a closed table rather than a format string per call site, so "how the app writes a
# kWh figure" has one definition. `pattern` is a CLDR decimal pattern (babel localises the
# separators; the pattern only fixes the digit counts and grouping).
_NUM_KINDS: dict[str, dict] = {
    # kWh totals, whole numbers: "3,924 kWh" / "3.924 kWh".
    "kwh": {"pattern": "#,##0", "unit": "kWh"},
    # A kWh figure that MAY be negative and carries its sign explicitly (§7.2 item 9's saving).
    "kwh_signed": {"pattern": "#,##0", "unit": "kWh", "signed": True},
    # As "kwh" but with no unit suffix, for the KPI tile that renders its unit separately.
    "kwh_bare": {"pattern": "#,##0", "signed": True},
    # An integer percentage of a 0..1 fraction: "31%". No space, matching §2.3a's band.
    "pct": {"pattern": "#,##0", "scale": 100, "unit": "%", "space": ""},
    # A percentage of a 0..1 fraction to one or two decimals, unsigned and unspaced: "8.4%",
    # "0.04%" / "8,4%", "0,04%". For a share too small to survive rounding to a whole percent,
    # which would print "0%" and say nothing.
    "pct_dec1": {"pattern": "#,##0.0", "scale": 100, "unit": "%", "space": ""},
    "pct_dec2": {"pattern": "#,##0.00", "scale": 100, "unit": "%", "space": ""},
    # A signed percentage to one decimal: "+15.9 %" / "−34.2 %" (§2.4's tile's delta line).
    # `zero_unsigned`: a value rounding to 0.0 prints "0.0 %" with no sign, because a signed zero
    # asserts a direction the measurement does not have.
    "pct_signed": {"pattern": "#,##0.0", "unit": "%", "force_sign": True, "zero_unsigned": True},
    # €/kWh to 3 dp: "0.094 €/kWh" / "0,094 €/kWh".
    "eur_kwh": {"pattern": "#,##0.000", "unit": "€/kWh"},
    # ── EURO AMOUNTS (§2.4's cost section) ──────────────────────────────────────────────────
    #
    # A PREFIX, not a suffix: the wireframe writes "€ 1,153" and "− € 141", with the symbol
    # ahead of the digits and a space after it. Both en and nl put the euro sign first, so this
    # is one convention rather than a per-locale table; `prefix` is applied AFTER the sign so a
    # negative amount reads "− € 141" rather than "€ −141" — the wireframe's arrangement, and the
    # one that keeps a column of amounts aligned on the symbol.
    #
    # Whole euros, not cents. §2.4's tile shows "€ 331" and the waterfall "+ € 402"; a euro
    # figure carried to the cent would assert a precision the 2027 tariffs behind it do not have
    # (appendix A's terugleverkosten rate is an explicit placeholder).
    "eur": {"pattern": "#,##0", "prefix": "€"},
    # A euro amount that may be negative, carrying its sign: "€ 331" / "− € 331". The saving,
    # which §7.2 item 9 makes legitimately negative in euros as well as in kWh.
    "eur_signed": {"pattern": "#,##0", "prefix": "€", "signed": True},
    # An explicitly-signed euro amount: "+ € 402" / "− € 141". §2.4's waterfall, where every line
    # is a contribution to a saving and the sign is the whole point of the row. `zero_unsigned`
    # because a line whose euro value rounds to zero has no direction to state: "− € 0" reads as a
    # loss where the measurement is a few cents either way. In practice such a line does not reach
    # this formatter at all — `results_view.WATERFALL_DISPLAY_EPS_EUR` is tied to THIS pattern's
    # rounding (0.5, whole euros), so anything that would print "€ 0" is dropped from the display
    # first. `zero_unsigned` is the belt to that braces, and it is what keeps a KPI or a future
    # cents-precision row honest if the pattern here ever changes.
    "eur_force_signed": {
        "pattern": "#,##0", "prefix": "€", "force_sign": True, "zero_unsigned": True
    },
    # As "eur" but with no symbol, for the KPI tile that renders its own unit: "331" / "−331".
    "eur_bare": {"pattern": "#,##0", "signed": True},
    # A bare count with grouping and no unit: "8,760" / "8.760".
    "count": {"pattern": "#,##0"},
    # A bare number to one/two decimals, no unit — the per-day cycle rate and similar.
    "dec1": {"pattern": "#,##0.0"},
    "dec2": {"pattern": "#,##0.00"},
    # A number at its OWN natural precision, `%g`-style — a config value quoted back in a sentence
    # ("10 kWh usable, 0.95 round-trip"), where the precision was decided by whoever typed it and
    # imposing a second one here would undo the first. See `format_num`'s `general` branch: this
    # one cannot be a CLDR pattern, because a pattern fixes the digit count and that is precisely
    # what this kind must not do.
    "general": {"general": True},
    # A whole number carrying an explicit sign and no unit — the self-sufficiency tile's
    # percentage-POINT delta ("+10", "−3"), which is a count of points rather than a percentage.
    # No `zero_unsigned` here, deliberately: a zero-point change prints "+0 pp", matching what the
    # old `f"{pp:+d} pp"` produced. The two kinds differ on this because the old code did, and
    # changing either would change the English render.
    "dec0_signed": {"pattern": "#,##0", "force_sign": True},
}

# U+2212 MINUS SIGN. Babel emits the locale's own minus, which for both en and nl is ASCII "-";
# the app writes U+2212 throughout so one panel never shows two different minus glyphs. Applied
# after formatting rather than by patching the pattern, because it must also catch the sign babel
# puts on a negative number we did not explicitly sign.
MINUS = "−"


def num(value, kind: str = "count") -> dict:
    """A NUMBER a template will format in the render locale: `{"num": value, "fmt": kind}`.

    The numeric counterpart of `msg()`, and it exists for the same reason: a value formatted while
    the view-model is built is formatted before anyone knows what language the page is in. So the
    view-model hands out the number and the name of the convention, and `templates/_msg.html`
    formats it against the request's locale — including when it rides inside a `msg()` pair's
    params, which is where most figures live since 5a/5b.

    `kind` names an entry in `_NUM_KINDS` (kwh, kwh_signed, pct, pct_signed, eur_kwh, count, …), so
    the app has ONE definition of how it writes a kWh figure rather than one per call site. An
    unknown kind raises here, at the point the view-model is built, rather than rendering wrongly.

    A non-numeric `value` (None, or the raw string a not-yet-validated config can carry) passes
    through to `format_num`, which renders it as text rather than raising on a page the user is
    reading.
    """
    if kind not in _NUM_KINDS:
        raise KeyError(f"unknown number format kind {kind!r}; known: {sorted(_NUM_KINDS)}")
    return {"num": value, "fmt": kind}


def format_num(value, kind: str, locale: str) -> str:
    """Format a number per `kind` in `locale`. The render-time half of `num()`.

    Also the direct entry point for tests and for the few places that hold a locale already, which
    is why it takes the locale as a REQUIRED argument: there is no way to call a formatter here
    without saying which language it is for, and therefore no way to leave a site accidentally
    English. `num()` is the only locale-free spelling and it does not format.

    Negative numbers come back with U+2212, not ASCII "-" (see `MINUS`).

    Three sign behaviours, each because a call site needs it:

    * plain — babel's own sign, with its ASCII "-" swapped for U+2212.
    * `signed` — the MAGNITUDE is formatted and the minus prepended, so a value between −0.5 and 0
      prints "0 kWh" rather than "−0 kWh". A signed zero is a formatting artefact, not a
      measurement, and it reads as a bug.
    * `force_sign` — as `signed`, and a non-negative value gets a "+". `zero_unsigned` then decides
      whether a value that ROUNDS to zero keeps its sign: the percentage delta drops it ("0.0 %"),
      the percentage-point delta keeps it ("+0"). Both match what the f-strings they replace did.

    Zero-ness is asked of the ROUNDED TEXT, not of the input, because that is what the reader sees:
    −0.04 renders "0.0" and must not carry a minus, while −0.06 renders "0.1" and must.
    """
    spec = _NUM_KINDS[kind]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        # Not a number: show it as it came (None → "—", matching the old defensive formatters).
        return "—" if value is None else str(value)

    scaled = value * spec.get("scale", 1)
    if spec.get("general"):
        # `%g` picks the digits; only the SEPARATORS are localised. Handing the value to babel
        # directly would not do: babel groups thousands where `%g` does not ("1,234.5" vs
        # "1234.5") and expands an exponent to twenty zeroes where `%g` writes "1e+20". Both are
        # arguably nicer, and both would change the English render, which this step may not do.
        # So `%g` decides the text and this swaps in the locale's decimal separator.
        # Only a LEADING "-" is the number's sign; a "-" after an "e" belongs to the exponent and
        # must stay ASCII ("1e-07", not "1e−07"). These are panel-② config values quoted back to
        # the user, so an exponent is unusual but reachable for a very small entry.
        text = f"{scaled:g}"
        text = MINUS + text[1:] if text.startswith("-") else text
        point = format_decimal(1.5, locale=locale)[1]
        return text.replace(".", point) + (
            spec.get("space", " ") + spec["unit"] if spec.get("unit") else ""
        )
    # A currency SYMBOL sits ahead of the digits and behind the sign: "− € 141", not "€ −141"
    # and not "−€ 141". Inserted here rather than by prepending to the finished text so that the
    # sign logic below stays the one place a sign is decided; each branch attaches its sign to
    # `prefixed(text)` and the arrangement is stated once.
    prefix = spec.get("prefix")

    def prefixed(digits: str) -> str:
        return f"{prefix} {digits}" if prefix else digits

    if spec.get("signed") or spec.get("force_sign"):
        text = format_decimal(abs(scaled), format=spec["pattern"], locale=locale)
        rounds_to_zero = not any(ch.isdigit() and ch != "0" for ch in text)
        unsigned = rounds_to_zero and (spec.get("zero_unsigned") or not spec.get("force_sign"))
        text = prefixed(text)
        if unsigned:
            pass
        elif scaled < 0:
            text = MINUS + " " + text if prefix else MINUS + text
        elif spec.get("force_sign"):
            text = "+ " + text if prefix else "+" + text
    else:
        # Format the MAGNITUDE and re-attach the sign, rather than letting babel sign it, for the
        # same reason the `signed` branch does: babel given −0.4 and the pattern "#,##0" produces
        # "-0", so a rounding artefact reaches the reader as "−0 kWh". The f-strings these kinds
        # replace could not do that — `f"{round(-0.4):,}"` rounds to int 0 first — so signing here
        # would be a regression rather than a new convention. `conversion_loss` is a floating
        # difference of three sums and does land marginally below zero when the battery barely
        # cycles, so this is reachable, not theoretical.
        text = format_decimal(abs(scaled), format=spec["pattern"], locale=locale)
        negative = scaled < 0 and any(ch.isdigit() and ch != "0" for ch in text)
        text = prefixed(text)
        if negative:
            text = MINUS + " " + text if prefix else MINUS + text

    unit = spec.get("unit")
    if unit:
        text += spec.get("space", " ") + unit
    return text


def month_abbr(month: int, locale: str) -> str:
    """The abbreviated calendar-month name for 1..12 in `locale` ("Jan" / "jan", "Mar" / "mrt").

    The monthly chart's x-axis. It used to read from a table of English abbreviations in
    `results_view`, which meant a Dutch page's axis said "Jan Feb Mar"; babel's CLDR data has the
    abbreviation for every locale, so there is no table to translate and nothing to keep in step
    when a language is added. Registered as the per-locale `monthname` Jinja filter.

    An out-of-range value renders as its own number rather than raising: the chart is decoration on
    a page of figures, and a broken axis label is not worth a 500.
    """
    try:
        return Locale.parse(locale).months["format"]["abbreviated"][int(month)]
    except (KeyError, ValueError, TypeError):
        return str(month)


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
