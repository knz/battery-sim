# 8. Open questions for the product owner

> **Purpose:** decisions the specification does not make, ordered by how much rework the
> answer causes if deferred.
> **Audience:** product owner.
> **Status:** all are open. Where the spec had to pick something to remain
> implementable, the choice it made is stated and marked as a choice, not a finding.
> **Read with:** [19-prototype-experiments.md](19-prototype-experiments.md). This file
> collects what must be **decided**; that one collects what can be **measured** once a
> prototype exists. Several questions below carry a pointer to an experiment whose
> outcome would inform the decision, and in some cases dissolve it — a parameter that
> provably changes nothing is not a question about which value to pick.
> A closing **Watch items** section collects external events — pending legislation or
> regulator action — that would change an answer above without anyone here deciding
> anything.

1. **Feed-in reference for dynamic contracts.** For a dynamic contract, is the 50% floor
   taken on the hourly spot price alone, or on spot plus the supplier's markup? The spec
   assumes `bare = spot + markup` for import and applies α to that same `bare` for export.
   That is a choice, not a finding. It moves feed-in revenue by roughly 1 ct/kWh.

   **What the statute says.** The operative provision is
   [artikel 2.34, negende lid Energiewet](18-dutch-electricity-background.md#e52-the-rules-on-compensation),
   in force from 1 January 2027: the compensation is "niet minder dan 50% van de voor de te
   leveren elektriciteit **overeengekomen prijs**". That phrase is the whole of it. The
   statute does not decompose the agreed price into components and does not contemplate a
   price that varies by the hour. Note that "kale leveringsprijs", the term this question
   was originally written around, does not appear in the statute at all — it is a gloss
   applied downstream, and it is not a defined term.

   **What ACM has supplied.** One reading, and only in the tax direction. Besluit
   modelcontracten 2026, toelichting rn. 65, says the base is "het kale leveringstarief,
   dus het leveringstarief per kWh zonder energiebelasting en btw", added because
   consultation respondents were confused by the draft. Rn. 66 confirms the floor binds
   every contract type, dynamic included: "geldt voor elk type contract". Neither settles
   the markup. The words *inkoopvergoeding*, *beursprijs*, *spotprijs* and *marktprijs* do
   not occur anywhere in the 43-page decision, and it contains no formula and no worked
   example for the floor.

   **Why the gap is structural.** ACM asked, in its advice on the bill of 17 September
   2024, for "redelijke terugleververgoeding" to be defined before enactment. The
   legislature supplied a percentage instead of a definition. ACM's most active instrument
   is the model contract, and dynamic contracts sit outside that regime by design — the
   Energiewet requires model contracts for fixed and variable tariffs only, and ACM has
   said it will not make a dynamic one. So the regulator best placed to close the gap is
   using an instrument that cannot reach the contracts where the gap bites.

   **Why supplier practice does not disambiguate it.** The floor does not bind under any
   currently observed Dutch dynamic offer. Suppliers split three ways on the feed-in
   side — markup added, markup absent, fee subtracted — and even the least generous
   observed (Tibber, spot − 2.48 ct) exceeds 0.5 × (spot + markup) at any positive spot
   price. A rule that never binds generates no practice and no dispute, so there is nothing
   to read the base off. No supplier has published binding post-2027 terms.

   **What the July 2026 consultation showed.** The Wijzigingsregeling Energieregeling
   consultation closed on 10 July 2026 with nine public responses; all nine were read and
   none raised the base for dynamic contracts. Energie-Nederland, the supplier trade body
   and the party best placed to flag it, did raise price-structure neutrality — but about
   the terugleverkosten *presentation* duty, not about the floor's base. Two caveats on how
   much this carries: the consultation's subject was terugleverkosten presentation and
   invoicing, so a respondent could reasonably have judged the base out of scope; and nine
   responses, three of them from organisations, is a small sample. It is consistent with
   the industry not treating this as live. It is not proof of that.

   **The two readings, and what each rests on.** *Spot alone* reads "overeengekomen prijs"
   as the price of the commodity, so the floor tracks the market and the supplier's margin
   is not something it has to hand back; this fits the tax-exclusive direction ACM took,
   which strips components that are not the supplier's own commodity charge. *Spot plus
   markup* reads it as the price actually agreed in the contract, which for a dynamic
   contract is spot plus the stated markup and is what the customer in fact pays per kWh;
   this fits the ordinary meaning of "overeengekomen" and matches how the spec already
   builds the import price. Neither reading has been adopted by any instrument. The spec
   takes the second because import and export then share one `bare`, which is an internal
   consistency argument, not a legal one.

   **What would resolve it,** in the order it could plausibly arrive. First, the final
   Energieregeling text — the consultation is closed and the draft toelichting still
   carries a "[PM aantal]" placeholder, so publication is pending; this is the near-term
   watch, recorded as [§8.21](#watch-items) below. Second, ACM guidance or a
   model-contract revision that reaches dynamic contracts, which would require ACM to act
   outside the instrument it has chosen. Third, the first published post-2027 dynamic
   offers, expected Q4 2026 — but these resolve the question only if some supplier prices
   *at* the floor, and none currently does.

   **It may never be resolved authoritatively.** A floor that never binds never needs a
   definition. If that holds, the practical answer to this question is not which reading is
   legally correct but that the floor is not the operative constraint on feed-in revenue,
   and the base is a stress-test parameter rather than a modelling choice.
   [Experiment X1](19-prototype-experiments.md#x1--does-the-feed-in-floor-base-matter)
   is what would establish that from the simulator's own arithmetic: if the base provably
   moves no number the user sees, this question retires without a legal answer, and what
   remains is the product decision of whether to expose the base at all.
   → [§6.5](10-pricing.md#65-price-curves),
   [E5.2](18-dutch-electricity-background.md#e52-the-rules-on-compensation),
   [experiment X1](19-prototype-experiments.md#x1--does-the-feed-in-floor-base-matter)

2. **Should the perfect-foresight benchmark be allowed to export?** Currently it inherits
   `allow_grid_export`. Inheriting makes the capture ratio a fair comparison of *policy
   quality*; not inheriting makes it a comparison against the true physical maximum. Both
   are defensible and they differ materially. Recommendation: inherit, and offer the
   unconstrained bound as a secondary figure.
   → [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark),
   [experiment X10](19-prototype-experiments.md#x10--does-the-benchmarks-export-permission-matter)

3. **Cycle-life cost.** Currently reported as cycles only, with an optional
   €/kWh-throughput term defaulting to 0. Confirm that a policy doing 700 cycles/yr
   ranking above one doing 300 with similar savings is acceptable output, or set a
   non-zero default (a €5,000 / 10 kWh / 6,000-cycle system implies ≈ €0.08/kWh
   throughput, which is large enough to reverse most arbitrage conclusions).
   → [§6.10](10-pricing.md#610-cost-accounting),
   [appendix-a-defaults.md](appendix-a-defaults.md),
   [experiment X2](19-prototype-experiments.md#x2--cycle-life-cost-sensitivity)

4. **Multiple policy comparison in one run.** The current UI evaluates one configuration
   at a time. Since a full run costs seconds, evaluating all nine charge×discharge
   combinations and presenting a matrix would be far more useful than sequential manual
   exploration. This is a significant UX addition — worth deciding before build rather
   than retrofitting panel ③.
   → [§2.4](02-ux-wireframes.md#24-panel--results-expanded),
   [experiment X9](19-prototype-experiments.md#x9--does-the-policy-matrix-have-a-stable-winner)

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
    → [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch),
    [experiment X8](19-prototype-experiments.md#x8--does-supplier_settlement-change-the-euro-figure)

13. **PV capacity-change detection** is the weakest of the epoch heuristics — seasonal
    variation, soiling and shading all produce similar signatures, and a false positive
    fragments the window unhelpfully. Consider shipping it disabled, surfacing it only as
    a note in the data-quality panel.
    → [§6.15](13-configuration-epochs.md),
    [experiment X11](19-prototype-experiments.md#x11--how-often-do-the-epoch-heuristics-fire-and-how-often-are-they-right)

14. **Feed-in floor assessment period — is it a parameter at all?** The statute names one
    period and only one: artikel 2.34, zevende lid Energiewet requires the compensation to
    be non-negative "gemiddeld gewogen over een periode van een maand". It does not say
    *ten minste een maand*, and it does not say *precies een maand*. So there are two
    readings and the sources consulted settle neither.

    Under the **fixed-period reading**, one month is the assessment window the law
    prescribes, `feedin_floor_period` has exactly one lawful value, and the parameter is a
    constant that should not be exposed at all — at most a stress-test control, labelled as
    modelling something the law may not permit. Under the **minimum-period reading**, a
    supplier may assess over a quarter or a year, longer windows absorb more negative
    intervals and are therefore weakly less favourable to the household, and the current
    calendar-month default is the most favourable setting available — an optimistic default
    that should be either asked for or folded into the feed-in preset.

    Note what is *not* being claimed. The statute's silence does not establish that longer
    periods are forbidden any more than it establishes that they are permitted. Neither
    reading should be treated as the settled one.

    The decision owed is therefore first which reading to build on, and only then, if the
    minimum-period reading is taken, what the default should be. Two things bound how much
    turns on it: no supplier has published 2027 terms, so any answer is provisional; and
    [experiment X6](19-prototype-experiments.md#x6--does-the-feed-in-floor-assessment-period-matter)
    measures whether the period reaches the result at all. If the spread across month,
    quarter and year is negligible on real data, the reading does not need to be resolved
    to ship — the parameter can be fixed at one month, matching the statutory text, with
    nothing at stake either way.
    → [§6.5](10-pricing.md#the-feed-in-floor-is-a-period-aggregate-not-a-per-interval-clamp),
    [E5.2](18-dutch-electricity-background.md#e52-the-rules-on-compensation),
    [experiment X6](19-prototype-experiments.md#x6--does-the-feed-in-floor-assessment-period-matter)

15. **Should the results panel show the feed-in floor top-up at all?** It is a genuine
    waterfall term and it closes the identity exactly, but it will read as €0.00 for
    almost every user, and a permanently-zero line in a six-line summary costs attention
    for nothing. Options: always show it; show it only when nonzero; or fold it into
    `lost_feedin_compensation` for display while keeping it separate in the result JSON.
    The third preserves the exact decomposition for anyone reading the export while
    keeping the panel clean, and is the recommendation.
    → [§6.10](10-pricing.md#610-cost-accounting),
    [§2.4](02-ux-wireframes.md#24-panel--results-expanded),
    [experiment X7](19-prototype-experiments.md#x7--does-the-floor-top-up-line-ever-read-nonzero)

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
    [§2.3](02-ux-wireframes.md#without-pv),
    [experiment X9](19-prototype-experiments.md#x9--does-the-policy-matrix-have-a-stable-winner)

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
    [§2.4](02-ux-wireframes.md#24-panel--results-expanded),
    [experiment X3](19-prototype-experiments.md#x3--do-the-two-perfect-foresight-runs-differ)

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

## Watch items

External events that would change an answer above, with what to check and when. This is
the only entry so far; the format is deliberately minimal — what, where, what to look for,
when.

21. **Watch item — final Wijzigingsregeling Energieregeling.**

    *What.* Publication of the final text of the Wijzigingsregeling Energieregeling
    (presenteren en factureren terugleverkosten, plus the Regeling garanties van
    oorsprong), and specifically whether the toelichting's "[PM aantal] partijen" placeholder
    in §4.1 has been filled in — while it stands, the text is still the unprocessed draft.

    *Where.* The consultation page on `internetconsultatie.nl`
    (`wijzigingsregeling_energieregeling_en_regeling_gvo`), for the published response
    report and any link to the final regulation; and `officielebekendmakingen.nl` for the
    Staatscourant publication itself.

    *What to look for.* Any decomposition of "de voor de te leveren elektriciteit
    overeengekomen prijs"; any occurrence of *inkoopvergoeding*, *beursprijs*, *spotprijs*
    or *marktprijs*, none of which appear in the draft; and any carve-out or special rule
    for dynamic contracts. Any of these would bear directly on §8.1. Also worth noting
    is whether the response to Energie-Nederland's price-structure-neutrality point extends
    beyond the presentation duty.

    *When.* The consultation closed 10 July 2026 and this was written on 23 July 2026, so
    the final text was not expected yet. Re-check within weeks rather than months; the
    regulation is to enter into force on 1 January 2027, which puts publication well before
    then.
    → §8.1 above,
    [E5.2](18-dutch-electricity-background.md#e52-the-rules-on-compensation)
