"""§6.12's perfect-foresight benchmark — run D, the ENERGY objective.

The headline "1,412 kWh saved" is uninterpretable on its own. §6.12's whole purpose is to make it
"1,412 kWh of a possible 1,988", which requires knowing what the best possible dispatch over this
exact window would have avoided. That best possible dispatch is what this module computes, by
dynamic programming over a discretised state of charge.

**This module implements the ENERGY benchmark only** (`transition_cost` = kWh of grid import in the
interval). §6.12's cost benchmark — run E, minimising euros — is a sibling that shares this DP's
state space, action set and feasibility rules and differs only in the objective. It is not built
here because `cfg.simulate_cost` is false in this increment and there is no §6.10 price model for
it to minimise. §6.12 is explicit that the two must be SEPARATE runs, not one retargeted run: a
cost-optimal dispatch imports more during cheap hours and therefore avoids LESS import, so a single
DP following `simulate_cost` would hand the energy section a ceiling that moved when the user asked
for euros. That is the invariant the split protects, and it is why nothing here reads a price.

## The optimisation, and the four things that make it correct rather than merely plausible

**1. The terminal constraint is load-bearing, not a refinement.** §6.12: "Without it the DP simply
liquidates the battery and inflates the bound." A DP free to end the window empty gets a free
`soc_start − soc_min` kWh of discharge it never paid to store, and the resulting bound is not an
upper bound on anything a real battery could have done over the same window. `V` is therefore
seeded `+INF` below the starting SoC, so no trajectory that ends below it is ever selected.

**2. `V` is INTERPOLATED, never snapped to the nearest SoC level.** §6.12: interpolation "avoids a
systematic pessimism bias of several percent". Snapping rounds every transition's landing point to
a grid node, and the rounding is not unbiased in its effect on the value — the DP can only realise
value at the discretised points, so a fine action grid buys nothing and the bound comes out below
the truth. `np.interp` is linear in `V` between the bracketing levels, which is exact whenever `V`
is locally linear in SoC and close otherwise.

**3. The DP obeys the SAME physical limits as run C, and NOT the user's price bands.** Rated charge
and discharge power, the SoC window, the import and export connection caps, the PV-first charge
ordering, the DC-coupled PV efficiency, and the standby draw added to the load — all identical to
§6.8/§6.9, so the comparison is like-for-like and the capture ratio measures decision quality
rather than a change of physics. The bands are exactly what the DP is allowed to ignore: that is
what "perfect foresight" means here.

**4. Gaps are skipped exactly as §6.9 skips them.** An interval whose `load` or `pv` is NaN moves no
energy, carries the SoC forward, and contributes NaN to the import array. If the DP evaluated gap
intervals that run C skipped, the two runs' import totals would be sums over different interval
sets and fixture 6's bound would be comparing unlike things.

## Why the transition is re-derived here instead of calling `battery_step`

`battery_step` is scalar and takes REQUESTS from the two policies; the DP takes a signed AC power
directly and must evaluate `n_soc × n_actions` of them at once. Calling it in a Python loop would
be 8,760 × 101 × 41 ≈ 36M scalar calls — minutes, not the seconds §6.12 budgets. So `_transition`
is §6.8's steps 2–7 written for arrays, in the same order and with the same clamps. That
duplication is a real risk (two implementations of one step function can drift), and it is managed
by a test rather than by hope: `tests/test_benchmark.py` drives `_transition` and `battery_step`
over the same states and actions and asserts they agree.

Two structural differences from `battery_step`, both deliberate:

  * **No netting step (§6.8 step 1).** A DP action is a single signed number, so simultaneous
    charge and discharge is not representable — there is nothing to net.
  * **Export permission is a FEASIBILITY rule, not a request-shaping one.** §6.7 lets
    `allow_grid_export` suppress the discharge-to-grid REQUEST; here the DP would simply choose a
    different action, so the constraint is applied where it belongs: an action whose dispatch would
    push energy onto the grid from the BATTERY is infeasible when export is disallowed. PV export
    is unaffected — it is not the battery's doing and run A exports it too.

## The two export baselines (§6.12), and when the second is skipped

    inheriting     the DP plays by the user's `allow_grid_export`. THE PRIMARY figure: the capture
                   ratio then measures decision quality alone, with the export setting held fixed
                   across numerator and denominator.
    unconstrained  the DP may always export. The bound is the true physical maximum, and the
                   capture ratio also absorbs the cost of the user's export setting.

When `allow_grid_export` is ON the two coincide **by construction** — same action set, same
feasibility, same objective — so only the inheriting DP runs and the unconstrained fields are None.
§6.12 is careful about the word: the second pass is skipped because it is provably identical, not
because it is expected to be close. When export is OFF (the default) both run, and
`unconstrained ≥ inheriting` holds because the unconstrained DP optimises over a superset of
actions.

## What is deliberately NOT here

    run E / the cost DP        needs §6.10's price model; `simulate_cost` is false. See above.
    any euro figure            nothing here reads a price, by design.
    a cache                    the DP is recomputed per request. See `perfect_foresight`'s note on
                               the measured cost before adding one.

Main items:
    DP_INF                 the +INF sentinel the backward pass uses for infeasible transitions.
    _DpLimits              the per-run constants hoisted out of the config once (cf. `_StepLimits`).
    _transition()          §6.8 steps 2–7, vectorised over (n_soc × n_actions).
    DispatchResult         one DP run's outcome: the import array, the SoC trace, the gap mask.
    perfect_foresight()    §6.12's DP — backward pass then `_roll_forward`.
    EnergyBenchmark        the §6.12 energy block: both bounds, both capture ratios.
    energy_benchmark()     runs the one or two DPs and assembles the block.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.reconcile import DIV_GUARD_EPS
from app.domain.simconfig import Coupling, SimulationConfig
from app.domain.simframe import SimulationFrame
from app.domain.simulate import SOC_COMPARE_EPS_KWH, Flows

# The +INF sentinel §6.12's pseudocode writes as `+INF`. `np.inf` rather than a large finite number:
# a finite sentinel can be added to a finite cost and stay below another sentinel, which silently
# turns "infeasible" into "expensive but allowed"; `inf + x` is `inf` and compares correctly.
DP_INF = np.inf


@dataclass(frozen=True)
class _DpLimits:
    """The per-run constants the DP reads, hoisted out of the config ONCE (cf. `_StepLimits`).

    Same reasoning as Phase 3's `_StepLimits`, and the same reason it is the CALLER's job: Phase 2
    makes every derived quantity a property so nothing can go stale under a Phase-6 form binding,
    and the safe optimisation is for the caller to hoist into locals before the loop, because the
    loop body does not mutate the config.

    Everything is already multiplied through by `dt` where §6.8 multiplies, so the DP compares
    energies with energies. `soc_levels` and `actions` are the two discretisation grids §6.12
    defines; they are built once here because neither depends on the interval.
    """

    eta_c: float
    eta_c_pv: float  # eta_c_dc on a DC-coupled system — §6.8 step 3, PV path only
    eta_d: float
    soc_min_kwh: float
    soc_max_kwh: float
    chg_cap_kwh: float
    dis_cap_kwh: float
    imp_cap_kwh: float
    exp_cap_kwh: float
    standby_kwh: float  # per interval, added to the load exactly as §6.9's caller does
    soc_levels: np.ndarray  # (n_soc,)
    actions: np.ndarray  # (n_actions,) signed AC kWh; negative charges, positive discharges
    allow_grid_export: bool
    # The SoC the run begins from, clamped into the window exactly as §6.9 clamps it before its
    # first interval. It lives here — rather than being recomputed by the caller — because the SoC
    # grid is built around it (see `of`) and the terminal constraint is stated against it; two
    # independent derivations of one number is how the grid and the constraint would drift apart.
    soc_start_kwh: float

    @classmethod
    def of(
        cls, cfg: SimulationConfig, dt_hours: float, *, allow_grid_export: bool
    ) -> _DpLimits:
        """Read every derived value off `cfg` once and build the two §6.12 grids.

        `allow_grid_export` is passed in rather than read off `cfg` because §6.12 runs the DP under
        BOTH readings — the inheriting one takes `cfg.allow_grid_export`, the unconstrained one
        forces True — and a function that read the config directly could only produce one of them.

        The action grid is §6.12's `linspace(-max_charge_kw, max_discharge_kw, n) * dt`, verbatim:
        negative is charge, positive is discharge, and the endpoints are the two rated powers. Note
        this does NOT guarantee a zero action for an even `n_actions`; with appendix A's 41 levels
        and equal 5/5 kW powers, index 20 is exactly 0. A grid without an exact zero is not a
        defect — an action arbitrarily close to zero is always available and the SoC window clamps
        the rest — but it is worth knowing that "do nothing" is only exactly representable when the
        grid happens to straddle 0 evenly.

        **The SoC grid is `linspace(soc_min, soc_max, n_soc)` with its nearest level MOVED onto the
        starting SoC.** §6.12 gives the plain linspace, but the terminal constraint it states in the
        very next line is `V[soc_levels < initial_soc − EPS] = +INF` — and on a plain linspace the
        starting SoC almost never IS a level. When it falls between two, every level below it is
        terminal-infeasible and the level above it is strictly higher than the SoC the run actually
        starts from, so the DP is forced to charge before it may do anything else and its bound
        comes out WORSE than simply doing nothing. Measured on a 96-interval no-PV P1/D1 fixture
        with `soc_start = 2.5` between levels 2.48 and 2.525: the DP returned 123.05 kWh of import
        against 122.80 for standing still, i.e. it was not an upper bound at all and fixture 6
        failed. Snapping one level onto `initial_soc_kwh` makes "hold the starting SoC and do
        nothing" an exactly representable trajectory, which is the trajectory the bound must never
        be worse than.

        The level count is unchanged (a level is MOVED, not inserted), the grid stays sorted — the
        moved level is by construction the nearest one, so it cannot cross a neighbour — and
        `np.interp`'s monotonicity precondition therefore still holds. The starting SoC is clamped
        into the window first, matching §6.9's clamp, so the move can never push a level outside
        `[soc_min, soc_max]`.

        **The snap searches the INTERIOR levels only, and never moves an endpoint.** `perfect_
        foresight` relies on `np.interp`'s out-of-grid clamping being harmless because "the ends of
        `soc_levels` ARE the window's ends" — a statement the snap can falsify. At
        `dp_soc_levels = 2` (which `validate()` permits) with `initial_soc = 5.0` over `[1, 10]`
        the nearest level IS `soc_min`, so moving it deletes `soc_min` from the grid entirely and
        every `soc_next` below 5.0 would then be clamped UP by the interpolation — the value
        function would be read at a state the trajectory is not in. The same happens at any grid
        size when the starting SoC sits nearer an endpoint than to the first interior level.
        Restricting the search to `soc_levels[1:-1]` keeps both endpoints pinned; when there is no
        interior level (`n_soc == 2`) or the starting SoC already IS an endpoint, no move is
        needed and none is made. Nothing in production sets a grid this coarse — appendix A's
        default is 101 — but it is reachable by configuration and a silently wrong value function
        is not an acceptable failure mode for it.
        """
        soc_levels = np.linspace(
            cfg.soc_min_kwh, cfg.soc_max_kwh, int(cfg.dp_soc_levels), dtype=np.float64
        )
        soc_start = min(max(cfg.initial_soc_kwh, cfg.soc_min_kwh), cfg.soc_max_kwh)
        # An endpoint that already IS the starting SoC needs no snap at all — and must not trigger
        # one, or an interior level would be moved onto a value the grid already contains, creating
        # a duplicate node `np.interp` would read as a zero-width interval.
        on_endpoint = len(soc_levels) > 0 and (
            abs(soc_levels[0] - soc_start) <= SOC_COMPARE_EPS_KWH
            or abs(soc_levels[-1] - soc_start) <= SOC_COMPARE_EPS_KWH
        )
        if len(soc_levels) > 2 and not on_endpoint:
            # +1 to translate the interior-slice index back to the full array's index.
            nearest = int(np.abs(soc_levels[1:-1] - soc_start).argmin()) + 1
            soc_levels[nearest] = soc_start

        return cls(
            eta_c=cfg.eta_c,
            eta_c_pv=cfg.eta_c_dc if cfg.coupling == Coupling.DC_HYBRID else cfg.eta_c,
            eta_d=cfg.eta_d,
            soc_min_kwh=cfg.soc_min_kwh,
            soc_max_kwh=cfg.soc_max_kwh,
            chg_cap_kwh=cfg.max_charge_kw * dt_hours,
            dis_cap_kwh=cfg.max_discharge_kw * dt_hours,
            imp_cap_kwh=cfg.max_import_kw * dt_hours,
            exp_cap_kwh=cfg.max_export_kw * dt_hours,
            standby_kwh=cfg.standby_kw * dt_hours,
            soc_levels=soc_levels,
            actions=np.linspace(
                -cfg.max_charge_kw * dt_hours,
                cfg.max_discharge_kw * dt_hours,
                int(cfg.dp_action_levels),
                dtype=np.float64,
            ),
            allow_grid_export=allow_grid_export,
            soc_start_kwh=soc_start,
        )


def _interval_actions(load_kwh: float, pv_kwh: float, lim: _DpLimits) -> np.ndarray:
    """The action grid for ONE interval: §6.12's `linspace`, plus the two exact dispatch points.

    **Why the plain linspace is not enough, measured rather than assumed.** With appendix A's 41
    levels and a 5 kW battery on hourly data the action step is 0.25 kWh, and the §6.6/§6.7 policies
    dispatch on two CONTINUOUS quantities the grid almost never contains: the PV surplus
    `max(0, pv − load)` that P1/P3 charge with, and the household deficit `max(0, load − pv)` that
    D1/D3 discharge into. A policy can therefore make a move the DP cannot represent, and on a
    96-interval PV fixture the DP came out ~0.3 kWh (≈3 percent) BELOW the P1/D1 policy it is
    supposed to bound — refining the action grid to 401 levels closed the gap, confirming
    discretisation rather than a logic error. A bound that a policy can beat by three percent is not
    a bound, and fixture 6 said so.

    Adding the two exact points makes every dispatch the §6.6/§6.7 policies can choose exactly
    representable, so the DP optimises over a genuine SUPERSET of the policy's action set at every
    interval — which is the property the bound rests on. It costs two extra columns out of 41.

    Both are clipped into `[-chg_cap, +dis_cap]`: a surplus larger than rated charge power is not an
    action the battery can take, and `_transition` would clamp it to the same place anyway. Signs
    follow §6.12's convention — negative charges, positive discharges.

    **What this does NOT make exact, stated so it is not mistaken for a complete fix.** The action
    that returns the battery to EXACTLY its starting SoC — the one the terminal constraint rewards
    on the last interval it can be taken — depends on the current SoC and so cannot live in a row
    shared by every state without breaking the (n_soc × n_actions) broadcast the DP's speed rests
    on. A two-interval lossless-shift fixture at 90 percent RTE shows it: the exact discharge is
    2.7 kWh AC, which lands on the terminal SoC precisely, but the nearest representable actions are
    2.75 (which overshoots the floor and is infeasible) and 2.5, so the DP takes 2.5 and reports
    0.5 kWh of import where 0.3 was attainable. The residual is bounded by the action step and
    shrinks with `dp_action_levels` — at 401 levels the same fixture returns 0.3 — and it is the
    same discretisation floor `tests/test_benchmark._DP_SLACK_KWH` measures at 0.025 kWh over 216
    configurations. It makes the bound slightly CONSERVATIVE, which is the safe direction for an
    upper bound: it can understate the ceiling, never overstate it.
    """
    pv_surplus = min(max(0.0, pv_kwh - load_kwh), lim.chg_cap_kwh)
    deficit = min(max(0.0, load_kwh - pv_kwh), lim.dis_cap_kwh)
    return np.concatenate((lim.actions, np.array([-pv_surplus, deficit], dtype=np.float64)))


class _Transition:
    """What one interval's (state × action) grid evaluates to. All arrays are (n_soc, n_actions).

        soc_next    the SoC each (state, action) pair lands on, already clamped by every §6.8 limit.
        imp         kWh imported — §6.12's `transition_cost` for the ENERGY objective.
        feasible    False where the action cannot be taken at all (see `_transition`).

    A small class rather than a tuple so the three arrays are named at every use; the DP evaluates
    it once per interval and discards it, so the allocation is not on any hot path worth defending.
    """

    __slots__ = ("soc_next", "imp", "feasible")

    def __init__(self, soc_next: np.ndarray, imp: np.ndarray, feasible: np.ndarray) -> None:
        self.soc_next = soc_next
        self.imp = imp
        self.feasible = feasible


def _transition(
    soc: np.ndarray, actions: np.ndarray, load_kwh: float, pv_kwh: float, lim: _DpLimits
) -> _Transition:
    """§6.8 steps 2–7 for every (SoC, action) pair at once — the DP's `transition_cost`.

    `soc` is (n_soc, 1) and `actions` is (1, n_actions); everything below broadcasts to
    (n_soc, n_actions). `load_kwh` already includes the standby draw (the caller adds it, exactly
    as §6.9's caller does, so nothing in the step arithmetic knows standby exists).

    The steps, in §6.8's order and with §6.8's meanings:

      2. **Charge clamped to rated power, PV first.** The charge request is `max(0, −action)`,
         capped at `chg_cap`. Within it PV takes priority — `chg_pv = min(pv surplus, chg_ac)` —
         because PV is free and, DC-coupled, more efficient. This is the same ordering §6.8 step 2
         applies and it matters here for the same reason: it is what makes the efficiency
         assignment in step 3 meaningful.
      3. **Charge clamped to SoC headroom, in STORED units.** The two paths have different
         efficiencies, so the clamp has to happen after conversion and be scaled back to the AC
         figures. Doing it in AC units would overfill a DC-coupled battery by the bonus.
      4. **Discharge clamped to rated power AND to available energy** — `(soc − soc_min) × eta_d`,
         what is left above the floor converted to what the inverter can deliver. Floored at 0 for
         the same reason `battery_step` floors it.
      5. **Grid flows as the residual of the household balance.** `imp` and `exp` are the two signs
         of one net figure, so at most one is positive.
      6. **Connection limits.** Import: shed grid charging first (the discretionary part of the
         draw). Export: shed battery-to-grid discharge first (a choice), then curtail PV (not).
         Unlike §6.8 this does not FLAG a household load that alone exceeds the import cap — the DP
         cannot act on that flag and the flag's consumer is the warnings list, which belongs to the
         policy run; the arithmetic is identical either way.
      7. **Integrate.**

    **Feasibility** (§6.12's `tot[~feasible(soc_next, cfg)] = +INF`) is TWO conditions:

      * `soc_next` inside the operating window. After the step-3 and step-4 clamps this holds by
        construction, so it is asserted rather than relied on to filter — a clamp bug would
        otherwise be absorbed into an infeasibility and never seen.
      * **battery export permission.** When `allow_grid_export` is False, any action whose dispatch
        results in the BATTERY pushing energy onto the grid is infeasible. The test is on what the
        battery contributed to the export, not on `exp > 0`: PV export is not the battery's doing
        and run A exports it too, so forbidding it would make the DP's baseline differ from run
        A's and the bound would no longer bound the same quantity. The condition is therefore
        `dis_ac` exceeding what the household could absorb, i.e. the discharge that necessarily
        left the premises.
    """
    # ---- 2. clamp charge to rated power, PV first ------------------------------------------
    chg_req = np.maximum(0.0, -actions)
    chg_ac = np.minimum(chg_req, lim.chg_cap_kwh)
    # PV surplus is what §6.6's P1/P3 would have offered: generation the house did not consume.
    # A scalar, broadcast over the whole grid.
    pv_surplus = max(0.0, pv_kwh - load_kwh)
    chg_pv = np.minimum(pv_surplus, chg_ac)
    chg_grid = chg_ac - chg_pv

    # ---- 3. clamp charge to SoC headroom, in STORED units -----------------------------------
    stored = chg_pv * lim.eta_c_pv + chg_grid * lim.eta_c
    headroom = np.maximum(0.0, lim.soc_max_kwh - soc)
    # `where` rather than a branch: `stored` is 0 on every discharge action and the division would
    # be 0/0 there. The scale is 1 wherever the charge already fits.
    scale = np.where(stored > headroom, headroom / np.where(stored > 0.0, stored, 1.0), 1.0)
    chg_pv = chg_pv * scale
    chg_grid = chg_grid * scale
    stored = np.minimum(stored, headroom)

    # ---- 4. clamp discharge to rated power and available energy -----------------------------
    dis_req = np.maximum(0.0, actions)
    available = np.maximum(0.0, (soc - lim.soc_min_kwh) * lim.eta_d)
    dis_ac = np.minimum(np.minimum(dis_req, lim.dis_cap_kwh), available)
    dis_ac = np.maximum(0.0, dis_ac)
    withdrawn = dis_ac / lim.eta_d if lim.eta_d > 0.0 else np.zeros_like(dis_ac)

    # ---- 5. resulting grid flows -------------------------------------------------------------
    net_flow = load_kwh + chg_pv + chg_grid - pv_kwh - dis_ac
    imp = np.maximum(0.0, net_flow)
    exp = np.maximum(0.0, -net_flow)

    # ---- 6. connection limits ----------------------------------------------------------------
    # Import: shed GRID CHARGING first, then accept what the household load alone forces.
    over_imp = np.maximum(0.0, imp - lim.imp_cap_kwh)
    cut = np.minimum(chg_grid, over_imp)
    chg_grid = chg_grid - cut
    stored = stored - cut * lim.eta_c
    imp = imp - cut

    # Export: shed BATTERY-TO-GRID discharge first (a choice), then curtail PV (not a choice).
    over_exp = np.maximum(0.0, exp - lim.exp_cap_kwh)
    # How much of the export is the battery's: the discharge the household could not absorb. The
    # house's own deficit is served first (§6.7's ordering), so the surplus discharge is what is
    # left after covering `load − pv`, floored at 0.
    house_deficit = max(0.0, load_kwh - pv_kwh)
    dis_to_grid = np.maximum(0.0, dis_ac - house_deficit)
    cut_dis = np.minimum(dis_to_grid, over_exp)
    dis_ac = dis_ac - cut_dis
    dis_to_grid = dis_to_grid - cut_dis
    withdrawn = withdrawn - (cut_dis / lim.eta_d if lim.eta_d > 0.0 else 0.0)
    exp = exp - cut_dis
    # Whatever export remains above the cap is PV that could not be delivered and could not be
    # stored — curtailed. It does not change `imp`, which is what the DP minimises, but it does
    # change nothing else here either: curtailment is a pure loss with no state consequence.
    exp = np.minimum(exp, lim.exp_cap_kwh)

    # ---- 7. integrate --------------------------------------------------------------------------
    soc_next = soc + stored - withdrawn

    # ---- feasibility ---------------------------------------------------------------------------
    # The window bound holds by construction after steps 3 and 4 (see the docstring), so it is an
    # assertion rather than a filter: silently marking a clamp bug "infeasible" would hide it.
    assert np.all(soc_next >= lim.soc_min_kwh - SOC_COMPARE_EPS_KWH), "DP SoC fell below the floor"
    assert np.all(soc_next <= lim.soc_max_kwh + SOC_COMPARE_EPS_KWH), "DP SoC rose above the ceiling"

    if lim.allow_grid_export:
        feasible = np.ones_like(soc_next, dtype=bool)
    else:
        # Battery energy leaving the premises is what the permission governs; PV export is not.
        feasible = dis_to_grid <= SOC_COMPARE_EPS_KWH

    return _Transition(soc_next=soc_next, imp=imp, feasible=feasible)


@dataclass(frozen=True)
class DispatchResult:
    """One perfect-foresight run's outcome — what the optimal dispatch actually did.

        imp        kWh imported per interval, NaN on gap intervals (matching `Flows`, §6.9's
                   convention: a gap is an interval nobody evaluated, and 0 would be a claim).
        soc        kWh state of charge at the END of each interval, populated on gaps too (the SoC
                   carried forward), so the trace is a continuous line.
        gap        the intervals skipped, identical to run C's mask by construction.
        soc_start  the SoC the run began from, clamped into the window exactly as §6.9 clamps it.
        import_kwh Σ `imp` over the non-gap intervals — the figure §6.11's saving subtracts.
        allow_grid_export   which export reading this run was made under. Carried so a caller
                   cannot mix up the inheriting and unconstrained results.
    """

    imp: np.ndarray
    soc: np.ndarray
    gap: np.ndarray
    soc_start: float
    import_kwh: float
    allow_grid_export: bool

    @property
    def soc_end(self) -> float:
        """The SoC after the last interval — `soc_start` when there were no intervals at all."""
        if len(self.soc) == 0:
            return self.soc_start
        return float(self.soc[-1])


def perfect_foresight(
    frame: SimulationFrame,
    cfg: SimulationConfig,
    *,
    allow_grid_export: bool | None = None,
) -> DispatchResult:
    """§6.12's DP: the dispatch that minimises kWh of grid import over the whole window.

    `allow_grid_export` selects the §6.12 export baseline: None (the default) INHERITS
    `cfg.allow_grid_export` — the primary reading — and True forces the unconstrained one. There is
    no reason to pass False explicitly; inheriting an already-False config gives the same run.

    ## The two passes

    **Backward.** `V[j]` is the minimum total future import achievable from SoC level `j` at the
    current interval boundary. It is seeded at the terminal boundary with 0 for every level at or
    above the starting SoC and `+INF` below it — §6.12's terminal constraint, without which "the DP
    simply liquidates the battery and inflates the bound". Then, walking backwards, each interval
    evaluates every (level, action) pair at once, interpolates `V` at the landing SoC, adds the
    interval's import, and takes the per-level minimum. The chosen action index is recorded so the
    forward pass can replay it.

    **Forward.** `_roll_forward` starts from the actual (clamped) initial SoC and, at each
    interval, reads the policy at the SoC level nearest the current SoC, applies that action through
    the same `_transition`, and records the import and the new SoC. Nearest-level lookup on the
    POLICY is not the same approximation `V` interpolation removes: `V` is a value being summed over
    8,760 intervals, where a systematic rounding compounds; the policy is a discrete choice among
    41 actions, and the action chosen at a slightly different SoC is almost always the same action.
    The resulting trajectory is a genuine feasible dispatch under the real step function, which is
    what makes the reported figure a dispatch's import total rather than the DP's own estimate of
    one.

    ## Complexity and cost

    `O(T × n_soc × n_actions)` ≈ 8,760 × 101 × 41 ≈ 36M vectorised operations at appendix A's
    defaults — §6.12 says "a few seconds in numpy" and the measurement on the real dataset agrees
    (see `changelog/20260725-perfect-foresight-benchmark-phase5.md`). The per-interval work is a
    handful of (101 × 41) array ops plus one `np.interp` over 4,141 points; the Python loop over
    intervals is unavoidable because `V` at interval `i` depends on `V` at `i+1`.

    ## Gaps

    An interval whose `load` or `pv` is NaN is skipped in BOTH passes: it contributes no cost, no
    transition and no choice, and `V` passes through it unchanged. This mirrors §6.9 exactly, which
    is what keeps the DP's import total summed over the same interval set as run C's.
    """
    if allow_grid_export is None:
        allow_grid_export = cfg.allow_grid_export

    n = frame.intervals
    lim = _DpLimits.of(cfg, frame.dt_hours, allow_grid_export=allow_grid_export)
    # §6.9's clamp, applied in `_DpLimits.of` and read back here so the SoC grid, the terminal
    # constraint and the forward pass all start from ONE number.
    soc_start = lim.soc_start_kwh

    # §6.9's gap rule, evaluated once for the whole window.
    gap = np.isnan(frame.load) | np.isnan(frame.pv)
    # `frame.load + standby` REBINDS into a new array — the frame's own arrays are shared with
    # `app/summary_view.py` and the panel-③ view and are never written to (§6.9's `_View`).
    load = frame.load + lim.standby_kwh

    if n == 0:
        return DispatchResult(
            imp=np.zeros(0),
            soc=np.zeros(0),
            gap=gap,
            soc_start=soc_start,
            import_kwh=0.0,
            allow_grid_export=allow_grid_export,
        )

    soc_col = lim.soc_levels[:, None]  # (n_soc, 1)
    n_soc = len(lim.soc_levels)

    # ── Backward pass ────────────────────────────────────────────────────────────────────────
    # §6.12's terminal constraint. `SOC_COMPARE_EPS_KWH` of slack so a level that lands exactly on
    # the starting SoC in floating point is not excluded by a rounding artefact.
    V = np.zeros(n_soc, dtype=np.float64)
    V[lim.soc_levels < soc_start - SOC_COMPARE_EPS_KWH] = DP_INF

    # `V` after each interval boundary, so the forward pass can re-solve the one-step problem at
    # the TRUE continuous SoC rather than at a snapped grid level. `values[i]` is the value function
    # facing interval `i`; `values[n]` is the terminal one. At appendix A's 101 levels over 8,760
    # hourly intervals that is 8,761 × 101 float64 ≈ 7 MB, which buys the forward pass exactness —
    # see `_roll_forward` on why storing an action table instead is measurably worse.
    values = np.empty((n + 1, n_soc), dtype=np.float64)
    values[n] = V
    for i in range(n - 1, -1, -1):
        if gap[i]:
            # No energy moves and no choice is made; `V` passes through unchanged (§6.9's gap rule).
            values[i] = V
            continue
        act_row = _interval_actions(float(load[i]), float(frame.pv[i]), lim)[None, :]
        tr = _transition(soc_col, act_row, float(load[i]), float(frame.pv[i]), lim)
        # §6.12's `Vn = interp(soc_next, soc_levels, V)` — LINEAR, not nearest. `np.interp` clamps
        # outside the grid, which is correct here: `soc_next` is inside the window by construction
        # (asserted in `_transition`) and the ends of `soc_levels` ARE the window's ends.
        vn = np.interp(tr.soc_next, lim.soc_levels, V)
        tot = np.where(tr.feasible, tr.imp + vn, DP_INF)
        V = tot.min(axis=1)
        values[i] = V

    return _roll_forward(values, frame, load, gap, lim, soc_start, allow_grid_export)


def _roll_forward(
    values: np.ndarray,
    frame: SimulationFrame,
    load: np.ndarray,
    gap: np.ndarray,
    lim: _DpLimits,
    soc_start: float,
    allow_grid_export: bool,
) -> DispatchResult:
    """§6.12's `roll_forward` — replay the optimal policy from the real initial SoC.

    The forward pass is what turns a value function into a dispatch. At each interval it evaluates
    every action at the CURRENT continuous SoC through the same `_transition` the backward pass
    used, adds the interpolated continuation value `values[i+1]`, and takes the best. Because the
    transition is the same function, the trajectory is feasible under exactly the limits run C
    obeys — so the import total it produces is a real dispatch's, not the DP's estimate of one.

    **Re-solving beats replaying a stored action table, and the difference is not academic.**
    §6.12's pseudocode stores `policy[i] = tot.argmin(axis=1)` and the obvious forward pass reads
    `policy[i, nearest_level(soc)]`. That snapping is a second discretisation on top of the one
    `V` interpolation exists to remove, and it bites hardest exactly where it matters: near the
    terminal constraint, where the level below the true SoC is `+INF`-valued and prescribes an
    action chosen to escape an infeasibility the real state is not in. Re-solving costs one extra
    (1 × n_actions) transition per interval — a few percent of the backward pass, which evaluates
    (n_soc × n_actions) — and removes the error entirely.
    """
    n = frame.intervals
    imp = np.full(n, np.nan, dtype=np.float64)
    soc_trace = np.empty(n, dtype=np.float64)
    soc = soc_start
    for i in range(n):
        if gap[i]:
            soc_trace[i] = soc  # SoC carried forward across the outage, as §6.9 carries it
            continue
        # The SAME per-interval action set the backward pass optimised over — see
        # `_interval_actions`. A forward pass on a different action set would re-solve a different
        # problem from the one `values[i + 1]` was computed for.
        act_row = _interval_actions(float(load[i]), float(frame.pv[i]), lim)[None, :]
        one = np.array([[soc]], dtype=np.float64)
        tr = _transition(one, act_row, float(load[i]), float(frame.pv[i]), lim)
        vn = np.interp(tr.soc_next, lim.soc_levels, values[i + 1])
        tot = np.where(tr.feasible, tr.imp + vn, DP_INF)
        k = int(np.argmin(tot[0]))
        imp[i] = float(tr.imp[0, k])
        soc = float(tr.soc_next[0, k])
        soc_trace[i] = soc

    return DispatchResult(
        imp=imp,
        soc=soc_trace,
        gap=gap,
        soc_start=soc_start,
        import_kwh=float(np.nansum(imp)),
        allow_grid_export=allow_grid_export,
    )


# ── The §6.12 energy benchmark block ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EnergyBenchmark:
    """§6.12's `benchmarks.energy` — the bound, the capture ratio, and their unconstrained twins.

        policy_saved_kwh   `A.imp − C.imp`, repeated here so the block is self-contained and the
                   fixture-6 assertion has both sides in one place, in one unit.
        perfect_foresight_saved_kwh   `A.imp − D.imp` under the INHERITING export reading. The
                   primary bound. Fixture 6: this is ≥ `policy_saved_kwh` for every configuration.
        capture_ratio   `policy_saved_kwh / perfect_foresight_saved_kwh`. None when the bound is
                   ~0 — a window in which even perfect foresight could avoid nothing has no ratio
                   to report, and 0/0 or a huge number would both be worse than an absence.
                   §7.2 item 6: this is a FLOOR on achievable improvement, not a target; no real
                   controller knows every future price.
        perfect_foresight_saved_kwh_unconstrained / capture_ratio_unconstrained   the same two
                   under the unconstrained reading. **Both None when `allow_grid_export` is on**,
                   because the second DP is provably identical and is not run (§6.12). Never
                   "equal and present" — that would invite a reader to think two DPs agreed.
        bound_import_kwh / bound_import_kwh_unconstrained   the DP runs' own import totals, kept
                   so a caller can see the bound's absolute figure and not only its difference.
        soc_end_kwh / soc_start_kwh   the inheriting DP's SoC endpoints, which is where the §6.12
                   terminal constraint is observable: `soc_end ≥ soc_start` within
                   `SOC_COMPARE_EPS_KWH` is the constraint having bound.
        policy_soc_delta_kwh   run C's `soc_end − soc_start`, the POLICY run's drift. Carried here
                   because §6.12's terminal constraint is ASYMMETRIC — the DP must end at or above
                   its starting SoC, the policy run need not — so a policy that liquidates its
                   opening charge books a saving the DP is forbidden to book, and the capture ratio
                   compares a drift-funded numerator against a drift-neutral denominator. Without
                   this field a consumer cannot tell a ratio that means something from one that
                   does not. It is read off the same run C `Flows` the saving comes from, so it
                   cannot disagree with `metrics.soc_delta_kwh`. Negative means the battery ended
                   MORE empty than it started, which is the direction that inflates the saving.

    Note the capture ratio may exceed 1 only if something is wrong: fixture 6 says the bound cannot
    be beaten. It is NOT clamped here — a clamp would turn a detectable defect into a plausible
    number — so a consumer that sees > 1 is seeing a real fault. **A VIEW must not print it as a
    plain percentage on that account**: see `app/results_view._benchmark_block`, which distinguishes
    a drift-funded ratio (restated on the drift-corrected basis) from a genuine fault (stated as
    "not usable" and given no number).
    """

    policy_saved_kwh: float
    perfect_foresight_saved_kwh: float
    capture_ratio: float | None
    perfect_foresight_saved_kwh_unconstrained: float | None
    capture_ratio_unconstrained: float | None
    bound_import_kwh: float
    bound_import_kwh_unconstrained: float | None
    baseline_import_kwh: float
    soc_start_kwh: float
    soc_end_kwh: float
    policy_soc_delta_kwh: float = 0.0


def _capture_ratio(policy_saved: float, bound_saved: float) -> float | None:
    """`policy_saved / bound_saved`, or None when the bound is ~0 (§6.11's DIV_GUARD_EPS shape).

    Guarded on the DENOMINATOR only. A negative policy saving is a legitimate result (§7.2 item 9)
    and passes through with its sign — a battery that cost energy captured a negative share of what
    a perfect one would have avoided, which is exactly what the reader should see.
    """
    if abs(bound_saved) <= DIV_GUARD_EPS:
        return None
    return policy_saved / bound_saved


def energy_benchmark(
    baseline: Flows,
    policy: Flows,
    frame: SimulationFrame,
    cfg: SimulationConfig,
) -> EnergyBenchmark:
    """Run §6.12's energy DP(s) over `frame` and assemble the block against runs A and C.

    `baseline` is run A and `policy` is run C — passed in rather than re-run, so the saving in this
    block is the SAME number `app/domain/metrics.py` reports and the two cannot drift.

    One DP when `cfg.allow_grid_export` is on (the unconstrained reading is provably identical, so
    the fields are None), two when it is off (the default). §6.12's second invariant —
    `unconstrained ≥ inheriting` — is a property of the action sets, and it is asserted in
    `tests/test_benchmark.py` rather than here: a runtime assertion on a user-facing page would turn
    a numerical near-tie into a crash.
    """
    baseline_import = float(np.nansum(baseline.imp))
    policy_import = float(np.nansum(policy.imp))
    policy_saved = baseline_import - policy_import

    inheriting = perfect_foresight(frame, cfg)
    pf_saved = baseline_import - inheriting.import_kwh

    unconstrained_saved: float | None = None
    unconstrained_import: float | None = None
    if not cfg.allow_grid_export:
        unconstrained = perfect_foresight(frame, cfg, allow_grid_export=True)
        unconstrained_import = unconstrained.import_kwh
        unconstrained_saved = baseline_import - unconstrained.import_kwh

    return EnergyBenchmark(
        policy_saved_kwh=policy_saved,
        perfect_foresight_saved_kwh=pf_saved,
        capture_ratio=_capture_ratio(policy_saved, pf_saved),
        perfect_foresight_saved_kwh_unconstrained=unconstrained_saved,
        capture_ratio_unconstrained=(
            None if unconstrained_saved is None
            else _capture_ratio(policy_saved, unconstrained_saved)
        ),
        bound_import_kwh=inheriting.import_kwh,
        bound_import_kwh_unconstrained=unconstrained_import,
        baseline_import_kwh=baseline_import,
        soc_start_kwh=inheriting.soc_start,
        soc_end_kwh=inheriting.soc_end,
        # The POLICY run's drift, from the same `Flows` the saving is computed from — see the
        # field's note on why the ratio is uninterpretable without it.
        policy_soc_delta_kwh=policy.soc_end - policy.soc_start,
    )
