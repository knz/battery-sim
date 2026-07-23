# Bilingual UI (English / Dutch)

## Task specification

**Original request (2026-07-23):** "We'll want to have the UI bilingual (english/dutch) with
a toggle at the top. The UI strings need to be in a separate source file to simplify
translation syncs."

Scope:

- Extract all user-facing UI strings out of the templates into a separate translation source.
- Support English and Dutch, with a language toggle in the header.
- Server-side i18n (the app is server-rendered Jinja per §5.1 — no client-side string swap).

## High-level decisions (from user Q&A)

- **String format: gettext / `.po` files** via Babel. Standard Python i18n toolchain; works
  with translation tools (Poedit, Weblate); adds a `.po → .mo` compile step. Templates call
  `{{ _('...') }}` / `{{ gettext('...') }}`.
- **Persistence: cookie.** The toggle sets a `lang` cookie; every request reads it. Survives
  reloads and restarts, no DB or auth needed.
- **Default: browser `Accept-Language`,** falling back to English. Order of precedence:
  explicit cookie → `Accept-Language` → English.

### Consequence flagged: determinism for tests/screenshots

Accept-Language makes the default non-deterministic across environments. The Playwright
screenshot helper and smoke tests will **pin a language explicitly** (cookie or header) so
verification is stable; the app itself still auto-detects for real users.

## Plan

1. Add deps: `babel` (runtime helpers + CLI) and Jinja2's `i18n` extension.
2. Locale layout:
   - `app/locales/messages.pot` — extraction template (all msgids).
   - `app/locales/en/LC_MESSAGES/messages.po` + `.mo`
   - `app/locales/nl/LC_MESSAGES/messages.po` + `.mo`
   - `babel.cfg` — extraction config (which files to scan).
3. `app/i18n.py` — load catalogs, resolve the active locale per request
   (cookie → Accept-Language → en), expose `gettext` to Jinja via `jinja2.ext.i18n`.
4. Wire FastAPI: a dependency/middleware that picks the locale and installs the right
   translations on the template environment per request; a `POST /lang` (or `GET`) route
   that sets the cookie and redirects back.
5. Header: a language toggle (EN / NL) that hits that route.
6. Mark strings: replace literal UI text in templates with `{{ _('...') }}`; move
   sample-data display strings behind translation too where they are UI chrome (labels,
   headings) vs. data (entity IDs, numbers stay as-is).
7. Extract + fill Dutch: `pybabel extract` → `.pot`, init/update `en` and `nl` `.po`,
   translate Dutch, `pybabel compile`.
8. Update tooling: screenshot helper + smoke tests pin a locale; add a test that NL renders
   and the toggle switches language.
9. Docs: README section on the i18n workflow (extract/update/compile).

## Files modified

Created:

- `babel.cfg` — extraction config (scans templates + `app/**.py`, uses `jinja2.ext.i18n`).
- `app/i18n.py` — locale resolution (cookie → Accept-Language → en), catalog loading/caching,
  Jinja install helper, language endonym helper.
- `app/locales/messages.pot` — extraction template (154 msgids).
- `app/locales/en/LC_MESSAGES/messages.{po,mo}` — English (msgstr = msgid).
- `app/locales/nl/LC_MESSAGES/messages.{po,mo}` — Dutch translations.

Changed:

- `app/main.py` — enable `jinja2.ext.i18n`; install per-request catalog; add `GET /lang/{code}`
  (sets `lang` cookie, 303 redirect); pass `lang` context to the template.
- `app/templates/index.html` — `EN | NL` toggle in header; `{{ _() }}` on chrome + dialog;
  `<html lang>` reflects the active locale.
- `app/templates/_panel_data.html`, `_panel_params.html`, `_panel_results.html` — wrap UI
  chrome in `_()`; translate sample-data chrome via `_(value)`; newstyle `_('...%(x)s', x=…)`
  for the three interpolated strings.
- `app/sample_data.py` — `_N()` extraction marker; wrap translatable chrome (roles, series
  names, policy labels, KPI titles, breakdown/benchmark labels, caveats, periods); literal
  `%` → fullwidth `％` in translatable strings.
- `tests/screenshot.py` — `--lang` flag; pin locale via cookie.
- `tests/test_smoke.py` — shared browser fixture; pin EN; add NL render, toggle-present, and
  `/lang` cookie tests (9 passing).
- `pyproject.toml` — add `babel`.
- `README.md` — i18n workflow section.

## Obstacles and solutions

- pybabel didn't extract `_N()` strings from `sample_data.py` → added `-k _N` extract keyword.
- Newstyle gettext (`_('...%(x)s') % {...}`) raised KeyError → switched to `_('...', x=…)`.
- **Literal `%` broke both compile and render.** Babel's `.po` compiler rejects a bare ASCII
  `%` as an incompatible format placeholder, and Jinja's newstyle gettext runs printf
  substitution on every `_()` result (so a stray `%` raises at render). Fixed by using the
  fullwidth `％` (U+FF05) for literal percents in translatable strings — the user's suggestion.
- A stale English `.mo` (filled before the `％` conversion) kept an ASCII `%` and 500'd the
  default render → rebuilt the EN catalog fresh from the current `.pot`.
- Two `sync_playwright()` module fixtures collided with the asyncio loop → single shared
  browser fixture.

## Current status

**Complete.** UI is bilingual; header toggle switches EN/NL via cookie; default follows
Accept-Language. Both languages render (verified by screenshot + 9 passing tests); the
`extract → update → compile` workflow runs clean.

Deliberately left as English (sample **data**, not chrome — will come formatted from the
domain layer): the two panel summary lines, granularity cell values ("hourly (full)" etc.),
KPI deltas, and the coverage/period detail strings. Locale-aware number/date formatting
(Dutch `,` decimal) is a follow-up, not done here.
