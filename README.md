# Home Battery Simulator

A locally-run web app that retrospectively simulates what a home battery would have saved a
Dutch household, using that household's own historical data under the post-2027 Dutch regime.
See [`specs/README.md`](specs/README.md) for the full specification.

## For households — using the app

**The rest of this README is for people working on the app.** If you just want to run it,
start here instead:

- **[Installing and running](docs/en/install.md)** — [Installeren en starten](docs/nl/installatie.md)
- **[The security warnings your OS shows](docs/en/security-warnings.md)** — [Beveiligingswaarschuwingen](docs/nl/beveiligingswaarschuwingen.md)
- **[Supporting the project](docs/en/sponsor.md)** — [Het project steunen](docs/nl/sponsor.md)

Those pages exist in English and Dutch; the index is [`docs/README.md`](docs/README.md).

The short version: there is a **Linux AppImage** — download it, `chmod +x`, run it. **No macOS
or Windows build has been produced yet.** Neither desktop build is signed, which is what the
security-warnings page is about.

## Status

**Both the energy and the cost paths are complete end to end.** Panel ② configures a battery
and, behind the cost opt-in, a contract; panel ③ simulates against the household's own
persisted data and reports what it would have saved in kWh and in euros, each bounded by its
own §6.12 perfect-foresight benchmark. The per-area breakdown is in
[specs/implementation-progress.md](specs/implementation-progress.md), which is the file to
trust over this paragraph.

Known limits, from that same file: the cost path carries **only the DYNAMIC contract type**
(FIXED and VARIABLE are pending controls, blocked on §6.4's `tariff_zone`), terugleverkosten
are FLAT only, and CSV ingestion, configuration epochs and per-interval CSV export are not
built. Controls that are specified but not yet built render *pending* — disabled, with a `[?]`
button explaining what is missing.

**Desktop packaging** is at phase 7: a PyInstaller `onedir` build wrapped as an AppImage with
WebKit2GTK bundled, verified to open its native window on a machine with no WebKit installed.
Built against glibc 2.39, so it needs Ubuntu 24.04 or newer. macOS and Windows are planned but
not built. The record is `changelog/20260805-desktop-packaging.md`.

## Stack

Per [specs/08-architecture.md](specs/08-architecture.md) §5.1: FastAPI + Jinja2 server-rendered
HTML, HTMX for later fragment swaps, Plotly for charts, styled with **daisyUI v5 on Tailwind
CSS v4**. No SPA framework and no client-side computation. Python managed with `uv`.

## Running the app

```bash
uv sync                                   # create venv, install Python deps
uv run uvicorn app.main:app --reload      # serve at http://127.0.0.1:8000
```

The browser receives plain HTML plus one committed stylesheet
(`app/static/app.css`) and a locally-served Plotly bundle — **running the app needs no Node
step**.

## Working on the styles

The stylesheet is generated from `app/static/src/app.tailwind.css` by the Tailwind CLI and
**committed** as `app/static/app.css`. Regenerate it after editing templates or the source
CSS (Tailwind scans templates for the classes it emits):

```bash
npm install            # once, installs tailwindcss + daisyui (dev-time only)
npm run build:css      # regenerate app/static/app.css
npm run watch:css      # or watch and rebuild on change
```

## Internationalisation (English / Dutch)

The UI is bilingual. Translation is server-side gettext (`app/i18n.py`): the active locale is
resolved per request as **cookie → `Accept-Language` → English**, and a header toggle
(`EN | NL`) sets the `lang` cookie via `GET /lang/{code}`.

UI strings are marked for translation in two places: `{{ _('...') }}` in the Jinja templates,
and `_N('...')` in `app/sample_data.py` (a no-op extraction marker for chrome strings that
live in the sample view-model; the template translates them with `_(value)` at render). Data
values — entity IDs, coverage strings — are left untranslated. Numbers are neither: they carry no
words, so they never reach a catalog, but they are still written differently in each language and
are formatted at render time (see **Numbers and dates** below).

Catalogs live under `app/locales/<lang>/LC_MESSAGES/messages.{po,mo}`. The compiled `.mo`
files are **committed**, so running the app needs no compile step — only updating translations
does:

```bash
# 1. extract msgids from templates + the view-models (all three -k keywords are required)
uv run pybabel extract -F babel.cfg -k _N -k _msg -k _msg_n:1,2 \
    -o app/locales/messages.pot --sort-output --no-location .
# 2. merge into the per-language catalogs (--no-fuzzy-matching is REQUIRED, see below)
uv run pybabel update -i app/locales/messages.pot -d app/locales -l nl --no-fuzzy-matching   # and -l en
# 3. edit app/locales/nl/LC_MESSAGES/messages.po, then compile
uv run pybabel compile -d app/locales
```

**The flags and keywords on those commands are required, not cosmetic.** `--no-location` keeps
the `#:` source-location comments out of the committed catalogs, which is the form they are in.
`--no-fuzzy-matching` stops `pybabel update` guessing a translation for a new msgid from a
similar old one: without it, adding "Extra grid import" picked up the existing Dutch for a
different string and shipped it as "Netafname T2" — marked `#, fuzzy`, but compiled and shown
to the user all the same. A wrong translation is worse than an untranslated string, because
nothing flags it on the page.

The three `-k` keywords name the project's own extraction markers, none of which Babel knows by
default; omitting one drops its msgids silently, and the run still reports success. `_N` is
`app/sample_data.py`'s no-op tagger for view-model strings the templates translate. `_msg` and
`_msg_n` are `app/i18n.py`'s message builders (`msg` / `msg_n`, imported under those private
aliases by `app/results_view.py` and `app/data_view.py` — the aliases are what the keywords match,
so a third view module must import them under the same two names): a view-model that needs runtime
figures in a sentence emits a `(msgid, params)` pair rather than a finished string, so the msgid
stays a compile-time constant the extractor can see — see **Messages with runtime values** below.

**Messages with runtime values.** A display string built with an f-string has a msgid that exists
only at runtime, so `pybabel extract` never records it and the template's `_()` around it matches
nothing — the string renders in English on a Dutch page while every catalog reports 100% translated.
View-models therefore emit the constant text and the values separately:

```python
_msg("Your meter recorded %(meter)s imported over this period; …", meter=num(imp_total, "kwh"))
_msg_n("simulated %(res)s · %(n)s interval",     # count-driven plural
       "simulated %(res)s · %(n)s intervals", n_intervals, res=label, n=num(n_intervals, "count"))
```

and templates render them with the `msg()` macro in `app/templates/_msg.html`, which translates
the msgid first and substitutes afterwards. The order matters: substituting first rebuilds exactly
the unextractable runtime string the split exists to avoid.

A parameter may itself be a message, and is then translated before being substituted. That is for
an embedded WORD rather than a figure — a resolution label such as "hourly" or "15-min"
(`app/data_view._res_msg`) appears inside a dozen sentences, and passing it as a bare string would
leave one English word in each translated one, since interpolation runs after the lookup.

**Numbers and dates.** A figure is not a msgid and does not go in a catalog, but it still depends
on the locale: Dutch writes `3.924 kWh` and `0,094 €/kWh` where English writes `3,924 kWh` and
`0.094 €/kWh` — the two separators are swapped. A view-model runs before the request's locale is
known, so it must not format one. It emits a figure the same way it emits a sentence:

```python
num(3924.5, "kwh")      # → {"num": 3924.5, "fmt": "kwh"}, formatted at RENDER time
```

`num()` is in `app/i18n.py` and `kind` names an entry in its `_NUM_KINDS` table (`kwh`, `pct`,
`eur_kwh`, `count`, `general`, …) — so how the app writes a kWh figure has one definition, and an
unknown kind raises where the view-model is built rather than mid-render. The `msg()` macro formats
such a figure whether it is the whole field or a param inside a sentence.

`num()` is **not** an extraction keyword and needs none: nothing in it reaches a catalog. The unit
suffixes (`kWh`, `€/kWh`, `%`, `pp`) live in that table as literals, deliberately — they are written
identically in Dutch, and routing a symbol through gettext invites a translator to change one of the
two places it appears. Every negative figure carries U+2212 (`−`), not the ASCII hyphen, on every
path and in both locales; babel emits the hyphen, so `format_num` substitutes.

To format one outside a template, call `i18n.format_num(value, kind, locale)` — the locale is a
required argument on purpose, so no call site can quietly default to English. That is also how the
tests assert English figures: they pass `locale="en"` explicitly rather than relying on a default.

**Dates stay ISO** (`2026-07-24`) in both locales, and that is a decision rather than an omission —
`en` short is `7/24/26` and `nl` short is `24-07-2026`, which are the same day written two ways, so
a reader unsure which convention a page follows cannot tell them apart. Month NAMES are localised,
because they are words (`app/i18n.month_abbr`, the `monthname` filter — the monthly chart's axis).

**Literal percent signs need no escaping, in a msgid or in a translation.** Write `50%`, not
`50%%` and not the fullwidth `％`. Two separate mechanisms make that true, and both are needed:
`_()` does not printf-format its result (the i18n extension is installed with `newstyle=False`),
and `app.i18n.interpolate()` — which *does* %-format, since that is how `%(name)s` gets
substituted — doubles every `%` that is not part of a placeholder before it does so.

There is no escape sequence to remember: `%%` is two literal percent characters, not one. Only
`%(name)s` is special.

This matters most for translations. A Dutch string reading "50% lager" is ordinary copy a
translator has no reason to think twice about; before the escaping was added it rendered as
"50{}ager" or raised, producing a 500 on a page that worked fine in English. `tests/test_i18n.py`
pins the behaviour for msgids, translations, counted messages and nested ones.

## Self-testing (browser automation)

Playwright drives a bundled headless Chromium — no separate browser install, no extension.

```bash
uv run playwright install chromium              # once
uv run python tests/screenshot.py --lang en     # full-page PNG → tests/artifacts/page.png
uv run python tests/screenshot.py out.png --lang nl   # Dutch render
uv run pytest tests/test_smoke.py               # structural + bilingual assertions
```

The screenshot helper and tests pin the language (via the `lang` cookie) so rendering is
reproducible despite the Accept-Language default.

`tests/screenshot.py` starts the app on a free port, expands both collapsed panels, and
captures the whole page — the tool for eyeballing changes while iterating.

## Layout

```
app/
  main.py               FastAPI app; GET / renders the page, GET /lang/{code} toggles language
  i18n.py               locale resolution (cookie/Accept-Language) + gettext catalog loading
  sample_data.py        static sample view-model (placeholder numbers; _N() marks UI chrome)
  locales/              gettext catalogs: messages.pot, en/ and nl/ .po/.mo
  templates/
    index.html          page shell + header + pending-feature dialog
    _panel_data.html    panel ① Data input
    _panel_params.html  panel ② Parameters
    _panel_results.html panel ③ Results
    topology/*.svg      inline topology diagrams (§2.5)
  static/
    app.css             generated, committed stylesheet
    src/app.tailwind.css  stylesheet source (edit this)
    vendor/plotly.min.js  Plotly bundle, served locally
tests/
  screenshot.py         launch + screenshot helper
  test_smoke.py         Playwright smoke tests
docs/
  en/, nl/              user-facing documentation (install, security warnings, sponsorship)
```

## Licence

**GNU Affero General Public License v3.0 only** (`AGPL-3.0-only`). The full text is in
[LICENSE](LICENSE); `pyproject.toml` declares it as a PEP 639 SPDX expression.

The AGPL's distinguishing clause is §13: if you run a modified version and let other people use
it over a network, those users are entitled to the source of your modified version. Running the
app on your own machine for yourself — which is what it is designed for — triggers nothing.

## Supporting the project

The desktop builds are unsigned, which is why macOS and Windows warn about them. What signing
would cost and what it would actually fix is set out in
[docs/en/sponsor.md](docs/en/sponsor.md) ([Nederlands](docs/nl/sponsor.md)).

This invitation lives in the documentation and in this README, and **deliberately nowhere in
the application itself**: the app makes no outbound network calls except to the user's own Home
Assistant ([specs/01-product-brief.md](specs/01-product-brief.md) §1.5), and a sponsor link in
the window would be the first outward-facing affordance the product has.
