# Make the source drawer transactional (explicit Confirm)

> Status: **implemented.** Created 2026-07-24. Follow-up on
> [20260724-entity-picker-in-drawer.md](20260724-entity-picker-in-drawer.md).

## Task specification (original request)

User prompt, verbatim:

> "I think I would prefer if the user would need to click a "confirm" button on the side panel
> to commit the changes, instead of having them committed implicitely whenever they change a
> control"

Today the drawer commits implicitly: picking Home Assistant + choosing an entity writes to
`slotState` immediately (updating the row label and the fetchable set), and Energy-Charts has
its own "Use this source" button that loads + reloads on click. There is no single explicit
commit step, and merely opening/closing the drawer can mutate committed state (the guessed
entity).

## Decisions (from the user, 2026-07-24)

- **Unified Confirm button.** One Confirm in the drawer commits whatever was staged:
  - Home Assistant → write the chosen source + entity into `slotState`, update the row label,
    make the slot fetchable.
  - Energy-Charts (backend_load) → do what "Use this source" does today: POST the slot load and
    reload. Replaces the separate "Use this source" button.
- **Close without confirm discards.** Escape / ✕ / backdrop / Cancel revert to the committed
  state; the row label and `slotState` are unchanged. Nothing commits until Confirm.

## Implementation approach

Introduce a drawer-local **draft** (staged source + entity) separate from the committed
`slotState`. All in-drawer controls write only to the draft. Confirm applies `draft → slotState`
(+ backend load/reload for a backend source). Cancel/close discards the draft. The row label and
`mappedSlots()` read only committed `slotState`, so nothing changes on selection or close.

## Implementation notes (the draft/commit split)

The crux is a drawer-local `draft = { slot, source, statId }` that is the ONLY thing the in-drawer
controls write to while the drawer is open. Committed per-slot state stays in
`slotState[name] = { source, statId, kind }`, the ONLY thing `updateSlotButton` and `mappedSlots`
read. Concretely:

- `openDrawer(btn)` seeds `draft` from the slot's committed `slotState` (source + statId), or a
  data-* fallback for a first open. It no longer creates or mutates a `slotState` entry.
- The source radios (`onSelectSource`) write `draft.source` only; a non-HA pick clears
  `draft.statId`. They toggle the entity picker / backend hint but never touch `slotState` or call
  `updateSlotButton`.
- The entity `<select>` change handler and `fillDrawerEntitySelect` read/write `draft.statId`. The
  heuristic `guessId` is staged into the draft as a visible default in the open dropdown, but is
  NOT committed — `fillDrawerEntitySelect` no longer calls `updateSlotButton`.
- One `#drawer-confirm` button (`confirmDraft`) is the single commit path. For an HA source it
  writes `draft → slotState[name]`, calls `updateSlotButton`, and closes; for a backend source it
  runs the load POST (the old `useBackendSource` flow, now `confirmBackend`) and reloads on success,
  leaving the drawer open with an error on failure. Confirm is disabled when no source is staged or
  a backend load is in flight (`updateConfirmEnabled`).
- `#drawer-cancel` (plus ✕ / backdrop / Escape) calls `closeDrawer`, which now discards the draft
  and never mutates `slotState` or the row label. The commit-on-close behaviour was removed.

**Confirm-with-no-entity decision.** Confirm is allowed for HA with an empty entity: it commits
`source = home_assistant, statId = ""`, so the row shows "Home Assistant · choose entity…" and the
slot is simply not fetchable (excluded by `mappedSlots`) until an entity is chosen. This matches the
existing row-label semantics and keeps Confirm from being blocked in a half-configured state; it is
reversible by reopening and picking an entity.

## Files modified

- `app/static/ha_fetch.js` — introduced the `draft` object; rewrote `openDrawer`, `closeDrawer`,
  `onSelectSource`, `fillDrawerEntitySelect`, the entity change handler; replaced `useBackendSource`
  with `confirmDraft` / `confirmBackend`; added `updateConfirmEnabled` and `selectedSource`; retired
  `drawerState` and `drawerUseBtn`; rewired the bottom (Confirm / Cancel). Updated the header
  comment to the staged-then-confirm model.
- `app/templates/index.html` — replaced the "Use this source" button (`#drawer-use-source`) with a
  transactional footer: `#drawer-confirm` (disabled by default) and `#drawer-cancel`. Kept
  `#drawer-backend-action` / `#drawer-backend-status` as the backend progress line. Updated the
  drawer comment block.
- i18n: new msgids "Confirm" / "Cancel" (NL "Bevestigen" / "Annuleren"); "Use this source" dropped.
  Extracted to `messages.pot`, updated + compiled `en` and `nl` catalogs.
- `app/static/app.css` — rebuilt via Tailwind (no new utilities needed, rebuilt for safety).

## Review (2026-07-24)

A sub-agent review found **no blockers and no should-fix items**. It audited every write site and
confirmed the core invariant: the only path that mutates committed `slotState`, the row label, or
triggers a backend load is `confirmDraft` (behind Confirm). Verified: `openDrawer` only reads
`slotState` to seed the draft (the old lazy `slotState[name] = …` creation is gone);
`onSelectSource`, `fillDrawerEntitySelect`, the entity change handler, and `closeDrawer` write only
the draft; reopening after a discard re-seeds from committed state; `mappedSlots` excludes a
staged-but-unconfirmed entity; Cancel/Escape/✕/backdrop all discard; Confirm/Cancel resolve EN+NL.
One nit (a §2.2 intro sentence that understated Confirm as backend-only) fixed.

Spec §2.2 updated: the drawer wireframe shows `[ Confirm ] [ Cancel ]` and a paragraph stating the
drawer is transactional (nothing takes effect until Confirm; Cancel/close discards).

## Current status

Done and reviewed. `node -c` parses; app imports; GET / renders 200 in EN + NL with the Confirm
control present and the old auto-commit-on-close/select path removed; `tests/test_slot_load.py` and
`tests/test_ingest_ws.py` pass (22).
