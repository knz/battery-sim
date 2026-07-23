# Prototype follow-up experiments (§19)

## Task specification

Add a new spec file tracking follow-up experiments to run against the prototype once it
exists, cross-linked with the §17 open questions. Plus a prerequisite citation
verification against the consolidated Energiewet.

### User's request, verbatim

> Regarding the point about a parameter maybe not mattering for the end user: yes we will
> want to explore whether or not a parameter matters, later. For this add a new file which
> tracks some followup experiments we will want to run with the prototype, towards both
> informing the user ('does this parameter really matter?') and the implementation ('can we
> simplify this feature?')

### Scope as elaborated by the calling agent

Two audiences per entry, each named explicitly:

- **User-facing** — does the parameter meaningfully change the answer the user sees? If
  not, the UI can stop asking, ask less prominently, or say it rarely matters.
- **Implementation-facing** — if a parameter, policy, code path or diagnostic changes no
  outcome, can it be simplified or removed?

Each entry must carry: the question, the method, the decision it informs, the data it
needs, and a position in a priority ordering.

## High-level decisions

### §19 is measurement; §17 stays decision

Made explicit in both files' purpose blocks. §17 collects what must be **decided** — product
owner's calls that no amount of measurement settles, because they are judgements about what
the tool should do. §19 collects what can be **measured** once a prototype runs. The two are
not redundant: a measurement does not decide anything by itself, but it can change what is
being decided, and in the best case dissolve the question. If a parameter provably changes
nothing on realistic input, §8.1 stops being "which reading of the law is right" and becomes
"should we expose this at all".

Kept as separate files per the user's instruction, cross-linked both ways.

### The admission rule is a filter, not decoration

An experiment earns a place only if a decision would come out **differently** depending on
the number. Each entry states what would be done under each outcome. This was applied while
drafting and did remove candidates — see "Rejected candidates" below.

### Experiments are labelled X1–X13, not E1–E13

The obvious labelling collided with the background document's `E` prefix (`E1.4`, `E5.2`,
Appendix `E-A`), which README explicitly reserves so background references never collide
with the specification's own `§n.m`. Renamed to `X` and the README's prefix paragraph now
documents both. Caught during link validation, after an initial draft had used `E`.

### The file is §9, following file 18 in the numbering

Files are numbered `NN-topic.md` with a matching `§` heading. `19-prototype-experiments.md`
carries `# 9. Prototype experiments`, matching how `17-open-questions.md` carries `# 8.`.

## The thirteen experiments

Ordered by what each unblocks, not by interest.

| # | Experiment | Serves | Data | Informs |
|---|---|---|---|---|
| X1 | Does the feed-in floor base matter? | Both | Synthetic, then one year | §8.1 |
| X2 | Cycle-life cost sensitivity | User | One year | §8.3 |
| X3 | Do the two perfect-foresight runs differ? | Implementation | Synthetic, then one year | §8.19 |
| X4 | Does `economic_guard` change anything? | Both | One year | — |
| X5 | Is the resolution bias large enough to act on? | User | Several households | — |
| X6 | Does the feed-in floor assessment period matter? | Both | One year | §8.14 |
| X7 | Does the floor top-up line ever read nonzero? | User | Several households | §8.15 |
| X8 | Does `supplier_settlement` change the euro figure? | Both | Several households | §8.12 |
| X9 | Does the policy matrix have a stable winner? | Both | Several households | §8.4, §8.17 |
| X10 | Does the benchmark's export permission matter? | Implementation | Synthetic, then one year | §8.2 |
| X11 | How often do the epoch heuristics fire, and how often are they right? | Both | Several households | §8.13 |
| X12 | Does standby draw survive as a separate line? | Both | One year | — |
| X13 | Are the DP discretisation levels adequate? | Implementation | Synthetic | — |

X1–X5 were supplied as known-good starting points by the caller. X6–X13 were derived from
the specs, mostly from appendix A defaults whose rationale reads as a guess, from
diagnostics that may rarely fire, and from thresholds with no stated derivation.

Notes on the derived ones:

- **X6/X7** both concern the feed-in floor term. They are separate because they ask
  different questions of the same quantity: X6 sweeps `feedin_floor_period` and asks what
  the choice costs (§8.14); X7 asks only how often the term is live at all under defaults,
  which is the frequency §8.15's display recommendation rests on. X7 explicitly piggybacks
  on X6's instrumentation.
- **X9** merges §8.4 (policy matrix UI) and §8.17 (keep D1 without PV) because both turn on
  one measurement — how much the policy choice moves the result, and whether the winner is
  predictable.
- **X11** targets the epoch heuristics. §8.13 asserts capacity-change detection produces too
  many false positives; that assertion has no evidence behind it. The method requires ground
  truth collected *before* running detection, and requires households with no installation
  events, which is where false positives live. Also flags the undeclared-battery
  `flat_top_fraction > 0.3` threshold as having no stated derivation.
- **X12** questions whether run B (the standby-isolating simulation pass) is separable — if
  the analytic estimate matches it, a full simulation pass could be dropped from every
  request. Guarded: the two should diverge near SoC limits, so that case must be tested
  rather than assumed away.
- **X13** targets `dp_soc_levels = 101` / `dp_action_levels = 41`, which appendix A states
  without derivation, while §6.12 notes the interpolation-vs-snapping choice avoids "a
  systematic pessimism bias of several percent" — implying the discretisation is coarse
  enough to matter. Purely synthetic, runnable the day the DP works.

### Rejected candidates

Applied the admission rule and dropped these:

- **Does `roundtrip_efficiency` matter?** It obviously does, monotonically, and fixture 2
  already pins its arithmetic. No decision hangs on measuring it.
- **Does the timestamp-misalignment detector fire in practice?** Tempting, but its decision
  is already made: §6.17 reports and offers, never applies. Whether it fires often changes
  nothing about what the app does. Would have been "interesting to know" only.
- **How long does a run actually take?** A performance question, not a
  does-this-parameter-matter question. Belongs in ops. Folded into X13 and X3 where run time
  bears on a real choice.
- **Does `has_pv` / `simulate_cost` defaulting matter (§8.16, §8.18)?** These are friction
  and discoverability questions about user behaviour, not about whether a number changes.
  They need user testing, not a simulator run. Deliberately left with no experiment pointer.

## Files modified

- **Created** `specs/19-prototype-experiments.md` — §9, thirteen experiments, purpose block,
  the §8-vs-§9 distinction, the two-audiences framing, the admission rule, the three data
  tiers, priority table, and a closing note on recording results without deleting entries.
- **Modified** `specs/17-open-questions.md` — added a "Read with" line to the purpose block
  stating the decided/measured split; added `→ experiment Xn` back-pointer lines to §8.1,
  §8.2, §8.3, §8.4, §8.12, §8.13, §8.14, §8.15, §8.17 and §8.19, in the same style as the
  existing `→ §6.5` reference lines.
- **Modified** `specs/README.md` — Files table row after 18; `§9` row in the section-number
  table; `X` prefix documented alongside the existing `E` prefix explanation; version block
  bumped to 1.2 with a "Changes in 1.2" entry following the existing block's convention, and
  the status line now names both §17 and §19.
- **Created** this changelog.

`specs/18-dutch-electricity-background.md` was **not** modified, per instruction.

## Citation verification — Energiewet artikel 2.34

**Outcome: established confidently. The 50% floor is artikel 2.34, lid 9. The
redelijke-vergoeding duty is lid 7.**

Verified against the consolidated future text of the Energiewet on wetten.overheid.nl:
BWBR0050714, version "Toekomstige tekst van 01-01-2027 t/m 30-09-2030", retrieved
2026-07-23 via the print view
(`https://wetten.overheid.nl/BWBR0050714/2027-01-01/afdrukken`). Artikel 2.34 sits in
Hoofdstuk 2, Afdeling 2.3 and has ten leden. Verbatim:

> **7.** De actieve afnemer ontvangt voor de teruggeleverde elektriciteit een redelijke
> vergoeding, die in het geval van een actieve afnemer met een kleine aansluiting gemiddeld
> gewogen over een periode van een maand niet kan worden vastgesteld op een negatief bedrag.
> Een vergoeding is niet redelijk indien die vergoeding: a. onevenredig laag is gezien de
> kosten en baten van de marktdeelnemer; en b. niet concurrerend is.

> **9.** Indien een marktdeelnemer een leverings- en terugleveringsovereenkomst heeft met een
> actieve afnemer met een kleine aansluiting, dan bedraagt de redelijke vergoeding, bedoeld
> in het zevende lid, tot 1 januari 2030 niet minder dan 50% van de voor de te leveren
> elektriciteit overeengekomen prijs.

Lid 8, which the tabled amendment 36611 nr. 17 would have carried the floor in, is in the
adopted text a different provision — that feed-in-related costs may be charged only to the
active customers who cause them. This confirms renumbering on adoption, which was the
hypothesis recorded in `20260723-open-question-1-research.md`. Both the ACM Besluit
modelcontracten 2026 and the consultation Wijzigingsregeling Energieregeling were correct to
cite lid 7 and lid 9; the lid-8 attribution from the amendment as tabled is superseded.

Two further points the consolidated text settles, both worth carrying into any spec edit:

1. The one-month non-negativity assessment lives in **lid 7**, in the same sentence as the
   duty — not in a separate provision. It is scoped to "een actieve afnemer met een kleine
   aansluiting". This bears on §8.14 and on E5.2 provision 2.
2. The 50% floor in lid 9 is likewise scoped to a **kleine aansluiting**, and applies only
   where the supplier holds *both* a leverings- and a terugleveringsovereenkomst with that
   customer. Neither qualification appears in the current E5.2 wording.

**Recommended citation, for the user's review before it is applied:**
Energiewet (Stb. 2024, 424; BWBR0050714), artikel 2.34, zevende lid (redelijke vergoeding,
non-negativity over one month) and negende lid (50% minimum until 1 January 2030), as those
provisions read from 1 January 2027.

**No spec edit was made.** Per instruction, `18-dutch-electricity-background.md` is
untouched pending review.

### One finding that changes the framing of the correction task

The task described §18 as "currently attributing the 50% feed-in floor to the
Elektriciteitswet 1998" in E5 and Appendix E-D. On inspection that attribution is **not
present**. `grep` for "Elektriciteitswet" over the file returns nothing. E5.2 describes the
four provisions without naming a statute or an article at all, and Appendix E-D cites
"Eerste Kamer, dossier 36.611 — *Wet beëindiging salderingsregeling*", which is the correct
vehicle.

So there is no wrong citation to correct. What exists is an **absent** one: §18 currently
states the rules without pointing at the provision that carries them. The verified citation
above would be an addition rather than a correction, and E5.2's provisions 1 and 2 would
additionally gain the kleine-aansluiting scoping they currently omit. Flagged rather than
acted on, since the instruction was to hold for review either way.

## Obstacles and solutions

- Direct article-level URLs on wetten.overheid.nl 404, and the full-law HTML page truncates
  before artikel 2.34 when fetched. Solved by fetching the `/afdrukken` print view (1.4 MB)
  with curl and extracting the article locally.
- The Energiewet's BWB number was not obvious; an early guess (BWBR0049424, BWBR0048887)
  404'd. Found via search: BWBR0050714.
- The initial `E`-prefix labelling for experiments collided with the background document's
  reserved `E` prefix. Renamed to `X` and documented in README.
- A naive slug function produced 74 false-positive broken anchors on first validation.
  Corrected; 14 pre-existing failures remain, all pointing at `02-ux-wireframes.md`
  headings containing `①②③` glyphs. None were introduced by this task and none are in the
  new file.

## Current status

Complete, uncommitted.

Open for the user:

- Whether to apply the verified artikel 2.34 lid 7 / lid 9 citation to §18 E5.2 and Appendix
  E-D, and whether to add the kleine-aansluiting scoping while doing so.
- Whether the X1–X13 set is the right scope, or whether entries should be added or cut.
- Whether the priority ordering matches what the product owner actually wants answered
  first. The current ordering favours what unblocks a pending §8 decision; an alternative
  ordering by cheapness would put X13, X10 and X3's synthetic halves first.
