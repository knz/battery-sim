# 2026-08-05 — UI/UX screens iteration

## Task Specification

Worktree for iterating on the application's UI/UX screens.

### Task 1 — site footer

Add a footer carrying two lines:

1. "This application does not collect your data and does not send it remotely."
2. "<app name> is a digital creation Raphael Poss. NO WARRANTY. Licensed as
   <license name>. Source code available."

with "Raphael Poss" linking to https://raphaelposs.com, "Source code available"
linking to the GitHub project, and "NO WARRANTY" opening a popup that clarifies
what is being disclaimed.

## High-Level Decisions

- Worktree `ui-ux-screens`, branch `worktree-ui-ux-screens`, based on `master`
  at c3ceef3. Isolated from the two other worktrees open on the same base
  (`packaging-release-params`, `user-docs`).

### Footer

Decided with the user before implementation:

- **On all four screens** — workspaces, workspace_edit, workspace_data,
  workspace_results — as a shared `_footer.html` partial. A privacy and licence
  notice that only appears on the home screen is easy to miss. There is no
  shared base template in this codebase (each screen is a standalone full page),
  so "shared" means an `{% include %}` in four places, matching how
  `_workspace_card.html` and the panels are already reused.
- **The NO WARRANTY popup is a daisyUI `<dialog class="modal">`**, page-level,
  matching the existing `#slot-info-dialog` / `#pending-dialog` / delete dialogs
  rather than introducing a second idiom (`<details>`) for the same job. Page
  level for the reason those dialogs already document: a `<dialog>` inside a
  subtree with `content-visibility: hidden` enters the top layer on
  `showModal()` and blocks clicks without ever being painted.
- **Fully translated.** Strings wrapped in `_()`, extracted, Dutch written, `.mo`
  recompiled — the rest of the UI is bilingual and a monolingual footer would be
  the only English text on a Dutch page.
- **The licence is named "GNU AGPL v3"** and hyperlinked to `LICENSE` in the
  GitHub repository. The project is AGPL-3.0-only (pyproject.toml). Short name
  so the footer line stays one line; hyperlinked so the text is reachable.

## Requirements Changes

_(none)_

## Files Modified

- `app/templates/_footer.html` — created. The two footer lines and the warranty dialog, plus
  the small delegated script that opens it.
- `app/templates/workspaces.html`, `workspace_edit.html`, `workspace_data.html`,
  `workspace_results.html` — the footer include added after `</main>` on each.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.{po,mo}` — the twelve
  new msgids extracted, translated and compiled.
- `app/static/app.css` — rebuilt (`npm run build:css`); Tailwind scans the templates, so the
  footer's utility classes only exist in the stylesheet after a rebuild.
- `tests/test_footer.py` — created. 13 tests.
- `tests/test_workspace_results.py` — its "every link resolves" test relaxed to allow the three
  footer URLs (see below).
- `changelog/20260805-ui-ux-screens.md` — this file.

## Rationales and Alternatives

Worktree rather than a plain branch: the user asked for one explicitly, and two
other worktrees are already open on the same base, so parallel work is expected.

**The attribution line is one translatable sentence, not concatenated
fragments.** It carries four interactive pieces (two external links, the
licence link, and the warranty button), so the naive spelling is to break it
into six template chunks and let the markup fall between them. That gives
translators word-salad and makes Dutch word order impossible to honour. Instead
the sentence is a single msgid with `%(name)s` holes, matching the two-step
translate-then-interpolate order the app already uses (`app/i18n.py`
`interpolate`, `templates/_msg.html`, the delete-dialog bodies).

**The warranty dialog is a plain-language summary that points at the real
text.** AGPL §15 and §16 are what is actually being disclaimed; the dialog
restates them in readable prose and links to `LICENSE` rather than claiming to
substitute for it. It also names the app-specific risk the generic clause does
not: the simulator's outputs are retrospective estimates computed from the
user's own data, not financial advice.

## Obstacles and Solutions

- **`test_every_link_and_form_action_on_the_page_resolves` failed** — it asserted that no link on
  the results screen is external, which the footer deliberately changes. Relaxed to an explicit
  three-URL allowlist rather than a scheme-wide skip, so a stray external link elsewhere still
  fails it. The URLs are not requested: the suite must pass offline.
- **`write_po` reflowed both catalogs** — a 1100-line diff for a 12-entry change. Replaced the
  round-trip with a line-oriented fill that only rewrites the empty `msgstr` following a target
  msgid; the diff is now the size of the change.
- **The Dutch footer arrived in the formal register (u/uw)** while the app's Dutch is informal
  throughout (127 `je`/`jouw` against 10 `uw`, and 9 of those 10 were the footer's own or obsolete
  entries). Legal-sounding copy invites the formal register. Rewritten per string — the verb forms
  change with the pronoun, so this was not a pronoun substitution — and pinned by a test.

## Dutch review (sub-agent, native-quality pass)

The footer's Dutch was written by an English-first author, so it was reviewed against the rest of
the catalog. Five genuine errors and four taste items were found and all were applied:

- **"digitale creatie" was a calque.** *Creatie* in Dutch belongs to fashion, advertising and
  menus — an artistic/promotional flavour a software footer does not want. Now "is gemaakt door",
  and "Gelicentieerd onder" → "Uitgebracht onder", the standard collocation for a licence release.
- **"naar elders" is literary/stilted.** Now "stuurt ze nergens naartoe".
- **"applicatie" → "app"**, matching the ~470 existing strings.
- **"rekenmachine" means the physical object** in Dutch, so calling the simulator one reads as a
  category error. Restructured to "Deze simulator rekent achteraf" — *achteraf rekenen* is the
  exact idiom for retrospective calculation.
- **An antecedent slip**, not spotted before the review: the paragraph calls the simulator "hij"
  throughout, then switched to "het is geen financieel advies". Now "hij is".
- **Number agreement** in the binding-text line: singular "de bindende tekst" with plural "zijn".
  The reviewer proposed pluralising the subject ("de bindende teksten"), but §15 and §16 are two
  clauses of ONE licence text, so a plural noun is semantically off. Used a free-relative subject
  instead — "Wat bindend is, zijn de artikelen 15 en 16" — which takes the plural verb naturally
  and keeps the singular sense. "de artikelen 15 en 16" is the standard citation form.
- Taste items applied: "wat betreft" → "voor"; the stacked "verlies van … verlies van …" collapsed
  (Dutch does not stack *verlies* the way English stacks "loss", so the third became "schade"); a
  comma after the fronted adverbial in the liability sentence; and curly quotes “ ” in the dialog
  title, matching the catalog's convention everywhere else.

Deliberately NOT changed: "zoals het is" for "as is". The formal alternative ("in de staat waarin
het zich bevindt") is exactly the legalese the dialog exists to avoid.

The review also confirmed the informal register is now complete — **no `u`/`uw` anywhere in the
live catalog**. This corrects an earlier note in this file: the one apparently-formal entry left
was in the obsolete `#~` section, not live. Nothing to align there.

## Verification

- Full suite: 1354 passed, 24 skipped, 0 failures — run BEFORE the Dutch review revisions.
- After the review revisions, the i18n-relevant subset only (`test_footer.py`, `test_i18n.py`,
  `test_no_english_leakage.py`): 218 passed. The full suite was not re-run — it carries benchmarks
  that take too long to be a per-change check (user's instruction). Nothing outside those three
  files asserts on Dutch strings, so the subset is the part that could plausibly have broken.
- The four screens rendered in a real browser (Playwright, via `tests/screenshot.py`'s helpers) in
  both languages: footer text correct, links live, dialog opens on click and closes on Escape, no
  console errors.
- The `| e | interpolate | safe` chain was mutation-checked — removing `| e` and `| safe` makes
  two of the new tests fail, so the assertions bite.

## Current Status

Task 1 (the footer) is complete and verified. Not committed — the working tree carries the
change on `worktree-ui-ux-screens`.

Open, for whenever the footer is revisited:

- The `en` catalog has 76 msgids that were already untranslated before this change. English falls
  back to the msgid so they render correctly, and they are unrelated to the footer — left alone
  deliberately rather than swept into this diff.
- ~~The one pre-existing formal-register Dutch string is the only `uw` left in the live
  catalog.~~ Withdrawn: the Dutch review found no `u`/`uw` anywhere in the live catalog. The
  entries that turned up in the original grep were in the obsolete `#~` section.
