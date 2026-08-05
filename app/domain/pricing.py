"""The §6.5 price curves — turning a contract into the arrays every run is costed against.

This module is the first half of the cost path. It converts a `PricingConfig` and the frame's
bare spot series into the two per-interval EUR/kWh arrays §6.10's `compute_costs` consumes, plus
the one quantity that is deliberately NOT an array: the statutory feed-in floor top-up, which is a
period-level scalar. Nothing here reads a flow, accumulates a cost or produces a waterfall —
that is §6.10, the next phase. Nothing here formats anything either; `app/results_view.py` owns
presentation, exactly as it does for `app/domain/metrics.py`.

The whole module is gated on `cfg.simulate_cost` at the CALL site (§6.5's opening note). It must
not be called with neutral parameters in energy-only mode: there is no neutral tax rate and no
neutral feed-in term, and a run costed at zero everywhere would produce a confident €0.00 saving
rather than no answer. Note what is not gated — the bare spot series itself, which §6.6–§6.7's
charge and discharge bands read directly and independently of anything here.

## The five things this module has to get right

**1. The feed-in floor is a PERIOD aggregate, not a per-interval clamp.** This is the hard part
and the reason `compensation` is returned separately from `p_export_net`. Writing
`c(t) = α·bare(t) + β` for the unclamped compensation, §6.5's two readings are:

    per-interval clamp (v1.1, PER_INTERVAL)   Σ export(t) · max(0, c(t))
    period floor (the law, MONTHLY)           max(0, Σ export(t) · c(t))   summed over periods

The first is always ≥ the second, because clamping discards every negative term individually
while the aggregate lets them offset positive ones. Moving to the legally correct rule therefore
REDUCES modelled feed-in revenue. That is fixture 13 in docs/specs/16-validation-harness.md, and
`tests/test_pricing.py` asserts the ordering directly rather than trusting the algebra.

**2. The top-up is not foldable into `p_export_net`.** §6.5 point 1 and §6.10's "why the top-up
needs its own line" both say so, for the same reason: a period-level scalar has no correct
per-interval allocation, only conventions, and folding it into the array would silently turn
§6.10's exact waterfall identity into an allocation convention. `PriceCurves` therefore carries
the unclamped `compensation` alongside `p_export_net`, because §6.10's `compute_costs` and
`waterfall` each need both — `compute_costs` re-derives the top-up from `compensation`, and the
waterfall's `lost_feedin_compensation` and `avoided_terugleverkosten` lines split the net back
into its two components.

**3. Nothing is clamped, and negative numbers are the point.** Both the per-interval compensation
and the net after terugleverkosten may legitimately be negative. §6.10: exporting during a
negative-price hour increases the bill, "and it is one of the more important things this tool can
show a user". A `max(0, ·)` anywhere in this module would hide exactly that.

**4. NaN in, NaN out — never a zero.** `SimulationFrame.spot` is NaN where no price covers the
interval (§4.4: "an uncovered interval is NaN, never 0", because a zero spot is a real price). The
three price functions are plain vectorised arithmetic, so NaN propagates through them untouched;
that is a deliberate decision, not an accident of numpy. It matches what §6.9 does with a gap
interval — `simulate.py` writes NaN into the flow arrays and consumers use `np.nansum` — so the
frame's uncovered intervals and the runs' gap intervals reach §6.10 as the same kind of absence.

`feedin_floor_topup` is the one place that has to collapse an array to a scalar, and it uses
NaN-EXCLUDING sums: an interval with no price contributes nothing to its period's aggregate rather
than poisoning it to NaN. Excluding is the same choice `Flows.totals()` makes, and the alternative
(a NaN top-up) would propagate a NaN into the euro figure for a window that is priced almost
everywhere. The cost of excluding is that a period which is mostly uncovered is assessed on the
part that is covered; the frame already reports `spot_missing_intervals` so a caller can say so,
and this module does not re-report it.

**5. UTC months, not Amsterdam months.** Period bucketing is done with numpy's
`astype("datetime64[M]")` on the frame's UTC-naive index, so a "calendar month" here begins at
00:00 UTC on the 1st — one or two hours after the Dutch calendar month does. That is a
simplification, and it is a knowing one: the whole pipeline is UTC-naive by design (see
`simframe.py`, and follow-up H1), and the misattributed sliver is the first one or two hours of
each month, which changes an answer only when the floor binds AND the binding period's sign flips
on those hours. Whoever builds the local-time axis for §6.4's dal mask should revisit this at the
same time, since it is the same conversion.

## What is deliberately NOT here

    FIXED and VARIABLE contracts   only DYNAMIC is built (follow-up H4). The other two branches
                      raise rather than falling back. FIXED's only blocker is `tariff_zone`,
                      which needs a UTC → Europe/Amsterdam conversion this codebase does not have
                      (follow-up H1) — its two rates ARE shipped fields (`rate_normaal`,
                      `rate_dal`), so it is one conversion away from working. VARIABLE needs that
                      same conversion AND a dated `rate_schedule`, which is not a field on
                      `PricingConfig` at all (H6), so it is the further of the two. A silent
                      fallback to the dynamic branch would be a confident wrong euro figure with
                      nothing to flag it.
    TlkMode.TIERED    needs annualised export and the `min_tlk_tiering_days` fallback (H3).
                      Raises for the same reason.
    §6.10 cost accounting, the waterfall, the top-up's A-vs-C difference   the next phase.
    §6.16 price bracket, §6.13's euro-basis resolution bias   deferred (H3).

Main items:
    PriceCurves           the three per-interval arrays, bundled.
    FeedinFloorResult     the period top-up and its two §4.5 diagnostics.
    bare_supply_price(cfg, spot)          EUR/kWh excl. energy tax and VAT. DYNAMIC only.
    import_price(cfg, bare)               EUR/kWh all-in, what you actually pay.
    feedin_compensation(cfg, bare)        α·bare + β, UNCLAMPED.
    export_price_net(cfg, bare)           compensation − terugleverkosten. FLAT only.
    price_curves(cfg, spot)               all three at once, as `PriceCurves`.
    feedin_floor_topup(cfg, export_kwh, compensation, index) -> FeedinFloorResult
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.simconfig import Contract, FeedinFloorMode, PricingConfig, TlkMode

# The numpy datetime64 unit calendar months are bucketed on. `astype("datetime64[M]")` truncates
# an instant to the first of its month, which is exactly the bucket key `feedin_floor_topup`
# needs and is why no explicit calendar arithmetic appears below. Named rather than inlined
# because it is the single place the assessment period's length is decided, and §6.5 leaves that
# period configurable in principle (`feedin_floor_period`, not modelled — see `PricingConfig`).
_MONTH_UNIT = "datetime64[M]"


def _not_built(what: str, followup: str, reason: str) -> NotImplementedError:
    """A refusal that names the unbuilt case, its follow-up entry and why it cannot be faked.

    Every branch of §6.5 this increment does not build funnels through here, so the four messages
    are one shape and each carries the pointer a reader needs to find the deferral record rather
    than re-deriving why the branch is missing.
    """
    return NotImplementedError(f"{what} is not implemented ({followup}): {reason}")


def bare_supply_price(cfg: PricingConfig, spot: np.ndarray) -> np.ndarray:
    """[vectorised] EUR/kWh excl. energy tax and VAT — §6.5's `bare_supply_price`.

    DYNAMIC only: `spot + cfg.supplier_markup`, the inkoopvergoeding added to the bare EPEX
    price. NaN intervals in `spot` (no price covers them, §4.4) stay NaN.

    FIXED and VARIABLE raise. Both select their rate with §6.5's
    `where(tariff_zone == DAL, ...)`, and `tariff_zone` is §6.4's wall-clock day/night mask —
    "dal from 23:00 to 07:00 plus weekends" is an Amsterdam-local rule, while this whole pipeline
    is UTC-naive. Applying the hour mask to the UTC index directly would shift the window one hour
    in winter and two in summer and misprice every interval, with no test and no figure that would
    look wrong (follow-up H1). Raising is the only honest option: a fallback to the dynamic branch
    would price a fixed contract off spot, and a fallback to a single rate would ignore dal
    entirely. Both would return a plausible number.
    """
    if cfg.contract == Contract.DYNAMIC:
        return np.asarray(spot, dtype=np.float64) + cfg.supplier_markup
    if cfg.contract == Contract.FIXED:
        raise _not_built(
            "The FIXED contract",
            "follow-up H1",
            "it prices off §6.4's `tariff_zone`, which needs a UTC -> Europe/Amsterdam "
            "conversion the pipeline does not have; only DYNAMIC is built",
        )
    if cfg.contract == Contract.VARIABLE:
        raise _not_built(
            "The VARIABLE contract",
            "follow-ups H1 and H6",
            "it needs both §6.4's `tariff_zone` and a dated `rate_schedule` that is not a field "
            "on PricingConfig; only DYNAMIC is built",
        )
    raise _not_built(
        f"Contract {cfg.contract!r}",
        "§6.5",
        "it is not one of DYNAMIC / FIXED / VARIABLE",
    )


def import_price(cfg: PricingConfig, bare: np.ndarray) -> np.ndarray:
    """[vectorised] EUR/kWh all-in, what the household actually pays — §6.5's `import_price`.

    `(bare + energy_tax_excl_vat) * (1 + vat_rate)`. Both charges apply to the import side only;
    §6.5 is explicit that private-consumer feed-in carries neither energy tax nor VAT, which is
    why `feedin_compensation` below is not their mirror image.

    Contract-independent: it takes whatever `bare_supply_price` produced, so it needs no dispatch
    and works unchanged when FIXED and VARIABLE land.
    """
    return (np.asarray(bare, dtype=np.float64) + cfg.energy_tax_excl_vat) * (1.0 + cfg.vat_rate)


def feedin_compensation(cfg: PricingConfig, bare: np.ndarray) -> np.ndarray:
    """[vectorised] EUR/kWh of gross feed-in compensation, `α·bare + β` — UNCLAMPED.

    §6.5: "per interval, NOT clamped here". The statutory ≥0 floor is assessed over an assessment
    period by `feedin_floor_topup`, not interval by interval, so clamping here would apply the
    v1.1 rule to every mode and make `FeedinFloorMode` inert. Negative values are the expected
    output during negative-price hours and are what the MONTHLY aggregate offsets against
    positive ones.

    Appendix A's α = 0.50 / β = 0.0000 is §6.5's "Legal minimum" preset — the statutory floor
    valid to 1 Jan 2030 — so on the shipped defaults compensation is half the bare supply price
    and goes negative exactly when the bare price does.
    """
    return cfg.feedin_alpha * np.asarray(bare, dtype=np.float64) + cfg.feedin_beta


def export_price_net(cfg: PricingConfig, bare: np.ndarray) -> np.ndarray:
    """[vectorised] EUR/kWh net received per exported kWh under the 2027+ regime — §6.5.

    `compensation − terugleverkosten`, with `compensation` the unclamped `feedin_compensation`
    above. FLAT terugleverkosten only: a rate per fed-in kWh, `cfg.tlk_eur_per_kwh`.

    Not clamped, in either direction. The net is negative whenever the compensation falls below
    the feed-in charge — which, on the shipped α = 0.50 and a 4 ct/kWh charge, happens at any bare
    price below 8 ct/kWh, i.e. far more often than only during negative-price hours. §6.10: the
    export term is SUBTRACTED from the bill, so a negative net means exporting costs money, and
    that is "one of the more important things this tool can show a user".

    TIERED raises. A staffel resolves its tier from ANNUALISED export, so the rate depends on a
    window-level total this function is not given and cannot see, and §6.5 requires a visible
    fallback notice for windows under `min_tlk_tiering_days` — a UI affordance that does not
    exist. Returning the FLAT rate silently would make a step function look linear (§6.5: reducing
    export by 200 kWh can be worth €0 or €40 depending on the tier boundary). Follow-up H3.
    """
    if cfg.tlk_mode == TlkMode.FLAT:
        tlk = cfg.tlk_eur_per_kwh
    elif cfg.tlk_mode == TlkMode.TIERED:
        raise _not_built(
            "Tiered terugleverkosten",
            "follow-up H3",
            "the tier resolves from ANNUALISED export and needs `min_tlk_tiering_days` with a "
            "visible FLAT fallback notice; only FLAT is built",
        )
    else:
        raise _not_built(
            f"tlk_mode {cfg.tlk_mode!r}",
            "§6.5",
            "it is not one of FLAT / TIERED",
        )
    return feedin_compensation(cfg, bare) - tlk


@dataclass(frozen=True)
class PriceCurves:
    """The three per-interval EUR/kWh arrays §6.10 costs a run against.

    Bundled rather than returned as a bare tuple for one reason: `compensation` and
    `p_export_net` are easy to transpose at a call site and impossible to tell apart by
    inspection — both are EUR/kWh, both are frequently negative, and they differ by a constant
    (the flat terugleverkosten rate). §6.10's `compute_costs(flows, p_import, p_export_net,
    compensation, index, cfg)` needs BOTH, in that order, and a swapped pair would produce a
    wrong bill that closes against a wrong waterfall. Named fields make that transposition a
    typo rather than a silent sign error.

        bare          EUR/kWh excl. energy tax and VAT. Carried because §6.10's waterfall does
                      not need it but a caller re-deriving a compensation under a different
                      (α, β) preset does, and because it is the one array a reader can check
                      against the raw spot series by eye.
        p_import      all-in import price (`import_price`).
        compensation  gross feed-in compensation, UNCLAMPED (`feedin_compensation`). Kept
                      separate from `p_export_net` because the period floor is assessed on it and
                      because the waterfall's `lost_feedin_compensation` line reads it directly.
        p_export_net  compensation − terugleverkosten (`export_price_net`).

    All four are NaN wherever `spot` was, and all four are the same length as the frame's index.
    The flat terugleverkosten rate is recoverable as `compensation − p_export_net`, so §6.10's
    `waterfall(..., tlk)` argument needs no extra field here.
    """

    bare: np.ndarray
    p_import: np.ndarray
    compensation: np.ndarray
    p_export_net: np.ndarray


def price_curves(cfg: PricingConfig, spot: np.ndarray) -> PriceCurves:
    """The three §6.5 price arrays for one window, from the frame's bare spot series.

    The ordinary entry point: one dispatch on contract type, one on tlk mode, four arrays out.
    The individual functions stay public because the tests pin them against hand-computed values
    and because §6.10's waterfall re-derives a compensation under a different preset.

    Raises whatever `bare_supply_price` or `export_price_net` raises — a non-DYNAMIC contract or
    a TIERED tlk mode fails here rather than at the first euro figure.
    """
    bare = bare_supply_price(cfg, spot)
    return PriceCurves(
        bare=bare,
        p_import=import_price(cfg, bare),
        compensation=feedin_compensation(cfg, bare),
        p_export_net=export_price_net(cfg, bare),
    )


@dataclass(frozen=True)
class FeedinFloorResult:
    """The §6.5 feed-in floor top-up over one window, with the two §4.5 diagnostics it needs.

        topup_eur     EUR to be CREDITED over the window — §6.10 subtracts it from the bill,
                      because it is money received. Zero in all but exceptional periods:
                      the floor binds only in a period whose export earned a net negative amount
                      overall. Always ≥ 0.
        partial_periods   `diagnostics.feedin_floor_partial_periods` (§4.5, §7.4): how many
                      assessment periods the window covers only partly. An arbitrary window
                      leaves one at each end, so 2 is the ordinary value and 0 means the window
                      happens to align with month boundaries. §7.4 is explicit that a partial
                      period is assessed AS IT STANDS — not dropped, not extrapolated to a full
                      month — so this is a fact about the answer, not a defect in it.
        shorter_than_period   `diagnostics.feedin_floor_shorter_than_period` (§4.5, §7.4): the
                      window is shorter than one assessment period, so the floor was assessed
                      over the whole window. That is a WEAKER constraint than the law imposes,
                      and the flag is how the result carries the fact. When it is True,
                      `partial_periods` is 1: the single bucket is itself partial.

    Under `PER_INTERVAL` the two diagnostics are meaningless — no period is assessed at all — and
    are reported as 0 / False rather than as the MONTHLY values they would have had. §4.5 reports
    them as `null` when cost simulation is off entirely; that null is the caller's to write, since
    this function is not called at all in energy-only mode.
    """

    topup_eur: float
    partial_periods: int
    shorter_than_period: bool


def feedin_floor_topup(
    cfg: PricingConfig,
    export_kwh: np.ndarray,
    compensation: np.ndarray,
    index: np.ndarray,
) -> FeedinFloorResult:
    """The statutory floor on feed-in compensation, as EUR to credit over the window — §6.5.

    `index` is `SimulationFrame.index`: UTC-naive `datetime64[s]`, one entry per interval,
    interval START.

    **PRECONDITION: `index` is a uniform grid over a CONTIGUOUS window** — which is what
    `SimulationFrame` guarantees (it is built with `arange`), and the partial-period count below
    relies on it: only the first and last month can be partial, so an interior month is assumed
    whole. Passed a non-contiguous index — January whole, ten days of February, March whole — the
    count under-reports, returning 0 where February is plainly partial. Not validated here (the
    frame's contract makes it unreachable, and a length-N check on every call is not free), but
    stated because this is a public function taking a bare array rather than a frame.

    `export_kwh` and `compensation` are the same length; `export_kwh` is a run's
    `Flows.exp` and is NaN on gap intervals, `compensation` is NaN where no price covered the
    interval. Both kinds of absence are excluded from the sums (see the module comment), so an
    interval missing either one contributes nothing to its period's aggregate.

    Two modes, and they are not a rounding difference (§6.5):

      * PER_INTERVAL — `Σ export(t)·max(0, −c(t))`, the v1.1 behaviour. Each negative interval is
        topped up on its own, so the top-up is the export-weighted negative part of `c`. Retained
        for reproducibility and because a supplier may genuinely offer a non-negative compensation
        in every interval, which is stricter than the law requires.
      * MONTHLY — `Σ over periods of max(0, −Σ export(t)·c(t))`, the law. Negative intervals
        offset positive ones within the period, so the top-up is nonzero only in a period whose
        export earned a net negative amount overall.

    The PER_INTERVAL top-up is always ≥ the MONTHLY one, with equality iff no interval has a
    negative unclamped compensation carrying nonzero export — fixture 13, asserted in
    `tests/test_pricing.py` on revenue rather than on the top-up, since revenue is what §6.10
    consumes.

    Periods are UTC calendar months (`astype("datetime64[M]")`), not Amsterdam ones — see the
    module comment for why that simplification is knowingly taken and what it costs. Partial
    periods at the window edges are assessed as they stand and counted; a window shorter than one
    month is assessed whole and sets `shorter_than_period` (§7.4).

    Returns a `FeedinFloorResult` rather than a bare float so the two §4.5 diagnostics travel with
    the number they describe. §6.5 point 1 and §6.10 both forbid folding this into
    `p_export_net`: it is a period-level scalar with no correct per-interval allocation, and
    folding it in would turn §6.10's exact waterfall identity into an allocation convention.
    """
    export = np.asarray(export_kwh, dtype=np.float64)
    comp = np.asarray(compensation, dtype=np.float64)

    # Absence on either side excludes the interval. Written as one mask rather than as `nansum`
    # over the product because the product's NaNs are the union anyway, and because the mask is
    # also what makes the empty-window case below observable.
    usable = ~(np.isnan(export) | np.isnan(comp))

    if cfg.feedin_floor_mode == FeedinFloorMode.PER_INTERVAL:
        # `maximum(0, -c)` is the shortfall per kWh; on the excluded intervals it is NaN, so the
        # mask does the work `nansum` would otherwise do.
        shortfall = np.where(usable, export * np.maximum(0.0, -comp), 0.0)
        return FeedinFloorResult(
            topup_eur=float(shortfall.sum()),
            # No period is assessed under this mode, so neither diagnostic has a meaning. See
            # `FeedinFloorResult`.
            partial_periods=0,
            shorter_than_period=False,
        )

    if cfg.feedin_floor_mode != FeedinFloorMode.MONTHLY:
        raise _not_built(
            f"feedin_floor_mode {cfg.feedin_floor_mode!r}",
            "§6.5",
            "it is not one of MONTHLY / PER_INTERVAL",
        )

    idx = np.asarray(index)
    if idx.size == 0:
        # An empty window assesses nothing. Not `shorter_than_period=True`: there is no window to
        # be shorter than a month, and flagging a weakened constraint on an answer that has no
        # intervals would put a caveat on nothing.
        return FeedinFloorResult(topup_eur=0.0, partial_periods=0, shorter_than_period=False)

    months = idx.astype(_MONTH_UNIT)
    # `np.unique` sorts, so `bucket` indexes months in chronological order and `first`/`last`
    # below are the window's edge periods.
    keys, bucket = np.unique(months, return_inverse=True)
    earned = np.bincount(
        bucket, weights=np.where(usable, export * comp, 0.0), minlength=keys.size
    )
    topup = float(np.maximum(0.0, -earned).sum())

    # A period is partial when the window does not contain all of it. The window's interior
    # months are whole by construction (the index is a uniform grid over a contiguous window), so
    # only the first and last bucket can be partial, and each is partial exactly when the window
    # starts after that month began / ends before the next one does. `index` holds interval
    # STARTS, so the window's end is the last start plus one interval — inferred from the grid
    # spacing rather than from a window object, which this function is not given.
    starts_mid_month = idx[0] > idx[0].astype(_MONTH_UNIT).astype(idx.dtype)
    if idx.size >= 2:
        step = idx[1] - idx[0]
        window_end = idx[-1] + step
    else:
        # One interval: its own spacing is unknown here, so treat the window as ending at the
        # interval start. That can only understate the end, i.e. count the final month as partial
        # — which a single-interval window certainly is.
        window_end = idx[-1]
    # An explicit month timedelta rather than a bare `+ 1`: numpy deprecates the implicit
    # generic unit, and the unit is the assessment period's, so naming it keeps this line honest.
    next_month_start = (keys[-1] + np.timedelta64(1, "M")).astype(idx.dtype)
    ends_mid_month = window_end < next_month_start

    if keys.size == 1:
        partial = 1 if (starts_mid_month or ends_mid_month) else 0
    else:
        partial = int(starts_mid_month) + int(ends_mid_month)

    # §7.4's flag is about the window's DURATION, not about how many buckets it lands in: it
    # records that the floor was assessed over less than one assessment period, which is a WEAKER
    # constraint than the law imposes. Deriving it from `keys.size == 1` gets that backwards at
    # the boundary — a 3-day window over 30 Jan → 2 Feb lands in two buckets and is assessed as
    # two sub-month fragments, which is weaker still than the same 3 days inside one month, yet
    # the bucket-count reading flags the latter and not the former. Any run started mid-month and
    # shorter than a month hits it.
    #
    # Measured against the SHORTEST month the window touches, rather than a fixed 28/30/31 days:
    # "shorter than one month" has no day count that is right in every month, and a window shorter
    # than the shortest period it is assessed over is unambiguously shorter than one period. A
    # window between the shortest and longest touched month is not flagged, which is the
    # conservative direction — the flag claims a weakened constraint, so it should not fire on a
    # window that may well cover a whole period.
    span = window_end - idx[0]
    month_starts = np.concatenate([keys, keys[-1:] + np.timedelta64(1, "M")]).astype(idx.dtype)
    shortest_month = np.diff(month_starts).min()
    shorter = bool(span < shortest_month)

    return FeedinFloorResult(
        topup_eur=topup, partial_periods=partial, shorter_than_period=shorter
    )
