# 9. Prototype experiments

> **Purpose:** the measurements to run against the prototype once it exists, to establish
> which parameters, policies, code paths and diagnostics actually change the answer.
> **Audience:** product owner and implementers, after the first working build.
> **Status:** none of these can be run yet — every one needs a prototype. The list is
> maintained from now so that the questions are framed before the data arrives, rather
> than reverse-engineered from whatever the first run happened to produce.
> **Read with:** [17-open-questions.md](17-open-questions.md), which several of these
> inform, and [appendix-a-defaults.md](appendix-a-defaults.md), the source of most of the
> parameters under test.

## How this differs from §8

[§8](17-open-questions.md) collects things that must be **decided**. They are product
owner's calls: the specification cannot settle them by reasoning or by measurement,
because they are judgements about what the tool should do.

This file collects things that can be **measured**. Each entry is an experiment whose
outcome is a number, obtainable by running the prototype. A measurement does not by itself
decide anything — but for several of §8's entries it changes what is being decided, and in
the best case it dissolves the question entirely. If the choice in §8.1 moves the euro
headline by less than a rounding error on every realistic input, the decision is no longer
about accuracy and becomes about whether to ask the user at all.

Nothing here blocks the build. These are all post-prototype.

## Two audiences for every result

Each experiment serves one or both of:

- **User-facing.** Does this parameter meaningfully change the answer the user sees? If
  not, the UI can stop asking for it, ask for it less prominently, or say plainly that it
  rarely matters. Every question panel ② asks costs the user attention, and the
  five-minute cold-start criterion in
  [§1.6](01-product-brief.md#16-success-criteria) is a budget that these questions spend.
- **Implementation-facing.** If a parameter, policy, code path or diagnostic turns out not
  to change outcomes, can it be simplified or removed? A branch that never changes a
  number is a branch that still has to be written, tested and maintained.

Each entry names which it serves.

## Admission rule

An experiment belongs here only if a decision hangs on its outcome, and only if that
decision would be **different** depending on which way the number comes out. "Interesting
to know" is not sufficient. Each entry therefore states, explicitly, what would be done
differently under each outcome. An entry that cannot state that should be deleted rather
than kept for completeness.

## Data each experiment needs

Three tiers, named per experiment:

- **Synthetic** — runs on the fixtures in
  [16-validation-harness.md](16-validation-harness.md) or on data constructed for the
  purpose. Available as soon as the domain layer runs. No household need volunteer
  anything.
- **One real household, one year** — a single consenting household's own export, covering
  a full annual cycle so that seasonal structure is present. Enough to establish magnitude
  and to rule a parameter out if the effect is tiny.
- **Several real households** — enough to say something about the *spread* across
  household types, which matters for any claim of the form "this rarely matters". A
  parameter that is inert for one household and decisive for another must keep its UI
  control. Target composition: PV and no-PV, hourly and 5-minute recording, dynamic and
  fixed contracts.

Synthetic experiments can be run first and cost nothing. Anything claiming "this does not
matter for users" needs the third tier before it is said in the UI.

---

## Priority order

The ordering is by what it unblocks, not by how interesting the answer is.

| # | Experiment | Serves | Data | Informs |
|---|---|---|---|---|
| X1 | [Does the feed-in floor base matter?](#x1--does-the-feed-in-floor-base-matter) | Both | Synthetic, then one year | [§8.1](17-open-questions.md) |
| X2 | [Cycle-life cost sensitivity](#x2--cycle-life-cost-sensitivity) | User | One year | [§8.3](17-open-questions.md) |
| X3 | [Do the two perfect-foresight runs differ?](#x3--do-the-two-perfect-foresight-runs-differ) | Implementation | Synthetic, then one year | [§8.19](17-open-questions.md) |
| X4 | [Does `economic_guard` change anything?](#x4--does-economic_guard-change-anything) | Both | One year | — |
| X5 | [Is the resolution bias large enough to act on?](#x5--is-the-resolution-bias-large-enough-to-act-on) | User | Several households | — |
| X6 | [Does the feed-in floor assessment period matter?](#x6--does-the-feed-in-floor-assessment-period-matter) | Both | One year | [§8.14](17-open-questions.md) |
| X7 | [Does the floor top-up line ever read nonzero?](#x7--does-the-floor-top-up-line-ever-read-nonzero) | User | Several households | [§8.15](17-open-questions.md) |
| X8 | [Does `supplier_settlement` change the euro figure?](#x8--does-supplier_settlement-change-the-euro-figure) | Both | Several households | [§8.12](17-open-questions.md) |
| X9 | [Does the policy matrix have a stable winner?](#x9--does-the-policy-matrix-have-a-stable-winner) | Both | Several households | [§8.4](17-open-questions.md), [§8.17](17-open-questions.md) |
| X10 | [Does the benchmark's export permission matter?](#x10--does-the-benchmarks-export-permission-matter) | Implementation | Synthetic, then one year | [§8.2](17-open-questions.md) |
| X11 | [How often do the epoch heuristics fire, and how often are they right?](#x11--how-often-do-the-epoch-heuristics-fire-and-how-often-are-they-right) | Both | Several households | [§8.13](17-open-questions.md) |
| X12 | [Does standby draw survive as a separate line?](#x12--does-standby-draw-survive-as-a-separate-line) | Both | One year | — |
| X13 | [Are the DP discretisation levels adequate?](#x13--are-the-dp-discretisation-levels-adequate) | Implementation | Synthetic | — |

X1 through X3 come first because each can retire or reshape a pending decision, and
because all three can be started on synthetic data before any household has volunteered
a year of history.

---

## X1 — Does the feed-in floor base matter?

**Serves:** both. **Data:** synthetic for the binding-frequency half; one real household,
one year, for the euro delta. **Informs:** [§8.1](17-open-questions.md).

**Question.** For a dynamic contract, `bare_supply_price()` may be the hourly spot alone
or spot plus the supplier markup. §8.1 records this as a choice the spec had to make. Does
the choice change any number the user sees?

**Background.** Research recorded in
`changelog/20260723-open-question-1-research.md` established that the 50% floor does not
bind under any currently observed Dutch dynamic offer: every supplier surveyed pays a
feed-in rate far above `0.5 × (spot + markup)`, whether they add a markup, pass the bare
market price through, or subtract a fee. That research also established that the statute
itself does not decompose the base, and that ACM was asked to define it and did not. So
there is a real possibility that the parameter is a stress-test knob rather than a
modelling choice — but that has not been measured against the simulator's own arithmetic,
only inferred from published supplier rates.

**Method.** Two measurements, and the second is the load-bearing one.

1. *Euro delta.* Run one representative PV household over a full year twice, identical in
   every respect except `bare = spot` versus `bare = spot + markup`. Record the difference
   in `cost.saved_eur`, in euros and as a percentage of the headline.
2. *Binding frequency.* Instrument `feedin_floor_topup()` to record, per interval, whether
   the floor was the operative term — that is, whether `α × bare` exceeded the contractual
   feed-in rate. Report the fraction of exporting intervals in which it bound, under each
   of the three observed supplier shapes (markup added, markup absent, fee subtracted) and
   under each choice of base.

The second measurement is what generalises. The first is one household's arithmetic; the
second says whether the parameter can reach the result at all.

**Decision it informs.** If the floor never binds on any realistic offer shape, §8.1 stops
being a question about which reading of the law is right and becomes a question about
whether to expose the base at all: the parameter would then be a stress-test scenario
("what if my supplier pays the legal minimum?"), which is a legitimate thing to offer but
belongs behind an advanced control with that label, not among the primary contract
questions. If it binds on some plausible shape, the reading matters, §8.1 stays a live
decision, and the spec's current choice needs to be defended rather than merely recorded.

---

## X2 — Cycle-life cost sensitivity

**Serves:** user-facing. **Data:** one real household, one year. **Informs:**
[§8.3](17-open-questions.md).

**Question.** `degradation_eur_per_kwh` defaults to 0. §8.3 observes that a realistic value
— around €0.08/kWh for a €5,000 / 10 kWh / 6,000-cycle system — is large enough to reverse
most arbitrage conclusions. Does it, on real data?

**Method.** Sweep `degradation_eur_per_kwh` across 0, 0.02, 0.05, 0.08 and 0.12 €/kWh over
one household-year, for each of the nine charge×discharge policy combinations. Record for
each cell: `cost.saved_eur`, `efc`, and the rank of that policy within the matrix. Then
find the value of `degradation_eur_per_kwh` at which the ranking first changes, and the
value at which the best policy's saving first crosses zero.

The crossing point is the useful output. "Arbitrage stops paying above €0.06/kWh of
throughput" is a statement a user can check against their own battery's warranty.

**Decision it informs.** Directly §8.3's three options. If the ranking is stable across the
whole sweep, shipping 0 is harmless and the parameter can stay an advanced control. If the
ranking inverts somewhere inside the plausible range — which is what §8.3 expects — then
shipping 0 means shipping a default that recommends the wrong policy, and the choice
narrows to setting a non-zero default or requiring an answer. The crossing point also gives
the results panel something concrete to say, which is more useful than the parameter
itself.

---

## X3 — Do the two perfect-foresight runs differ?

**Serves:** implementation-facing. **Data:** synthetic first, then one household-year.
**Informs:** [§8.19](17-open-questions.md).

**Question.** Runs D and E are the same DP under different objectives
([§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)). The additivity
argument establishes that both are *needed*: retargeting a single DP would move the energy
section's ceiling when the user asked for euros, which the invariant in
[§4.5](07-internal-representation.md#shape-of-the-object-without-cost-simulation) forbids.
That argument is settled and this experiment does not reopen it. What is not known is how
far apart the two dispatches actually land on real data.

**Method.** Over one household-year with cost simulation on, compare the two DP traces
directly: the fraction of intervals in which the two policies choose a different action,
the mean absolute difference in SoC across the window, and the two capture ratios each
benchmark produces against the other's objective (the energy DP's euro saving, the cost
DP's kWh saving). Fixture 20 already asserts the traces are *not identical*; this measures
by how much. Run the synthetic square-wave case from fixture 20 first to establish that the
instrumentation reports what it should on a case with a known answer.

**Decision it informs.** Not whether to keep both runs — that is settled. Whether the second
run's cost is worth carrying at its current fidelity. If the two dispatches are near
identical on real data despite differing in principle, the cost DP could plausibly run at
reduced `dp_soc_levels` and `dp_action_levels`, or be computed lazily when the user first
opens the cost section, halving the perceived run time for the majority who never look. If
they diverge substantially, the second run is doing real work at full fidelity and the
compute cost stands as specified — which is the confirmation §8.19 actually asks for.
Interacts with X13.

---

## X4 — Does `economic_guard` change anything?

**Serves:** both. **Data:** one real household, one year.

**Question.** `economic_guard` defaults false and is forced off without cost simulation. When
enabled it suppresses grid export whenever `p_export_net ≤ 0`
([§6.7](11-policies-and-battery.md#67-discharge-policy)). It is one of the few settings that
makes a cost input reach the dispatch path, and therefore one of the few that can make the
kWh results differ between cost modes. How often does it actually fire, and what does it
change?

**Method.** Run one household-year with cost simulation on and `allow_grid_export` on,
twice, with the guard off and on. Record: the fraction of intervals in which the guard
suppressed a nonzero `req_grid`, the resulting difference in `saved_eur`, and the resulting
difference in `saved_kwh`. Repeat with `allow_grid_export` off, where the guard should be
provably inert — it only ever zeroes `req_grid`, which is already zero — as a control that
confirms the instrumentation is measuring the guard and not something else.

**Decision it informs.** Three outcomes, three different actions. If the guard never fires
under a realistic dynamic contract, it can be demoted to an advanced control with a note,
and the ordinary user never sees it. If it fires and improves the euro figure materially,
its default should be reconsidered: a setting that reliably makes the user money while
defaulting off is a poor default, and the "policies stay literal" rationale in
[appendix-a-defaults.md](appendix-a-defaults.md) would need to be weighed against it
explicitly rather than assumed. If it fires but changes the euro figure only trivially while
changing the kWh figure noticeably, that is the awkward case — a cost setting perturbing an
energy headline for no cost benefit — and the honest response is to remove it. The control
run also confirms whether the guard is genuinely inert without export, which if true means
the UI can hide it whenever `allow_grid_export` is off.

---

## X5 — Is the resolution bias large enough to act on?

**Serves:** user-facing. **Data:** several real households.

**Question.** [§6.13](14-diagnostics.md#613-resolution-bias-diagnostic) already computes the
hourly-versus-5-minute difference; the spec estimates 5–20% and says it must be measured
rather than assumed. The experiment is not whether to measure it — that is specified — but
whether the measured spread is wide enough that the tool should actively push users toward
finer data.

**Method.** Collect `diagnostics.resolution_bias_pct` across every household that has a
5-minute trailing window, along with `overlap_pct` from
[§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly),
PV presence, and battery size. Report the distribution, not the mean. Separately, test
whether `overlap_pct` predicts the bias well enough to serve as a proxy — it is available
on the full window and needs no 5-minute data, so a usable relationship would extend the
diagnostic to every user rather than only those with fine-grained history.

**Decision it informs.** If the bias is consistently small, §6.13 stays a quiet advisory in
the caveats box and nothing changes. If it is consistently large, the tool should say so
before the run rather than after — a household about to invest thousands of euros on an
hourly-data estimate that systematically overstates the benefit deserves to be told at data
selection time, which is a panel ① change, not a panel ③ one. If it is large but highly
variable, neither blanket message is honest and the only defensible option is per-household
reporting, which is what is already specified. The proxy result decides separately whether
the caveat can be shown to users with no 5-minute data at all.

---

## X6 — Does the feed-in floor assessment period matter?

**Serves:** both. **Data:** one real household, one year.

**Informs:** [§8.14](17-open-questions.md).

**Question.** Artikel 2.34, zevende lid Energiewet assesses the non-negativity floor
"gemiddeld gewogen over een periode van een maand", without saying whether that is a minimum
or the only lawful window ([§8.14](17-open-questions.md)). So the experiment asks two things
at once: how much would a quarter or a year cost the household, and does the period reach
the result at all? The second matters because if it does not, the legal reading need not be
resolved before shipping.

**Method.** One household-year, cost simulation on, sweeping `feedin_floor_period` over
month, quarter and year with everything else fixed. Record `feedin_floor_topup` and
`saved_eur` under each. Construct the accompanying synthetic case too: the sweep only
produces a nonzero spread if the household had months whose export earned a net negative
unclamped amount, which on real Dutch data may be rare and on some households may not occur
at all. A synthetic year with a deliberately negative-price-heavy summer establishes what the
spread looks like when the term is live, which is what tells you whether a zero real-data
spread means "does not matter" or "did not occur this year".

**Decision it informs.** §8.14, and in the useful case it dissolves it. If the spread is
zero or negligible on real data, the parameter can be fixed at the calendar month the
statute names and dropped from panel ② rather than merely defaulted — one fewer question
about a supplier term the user almost certainly does not know, and the unresolved question
of whether longer periods are lawful stops blocking anything. If the spread is material,
the reading has to be settled before the default can be defended: under the fixed-period
reading one month is the only lawful setting and the others are stress tests; under the
minimum-period reading a calendar month is the most favourable setting available and
defaulting to it flatters the result, so it has to be asked for or folded into the feed-in
preset. Note that no supplier has published 2027 terms, so this experiment bounds the stakes
of the decision without being able to settle what suppliers will actually do.

---

## X7 — Does the floor top-up line ever read nonzero?

**Serves:** user-facing. **Data:** several real households. **Informs:**
[§8.15](17-open-questions.md).

**Question.** §8.15 asks whether the results panel should show the feed-in floor top-up at
all, on the reasoning that it "will read as €0.00 for almost every user". That reasoning is
an expectation, not a measurement.

**Method.** Across every household run with cost simulation on, record the fraction for
which `feedin_floor_topup` is nonzero at all, and where nonzero, its size relative to the
other waterfall lines. Piggybacks on X6, which produces the same term under a parameter
sweep; this one asks only how often it is live under default settings.

**Decision it informs.** §8.15's three display options, and the choice among them turns
entirely on this frequency. Never nonzero across a real population supports folding it into
`lost_feedin_compensation` for display — §8.15's own recommendation — and keeping it separate
only in the result JSON. Occasionally nonzero supports showing it conditionally. Frequently
nonzero makes it an ordinary waterfall line and removes the question. The decision is cheap
to reverse either way, which is why this sits at X7 and not higher.

---

## X8 — Does `supplier_settlement` change the euro figure?

**Serves:** both. **Data:** several real households, with quarter-hourly `spot_min`/
`spot_max` available. **Informs:** [§8.12](17-open-questions.md).

**Question.** `supplier_settlement` defaults to hourly, which silently disables the price
bracket in [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)
for most users. §8.12 asks whether that default is right or whether the app should ask. The
measurable half is how wide the bracket is when it does apply.

**Method.** For households with hourly energy data and quarter-hourly price information,
compute the bracket regardless of the configured settlement, and record its width as a
percentage of `saved_eur`. Alongside it, record `intra_hour_spread`, which §6.16 already
specifies as a standalone indicator. Report both distributions.

**Decision it informs.** If the bracket is narrow wherever it applies, defaulting to hourly
costs the user nothing even when the default is wrong for them, and §8.12 resolves toward
keeping the default and not adding a setup question. If it is wide, a silently wrong default
hides a real uncertainty band from exactly the users who have it, and the app should ask —
the friction is then justified. The `intra_hour_spread` distribution separately determines
whether the "large spread with hourly settlement is an argument for switching supplier"
insight that §6.16 contemplates is worth surfacing prominently or is a curiosity.

---

## X9 — Does the policy matrix have a stable winner?

**Serves:** both. **Data:** several real households. **Informs:**
[§8.4](17-open-questions.md), [§8.17](17-open-questions.md).

**Question.** Two related things. §8.4 asks whether to evaluate all nine charge×discharge
combinations and present a matrix rather than one configuration at a time. §8.17 asks
whether D1 should remain a separate option for households without PV, where it is expected
to be the policy most likely to lose money under a dynamic contract. Both turn on the same
underlying measurement: how much the policy choice actually moves the result, and whether the
best choice is predictable from household characteristics.

**Method.** Run the full nine-cell matrix for every household in the panel, in both cost
modes, recording `saved_kwh` and `saved_eur` per cell. Then ask: is the winning cell the same
across households, or does it depend on PV presence, contract type, load shape, battery size?
How large is the gap between the best and the default cell? And specifically for §8.17,
across no-PV households under a dynamic contract, where does D1 rank and does it ever produce
a negative euro saving?

**Decision it informs.** For §8.4: if one cell wins nearly everywhere, the matrix UI is not
worth building and a good default plus an explanation serves better. If winners vary by
household in a way the app can see in the data, the matrix earns its place — and might even
be reduced to a recommendation. If they vary unpredictably, the matrix is the only honest
presentation, since the app cannot advise. For §8.17: if D1 without PV loses money on real
data, that is the demonstration §8.17 says keeping it exists to provide, and it can be kept
with a warning attached rather than merely kept. If it does not lose money, the concern
motivating §8.17 was unfounded and the option keeps its place without qualification.

---

## X10 — Does the benchmark's export permission matter?

**Serves:** implementation-facing. **Data:** synthetic first, then one household-year.
**Informs:** [§8.2](17-open-questions.md).

**Question.** §8.2 asks whether the perfect-foresight benchmark should inherit
`allow_grid_export`. Both readings are defensible and §8.2 once stated they "differ
materially". By how much?

**This is now a reading, not an A/B.** As of the §8.2 revision the simulator computes both
bounds whenever `allow_grid_export` is off — the inheriting one and the unconstrained one
both land in `benchmarks.*` ([§4.5](07-internal-representation.md#45-result-object)). So the
divergence is a by-product of ordinary export-off runs, not something a bespoke experiment
has to generate. The experiment is therefore: **collect the two capture ratios across
whatever export-off runs are available and characterise how far apart they sit.**

**Method.** Two measurements.

1. *Synthetic bound.* Run the no-PV arbitrage case (fixture 16), where the unconstrained
   bound is analytically approachable, and confirm the computed `*_unconstrained` figures
   match the analytic maximum. This validates the second DP before its output is trusted.
2. *Real spread.* Over each available household-year with `allow_grid_export = false`,
   record `capture_ratio` versus `capture_ratio_unconstrained` in both the energy and cost
   blocks, and report the distribution of the gap. With export permitted the two are equal
   by construction (`*_unconstrained` is `null`), which is the trivial control.

**Decision it informs.** §8.2's *remaining* questions — both now presentational, since the
compute decision is settled by computing both. If the gap is consistently small, the
"…if export allowed" row is clutter and `benchmark_divergence_display_threshold` can be
raised until it effectively never fires; the primary inheriting ratio stands alone. If the
gap is consistently wide, the row earns its place, the threshold stays low, and the
primary-figure label has to name which bound it reports — because a wide gap means the
capture ratio is not comparable across users with different export settings, a claim the
results panel currently makes implicitly. The threshold's shipped default of 0.02 is a
provisional guess this measurement is meant to replace with a value read off the observed
distribution.

---

## X11 — How often do the epoch heuristics fire, and how often are they right?

**Serves:** both. **Data:** several real households, with ground truth. **Informs:**
[§8.13](17-open-questions.md).

**Question.** [§6.15](13-configuration-epochs.md) carries four heuristics — PV commissioning,
PV capacity change, battery commissioning, undeclared battery — plus undeclared-PV detection.
§8.13 already suspects the capacity-change one produces too many false positives, which is
why it ships disabled. The others have never been tested against a household that knows what
actually happened.

**Method.** For each participating household, collect the ground truth first — installation
dates for PV and battery, any panel additions, any inverter replacement — and only then run
detection, so the ground truth is not contaminated by the algorithm's output. Record per
heuristic: fired or not, correct or not, and the date error where it fired correctly. Run
`pv_capacity_change_detection` in both its shipped-off state and forced on, since its false
positive rate is the specific thing §8.13 asserts without evidence. Include households with
no installation events, which is where false positives live and where a heuristic that
fragments a clean window does the most damage.

**Decision it informs.** For §8.13: whether shipping capacity-change detection disabled is a
sound precaution or an unnecessary loss of a working feature. For the rest: a heuristic that
never fires correctly across the panel should be removed rather than left as a question the
user has to dismiss, and one that fires often and correctly could be promoted from "asked as a
question" to "proposed with a default answer". The undeclared-battery flat-top signal is the
one to watch, since it is the only signal available in a no-PV household and its
`flat_top_fraction > 0.3` threshold has no stated derivation.

---

## X12 — Does standby draw survive as a separate line?

**Serves:** both. **Data:** one real household, one year.

**Question.** Run B exists solely to isolate standby consumption
([§6.9](11-policies-and-battery.md#69-main-simulation-loop)), and `standby_w` defaults to 30 W
— about 260 kWh/year, which appendix A calls "material, routinely omitted". Is it material
against the headline, and is the extra run the only way to get it?

**Method.** Over one household-year, record `energy.standby_kwh` and `standby_cost` as
percentages of `saved_kwh` and `saved_eur`. Then test whether run B is separable: compare the
isolated standby cost against the analytic estimate `standby_w × hours × p_import`, over the
same window. If the two agree closely, the third run is computing something a formula
already gives.

**Decision it informs.** If standby is a large fraction of the saving, it stays a headline
line and `standby_w` deserves a prominent control with real guidance on where to find the
figure — a user entering 0 because they do not know the number would then be materially
overstating their result. If it is small, the control can be demoted. Separately, if the
analytic estimate matches run B closely, run B can be dropped and the line computed directly,
removing a full simulation pass from every request — but only if the agreement holds where
the battery is near its SoC limits, which is where the two should diverge, so that case must
be tested explicitly rather than assumed away.

---

## X13 — Are the DP discretisation levels adequate?

**Serves:** implementation-facing. **Data:** synthetic.

**Question.** `dp_soc_levels = 101` and `dp_action_levels = 41` are stated without
derivation. §6.12 notes that interpolating `V` rather than snapping avoids "a systematic
pessimism bias of several percent", which implies the discretisation is coarse enough for the
choice to matter. Are these values converged?

**Method.** Sweep both parameters — SoC levels over 51, 101, 201, 401; action levels over 21,
41, 81 — on a synthetic case whose optimum is analytically known (fixture 16's square wave)
and on one household-month of real data. Record the benchmark value and the wall-clock time at
each setting. Find the point at which the benchmark stops moving by more than 0.5%.

**Decision it informs.** If 101×41 is already converged, the defaults are confirmed and can be
documented as such rather than left unexplained in appendix A. If the benchmark is still
moving at 101×41, the capture ratio — which is the number the whole benchmark exists to
produce — carries a discretisation error the user is not told about, and either the defaults
rise or the ratio needs a stated precision. If it converges well below 101×41, both DP runs
can be made cheaper, which bears directly on X3 and on §8.19's compute-cost question. Purely
synthetic, so this can be run the day the DP works.

---

## Recording results

When an experiment is run, record its outcome in a changelog entry and update the entry here
with the finding and its date. Do not delete the entry — an experiment whose result closed a
question is the evidence for that closure, and it is what a later reader needs when asking
why a parameter was removed. Where a result resolves a §8 open question, update that question
too rather than leaving §8 pointing at an experiment that has already answered it.
