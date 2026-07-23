# Frontend visual scaffold — first increment

## Task specification

**Original request (2026-07-23):** "We have some specs for our desired app. We'd like to
start implementing, but do it incrementally. The first goal is to have something show up on
the screen which displays the main visual items from the UX (but not yet connected to
feature logic). I'd like you to set this up. Later I'll ask you to iterate on stuff so also
ensure you have enough equipment (browser automation) set up to iterate on testing yourself."

Scope of this increment:

- Stand up the application skeleton (per §5.1 architecture: FastAPI + Jinja2 + HTMX + Plotly,
  no build step).
- Render the **main visual items** of the UX on screen — the three-panel stepper (Data,
  Parameters, Results) from §2.2–2.4 — with representative static/placeholder content.
- **Not** wired to feature logic: no ingestion, no simulation, no pricing. Static sample
  values stand in for computed results.
- Set up browser automation (Playwright) so future iterations can be self-tested with
  screenshots and DOM assertions.

## High-level decisions

- **Stack:** follow §5.1 exactly — FastAPI, Jinja2 server-rendered HTML, HTMX for fragment
  swaps (not needed yet but the structure anticipates it), Plotly for charts. `uv` for
  dependency/venv management (present on system; poetry is not).
- **Browser automation:** Playwright driving its own bundled Chromium headless. Chosen over
  the claude-in-chrome extension because it is self-contained (no separate Chrome install,
  no extension permissions) and scriptable for regression screenshots.
- **This increment renders the "Available" and "Inapplicable/hidden" states with sample
  data.** Pending/blocked/soft-blocked states are structurally present in the templates but
  driven by static flags, since no feature logic decides them yet.

## Requirements changes

- **UI library (mid-conversation):** user chose daisyUI (with alternatives welcomed). After
  presenting §5.1-compatible options, settled on daisyUI. User then **insisted on Tailwind
  v4** specifically, which changed the setup from the initial v3 assumption: Tailwind v4 is
  CSS-first (no `tailwind.config.js`; config via `@import`/`@plugin`/`@source` in the CSS),
  and requires **daisyUI v5** (v4 is for Tailwind v3).

## Files modified

Created:

- `pyproject.toml`, `.python-version`, `uv.lock` — uv project; deps fastapi, uvicorn,
  jinja2 (+ dev: playwright, pytest).
- `package.json` — dev-time only; tailwindcss v4, @tailwindcss/cli v4, daisyui v5, with
  `build:css`/`watch:css` scripts. No runtime Node dependency.
- `app/main.py` — FastAPI app, `GET /` renders the page from the sample view-model.
- `app/sample_data.py` — static sample view-model (placeholder numbers from the wireframes).
- `app/templates/index.html` — shell, header, shared "not built yet" pending dialog.
- `app/templates/_panel_data.html` — panel ① (source, series mapping, granularity, quality).
- `app/templates/_panel_params.html` — panel ② (battery, grid, PV, topology selector,
  policies; Pricing box absent because cost off).
- `app/templates/_panel_results.html` — panel ③ (KPI tiles, breakdown, benchmark bars,
  Plotly chart, caveats; COST section absent).
- `app/templates/topology/pv-dc.svg`, `pv-ac.svg` — inline topology diagrams (§2.5),
  currentColor stroke, 240×160.
- `app/static/src/app.tailwind.css` — Tailwind v4 CSS-first source (+ custom radio-card,
  benchmark-bar components, and a pinned sans-serif fallback).
- `app/static/app.css` — generated, committed stylesheet.
- `app/static/vendor/plotly.min.js` — Plotly 2.35.2, served locally (no runtime CDN).
- `tests/screenshot.py` — launch app + full-page screenshot helper for iteration.
- `tests/test_smoke.py` — Playwright smoke tests (6, all passing).
- `README.md`, `.gitignore`.

Removed: `main.py` (uv's leftover stub; real entry point is `app/main.py`).

## Rationales and alternatives

- Server-rendered Jinja over a JS SPA: mandated by §5.1 ("No build step, no SPA framework,
  no client-side computation").
- Playwright over Selenium/puppeteer: bundles its own browser, first-class screenshot API,
  Python bindings align with the backend language.

## Obstacles and solutions

- npm pulled Tailwind v4 CLI alongside a v3 core; after the v4 decision, reinstalled a
  coherent v4 + daisyUI v5 stack.
- Topology SVGs were `{% include %}`d but lived under `static/`; moved them under
  `templates/topology/` since they are inlined HTML partials, not served assets.
- `results.chart.values | tojson` failed — Jinja resolved `.values` as the dict method;
  fixed with bracket access `results.chart["values"]`.
- Headless Chromium rendered wide letter-spacing (Tailwind's default `system-ui` font stack
  did not resolve); pinned a concrete sans-serif fallback ending in DejaVu Sans/Arial.
- Smoke test `get_by_text("COST SAVINGS")` matched "cost" substrings; tightened to
  `exact=True`.

## Current status

**Complete for this increment.** The page renders all main visual items of the UX for the
default variant (PV on, cost off), verified by screenshot and 6 passing Playwright smoke
tests. Browser-automation tooling (Playwright + screenshot helper) is in place for future
iteration. Not wired to feature logic, as scoped.

Natural next steps (user's call, not decided):

- Make the PV / cost toggles actually re-render the page, to eyeball all four variants.
- Wire up expand/collapse persistence and the HTMX fragment flow from the state machine (§3).
- Begin the service/domain layer, or add the CSV-upload source sub-panel variant.

**Approved and in progress.** Decisions locked in:

- Scope: stepper with real expand/collapse (panels ①② collapsed, ③ expanded).
- Sample variant: default (PV on, cost simulation off) — solar rows shown, Pricing box and
  COST SAVINGS section absent, summary reads "energy only".
- Environment: `uv`, install now so the app can be launched and screenshotted.
- **UI library: daisyUI on Tailwind**, generated via the `tailwindcss` CLI into a committed
  `app/static/app.css`. The browser receives plain HTML + one static CSS file, honouring
  §5.1 "no build step / no SPA": the generated CSS is committed so running the app never
  needs the build; only regenerating after template edits does.
