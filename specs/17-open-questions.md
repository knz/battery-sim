# 8. Open questions for the product owner

> **Purpose:** decisions the specification does not make, ordered by how much rework the
> answer causes if deferred.
> **Audience:** product owner.
> **Status:** all seventeen are open. Where the spec had to pick something to remain
> implementable, the choice it made is stated and marked as a choice, not a finding.

1. **Feed-in reference for dynamic contracts.** The statutory floor is 50% of the "bare
   supply price". For a fixed contract that is unambiguous. For a dynamic contract, is the
   bare price the hourly spot, or the spot plus the supplier's markup? The spec currently
   assumes `bare = spot + markup` for import but applies α to the same `bare` for export,
   which is a choice, not a fact. It moves feed-in revenue by roughly 1 ct/kWh.
   → [§6.5](10-pricing.md#65-price-curves)

2. **Should the perfect-foresight benchmark be allowed to export?** Currently it inherits
   `allow_grid_export`. Inheriting makes the capture ratio a fair comparison of *policy
   quality*; not inheriting makes it a comparison against the true physical maximum. Both
   are defensible and they differ materially. Recommendation: inherit, and offer the
   unconstrained bound as a secondary figure.
   → [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)

3. **Cycle-life cost.** Currently reported as cycles only, with an optional
   €/kWh-throughput term defaulting to 0. Confirm that a policy doing 700 cycles/yr
   ranking above one doing 300 with similar savings is acceptable output, or set a
   non-zero default (a €5,000 / 10 kWh / 6,000-cycle system implies ≈ €0.08/kWh
   throughput, which is large enough to reverse most arbitrage conclusions).
   → [§6.10](10-pricing.md#610-cost-accounting),
   [appendix-a-defaults.md](appendix-a-defaults.md)

4. **Multiple policy comparison in one run.** The current UI evaluates one configuration
   at a time. Since a full run costs seconds, evaluating all nine charge×discharge
   combinations and presenting a matrix would be far more useful than sequential manual
   exploration. This is a significant UX addition — worth deciding before build rather
   than retrofitting panel ③.
   → [§2.4](02-ux-wireframes.md#24-panel--results-expanded)

5. **Terugleverkosten presets.** 2027 tariffs are not published. Shipping presets named
   after real suppliers implies a precision that does not exist. Recommendation: ship
   generic presets ("low / mid / high: 2, 4, 7 ct/kWh") plus a dated note, and let users
   enter their own. Confirm.
   → [§6.5](10-pricing.md#65-price-curves)

6. **Battery-free periods.** If the user already owns a battery, its sensors are stripped
   in [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) — but if the battery
   was installed partway through the window, the reconstructed load will be inconsistent
   across the boundary unless the sensors cover the whole period. Should the app detect
   this and offer to restrict the window?
   → [§6.15](13-configuration-epochs.md)

7. **1-phase vs 3-phase asymmetry.** A 1-phase battery on a 3-phase connection can only
   charge and discharge on its own phase, while the meter nets across phases. This is
   common in the Netherlands and the current model ignores it (it assumes the battery sees
   the net). Is per-phase modelling in scope later? If so, the data model needs per-phase
   series and the decision affects [05-data-formats.md](05-data-formats.md) now.
   → [§2.5](03-topology-selector.md#b-battery-phase-configuration)

8. **DST-boundary intervals.** The October transition produces a 25-hour local day. The
   spec computes in UTC throughout, which is correct, but hourly *prices* published per
   local hour need care at the boundary. Confirm the spot price source's convention.
   → [§4.1](05-data-formats.md#column-rules),
   [fixture 7](16-validation-harness.md)

9. **Is a soft block on 1-phase / 3×1-phase batteries the right call?** The spec
   implements your instruction, but with an escape hatch, because Dutch smart meters net
   internally across phases and that behaviour survives 2027. The financial result for a
   1-phase battery on a 3-phase connection is therefore close to the 3-phase case; what is
   genuinely unmodellable without per-phase data is the per-phase power ceiling. A hard
   block denies users a number that is probably good to a few percent. Confirm soft block,
   or overrule to hard block.
   → [§2.5](03-topology-selector.md#b-battery-phase-configuration)

10. **Should `max_charge_kw` / `max_discharge_kw` be auto-derived from the phase
    topology?** For a 1-phase battery on a 3-phase connection the ceiling is one phase's
    fuse rating, which the user may not think to enter. Proposal: derive a suggested cap
    and warn when the entered value exceeds it, rather than enforcing.
    → [§2.3](02-ux-wireframes.md#23-panel--parameter-configuration-expanded)

11. **Epoch semantics for battery state.**
    [§6.15](13-configuration-epochs.md#effects-on-the-rest-of-the-application) keeps one
    continuous SoC trace across epoch boundaries and segments only the reporting. The
    alternative — reset SoC at each boundary — is arguably cleaner when the boundary is a
    PV commissioning date. Confirm.

12. **Default for `supplier_settlement`.** Set to hourly, since most Dutch dynamic
    suppliers still bill on the hourly average despite 15-minute EPEX settlement. This
    default silently disables the price bracket for most users. Is that right, or should
    the app ask explicitly during setup rather than defaulting?
    → [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)

13. **PV capacity-change detection** is the weakest of the epoch heuristics — seasonal
    variation, soiling and shading all produce similar signatures, and a false positive
    fragments the window unhelpfully. Consider shipping it disabled, surfacing it only as
    a note in the data-quality panel.
    → [§6.15](13-configuration-epochs.md)

14. **Feed-in floor assessment period.** The law requires the non-negativity of feed-in
    compensation to be assessed over a period of **at least one month**, which leaves the
    supplier free to use a quarter or a year instead. A longer period lets more negative
    intervals be absorbed, so it is weakly less favourable to the household. The spec
    defaults `feedin_floor_period` to a calendar month — the most favourable period the
    law permits, and therefore an optimistic default. Options: keep the optimistic
    default, ask the user during setup as with `supplier_settlement`, or make it part of
    the feed-in preset. Note that no supplier has published 2027 terms, so any answer is
    provisional.
    → [§6.5](10-pricing.md#the-feed-in-floor-is-a-period-aggregate-not-a-per-interval-clamp)

15. **Should the results panel show the feed-in floor top-up at all?** It is a genuine
    waterfall term and it closes the identity exactly, but it will read as €0.00 for
    almost every user, and a permanently-zero line in a six-line summary costs attention
    for nothing. Options: always show it; show it only when nonzero; or fold it into
    `lost_feedin_compensation` for display while keeping it separate in the result JSON.
    The third preserves the exact decomposition for anyone reading the export while
    keeping the panel clean, and is the recommendation.
    → [§6.10](10-pricing.md#610-cost-accounting),
    [§2.4](02-ux-wireframes.md#24-panel--results-expanded)

16. **Default for `has_pv`.** Defaulted to `true`, on the reasoning that a household
    motivated enough to run Home Assistant and evaluate a battery is more likely than not
    to already have solar. The cost of the default being wrong is asymmetric: a no-PV user
    who leaves it alone is asked for a solar sensor they do not have and is blocked by
    check 4 until they notice the toggle, which is annoying but self-correcting. Options:
    keep `true`; default to `false`, which fails in the other direction and is caught by
    the daytime-export heuristic; or make it an unset radio group that must be answered
    before the run proceeds, which costs one click for everyone and removes the guess
    entirely. The third is the recommendation if panel ② can afford the friction.
    → [§2.3](02-ux-wireframes.md#23-panel--parameter-configuration-expanded),
    [appendix-a-defaults.md](appendix-a-defaults.md)

17. **Should D1 remain a separate option without PV?** With PV, D1 ("serve the deficit
    above solar") and D3 ("that plus price-band discharge") are clearly different
    strategies. Without PV, D1 becomes "discharge whenever the house draws anything, at any
    price", which is a defensible policy — it maximises self-sufficiency and needs no price
    data — but it is also the policy most likely to lose money under a dynamic contract,
    since it will happily discharge into a cheap hour. The spec keeps all three options and
    relabels D1. The alternative is to hide D1 without PV and offer only D2/D3, which
    removes a footgun but also removes the ability to demonstrate that the footgun is one.
    Consistent with the "literal policies" principle in
    [§1.7](01-product-brief.md#17-design-principles), keeping it is the recommendation.
    → [§6.7](11-policies-and-battery.md#67-discharge-policy),
    [§2.3](02-ux-wireframes.md#without-pv)
