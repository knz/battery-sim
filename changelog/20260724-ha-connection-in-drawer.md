# 20260724 — Move the HA connection card into the source drawer

## Original user prompts (verbatim, per specs/CLAUDE.md)

1. "in the data source selection UX: currently the user has to fill in HA connection details
   always, above the selection of data sources. we'd like to have the HA connection details
   only appear when the user selects HA in the side pane where they select the data source.
   However the HA connection details should be preserved/shared across sources."
2. Clarification answers: place the connection UI in a **configuration modal** opened by a
   **"Configure" button next to the Home Assistant option**; **require a successful Test before
   Confirm**; the Configure button shows connection status; Confirm requires connection AND an
   entity.
3. "don't forget to update the ux/wireframes specs"

## Task Specification

In Panel ① (data-source selection), the Home Assistant connection details (Base URL,
Token, Test connection, status) are currently a permanent panel-level card shown above
the slot roster — the user must fill them in regardless of whether they use HA.

Requested change: show the HA connection details **only when the user selects Home
Assistant inside the per-slot source drawer**. The connection details must still be
**preserved / shared across sources and slots** — connect once, reuse everywhere.

## High-Level Decisions

- The shared HA connection UI is removed from the top of Panel ① and moved into a
  **configuration modal** (`<dialog id="ha-config-dialog">`), opened by a **"Configure"**
  button rendered next to the Home Assistant radio in the source drawer (JS-rendered, since
  the source list is built in `ha_fetch.js`).
- Connection state stays **shared** across slots (in-JS `haConnected`/`statIds` +
  localStorage, unchanged). Element IDs `#ha-base-url`, `#ha-token`, `#ha-test-btn`,
  `#ha-status` are preserved so `ha_fetch.js` bindings resolve — only their host node moves
  from the panel card into the modal.
- The Configure button reflects the shared state: "Configure…" when not connected,
  "✓ Connected" once a Test succeeds. Reopening any slot's drawer shows it already connected.
- **Confirm gate for HA slots:** enabled only when the connection has tested OK
  (`haConnected`) **and** a non-empty entity is chosen. This removes the previous
  "commit HA with no entity, choose later" reversible state for newly-confirmed slots.
- `data-ingest-ws` attribute (needed by JS for the backend ingest WS) moves off the removed
  `#ha-connection` card onto the `#slot-roster` card, which stays.

## Files Modified

- `app/templates/_panel_data.html` — removed the shared HA connection card; reworded intro;
  moved `data-ingest-ws` onto `#slot-roster`.
- `app/templates/index.html` — added `#ha-config-dialog` modal (URL/token/Test/status);
  added drawer i18n strings.
- `app/static/ha_fetch.js` — connection fields read from the modal; Configure button rendered
  next to the HA radio; button reflects shared state; Confirm requires connection + entity;
  module header comment updated.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.{po,mo}` — extracted +
  translated the new/changed strings (Configure…, ✓ Connected, "Configure the connection
  first", reworded intro + drawer note).
- `specs/02-ux-wireframes.md` — §2.2: removed the panel-level connection card from the wireframe;
  added the Configure button + connection modal wireframe; rewrote the entity/connection-sharing
  narrative; documented the HA Confirm gate (tested connection + chosen entity).

## Obstacles and Solutions

- `data-ingest-ws` lived on the removed `#ha-connection` card → moved onto `#slot-roster`
  (which stays and gates the JS module).
- Pre-existing test `test_smoke.py::test_new_pending_controls_marked` fails on the disabled
  CSV `input[name=source]` radio — it is now drawer-rendered (from the prior transactional-
  drawer commit `ffaa7e5`), so it is absent from the initial DOM. Confirmed failing on `HEAD`
  before this work; **out of scope**, left untouched.

## Current Status

Implemented and verified. `pybabel compile` clean. Playwright drive-through confirms: no
panel-level connection card, Configure button beside HA, modal opens with the connection
fields, entity picker disabled + Confirm gated before connection, and no console errors.
Test suite: 71 passed, 2 skipped, 1 pre-existing failure (above).

Not done (deliberately): a translated status string for `test_smoke` and the CSV-radio test
expectation update — both belong to the drawer-render change that predates this work.

- `#ha-connection` card lives in `app/templates/_panel_data.html` (lines ~64-89), rendered
  panel-level above the slot roster.
- The drawer (`#source-drawer`) lives in `app/templates/index.html`; its entity `<select>`
  and note (`#drawer-ha-note`) currently point "above" to the connection card.
- `app/static/ha_fetch.js` binds `#ha-base-url`, `#ha-token`, `#ha-test-btn`, `#ha-status`
  and manages the shared connection state (`statIds`, `haConnected`) + localStorage
  (`ha.base_url`, `ha.token`). The "Fetch history" button + progress also live in the
  roster card and depend on `haConnected`.
</content>
</invoke>
