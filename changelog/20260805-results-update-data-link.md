# Results screen — "Update your data" link under "Your energy use"

## Task specification

The results screen already carries a small ghost hyperlink "Edit contract & rates →" under
the "Cost savings" divider, pointing at `/w/{id}/edit#contract`. Add a similarly styled link
"Update your data →" under the "Your energy use during the selected period" divider, pointing
at the data editor screen (`/w/{id}/data`).

## High-level decisions

- **Placement in `_panel_results.html`, not in the `data_glance` macro.** The macro in
  `_data_glance.html` is shared with panel ① on the data screen, where a link back to the data
  editor would point at the screen the reader is already on. Putting the link in the panel-③
  caller keeps the macro unchanged and the link scoped to the results screen.
- **Mirrors the contract link's markup exactly**: `flex flex-wrap items-center justify-end
  gap-1 -mt-2` wrapper, `btn btn-ghost btn-xs` anchor, `→` suffix, and a `data-*` hook
  (`data-energy-edit-data`) for tests.
- **No ⓘ button beside it.** The contract link has one because the euro figures need their
  provenance explained; the energy figures come from the dataset the link leads to, and a
  dialog repeating the link would be two controls to one destination.
- **Destination `/w/{id}/data` with no `mode=wizard`** — the reader is revisiting an existing
  workspace, not walking the creation wizard.

## Files modified

- `app/templates/_panel_results.html` — added the link block after the `data_glance` call.
- `tests/test_workspace_results.py` — added a test pinning the link's presence and href.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.po` — new msgid
  "Update your data →" extracted and translated (nl: "Werk je gegevens bij →").

## Current status

Implemented; test suite run for the results screen.
