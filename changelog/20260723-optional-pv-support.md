# 2026-07-23 — Optional PV: supporting households without solar

## Task specification

### Original user prompt (verbatim)

> let's iterate on the specs for this project.
> i'll throw in some requests for adjustments. your task will be to update the specs according to my requests.
> whenever possible, it will be preferable to rewrite/simplify existing paragraphs -- we do not have users who know the previous version so there is no need to inform them of what has changed.
>
> initial request;
> - audience: users who _may_ have PV (the simulation should also work for users without PV; there may be benefits to adding a battery without PV).  The data for PV is thus optional, and the supported topologies should include configurations without PV.

### Scope

Widen the specification's target audience from "Dutch homeowner with solar PV" to
"Dutch homeowner who may or may not have solar PV". PV data becomes optional
throughout; the supported installation topologies must include grid-only battery
configurations.

### Working style established for this series of tasks

Rewrite and simplify existing paragraphs in place. Do not add "changed from"
or migration notes — there is no existing user base familiar with the previous
version of the specs.

## Clarifications obtained

Three questions were put to the user before editing:

1. **How is the no-PV case established?** → **Explicit toggle in panel ②.**
   A "Do you have solar PV?" control gates the PV coupling selector and the
   solar sensor mapping. Rejected: pure inference from an unmapped
   `solar_production` series.
2. **Which policies/metrics does a no-PV household see?** → **Hide the
   inapplicable ones.** P1 and the PV half of P3 disappear; D1 is relabelled;
   self-consumption ratio is suppressed as undefined.
3. **Topology selector treatment?** → **Suppress the PV-coupling selector and add
   a new illustrated no-PV topology** (grid → battery inverter → AC bus).
   Requires one new SVG asset.

## High-level decisions

- **`cfg.has_pv` is the single source of truth**, set by the panel ② toggle. It
  gates sensor mapping requirements, policy availability, topology selectors,
  metrics, and diagnostics. Chosen over inference so that the app can still warn
  a PV owner who forgot to map their inverter — with inference alone, that user's
  PV output silently folds into reconstructed household load, which is the exact
  failure mode §6.3 works hardest to catch.
- **The numeric core needs no special-casing.** With `pv = 0` the energy balance,
  battery step function, main loop, pricing and the perfect-foresight DP are all
  already correct. The changes are to requirements, UI, diagnostics and metrics —
  not to the simulation math. This is recorded explicitly in the specs so an
  implementer does not add defensive branches.
- **Without PV the battery's value is entirely price arbitrage** (charge cheap,
  discharge expensive) plus avoided peak-tariff import. The product brief must
  say so, since the headline saving comes from a different mechanism than in the
  PV case and is generally smaller.
- **Undefined metrics are reported as `null`, not as zero.** `self_consumption`
  has `pv.sum()` in its denominator; emitting 0 or 1 would be a fabricated
  number. Self-sufficiency remains well-defined (import ÷ load).
- **Diagnostics that need PV are skipped, not failed.** Cross-correlation
  misalignment detection (§6.17) needs a PV signal; PV commissioning epoch
  detection (§6.15) needs a solar series; the implausible-PV check (§7.3 #9) has
  nothing to check. Each is marked not-applicable rather than reporting a
  spurious pass or a warning.

## Files modified

See "Current status" below; list is filled in as edits land.

## Rationales and alternatives

- **Explicit toggle over inference** — see clarification 1 above. Cost: one more
  control in an already dense panel ②. Benefit: the "forgot to map the inverter"
  failure stays detectable.
- **Hiding P1/P3 rather than leaving them inert** — offering a user a charge
  policy that provably does nothing is a usability defect, and P1's presence
  would imply the app expects solar data it was told does not exist.
- **New no-PV topology diagram rather than just suppressing the selector** — the
  topology selector exists because users recognise a picture of their own meter
  cupboard. A no-PV user shown nothing at all gets no confirmation that the app
  understood their setup.

## Obstacles and solutions

- *Negative reconstructed load has a different meaning without PV.* With
  `pv = 0`, `load = import − export`, so negative load means the meter recorded
  export from a household with no generator — a much stronger signal (undeclared
  PV, undeclared battery, or inverted sign convention) than in the PV case where
  it is usually a sensor-scope or clock issue. Solution: split the §6.3 diagnostic
  wording by `has_pv`.
- *The energy balance in §6.3 reads as PV-centric prose.* Solution: restate it as
  the general AC-bus balance with PV as one optional term.

## Current status

- [x] Read all 20 spec files; identified every PV assumption.
- [x] Clarifying questions answered.
- [x] Implementation plan approved by the user (2026-07-23).
- [x] Edits applied to all 14 affected spec files.
- [ ] User review of the applied edits.

### Files modified

| File | Change |
|---|---|
| `specs/01-product-brief.md` | §1.2 target user widened; §1.4 scope gains optional-PV bullet; new §1.4 note on where value comes from without PV |
| `specs/02-ux-wireframes.md` | Panel ① mapping table marks solar optional and adds the has-PV gate; panel ② gains the PV toggle; policy lists and secondary metrics shown conditionally |
| `specs/03-topology-selector.md` | PV-coupling selector gated on `has_pv`; new grid-only illustrated topology; asset count raised to five SVGs |
| `specs/05-data-formats.md` | `solar_production` required → conditional; note on what the absence means |
| `specs/06-home-assistant-ingestion.md` | Solar sensor listed as conditional in the state-class table |
| `specs/07-internal-representation.md` | `SimulationFrame.pv` documented as all-zero when no PV; result object gains `has_pv`, `topology.pv_coupling: null`, nullable self-consumption |
| `specs/09-ingest-algorithms.md` | §6.3 balance restated with PV optional; `reconstruct_load` signature and negative-load diagnostic split by `has_pv` |
| `specs/10-pricing.md` | No change needed (pricing is flow-based); verified |
| `specs/11-policies-and-battery.md` | P1/P3 and D1 semantics under `has_pv = false`; policy availability table |
| `specs/12-metrics-and-benchmarks.md` | `self_consumption` nullable when `pv.sum() == 0` |
| `specs/13-configuration-epochs.md` | PV epoch detection skipped without PV; undeclared-PV heuristic added |
| `specs/14-diagnostics.md` | §6.17 cross-correlation marked PV-only, power/energy fallback promoted; availability table updated |
| `specs/15-data-quality-and-limits.md` | Check 4, 6, 9 and 16 conditioned on `has_pv`; new check for export without declared PV |
| `specs/16-validation-harness.md` | New fixtures 16 (no-PV arbitrage) and 17 (PV-invariance of the numeric core) |
| `specs/17-open-questions.md` | New §8.16 (default `has_pv`) and §8.17 (whether D1 survives without PV); stale "thirteen" count in the header corrected to seventeen |
| `specs/appendix-a-defaults.md` | `has_pv` default added |
| `specs/README.md` | "What this is" paragraph widened; stale "twelve fixtures" description made count-free |

Unchanged after review: `04-state-machine.md`, `08-architecture.md`, `10-pricing.md`,
`18-dutch-electricity-background.md`, `appendix-b-glossary.md`. Pricing in particular was
checked and needs nothing — it operates on flows (`flows.imp`, `flows.exp`) and never
references PV, so a no-PV run prices correctly with no change. The background document
describes the Dutch regime rather than the app and remains accurate as written.

## Incidental corrections

Two counts in the specs were already stale before this task and were corrected while
editing the files they appear in: `README.md` described 16-validation-harness as holding
"the twelve fixtures" (it held fifteen), and `17-open-questions.md` said "all thirteen are
open" (there were fifteen). Both are now correct, the first by dropping the count.
