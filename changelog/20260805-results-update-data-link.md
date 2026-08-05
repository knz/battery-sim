# Results screen — "Update your data" link under "Your energy use"

## Task specification

The results screen already carries a small ghost hyperlink "Edit contract & rates →" under
the "Cost savings" divider, pointing at `/w/{id}/edit#contract`. Add a similarly styled link
"Update your data →" under the "Your energy use during the selected period" divider, pointing
at the data editor screen (`/w/{id}/data`).

## High-level decisions

- **The link renders between the divider heading and the figure cards**, not after the band.
  The first attempt placed it beside the macro call in `_panel_results.html`, which put it
  *below* the cards; the user asked for it immediately under "Your energy use". Since that
  position is inside the macro's output, `data_glance` gained an optional `action` slot.
- **`action` is honoured by the `divider` frame only.** The macro is shared with panel ① on
  the data screen, where a link back to the data editor would point at the screen the reader
  is already on, so the `section` (card) frame ignores the slot. The link's markup and its
  `_()` still live in the panel-③ caller — the macro neither styles nor translates it.
- **Right-aligned on its own row** rather than on the divider line: DaisyUI's `divider-start`
  gives the label the start and lets the rule fill the rest, so a control on that line would
  fight the layout. `-mt-2` pulls the row up under the rule, matching the contract link's
  offset from the Cost savings divider.
- **Mirrors the contract link's markup exactly**: `flex flex-wrap items-center justify-end
  gap-1 -mt-2` wrapper, `btn btn-ghost btn-xs` anchor, `→` suffix, and a `data-*` hook
  (`data-energy-edit-data`) for tests.
- **No ⓘ button beside it.** The contract link has one because the euro figures need their
  provenance explained; the energy figures come from the dataset the link leads to, and a
  dialog repeating the link would be two controls to one destination.
- **Destination `/w/{id}/data` with no `mode=wizard`** — the reader is revisiting an existing
  workspace, not walking the creation wizard.

## Files modified

- `app/templates/_data_glance.html` — new optional `action` macro argument, rendered by the
  `divider` frame between the heading and the figures; header comment updated.
- `app/templates/_panel_results.html` — the link built into a `{% set %}` block and passed as
  `action=`; header comment updated.
- `tests/test_workspace_results.py` — a test pinning the link's presence, href, and its
  position between the heading and the first figure card. Verified to fail against the
  pre-change templates, so the ordering assertion is live rather than vacuous.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.po` — new msgid
  "Update your data →" extracted and translated (nl: "Werk je gegevens bij →").

## Current status

Implemented; test suite run for the results screen.
