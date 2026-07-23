# 2026-07-23 — Contract type naming: "dynamic", "fixed", "variable"

## Task specification

### Original user prompt (verbatim)

From `todo.txt`:

> UX/wireframes: the contract types should e just "dynamic", "fixed", "variable" (all are
> implicitely Dutch)

Standing guidance at the top of `todo.txt`:

> Whenever possible, it will be preferable to rewrite/simplify existing paragraphs -- we do
> not have users who know the previous version so there is no need to inform them of what
> has changed.

### Phase

Investigation only. No spec file edited in this phase.

## Findings (phase 1)

### Current naming, verbatim

There are exactly three contract types today, and the internal enum values are already
`DYNAMIC` / `FIXED` / `VARIABLE` (`specs/10-pricing.md` §6.5, `bare_supply_price()`).
The problem is confined to the **display labels**, which are asymmetric: the two
supplier-set forms carry a "Dutch" qualifier and the spot-following one does not.

| Location | Verbatim text |
|---|---|
| `02-ux-wireframes.md` panel ② radio group | `Contract   ( • ) Dynamic   (   ) Dutch fixed   (   ) Dutch variable` |
| `02-ux-wireframes.md` §2.1 summary line | ``(`dynamic`, `Dutch fixed`, `Dutch variable`)`` |
| `02-ux-wireframes.md` sub-panel frames | `┌ Dynamic ─`, `┌ Dutch fixed ─`, `┌ Dutch variable ─`, plus the prose "The **Dutch fixed** and **Dutch variable** sub-panels replace the Dynamic sub-panel" |
| `01-product-brief.md` §1.4 scope bullet | `Three pricing models: dynamic (spot-based), Dutch fixed, Dutch variable` |
| `10-pricing.md` §6.5 | `cfg.contract == DYNAMIC / FIXED / VARIABLE` — no "Dutch" |
| `18-dutch-electricity-background.md` E3.1 | `**Fixed (vast).**`, `**Variable (variabel).**`, `**Dynamic (dynamisch).**` |

So the naming already **drifts**: the domain files (10-pricing, 09-ingest, 18-background,
17-open-questions, appendix-a) use the bare three words consistently; only the two
user-facing files (02-ux-wireframes, 01-product-brief) prepend "Dutch" to two of the three.

### Root cause

The "Dutch" qualifier is a leftover disambiguator, not a domain distinction. It marks
*Dutch* fixed/variable as opposed to some other jurisdiction's — but the package is
single-jurisdiction throughout, and the README already says so. It is also applied
inconsistently (dynamic never got it), which is the tell that it is decorative rather than
load-bearing. Removing it is a vocabulary alignment: the UI adopts the vocabulary the
domain layer already uses.

### The variable-vs-dynamic risk

Genuinely distinct products, and the three bare words are **not** self-explanatory to a
user who does not already know the Dutch market. But the current labels do not help
either — "Dutch fixed" vs "Dutch variable" vs "Dynamic" conveys nothing about
supplier-set-quarterly vs EPEX-hourly. The information loss from shortening is therefore
approximately zero; the pre-existing gap is that **the radio group carries no helper
text at all**.

The distinction *is* stated, correctly and at length, in
`18-dutch-electricity-background.md` E3.1 — but that is a background document a user
filling in panel ② is not reading. `appendix-b-glossary.md` has **no** entry for any of
the three contract types.

## Clarifications obtained

Two questions were put to the user before editing. The answers below are the decisions
implemented.

1. **Does the radio group get helper text?** → **A single `ⓘ` next to "Contract"**, not
   per-radio sub-labels. It opens a popover covering all three types, weighted toward what
   separates variable from dynamic. The spec states what the popover shows, not merely
   that it exists.
2. **Do the three types get glossary entries?** → **Yes**, all three, cross-referencing
   E3.1.

## High-level decisions

- **The "Dutch" qualifier was decorative, not disambiguating**, and is removed rather than
  extended to the third type. Three pieces of evidence: it was applied to only two of the
  three types, though dynamic is equally Dutch; the entire domain half of the package
  already used the bare words; and the package is single-jurisdiction throughout, which
  the README establishes in its opening paragraph. No spec text anywhere distinguished
  "Dutch fixed" from "fixed". This is therefore a vocabulary alignment — the UI adopts the
  names the domain layer already used — not a rename.
- **The missing point-of-choice distinction is pre-existing, not introduced here.** The
  bare words are not self-explanatory to someone unfamiliar with the Dutch market, and
  variable/dynamic is the pair most easily confused. But "Dutch fixed" vs "Dutch variable"
  vs "Dynamic" conveyed nothing about supplier-set-periodically vs EPEX-hourly either. The
  radio group carried no helper text at all. The label change is information-neutral; the
  `ⓘ` closes a gap that predates it.
- **E3.1 is the single normative definition of the three types.** Q1 and Q2 both need the
  same three definitions, so they are not written out three times. E3.1 already states
  them correctly and at length, including the Dutch names and the battery consequence, and
  is left untouched. The `ⓘ` popover copy and the glossary rows are one line per type and
  both say in the text that they defer to E3.1 — so an editor revising a definition has a
  named single place to do it and two explicit pointers back to it. `01-product-brief.md`
  §1.4 and `10-pricing.md` §6.5 also link to E3.1.
- **§1.4's `(spot-based)` gloss is not dropped but levelled up.** The prior text glossed
  only dynamic. Rather than removing the one gloss or leaving the asymmetry, all three now
  carry a parenthetical of the same shape, consistent with the popover wording.
- **The enum is stated as normative in §6.5.** `DYNAMIC` / `FIXED` / `VARIABLE` are
  declared the vocabulary everywhere, user-facing labels included, with the rule that a
  label is the enum value lower-cased and carries no country qualifier. Stated because the
  labels had drifted from the enum, and stated at the point where the enum is defined.
- **No validation fixture added.** No fixture asserts on contract-type names today, and a
  relabel does not create an invariant worth guarding. Declining to add one follows the
  YAGNI discipline of the recent entries rather than the invariant-guarding pattern, which
  applies to numeric and structural invariants, not to display strings.

## Files modified

| File | Change |
|---|---|
| `specs/02-ux-wireframes.md` | §2.1 summary line contract names de-qualified; §2.3 radio group relabelled `Dynamic` / `Fixed` / `Variable` with an `ⓘ` affordance added, box padding re-aligned to the file's 80-column convention; `Dutch fixed` / `Dutch variable` sub-panel frames retitled and re-padded to 75 columns; new "The contract-type help affordance" subsection specifying the popover contents, the label/enum identity, and the deferral to E3.1 |
| `specs/01-product-brief.md` | §1.4 pricing-models bullet rewritten: all three types named bare, each with a parenthetical gloss of the same shape, linked to E3.1 |
| `specs/10-pricing.md` | §6.5 gains the statement that `DYNAMIC`/`FIXED`/`VARIABLE` are the vocabulary everywhere including user-facing labels, and the link to E3.1 |
| `specs/appendix-b-glossary.md` | Three term-table rows added for dynamic/fixed/variable with their Dutch names; a modelling-consequence entry marks the rows as summaries, names E3.1 as the single place to revise, and records the label/enum identity |

Unchanged deliberately: `18-dutch-electricity-background.md` E3.1 (the authoritative
definition, including its `(vast)` / `(variabel)` / `(dynamisch)` glosses);
`09-ingest-algorithms.md`, `15-data-quality-and-limits.md`, `17-open-questions.md`,
`appendix-a-defaults.md` and `README.md`, all of which already used the bare words;
`16-validation-harness.md`, per the no-fixture decision.

The two surviving occurrences of "Dutch dynamic" (`14-diagnostics.md` L207,
`17-open-questions.md` L85) are prose about Dutch *suppliers* and their settlement
practice, not contract-type labels. Left as written.

## Obstacles and solutions

- *The `ⓘ` glyph.* The file's ASCII boxes are padded by character count, and existing
  lines treat `ⓘ` as one character. The new radio line was padded to match at 80, verified
  against its neighbours rather than assumed.
- *Two `### Without …` headings had previously collided across panels in this file.* The
  new `### The contract-type help affordance` heading was checked for uniqueness, and it
  falls inside §2.3, which is how the glossary cross-reference names it.

## Current status

- [x] Inventory of current naming across all 20 spec files.
- [x] Drift between UX files and domain files identified.
- [x] Clarifying questions answered by the user (2026-07-23).
- [x] Edits applied to the four affected spec files.
- [x] Box-drawing alignment and cross-reference anchors verified.
- [ ] User review of the applied edits.

Not done, deliberately: `todo.txt` is unchanged and nothing is committed. Both are
separate steps.
