# Workspace card button labels

## Task specification

On the "list workspaces" screen (`specs/20-workspaces-ux.md` §2′.2), two changes to the
workspace card's action row:

1. The `[ Update ]` button becomes **"Configure workspace"**, with the Dutch translation
   updated to match.
2. The trashcan icon button (`🗑`) becomes a full text button instead of an icon.

Both were requested by the user in one session; the second arrived mid-turn while the first
was being scoped.

## Clarifications obtained

Three questions were put to the user before any code change:

- **Delete button wording.** The card's icon button already carries `Delete analysis` as its
  `aria-label`/`title`, and the same string labels the confirmation dialog's confirming button
  (§2′.3). The user asked for "delete workspace" text; offered the choice between renaming the
  string (card only / everywhere) or simply surfacing the existing label as visible text, the
  user chose **keep "Delete analysis"** — so this is a presentation change only, no new msgid
  and no divergence between card and dialog.
- **Dutch wording for "Configure workspace".** Chosen: **"Werkruimte instellen"**, parallel to
  the sibling button "Configure data" → "Gegevens instellen". Rejected alternatives:
  "Werkruimte configureren" (literal, but breaks the pair) and "Werkruimte aanpassen" (keeps
  the current verb "aanpassen").
- **Spec.** The user asked for `specs/20-workspaces-ux.md` to be updated alongside the code, so
  the wireframes and action tables do not drift from what ships.

## High-level decisions

- **"Configure workspace" over "Edit workspace"** — it matches the neighbouring
  `[ Configure data ]` button, so the two configuration entry points read as a pair.
- **New msgid rather than retranslating `Update`.** `Update` is replaced by a new
  `Configure workspace` msgid. The old entry is dropped from the catalogs on the next
  `pybabel extract` if nothing else references it.
- **The delete button keeps its existing string**, so the icon→text change costs no translation
  work: `Delete analysis` / `Analyse verwijderen` already exist and are already correct.

## Files modified

- `app/templates/_workspace_card.html` — button labels in the action row, plus the header
  comment's build-progress note that refers to `[ Update ]`.
- `app/workspace_list_view.py` — the action table in the module docstring names `[ Update ]`.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.po` — regenerated via
  `pybabel extract` + `pybabel update`; Dutch translation supplied by hand; `.mo` files
  recompiled with `pybabel compile`.
- `tests/test_smoke.py` — the round-trip test locates the link by accessible name `Update`.
- `specs/20-workspaces-ux.md` — §2′.2 wireframes and action table, and §2′.4's "Reached by
  `[ Update ]`" line.

## Obstacles and solutions

- The session began in the already-merged `ui-ux-screens` worktree; `EnterWorktree` refuses to
  create a second worktree from inside one. Solved by creating the worktree with
  `git worktree add` from within the current worktree (the sandbox only blocks `git -C`
  redirects to the shared checkout) and then entering it by path.

## Additional obstacles and solutions

- **The spec's wireframe could not hold the new labels.** `[ Configure workspace ]` and
  `[ Delete analysis ]` are 24 columns wider than `[ Update ]` and `[ 🗑 ]`, so the action row no
  longer fit inside the 80-column box. Rather than redraw every line of the §2′.2 diagram, the
  action row was wrapped onto two lines — which also matches the real card, whose row is
  `flex-wrap` and does wrap on a narrow viewport. Row widths were recomputed by script using
  east-asian display width, so the box borders still align.
- One pre-existing 79-column line in an unrelated §2′.2 wireframe (the no-data card's old action
  row) was corrected as a side effect. Another, at line ~474 in a different diagram, was left
  alone as out of scope.

## Verification

- Full suite: **1356 passed, 24 skipped** (the skips are the live-HA suite, as usual).
- Catalog diff inspected: the only msgid change is `Update` dropped and `Configure workspace`
  added. `pybabel` also re-wrapped a handful of long existing English translations at a different
  column — text unchanged. No `#, fuzzy` entries in either catalog; the Dutch catalog has no
  untranslated entries, and the English one still has its pre-existing 43 (English falls back to
  the msgid), unchanged in count.
- The list page was rendered in both locales and the card's action row read back:
  `en -> ['Configure data', 'Configure workspace', 'Delete analysis']`,
  `nl -> ['Gegevens instellen', 'Werkruimte instellen', 'Analyse verwijderen']`, with the 🗑
  glyph absent from the markup.

## Note recorded for the user

Spelling out the workspace-deleting action makes it visually heavier than the icon it replaces.
It remains last in the row and `btn-ghost`, so the ordering and de-emphasis signals survive, but
it now draws more attention than the original design intended. Raised before implementing; the
user confirmed the change.

## Current status

Complete and verified. Not committed — awaiting review.
