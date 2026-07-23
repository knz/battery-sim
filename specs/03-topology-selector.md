# 2.5 Topology selector detail

> **Purpose:** the two illustrated selectors in panel ②, the soft block on unsupported
> phase topologies, and the SVG asset requirements.
> **Audience:** frontend.
> **Read with:** [02-ux-wireframes.md](02-ux-wireframes.md) §2.3, which hosts these
> selectors; [11-policies-and-battery.md](11-policies-and-battery.md) §6.8, where PV
> coupling changes the charge efficiency; and open questions
> [§8.7, §8.9 and §8.10](17-open-questions.md).

Both selectors are **illustrated radio groups**, not dropdowns. Users recognise a picture
of their own meter cupboard far more reliably than they answer the equivalent question in
words, and both of these settings materially change the numbers.

## (a) PV coupling — always shown

```
  How is your PV connected to the battery?

  ┌───────────────────────────────┐   ┌───────────────────────────────┐
  │ ( • ) DC-coupled / hybrid     │   │ (   ) AC-coupled              │
  │                               │   │                               │
  │   ┌────┐   DC   ┌──────────┐  │   │  ┌────┐    ┌─────┐            │
  │   │ PV │───────►│ hybrid   │  │   │  │ PV │───►│ PV  │───┐        │
  │   └────┘        │ inverter │  │   │  └────┘    │ inv │   │        │
  │                 │  ┌─────┐ │  │   │            └─────┘   ▼        │
  │                 │  │ BAT │ │  │   │                    ══╪══ AC   │
  │                 │  └─────┘ │  │   │  ┌────┐    ┌─────┐   │        │
  │                 └────┬─────┘  │   │  │ BAT│───►│batt │───┘        │
  │                   AC │        │   │  └────┘    │ inv │   │        │
  │                   ═══╪═══     │   │            └─────┘   │        │
  │                grid ─┴─ load  │   │        grid ─────────┴─ load  │
  │                               │   │                               │
  │  One conversion PV→battery    │   │  Two conversions PV→battery   │
  └───────────────────────────────┘   └───────────────────────────────┘

  DC-coupled skips an inversion on the solar charging path — typically
  +3 to +5 percentage points on that path only. Grid charging is
  unaffected. Set the bonus under Advanced if your installer gave you
  separate figures.
```

The selection sets `cfg.coupling`, which selects `eta_c_dc` instead of `eta_c` on the PV
charging path in the battery step function
([§6.8](11-policies-and-battery.md#68-battery-step-function)). The default bonus is
`roundtrip_dc_bonus = +0.04`.

## (b) Battery phase configuration

Rendered only when *Grid connection → 3-phase* is selected. On a 1-phase connection there
is nothing to choose.

```
  How is your battery connected across the phases?

  ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
  │ (   ) 1-phase      │ │ ( • ) 3-phase      │ │ (   ) 3 × 1-phase  │
  │       battery      │ │       inverter     │ │       batteries    │
  │                    │ │                    │ │                    │
  │  L1 ══╤══──[ BAT ] │ │  L1 ══╤══──┐       │ │  L1 ══╤══──[ BAT ] │
  │  L2 ══╪══          │ │  L2 ══╪══──┼─[BAT] │ │  L2 ══╪══──[ BAT ] │
  │  L3 ══╪══          │ │  L3 ══╪══──┘       │ │  L3 ══╪══──[ BAT ] │
  │                    │ │                    │ │                    │
  │   ⚠ not in v1      │ │   ✓ supported      │ │   ⚠ not in v1      │
  └────────────────────┘ └────────────────────┘ └────────────────────┘
```

Selecting either unsupported option reveals:

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  ⚠  This topology is not fully supported in version 1.               │
  │                                                                      │
  │     Your smart meter nets across phases, so the *financial* result   │
  │     would be close to the 3-phase case. What we cannot model without │
  │     per-phase data is the per-phase power limit — a 1-phase battery  │
  │     cannot exceed one phase's fuse rating no matter how the load is  │
  │     distributed.                                                     │
  │                                                                      │
  │     Please email setups@<domain> describing your setup — inverter    │
  │     model, phase allocation, and whether you have per-phase sensors. │
  │     It directly determines whether this lands in version 2.          │
  │                                                                      │
  │  [ Continue with a 3-phase approximation ]        [ Email us ]       │
  └──────────────────────────────────────────────────────────────────────┘
```

**Soft, not hard, block.** Given phase netting, refusing to compute anything would deny
the user a number that is probably accurate to within a few percent. Continuing sets
`topology_approximated = true`, which propagates into the result JSON
([§4.5](07-internal-representation.md#45-result-object), field `topology.approximated`)
and pins a persistent caveat to the results panel. This is check 18 in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order), and
fixture 12 in [16-validation-harness.md](16-validation-harness.md) asserts that the
approximated run is numerically identical to the 3-phase case. Whether the soft block is
the right call is [open question §8.9](17-open-questions.md).

## Asset requirements

Four inline SVGs, 240 × 160 viewBox, single `currentColor` stroke at 2 px, no fills, no
external fonts or dependencies. Selected state indicated by border and background, never
by colour alone. Each `<svg>` carries a `role="img"` and an `aria-label` repeating the
full text description, and each option keeps a visible text label — the diagram
supplements the label, it does not replace it.
