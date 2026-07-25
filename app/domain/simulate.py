"""The sequential simulation core — §6.6 policies, §6.8 battery step, §6.9 main loop.

Given a §4.4 `SimulationFrame` (Phase 1) and a `SimulationConfig` (Phase 2), this module answers
the product's actual question: interval by interval, what would the battery have done, and what
would have crossed the meter as a result. Everything downstream — the §6.11 metrics, the §6.10
cost accounting, the §4.5 result object — is a summary of the arrays produced here.

It is pure: arrays in, arrays out, no I/O, no clock, no global state (§5.2). That is what makes
the §6.14 fixtures possible, and every fixture in `tests/test_simulate.py` is arrays-in/numbers-out.

## The shape of one interval

    charge_request()     what the CHARGE policy would like       (§6.6)  →  (req_pv, req_grid_chg)
    discharge_request()  what the DISCHARGE policy would like    (§6.7)  →  (req_home, req_grid_dis)
    battery_step()       what the battery and the connection ALLOW (§6.8) →  new SoC + flows

The split is the spec's and it is load-bearing: the policies express intent and know nothing about
SoC, rated power or the fuse; the step knows nothing about price bands. A limit applied in the
wrong half is the classic way a simulator ends up reporting a battery that charges past its own
capacity, or a policy that quietly never fires because a clamp upstream zeroed its request.

## Flows are non-negative magnitudes in named directions

Per §6.6's reminder, there are no signed flows anywhere here. `imp` and `exp` are both ≥ 0 and at
most one is positive in any interval; likewise `chg_*` and `dis_*`. Sign conventions are the other
classic error source in this kind of model, and the spec removes the question by not having signs.

## What is deliberately NOT here

    §6.11 metrics                 saved_kwh, efc, self-consumption — Phase 4 reads these arrays.
    §6.10 cost accounting         no euro touches this module; `simulate_cost` is never read.
    §6.12 perfect foresight       runs D and E — Phase 5.
    §6.15 epochs, §6.16 bracket   later increments; the frame does not carry their fields yet.

`run_all` therefore builds runs A, B and C only, which is what §6.9's table says is "always"
computable from the flow simulation alone.

## Two constraints carried in from earlier phases

**Frame arrays are never modified in place.** `frame.load`, `.pv`, `.import_obs` and `.export_obs`
are the very array objects `reconcile_grid` produced, shared with the data-summary band
(`app/summary_view.py`) and the panel-③ results view. An `+=`, a `[:] =` or an `out=` on any of
them would silently change numbers already published elsewhere in the app. §6.9's
`st.load = frame.load + standby_kwh` REBINDS, which is safe; see `_View`.

**Derived config values are hoisted into locals before the loop, never cached on the config.**
Phase 2 makes `cfg.eta_c`, `cfg.soc_max_kwh` and friends properties on purpose, so a Phase-6 form
binding cannot leave them answering for a superseded slider value. The hoisting happens here, in
the caller, because the loop body does not mutate `cfg` — which is exactly the condition that makes
hoisting safe and caching on the object unsafe.

Main items:
    CANCEL_CHECK_INTERVAL   how often §6.9's loop polls the cancellation hook.
    SOC_COMPARE_EPS_KWH     float slack on the SoC bound assertion (§8 constants table).
    Cancelled               raised by `simulate` when the injected hook says to stop.
    StepFlows               one interval's flows, as `battery_step` returns them.
    Flows                   the per-interval arrays for one run, plus the gap mask.
    charge_request()        §6.6.
    discharge_request()     §6.7.
    net_requests()          §6.7's band-overlap netting.
    battery_step()          §6.8, all seven steps.
    simulate()              §6.9's sequential loop (runs B and C).
    simulate_baseline()     §6.9's vectorised no-battery run (run A), export limit included.
    RunSet / run_all()      runs A, B, C per §6.9's table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, NamedTuple

import numpy as np

from app.domain.simconfig import ChargePolicy, Coupling, DischargePolicy, SimulationConfig
from app.domain.simframe import SimulationFrame

# §6.9: "How often the loop polls the cancellation flag. A power of two large enough that the check
# is free, small enough that cancellation feels prompt." Kept at the spec's value.
CANCEL_CHECK_INTERVAL = 1024

# §8's constants table: "Float-comparison slack, in kWh, on SoC bound assertions and the DP terminal
# constraint, so rounding does not trip an exact `<=`." Numerically equal to `simframe.CLOSURE_TOL`
# but a different quantity — that one is slack on a sum-of-parts identity, this one on a bound
# comparison — so the two stay separate names per §8's `EPS` cautionary note.
SOC_COMPARE_EPS_KWH = 1e-6


class Cancelled(Exception):
    """Raised by `simulate` when the injected cancellation hook returns True (§6.9, §3.3)."""


# ── The per-interval result ──────────────────────────────────────────────────────────────────


class StepFlows(NamedTuple):
    """One interval's flows, as §6.8's `Flows(...)` return — all non-negative kWh.

        imp        kWh drawn from the grid.
        exp        kWh delivered to the grid.
        chg_pv     kWh AC charged into the battery attributed to PV surplus.
        chg_grid   kWh AC charged into the battery attributed to the grid.
                   §7.2 item 4: this is a REQUEST LABEL, not a measurement — under P2/P3 during a
                   sunny hour, energy requested "from grid" may in fact be served by PV. It only
                   affects the efficiency assignment on DC-coupled systems. Documented, not fixed.
        dis_home   kWh AC discharged to serve household load.
        dis_grid   kWh AC discharged to the grid (arbitrage export).
        stored     kWh added to the SoC — chg_ac × eta, i.e. AFTER charge losses.
        withdrawn  kWh removed from the SoC — dis_ac / eta_d, i.e. BEFORE discharge losses.
                   §6.11 counts equivalent full cycles on `withdrawn`, the storage side, precisely
                   because AC-side throughput gives a figure ~5% lower.
        curtailed  kWh of PV that could not be exported and was not stored — generated but never
                   delivered anywhere. See `Flows.conservation_residual`.

    A NamedTuple rather than a dataclass because §6.9 scatters it into arrays immediately and n
    small objects would be allocated for nothing; the field names still read at the call site.
    """

    imp: float
    exp: float
    chg_pv: float
    chg_grid: float
    dis_home: float
    dis_grid: float
    stored: float
    withdrawn: float
    curtailed: float


_FLOW_FIELDS = (
    "imp",
    "exp",
    "chg_pv",
    "chg_grid",
    "dis_home",
    "dis_grid",
    "stored",
    "withdrawn",
    "curtailed",
)


@dataclass
class Flows:
    """The per-interval arrays for ONE run — §6.8/§6.9's `Flows`, as a struct of arrays.

    One float64 array per `StepFlows` field, plus:

        soc        kWh of state of charge at the END of each interval. Always populated, including
                   on gap intervals, where it holds the SoC carried forward.
        gap        boolean mask: True where §6.9 skipped the interval because `load` or `pv` was
                   NaN. The flow arrays are NaN there.
        import_limit_exceeded   indices where household load ALONE exceeded the import cap, i.e.
                   §6.8 step 6's `record_warning(IMPORT_LIMIT_EXCEEDED, i)`. A list of ints rather
                   than a mask because it is normally empty and is reported as a count + examples.
        soc_start  the SoC the run began from, before interval 0. §6.11's `soc_end − soc_start`
                   drift correction needs it and it is not recoverable from `soc` alone.

    **Gap intervals are NaN in the flow arrays, not 0.** This follows §4.4's reasoning about
    `spot`: a 0 in `imp` is a positive claim ("nothing was imported"), which is exactly what the
    simulation declined to assert for an interval whose inputs were missing. §7.3 check 3 says gaps
    are EXCLUDED from sums, and NaN is what makes an accidental `.sum()` fail loudly instead of
    quietly under-reporting. Consumers therefore use `np.nansum` — `totals()` exists so that
    decision is taken once, here, rather than at every call site in Phase 4.
    """

    imp: np.ndarray
    exp: np.ndarray
    chg_pv: np.ndarray
    chg_grid: np.ndarray
    dis_home: np.ndarray
    dis_grid: np.ndarray
    stored: np.ndarray
    withdrawn: np.ndarray
    curtailed: np.ndarray
    soc: np.ndarray
    gap: np.ndarray
    import_limit_exceeded: list[int]
    soc_start: float

    @classmethod
    def empty(cls, n: int, soc_start: float = 0.0) -> Flows:
        """`n` intervals of NaN flows and zero SoC — §6.9's `Flows.empty(n)`.

        NaN rather than 0 so an interval the loop never wrote (a gap, or a run that raised part-way
        through) cannot be mistaken for an interval in which nothing happened.
        """
        return cls(
            **{f: np.full(n, np.nan, dtype=np.float64) for f in _FLOW_FIELDS},
            soc=np.full(n, np.nan, dtype=np.float64),
            gap=np.zeros(n, dtype=bool),
            import_limit_exceeded=[],
            soc_start=soc_start,
        )

    @property
    def intervals(self) -> int:
        return len(self.imp)

    def set(self, i: int, f: StepFlows) -> None:
        """§6.9's `out[i] = f` — scatter one interval's flows into the arrays."""
        self.imp[i] = f.imp
        self.exp[i] = f.exp
        self.chg_pv[i] = f.chg_pv
        self.chg_grid[i] = f.chg_grid
        self.dis_home[i] = f.dis_home
        self.dis_grid[i] = f.dis_grid
        self.stored[i] = f.stored
        self.withdrawn[i] = f.withdrawn
        self.curtailed[i] = f.curtailed

    def mark_gap(self, i: int, soc: float) -> None:
        """§6.9's `out.mark_gap(i)` — the interval is excluded and NO energy moved.

        The flow arrays are left at NaN (see the class docstring). `soc[i]` IS written, with the
        SoC carried forward unchanged, so the SoC trace stays a continuous line across the gap
        rather than acquiring a hole that a plot or a drift calculation would have to guess at.
        """
        self.gap[i] = True
        self.soc[i] = soc

    def totals(self) -> dict[str, float]:
        """Gap-excluding sums of every flow array — the one place `nansum` is decided (§7.3 check 3).

        Returned as a plain dict so Phase 4 can name what it wants without this module having to
        anticipate which totals the §6.11 metrics need.
        """
        return {f: float(np.nansum(getattr(self, f))) for f in _FLOW_FIELDS}

    @property
    def soc_end(self) -> float:
        """The SoC after the last interval — `soc_start` when the run had no intervals at all."""
        if self.intervals == 0:
            return self.soc_start
        return float(self.soc[-1])


# ── §6.6 Charge policy ───────────────────────────────────────────────────────────────────────


def charge_request(
    policy: ChargePolicy, i: int, st: _View, cfg: SimulationConfig
) -> tuple[float, float]:
    """§6.6 verbatim. Returns (kwh_from_pv_surplus, kwh_from_grid) BEFORE any physical limit.

        P1  solar surplus only — net zero at the grid on the export side.
        P2  grid charging only, at FULL RATED POWER, while `A <= spot <= B`. Surplus solar is not
            captured under P2 alone. "Maximise" means full power, literally.
        P3  both; PV surplus is always taken and grid charging adds on top inside the band. The
            combined request is clamped to rated power in §6.8 step 2, PV first, because PV is free
            and — on a DC-coupled system — more efficient.

    **The band is compared against the BARE spot price** (§6.6, product decision), not against a
    retail import price. `A` is a lower bound that exists mainly to let a user exclude deeply
    negative prices; typically it is left very negative so only `B` binds.

    **No `has_pv` branch, and it must not acquire one.** Without PV, `st.pv` is all zeros (§4.4
    fills it that way exactly once, at frame construction), so `solar_surplus` is identically zero:
    P1 charges nothing and P3 degenerates to P2 with no code path saying so. §6.6 states this
    explicitly and §6.14 fixture 17 pins it — the same input with `has_pv=True` + an all-zero solar
    series and with `has_pv=False` + no series at all must produce identical energy figures.

    **No `simulate_cost` branch either.** The band comparison is a DISPATCH decision — it selects
    which intervals the battery charges in, and that changes the kWh answer whether or not anyone
    prices the result. §6.6 says this function takes no branch on `simulate_cost` and should not
    acquire one.

    **A NaN spot idles the grid-charge request, deliberately.** Phase 1 emits NaN for an interval
    no price covers (§4.4: absence is NaN, never 0). `A <= nan <= B` evaluates False in Python, so
    `in_band` is False and no grid charging is requested. That is the behaviour we want — charging
    on an unknown price would be an invention — but it is worth being explicit that it arises from
    IEEE comparison semantics rather than from a test written for it, because a future rewrite of
    the band test (`abs(spot - mid) <= width`, say) would preserve neither the semantics nor the
    reader's ability to see them. PV-surplus charging is unaffected: it never reads `spot`.
    """
    solar_surplus = max(0.0, st.pv[i] - st.load[i])

    req_pv = solar_surplus if policy in (ChargePolicy.P1, ChargePolicy.P3) else 0.0

    in_band = cfg.band_a <= st.spot[i] <= cfg.band_b  # False when spot is NaN — see the docstring
    req_grid = (
        cfg.max_charge_kw * st.dt if (policy in (ChargePolicy.P2, ChargePolicy.P3) and in_band) else 0.0
    )

    return req_pv, req_grid


# ── §6.7 Discharge policy ────────────────────────────────────────────────────────────────────


def discharge_request(
    policy: DischargePolicy, i: int, st: _View, cfg: SimulationConfig
) -> tuple[float, float]:
    """§6.7 verbatim. Returns (kwh_to_home, kwh_to_grid) requested, before physical limits.

        D1  serve household deficit only. Never exports.
        D2  discharge only while `C <= spot <= D`, at FULL rated power. Outside the band the
            battery does nothing even if the house is importing — §6.7: "This is intentional and
            literal."
        D3  both.

    Inside the band, D2/D3 **serve the house FIRST** (`req_home = min(full, deficit)`) and only the
    remainder can go to the grid, and only when `allow_grid_export` permits it. That ordering is
    not cosmetic: under the 2027 regime a kWh discharged to the house displaces `p_import` (≈ €0.25
    at €0.08 spot) while a kWh exported earns `p_export_net` (≈ €0.04–0.09 minus terugleverkosten),
    so home discharge is worth roughly three times as much. `allow_grid_export` defaults off.

    All three policies remain available and DISTINCT without PV, where the deficit `max(0, load −
    pv)` is simply the whole load. Only D1's UI label changes there; its behaviour does not.

    **`economic_guard` is effectively dead in this increment.** The guard's condition reads
    `st.p_export_net[i]`, a §6.10 cost-model output that does not exist in an energy-only run.
    Phase 2 forces `cfg.economic_guard` to read False whenever `simulate_cost` is False — on READ,
    through a property, so no caller can observe it True — and `simulate_cost` is not yet
    implementable at all. The branch is written here per spec, guarded on `cfg.economic_guard` so
    it cannot fire, and left for the increment that adds `p_export_net` to the frame.

    NaN spot: same as `charge_request` — both band comparisons are False, so D2 requests nothing
    and D3 falls back to deficit service alone.
    """
    deficit = max(0.0, st.load[i] - st.pv[i])

    req_home = deficit if policy in (DischargePolicy.D1, DischargePolicy.D3) else 0.0
    req_grid = 0.0

    in_band = cfg.band_c <= st.spot[i] <= cfg.band_d  # False when spot is NaN
    if policy in (DischargePolicy.D2, DischargePolicy.D3) and in_band:
        full = cfg.max_discharge_kw * st.dt
        req_home = min(full, deficit)  # serve the house first
        if cfg.allow_grid_export:
            req_grid = full - req_home

    # economic_guard requires a cost model: p_export_net does not exist without one, and Phase 2
    # forces this flag False when simulate_cost is False. Unreachable in this increment.
    if cfg.economic_guard and st.p_export_net is not None and st.p_export_net[i] <= 0:
        req_grid = 0.0  # never pay to export

    return req_home, req_grid


def net_requests(
    req_pv: float, req_grid_chg: float, req_home_dis: float, req_grid_dis: float
) -> tuple[float, float, float, float]:
    """§6.7's band-overlap netting, in the scaled form §6.8 step 1 states.

    If `[A,B]` and `[C,D]` intersect, a single interval can fire BOTH a charge and a discharge
    request. §7.3 check 12 warns about that configuration at validation time but allows it, so the
    core has to compute something well-defined. §6.7 gives the rule:

        net = (req_pv + req_grid_chg) - (req_home + req_grid_dis)
        charge_total, discharge_total = (net, 0) if net > 0 else (0, -net)

    and §6.8 step 1 spells out how the netted total is split back across the two components: each
    side is scaled by the same factor, so the PV/grid (and home/grid) proportions of the surviving
    request are preserved. Scaling rather than, say, cancelling PV against home first is what keeps
    the efficiency assignment in step 3 meaningful.

    P1/D1 can never conflict — `max(0, pv−load)` and `max(0, load−pv)` are never both positive — so
    this only ever does work under an overlapping-band P2/P3 × D2/D3 configuration.

    Kept as a named function rather than inlined into `battery_step` so the rule can be tested on
    its own; `battery_step` calls it as its step 1.
    """
    chg_req = req_pv + req_grid_chg
    dis_req = req_home_dis + req_grid_dis
    if chg_req > 0 and dis_req > 0:
        net = chg_req - dis_req
        if net >= 0:
            scale = net / chg_req
            return req_pv * scale, req_grid_chg * scale, 0.0, 0.0
        scale = -net / dis_req
        return 0.0, 0.0, req_home_dis * scale, req_grid_dis * scale
    return req_pv, req_grid_chg, req_home_dis, req_grid_dis


# ── §6.8 Battery step function ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _StepLimits:
    """The per-run constants §6.8 reads, hoisted out of the config ONCE before the loop.

    Phase 2's `SimulationConfig` computes every derived quantity on access and deliberately caches
    nothing, so that a Phase-6 form binding cannot leave `soc_max_kwh` or `eta_c` answering for a
    slider value the user has already changed. Its module comment names the correct optimisation:
    the CALLER hoists into locals before the loop, which is safe because the loop body does not
    mutate the config. This object is that hoist, given a name so `battery_step`'s signature does
    not grow eight floats.

    Everything here is already multiplied through by `dt` where §6.8 does so, so the step function
    compares energies against energies and never re-derives a per-interval cap.
    """

    eta_c: float  # AC→storage on the grid charge path
    eta_c_pv: float  # AC→storage on the PV path — eta_c_dc when DC-coupled (§6.8 step 3)
    eta_d: float  # storage→AC on discharge
    soc_min_kwh: float
    soc_max_kwh: float
    chg_cap_kwh: float  # max_charge_kw × dt
    dis_cap_kwh: float  # max_discharge_kw × dt
    imp_cap_kwh: float  # max_import_kw × dt
    exp_cap_kwh: float  # max_export_kw × dt

    @classmethod
    def of(cls, cfg: SimulationConfig, dt_hours: float) -> _StepLimits:
        """Read every derived value off `cfg` exactly once, for a run at `dt_hours` per interval."""
        return cls(
            eta_c=cfg.eta_c,
            # §6.8 step 3: "DC-coupled systems skip one inversion on the PV path." `cfg.coupling`
            # (not `cfg.battery.coupling`) is read because the no-PV forcing to AC lives on the
            # SimulationConfig accessor — see Phase 2's `_force_invariants`.
            eta_c_pv=cfg.eta_c_dc if cfg.coupling == Coupling.DC_HYBRID else cfg.eta_c,
            eta_d=cfg.eta_d,
            soc_min_kwh=cfg.soc_min_kwh,
            soc_max_kwh=cfg.soc_max_kwh,
            chg_cap_kwh=cfg.max_charge_kw * dt_hours,
            dis_cap_kwh=cfg.max_discharge_kw * dt_hours,
            imp_cap_kwh=cfg.max_import_kw * dt_hours,
            exp_cap_kwh=cfg.max_export_kw * dt_hours,
        )


def battery_step(
    soc: float,
    req_pv: float,
    req_grid_chg: float,
    req_home_dis: float,
    req_grid_dis: float,
    load_kwh: float,
    pv_kwh: float,
    lim: _StepLimits,
) -> tuple[float, StepFlows, bool]:
    """§6.8, all seven steps in order. Returns (soc_new, flows, import_limit_exceeded).

    Takes the interval's `load_kwh` and `pv_kwh` directly rather than `(st, i)` — the caller has
    already read them to test for NaN, and passing scalars keeps the step function a pure function
    of numbers, which is what makes it testable one interval at a time.

    `load_kwh` **already includes the standby draw** where the run models one; §6.9 adds it in the
    caller, so nothing here knows standby exists.

    The seven steps, and what each is actually protecting against:

      1. **Resolve simultaneous charge and discharge.** Only reachable under overlapping bands; see
         `net_requests`. Without it, an overlapping configuration would charge and discharge the
         same battery in the same interval and pay the round-trip loss twice on energy that never
         needed to move.
      2. **Clamp charge to rated power, PV FIRST.** The clamp is on the COMBINED request, and PV
         takes priority within it, because PV is free and (DC-coupled) more efficient. Clamping the
         two independently would let a P3 interval charge at up to twice rated power.
      3. **Clamp charge to SoC headroom.** In STORED units, not AC units, so the two charge paths'
         different efficiencies are respected; the scale factor is then applied back to the AC
         figures. Doing it in AC units would overfill a DC-coupled battery by the bonus.
      4. **Clamp discharge to rated power AND available energy.** The available-energy term is
         `(soc − soc_min) × eta_d`: what is left above the floor, converted to what the inverter
         can actually deliver. Forgetting the `eta_d` factor here is the mirror of the step-3 error
         and drives SoC below `soc_min`.
      5. **Compute the grid flows** as the residual of the household balance. `imp` and `exp` are
         the two signs of one net figure, so at most one is ever positive.
      6. **Apply connection limits**, in the spec's order. On import: shed GRID CHARGING first,
         because that is the discretionary part of the draw; if the limit is still exceeded, the
         household load alone exceeds it and there is nothing the battery can do — flag it. On
         export: shed ARBITRAGE EXPORT first (it is a choice), then curtail PV (it is not).
      7. **Integrate**, and assert the SoC stayed inside its window. The assertion is the cheapest
         possible detector for a clamping bug in steps 3 and 4, which otherwise produce entirely
         plausible-looking output.
    """
    # ---- 1. resolve simultaneous charge/discharge ------------------------
    req_pv, req_grid_chg, req_home_dis, req_grid_dis = net_requests(
        req_pv, req_grid_chg, req_home_dis, req_grid_dis
    )

    # ---- 2. clamp charge to rated power, PV first -----------------------
    chg_ac = min(req_pv + req_grid_chg, lim.chg_cap_kwh)
    chg_pv = min(req_pv, chg_ac)
    chg_grid = chg_ac - chg_pv

    # ---- 3. clamp charge to SoC headroom --------------------------------
    #   DC-coupled systems skip one inversion on the PV path (eta_c_pv, hoisted in _StepLimits).
    stored = chg_pv * lim.eta_c_pv + chg_grid * lim.eta_c
    headroom = lim.soc_max_kwh - soc
    if stored > headroom:
        # `stored > headroom >= 0` here, so the division is safe: a positive `stored` is the only
        # way to reach this branch, and headroom cannot be negative unless the SoC already escaped
        # its window — which step 7's assertion of the PREVIOUS interval would have caught.
        scale = headroom / stored
        chg_pv *= scale
        chg_grid *= scale
        stored = headroom

    # ---- 4. clamp discharge to rated power and available energy ---------
    dis_ac = min(
        req_home_dis + req_grid_dis,
        lim.dis_cap_kwh,
        (soc - lim.soc_min_kwh) * lim.eta_d,
    )
    # A SoC that starts BELOW soc_min (a user's initial_soc_pct under the floor — Phase 2 warns
    # rather than blocks) makes the third term negative, and a negative `dis_ac` would run the
    # arithmetic below backwards: `withdrawn` would be negative and step 7 would CHARGE the battery
    # on a discharge request. Floored at 0, which is the physically obvious reading of "there is
    # nothing available to discharge" and matches how the SoC then simply stays put.
    dis_ac = max(0.0, dis_ac)
    dis_home = min(req_home_dis, dis_ac)
    dis_grid = dis_ac - dis_home
    withdrawn = dis_ac / lim.eta_d if lim.eta_d > 0.0 else 0.0

    # ---- 5. resulting grid flows ----------------------------------------
    #   load here already includes standby draw (added in the caller).
    net_flow = load_kwh + chg_pv + chg_grid - pv_kwh - dis_ac
    imp = max(0.0, net_flow)
    exp = max(0.0, -net_flow)

    # ---- 6. connection limits -------------------------------------------
    curtailed = 0.0  # §6.8's pseudocode leaves this unbound on the non-curtailing path
    import_limit_exceeded = False
    if imp > lim.imp_cap_kwh:  # shed grid charging first
        excess = imp - lim.imp_cap_kwh
        cut = min(chg_grid, excess)
        chg_grid -= cut
        stored -= cut * lim.eta_c
        imp -= cut
        if imp > lim.imp_cap_kwh:
            # Household load alone exceeds the connection. Nothing the battery can do about it, and
            # the run is not stopped: the data says the house drew this much, and refusing to
            # report it would be worse than reporting it with a flag. Usually a mis-entered fuse
            # rating rather than a real overload.
            import_limit_exceeded = True

    if exp > lim.exp_cap_kwh:  # shed arbitrage export, then curtail PV
        excess = exp - lim.exp_cap_kwh
        cut = min(dis_grid, excess)
        dis_grid -= cut
        dis_ac -= cut
        withdrawn -= cut / lim.eta_d if lim.eta_d > 0.0 else 0.0
        exp -= cut
        if exp > lim.exp_cap_kwh:
            # What remains is PV that cannot be exported and cannot be stored — generated and
            # discarded. It is tracked because it is the one term that makes the §6.14 fixture 3
            # conservation identity close, and because §7.2 item 1 makes the same clamp apply to
            # the BASELINE run: a battery must not be credited with avoiding a constraint the
            # baseline never faced.
            curtailed = exp - lim.exp_cap_kwh
            exp = lim.exp_cap_kwh

    # ---- 7. integrate ----------------------------------------------------
    soc_new = soc + stored - withdrawn
    assert (
        lim.soc_min_kwh - SOC_COMPARE_EPS_KWH <= soc_new <= lim.soc_max_kwh + SOC_COMPARE_EPS_KWH
    ), f"SoC {soc_new} escaped [{lim.soc_min_kwh}, {lim.soc_max_kwh}]"

    return (
        soc_new,
        StepFlows(imp, exp, chg_pv, chg_grid, dis_home, dis_grid, stored, withdrawn, curtailed),
        import_limit_exceeded,
    )


# ── §6.9 Main simulation loop ────────────────────────────────────────────────────────────────


class _View:
    """§6.9's `st = frame.view()` — the frame's arrays with `load` REBOUND to include standby.

    **This exists to make it impossible to write standby into the frame.** `frame.load` and
    `frame.pv` are the same array objects `reconcile_grid` produced, shared with the data-summary
    band (`app/summary_view.py`) and the panel-③ results view; `frame.load += standby` would change
    numbers already published elsewhere in the app, silently and permanently for the life of the
    process. `frame.load + standby_kwh` allocates a NEW array and binds it here, leaving the
    frame's own array untouched. Nothing in this module ever writes through to a frame array.

    `p_export_net` is the §6.10 cost-model array `discharge_request`'s economic-guard branch reads.
    It is None here because no cost model exists yet; the guard cannot fire (Phase 2 forces the
    flag off without `simulate_cost`), and None rather than an invented zero array means a future
    increment that forgets to populate it fails loudly rather than suppressing every grid discharge.
    """

    __slots__ = ("load", "pv", "spot", "dt", "p_export_net")

    def __init__(self, frame: SimulationFrame, standby_kwh: float) -> None:
        # REBIND, never mutate — see the class docstring. `+ 0.0` still allocates a copy, so even a
        # standby-free run cannot alias the frame's array into something a caller might later write.
        self.load = frame.load + standby_kwh
        self.pv = frame.pv
        self.spot = frame.spot
        self.dt = frame.dt_hours
        self.p_export_net: np.ndarray | None = None


def simulate(
    frame: SimulationFrame,
    cfg: SimulationConfig,
    include_standby: bool = True,
    should_cancel: Callable[[], bool] | None = None,
) -> Flows:
    """§6.9's sequential loop — runs B (`include_standby=False`) and C (True).

    Walks the frame interval by interval: ask both policies what they want, hand both requests to
    `battery_step`, record what actually happened, carry the SoC to the next interval. Sequential
    by nature — the SoC of interval `i` depends on every interval before it — which is why this is
    the one part of the pipeline that is not vectorisable.

    **Standby exists only with a battery** (§6.9), which is what makes run B meaningful: B and C
    differ in exactly this term, so `C − B` isolates the standby draw exactly rather than
    estimating it. It is added to the LOAD, not subtracted from the battery, because an inverter's
    parasitic draw is served from wherever the house's energy comes from in that interval — PV,
    battery or grid — and putting it on the load side gets that routing for free.

    **NaN load or pv → the interval is skipped and the SoC is carried forward.** §7.3 check 3
    excludes gaps from sums; the battery does not move energy in an interval whose inputs are
    unknown, and inventing a dispatch for it would put fabricated kWh into the headline figure.
    Note the SoC is carried, not reset: the battery physically still held its charge across the
    sensor outage.

    **The starting SoC is clamped into the operating window before the first interval.** Phase 2
    WARNS about an `initial_soc_pct` outside `[min, max]` but does not block it, and its warning
    says the value "will be clamped at the first step" — so something has to do the clamping, and
    §6.8's steps do not. A SoC below `soc_min` cannot be raised by them (step 4 has nothing to
    discharge and step 3 charges only toward `soc_max`), so it would sit outside the window and
    trip step 7's bound assertion on interval 0, turning a configuration the spec explicitly allows
    into a crash. Clamping here, once, before the loop, is where the spec's own wording puts it,
    and `soc_start` records the clamped value so the §6.11 drift figure `soc_end − soc_start`
    measures against the SoC the simulation actually began from rather than an unreachable one.

    **Cancellation is an injectable hook.** §6.9 writes a module-level `cancel_event`, which
    presupposes the run-orchestration layer of §3.3/§5.3 — and there is none yet. Rather than
    invent a threading model here, `should_cancel` is an optional zero-argument callable polled
    every `CANCEL_CHECK_INTERVAL` intervals; `None` (the default) skips the check entirely, so a
    pure-domain caller pays nothing. Phase 6 passes `run_event.is_set` and gets §6.9's semantics.

    Every derived config value is hoisted into `_StepLimits` before the loop — see Phase 2's module
    comment on why the hoist belongs to the caller and not to the config object.
    """
    n = frame.intervals
    # Clamped into the operating window before anything runs — see the docstring. Note this reads
    # the SoC bounds off `cfg` once, before `_StepLimits` hoists them, which is the same values.
    soc = min(max(cfg.initial_soc_kwh, cfg.soc_min_kwh), cfg.soc_max_kwh)
    out = Flows.empty(n, soc_start=soc)

    standby_kwh = cfg.standby_kw * frame.dt_hours if include_standby else 0.0

    st = _View(frame, standby_kwh)  # st.load = frame.load + standby_kwh — REBINDS, never mutates
    lim = _StepLimits.of(cfg, frame.dt_hours)
    charge_policy = cfg.policy.charge_policy
    discharge_policy = cfg.policy.discharge_policy

    for i in range(n):
        if should_cancel is not None and i % CANCEL_CHECK_INTERVAL == 0 and should_cancel():
            raise Cancelled

        if math.isnan(st.load[i]) or math.isnan(st.pv[i]):
            out.mark_gap(i, soc)  # gaps excluded, SoC carried forward
            continue

        rp, rg = charge_request(charge_policy, i, st, cfg)
        dh, dg = discharge_request(discharge_policy, i, st, cfg)
        soc, f, over_import = battery_step(soc, rp, rg, dh, dg, st.load[i], st.pv[i], lim)
        out.set(i, f)
        out.soc[i] = soc
        if over_import:
            out.import_limit_exceeded.append(i)

    return out


def simulate_baseline(frame: SimulationFrame, cfg: SimulationConfig) -> Flows:
    """§6.9's run A — [vectorisable] no battery, no standby. **The export limit still applies.**

    The household as it would have been without the battery: whatever PV does not cover is
    imported, whatever it exceeds is exported.

        net = load − pv;   imp = max(net, 0);   exp = max(−net, 0)

    **§7.2 item 1, the thing this function exists to get right.** If an export limit is configured,
    run A must apply it too, curtailing the PV it cannot export — exactly as §6.8 step 6 does for
    the battery run. Skipping it here is easy to do and produces a completely plausible result in
    which the baseline exports freely past a cap the battery scenario respects; every kWh of that
    phantom export becomes kWh the battery appears to have rescued, and the headline saving is
    inflated by a constraint the baseline never actually faced. There is no arbitrage export to
    shed first in a battery-free run, so only the second half of step 6 applies.

    Standby is absent by definition: it is the battery's own parasitic draw and there is no battery
    (§6.9). The battery-side arrays are therefore all zero rather than NaN — zero is a true
    statement about a run in which the battery provably did nothing, unlike a gap interval, where
    it is an assertion about an interval nobody evaluated.

    Gaps are propagated: an interval whose `load` or `pv` is NaN comes out NaN in `imp`/`exp` (the
    arithmetic does that on its own) and is marked in `gap`, so run A and run C exclude the same
    intervals from their sums and `saved_kwh = A.imp − C.imp` compares like with like. Without
    this, a NaN interval would contribute to one run's total and not the other's.

    `cfg` is read only for the export cap. It is not optional: the cap is a property of the
    household's connection, not of the battery.
    """
    n = frame.intervals
    out = Flows.empty(n, soc_start=0.0)

    net = frame.load - frame.pv  # allocates; the frame's arrays are never written to
    imp = np.maximum(net, 0.0)
    exp = np.maximum(-net, 0.0)

    # §7.2 item 1 — the same cap §6.8 step 6 applies, and the same curtailment accounting.
    exp_cap = cfg.max_export_kw * frame.dt_hours
    curtailed = np.maximum(exp - exp_cap, 0.0)
    # NaN-safe: `np.maximum(nan, 0.0)` is nan, and `np.minimum(nan, cap)` is nan, so a gap interval
    # stays NaN through the cap rather than being silently clamped to it.
    exp = np.minimum(exp, exp_cap)

    gap = np.isnan(frame.load) | np.isnan(frame.pv)
    zeros = np.zeros(n, dtype=np.float64)
    out.imp = np.where(gap, np.nan, imp)
    out.exp = np.where(gap, np.nan, exp)
    out.curtailed = np.where(gap, np.nan, curtailed)
    out.chg_pv = np.where(gap, np.nan, zeros)
    out.chg_grid = np.where(gap, np.nan, zeros)
    out.dis_home = np.where(gap, np.nan, zeros)
    out.dis_grid = np.where(gap, np.nan, zeros)
    out.stored = np.where(gap, np.nan, zeros)
    out.withdrawn = np.where(gap, np.nan, zeros)
    out.soc = zeros.copy()
    out.gap = gap
    return out


# ── The run harness (§6.9's table, runs A / B / C) ───────────────────────────────────────────


@dataclass(frozen=True)
class RunSet:
    """The three flow runs §6.9's table marks "always" — A, B and C.

        a  baseline: no battery, no standby. The denominator of every saving figure (§6.11:
           `saved_kwh = A.imp.sum() − C.imp.sum()`, and `saved_pct` divides by the SIMULATED
           baseline, never by observed import).
        b  battery, NO standby. Exists solely so standby is an exact run difference rather than an
           estimate: §6.9 states `standby_cost ≡ cost(C) − cost(B)` exactly, and without a cost
           model the same difference is reported as `energy.standby_kwh`. It is not a scenario
           anyone would run for its own sake.
        c  battery + standby — THE headline result.

    **Runs D and E (perfect foresight, §6.12) are deliberately NOT here, and that is a latency
    decision rather than a layering one.** They exist — `app/domain/benchmark.py` builds both, D on
    the energy objective and E on the cost one — but each is ~4.6 s on a year of hourly data at
    appendix A's grids against ~0.12 s for A/B/C together, and §6.9's table marks D "always" only
    in the sense that the energy benchmark is always DEFINED, not that every page view must pay for
    it. Putting them in `run_all` would make the two DPs unavoidable for every caller that wanted a
    kWh figure. `app/results_view.py` therefore calls `energy_benchmark` separately behind
    `with_benchmark`, which only `POST /results/benchmark` sets, and a cost block would be gated the
    same way (and additionally on `cfg.simulate_cost`, per §6.12's table).

    A `None` field for each would be worse than their absence: it would invite a caller to treat
    "not computed on this request" as "not applicable to this run".
    """

    a: Flows
    b: Flows
    c: Flows

    @property
    def standby_kwh(self) -> float:
        """The standby draw over the window, as the exact run difference §6.9 defines it.

        `C.imp − B.imp` rather than `standby_w × hours`: the two differ whenever standby was served
        by PV or by the battery instead of by the grid, and the run difference is the one that
        matches what the meter would have seen. Computed here, once, so Phase 4 does not re-derive
        it from the parameter and quietly disagree with the flows.
        """
        return float(np.nansum(self.c.imp) - np.nansum(self.b.imp))


def run_all(
    frame: SimulationFrame,
    cfg: SimulationConfig,
    should_cancel: Callable[[], bool] | None = None,
) -> RunSet:
    """Runs A, B and C over one frame and config (§6.9's table).

    B and C are the same `simulate` call differing only in `include_standby`, which is precisely
    what makes their difference the standby term and nothing else — same policies, same SoC
    trajectory rules, same clamps, same seed state.

    Runs D and E are not built here; see `RunSet` for why, and `app/domain/benchmark.py` for where.
    """
    return RunSet(
        a=simulate_baseline(frame, cfg),
        b=simulate(frame, cfg, include_standby=False, should_cancel=should_cancel),
        c=simulate(frame, cfg, include_standby=True, should_cancel=should_cancel),
    )
