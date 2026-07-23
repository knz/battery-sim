# 20260723 — Writing up open question §8.1: statutory citation, rewrite, watch item

## Task specification

Apply to the specs the findings of three prior research passes, recorded in:

- `changelog/20260723-open-question-1-research.md` (legal research, then verbatim PDF
  extraction of the ACM Besluit modelcontracten 2026 and the consultation
  Wijzigingsregeling Energieregeling)
- `changelog/20260723-consultation-responses.md` (all nine consultation responses, plus
  independent verification of the statutory citation)
- `changelog/20260723-prototype-experiments.md` (experiments file, including its own
  independent citation verification)

Three changes were asked for:

1. Add the verified statutory citation (Energiewet art. 2.34 lid 7 and lid 9, as in force
   from 1 Jan 2027) to `specs/18-dutch-electricity-background.md` §E5.2, together with the
   two scoping conditions the consolidated text carries and E5.2 omitted (kleine
   aansluiting; and, for lid 9, that the supplier holds both a leverings- and a
   terugleveringsovereenkomst), and the fact that the monthly non-negativity assessment is
   statutory rather than an ACM interpretation.
2. Rewrite `specs/17-open-questions.md` item 1 (§8.1) to state everything established:
   the operative provision and the statutory phrase, ACM's tax-exclusive gloss and its
   confirmation that the floor binds every contract type, why the gap is structural, why
   supplier practice cannot disambiguate it, the consultation result with its caveats, the
   two readings, what would resolve it, and the possibility that nothing ever will.
3. Add a watch item on the final Energieregeling.

### User's request, verbatim (as relayed by the calling agent)

> set a watch on the final Energieregeling

and, on the scoping conditions:

> the floor (and the monthly assessment) apply only to a kleine aansluiting; lid 9 applies
> only where the supplier holds BOTH a leverings- and a terugleveringsovereenkomst with
> that customer.

Constraints given: do not commit; do not modify `todo.txt`; build on
`specs/19-prototype-experiments.md` and the §17 back-pointers created by another agent
rather than duplicating them; follow `todo.txt`'s guidance to rewrite rather than describe
what changed.

## Verification of the task's premise

The task warned that an earlier report had claimed §E5.2 cites the Elektriciteitswet 1998,
and that this claim was wrong. Checked directly before editing:

- `grep -n "Elektriciteitswet" specs/18-dutch-electricity-background.md` → no matches.
- §E5.2 states its four provisions with no statute and no article number anywhere.
- Appendix E-D cites "Eerste Kamer, dossier 36.611 — *Wet beëindiging salderingsregeling*",
  which is the correct vehicle.

So the edit is an **addition of an absent citation**, not a repair of a wrong one. This
matches what `20260723-prototype-experiments.md` independently found.

## High-level decisions

### The citation goes in E5.2 as a lead-in paragraph, not in each provision

E5.2's four provisions are written as a numbered list of rules with an "In the
specification" block below. Naming the statute once, above the list, keeps each provision
readable and avoids repeating "art. 2.34" four times. The per-lid attribution is then given
inside the provisions that need it (1 → lid 9, 2 → lid 7, 4 → lid 8).

### Verbatim Dutch is included for lid 9 only

Lid 9 is the provision whose exact wording is the substance of §8.1 — the phrase "de voor
de te leveren elektriciteit overeengekomen prijs" is what is undecomposed, and paraphrasing
it would lose the point. Lid 7's content is given in English prose; its two-limb
conjunctive test and its monthly non-negativity rule are both stated.

### §8.1 is rewritten as prose paragraphs, not a bullet list

The item now has to carry a statutory citation, a regulator's partial gloss, a negative
finding from market practice, a negative finding from a consultation with two caveats, two
readings with their evidence, and a resolution path. Written as short labelled paragraphs
inside the existing numbered item, which is the same shape §8.20 already uses (it is the
other long item in the file). Each claim is attributed to its source class — statute, ACM,
supplier practice, consultation, or spec choice — so the tax-exclusivity gloss cannot be
read as settling the markup question.

### The watch item is a separate numbered item, §8.21, marked as a watch

The spec has no convention for watch items. Options considered: a sub-block inside §8.1; a
new section in §18 E7; a separate §17 item. Chose a separate item, §8.21, opening with a
bold **Watch item** label, because §17 is the file the product owner reads for outstanding
work and a watch is outstanding work with a date attached, whereas E7 is a
what-is-not-known table rather than a to-do. §8.1 carries a pointer to it. The convention
introduced is minimal: one bold label, and the four fields the user asked for (what,
where, what to look for, when). If more watches accumulate they can move to their own file
without disturbing §8.1.

### The §8.14 back-pointer from E5.2

§8.14 (assessment period) is discussed in E5.2's "In the specification" block, which
already links it. That link is kept and the surrounding sentence rewritten so it rests on
the statutory text: lid 7 fixes the assessment at "gemiddeld gewogen over een periode van
een maand", so the "at least one month" reading — under which a supplier could use a
quarter — is an inference from the statute's silence on longer periods, not something the
statute states. This is a genuine tightening: the previous wording attributed "at least one
month" to an amendment, and the consolidated text says "een periode van een maand" without
"ten minste". Recorded as a wording change with the uncertainty made explicit rather than
resolved, because whether a longer period is permitted is not something the sources
consulted settle. §8.14's own text was left as it stands; it already flags the answer as
provisional.

## Files modified

- **Modified** `specs/18-dutch-electricity-background.md` — §E5.2 gains a lead-in naming
  Energiewet art. 2.34 (BWBR0050714) as in force from 1 Jan 2027; provision 1 gains the lid
  9 citation, the verbatim statutory phrase, ACM's tax-exclusive gloss with its source, and
  the two scoping conditions; provision 2 is rewritten on lid 7, with the monthly
  assessment stated as statutory and the two-limb reasonableness test added; provision 4
  gains the lid 8 attribution. The "In the specification" block gains the §8.1 pointer and a
  reworded §8.14 pointer. Appendix E-D gains the consolidated-Energiewet and ACM Besluit
  modelcontracten 2026 entries, and the internetconsultatie entry.
- **Modified** `specs/17-open-questions.md` — item 1 (§8.1) rewritten; new item 21 (§8.21),
  the watch item.
- **Created** this changelog.

Not modified: `specs/19-prototype-experiments.md` (X1 already states the relationship
correctly), `specs/10-pricing.md` (its §6.5 pointer to §8.1 remains accurate),
`specs/README.md`, `todo.txt`.

## Rationales and alternatives

- **Why not also revise §6.5's presets table.** The "Legal minimum" preset row reads
  "Statutory floor, valid to 1 Jan 2030", which remains accurate. Adding the citation there
  would duplicate E5.2 without adding a decision. Left alone.
- **Why not state a preferred reading in §8.1.** All three research passes concluded the
  question is undetermined in the instruments that exist. Picking a reading in a
  decisions-owed file would misrepresent that. The spec's existing choice (`bare = spot +
  markup`) stays recorded as a choice.
- **Why the consultation finding is stated with both caveats in the spec text, not just
  here.** Absence of comment is weak evidence and the spec is the document that will be
  read later without the changelog beside it.

## Obstacles and solutions

- Two conflicting numbers for the lid carrying the floor (lid 8 as tabled, lid 9 as
  enacted) — resolved by two independent verifications against the consolidated text, both
  recorded in the prior changelogs; the spec cites lid 9.
- E5.2 provision 2's "at least one month" phrasing does not match the consolidated lid 7 —
  reworded to quote the statute and mark the longer-period question as an inference.

## Follow-up — the assessment period, ruled on and propagated

The E5.2 rewording raised an inconsistency: E5 now quoted lid 7's "gemiddeld gewogen over
een periode van een maand", while §6.5, §8.14 and appendix A still asserted the law
requires "at least" one month. Referred to the user.

### The user's ruling, verbatim as relayed

> **Decision: state the statute exactly, and mark longer periods as unverified.**

with the calibration instruction:

> the statute says "een periode van een maand". It does not say "ten minste een maand" and
> it does not say "precies een maand". State exactly that, and mark both the fixed-period
> and minimum-period readings as unresolved rather than asserting either. Do not let the
> correction overshoot into claiming the statute forbids longer periods — silence is
> silence in both directions.

### How it was applied

The claim that changed is what the spec says about the *law*. The `feedin_floor_period`
capability is untouched — it remains configurable everywhere, with the calendar month as
default, because the default now rests on "the period the statute names" rather than on
"the shortest the law permits". That is the same value defended on different grounds.

Both readings are stated and neither is adopted:

- **Fixed-period reading** — one month is the prescribed window, the parameter has one
  lawful value, the longer settings are stress tests.
- **Minimum-period reading** — longer windows are lawful, they absorb more negative
  intervals, and a calendar-month default is optimistic.

§8.14 was re-posed rather than patched, because the reframing changes what it asks. It
previously asked which period to default to; it now asks first whether the period is a
parameter at all, and only then, conditionally, what the default should be. It also names
the escape route: X6 may show the period reaches no number the user sees, in which case the
legal reading does not have to be resolved before shipping and the parameter can be fixed
at one month.

X6's structure was left as the other agent wrote it. Only its **Question** and **Decision
it informs** were adjusted, so that the experiment asks both "what does a longer period
cost" and "does the period matter at all given the statute may fix it", and so that its
decision branches on the two readings. The `§8.14` pointer was already present.

Two places beyond the three named in the instruction also carried the claim and were
brought into line:

- `specs/appendix-a-defaults.md` — the `feedin_floor_period` row said "Shortest period the
  law permits, so the most favourable", and the `feedin_floor_mode` row said the law
  assesses over "≥1 month". Both restated.
- `specs/15-data-quality-and-limits.md` — checked and **not** changed: it says the floor is
  assessed over a calendar month "by default" and makes no claim about what the law
  permits, so it was already accurate.

One phrase in §6.5 consequence 2 and in `15-data-quality-and-limits.md` — that assessing a
short window whole is "a weaker constraint than the law imposes" — was left alone. It holds
under both readings, since a window shorter than a month is shorter than the statutory
period either way.

### Files modified in this follow-up

- `specs/10-pricing.md` — §6.5 consequence 3 restated on lid 7's exact wording, with the
  longer-period question marked unverified in both directions and the parameter's continued
  existence explained.
- `specs/17-open-questions.md` — §8.14 re-posed as "is it a parameter at all?", with the two
  readings, the explicit non-claim about silence, and the X6 escape route.
- `specs/19-prototype-experiments.md` — X6 Question and Decision-it-informs only.
- `specs/appendix-a-defaults.md` — two table rows.
- `specs/18-dutch-electricity-background.md` — provision 2 and the specification block
  tightened so the silence is marked as cutting both ways, matching the other files.

## Current status

Complete, uncommitted. Open for the user:

- Whether §8.21 is the right home for the watch item, or whether watches belong in their
  own file once there is more than one.
- §8.14 now poses a legal question the sources consulted do not answer. If it matters
  before X6 can run, the parliamentary history of the amendment that inserted the
  non-negativity rule is the place a "ten minste" that was dropped on adoption would show
  up — not searched for in this pass.
