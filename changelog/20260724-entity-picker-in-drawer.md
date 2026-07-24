# Move the Home Assistant entity picker into the source drawer

> Status: **in progress.** Created 2026-07-24. Follow-up on the slot-first data panel
> (see [20260724-slot-first-data-panel-ui.md](20260724-slot-first-data-panel-ui.md)).

## Task specification (original request)

User prompt, verbatim:

> "when choosing the home assistant source, the entity to use should be defined in the side
> panel, not the main screen. (there's no "entity" to choose from when another source than HA
> is selected)"

The HA entity `<select>` currently lives in the main slot-roster row (the "Entity / statistic ID"
column). It should move into the source drawer, shown only when Home Assistant is the selected
source — there is no entity to choose for any other source.

## Decisions (from the user, 2026-07-24)

- **Per-slot entity state:** one entity `<select>` in the drawer, reconfigured per slot when the
  drawer opens; the chosen entity per slot kept in JS state (not a per-slot DOM select).
- **Main row:** drop the "Entity / statistic ID" column entirely. The source button shows the
  source and, for HA, the chosen entity inline (e.g. `Home Assistant · sensor.…import_t1`).
  Everything (source + entity) is editable only in the drawer.

## Files modified

- `app/templates/_panel_data.html` — dropped the "Entity / statistic ID" column (both the `<th>`
  and the `<td>` that held the `.ha-map-select` / energy_charts span). The roster is now Role /
  Req / Source. The source button wraps its label text in a `.slot-source-label` span (so JS can
  rewrite just the text), carries a new `data-slot-kind` attribute (energy/price, derived as the
  template did), and keeps `data-slot` / `data-slot-source` / `data-slot-sources`. Header comment
  updated to describe the drawer-based entity choice.
- `app/templates/index.html` — added the drawer entity picker: a `#drawer-ha-entity` wrapper
  (hidden by default) with a labelled `#drawer-entity-select` beside `#drawer-ha-note`. Added
  i18n keys to `#drawer-i18n`: `choose_entity`, `connect_first`, `ha_source`, `choose_source`,
  `none`. Drawer header comment updated.
- `app/static/ha_fetch.js` — the state-model rewrite (see below). Header comment rewritten.
- `app/locales/**` — extracted/updated/compiled; new msgids added (see below). NL left empty;
  the two fuzzy auto-matches Babel introduced (NL and EN) were cleared to empty.
- `app/static/app.css` — rebuilt (minified) after the template class changes.
- `tests/test_ingest_ws.py` — `test_page_shows_sample_before_any_fetch` asserted a sample-only
  *entity id* (`sensor.electricity_meter_import_t1`) that used to render in the removed column;
  it no longer appears anywhere on the page. Switched the sample-only marker to the quality
  string `"3 gaps totalling 4.2 h"` (emitted only by the sample, never by the real view-model).

Python view-models (`app/data_view.py`, `app/sample_data.py`) were left unchanged: the template
derives the slot kind itself and no longer reads `row.entity` on the main row, so no view-model
field needed adding or removing.

## Implementation notes — the JS state model (the crux)

There is no per-row DOM `<select>` any more. Instead `ha_fetch.js` keeps a per-slot map
`slotState[name] = { source, statId, kind }`, seeded at load from each `.slot-source-btn`'s
`data-slot-source` / `data-slot-kind`. `statId` starts empty because the persisted view-model
carries only a "(res, N intervals)" coverage summary, not a re-selectable statistic id.

- `mappedSlots()` (used by `fetchHistory`) now reads `slotState`: the slots with
  `source === "home_assistant"` and a truthy `statId`, mapped to `{name, kind, statId}` exactly as
  before, so `fetchHistory` is unchanged downstream.
- `fillSelects()` was replaced by `fillDrawerEntitySelect(slotName)`, which populates the single
  `#drawer-entity-select` for one slot: kind-appropriate ids, preselecting the slot's stored
  `statId` or a `guessId()` heuristic. When not connected it shows a single disabled
  "Connect Home Assistant above first" hint.
- `testConnection` still stores `statIds` and enables Fetch history; if a drawer is open on an HA
  slot it repopulates the entity select, otherwise the ids are just stored for the next open.
- `onSelectSource` writes `slotState[slot].source`, toggles the entity picker / note / backend
  action, and refreshes the slot button label. The entity `<select>`'s `change` handler writes
  `slotState[slot].statId` and refreshes the label. `closeDrawer` also refreshes the label.
- `updateSlotButton()` rewrites `.slot-source-label`: `Home Assistant · <entity>` (or
  `· choose entity…` when HA is chosen but no entity yet), the plain source label otherwise, or
  the "Choose source…" affordance when unchosen. An initial pass at load sets the suffix on
  already-HA slots so the missing entity is visible before the drawer is opened.

Connect-vs-open ordering both work: connect-then-open populates on open via `fillDrawerEntitySelect`;
open-then-connect shows the disabled hint, and `testConnection` repopulates the open drawer.

## New English msgids added (NL to be supplied by the parent)

- `Entity`
- `choose entity…`
- `Connect Home Assistant above first`

(`Home Assistant`, `Choose source…`, `— none —` already existed in the catalog and were reused
via the `#drawer-i18n` JSON block.)

## Review + fixes applied (2026-07-24)

A sub-agent review found **no blocker** and one should-fix, plus verified the happy-path fetch
pickup, the seed/re-fetch behaviour, connect-vs-open ordering, the token invariant, i18n, and the
test-assertion change. Resolved:

- **Dutch supplied** for the three new msgids (`Entity` → "Entiteit", `choose entity…` →
  "kies entiteit…", `Connect Home Assistant above first` → "Verbind eerst Home Assistant
  hierboven"); catalogs recompiled.
- **Guess-commit contract made explicit (the should-fix).** Opening a connected HA slot's drawer
  pre-selects a heuristic `guessId()` and writes it into `slotState`, so the guess is fetchable by
  default. The prior comment ("the user confirms by fetching") overstated the safety. Rather than
  gate the write — which would break the connect-once convenience and force the user to open every
  slot's drawer — the guess is now made a *visible* default: `fillDrawerEntitySelect` calls
  `updateSlotButton` so the roster row immediately shows `Home Assistant · <guessed id>`, and the
  comments state plainly that the guess is shown on the row and in the dropdown and overridden
  there. A wrong guess is visible before any fetch, not silent.
- **Pre-existing corrupted NL string fixed** (the "0.41％ … negative reconstructed load" msgstr had
  two Dutch sentences concatenated) — now a single clean sentence. Unrelated to this task; fixed
  opportunistically while in the catalog.

Spec §2.2 updated to match: the roster wireframe drops the entity column and shows the source +
bound entity inline; the drawer subsection documents the Entity dropdown (HA only, populated from
the shared connection).

## Current status

Done and reviewed. `app.main` imports; GET / renders 200 in EN and NL with the roster missing the
entity column and the drawer entity select present; `ha_fetch.js` parses (`node -c`); CSS rebuilt;
Dutch supplied for all three new strings; full suite (minus flaky smoke) green. No live/browser
exercise of the fetch (no browser automation available this session) — worth a manual
pick-entity-then-fetch check.
