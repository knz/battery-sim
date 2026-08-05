"""§6.12's perfect-foresight benchmarks — run D (the ENERGY objective) and run E (the COST one).

The headline "1,412 kWh saved" is uninterpretable on its own. §6.12's whole purpose is to make it
"1,412 kWh of a possible 1,988", which requires knowing what the best possible dispatch over this
exact window would have avoided. That best possible dispatch is what this module computes, by
dynamic programming over a discretised state of charge. The same applies to "€331", which §6.12
wants read as "€331 of a theoretical €478" — hence the second objective.

## One DP, two objectives, two runs

§6.12: "Both are well-formed minimisation problems over the same state space, the same action set
and the same feasibility constraints, so the DP below, its terminal constraint and its
interpolation serve both unchanged — **only `transition_cost` differs**." That sentence is the
shape of this module. `perfect_foresight` takes an `Objective` and everything else — the state
grid, the per-interval action set, the SoC-grid snap, `V` interpolation, the terminal constraint,
the gap rule, the two export baselines, the forward pass — is shared code that neither objective
can specialise. A second DP written out for euros would have been the wrong shape: the two would
drift, and the six paragraphs below documenting why the shared machinery is correct would then
document only half of it.

    ENERGY (run D)   `transition_cost` = kWh of grid import in the interval. Always run.
    COST   (run E)   `transition_cost` = `imp × p_import[i] − exp × p_export_net[i]` EUR in the
                     interval. Run only when `cfg.simulate_cost` (§6.12's table).

**They are two RUNS, not one retargeted run** — §6.12 is explicit, and fixture 20 pins it. A
cost-optimal dispatch imports more during cheap hours and therefore avoids LESS import, so a single
DP whose objective followed `simulate_cost` would hand the energy section a ceiling that moved when
the user asked for euros: a kWh figure changing for a reason that has nothing to do with the
household's battery. `energy_benchmark` therefore never reads a price, under any config, and
`benchmarks.energy` is bit-identical with and without cost simulation.

**The cost objective prices BOTH grid directions, which is why `_Transition` carries `exp`.** The
energy objective needs import alone; euros need the export term too, and §6.5 clamps nothing, so
`p_export_net` is frequently negative — exporting during a negative-price hour ADDS to the bill
(§6.10's "one of the more important things this tool can show a user"). A cost DP that dropped the
export term, or clamped it at zero, would be optimising a different problem and would miss exactly
the effect the tool exists to surface.

## The optimisation, and the four things that make it correct rather than merely plausible

**1. The terminal constraint is load-bearing, not a refinement.** §6.12: "Without it the DP simply
liquidates the battery and inflates the bound." A DP free to end the window empty gets a free
`soc_start − soc_min` kWh of discharge it never paid to store, and the resulting bound is not an
upper bound on anything a real battery could have done over the same window. `V` is therefore
seeded `+INF` below the starting SoC, so no trajectory that ends below it is ever selected.

**2. `V` is INTERPOLATED, never snapped to the nearest SoC level.** Snapping rounds every
transition's landing SoC to a grid node, and rounds *upward* about as often as downward — an upward
round credits the battery with energy it does not have, a small leak at every transition that
compounds over the window. So the snapped figure is **optimistic, and lands BELOW the realised
saving**: it bounds nothing, which is the one thing this run exists to do. It also converges upward
as the grid refines rather than settling, so a finer grid does not rescue it — §6.12 measures
snapping still 0.5 kWh short at 401 levels where interpolation is stable from 11 on.

Do not read snapping as the cheap conservative option; it is neither. (§6.12's earlier drafts
called the snapping error "a systematic pessimism bias of several percent" and that quotation
survived in this docstring for a while — it was **wrong in both direction and magnitude**, and the
spec retracted it from measurement. `test_interpolating_v_differs_measurably_from_nearest_snapping`
and `test_interpolation_is_stable_under_soc_grid_refinement` are the local demonstrations.)

`np.interp` is linear in `V` between the bracketing levels, which is exact whenever `V` is locally
linear in SoC and close otherwise.

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

## The one thing the cost objective CANNOT see: §6.5's feed-in floor top-up

`compute_costs` subtracts a period-level top-up from the bill — the statutory floor, assessed on a
whole assessment period's export revenue at once (§6.5). It is **not separable across intervals**,
so a DP whose state is the SoC cannot represent it: `max(0, −Σ_period exp × compensation)` depends
on the whole period's dispatch, and pricing it inside `transition_cost` would require carrying the
period's running export revenue as a second state dimension. Run E therefore minimises the
per-interval part of the bill and the top-up is applied afterwards, when the realised dispatch's
export array exists.

That is a real, documented limitation rather than an oversight, and `CostBenchmark` carries both
bases so a consumer can see which one it is reading. In every window where the floor does not bind
— which is almost all of them; the floor binds only where a whole period's export earned a net
negative amount — the two bases are identical and the distinction is invisible. Where it does bind,
run E is optimal for the pre-top-up bill and merely very good for the full one, so the FULL-bill
bound can in principle be beaten by a policy that stumbles into a larger top-up. §6.12 does not
address this at all; see `CostBenchmark` for the fields and `cost_benchmark` for what is asserted.

## What is deliberately NOT here

    a cache                    the DPs are recomputed per request. See `perfect_foresight`'s note
                               on the measured cost before adding one.
    the euro drift correction  `CostBenchmark` carries the inputs (§6.11's median import price and
                               each side's SoC drift) but does not apply it: §6.12 states the
                               correction only in kWh, so applying a euro analogue silently inside
                               the block would present a reasoned extension as a spec figure.
    §4.5's `benchmarks` assembly, `null`-when-energy-only   a view/result-object concern.

Main items:
    DP_INF                 the +INF sentinel the backward pass uses for infeasible transitions.
    Objective              §6.12's `transition_cost`, as the ONE thing the two runs differ in.
    ENERGY_OBJECTIVE       run D's: kWh of grid import.
    CostObjective          run E's: EUR per interval, from the §6.5 price arrays.
    _DpLimits              the per-run constants hoisted out of the config once (cf. `_StepLimits`).
    _transition()          §6.8 steps 2–7, vectorised over (n_soc × n_actions).
    DispatchResult         one DP run's outcome: the import and export arrays, the SoC trace, the
                           gap mask.
    perfect_foresight()    §6.12's DP under a given objective — backward pass then `_roll_forward`.
    EnergyBenchmark        the §6.12 energy block: both bounds, both capture ratios.
    energy_benchmark()     runs the one or two ENERGY DPs and assembles the block.
    CostBenchmark          the §6.12 cost block, §4.5's `benchmarks.cost`.
    cost_benchmark()       runs the one or two COST DPs and assembles the block.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.costs import compute_costs
from app.domain.pricing import PriceCurves
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
        imp         kWh imported — §6.12's `transition_cost` for the ENERGY objective, and the
                    priced-at-`p_import` half of the COST one.
        exp         kWh exported, after §6.8 step 6's cap and curtailment. **Carried because the
                    cost objective prices BOTH directions**: euros are
                    `imp × p_import − exp × p_export_net`, and `p_export_net` is frequently
                    negative (§6.5 clamps nothing), so export is not a term a euro-minimising DP
                    may drop. The energy objective ignores it; it is computed either way as a local
                    inside `_transition` — §6.8 step 6's export cap needs it — so returning it
                    costs nothing but the attribute.
        feasible    False where the action cannot be taken at all (see `_transition`).

    A small class rather than a tuple so the four arrays are named at every use; the DP evaluates
    it once per interval and discards it, so the allocation is not on any hot path worth defending.
    """

    __slots__ = ("soc_next", "imp", "exp", "feasible")

    def __init__(
        self, soc_next: np.ndarray, imp: np.ndarray, exp: np.ndarray, feasible: np.ndarray
    ) -> None:
        self.soc_next = soc_next
        self.imp = imp
        self.exp = exp
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

    return _Transition(soc_next=soc_next, imp=imp, exp=exp, feasible=feasible)


# ── §6.12's `transition_cost`: THE one thing runs D and E differ in ───────────────────────────


class Objective:
    """§6.12's `transition_cost` — the per-interval quantity the DP minimises, and nothing else.

    §6.12: "Both are well-formed minimisation problems over the same state space, the same action
    set and the same feasibility constraints, so the DP below, its terminal constraint and its
    interpolation serve both unchanged — only `transition_cost` differs." This class is that
    sentence made structural. An objective may supply ONE thing: `cost(tr, i)`, an (n_soc,
    n_actions) array of the interval's cost for every (state, action) pair. It gets no hook into
    the grids, the feasibility rule, the terminal constraint or the two passes, so there is no
    seam along which run D and run E can come to disagree about the physics.

    **A class rather than a plain callable or an enum, and both alternatives were considered.** A
    bare callable would do the job — `cost(tr, i)` is the whole interface — but the cost objective
    has to carry two price arrays with it, so it would have to be a closure, and a closure is
    exactly the shape that makes "which prices was this bound computed under?" unanswerable from
    the result. An enum would push the price arrays back into `perfect_foresight`'s signature as
    optional parameters that are required for one member and meaningless for the other, which is
    the arrangement that lets a caller ask for euros and silently get kWh. A small object carries
    its own data, names itself in a traceback, and is trivially inspectable.

    Subclasses are `_EnergyObjective` (run D) and `CostObjective` (run E).
    """

    #: Short name for messages and for the `DispatchResult` a run carries, so a bound can always
    #: say which quantity it is a bound ON.
    name: str = "abstract"

    def cost(self, tr: _Transition, i: int) -> np.ndarray:
        """The interval's cost for every (state, action) pair — same shape as `tr.imp`."""
        raise NotImplementedError


class _EnergyObjective(Objective):
    """Run D: `transition_cost` is kWh of grid import in the interval (§6.12's table).

    Not a "degraded substitute for the cost one" (§6.12): minimising grid import is what a
    household optimising for self-sufficiency rather than for money would want, and the capture
    ratio it produces is a real measurement in every run.

    Stateless, so `ENERGY_OBJECTIVE` below is the single shared instance.
    """

    name = "energy"

    def cost(self, tr: _Transition, i: int) -> np.ndarray:
        return tr.imp


#: The one energy objective. A module-level singleton because it holds no state: two instances
#: could not differ, and a fresh one per DP run would only obscure that.
ENERGY_OBJECTIVE = _EnergyObjective()


class CostObjective(Objective):
    """Run E: `transition_cost` is EUR spent in the interval (§6.12's table).

        cost_i = imp × p_import[i] − exp × p_export_net[i]

    which is `costs.compute_costs`' per-interval integrand, term for term, so the DP minimises
    exactly the quantity the bill is later computed from. Deriving the two independently is how a
    "bound" that the bill disagrees with gets built.

    **The export term is SUBTRACTED and is NOT clamped**, for §6.10's reason: §6.5 clamps nothing,
    `p_export_net = compensation − terugleverkosten` goes negative well above the negative-price
    range, and subtracting a negative export term ADDS to the bill. A DP with a `max(0, .)` here
    would believe exporting is always weakly good and would happily dump energy onto the grid in
    hours where doing so costs the household money — which is the specific behaviour this tool
    exists to let a user see, so a benchmark blind to it would bound the wrong problem.

    **NaN prices are treated as zero cost, matching §6.10's gap rule.** §4.4 writes NaN into `spot`
    where no price covers the interval and it propagates through every §6.5 array; `costs._nansum`
    excludes those intervals from the bill entirely. The DP has to agree, or its bound would be
    summed over a different interval set than the bill it bounds — the same reasoning that makes
    both skip §6.9's gaps. `np.nan_to_num` on the two scalars is where that happens, and it means
    an uncovered interval is one in which the DP is free to do anything: it is, and the bill will
    charge it nothing either way.

    The floor top-up is NOT here; see the module comment on why it cannot be (it is a period
    aggregate, not a per-interval term) and `cost_benchmark` for what is done about it.
    """

    name = "cost"

    __slots__ = ("p_import", "p_export_net")

    def __init__(self, p_import: np.ndarray, p_export_net: np.ndarray) -> None:
        # Copied into float64 arrays here rather than trusted as passed: the DP indexes them 8,760
        # times and a list or an integer dtype would be a per-interval surprise.
        self.p_import = np.asarray(p_import, dtype=np.float64)
        self.p_export_net = np.asarray(p_export_net, dtype=np.float64)

    def cost(self, tr: _Transition, i: int) -> np.ndarray:
        p_imp = float(np.nan_to_num(self.p_import[i], nan=0.0))
        p_exp = float(np.nan_to_num(self.p_export_net[i], nan=0.0))
        return tr.imp * p_imp - tr.exp * p_exp


@dataclass(frozen=True)
class DispatchResult:
    """One perfect-foresight run's outcome — what the optimal dispatch actually did.

        imp        kWh imported per interval, NaN on gap intervals (matching `Flows`, §6.9's
                   convention: a gap is an interval nobody evaluated, and 0 would be a claim).
        exp        kWh exported per interval, NaN on gaps, after §6.8 step 6's cap. Populated for
                   BOTH objectives — the arithmetic is the same either way — because the cost
                   block has to price the realised dispatch's export, and because a caller that
                   wants a euro figure for an ENERGY-optimal dispatch (§6.13's basis question, a
                   plausible future consumer) can get one without a third DP.
        soc        kWh state of charge at the END of each interval, populated on gaps too (the SoC
                   carried forward), so the trace is a continuous line.
        gap        the intervals skipped, identical to run C's mask by construction.
        soc_start  the SoC the run began from, clamped into the window exactly as §6.9 clamps it.
        import_kwh Σ `imp` over the non-gap intervals — the figure §6.11's saving subtracts.
        allow_grid_export   which export reading this run was made under. Carried so a caller
                   cannot mix up the inheriting and unconstrained results.
        objective  the name of the objective this dispatch was optimal FOR ("energy" / "cost").
                   Carried for the same reason `allow_grid_export` is: the two runs' results are
                   the same type and are otherwise indistinguishable, and §6.12's whole point is
                   that they are different dispatches. Fixture 20 asserts they differ; this is the
                   field that makes a mix-up at a call site a visible error rather than a plausible
                   number.
    """

    imp: np.ndarray
    exp: np.ndarray
    soc: np.ndarray
    gap: np.ndarray
    soc_start: float
    import_kwh: float
    allow_grid_export: bool
    objective: str = ENERGY_OBJECTIVE.name

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
    objective: Objective = ENERGY_OBJECTIVE,
) -> DispatchResult:
    """§6.12's DP: the dispatch that minimises `objective` over the whole window.

    `objective` is §6.12's `transition_cost` and is the ONLY thing runs D and E differ in — see
    `Objective`. It defaults to `ENERGY_OBJECTIVE` (run D, kWh of grid import) because that is the
    run §6.12's table marks "always"; `CostObjective` gives run E. Everything below is written once
    and serves both: a change to the terminal constraint, the interpolation, the action set or the
    gap rule reaches the two runs together or not at all.

    `allow_grid_export` selects the §6.12 export baseline: None (the default) INHERITS
    `cfg.allow_grid_export` — the primary reading — and True forces the unconstrained one. There is
    no reason to pass False explicitly; inheriting an already-False config gives the same run.

    ## The two passes

    **Backward.** `V[j]` is the minimum total future OBJECTIVE achievable from SoC level `j` at the
    current interval boundary — kWh of import under run D, euros under run E. It is seeded at the
    terminal boundary with 0 for every level at or above the starting SoC and `+INF` below it —
    §6.12's terminal constraint, without which "the DP simply liquidates the battery and inflates
    the bound". Then, walking backwards, each interval evaluates every (level, action) pair at
    once, interpolates `V` at the landing SoC, adds the interval's cost, and takes the per-level
    minimum. The chosen action index is recorded so the forward pass can replay it.

    **Note `V` may be NEGATIVE under the cost objective**, and nothing here assumes otherwise: an
    hour of negative `p_import` or of positive `p_export_net` is money made, not spent. `DP_INF` is
    `np.inf` rather than a large finite number precisely so a genuinely large negative continuation
    value can never sort below an infeasibility (module note on `DP_INF`).

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
            exp=np.zeros(0),
            soc=np.zeros(0),
            gap=gap,
            soc_start=soc_start,
            import_kwh=0.0,
            allow_grid_export=allow_grid_export,
            objective=objective.name,
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
        # §6.12's `tot = cost + Vn`. `objective.cost` is the ONE call that differs between runs D
        # and E; everything above and below it is shared.
        tot = np.where(tr.feasible, objective.cost(tr, i) + vn, DP_INF)
        V = tot.min(axis=1)
        values[i] = V

    return _roll_forward(
        values, frame, load, gap, lim, soc_start, allow_grid_export, objective
    )


def _roll_forward(
    values: np.ndarray,
    frame: SimulationFrame,
    load: np.ndarray,
    gap: np.ndarray,
    lim: _DpLimits,
    soc_start: float,
    allow_grid_export: bool,
    objective: Objective,
) -> DispatchResult:
    """§6.12's `roll_forward` — replay the optimal policy from the real initial SoC.

    The forward pass is what turns a value function into a dispatch. At each interval it evaluates
    every action at the CURRENT continuous SoC through the same `_transition` the backward pass
    used, adds the interpolated continuation value `values[i+1]`, and takes the best. Because the
    transition is the same function, the trajectory is feasible under exactly the limits run C
    obeys — so the import total it produces is a real dispatch's, not the DP's estimate of one.

    `objective` must be the SAME one the backward pass used, since `values` is the value function
    it produced; re-solving the one-step problem under a different objective would pick actions
    against a continuation value computed for a different quantity. It is passed rather than
    re-derived for that reason, and `perfect_foresight` is the only caller.

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
    exp = np.full(n, np.nan, dtype=np.float64)
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
        tot = np.where(tr.feasible, objective.cost(tr, i) + vn, DP_INF)
        k = int(np.argmin(tot[0]))
        imp[i] = float(tr.imp[0, k])
        exp[i] = float(tr.exp[0, k])
        soc = float(tr.soc_next[0, k])
        soc_trace[i] = soc

    return DispatchResult(
        imp=imp,
        exp=exp,
        soc=soc_trace,
        gap=gap,
        soc_start=soc_start,
        import_kwh=float(np.nansum(imp)),
        allow_grid_export=allow_grid_export,
        objective=objective.name,
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

    **`ENERGY_OBJECTIVE` is passed explicitly and `cfg.simulate_cost` is not read anywhere in this
    function.** That is fixture 18/20's invariant expressed in code rather than in a comment: this
    block is bit-identical whether or not the user asked for euros. Relying on the default argument
    would give the same numbers today and would leave the invariant resting on a default nobody is
    reading, which is how "a cost benchmark was added" becomes "the benchmark was re-aimed".
    """
    baseline_import = float(np.nansum(baseline.imp))
    policy_import = float(np.nansum(policy.imp))
    policy_saved = baseline_import - policy_import

    inheriting = perfect_foresight(frame, cfg, objective=ENERGY_OBJECTIVE)
    pf_saved = baseline_import - inheriting.import_kwh

    unconstrained_saved: float | None = None
    unconstrained_import: float | None = None
    if not cfg.allow_grid_export:
        unconstrained = perfect_foresight(
            frame, cfg, allow_grid_export=True, objective=ENERGY_OBJECTIVE
        )
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


# ── The §6.12 cost benchmark block (run E) ───────────────────────────────────────────────────


@dataclass(frozen=True)
class CostBenchmark:
    """§6.12's `benchmarks.cost` (§4.5) — the euro bound, the capture ratio, and their twins.

    The exact sibling of `EnergyBenchmark`, field for field and convention for convention, in
    euros instead of kWh. Every figure is a SAVING relative to run A's bill, matching §4.5's
    example, where `benchmarks.cost.policy_eur` is the same 331.10 as `cost.saved_eur`:

        no_battery_eur   0.0 by construction — run A's saving against itself. §4.5 lists it, and it
                   is carried rather than left implicit for the same reason §4.5 lists it: it is the
                   origin the other two figures are measured from, and a reader comparing the block
                   against §4.5 should find every field §4.5 shows. `EnergyBenchmark` omits its
                   twin; that asymmetry is worth a note rather than a silent alignment either way,
                   since removing a field from a shipped block is not this phase's business.
        policy_eur   `cost(A) − cost(C)`: what the user's policy actually saved, in euros. The
                   §6.10 bill on both sides, computed here through `compute_costs` from the same
                   `Flows` the energy block reads, so the two blocks describe one pair of runs.
        perfect_foresight_eur   `cost(A) − cost(E)` under the INHERITING export reading. The
                   primary bound. Fixture 6, in EUROS: this is ≥ `policy_eur` for every
                   configuration. **Never compared against the energy block** — §6.12: "the
                   cost-optimal dispatch routinely avoids less import than the import-optimal one",
                   so a cross-block assertion fails correctly-built code.
        capture_ratio   `policy_eur / perfect_foresight_eur`, None when the bound is ~0. Same
                   `_capture_ratio` the energy block uses, so the two cannot acquire different
                   guard conventions.
        perfect_foresight_eur_unconstrained / capture_ratio_unconstrained   the same two under the
                   unconstrained reading. **Both None when `allow_grid_export` is on** — the second
                   DP is provably identical and is not run (§6.12), and "equal and present" would
                   claim two DPs ran and agreed.

                   Note the unconstrained reading bites HARDER here than on the energy side. An
                   export permission cannot change an import-minimising dispatch (exporting earns
                   revenue but avoids no import), so the energy block's two bounds are usually
                   equal; on euros, exporting into a high-price hour is the whole arbitrage case,
                   so a real gap is expected. That is §8.2/X10's question, and this block is where
                   the euro half of the answer accumulates.
        bound_eur / bound_eur_unconstrained   the DP runs' own BILLS (not savings), kept for the
                   same reason `bound_import_kwh` is: a saving is a difference and a reader
                   checking one wants both terms.
        baseline_eur   run A's bill, the term both savings subtract from.
        policy_bill_eur   run C's bill. With `baseline_eur` it makes `policy_eur` checkable by eye.
        soc_start_kwh / soc_end_kwh   the inheriting cost DP's SoC endpoints — where §6.12's
                   terminal constraint is observable for THIS run. Not the energy DP's: the two
                   dispatches differ, which is fixture 20's point.
        policy_soc_delta_kwh   run C's drift, carried for exactly the reason `EnergyBenchmark`
                   carries it: the terminal constraint is asymmetric, so a policy that liquidates
                   its opening charge books a euro saving the DP is forbidden to book.
        median_import_price_eur_kwh   the median of `p_import` over the window, or None when no
                   interval had a price. **The one input a euro-side drift correction needs, and
                   the reason it is a field rather than an applied correction.** §6.12 states the
                   drift correction only in kWh (`saved_kwh + soc_delta_kwh × eta_d`); it says
                   nothing about the euro block. The natural analogue is
                   `saved_eur + soc_delta_kwh × eta_d × median(p_import)` — the residual stored
                   energy, converted to the AC side by `eta_d` exactly as the kWh form does, and
                   valued at the price §6.11 already chose for residual SoC when it defined
                   `soc_delta_value_eur` as the drift "valued at the median import price". So the
                   valuation basis is a spec figure, borrowed from §6.11; APPLYING it inside a
                   §6.12 block is the part the spec does not settle. It is therefore offered, not
                   imposed: the fields needed to compute it are all here, `tests/test_benchmark.py`
                   asserts fixture 6 on it, and a view that wants the corrected figure computes it
                   where the choice is visible. Median rather than mean because §6.11 says median.
        floor_binds   True when either bill's feed-in floor top-up was nonzero, i.e. when the
                   period aggregate the cost DP cannot see actually did something. **The flag that
                   says whether `perfect_foresight_eur` is a bound on the quantity it names.** Run
                   E minimises the per-interval bill; the top-up is a period aggregate and is not
                   separable across intervals (module comment), so it is applied afterwards. When
                   this is False — which is the ordinary case, since the floor binds only where a
                   whole assessment period's export earned a net negative amount — the two bases
                   coincide and the bound is exact up to discretisation. When it is True the bound
                   is on the pre-top-up bill and a policy could in principle beat the full-bill
                   figure by stumbling into a larger top-up. §6.12 does not discuss this; the flag
                   is how the block says so rather than presenting an unqualified number.

    Nothing here is clamped, on the same reasoning as `EnergyBenchmark`: clamping would turn a
    detectable condition into a plausible number. A NEGATIVE euro saving is not a defect — §7.2
    item 9's case, in euros — and passes through with its sign.

    **A euro capture ratio above 1 is USUALLY drift-funding, not a fault — and unlike the energy
    block, there is no corrected basis to restate it on.** A policy that ends emptier than it
    started spent its opening charge, which the DP's terminal constraint forbids; measured over
    `_fixture_6_cost_configs`' 144-configuration sweep, 48 exceed 1 (up to 1.60), all of them in
    the liquidating half. `EnergyBenchmark`'s twin has the same property and `results_view`
    restates it on §6.12's drift-corrected kWh figures — but that correction has **no sound euro
    analogue** (see `median_import_price_eur_kwh` above, and
    `test_the_euro_drift_correction_does_not_restore_the_bound_for_a_liquidating_policy`), because
    a residual kWh's euro worth depends on when it is used and the two sides use it at different
    times by construction.

    So a view MUST NOT print this as a plain percentage, and must not reach for a drift-corrected
    euro restatement either — there is not one to reach for. Branch on `policy_soc_delta_kwh`:
    when the drift is materially negative, say the battery ended less charged than it started and
    that the comparison is not available in euros on that basis. A ratio above 1 with
    NON-negative drift is the case that is a genuine fault.
    """

    no_battery_eur: float
    policy_eur: float
    perfect_foresight_eur: float
    capture_ratio: float | None
    perfect_foresight_eur_unconstrained: float | None
    capture_ratio_unconstrained: float | None
    bound_eur: float
    bound_eur_unconstrained: float | None
    baseline_eur: float
    policy_bill_eur: float
    soc_start_kwh: float
    soc_end_kwh: float
    median_import_price_eur_kwh: float | None
    floor_binds: bool
    policy_soc_delta_kwh: float = 0.0


def _dispatch_flows(result: DispatchResult) -> Flows:
    """A `Flows` carrying the DP dispatch's grid exchange, so `compute_costs` can bill it.

    §6.10's `compute_costs` reads `flows.imp` and `flows.exp` and passes `flows.exp` on to §6.5's
    floor assessment; nothing else on `Flows` is touched. Rather than reimplement that arithmetic
    against a `DispatchResult` — which would be a second bill computation, free to disagree with
    the one the headline euro figure comes from — the dispatch is dressed as a `Flows` and billed
    by the SAME function. That is the same discipline `energy_benchmark` follows by taking runs A
    and C as `Flows` instead of re-running them.

    Everything comes off `result` — the interval count, the starting SoC, and the four arrays
    below. There is deliberately no `template` parameter: an earlier draft took the policy run as
    one and never read it, which is exactly the dead argument that invites a caller to pass
    something plausible and believe it matters. The remaining flow arrays stay at `Flows.empty`'s
    NaN, which is correct rather than lazy: the DP does not decompose its
    dispatch into `chg_pv` / `dis_home` / `withdrawn` (a signed AC action has no such split — see
    `_transition`'s note on the missing netting step), and NaN is §6.9's marker for "the simulation
    declined to assert anything here". A caller reaching for `withdrawn` on this object — to price
    degradation, say — gets NaN rather than a fabricated zero.
    """
    flows = Flows.empty(result.imp.shape[0], soc_start=result.soc_start)
    flows.imp = result.imp
    flows.exp = result.exp
    flows.soc = result.soc
    flows.gap = result.gap
    return flows


def cost_benchmark(
    baseline: Flows,
    policy: Flows,
    frame: SimulationFrame,
    cfg: SimulationConfig,
    curves: PriceCurves,
) -> CostBenchmark:
    """Run §6.12's COST DP(s) over `frame` and assemble §4.5's `benchmarks.cost`.

    The exact sibling of `energy_benchmark`: `baseline` is run A, `policy` is run C, both passed in
    rather than re-run so this block describes the same pair of runs every other figure does. It
    differs in two things and only two: the objective handed to `perfect_foresight`, and the fact
    that a euro figure needs `curves` (§6.5's per-interval price arrays for this window).

    **The caller decides whether to call this at all.** §6.12's table says the cost benchmark runs
    "only when `cfg.simulate_cost`", and this function does not check the flag — the same division
    of labour `compute_costs` follows, and the reason is that a function which silently returned
    `None` on a config flag would make "cost simulation is off" and "the DP failed" the same
    result. Calling it with `simulate_cost` false is not an error (the prices are whatever the
    caller built), it is simply not what §4.5 asks for.

    One DP when `cfg.allow_grid_export` is on, two when it is off — §6.12's two export baselines,
    with the same skip-because-provably-identical rule the energy block applies.

    **Cost, and why the caller must be lazy about it.** This is a second pair of DP passes at the
    same price as the first: ~2.3 s per pass on a year of hourly data at appendix A's 101 × 41
    grids, so ~4.6 s here on top of the energy block's ~4.6 s. `app/results_view.py` already gates
    the energy block behind `with_benchmark` for exactly this reason; a caller that ran this one
    eagerly would put the whole ~9 s on every request.
    """
    p_import = np.asarray(curves.p_import, dtype=np.float64)
    p_export_net = np.asarray(curves.p_export_net, dtype=np.float64)
    objective = CostObjective(p_import, p_export_net)

    def bill(flows: Flows):
        """One run's §6.10 bill, through the SAME `compute_costs` the headline euro figure uses."""
        return compute_costs(
            flows, p_import, p_export_net, curves.compensation, frame.index, cfg.pricing
        )

    baseline_cost = bill(baseline)
    policy_cost = bill(policy)
    policy_saved = baseline_cost.eur - policy_cost.eur

    inheriting = perfect_foresight(frame, cfg, objective=objective)
    inheriting_cost = bill(_dispatch_flows(inheriting))
    pf_saved = baseline_cost.eur - inheriting_cost.eur

    unconstrained_saved: float | None = None
    unconstrained_bill: float | None = None
    unconstrained_topup = 0.0
    if not cfg.allow_grid_export:
        unconstrained = perfect_foresight(
            frame, cfg, allow_grid_export=True, objective=objective
        )
        unconstrained_cost = bill(_dispatch_flows(unconstrained))
        unconstrained_bill = unconstrained_cost.eur
        unconstrained_saved = baseline_cost.eur - unconstrained_cost.eur
        unconstrained_topup = unconstrained_cost.topup_eur

    # §6.11's basis for valuing residual SoC — the median IMPORT price over the window, gaps and
    # uncovered intervals excluded. None when nothing was priced at all, so a consumer cannot
    # value a drift against a number that does not exist. See the field's note: this is offered as
    # the input to a euro drift correction, not applied here.
    priced = p_import[~np.isnan(p_import)]
    median_price = float(np.median(priced)) if priced.size else None

    # Did the period aggregate the DP cannot see actually do anything? Checked across every bill
    # computed here, not only run A's: the floor is assessed per run, and a top-up that appears in
    # exactly one of them is the case where the pre-top-up and full-bill bases diverge.
    floor_binds = (
        max(
            baseline_cost.topup_eur,
            policy_cost.topup_eur,
            inheriting_cost.topup_eur,
            unconstrained_topup,
        )
        > 0.0
    )

    return CostBenchmark(
        # Run A's saving against itself. §4.5 shows it as 0.0 and it is 0.0 by construction, not by
        # measurement — writing `baseline_cost.eur - baseline_cost.eur` would suggest otherwise.
        no_battery_eur=0.0,
        policy_eur=policy_saved,
        perfect_foresight_eur=pf_saved,
        capture_ratio=_capture_ratio(policy_saved, pf_saved),
        perfect_foresight_eur_unconstrained=unconstrained_saved,
        capture_ratio_unconstrained=(
            None if unconstrained_saved is None
            else _capture_ratio(policy_saved, unconstrained_saved)
        ),
        bound_eur=inheriting_cost.eur,
        bound_eur_unconstrained=unconstrained_bill,
        baseline_eur=baseline_cost.eur,
        policy_bill_eur=policy_cost.eur,
        soc_start_kwh=inheriting.soc_start,
        soc_end_kwh=inheriting.soc_end,
        median_import_price_eur_kwh=median_price,
        floor_binds=floor_binds,
        policy_soc_delta_kwh=policy.soc_end - policy.soc_start,
    )
