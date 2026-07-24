# Slot-first data panel — Phase C frontend

## Task Specification

Build the frontend ("Phase C") for the slot-first data-input reshape of panel ①. Phases A/B
(backend `app/sources/` package, per-slot persistence, `POST /data/slot/{name}/load`) are
committed. This task is UI only. Do NOT change backend Python logic in `app/sources/`,
`app/dataset.py`, or the `app/main.py` route bodies. Small view-model additions to
`app/data_view.py` and `app/sample_data.py` are permitted.

Design (approved with the user): panel ① leads with the roster of data slots (gated by the
setup band), each row shows its chosen source or a "Choose source…" affordance; clicking opens
a right-side drawer for that slot listing its available sources and config. The Home Assistant
connection is SHARED across all HA slots — test/connect once, reuse everywhere.

## High-Level Decisions

1. **Full slot roster in `data_view.py`.** `panel_data_from` now emits one row per
   `SERIES_SLOTS` entry (not only series present in the persisted dataset). Absent slots get
   `entity=None`, `source=None`, plus the same `sources` list from `registry.sources_for`. This
   is what lets a user pick a source for a slot with no data yet.
2. **Sample empty-state parity.** `sample_data._panel_data` rows gain `source` and `sources`,
   built by importing `registry.sources_for` + `SLOT_BY_NAME`, keyed on each row's `name`.
   Sample sets `home_assistant` on grid rows and `energy_charts` on `price_spot` to show the
   populated look.
3. **Drawer = a hand-rolled fixed right-side panel** (not daisyUI's content-wrapping `drawer`,
   which would restructure the page shell), one shared instance whose content is filled per slot
   by JS from the `data-slot-sources` JSON on each row's "Choose source" button. Keyboard-
   closable (Escape), visible close control, backdrop click. Radios labelled per source.
4. **Shared HA connection** stays the single `#ha-connection` card (all IDs preserved for
   `ha_fetch.js`). After a successful Test connection, every HA slot's `<select>` is filled.
5. **energy_charts backend load** posts to `/data/slot/{slot}/load` with the same
   `HISTORY_DAYS` window the HA fetch uses, then reloads on success.

## Files Modified

- `app/data_view.py` — emit full slot roster (present + absent rows).
- `app/sample_data.py` — add `source`/`sources` to each mapping row; `_N` markers for new chrome.
- `app/templates/_panel_data.html` — slot-first rewrite: intro, shared HA card, slot roster
  with per-row source control + drawer trigger, right-side drawer, unchanged quality box.
- `app/templates/index.html` — mount the shared source-picker drawer + its script (drawer
  open/close + "Use this source" backend-load wiring lives in ha_fetch.js).
- `app/static/ha_fetch.js` — shared connection, per-slot source selection, drawer wiring,
  energy_charts backend load, fetch-history over HA slots only.
- `app/static/app.css` — rebuilt (drawer classes now compiled).
- `app/locales/*` — extracted/compiled new msgids.

## Obstacles and Solutions

- gettext printf substitution: `_("Source for: %(role)s")` crashed the render (jinja2 i18n
  applies `% variables`). Dropped the placeholder; the drawer subtitle is set to the plain role
  string in JS instead.
- `pybabel update` fuzzy-matched 4 new msgids to old ones ("Close"→"close",
  "Series slots"→"Series", "Source"→"Source:", "Home Assistant connection"→"Home Assistant").
  Fixed with a Babel-API pass: EN new msgstrs set to the English source with fuzzy cleared; NL
  new msgstrs cleared to empty with fuzzy cleared. Pre-existing fuzzy entries left untouched.
- CSV pending option is created dynamically in the drawer, so its `[?]` could not use the
  static per-button listener in index.html. Switched that listener to delegated (document-level)
  so dynamically-added `[data-pending-name]` buttons open the shared dialog with no extra wiring.

## Review + fixes applied (2026-07-24)

A sub-agent review found **no blockers** — the three high-risk surfaces all verified correct:
the `tojson | forceescape` `data-slot-sources` JSON round-trips through HTML-attr decoding
(em dash / ellipsis / quotes survive, EN and NL); the pending `[?]` opener in index.html is
delegated at the document level, so the drawer's dynamically-created CSV button works; and the
shared-connection fill activates every HA slot's select after one Test.

Fixes applied from the review:

- **Dutch translations supplied** for the 17 new msgids (parent-authored, idiomatic NL);
  catalogs recompiled. Verified NL render shows them.
- **Pre-existing fuzzy `"Not connected"` fixed** (it was inverted: EN msgstr said "Connected",
  NL "Verbonden", both `#, fuzzy` so gettext showed English in both locales). Now EN "Not
  connected", NL "Niet verbonden", fuzzy cleared. (Touched opportunistically while in the catalog.)

Follow-ups filed (not blocking, deferred):

- **energy_charts → HA source switch in the drawer is inert without a reload.** When a slot's
  persisted source is `energy_charts`, its row renders a static `<span>`, not an `.ha-map-select`;
  `selects` is captured once at load, so picking Home Assistant in that slot's drawer finds no
  select to activate. Narrow (only `price_spot`, only after an energy_charts load) and recoverable
  by a page reload. A proper fix injects a select dynamically — deferred to a later UI pass.
- **Hardcoded English fetch-status strings** in ha_fetch.js (`Connecting…`, `Fetching…`, error
  messages) predate Phase C; the new drawer strings do go through `t()`/`#drawer-i18n`. A full JS
  i18n pass is a separate cleanup.

## Current Status

Done and reviewed. App imports; `/` renders 200 in EN and NL; the full applicable slot roster
renders for both the sample empty-state and a real partial dataset; cost-on surfaces the min/max
rows. CSS rebuilt (drawer classes compiled). Dutch supplied for all 17 new msgids.
`tests/test_slot_load.py` + `tests/test_ingest_ws.py`: 22 passed.

## Design notes

- energy_charts backend load reuses the HA `HISTORY_DAYS` (730-day) window; the backend clamps
  to committed data, so the exact span is not load-bearing.
- The drawer is a hand-rolled fixed right panel (not daisyUI's content-wrapping `drawer`), which
  avoids restructuring the page shell; Escape/backdrop/✕ all close it and focus returns to the
  opening button. Focus is not fully trapped inside the drawer while open (acceptable for a
  non-modal picker; noted for a later a11y pass).
