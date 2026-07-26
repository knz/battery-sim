# Home Battery Simulator — Specification Package

**Version:** 1.3 (draft for implementation)
**Date:** 2026-07-25
**Status:** Ready for implementer hand-off. Decisions still owed are collected in
[17-open-questions.md](17-open-questions.md); measurements to run once a prototype exists
are collected in [19-prototype-experiments.md](19-prototype-experiments.md).

**Changes in 1.3 — corrections from implementation.** §6.6–§6.12 have now been built and
the energy path measured end to end; four findings against this package came out of that and
are applied here. They are corrections to *this specification*, not deferred work.

- **§6.12's interpolation rationale was wrong in direction and magnitude.** Nearest-snapping
  is *optimistic*, not "a systematic pessimism bias of several percent" — its figure lands
  *below* the realised saving, so it bounds nothing, and it converges upward as the grid
  refines rather than settling. The instruction to interpolate stands; the reason it gave
  would have led a reader to treat snapping as the safe conservative option, which is
  backwards ([§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)).
- **§6.12's terminal constraint is asymmetric with the policy run** and the package did not
  say so. The DP must finish at or above its starting SoC; run C need not, and §6.11
  deliberately reports drift rather than netting it out — so a policy that spends its opening
  charge books a saving the benchmark is forbidden to match, and fixture 6's bound fails on
  correct code. The comparison basis is now stated
  ([§6.12](12-metrics-and-benchmarks.md#the-terminal-constraint-makes-the-two-sides-asymmetric--compare-them-drift-corrected)),
  along with fixture 6 ([§6.14 item 6](16-validation-harness.md)) and the presentation rule
  for a drift-funded capture ratio ([§2.4](02-ux-wireframes.md#24-panel--results-expanded)).
- **§6.12's DP pseudocode omits two things the bound depends on** — putting the starting SoC
  on the state grid, and making the PV surplus and household deficit representable in the
  action set. Without either, the DP comes out *below* a policy run it is supposed to bound.
  Added as implementation notes, with the residual discretisation error quantified.

**Changes in 1.2:** prototype experiments, the measurements that establish which
parameters, policies and diagnostics actually change the answer
([§9](19-prototype-experiments.md)), cross-linked with the open questions several of them
inform.

**Changes in 1.1:** configuration epochs for mid-window PV/battery installation
([§6.15](13-configuration-epochs.md)); installation topology selector with diagrams
([§2.5](03-topology-selector.md)); use of HA statistics min/max/mean for price bracketing
([§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)) and
timestamp-misalignment detection
([§6.17](14-diagnostics.md#617-timestamp-misalignment-detection)); corrected
conversion-loss formula ([§6.11](12-metrics-and-benchmarks.md#611-metrics)); overlap
diagnostic reinterpreted in light of smart-meter phase netting
([§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly)).

---

## What this is

A locally-run web application that answers one question with a household's own historical
data: *if I had owned a home battery over this period, operated under this policy, how
much grid electricity — and, if I ask for it, how much money — would I have saved?*

It is a **retrospective counterfactual simulator**, not a forecaster and not a controller.
It serves households **with or without solar PV** — PV data is optional throughout, and a
battery bought purely for price arbitrage is a supported case. **Cost simulation is
likewise optional and defaults off**: energy savings are always reported, and the contract,
tax and feed-in configuration needed for euro figures is asked for only when the user opts
in. Start with [01-product-brief.md](01-product-brief.md).

---

## Conventions used throughout

These apply to every file in this package and are not restated in full elsewhere.

- All energy in **kWh**, all power in **kW**, all money in **EUR**.
- All timestamps stored and computed in **UTC**; displayed in **Europe/Amsterdam**.
- `dt` = interval duration in hours (0.0833 for 5 min, 0.25 for 15 min, 1.0 for hourly).
- Sign convention: energy flows are **non-negative magnitudes** in named directions
  (`import`, `export`, `charge`, `discharge`). No signed net flows in the domain model —
  this has repeatedly been a source of bugs in comparable tools.
- Pseudocode is Python-flavoured. Functions marked **[vectorisable]** should be
  implemented with numpy over the whole array; the rest are genuinely sequential.

---

## Files

| File | Contents | Primary audience |
|---|---|---|
| [01-product-brief.md](01-product-brief.md) | Purpose, target user, regulatory regime, scope, success criteria, design principles | Everyone |
| [02-ux-wireframes.md](02-ux-wireframes.md) | Overall layout, the four availability states, and the three panels: data, parameters, results | Frontend |
| [03-topology-selector.md](03-topology-selector.md) | Illustrated PV-coupling and battery-phase selectors, soft block, SVG asset requirements | Frontend |
| [04-state-machine.md](04-state-machine.md) | Session states, events, run identity, panel focus, persistence points | Frontend + backend |
| [05-data-formats.md](05-data-formats.md) | The series vocabulary, the per-series CSV file format, `kind` semantics, per-slot validation | Backend, integrators |
| [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md) | WebSocket statistics API, fetch strategy, which columns exist per `state_class` | Backend |
| [07-internal-representation.md](07-internal-representation.md) | `SeriesFrame`, `SimulationFrame`, result JSON, per-interval CSV export | Backend |
| [08-architecture.md](08-architecture.md) | Layer diagram, why the split, compute model, configuration, multi-user readiness | Backend |
| [09-ingest-algorithms.md](09-ingest-algorithms.md) | Counter deltas and resets, grid selection, load reconstruction, tariff registers | Backend (domain) |
| [10-pricing.md](10-pricing.md) | Price curves for all three contract types, feed-in, cost accounting, waterfall. Entirely gated on cost simulation | Backend (domain) |
| [11-policies-and-battery.md](11-policies-and-battery.md) | Charge and discharge policies, battery step function, main loop, the simulation runs | Backend (domain) |
| [12-metrics-and-benchmarks.md](12-metrics-and-benchmarks.md) | KPIs, SoC drift correction, perfect-foresight dynamic program | Backend (domain) |
| [13-configuration-epochs.md](13-configuration-epochs.md) | Detecting PV/battery commissioning mid-window, undeclared-battery heuristics | Backend + frontend |
| [14-diagnostics.md](14-diagnostics.md) | Overlap, resolution bias, price bracketing, timestamp misalignment | Backend + frontend |
| [15-data-quality-and-limits.md](15-data-quality-and-limits.md) | Known modelling limitations, the 18 quality checks, window anchoring, ops notes | Everyone |
| [16-validation-harness.md](16-validation-harness.md) | The fixtures the implementation must reproduce exactly | Backend, QA |
| [17-open-questions.md](17-open-questions.md) | Decisions still owed by the product owner | Product owner |
| [18-dutch-electricity-background.md](18-dutch-electricity-background.md) | Domain background: what the meter measures, how the bill is built, salderen and the 2027 regime, what is still unknown | Everyone; essential if the Dutch regime is unfamiliar |
| [19-prototype-experiments.md](19-prototype-experiments.md) | Measurements to run once a prototype exists: which parameters, policies and diagnostics actually change the answer | Product owner, backend |
| [20-workspaces-ux.md](20-workspaces-ux.md) | **Draft.** Multi-workspace restructure: the workspace list, the three per-workspace screens, the new-analysis wizard. Supersedes §2.1's single-page stepper; §2.2–§2.4's box contents are unchanged | Frontend, product owner |
| [appendix-a-defaults.md](appendix-a-defaults.md) | Every default parameter value with its rationale | Everyone |
| [appendix-b-glossary.md](appendix-b-glossary.md) | Dutch energy terminology and abbreviations | Everyone |
| [implementation-progress.md](implementation-progress.md) | Living build record: which controls are pending and their feature keys (not a spec) | Implementers |

---

## Section number → file

The original document numbered its sections `§1`–`§8`. Those numbers are retained as
headings because the text cross-references them heavily. Use this table to resolve any
`§n.m` reference.

| § | Topic | File |
|---|---|---|
| §1 | Product brief | [01-product-brief.md](01-product-brief.md) |
| §2.1–2.4 | UX wireframes | [02-ux-wireframes.md](02-ux-wireframes.md) |
| §2.5 | Topology selector | [03-topology-selector.md](03-topology-selector.md) |
| §3 | Application state machine | [04-state-machine.md](04-state-machine.md) |
| §4.1–4.2 | CSV formats | [05-data-formats.md](05-data-formats.md) |
| §4.3 | Home Assistant ingestion | [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md) |
| §4.4–4.6 | Internal representation, result object, export | [07-internal-representation.md](07-internal-representation.md) |
| §5 | Software architecture | [08-architecture.md](08-architecture.md) |
| §6.1–6.4 | Ingest and normalisation algorithms | [09-ingest-algorithms.md](09-ingest-algorithms.md) |
| §6.5, §6.10 | Pricing and cost accounting | [10-pricing.md](10-pricing.md) |
| §6.6–6.9 | Policies, battery step, main loop | [11-policies-and-battery.md](11-policies-and-battery.md) |
| §6.11–6.12 | Metrics and perfect-foresight benchmark | [12-metrics-and-benchmarks.md](12-metrics-and-benchmarks.md) |
| §6.13 | Resolution-bias diagnostic | [14-diagnostics.md](14-diagnostics.md#613-resolution-bias-diagnostic) |
| §6.14 | Validation harness | [16-validation-harness.md](16-validation-harness.md) |
| §6.15 | Configuration epochs | [13-configuration-epochs.md](13-configuration-epochs.md) |
| §6.16 | Price bracketing | [14-diagnostics.md](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) |
| §6.17 | Timestamp misalignment | [14-diagnostics.md](14-diagnostics.md#617-timestamp-misalignment-detection) |
| §7.1 | Overlap diagnostic | [14-diagnostics.md](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly) |
| §7.2–7.5 | Limitations, quality checks, anchoring, ops | [15-data-quality-and-limits.md](15-data-quality-and-limits.md) |
| §8 | Open questions | [17-open-questions.md](17-open-questions.md) |
| §9 | Prototype experiments | [19-prototype-experiments.md](19-prototype-experiments.md) |
| E1–E7, E-A–E-D | Dutch electricity background | [18-dutch-electricity-background.md](18-dutch-electricity-background.md) |
| Appendix A | Default parameter values | [appendix-a-defaults.md](appendix-a-defaults.md) |
| Appendix B | Glossary | [appendix-b-glossary.md](appendix-b-glossary.md) |

Background sections carry an **`E` prefix** (`E1.4`, `E5.2`, Appendix `E-A`) so they never
collide with the specification's own `§1.4`, `§5.2` and Appendix A. A reference of the
form `§n.m` is always the specification; `En.m` is always the background. The experiments
in §9 carry an **`X` prefix** (`X1`, `X7`) for the same reason — `E` was already taken by
the background.

Two groupings depart from the original section order, in both cases to put material next
to what it is used with rather than where its number fell:

- **§7.1 sits with §6.13, §6.16 and §6.17** in `14-diagnostics.md`. These four diagnostics
  reference each other continuously — §6.13 opens by saying it complements §7.1, and §6.17
  ends by using §7.1 as a corroborating signal.
- **§6.10 sits with §6.5** in `10-pricing.md`. The waterfall consumes the price arrays
  directly; they are two halves of one calculation.

§6.14 appeared after §6.17 in the original document, apparently by accident. It is placed
in numeric order here, as `16-validation-harness.md`.

---

## Suggested reading order

If the Dutch electricity regime is unfamiliar, read
[18-dutch-electricity-background.md](18-dutch-electricity-background.md) before any of
these. Parts E1, E2 and E5 in particular carry the facts the rest of the package assumes
without restating: that the meter measures only what crosses the connection, that VAT
compounds on the energy tax, and what changes on 1 January 2027.

**Implementing the domain layer** — the numeric core, and the part with the most ways to
be subtly wrong:

1. [01-product-brief.md](01-product-brief.md) §1.3 (the 2027 regime) and §1.7 (principles)
2. [07-internal-representation.md](07-internal-representation.md) §4.4 (the two frame types)
3. [09-ingest-algorithms.md](09-ingest-algorithms.md) → [10-pricing.md](10-pricing.md) →
   [11-policies-and-battery.md](11-policies-and-battery.md) →
   [12-metrics-and-benchmarks.md](12-metrics-and-benchmarks.md), in that order — each
   consumes the previous one's output
4. [16-validation-harness.md](16-validation-harness.md) — write these fixtures first
5. [15-data-quality-and-limits.md](15-data-quality-and-limits.md) §7.2, so the known
   limitations are known before rediscovering them

**Implementing the frontend:**

1. [02-ux-wireframes.md](02-ux-wireframes.md) and [03-topology-selector.md](03-topology-selector.md)
2. [04-state-machine.md](04-state-machine.md) — §3.4 in particular
3. [07-internal-representation.md](07-internal-representation.md) §4.5, the result object
   the templates render

**Implementing ingestion:**

1. [05-data-formats.md](05-data-formats.md) and
   [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md)
2. [09-ingest-algorithms.md](09-ingest-algorithms.md)
3. [13-configuration-epochs.md](13-configuration-epochs.md) and
   [14-diagnostics.md](14-diagnostics.md) — both run at ingest time
4. [15-data-quality-and-limits.md](15-data-quality-and-limits.md) §7.3, the ordered check
   list

**Reviewing the design:** [01-product-brief.md](01-product-brief.md) →
[17-open-questions.md](17-open-questions.md) →
[15-data-quality-and-limits.md](15-data-quality-and-limits.md), with
[background E7](18-dutch-electricity-background.md#part-e7--what-is-not-yet-known)
alongside the open questions — several of them are open because the underlying 2027
tariffs are not published, not because the product decision is hard.
