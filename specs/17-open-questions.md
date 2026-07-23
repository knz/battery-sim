# 8. Open questions for the product owner

> **Purpose:** decisions the specification does not make, ordered by how much rework the
> answer causes if deferred.
> **Audience:** product owner.
> **Status:** all are open. Where the spec had to pick something to remain
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
   → [§4.2](05-data-formats.md#column-rules),
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
    **Decide together with §8.18** — these are the two toggles that shape what panel ②
    asks for, and making both unset costs the user two clicks before any result appears,
    which is a different friction calculation from making one unset.
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

18. **Default for `simulate_cost`.** Defaulted to `false`, so a first-time user reaches an
    energy-only result without entering a single euro figure — which is what protects the
    five-minute cold-start criterion in
    [§1.6](01-product-brief.md#16-success-criteria), since the alternative asks a user who
    has just connected Home Assistant to also know their supply rate, their feed-in terms
    and the current energy tax. The cost of the default is that cost simulation is the more
    compelling half of the product and some users will never find the toggle. The results
    panel carries an explicit affordance for this reason
    ([§2.4](02-ux-wireframes.md#panel--without-cost-simulation)), but an affordance is weaker than
    a default. Options: keep `false`; default to `true` and accept the configuration
    burden on first run; or leave it unset and require an answer, as
    [§8.16](17-open-questions.md) contemplates for `has_pv`. Decide together with §8.16.
    → [§2.3](02-ux-wireframes.md#23-panel--parameter-configuration-expanded),
    [appendix-a-defaults.md](appendix-a-defaults.md)

19. **Two perfect-foresight runs when cost is simulated.** The benchmark that bounds the
    kWh headline minimises grid import; the one that bounds the euro headline minimises
    euros ([§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)). Both run
    when cost simulation is on. This is **required**, not a convenience: the two objectives
    have different optima, so a single DP retargeted by `simulate_cost` would move the
    energy section's ceiling and capture ratio when the user asked for euros — a kWh figure
    changing for a reason unrelated to the household's battery, which is precisely what the
    additive-layer guarantee in
    [§4.5](07-internal-representation.md#shape-of-the-object-without-cost-simulation)
    forbids. The price is a second DP pass (a few seconds) and a second objective to test.
    The only alternative that preserves the guarantee is to show no ceiling in the energy
    section at all, which is cheaper but leaves "you saved 1,412 kWh" unanchored — the
    condition §6.12 exists to prevent. Recorded here because the compute cost is a product
    decision, not because the design is undecided: confirm the two-run cost is acceptable,
    or accept an unanchored kWh headline.
    → [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark),
    [§6.9](11-policies-and-battery.md#69-main-simulation-loop),
    [§2.4](02-ux-wireframes.md#24-panel--results-expanded)

20. **Irregularly-spaced series.** `SeriesFrame.resolution_s` is `int | None`, `None`
    meaning the series has no regular spacing, but three things about that case are
    undefined. What makes a series irregular in the first place — a single missing row
    already reads as a gap under check 3, so the threshold that separates "regular with
    gaps" from "irregular" is unstated. Whether such a series blocks the run, is dropped, or
    is accepted. And what `choose_grid` does with it: it computes `max(resolutions)` over
    the energy series, which is undefined if the list contains `None`, so an irregular
    energy series would currently either crash or be silently excluded from the vote
    depending on how the list comprehension is written.

    The options, roughly in increasing tolerance: reject an irregular series at ingest and
    name it, which is simple and never produces a quietly wrong grid but refuses data a user
    may have no way to regularise; exclude it from the grid vote and reconcile it onto the
    chosen grid by its `kind` (energy summed into buckets, price forward-filled), which
    accepts the data and keeps the grid decision resting on regular series; or infer a
    nominal resolution from the modal spacing and let it vote, which is the most permissive
    and the most likely to pick a grid that misrepresents the data.

    Recorded rather than settled because it is **pre-existing** — the field has always been
    nullable and `choose_grid` has always been undefined on it — and because the right answer
    depends on how often real Home Assistant and CSV exports actually produce irregular
    series, which is not yet known. The reporting half is specified regardless, so the
    frontend is implementable while this stays open: panel ① shows such a series as
    `irregular` with its reconciliation `undefined`, claiming nothing about what the run did
    with it ([§2.2](02-ux-wireframes.md#granularity-per-series)).
    → [§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling),
    [§4.4](07-internal-representation.md#44-internal-normalised-representation),
    [§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order)
