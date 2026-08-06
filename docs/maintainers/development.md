<!--
Maintainer documentation: the technology stack, how to run the app from source (including
scoping the auto-reload watcher), what the browser is served, and the repository layout.
Styles and testing are in styles-and-testing.md; the bilingual UI is in i18n.md.
-->

# Development

## Stack

Per [docs/specs/08-architecture.md](../specs/08-architecture.md) §5.1: FastAPI + Jinja2
server-rendered HTML, HTMX for later fragment swaps, Plotly for charts, styled with **daisyUI
v5 on Tailwind CSS v4**. No SPA framework and no client-side computation. Python managed with
`uv`.

## Running the app

```bash
uv sync                                   # create venv, install Python deps
uv run uvicorn app.main:app --reload      # serve at http://127.0.0.1:8000
```

### Scoping the reload watcher

`--reload` watches the entire working directory, so unrelated directories beside `app/`
(build outputs, caches, checked-out worktrees) can trigger spurious reloads. Restrict the
watcher to the sources:

```bash
uv run uvicorn app.main:app --reload --reload-dir app
```

`app/` holds the Python sources, templates, static files and locales, so nothing that should
trigger a reload lives outside it.

To avoid passing the flag every time, set it in the environment instead — uvicorn has no
config file of its own, but every CLI option has a `UVICORN_*` counterpart:

```bash
export UVICORN_RELOAD=true
export UVICORN_RELOAD_DIRS=app
```

Note that `UVICORN_RELOAD_DIRS` takes **one** directory despite the plural name; a space- or
comma-separated list is passed through verbatim and fails with `Path '...' does not exist`.
Watching several directories requires repeating `--reload-dir` on the command line. These
variables are read from the process environment only — uvicorn's `--env-file` does not apply
to `UVICORN_*` settings.

## Assets

The browser receives plain HTML plus one committed stylesheet (`app/static/app.css`) and a
locally-served Plotly bundle — **running the app needs no Node step**. Node is only needed to
regenerate the stylesheet, and the compiled translation catalogs are committed too, so neither
is a prerequisite for starting the app.

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
packaging/
  icon/battery-sim.svg  master application icon; PNGs are rendered from it by icon/render.py
docs/
  en/, nl/              user-facing documentation (install, security warnings, sponsorship)
  maintainers/          this tree
  specs/                the specification
changelog/              per-task record of decisions and rationales
```
