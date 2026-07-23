# 2026-07-23 — Scope of the "no regime mixing" rule

## Task Specification

Original todo item (from `todo.txt`):

> "regimes must never been mixed within one calculation" -> this only applies to
> pricing. For kWh usage and benefits of a battery, it's OK to mix pre-2027 and
> post-2027 data.

The specs currently state a hard rule that pre-2027 (net metering / salderen) and
post-2027 regimes must never be mixed within one calculation. The rule is to be
relaxed so that it applies **only** to pricing/cost computations. Energy-flow
(kWh-level) simulation and energy-savings metrics MAY span a period that crosses
the regime boundary.

Phase 1 (this session) is **investigation only**: no spec file may be edited.
Deliverables: inventory of affected passages, proposed edits in spirit, and a list
of clarifying questions for the user.

Repo convention: rewrite/simplify paragraphs in place; no "changed from X" notes,
since there is no existing user base.

### User's answers to the clarifying questions (verbatim)

> 1. Wording clarification only. No per-interval / date-driven regime selection in v1.
> 2. The 1 Jan 2027 calendar crossing is invisible in v1 — not an epoch boundary, no new
>    epoch machinery. Leave 13-configuration-epochs.md, 07-internal-representation.md and
>    the epoch-related parts of 15-data-quality-and-limits.md untouched.
> 3. (Contingent, now settled by 1+2): single energy figure for the whole window; a single
>    cost figure computed under the one selected regime, labelled as counterfactual. No
>    cost splitting or suppression.
> 4. (Contingent, now settled): no new UI warning for boundary-spanning windows. The
>    existing §1.3 counterfactual framing covers it. Do not touch 02-ux-wireframes.md.
> 5. Yes — state the general principle once (energy-flow simulation is regime-independent;
>    only cost accounting is regime-bound) in §1.3 of 01-product-brief.md, and reference it
>    from 10-pricing.md.
> 6. Yes — classify the metrics: perfect foresight and the cost waterfall are
>    cost-bound/regime-scoped; saved_kwh, saved_pct, EFC, self-consumption and
>    self-sufficiency are regime-free energy metrics. Note this where the rule is stated,
>    and add a brief note in 12-metrics-and-benchmarks.md if that is the natural home for
>    it.

## High-Level Decisions

Six questions were put to the user after the investigation; the answers below are the
decisions this session implements.

1. **Wording clarification only.** No per-interval or date-driven regime selection in v1.
   The simulator continues to apply one selected regime to the whole window.
2. **The 1 January 2027 calendar crossing is invisible in v1.** It is not a configuration
   epoch boundary and gains no epoch machinery.
3. **A boundary-spanning window yields one energy figure for the whole window and one
   cost figure** computed under the one selected regime, labelled as counterfactual. No
   cost splitting, no cost suppression.
4. **No new UI warning** for boundary-spanning windows; the existing §1.3 counterfactual
   framing covers it.
5. **The general principle is stated once** — energy-flow simulation is regime-independent,
   only cost accounting is regime-bound — in §1.3 of the product brief, and referenced
   from the pricing spec.
6. **Metrics are classified explicitly.** The cost waterfall and the perfect-foresight
   benchmark are cost-bound and regime-scoped; `saved_kwh`, `saved_pct`, `efc`,
   `self_consumption`, `self_sufficiency` and `conversion_loss` are regime-free energy
   metrics.

## Investigation findings (phase 1)

The rule is stated in three places and implied in three more:

- `specs/01-product-brief.md:59-62` — the primary normative statement ("Regimes must
  never be mixed within one calculation. Not per interval, not per epoch, not as a
  blend."), inside §1.3, which frames the regime as a fixed decision.
- `specs/18-dutch-electricity-background.md:365` — "never mix regimes within one
  calculation", in the E4.2 domain-background warning.
- `specs/18-dutch-electricity-background.md:367-371` — the "In the specification" note
  ("mixing the two within one calculation must not be expressible").
- `specs/10-pricing.md:158-161` — the pre-2027 extension point, described as a separate
  netting *stage*, justified by the no-mixing rule.
- `specs/01-product-brief.md:47-49`, `specs/appendix-b-glossary.md:13,29-30` — restate
  "pre-2027 out of scope" plus the extension point.
- `specs/15-data-quality-and-limits.md:36-45` (assumption 8) and
  `specs/01-product-brief.md:63-68` — the *behavioural* half of the caveat (load profile
  held fixed across the regime change). Related but distinct; likely unaffected.

Key observation: as written, "regime" is a property of the **pricing configuration**, not
of the data's calendar dates. The simulator applies one chosen regime (2027) to whatever
window the user selects; nothing in the specs currently reads the calendar date of an
interval to pick a regime. So today the no-mixing rule is already about pricing only —
but it is worded in absolute terms ("one calculation", "not per epoch") that read as
covering the whole simulation, energy flows included. The requested change is therefore
mainly a clarification/scoping edit rather than a behavioural change, *unless* the user
also wants a date-driven regime switch (see clarifying questions).

Also relevant: configuration epochs (`specs/13-configuration-epochs.md:129-143`) already
provide the pattern for "one continuous energy simulation, segmented reporting", and
`spans_epoch_boundary` already exists in the result object
(`specs/07-internal-representation.md:132`). A regime boundary could reuse that pattern,
but epochs are about *physical installation* changes, not policy changes — conflating
them would be a design decision, not a given.

## Requirements Changes

- None yet beyond the todo item above.

## Files Modified

- Created: `changelog/20260723-regime-mixing-scope.md` (this file).
- `specs/01-product-brief.md` — §1.3: the no-mixing bullet rewritten to bind cost
  calculations only, followed by a short statement of the general principle that
  energy-flow simulation is regime-independent and that a window may span 1 January 2027,
  with a pointer to the metric classification in §6.11.
- `specs/18-dutch-electricity-background.md` — E4.2: the "never mix regimes" warning and
  its "In the specification" note narrowed to the cost path, noting that the flow path is
  unaffected and a boundary-crossing window is not a special case.
- `specs/10-pricing.md` — §6.5: the pre-2027 extension-point note keeps its existing
  rationale and gains a paragraph explaining that placing the netting stage after the flow
  simulation is precisely what confines the regime to the cost path.
- `specs/12-metrics-and-benchmarks.md` — §6.11: new paragraph classifying each metric as
  regime-free or cost-bound.
- `specs/appendix-b-glossary.md` — salderingsregeling modelling note gains a clause that
  the regime binds the cost path only.

Deliberately left untouched:

- `specs/13-configuration-epochs.md`, `specs/07-internal-representation.md` and the
  epoch-related parts of `specs/15-data-quality-and-limits.md` (decision 2).
- `specs/02-ux-wireframes.md` (decision 4).
- The "load profile is held fixed across the regime change" caveat in
  `specs/15-data-quality-and-limits.md` assumption 8 and `specs/01-product-brief.md` — a
  different claim, about behaviour rather than about mixing.
- The "mixing the two information sets" passages in `specs/12-metrics-and-benchmarks.md`
  and `specs/14-diagnostics.md` — about observed-vs-simulated baselines, not regimes.
- `dutch-electricity-explainer.md` at the repo root, which carries the same E4.2 sentence.
  It is the archived source document that was folded into
  `specs/18-dutch-electricity-background.md`; the spec copy is the live one.

## Rationales and Alternatives

- The rule was already de-facto pricing-only in the specs: nothing reads an interval's
  calendar date to select a regime, and one chosen regime is applied to the whole window.
  The problem was wording ("one calculation", "not per epoch") that read as covering the
  whole simulation. Hence a prose clarification rather than a behavioural change.
- An alternative considered and rejected (decision 2) was to treat 1 January 2027 as a
  configuration-epoch boundary, reusing `spans_epoch_boundary` and per-epoch sub-totals.
  Rejected because epochs model *physical installation* changes; overloading them with a
  policy date adds machinery with no consumer while pre-2027 pricing is out of scope.
- The metric classification (decision 6) was added because the split is not inferable from
  the metric names — the perfect-foresight benchmark in particular optimises against
  prices while being reported alongside energy figures, so it is cost-bound.

## Obstacles and Solutions

- Grep for "mix" surfaced two unrelated passages about observed-vs-simulated baselines;
  identified as false positives and left alone.
- The repo root holds a near-duplicate of the E4.2 text in `dutch-electricity-explainer.md`;
  treated as an archived source rather than a second live copy, so only the spec was
  edited.

## Current Status

Complete. All five spec edits applied; the four cross-reference anchors introduced
(`#611-metrics`, `#610-cost-accounting`, `#65-price-curves`,
`#13-regulatory-regime--fixed-decision`) were checked against the corresponding headings.
Not committed; `todo.txt` not updated.
