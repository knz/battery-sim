# Phase 3 — Edit workspace

Part of the workspaces restructure; plan in `20260726-workspaces-implementation-plan.md`,
spec in `specs/20-workspaces-ux.md` §2′.4 (the screen) and §2′.8 (the footer).

## Task specification

Build the edit-workspace screen: `GET /w/{id}/edit` and `POST /w/{id}/edit`, rendering and
writing the workspace title, the postcode, the grid connection, and the contract type.

From §2′.4, the rules that constrain the build:

- The **connection dropdown** offers ten presets (`1×10 A` … `3×80 A`), each writing
  `grid.phases` and `grid.fuse_a` and labelled with `connection_capacity_kw_display`.
  A stored combination that matches no preset must render as an extra, marked, selected
  entry — **snapping it to the nearest preset would silently change `max_import_kw`**.
- Two advanced collapsibles, whose contents survive being collapsed, summarised as
  "N values overridden".
- The **Contract box is always shown, never greyed** — a deliberate exception to §2.3's
  Inapplicable rule, called out in the spec.
- The **postcode is live, not pending**.
- `pricing_configured` is set on save (§2′.6) and never cleared automatically.
- Footer modes per §2′.8: `[ Cancel ] [ Save ]` when reached from a card,
  `[ ← Previous ] [ Next → ]` in the wizard, where `[ Next → ]` persists. `[ Cancel ]`
  warns about unsaved changes.

## High-level decisions

### The flagged risk: split the view, share the store

The plan asked this be settled at the start of the phase rather than during it: `POST /params`
validates the whole config and returns the whole panel, and two screens now write disjoint
halves of one document. Either reuse that route behind a `sections` filter, or split.

**Decided: a separate `POST /w/{id}/edit` route with its own view-model, reusing the parsing
and persistence layers.**

Reuse would in fact have worked for *parsing*. `parse_form` already inherits every absent
field from its `base` (`app/params_view.py:290`).

> **Corrected by the review below — the sentence that followed here was wrong.** It read:
> "and every checkbox is gated behind the `sections` marker, so a grid-only POST is safe by
> construction and needs no new mechanism". Neither half held. The checkbox paths are precisely
> the documented EXCEPTIONS to inherit-if-absent, so they are the one thing a partial POST is
> *not* safe from by construction; one of them (`topology.approximated`) had no gate at all; and
> the gate the others did have was a per-BOX name that this screen could not claim truthfully,
> because it draws a strict subset of one box's checkboxes. Two settings were being cleared on
> every save as a result. The mechanism this needed was a finer-grained section name — see
> "Review findings and fixes".

The reasons not to reuse are elsewhere:

1. **The response is a different document.** `POST /params` returns the `_panel_params.html`
   fragment for an `outerHTML` swap. The edit screen is a full page with its own footer and a
   redirect on success. Reusing means the route branches on which shape to return — the exact
   coupling the plan named as having made panel ② hard to reason about.
2. **`validate()` is whole-config.** A user editing only their connection could be handed a
   blocking error about a battery field this screen does not draw, with no input to attach it
   to. The edit screen needs issues filtered to its own field set.
3. **Title and postcode do not live in the same place.** The title is a `workspaces` table
   column, the postcode is in the config document. One route writes both; `POST /params` has
   no business touching the workspace row beyond `touch()`.

What is shared, and deliberately not duplicated: `parse_form`, the `FIELDS` coercion table,
`issue_message`, and `simconfig_store.save`. The edit route builds its candidate through the
same parser, so there is no second copy of coercion or validation anywhere.

## Decisions taken during the build

These are the questions the brief left to judgement, and how each was settled.

**No `csrf.require_same_site` on `POST /w/{id}/edit`.** `app/csrf.py` states its line explicitly:
"the line is drawn at 'can this request destroy something', not at 'is this request a POST'", and
`POST /w/{id}/params` is deliberately outside it as an idempotent overwrite of a local parameter
set with values a forging page chooses blind and cannot read back. This route has exactly that
shape — it overwrites four settings and a title, all recoverable by editing them back — so leaving
it uncovered is what the stated line implies. Two things make it worth restating rather than
assuming: it now also sets `pricing_configured`, which a forged request could set (unblocking a
toggle, not destroying anything); and a forged rename is more visible to the user than a forged
battery capacity, which arguably makes it *less* dangerous rather than more. If that judgement is
revisited, both parameter-writing routes should get the dependency together and on purpose — a
check on one and not the other would be the drift `csrf.py` warns against. Written into the
route's docstring so the omission reads as a decision.

**The wizard mode is a query parameter, `?mode=wizard`.** §2′.8's two modes differ only in the
footer and in where a successful save goes; everything above the footer is the same screen. A
second route would be a second render site for two buttons, and the phase-2 changelog's complaint
about `POST /params` branching on response shape applies just as well to a route branching on
footer shape. The POST also accepts a `mode` form field, so the mode survives a re-render after a
validation failure without depending on the form's action URL being rebuilt.

**The wizard's `[ Next → ]` lands on `/w/{id}/results` for now.** Step 2 is the configure-data
screen, which phase 4 builds; until then it would 404. Same reasoning and same temporary shape as
`POST /workspaces`'s destination (phase 2), and recorded in the route where the redirect is
written.

**An empty title keeps the current one.** The list identifies an analysis by its title and both
§2′.3 dialogs quote it, so a stored empty string leaves a card the user cannot tell apart from any
other. There is nothing on this screen a user could be trying to express by clearing the field.
Not specified either way.

**The postcode is stored as typed, stripped of surrounding whitespace only.** §2′.4 leaves format
validation open and says storing the string as typed is the safe default until a consumer needs a
parsed form; the strip is for browser autofill rather than for validation.

**The leakage test was extended now rather than in phase 6.** The plan puts extending
`tests/test_no_english_leakage.py` in phase 6, but the edit screen is a new surface with prose
nothing else scans, and phase 2's changelog already records that an unscanned new screen is how
strings quietly ship in English. `/w/{id}/edit` is a fifth entry in `_PAGES` with a 100-word floor
(it renders ~150), for the same "guard against collapse, not assert verbosity" reason the list's
60-word floor was set.

## Files modified

- `app/workspace_edit_view.py` — **new.** `CONNECTION_PRESETS`, `CONNECTION_LABEL`,
  `CONNECTION_LABEL_OFF_LIST`, `EDITED_FIELDS`, `ADVANCED_GRID_FIELDS`,
  `ADVANCED_PRICING_FIELDS`, `connection_value`, `parse_connection`, `connection_options`,
  `_overridden_count`, `edit_view`.
- `app/templates/workspace_edit.html` — **new.** The four boxes, both `<details>` panes, the
  two-mode footer, the discard/info/pending dialogs and three small scripts (dirty check, info
  dialog, pending affordance).
- `app/main.py` — `GET`/`POST /w/{workspace_id}/edit` added with a shared `_edit_page` renderer;
  `workspace_edit_view` imported; module docstring gains the edit-screen paragraph and two route
  table rows.
- `app/templates/_workspace_card.html` — the phase-2 note rewritten: `[ Update ]` now reaches a
  real screen, `[ Configure data ]` is the one action still leading to a 404.
- `tests/test_workspace_edit.py` — **new**, 32 tests.
- `tests/test_smoke.py` — three browser tests: the `[ Update ]` → edit → `[ Save ]` round trip,
  the dirty-check dialog in both its states, and a collapsed-pane submit.
- `tests/test_no_english_leakage.py` — `/w/{id}/edit` added to `_PAGES`; the floor expression
  extended with its own entry.
- `app/locales/*` — full `babel.cfg` workflow (extract with all three `-k` flags, update ×2 with
  `--no-fuzzy-matching`, translate, compile). 26 new msgids, all Dutch, zero fuzzy.
- `app/static/app.css` — regenerated (`npm run build:css`).

## Obstacles and solutions

**"1 values overridden".** The count was one msgid with a `%(n)s` hole, which reads wrong at 1.
Switched to `ngettext('%(n)s value overridden', '%(n)s values overridden', n)` in the template —
the idiom `_data_glance.html` and `_panel_results.html` already use for day counts — and
translated as a plural pair.

**Two assertions that would have passed against nothing.** `html.count("<details") == 2` matched
three, because the page's inline script has a comment naming `<details>`; and `"Previous" not in
html` for the card footer matched the same script's comment naming both modes' buttons. Scoped to
`<details data-advanced>` and to a `data-footer` wrapper respectively. Worth recording because
both had the shape of a passing test that asserts nothing — the failure mode phase 2's "minor 7"
also hit.

**`inner_text()` reports the summary line uppercased.** Tailwind's `uppercase` is a CSS transform,
so Playwright reads "1 VALUE OVERRIDDEN". Compared case-insensitively rather than by matching the
painted form, which would couple the test to a styling class.

**Rewriting the `.po` through `babel.messages.pofile` dropped the obsolete `#~` entries.** The
first translation pass round-tripped the catalog through babel's writer, which discarded the
commented-out msgid phase 2's review had superseded and rewrapped one unrelated string. Reverted
and redone as targeted text edits on top of `pybabel update`'s own output, so the only lines that
changed are the new entries.

## Rationales and alternatives

**Reusing `params_view.parse_form` rather than writing a second parser.** Confirmed in practice:
the edit form carries the two grid fields and the pricing block, and every setting it does not
draw — the whole battery box, the policies, the bands — survives by `parse_form`'s inherit-if-absent
rule with no new mechanism. A test (`test_the_edit_screen_inherits_settings_it_does_not_draw`)
pins it, because the failure would be silent: a user who renamed their analysis would find their
battery reset to appendix A's defaults.

**The connection travels as one `"<phases>:<fuse>"` token.** The alternative — a `<select>` plus
two hidden fields kept in step by script — is a second place for the pair to disagree, and the
`grid.phases` / `grid.fuse_a` pair is exactly what must not disagree. `parse_connection` is
tolerant of an unreadable value (keep both fields) rather than falling back to a default, for the
same reason `_enum_or_keep` is: resetting would move `max_import_kw` on a submission nobody made.

**`_overridden_count` compares against a fresh `SimulationConfig`, not a hardcoded table.** The
count then follows appendix A wherever appendix A moves, and a second copy of the defaults cannot
drift from the first.

**The two `[?]` contract keys are `app/features.py`'s existing ones, not new keys.** A feature key
names the FEATURE, not the screen it was clicked on, so interest registered from panel ② and from
here counts in one row — which is what `features.py`'s "never reused, never repointed" discipline
is protecting. Nothing was added to `FEATURE_KEYS`.

## What the spec got wrong, or left open

**§2′.4's dropdown wireframe prints two decimals throughout; the function it names does not.**
The list at §2′.4 writes `3 × 25 A  (17.25 kW)` and `3 × 63 A  (43.47 kW)`, but the same section's
normative sentence says each option is labelled "from `connection_capacity_kw_display` — the
rounded display figure", and that function rounds to one decimal at or above 10 kW specifically so
that 3×25 A comes out as **17.3**, which is what appendix A and background E-A publish. The two
cannot both hold. The function was followed, because it is what the prose names and what the
published figures say; the wireframe's figures appear to be exact values written out rather than
display ones. The visible consequence: seven of the ten entries read one decimal (17.3, 24.2,
27.6, 34.5, 43.5, 55.2, 11.5) where the wireframe writes two. Not changed in the spec here —
it is a wireframe-versus-prose conflict worth someone deciding rather than an implementation
choice, and `connection_capacity_kw_display`'s own docstring already flags its precision rule as
INFERRED from two published points.

**§2′.4's wireframe shows "Max export [ same as import ▾ ]" as a dropdown.** Rendered as the
ordinary blank-means-follow-import text field panel ② already uses, since `GridConfig.max_export_kw`
models exactly that (None = follow import) and a two-state dropdown over one nullable number would
need its own coercion. The hint text says "blank = same as import".

## Verification

**Suite: 1016 passed, 2 skipped, 0 failed** (baseline 967 / 2). The two skips are
`tests/test_ha_live.py`, unchanged. Of the 49 added, 32 are `tests/test_workspace_edit.py`, 3 are
Playwright, and 14 are the leakage scan's seven scenarios × two checks on the new page.

**Playwright: 29 passed** (26 before), Chromium installed and running here. The three new ones
drive the real screen: `[ Update ]` from a card through the title, postcode and connection
controls to `[ Save ]` and back to the re-rendered list with the new `3×63 A` badge; the dirty
check in both states (no prompt with nothing typed, prompt + `[ Keep editing ]` with something
typed, typing intact afterwards); and typing an override, collapsing the pane, saving, and finding
the value still there — the property `<details>` buys and the one nothing but a browser can check.

**Exercised out of the test suite, against a real temporary data dir.** `GET /w/local/edit` was
rendered and read as text against §2′.4's wireframe: the four boxes in order, the ten options with
their capacities, both advanced panes, the pending `[?]` on Fixed and Variable, and `[ Cancel ]`
/ `[ Save ]`. The off-list case was rendered from a stored `1×20 A` and comes back as
`1 × 20 A  (4.6 kW) — your stored setting`, selected, with the ten presets still below it and none
of them selected. A `POST` was run against the same directory and confirmed to write
`grid.phases=3`, `grid.fuse_a=63.0`, `postcode='1012 AB'`, the workspace row's title, and
`retained.pricing_configured=true`; a following `POST /params` left that flag set.

**Both locales rendered and read.** Dutch is complete on this screen — including the off-list
entry ("je opgeslagen instelling") and the singular plural form ("1 waarde aangepast"). The
catalog check reports 0 untranslated and 0 fuzzy for nl.

**i18n workflow as `babel.cfg` documents it**, all three `-k` flags and `--no-fuzzy-matching` on
both updates, then compile. 26 new msgids. The `en` catalog gains them as empty msgstrs, which is
that catalog's existing convention (an empty English msgstr falls back to the msgid).

## Review findings and fixes

An adversarial review of the phase-3 working tree found two blocking defects and one test that
asserted nothing. All three were reproduced end-to-end through the real routes before anything
was changed, and all three are fixed here. Written after the work, from what was observed.

### The shared root cause

Phase 3 reasoned that `parse_form`'s inherit-if-absent rule made a partial POST safe. That is
true of ordinary fields and false of checkboxes, which the function's own docstring names as the
exception: an unticked checkbox and an absent control are indistinguishable in a form body, so
each checkbox is gated on the `sections` marker instead. The edit screen is the first form that
draws a *strict subset* of a box's checkboxes, and the marker had no way to express that.

### Defect 1 — the edit screen cleared `policy.economic_guard`

`workspace_edit.html` emitted `sections="grid pricing"`, and `parse_form` read TWO checkboxes
under the `pricing` name: `policy.economic_guard` and `pricing.dal_weekends`. The edit screen
draws only the second. The first was therefore read as unticked on every save and cleared. It was
compounded in `main.py`, where `guard_was_submitted(form, stored)` returned True — both halves
held, `pricing` was claimed and `simulate_cost` was on — which disabled `simconfig_store`'s
carry-forward safety net. Reproduced through `POST /w/{id}/edit`: stored `economic_guard=True`,
303 back, stored `economic_guard=False`.

**The naive fix was measured and rejected.** Dropping `pricing` from the marker protects the
guard but puts `dal_weekends` behind a name the screen no longer claims, so unticking `+ weekends`
is read as "this build never drew the control" and silently ignored. Both variants were run:
`sections="grid pricing"` gave guard=False with a working untick; `sections="grid"` gave
guard=True with the untick ignored. Neither is correct, because one name covered two checkboxes
that the two screens render differently.

**Fixed by splitting the section so the marker means what it claims.** A section name is now
explicitly a claim about WHICH CONTROLS WERE RENDERED, not about a topic. `pricing` covers
`policy.economic_guard`; a new `pricing_advanced` covers `pricing.dal_weekends`. `_sections_for`
emits BOTH whenever the Pricing box is drawn, so panel ② is bit-for-bit unchanged — it draws both
checkboxes and claims both names. The edit screen claims `grid pricing_advanced`. `guard_was_submitted`
needed no logic change, since `pricing` is now exactly the guard's own name, but its docstring was
corrected: it had described the marker as meaning "the Pricing box", which is the conflation that
produced the defect.

*Alternative considered and not taken:* passing an explicit "which checkboxes did I draw" list
per form instead of section names. It is more direct, but it would have changed every existing
caller and every panel-② test for a defect that is really about one name being too coarse, and it
moves the same claim into a second vocabulary rather than fixing the first.

### Defect 2 — the edit screen cleared `topology.approximated`

The `phase_topology_unsupported(cfg)` branch in `parse_form` had **no section gate at all**, so
any form that did not draw the checkbox cleared it. Reproduced with a 3×25 A connection and a
1-phase battery — a genuinely unsupported topology, confirmed by asserting
`phase_topology_unsupported` was True on the stored config — where a `POST /w/{id}/edit` turned
`approximated` from True to False. That value is documented in `simconfig.py` and `params_view.py`
as the record of a deliberate user choice, never derived: clearing it re-raises §2.5(b)'s soft
block on panel ② and drops the approximation caveat from the results.

**Fixed by gating the whole branch on the existing `topology` section name**, consistently with
every other checkbox. The `else: approximated = False` clearing is deliberately preserved INSIDE
the gate: a form that did draw the topology box and moved to a supported one must still clear the
caveat, per §2.5(b). Only a form that never rendered the box now leaves the value alone.

### Defect 3 — a test that asserted nothing

`test_the_contract_choice_round_trips` called `_form(contract="dynamic")`, but `_form`'s key is
`pricing.contract`, so `contract=` injected an ignored junk key; and it stored `dynamic` (the
appendix-A default) then asserted `dynamic`, so no state changed. Deleting the whole
`pricing.contract` block from `parse_form` left it green — verified. Rewritten to drive both
directions (`fixed` → `dynamic` and `dynamic` → `fixed`) through the real key, and confirmed to
fail against that same deletion.

### Tests added, and what each was confirmed to catch

Each was run against the defective code — the fix reverted, the tests kept — and against
deliberately sabotaged variants of the fix, to check it discriminates rather than merely passes.

In `tests/test_workspace_edit.py`:

- `test_the_edit_screen_claims_only_the_checkbox_it_draws` — compares the rendered marker against
  the checkboxes actually in the page. Failed pre-fix (`'pricing_advanced' not in ['grid',
  'pricing']`).
- `test_a_stored_economic_guard_survives_a_save_from_this_screen` — failed pre-fix
  (`assert False is True` on `policy.economic_guard`).
- `test_unticking_weekends_on_this_screen_still_turns_it_off` — passed pre-fix, as it must, and
  FAILED against the naive fix (`sections="grid"`): `assert True is False`. This is the test that
  makes the naive fix non-viable rather than merely arguable.
- `test_a_stored_topology_approximation_survives_a_save_from_this_screen` — failed pre-fix
  (`assert False is True` on `topology.approximated`), with an in-test assertion that
  `phase_topology_unsupported` is True so the branch under test is genuinely reached.

In `tests/test_params_route.py` (panel ②, which must be unchanged):

- `test_panel_two_still_unticks_the_guard_and_still_carries_it_forward` — both behaviours in one
  test, plus a check that the marker the test drives is the one panel ② actually renders. Failed
  against a variant of `_sections_for` that emitted only `pricing_advanced`.
- `test_panel_two_still_unticks_dal_weekends` — nothing in the suite drove this before, which is
  how `_cost_form` could carry a `sections` value the panel did not emit. Failed against a variant
  emitting only `pricing`.
- `test_panel_two_still_clears_approximated_on_a_supported_topology` — the deliberate `else`
  branch. Failed against a variant with the gate added but the `else` dropped.

A `_rendered_sections` helper was added to `tests/test_params_route.py` for the parity checks.
`_cost_form` and `_form` still write their markers out by hand — several tests are ABOUT what a
given marker does, and scraping the render would make those circular — but the tests that compare
now read the real one, which closes the drift that hid this.

### Verification of the fixes

Suite: **1023 passed, 2 skipped** (1016 / 2 before the fix, on the same tree). Seven tests were
added: four in `tests/test_workspace_edit.py` and three in `tests/test_params_route.py`. The
contract test was rewritten in place rather than added, so it does not move the count. Playwright
ran: 29 passed. The only skips remain `tests/test_ha_live.py`.

Reproduction through the real routes against a temporary data dir, before and after, with the
marker scraped from the rendered edit screen rather than assumed:

    BEFORE   edit screen renders sections = 'grid pricing'
             economic_guard: before=True -> POST 303 -> after=False
             unsupported topology? True
             approximated:   before=True -> POST 303 -> after=False
             dal_weekends after untick on the edit screen: False

    AFTER    edit screen renders sections = 'grid pricing_advanced'
             economic_guard: before=True -> POST 303 -> after=True
             unsupported topology? True
             approximated:   before=True -> POST 303 -> after=True
             dal_weekends after untick on the edit screen: False

Panel ② was checked for regression three ways: the whole existing suite passed unmodified before
any new test was written (no panel-② test needed editing, which is the strongest available signal
that the split is behaviour-preserving); the three new panel-② tests assert both the untick and
the carry-forward directly; and each was shown to fail against a plausible wrong version of the
split.

**No user-facing strings were added or changed.** The changes are comments, docstrings, a hidden
field's value, Python control flow and tests. Confirmed by re-running `pybabel extract` with all
three `-k` flags and diffing the msgid set against the committed `.pot`: no msgid changes. The
`app/locales/*` diffs in the working tree are phase 3's own, untouched here.

### Documentation updated

`_section`, `_sections_for`, `guard_was_submitted` and `parse_form`'s docstrings now state that a
section name is a claim about rendered CONTROLS and that every checkbox path must be gated. The
template comment that recorded the reasoning error — "Both boxes here are unconditional, so the
value is constant" — was replaced, and `workspace_edit.html`'s header gained a fourth "easy to
break" rule naming the marker and both defects it caused.

## Current status

Phase 3 complete. `GET`/`POST /w/{id}/edit` are live, `[ Update ]` on a card reaches a real
screen, and `pricing_configured` is now set by something — which is the precondition phase 4.2's
cost toggle needs.

Three things carried forward, none decided here:

- **`[ Configure data ]` is now the only card action that 404s** (phase 4). It is still rendered,
  per §2′.2's action table.
- **The wizard's `[ Next → ]` destination is temporary.** It goes to `/w/{id}/results` because
  step 2 does not exist; phase 4 gives it a real target and phase 5 wires the sequence.
- **The same-site question for the two parameter-writing routes** is recorded above as a decision
  to leave both uncovered. It is one line each if that is revisited, and it should be revisited
  for both together.
