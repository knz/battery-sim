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

## Self-testing (browser automation)

Playwright drives a bundled headless Chromium — no separate browser install, no extension.

```bash
uv run playwright install chromium        # once
uv run python tests/screenshot.py         # full-page PNG → tests/artifacts/page.png
uv run pytest tests/test_smoke.py         # structural assertions on the rendered page
```

`tests/screenshot.py` starts the app on a free port, expands both collapsed panels, and
captures the whole page — the tool for eyeballing changes while iterating.

## Layout

```
app/
  main.py               FastAPI app; GET / renders the page
  sample_data.py        static sample view-model (placeholder numbers)
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
