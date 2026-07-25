"""The §6.10 cost accounting — turning flows plus price curves into euros, and into the waterfall.

This is the second half of the cost path. `app/domain/pricing.py` (§6.5) turned a contract into
the per-interval EUR/kWh arrays; this module spends them against the §6.9 flow arrays and produces
the two things panel ③'s euro side is built from: the bill over the window for one run, and the
eight-line decomposition of the difference between the baseline and the battery scenario.

It is pure, in the same sense `app/domain/metrics.py` is pure: `Flows` in, bare floats out. No
formatting, no translation, no I/O, no clamping for display. `app/results_view.py` owns
presentation.

## What "cost" means here, and what is deliberately not in it

**Fixed costs are EXCLUDED — vastrecht, netbeheerkosten and the vermindering energiebelasting are
not added anywhere in this module, and adding them would be a regression, not a fix.** §6.10 states
the exclusion and background E2.5 is the authority: the test for inclusion is whether a component
responds to consumption at all. Netbeheerkosten is a capaciteitstarief set by the size of the
connection, so a 1x25 A connection pays the same on 500 kWh as on 5,000; the vermindering is a flat
annual credit per connection. Neither responds to a battery, so both cancel exactly out of a
before-and-after comparison — and since the headline figure is a saving and a percentage, folding
them in would leave the euro saving unchanged while diluting the percentage by an arbitrary
constant. §6.10 suggests showing them greyed out in an informational strip if total-bill context is
wanted; that is a VIEW concern, and this module deliberately gives the view nothing to add them
into.

So `compute_costs` returns a *marginal* bill: the part of the bill that responds to what the
household did with its electricity. It is not the number at the bottom of an energy invoice, and no
caller should present it as one.

## The four things this module has to get right

**1. The export term is SUBTRACTED, and `p_export_net` is frequently negative.** §6.5 clamps
nothing, so `compensation - terugleverkosten` goes negative at any bare price below roughly
8 ct/kWh on the shipped alpha = 0.50 and a 4 ct/kWh charge — not only during negative-price hours.
Subtracting a negative export term ADDS to the bill: exporting costs money. §6.10 calls that
intended, and "one of the more important things this tool can show a user". A `max(0, .)` anywhere
below would hide exactly the effect the tool exists to surface.

**2. Gap intervals contribute exactly zero — not NaN, and not a number.** §6.9 writes NaN into the
flow arrays on a gap (`Flows`'s docstring: a 0 in `imp` would be the positive claim "nothing was
imported", which is what the simulation declined to assert), and §4.4 writes NaN into `spot` where
no price covers the interval, which propagates through §6.5's arithmetic into every price array.
`NaN * price` and `flow * NaN` are both NaN, so a plain `.sum()` would poison the whole window's
euro figure off a single missing interval. Every sum here is therefore `np.nansum`, which is the
same decision `Flows.totals()` takes for kWh and `pricing.feedin_floor_topup` takes for the period
aggregate: absence on EITHER side excludes the interval, and the three layers agree on what a gap
costs, which is nothing.

That is an exclusion, not an imputation. A window that is half gap is costed over the half that is
present, and the euro figure is a bill for those intervals only. The frame already reports
`spot_missing_intervals` and §4.5 carries the gap diagnostics, so a caller can say how much of the
window the number covers; this module does not re-report it and does not scale the answer up to a
full window, which would be a forecast rather than a reconstruction.

**3. The top-up is a separate waterfall line, and folding it in would break the identity.** §6.5
and §6.10 both refuse the fold, for the same reason. The other seven lines are per-interval
quantities split by sign, and splitting by sign is lossless — that is precisely why the
decomposition is EXACT rather than approximate. The floor top-up is a period-level scalar with no
per-interval decomposition at all, so pushing it into `lost_feedin_compensation` would require
choosing an allocation across intervals, and the identity would quietly become a convention that
happens to sum correctly. As its own line it stays exact, and it is a DIFFERENCE — `topup(C) -
topup(A)`, what the battery actually changed about the floor, not the top-up either scenario
received. Usually zero on both sides and therefore zero in the waterfall; visible only when a
period's export earned a net negative amount in one scenario and not the other (fixture 14).

**4. `compute_costs` stays array-shaped.** §6.5's "pre-2027 extension point" note: reintroducing
salderen means inserting an ANNUAL NETTING STAGE between the flow simulation and the cost
accounting, not rewriting these functions. That stage consumes flow arrays and produces flow
arrays, so `compute_costs` takes `Flows` and per-interval prices and must keep doing so. Collapsing
the flows to scalars at the call site — passing a total imported kWh and a mean price — would work
today, produce the same number under a flat price, and make the netting stage impossible to insert
without rewriting every caller.

## Sign conventions, since half the lines are negative by construction

`compute_costs` returns a BILL: positive means the household paid. The waterfall lines are
SAVINGS relative to the baseline: positive means the battery made the household better off. So
`avoided_grid_import` is positive, `added_grid_import_charging` is negative, and the eight sum to
`cost(A) - cost(C) - degradation`, which is the euro saving. Nothing here is clamped to a sign, and
a negative total is a legitimate result — a battery can lose money, exactly as §7.2 item 9's
negative kWh saving is a legitimate result on the energy side.

## What is deliberately NOT here

    fixed costs                  excluded on purpose; see above. Not a gap to be filled.
    runs D and E, the cost benchmark   §6.12, Phase 4.
    the "enabled": false presentation of a zero degradation line   §4.5 shows the line carrying
                                 that flag; deciding a line is disabled is a statement about the
                                 CONFIG (`degradation_eur_per_kwh == 0`, appendix A's default), not
                                 about the computed number, and a run can produce a 0.00 line for
                                 arithmetic reasons (nothing withdrawn) while degradation is
                                 perfectly enabled. Conflating the two here would lose that
                                 distinction; the view reads the config alongside the waterfall and
                                 renders the flag. `waterfall` reports the euro figure only.
    percentages, currency formatting, ordering for display   `app/results_view.py`.
    the §4.5 diagnostics for the floor   they travel on `pricing.FeedinFloorResult`; `CostResult`
                                 carries the two top-ups it needed rather than restating them.

Main items:
    WATERFALL_LINES       the eight §6.10 labels, in §6.10's order.
    CostResult            one run's bill, with the top-up that was netted out of it.
    WaterfallLine         one labelled euro term.
    compute_costs(flows, p_import, p_export_net, compensation, index, cfg) -> CostResult
    waterfall(a, b, c, p_import, compensation, tlk, cfg, index, p_export_net) -> list[WaterfallLine]
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.pricing import feedin_floor_topup
from app.domain.simconfig import PricingConfig
from app.domain.simulate import Flows

# §6.10's eight lines, in §6.10's order and with §6.10's exact label strings. Named here rather
# than only being built inline so a test can assert the order and the spelling against one list,
# and so a view can key translations off it without importing the computation.
WATERFALL_LINES = (
    "avoided_grid_import",
    "added_grid_import_charging",
    "avoided_terugleverkosten",
    "lost_feedin_compensation",
    "arbitrage_export_revenue",
    "standby_consumption",
    "feedin_floor_topup",
    "degradation",
)


def _nansum(values: np.ndarray) -> float:
    """Gap-excluding sum — the one place this module decides what a missing interval costs.

    `np.nansum` rather than `.sum()`, for the reason in the module comment: a gap is NaN in the
    flow arrays and an uncovered interval is NaN in the price arrays, `NaN * x` is NaN, and a plain
    sum would turn one missing interval into a NaN bill for the whole window. Excluding matches
    `Flows.totals()` and `pricing.feedin_floor_topup`, so all three layers agree that an interval
    the simulation declined to assert anything about contributes exactly zero euros.
    """
    return float(np.nansum(values))


@dataclass(frozen=True)
class CostResult:
    """One run's marginal bill over the window, plus the top-up that was netted out of it.

        eur           the bill: positive means the household paid. Import cost MINUS export
                      revenue MINUS the feed-in floor top-up. Fixed costs excluded (see the module
                      comment) — this is the consumption-responsive part of the bill and nothing
                      else.
        topup_eur     the §6.5 statutory top-up credited over the window, always >= 0. Carried
                      because `waterfall`'s `feedin_floor_topup` line is `topup(C) - topup(A)` and
                      re-deriving it would mean calling `feedin_floor_topup` twice more with
                      arguments that must match the ones `compute_costs` used exactly. Also lets a
                      caller show the pre-top-up bill without a second pass.
        per_interval_eur   the bill BEFORE the top-up was subtracted, i.e. the purely vectorised
                      part. Kept because it is the quantity the waterfall's per-interval lines
                      decompose, so a test that suspects the top-up of hiding a sign error can
                      compare against it directly, and because §6.10's pseudocode names it.

    Deliberately NOT carried: `FeedinFloorResult`'s two §4.5 diagnostics. They describe the WINDOW
    (how many assessment periods it clips, whether it is shorter than one), not the run, so they are
    identical across A, B and C and belong to the caller that assembles §4.5's diagnostics block.
    Restating them per run would invite a reader to think run C could clip a different number of
    months than run A.
    """

    eur: float
    topup_eur: float
    per_interval_eur: float


def compute_costs(
    flows: Flows,
    p_import: np.ndarray,
    p_export_net: np.ndarray,
    compensation: np.ndarray,
    index: np.ndarray,
    cfg: PricingConfig,
) -> CostResult:
    """§6.10's `compute_costs` — the marginal EUR bill for one run over the window.

        per_interval = (flows.imp * p_import).sum() - (flows.exp * p_export_net).sum()
        return per_interval - feedin_floor_topup(...)

    Argument order follows §6.10's pseudocode. `cfg` is the `PricingConfig`, and note that
    `pricing.feedin_floor_topup` puts it FIRST while §6.5's pseudocode puts it last — this function
    keeps the spec's order at its own boundary and adapts at the call, so a reader comparing this
    body against §6.10 sees §6.10.

    **The export term is subtracted, and it is routinely negative** (§6.5 clamps nothing), in which
    case exporting raises the bill. Not a defect: §6.10 calls it the intended behaviour under the
    2027 regime and one of the more important things this tool can show. **The top-up is subtracted
    too**, because it is money received. It is zero in almost every window, and it is carried
    through rather than dropped so §6.10's waterfall closes exactly.

    **Operates on arrays, and must keep doing so.** §6.5's pre-2027 extension point puts an annual
    netting stage between the flow simulation and this function; that stage rewrites flow arrays, so
    a scalarised version of this function could not be fed by it.

    Gaps and uncovered prices are excluded, not imputed (module comment). `flows.imp` is NaN on gap
    intervals and the price arrays are NaN where `spot` was, so an interval missing either side
    contributes exactly zero euros — the same rule `feedin_floor_topup` applies to the period
    aggregate, which is why the two halves of the returned bill agree about which intervals exist.

    Raises whatever `feedin_floor_topup` raises — an unbuilt `feedin_floor_mode`.
    """
    imp_cost = _nansum(
        np.asarray(flows.imp, dtype=np.float64) * np.asarray(p_import, dtype=np.float64)
    )
    exp_revenue = _nansum(
        np.asarray(flows.exp, dtype=np.float64) * np.asarray(p_export_net, dtype=np.float64)
    )
    per_interval = imp_cost - exp_revenue

    floor = feedin_floor_topup(cfg, flows.exp, compensation, index)
    return CostResult(
        eur=per_interval - floor.topup_eur,
        topup_eur=floor.topup_eur,
        per_interval_eur=per_interval,
    )


@dataclass(frozen=True)
class WaterfallLine:
    """One §6.10 waterfall term: its label and its euro value.

        label   one of `WATERFALL_LINES`, spelled exactly as §6.10 spells it. The view translates
                off this key; it is not display text.
        eur     the term's contribution to the euro SAVING, signed. Positive means the battery made
                the household better off. Three lines are negative whenever they are nonzero —
                `added_grid_import_charging`, `degradation`, and `standby_consumption` whenever
                standby costs anything — and none is clamped.

                **`lost_feedin_compensation` is NOT reliably negative, despite its name.** It is
                `-(export avoided × compensation)`, so it flips positive in exactly the case this
                tool exists to surface: an hour whose compensation was negative, where NOT
                exporting is a gain rather than a loss. Both this module's primary fixture and
                fixture 14 produce it positive. Do not "correct" a positive value here.

    A dataclass rather than §6.10's literal `(label, value)` tuple: the tuple's two elements are a
    string and a float, so a transposition is a type error rather than a silent one, but every
    consumer would still have to remember which index is which. The order of the list `waterfall`
    returns is §6.10's, and it is load-bearing for the view's bar chart, so the sequence is the
    contract and the dataclass just makes each element self-describing.
    """

    label: str
    eur: float


def waterfall(
    a: Flows,
    b: Flows,
    c: Flows,
    p_import: np.ndarray,
    compensation: np.ndarray,
    tlk: float,
    cfg: PricingConfig,
    index: np.ndarray,
    p_export_net: np.ndarray,
) -> list[WaterfallLine]:
    """§6.10's eight-line decomposition of the euro saving, in §6.10's order.

    The invariant, which is fixture 4 in specs/16-validation-harness.md and is asserted directly in
    `tests/test_costs.py`:

        sum(waterfall) == cost(A) - cost(C) - degradation   +/- CLOSURE_TOL

    where `degradation` is the eighth line itself, so read literally the identity says the first
    seven lines reproduce `cost(A) - cost(C)` and the eighth is carried along on both sides. That is
    not a tautology on the eighth line: it is the assertion that the seven priced lines account for
    the whole difference between the two bills with nothing left over.

    **Why it is exact.** Per interval, `dcost = dimp * p_imp - dexp * p_exp_net`, and splitting each
    delta into its positive and negative parts is lossless (`x == max(x,0) - max(-x,0)`). The six
    per-interval lines are exactly those pieces, with the export side further split into its
    terugleverkosten and compensation components — which is why `avoided_terugleverkosten` and
    `lost_feedin_compensation` are two lines describing one physical quantity (export the battery
    did not make) and why `arbitrage_export_revenue` uses `compensation - tlk`, the net, for export
    the battery ADDED.

    **The A-to-B / B-to-C split.** §6.10's six per-interval lines are computed on `d = B - A`, the
    battery's effect WITHOUT standby, and standby enters as the single scalar `cost(B) - cost(C)`
    — §6.9's exact run difference, negative whenever standby costs money. Splitting it that way is
    what makes standby legible as one number instead of being smeared across the import and export
    lines, and it is exact because B and C differ in nothing else. See the body for why that line
    is taken on the PRE-TOP-UP bills; §6.10's `cost(B) - cost(C)` is ambiguous there and only one
    reading closes.

    **The top-up line is a DIFFERENCE**, `topup(C) - topup(A)`: what the battery changed about the
    floor, not what either scenario received. See the module comment for why it cannot be folded
    into `lost_feedin_compensation`.

    Arguments beyond §6.10's signature, and why:

        index, p_export_net   §6.10 writes `cost(B) - cost(C)` and `topup(C) - topup(A)` as calls
                      to functions that need the full price set and the time index. §6.10's
                      pseudocode signature omits them because the pseudocode treats `cost` and
                      `topup` as ambient; a real call has to pass them. They are appended AFTER
                      §6.10's arguments rather than interleaved, so the leading six still read as
                      the spec's signature.

    `tlk` is a SCALAR, not an array. §6.5 builds only `TlkMode.FLAT`, where terugleverkosten is one
    rate per fed-in kWh for the whole window, and `PriceCurves` documents it as recoverable as
    `compensation - p_export_net`. A scalar is the honest shape for what exists: it multiplies an
    export delta the same way an array of one repeated value would, and it makes the two export
    lines' arithmetic checkable by eye. Whether TIERED (follow-up H3) also resolves to one scalar
    per window is an open question, not a settled one: §6.5 says the tier is resolved from
    ANNUALISED export, which reads as one rate per window, but it does not say what a window
    spanning a tier boundary does. If that turns out to need an array the signature changes; this
    shape is chosen for what exists, not as a prediction. Passing an array would suggest a per-interval
    charge, which §6.5's note on what terugleverkosten may legally take says is not a shape that
    ships.

    Gap intervals contribute zero to every line, by the same `nansum` rule `compute_costs` uses:
    `b.imp - a.imp` is NaN wherever either run gapped.

    **PRECONDITION: the three runs mark the SAME gaps.** That holds for anything `run_all` produced
    — all three read one frame, and `simulate_baseline` propagates the same mask so `saved_kwh`
    compares like with like — but this is a public function taking three bare `Flows`, and the
    closure identity is silently wrong if they disagree: a difference gapped in one run but not
    another drops out of the A-vs-B group while remaining in the B-vs-C group, and the two sides of
    fixture 4 stop being the same partition of the window. Measured at €0.74 against a `CLOSURE_TOL`
    of 1e-6 on a three-interval misalignment. Asserted below rather than left to the caller's
    goodwill, because the failure produces a plausible number rather than a NaN.
    """
    # The precondition above. Cheap (two boolean array comparisons) against a failure that closes
    # to a plausible wrong number, and `run_all` satisfies it by construction, so nothing that
    # should work is refused.
    assert np.array_equal(a.gap, b.gap) and np.array_equal(a.gap, c.gap), (
        "waterfall requires runs A, B and C to mark the same gaps; misaligned gaps break the "
        "§6.10 closure identity silently"
    )

    a_imp = np.asarray(a.imp, dtype=np.float64)
    a_exp = np.asarray(a.exp, dtype=np.float64)
    d_imp = np.asarray(b.imp, dtype=np.float64) - a_imp
    d_exp = np.asarray(b.exp, dtype=np.float64) - a_exp

    p_imp = np.asarray(p_import, dtype=np.float64)
    comp = np.asarray(compensation, dtype=np.float64)

    # §6.10 verbatim. `maximum(-d, 0)` is the amount the battery REMOVED, `maximum(d, 0)` the
    # amount it ADDED; each product is NaN on a gap and dropped by `_nansum`.
    avoided_import = _nansum(np.maximum(-d_imp, 0.0) * p_imp)
    added_import = -_nansum(np.maximum(d_imp, 0.0) * p_imp)
    # Export the battery did not make, split into its two components: the terugleverkosten it
    # avoided paying (a gain) and the compensation it gave up (a loss). Their sum is
    # `-(maximum(-d_exp,0) * p_export_net)`, i.e. the export side of `dcost`, which is what makes
    # the pair exact rather than a presentational split.
    avoided_tlk = _nansum(np.maximum(-d_exp, 0.0) * tlk)
    lost_compensation = -_nansum(np.maximum(-d_exp, 0.0) * comp)
    # Export the battery ADDED, at the net rate — no split, because there is no story to tell about
    # a charge the household chose to incur in order to earn a compensation.
    arbitrage = _nansum(np.maximum(d_exp, 0.0) * (comp - tlk))

    # Three full bills, though only B and C's per-interval parts and A and C's top-ups are read.
    # Going through `compute_costs` rather than calling `feedin_floor_topup` directly is the point:
    # the closure identity is between THESE bills and this waterfall, so any future change to how a
    # bill is assembled reaches both sides at once. Re-deriving the top-up here with a second call
    # would let the two drift apart silently, and the arithmetic is a handful of array passes.
    cost_a = compute_costs(a, p_imp, p_export_net, comp, index, cfg)
    cost_b = compute_costs(b, p_imp, p_export_net, comp, index, cfg)
    cost_c = compute_costs(c, p_imp, p_export_net, comp, index, cfg)
    # §6.9's exact run difference: B and C differ only in `include_standby`, so this is the standby
    # term and nothing else. Negative whenever standby cost money.
    #
    # **On the PER-INTERVAL bills, not the full ones — this is a resolution of a genuine ambiguity
    # in §6.10, and it is what makes the identity exact.** §6.10 writes the line as
    # `cost(B) - cost(C)`, treating `cost` as the whole bill; but the whole bill has the top-up
    # netted out of it, and the seventh line ALREADY carries a top-up difference. Reading `cost`
    # as the full bill in both places puts `topup(C)` into the sum twice and `topup(B)` into it
    # once with the wrong sign, and the residual is exactly `topup(C) - topup(B)` — zero in almost
    # every window, which is why the ambiguity is invisible until the floor binds, and nonzero
    # precisely in fixture 14's case, where the identity is supposed to be doing real work.
    #
    # Taking the per-interval bills instead makes the three groups tile the difference exactly:
    # lines 1-5 are `per(A) - per(B)`, line 6 is `per(B) - per(C)`, line 7 is
    # `topup(C) - topup(A)`, and their sum is `cost(A) - cost(C)` with each top-up appearing once.
    # It is also the reading §6.10's own prose argues for: the top-up is a period-level scalar with
    # a single line of its own precisely SO THAT it is not distributed across the per-interval
    # terms, and `standby_consumption` is a per-interval term.
    standby = cost_b.per_interval_eur - cost_c.per_interval_eur
    # `topup(C) - topup(A)`: what the battery changed about the floor. Positive when the battery
    # earned a top-up the baseline did not, negative when it exported its way out of one the
    # baseline received — which is the ordinary direction, since a battery exports less.
    topup_line = cost_c.topup_eur - cost_a.topup_eur

    # §6.10: `-cfg.degradation_eur_per_kwh * C.withdrawn.sum()`, on the STORAGE side, matching
    # §6.11's `efc`. Zero on appendix A's default rate, which is 0.0 ("Disabled"); a zero line is
    # still REPORTED, because the waterfall's shape must not depend on the parameter values, and
    # because the closure identity has a degradation term on both sides whether or not it is zero.
    degradation = -cfg.degradation_eur_per_kwh * _nansum(
        np.asarray(c.withdrawn, dtype=np.float64)
    )

    values = (
        avoided_import,
        added_import,
        avoided_tlk,
        lost_compensation,
        arbitrage,
        standby,
        topup_line,
        degradation,
    )
    return [WaterfallLine(label, float(v)) for label, v in zip(WATERFALL_LINES, values)]
