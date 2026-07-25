# Home Battery Simulator

A locally-run web app that retrospectively simulates what a home battery would have saved a
Dutch household, using that household's own historical data under the post-2027 Dutch regime.
See [`specs/README.md`](specs/README.md) for the full specification.

## Status

**Frontend visual scaffold** (first increment). The three-panel UI
([specs/02-ux-wireframes.md](specs/02-ux-wireframes.md)) renders from a *static sample
view-model* — it shows the intended shape of the product but is **not yet wired to feature
logic**: no data ingestion, simulation, or pricing. Numbers on screen are placeholders.

The rendered variant is the app default: solar PV on, cost simulation off (energy only), so
the Pricing box and the COST SAVINGS results section are absent by design.

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
values — entity IDs, numbers, coverage strings — are left untranslated.

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
`_msg_n` are `app/results_view.py`'s message builders: a view-model that needs runtime figures in
a sentence emits a `(msgid, params)` pair rather than a finished string, so the msgid stays a
compile-time constant the extractor can see — see **Messages with runtime values** below.

**Messages with runtime values.** A display string built with an f-string has a msgid that exists
only at runtime, so `pybabel extract` never records it and the template's `_()` around it matches
nothing — the string renders in English on a Dutch page while every catalog reports 100% translated.
View-models therefore emit the constant text and the values separately:

```python
_msg("Your meter recorded %(meter)s imported over this period; …", meter=imp_str)
_msg_n("simulated %(res)s · %(n)s interval",     # count-driven plural
       "simulated %(res)s · %(n)s intervals", n_intervals, res=label, n=f"{n_intervals:,}")
```

and templates render them with the `msg()` macro in `app/templates/_msg.html`, which translates
the msgid first and substitutes afterwards. The order matters: substituting first rebuilds exactly
the unextractable runtime string the split exists to avoid.

**Literal percent signs** need no escaping. `_()` does not printf-format its result (the i18n
extension is installed with `newstyle=False` — see `app/i18n.py`), so a bare ASCII `%` in a
translatable string is safe. For genuine interpolation, build the string with `%(name)s`
placeholders and substitute explicitly after translation via `app.i18n.interpolate()`.

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
```
