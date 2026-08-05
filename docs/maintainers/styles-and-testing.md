<!--
Maintainer documentation: regenerating the committed Tailwind stylesheet, and the Playwright
self-testing workflow (screenshot helper + smoke tests). The stack and layout are in
development.md.
-->

# Styles and self-testing

## Working on the styles

The stylesheet is generated from `app/static/src/app.tailwind.css` by the Tailwind CLI and
**committed** as `app/static/app.css`. Regenerate it after editing templates or the source CSS
(Tailwind scans templates for the classes it emits):

```bash
npm install            # once, installs tailwindcss + daisyui (dev-time only)
npm run build:css      # regenerate app/static/app.css
npm run watch:css      # or watch and rebuild on change
```

Because the result is committed, forgetting to regenerate does not break the app — it silently
serves the previous stylesheet, so a new class simply has no effect. Check `git status` for a
modified `app/static/app.css` after template work.

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
