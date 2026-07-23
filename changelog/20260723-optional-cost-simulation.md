# 2026-07-23 — Optional cost simulation, and the §6.4 tariff-register rework

## Task specification

### Original user prompt (verbatim)

From `todo.txt`:

> UX/wireframes and simulation structure: we want to clearly separate "energy savings"
> from "cost savings" in the results. The latter is optional. There should be a master
> checkbox "do you want to simulate cost savings as well". The UX items related to cost /
> billing / contracts should be hidden when cost simulation is disabled.

Standing guidance at the top of `todo.txt`:

> Whenever possible, it will be preferable to rewrite/simplify existing paragraphs -- we do
> not have users who know the previous version so there is no need to inform them of what
> has changed.

### Scope

Two changes, deliberately carried in one entry because the second was surfaced by the
first and touches the same files.

1. **Cost simulation becomes optional.** A master toggle `cfg.simulate_cost` gates the
   contract/tax/VAT/feed-in apparatus, the money results, the cost waterfall and the price
   bracket. Energy results are always produced.
2. **§6.4 tariff-register handling is reworked.** The existing text modelled a permanently
   empty T2 register as a property of the household's *contract* ("single-tariff
   contracts"). That is incorrect: Dutch households switch supplier freely, so what is
   wired at the meter is not a function of the selected contract, and the law requires the
   meter to measure T1 and T2 independently. A missing or flat T2 therefore indicates an
   incomplete or incorrect installation, not a contract choice.

### Phase 1 — investigation (completed before any edit)

A survey of all 20 spec files established that, unlike the earlier optional-PV change,
this one does *not* leave the numeric core untouched. `pv = 0` was already a correct
neutral value everywhere; there is no equivalent neutral value for a price. Cost removal
structurally reaches:

- charge policies P2/P3 and discharge policies D2/D3, which read `st.spot[i]`;
- `economic_guard`, which reads `p_export_net`;
- the perfect-foresight benchmark (run D), whose objective *is* cost;
- `soc_delta_value_eur`, which values residual SoC at the median import price;
- the §6.16 price bracket, which is pure pricing;
- **§6.13's resolution-bias diagnostic**, which is computed from `saved_eur` and would
  silently return `None` for every energy-only run. This was the least obvious finding in
  the survey and is fixed here rather than deferred.

## Clarifications obtained

Five questions were put to the user before editing. The answers below are the decisions
implemented.

1. **Price-band policies without cost simulation?** → **Keep them; the spot series stays a
   required input.** "Price series as a dispatch signal" is separated from "cost
   modelling" (contract, tax, VAT, feed-in, terugleverkosten). The master toggle removes
   only the second. No `has_pv` × `simulate_cost` combination is blocked.
2. **Perfect-foresight benchmark?** → **Re-target the DP to minimise grid import (kWh)**
   when cost is off. Same machinery; `transition_cost` returns kWh imported instead of
   euros. Preserves the percent-of-theoretical-maximum framing and keeps fixture 6 alive
   as an energy invariant.
3. **§6.4 tariff registers?** → **Rework, decoupling three concerns** (see below).
4. **Default for `simulate_cost`?** → **`false`.** A first-time user gets an energy-only
   run; cost is opt-in. Toggle lives in a "What to simulate" box at the top of panel ②,
   mirrored in panel ①, following the `has_pv` convention. Recorded alongside open
   question §8.16 so both toggles are revisited together.
5. **Result JSON shape?** → **`cost`, `benchmarks` and `price_bracket` become `null`
   wholesale.** Cost columns are dropped from the per-interval CSV entirely rather than
   emitted blank; the spec states why the two differ.

## High-level decisions

- **`cfg.simulate_cost` is the single source of truth**, set by the panel ② toggle. Named
  for user intent rather than as `has_cost`, because unlike `has_pv` it describes what the
  user wants computed, not a property of their household.
- **A price series is not a cost model.** This is the central distinction of the change.
  The spot price is one number per interval and drives *dispatch*; the cost model is the
  contract/tax/VAT/feed-in apparatus and drives *euros*. Separating them is what keeps the
  no-PV × no-cost cell meaningful — without it, a household with neither PV nor cost
  simulation would have no viable charge policy and the run would be degenerate.
- **The energy core produces identical numbers either way.** With the price bands still
  driving dispatch, `simulate_cost` changes nothing about which kWh move. This is pinned
  by a new invariance fixture, mirroring what fixture 17 does for PV.
- **Cost-bound results are `null`, not zero.** Same reasoning as `self_consumption` in the
  PV change: a zero euro saving is a measurement, an absent cost model is not.
- **Cost-only quality checks are skipped and reported as skipped**, never as passed —
  reusing the convention established for the PV-only checks.
- **§6.4 splits into three independent concerns**: (1) whether separate T1/T2 series
  exist, which is an installation fact and runs always; (2) which series is dal and which
  is normaal, determined from when each reports activity; (3) how the zones are priced.
  Concerns (2) and (3) are cost-gated. Concern (1) is not, because an incomplete meter
  installation is worth telling the user about regardless of what they asked to simulate.

## Requirements changes

- The §6.4 rework was added mid-task, at the user's direction, after the investigation
  flagged tariff-zone assignment as cost-only. The user rejected the framing rather than
  the gating: the old text was wrong about *why* a register might be empty.

## Files modified

See "Current status" below.

## Rationales and alternatives

- **Keeping P2/D2/D3 over hiding them.** Hiding them would have mirrored the PV change
  exactly (P1/P3 are hidden without PV). Rejected because P1 charges nothing without PV,
  so a no-PV, no-cost household would have had zero usable charge policies. The
  alternative — declaring that combination unsupported and blocking it — was considered
  and rejected as a worse outcome than requiring a price series.
- **Energy-objective DP over dropping the benchmark.** An unanchored "you saved 1,412 kWh"
  is exactly the uninterpretable headline §6.12 exists to prevent. The DP is already
  written against an abstract `transition_cost`, so retargeting is a small spec change for
  a large interpretability gain.
- **`simulate_cost` defaults to `false`** — this trades the app's most distinctive output
  against the five-minute cold-start criterion in §1.6, and the user chose the latter. The
  risk is that users never find the toggle; recorded in §8.18 rather than mitigated here.
- **`null` blocks over null-filled blocks.** The PV change established "test for `null`,
  not for existence". Honoured at the block level; enumerating a waterfall array of eight
  nulls would invite an implementer to render eight empty rows.
- **CSV drops columns while JSON keeps keys.** A CSV header is self-describing and a
  column of blanks is worse than an absent column; a JSON consumer indexes by key and
  benefits from stable shape. The divergence is deliberate and stated in §4.6.

## Obstacles and solutions

- *§6.13 computes `bias_pct` from `saved_eur` and bails when it is under €1.* Would have
  disabled the resolution-bias diagnostic for every energy-only run, silently. Solution:
  the function now selects its metric from `simulate_cost`, with a kWh threshold for the
  energy variant.
- *Two independent toggles describe four configurations, and the existing "Without PV"
  prose is written as a single-axis delta.* Solution: state the matrix once, in §1.4, and
  keep every per-file passage single-axis.
- *The old §6.4 tied register availability to contract type.* Solution: the rewrite treats
  T1/T2 availability as an installation fact, checked always, and separates it from zone
  identification and from pricing.

## Current status

- [x] Phase 1 investigation: all 20 spec files surveyed; inventory and questions returned.
- [x] Clarifying questions answered by the user (2026-07-23).
- [x] Edits applied to all 18 affected spec files.
- [x] Cross-reference anchors verified against headings.
- [ ] User review of the applied edits.

Not done, deliberately: `todo.txt` is unchanged and nothing is committed. Both are
separate steps.

### Files modified

| File | Change |
|---|---|
| `specs/01-product-brief.md` | §1.1 restated as two separable questions; §1.2 gains the optional-cost note; §1.3 scoped to cost simulation; §1.4 gains the toggle, the "a price series is not a cost model" subsection and the `has_pv` × `simulate_cost` matrix; §1.6 criterion 1 explains the default |
| `specs/02-ux-wireframes.md` | Panel ② summary ends `energy only`; both toggles mirrored at the head of panel ①'s mapping box; spot price promoted to required; register strip split into installation vs tariff rows; new "What to simulate" box; Pricing box marked conditional; new "Without cost simulation" section in §2.3; §2.4 restructured into separate ENERGY SAVINGS and COST SAVINGS sections with an energy benchmark and energy breakdown box; new "Panel ③ without cost simulation" section |
| `specs/04-state-machine.md` | Note on toggles that change the field set: validation runs against the new field set, values are retained not discarded, no new events or states |
| `specs/05-data-formats.md` | `price_spot` required in both modes (footnote 3); T1/T2 marked *expected* with footnote 4 on installation completeness; alias footnote reworded |
| `specs/06-home-assistant-ingestion.md` | Spot mean always fetched; min/max fetched regardless so enabling cost later needs no refetch |
| `specs/07-internal-representation.md` | `spot` documented as always present with the reason it has no neutral value; `simulate_cost` added to the result object; `benchmarks` gains `objective` and kWh fields; new "Shape of the object without cost simulation"; §4.6 drops cost columns and explains the CSV/JSON divergence |
| `specs/08-architecture.md` | Note on which domain packages are skipped vs re-objectived vs untouched |
| `specs/09-ingest-algorithms.md` | §6.4 rewritten as three separated concerns: availability (always), dal identification (cost only), zone pricing (cost only); `register_availability` replaces the single-tariff-contract framing |
| `specs/10-pricing.md` | File-level gating note, including what is *not* gated (the spot series) |
| `specs/11-policies-and-battery.md` | §6.6 and §6.7 note no change under the cost toggle; `economic_guard` forced off with reason; §6.9 four-run table explains which run's objective moves |
| `specs/12-metrics-and-benchmarks.md` | §6.11 classification rebuilt as a table covering both regime-dependence and cost-mode presence; SoC drift gains an energy fallback; §6.12 gains the dual-objective specification and the different-optima warning |
| `specs/14-diagnostics.md` | Availability table updated; new "without cost simulation" paragraph; §6.13 rewritten to measure against kWh or euros per mode; §6.16 gated |
| `specs/15-data-quality-and-limits.md` | Check 4 reworded; check 8 split into 8a/8b; check 13 half-gated; skipped-not-passed convention extended to cost; §7.2 item 9 extended and new item 10 on what an energy-only run cannot answer; §7.4 annualisation clarified as non-cost |
| `specs/16-validation-harness.md` | Fixture 6 gains the dual-objective assertion and the do-not-cross-compare warning; fixture 15 rewritten for the new §6.4; new fixtures 18 (cost-invariance of the energy core), 19 (energy-only result shape) and 20 (energy-objective DP) |
| `specs/17-open-questions.md` | Header count made count-free; §8.16 cross-linked to §8.18; new §8.18 (default for `simulate_cost`) and §8.19 (whether the energy-objective DP earns its complexity) |
| `specs/18-dutch-electricity-background.md` | E1.3 corrected: register availability is a property of the meter, not the contract; a flat T2 indicates an installation or mapping problem |
| `specs/appendix-a-defaults.md` | `simulate_cost` added; new paragraph listing the defaults inert without cost simulation and noting `economic_guard` is forced rather than hidden; open-question count updated |
| `specs/appendix-b-glossary.md` | Normaal/dal modelling note rewritten; "Cost simulation" and "Dispatch signal" added to the table |
| `specs/README.md` | "What this is" paragraph gains the optional-cost sentence; `10-pricing.md` row marked as gated |

Unchanged after review: `03-topology-selector.md` (topology is physical and independent of
cost) and `13-configuration-epochs.md` (epoch detection reads energy series only).

## Incidental corrections

- `11-policies-and-battery.md` carried a stale anchor
  `03-topology-selector.md#a-pv-coupling--always-shown`, left over from the optional-PV
  change which renamed that heading to "shown when the household has PV". Fixed.
- The two `### Without PV` / `### Without cost simulation` headings in
  `02-ux-wireframes.md` would have collided across panels ② and ③, silently sending the
  panel ③ links to the panel ② sections. The panel ③ pair is now prefixed "Panel ③".
