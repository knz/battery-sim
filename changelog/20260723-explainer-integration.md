# 2026-07-23 — Integrate the Dutch electricity explainer into `specs/`

## Task specification

### Original user prompt, verbatim

> can you please add the content from dutch-electricity-explainer.md and
> dutch-electricity-explainer-findings.md into the spec and cross-link where relevant

Follows on from [20260723-spec-split-into-specs-folder.md](20260723-spec-split-into-specs-folder.md),
which split `battery-sim-spec.md` into `specs/`.

### Source material

**`dutch-electricity-explainer.md`** — 546 lines, version 1.0, dated 22 July 2026,
self-describing as "Companion to: Home Battery Simulator specification v1.1". Seven parts
plus four appendices: what the meter measures, how the bill is built, contract types,
salderen, the 2027 regime, implications, and what is not yet known. Explanatory in voice,
with a different job from the spec — it justifies and contextualises where the spec
prescribes.

**`dutch-electricity-explainer-findings.md`** — 4 lines, two findings the explainer's
author flagged as affecting the simulator spec:

1. The "compensation may not be negative" rule is assessed over a period of **at least a
   month**, not per interval — set explicitly by amendment. The spec's per-interval
   `max(0, α × bare + β)` clamp is therefore slightly too strict and could understate
   feed-in revenue during volatile months.
2. Feed-in charges may be levied only on **active customers** (those who actually feed
   in), not spread across all customers, and charges that are discriminatory or unrelated
   to feed-in are prohibited. This constrains which preset shapes are legally plausible.

Finding 1 is corroborated in the explainer body at §5.2 item 2 and Appendix B; finding 2
at §5.2 item 4.

## Scope assessment

Finding 1 is a substantive change to
[§6.5](../specs/10-pricing.md#65-price-curves) `export_price_net`, not a documentation
edit, and it has a consequence the finding does not mention: a monthly-aggregate floor is
**not separable per interval**, whereas the waterfall decomposition in
[§6.10](../specs/10-pricing.md#610-cost-accounting) is per-interval and exact. Changing
the floor changes what "exact" means there. This needs a decision rather than an
assumption.

Finding 2 is narrower — it bounds which terugleverkosten preset shapes are legally
plausible, which bears on [open question §8.5](../specs/17-open-questions.md) and on the
tiered-TLK note in §6.5.

## High-level decisions

(recorded as they are made)

## Files modified

(to be recorded)

## Current status

Source material read and assessed. Two integration decisions put to the user before
writing: how the explainer body should be folded in, and how far to take finding 1.
