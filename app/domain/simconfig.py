"""The simulation configuration — the `cfg` of specs §6.6–§6.9, with its derived quantities.

This is the per-run PARAMETER SET the user configures in panel ② (§2.3, §2.5): the battery
being simulated, the grid connection it sits behind, the charge/discharge policies, and the
installation topology. It is pure data plus the quantities derived from it, plus validation.

**Not to be confused with `app/config.py`.** That module is the APPLICATION's runtime config —
data directory, feature-interest endpoint, installation id — one instance per process, read from
disk at startup. This one is a per-run simulation input: many can exist at once, it changes every
time the user moves a slider, and none of it is machine- or install-scoped. Two different things
that both want the word "config"; they stay in separate modules and neither imports the other.

**No persistence and no UI wiring here.** Loading/storing a parameter set and rendering these
fields (and their validation issues) into the panel-② form are a later increment. What this module
owes those consumers is a shape they can bind to and a validation result they can key per-field.

## The grouping

Five dataclasses composed into one `SimulationConfig`:

    BatteryConfig    the battery being simulated: capacity, SoC window, powers, efficiency,
                     standby, coupling, initial SoC. Plus the derived SoC bounds in kWh and the
                     efficiency split.
    GridConfig       the connection: phases, fuse, and the import/export power caps derived from
                     them. Separate from the battery because a fuse constrains the whole house,
                     not the battery — §6.8 step 6 applies these caps to the NET flow.
    PolicyConfig     charge policy + band [A,B], discharge policy + band [C,D], allow_grid_export,
                     economic_guard. Charge and discharge share one object rather than getting one
                     each because check 12 (§7.3) is a check ACROSS the two bands; splitting them
                     would put the only cross-cutting validation in neither object.
    TopologyConfig   pv_coupling, battery_phases, approximated (§2.5, §4.5).
    PricingConfig    the contract and its rates: contract type, supplier markup, energy tax,
                     VAT, feed-in α/β and floor mode, terugleverkosten, the dal window,
                     degradation (§2.3's Pricing box, §6.5). Inert — but RETAINED, see below —
                     when `simulate_cost` is false.

The grouping mirrors the panel-② form boxes one-to-one, so an issue keyed `battery.min_soc_pct`
names both the field and the box the user has to open to fix it.

`has_pv` and `simulate_cost` sit on `SimulationConfig` itself, not in any group: each of them
conditions SEVERAL groups (has_pv → topology.pv_coupling and battery.coupling; simulate_cost →
policy.economic_guard and the whole of `PricingConfig`), so neither belongs to one box.

## Mutability: derived quantities are PROPERTIES, never cached fields

Every derived quantity here — `soc_min_kwh`, `soc_max_kwh`, `initial_soc_kwh`, `eta_c`, `eta_d`,
`eta_c_dc`, `max_import_kw`, `effective_max_export_kw` — is a `@property` computed on access.
None of them is stored.

That is a deliberate reversal of an earlier design that computed them once in `__post_init__` and
stored them in `init=False` fields. Phase 6 binds a mutable form to these objects: the user moves
the capacity slider, the code does `cfg.battery.usable_capacity_kwh = 20.0`, and with cached
fields `cfg.soc_max_kwh` silently kept answering 10.0. A stale `eta_c` or `soc_max_kwh` corrupts
every number §6.8 produces, with no error raised anywhere and nothing in a result to look wrong.
Nothing cached means nothing can go stale, which is the only version of this that is safe under
the binding model Phase 6 needs.

**Do not "optimise" these back into cached fields.** The cost is a `sqrt` and a multiply per
access, against a loop that runs once per interval — and §6.9's `simulate()` reads `cfg.*` a
handful of times per interval at most. If that ever measures as hot, the fix is for the CALLER to
hoist `eta_c`, `eta_d`, `eta_c_dc`, `soc_min_kwh`, `soc_max_kwh`, `max_import_kw`,
`max_export_kw` into locals before the loop — the loop body does not mutate the config, so
hoisting there is safe in a way that caching on the object is not. Frozen dataclasses would also
solve staleness, but Phase 6 needs to mutate a bound config in place; and a `__setattr__` hook
that re-derives is invisible magic that fails the moment someone assigns to a nested object.

## The efficiency split — the thing most easily got wrong

The user enters ONE number, an AC-to-AC round-trip efficiency (90% by default). §6.8 fixes the
convention: `eta_c = eta_d = sqrt(roundtrip_efficiency)`, i.e. the loss is split geometrically,
half on the way in and half on the way out. On the DC-coupled PV charging path one inversion is
skipped, so `eta_c_dc = sqrt(roundtrip_efficiency + roundtrip_dc_bonus)` and it applies to
`chg_pv` ONLY (§6.8 step 3).

Why the sqrt and not something simpler: §6.14 fixture 2 pins that one full charge + discharge of a
10 kWh battery at 90% RTE returns 9.0 kWh AC — a round-trip loss of exactly 1.0 kWh. The sqrt split
gives `10 × sqrt(0.9) = 9.4868` stored, then `9.4868 × sqrt(0.9) = 9.0` back. Putting the whole
loss on the charge side (eta_c = 0.9, eta_d = 1.0) also returns 9.0 but reports a wrong SoC in
between; splitting it linearly (0.95/0.95) returns 9.025, and applying 0.9 on both sides returns
8.1 — a 1.9 kWh loss. Only the geometric split is both symmetric and exact, and `eta_c * eta_d ==
roundtrip_efficiency` is the identity the fixture rests on.

## Construction never raises — and that is load-bearing

An invalid parameter set is a representable object on purpose: the form has to be able to hold
what the user typed in order to show them what is wrong with it. That covers more than an
out-of-range number. A Phase-6 form field the user left empty arrives as `None`; a text input
arrives as a string; a division upstream can hand over `nan` or `inf`. None of those may raise on
construction OR on reading a derived property, because the object that would have carried the
error message is the one that failed to exist.

`_finite()` is the single funnel: it turns anything that is not a finite real number into `None`,
the derived properties treat `None` as 0.0 (a meaningless number, for a meaningless input), and
`validate()` reports it as a blocking, field-keyed issue. The same reasoning is why `math.sqrt`'s
argument is floored at 0 rather than letting a negative efficiency raise `ValueError`.

## Validation (specs §7.3 checks 11 and 12)

`validate()` returns a `ValidationResult` — it does not raise, and construction does not raise
either.

    check 11 BLOCKS   soc_min < soc_max, powers > 0, rte_min < RTE <= 1.0.
    check 12 WARNS    charge band ∩ discharge band != ∅. §6.7 nets overlapping requests at
                      runtime, so an overlap is a configuration worth flagging, not a broken one.

Two settings are FORCED rather than validated, and forced at THREE points, because correctness
must not depend on the caller having called `validate()`:

    economic_guard  → False whenever simulate_cost is False. It reads `p_export_net`, a cost-model
                      output that does not exist in an energy-only run (§6.7, appendix A). Forced
                      ON READ, through a property, so a consumer that never validates still cannot
                      observe it True. The user's raw choice stays stored (`economic_guard_stored`)
                      so Phase 6 can round-trip the form and turning cost simulation back on
                      restores it — appendix A is explicit that cost-only parameters are retained
                      rather than reset.
    pv_coupling     → None, and battery coupling → AC, whenever has_pv is False (§2.5). Likewise
                      forced on read, over a stored raw value, for the same round-trip reason.

`__post_init__` and `validate()` additionally normalise the stored values (`_force_invariants`),
so a config that has passed the run precondition also LOOKS right in a debugger or a persisted
file, not merely through its accessors.

## The cost parameters are RETAINED, never forced — the opposite of `economic_guard`

`PricingConfig` carries the §6.5 contract parameters. Appendix A lists all of them as inert when
`simulate_cost` is false and says in as many words that they are "retained at their stored values
so that enabling cost simulation later restores the user's configuration rather than resetting
it". So nothing in `_force_invariants` touches this group, and there is no forcing property over
any of its fields.

That is deliberately unlike `economic_guard`, which appendix A singles out as "additionally
FORCED off rather than merely hidden". The distinction is about what reads the value. A DISPATCH
input that would make §6.7 read a cost array that does not exist has to be neutralised whether or
not anyone validated; a PRICE that is simply never consulted in an energy-only run — because
§6.5 states the whole pricing package is skipped outright, not called with neutral parameters —
changes no number by being stored. Clearing it would only lose the user's answer.

`validate()` follows the same line: the pricing checks run ONLY when `simulate_cost` is true.
Panel ② hides the entire Pricing box in energy-only mode (§2.3: "the whole Pricing box above,
Advanced included, is hidden when cost simulation is off"), so blocking a run on a field the user
was never shown would be an error with no input to attach itself to.

## What is deliberately NOT here

The §6.5 machinery that CONSUMES the pricing parameters — `bare_supply_price`, `import_price`,
`export_price_net`, the period feed-in floor — and the §6.10 cost accounting. This module holds
the parameter set and its validation; the pricing module is a later increment.

Three `PricingConfig` fields are vocabulary rather than implementation: `Contract.FIXED` and
`Contract.VARIABLE`, and `TlkMode.TIERED`. §6.5 defines all three and only the DYNAMIC / FLAT
paths are built. The enums carry every value so that the stored parameter set, the radio labels
and the eventual dispatch on contract type all name the same things; a `rate_schedule` for
VARIABLE and a `tlk_tiers` table for TIERED are not modelled and are absent rather than stubbed.

Main items:
    ChargePolicy / DischargePolicy / Coupling / PvCoupling / BatteryPhases   the enums.
    Contract / FeedinFloorMode / TlkMode              the §6.5 pricing vocabulary.
    RTE_MIN, NOMINAL_PHASE_VOLTAGE_V                the appendix-A / E-A constants.
    _finite()                                       the non-raising numeric funnel.
    connection_capacity_kw()                        EXACT phases × A × 230 V / 1000, for physics.
    connection_capacity_kw_display()                the rounded figure, for panel ② only.
    BatteryConfig, GridConfig, PolicyConfig, TopologyConfig, PricingConfig, SimulationConfig
                                                     the parameter set.
    ConfigIssue, ValidationResult                    field-keyed validation output.
    SimulationConfig.validate()                      §7.3 checks 11 and 12, plus §6.5's ranges.
    SimulationConfig.offerable_charge_policies() / .offerable_discharge_policies()
                                                     UI gating only — NOT dispatch semantics.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

# ── Constants from appendix A / background E-A ───────────────────────────────────────────────

# appendix A `rte_min`: "Lower bound on accepted round-trip efficiency; check 11. The 1.0 upper
# bound is physics, not configurable." So this one is a parameter and 1.0 is not — hence a named
# constant here and a bare literal at the comparison site.
RTE_MIN = 0.5

# The nominal single-phase voltage of the Dutch LV network. Not in appendix A as such; it is the
# constant INFERRED from appendix A's "→ 5.75 kW (1×25 A) / 17.3 kW (3×25 A)" and background E-A's
# connection-capacity table, both of which come out exactly as `phases × amps × 230 V`. The figure
# 230 appears nowhere in specs/ — it is pinned by those two published data points and nothing else.
# Named rather than inlined so the derivation reads as the physics it is.
NOMINAL_PHASE_VOLTAGE_V = 230.0


class ChargePolicy(str, Enum):
    """§6.6. P1 solar surplus only, P2 grid-in-band only, P3 both."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class DischargePolicy(str, Enum):
    """§6.7. D1 household deficit only, D2 in-band at full power, D3 both."""

    D1 = "D1"
    D2 = "D2"
    D3 = "D3"


class Coupling(str, Enum):
    """§6.8 `cfg.coupling` — which charge efficiency the PV path uses."""

    AC = "ac"
    DC_HYBRID = "dc_hybrid"


class PvCoupling(str, Enum):
    """§2.5(a) — the illustrated selector. Mirrors `Coupling`; see `TopologyConfig`."""

    DC_HYBRID = "dc_hybrid"
    AC = "ac"


class BatteryPhases(str, Enum):
    """§2.5(b) — how the battery inverter sits across L1/L2/L3. Only THREE_PHASE modelled in v1."""

    ONE_PHASE = "one_phase"
    THREE_PHASE = "three_phase"
    THREE_TIMES_ONE_PHASE = "three_times_one_phase"


class Contract(str, Enum):
    """§6.5's three contract types — the vocabulary of the whole pricing package.

    §6.5: "DYNAMIC, FIXED and VARIABLE are the vocabulary everywhere in this package, radio
    labels and result fields included: the user-facing name of a contract type is the enum value
    lower-cased, with no country qualifier." Hence the lowercase values, and hence all three
    being present even though only the DYNAMIC rate source is built: the enum is what panel ②'s
    radio group, the persisted parameter set and the eventual `bare_supply_price` dispatch all
    name their cases from, so a missing member would mean three places inventing their own.

    FIXED takes its rates from `PricingConfig.rate_normaal` / `rate_dal`. VARIABLE needs a dated
    rate SCHEDULE (§6.5 `lookup_schedule`), which is a table rather than a pair of numbers and is
    not modelled here.
    """

    DYNAMIC = "dynamic"
    FIXED = "fixed"
    VARIABLE = "variable"


class FeedinFloorMode(str, Enum):
    """§6.5 — over what period the statutory "compensation may not be negative" floor is assessed.

        MONTHLY       the period the statute names. Artikel 2.34, zevende lid Energiewet says
                      "gemiddeld gewogen over een periode van een maand" — weighted-averaged over
                      a period of a month — so individual negative-price intervals do not breach
                      the floor as long as the month's aggregate is non-negative. Appendix A's
                      default. Note the statute says neither *ten minste* nor *precies* a month;
                      whether a longer assessment period is lawful is an inference from its
                      silence and is unverified in both directions (§6.5 point 3, §8.14). Do not
                      restate this as "at least one month" — §6.5 explicitly disclaims that
                      phrasing, and a settled-sounding legal claim here propagates into UI copy.
        PER_INTERVAL  the v1.1 behaviour, "retained for reproducibility. Stricter than the law."
                      §6.5 notes it is also a shape a supplier could genuinely offer.

    The two are NOT a rounding difference: per-interval clamping is always ≥ the period aggregate,
    because clamping discards each negative term while the aggregate lets them offset positives.

    The assessment PERIOD (`feedin_floor_period`, appendix A "calendar month") is a separate
    parameter and is not modelled here — §6.5 leaves whether longer periods are lawful open
    (§8.14), and nothing in this module consumes a period yet.
    """

    MONTHLY = "monthly"
    PER_INTERVAL = "per_interval"


class TlkMode(str, Enum):
    """§6.5 — how terugleverkosten are charged.

        FLAT    a rate per fed-in kWh, `tlk_eur_per_kwh`. §6.5: from 2027 these must be expressed
                per fed-in kWh, so FLAT "is the default and the expected shape", and background
                E5.2 makes it close to the only clearly compliant one.
        TIERED  a staffel on ANNUALISED export. Retained as vocabulary because volume is plainly
                related to feed-in and so a staffel remains arguable, but not built: it needs a
                tier table, an annualisation, and the `min_tlk_tiering_days` fallback to FLAT.
    """

    FLAT = "flat"
    TIERED = "tiered"


# ── The non-raising numeric funnel ───────────────────────────────────────────────────────────


def _finite(value: object) -> float | None:
    """`value` as a finite float, or None if it is not a real finite number.

    The single place any user-supplied number enters the derived arithmetic. Phase 6 binds a web
    form to these dataclasses, so a field can arrive as `None` (the user cleared it), as a string
    (an un-coerced input), or as `nan`/`inf` (an upstream division). None of those may raise —
    see the module comment — so they all funnel to None here and the caller substitutes 0.0.

    `bool` is rejected even though it is an `int` subclass: `phases=True` would otherwise derive a
    perfectly plausible 5.75 kW single-phase capacity from what is almost certainly a wiring
    mistake in a form binding, and `validate()`'s `phases not in (1, 3)` would let it through
    (True == 1). Rejecting it here makes the derivation and the check agree on what a phase count
    is, which is the point.

    Strings are rejected rather than parsed. Parsing is the form layer's job and it has to happen
    before the value is stored, or the object's declared types stop meaning anything; accepting
    `"3"` here would leave `GridConfig(phases="3")` deriving a number while every other reader of
    `.phases` sees a str.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except OverflowError:
        # A Python int is unbounded; a float is not. `int("9" * 400)` is a perfectly ordinary
        # value for this funnel to be handed (the form layer parses digit strings with `int()`
        # first, and succeeds up to Python's 4300-digit limit), and `float()` on it raises
        # rather than returning inf. Without this the module's central guarantee — construction
        # never raises, any unusable value becomes a field error — would have a hole in it that
        # an ordinary long numeric input falls straight through.
        return None
    if not math.isfinite(f):  # nan and ±inf
        return None
    return f


def _num(value: object) -> float:
    """`_finite(value)` with a 0.0 substitute — a meaningless number for a meaningless input.

    Zero rather than nan so a derived quantity stays comparable and printable while the config is
    in its broken state; `validate()` is what reports it, and it reports on the STORED value, not
    on this substitute, so the user sees back exactly what they typed.
    """
    f = _finite(value)
    return 0.0 if f is None else f


# ── Validation output ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConfigIssue:
    """One validation finding, keyed to the field that caused it.

        field    dotted path into `SimulationConfig` — "battery.roundtrip_efficiency",
                 "policy.band_b". This is what the form binds an inline error to, which is why it
                 is a path and not a prose label: the renderer must be able to find the input.
        code     a stable machine identifier ("rte_out_of_range"). Tests and the renderer key on
                 this; `message` is free to be reworded or translated without breaking either.
        message  English, developer-facing. NOT the user-facing string: panel ② will phrase these
                 in the user's language keyed by `code`. Kept here so a failing check is legible
                 in a traceback or a test report without a lookup table.
    """

    field: str
    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of §7.3 checks 11 and 12 over one `SimulationConfig`.

    Errors and warnings are kept in SEPARATE lists rather than one list with a severity flag,
    because the two have different consequences and the caller must not be able to conflate them
    by forgetting to filter: check 11 blocks the run, check 12 does not. `blocking` is the single
    question the run precondition asks.
    """

    errors: tuple[ConfigIssue, ...] = ()
    warnings: tuple[ConfigIssue, ...] = ()

    @property
    def blocking(self) -> bool:
        """True when the configuration must not be simulated — i.e. check 11 found something."""
        return bool(self.errors)

    def fields_with_errors(self) -> set[str]:
        """The dotted paths carrying a blocking error, for the form to mark as invalid."""
        return {issue.field for issue in self.errors}


# ── The parameter groups ─────────────────────────────────────────────────────────────────────


@dataclass
class BatteryConfig:
    """The simulated battery (§2.3 Battery box; consumed by §6.8 `battery_step`).

    Defaults are appendix A. Fields:

        usable_capacity_kwh   the full 0–100% window the battery reports. §6.8 is explicit that
                      this is USABLE capacity, not nameplate, and that min/max SoC are additional
                      user-imposed limits INSIDE it — so 10 kWh usable with min 10% / max 100%
                      gives an operating window of 9 kWh, not 8.
        min_soc_pct / max_soc_pct   the user-imposed operating limits, as percentages of usable.
        max_charge_kw / max_discharge_kw   rated AC power, clamped in §6.8 steps 2 and 4.
        roundtrip_efficiency  ONE AC-to-AC figure. See the module comment for the split.
        roundtrip_dc_bonus    added to the round-trip before the sqrt on the DC PV path (§6.8).
        standby_w             continuous parasitic draw, added to the load by the §6.9 caller —
                      not by `battery_step`, which is why nothing here divides it by anything.
        initial_soc_pct       SoC at t=0, as a percentage of usable capacity.
        coupling              which of eta_c / eta_c_dc the PV charge path uses (§6.8 step 3).
                      Stored raw; `SimulationConfig.coupling` is what §6.8 must read, because the
                      no-PV forcing lives there (§2.5) — see `SimulationConfig._force_invariants`.

    `soc_min_kwh`, `soc_max_kwh`, `initial_soc_kwh`, `eta_c`, `eta_d` and `eta_c_dc` are
    PROPERTIES, recomputed on every access. See the module comment for why nothing is cached.
    """

    usable_capacity_kwh: float = 10.0
    min_soc_pct: float = 10.0
    max_soc_pct: float = 100.0
    max_charge_kw: float = 5.0
    max_discharge_kw: float = 5.0
    roundtrip_efficiency: float = 0.90
    roundtrip_dc_bonus: float = 0.04
    standby_w: float = 30.0
    initial_soc_pct: float = 50.0
    coupling: Coupling = Coupling.AC

    # ── Derived (§6.8) ──────────────────────────────────────────────────────────────────────
    # soc_min_kwh = usable_capacity * min_soc_pct/100, likewise max. The percentages are of
    # USABLE capacity, not of nameplate and not of the min..max window.

    @property
    def soc_min_kwh(self) -> float:
        return _num(self.usable_capacity_kwh) * _num(self.min_soc_pct) / 100.0

    @property
    def soc_max_kwh(self) -> float:
        return _num(self.usable_capacity_kwh) * _num(self.max_soc_pct) / 100.0

    @property
    def initial_soc_kwh(self) -> float:
        return _num(self.usable_capacity_kwh) * _num(self.initial_soc_pct) / 100.0

    @property
    def eta_c(self) -> float:
        """`sqrt(roundtrip_efficiency)` — the geometric split (§6.8); see the module comment.

        Floored at 0 before the sqrt. A negative or non-numeric round-trip efficiency must not
        raise here: construction and every read have to succeed for an invalid parameter set so
        `validate()` can report on it and the form can render the user's bad value back with the
        error attached. The resulting eta is meaningless, but so is the configuration, and check
        11 says so.
        """
        return math.sqrt(max(0.0, _num(self.roundtrip_efficiency)))

    @property
    def eta_d(self) -> float:
        """Equal to `eta_c` by the §6.8 convention — half the loss each way, not all on one side."""
        return self.eta_c

    @property
    def eta_c_dc(self) -> float:
        """`sqrt(roundtrip + dc_bonus)` — the DC PV path skips one inversion (§6.8 step 3).

        Floored at 0 for the same reason as `eta_c`; NOT capped at 1, because a user whose
        installer gave them a 0.97 round-trip and the default +0.04 bonus would get
        `eta_c_dc = sqrt(1.01) > 1` — physically wrong, but it is the user's two numbers combining,
        and check 11's bound is on the round-trip they entered, not on this derivative.
        `validate()` warns about it rather than silently clamping a number the user can see.
        """
        rte = max(0.0, _num(self.roundtrip_efficiency))
        return math.sqrt(max(0.0, rte + _num(self.roundtrip_dc_bonus)))


@dataclass
class GridConfig:
    """The grid connection (§2.3 Grid connection box; consumed by §6.8 step 6).

        phases        1 or 3. Appendix A default 1.
        fuse_a        the main fuse rating in amps. Appendix A default 25.
        max_import_kw_override   None to use the derived value, or a number the user typed into
                      the `[ override ]` control (§2.3). Kept distinct from the derived value so
                      changing the fuse still moves the cap for everyone who did not override.
        max_export_kw None means "same as import" — appendix A's literal default is "= import",
                      not a number. Modelled as None rather than a copied float so that the
                      distinction between "the user chose 5.75 kW" and "the user chose to track
                      import" survives a subsequent fuse change.

    Derived, as properties: `max_import_kw` (EXACT `phases × fuse × 230 V / 1000`, or the
    override) and `effective_max_export_kw` (`max_export_kw` or, when None, `max_import_kw`).
    Panel ② prints `max_import_kw_display`, which is the same number rounded — see
    `connection_capacity_kw_display`.
    """

    phases: int = 1
    fuse_a: float = 25.0
    max_import_kw_override: float | None = None
    max_export_kw: float | None = None

    @property
    def max_import_kw(self) -> float:
        """The cap §6.8 step 6 compares against — EXACT, never the rounded display figure."""
        override = _finite(self.max_import_kw_override)
        if override is not None:
            return override
        # Note `_finite`, not `is not None`: an override that is present but unusable (a string, a
        # nan) falls through to the fuse derivation rather than to 0.0, so a broken override field
        # does not silently turn the house into a 0 kW connection. `validate()` reports it against
        # `grid.max_import_kw_override`.
        return connection_capacity_kw(self.phases, self.fuse_a)

    @property
    def max_import_kw_display(self) -> float:
        """What panel ② prints next to the fuse control — rounded. NOT used in any computation."""
        override = _finite(self.max_import_kw_override)
        if override is not None:
            return override
        return connection_capacity_kw_display(self.phases, self.fuse_a)

    @property
    def effective_max_export_kw(self) -> float:
        """§6.8 step 6's `cfg.max_export_kw`, with the None-means-follow-import case resolved."""
        explicit = _finite(self.max_export_kw)
        if explicit is not None:
            return explicit
        return self.max_import_kw


def connection_capacity_kw(phases: int, fuse_a: float) -> float:
    """kW a `phases` × `fuse_a` A connection can pass — EXACT, `phases × fuse_a × 230 V / 1000`.

    This is the physical limit §6.8 step 6 compares the net flow against, so it carries no
    rounding at all: rounding here would bake a formatting decision into the physics. The measured
    difference is small but real — 3×25 A is 17.25 kW exactly and displays as 17.3 (+50 W of
    headroom if used as the cap), 3×16 A is 11.04 and displays as 11.0 (−40 W). Immaterial to an
    annual kWh total, which is exactly why it should not be a rounding artefact.

    `connection_capacity_kw_display` is the rounded figure, for panel ② and nothing else.

    Derived rather than table-looked-up so any fuse rating and either phase count works, which is
    the point of the `Fuse rating [ 25 ] A → max import 5.75 kW` control in §2.3.

    Non-numeric or non-finite inputs give 0.0 rather than raising (see the module comment);
    `validate()` reports them against `grid.phases` / `grid.fuse_a`.
    """
    return _num(phases) * _num(fuse_a) * NOMINAL_PHASE_VOLTAGE_V / 1000.0


def connection_capacity_kw_display(phases: int, fuse_a: float) -> float:
    """The connection capacity as panel ② should PRINT it. Never use this as a limit.

    Reproduces the only two figures the specs publish:
      1 × 25 A → 5750 W → 5.75 kW   (appendix A, §2.3's wireframe)
      3 × 25 A → 17250 W → 17.3 kW  (appendix A, background E-A)

    Two rounding subtleties, both deliberate:

    * **Half-away-from-zero, not Python's `round()`.** `round(17.25, 1)` is 17.2 — banker's
      rounding goes to the even digit. Appendix A and background E-A both say 17.3. `Decimal` with
      ROUND_HALF_UP is used so the derivation reproduces the published figure exactly rather than
      landing one tenth below it.
    * **Two decimals below 10 kW, one at or above.** 5.75 kW is what both appendix A and the
      panel-② wireframe print; rounding everything to one decimal would display 5.8 and contradict
      them, while two decimals everywhere would print 17.25 and contradict the other.

    **The precision rule is INFERRED, not specified.** The specs give exactly two figures — 5.75
    and 17.3 — and the magnitude-conditional rule is the simplest one that reproduces both. Other
    rules fit those two points equally well ("keep 2 dp only when the second digit is non-zero",
    "3 significant figures"). If a spec revision publishes a third figure, check it against this
    rule before assuming it holds; nothing downstream depends on it, since this function's output
    is display-only.
    """
    kw = (
        Decimal(str(_num(phases)))
        * Decimal(str(_num(fuse_a)))
        * Decimal(str(NOMINAL_PHASE_VOLTAGE_V))
        / Decimal(1000)
    )
    places = Decimal("0.01") if abs(kw) < Decimal(10) else Decimal("0.1")
    return float(kw.quantize(places, rounding=ROUND_HALF_UP))


@dataclass
class PolicyConfig:
    """Charge and discharge policy with their price bands (§2.3, §6.6, §6.7).

        charge_policy / discharge_policy   §6.6 / §6.7. Defaults P3 and D1 — appendix A does not
                      tabulate these, but §2.3's wireframe preselects them and app/sample_data.py
                      renders that; sourced to §2.3, not to appendix A.
        band_a / band_b   charge when `A <= spot <= B` (§6.6), against the BARE spot price.
        band_c / band_d   discharge when `C <= spot <= D` (§6.7).
                      Appendix A explicitly does not default these ("no fixed default"); the
                      values here are §2.3's wireframe figures. A is typically left very negative
                      so only B binds, and D very high so only C binds — hence 9.999, which is a
                      "no upper bound" sentinel in practice rather than a real price.
        allow_grid_export   §6.7. A PHYSICAL permission, not an economic one, so it is unaffected
                      by `simulate_cost`.
        economic_guard      §6.7 "never discharge at a loss". Reads `p_export_net`, so it is
                      FORCED off without a cost model.

    **`economic_guard` is the user's RAW stored choice here and may read True with no cost model.**
    Dispatch must never read it off this object — it must read `SimulationConfig.economic_guard`,
    which applies the forcing on access, because `simulate_cost` lives on `SimulationConfig` and a
    `PolicyConfig` on its own cannot know it. Keeping the raw value is required, not incidental:
    appendix A says cost-only parameters are RETAINED at their stored values so that re-enabling
    cost simulation restores the user's configuration rather than resetting it, and Phase 6 has to
    round-trip the checkbox through a save/load cycle. `SimulationConfig._force_invariants` does
    normalise this field to False on construction and on `validate()` so a persisted or inspected
    config also looks right; it is the read path that is authoritative.

    Both bands live in one object because §7.3 check 12 is a check across the two of them.
    """

    charge_policy: ChargePolicy = ChargePolicy.P3
    discharge_policy: DischargePolicy = DischargePolicy.D1
    band_a: float = -0.050
    band_b: float = 0.040
    band_c: float = 0.180
    band_d: float = 9.999
    allow_grid_export: bool = False
    economic_guard: bool = False


@dataclass
class TopologyConfig:
    """The installation topology (§2.5; `topology` in the §4.5 result object).

        pv_coupling   the illustrated §2.5(a) choice. Appendix A default `dc_hybrid`, FORCED to
                      None when `has_pv` is false — §2.5: "Set cfg.coupling = ac and
                      topology.pv_coupling = null". Same arrangement as `economic_guard`: the raw
                      choice is stored here, `SimulationConfig.pv_coupling` applies the forcing on
                      read (`has_pv` lives there), and `_force_invariants` normalises the stored
                      value on construction and on `validate()`. The result object (§4.5) should
                      report `SimulationConfig.pv_coupling`, not this field.
        battery_phases  the §2.5(b) choice. Appendix A default `three_phase`, "only offered when
                      connection is 3-phase". Note the tension with `phases = 1` also being the
                      default: the shipped configuration therefore carries a battery_phases value
                      that is not offered. It is left stored and INERT rather than normalised —
                      v1 has no per-phase model at all, so the value changes no number, and
                      clearing it would lose the user's answer if they later switch to 3-phase.
                      `SimulationConfig.battery_phases_offered` says whether to show the control.
        approximated  §2.5's soft block: set when the user chooses an unsupported phase topology
                      and continues anyway. Propagates to `topology.approximated` in the result
                      (§4.5) and pins a caveat to panel ③. NOT derived from `battery_phases` —
                      §2.5 makes it the record of a deliberate user choice, and deriving it would
                      also set it for a user who never saw the dialog.

    `pv_coupling` duplicates `BatteryConfig.coupling` by design: the former is the user's answer to
    an illustrated question and is reported in the result object, the latter is what §6.8 reads.
    """

    pv_coupling: PvCoupling | None = PvCoupling.DC_HYBRID
    battery_phases: BatteryPhases = BatteryPhases.THREE_PHASE
    approximated: bool = False


@dataclass
class PricingConfig:
    """The contract and its rates (§2.3's Pricing box; consumed by §6.5 and §6.10).

    Defaults are appendix A, except `rate_normaal` / `rate_dal`, which appendix A does not
    tabulate — those come from §2.3's Fixed sub-panel wireframe, the same arrangement as
    `PolicyConfig`'s bands. Fields, in the order the panel-② box shows them:

        contract              DYNAMIC / FIXED / VARIABLE (§6.5). Selects the rate source, i.e.
                      which of the fields below `bare_supply_price` reads. Appendix A does not
                      tabulate it; DYNAMIC is the only source built, and §2.3's wireframe
                      preselects it.
        supplier_markup       the inkoopvergoeding added to the bare spot price. DYNAMIC only —
                      §6.5's FIXED and VARIABLE branches never read it.
        energy_tax_excl_vat / vat_rate   `import_price = (bare + tax) * (1 + vat)` (§6.5). Both
                      2026 figures; appendix A notes they change on 1 January 2027.
        feedin_alpha / feedin_beta   `compensation = α × bare + β`, NOT clamped per interval.
                      Appendix A's 0.50 / 0.0000 is §6.5's "Legal minimum" preset, the statutory
                      floor valid to 1 Jan 2030.
        feedin_floor_mode     over what period the ≥0 floor is assessed; see `FeedinFloorMode`.
        tlk_mode / tlk_eur_per_kwh   terugleverkosten; see `TlkMode`. The rate is appendix A's
                      explicit PLACEHOLDER — "2027 tariffs unpublished".
        dal_start_hour / dal_end_hour / dal_weekends   the day/night window §6.4 assigns a
                      `tariff_zone` from, read by the FIXED and VARIABLE rate sources. The
                      default 23 → 7 WRAPS midnight, which is the normal shape and not an
                      inversion; `validate()` is written to know that.
        degradation_eur_per_kwh   the §6.10 waterfall's degradation term, per kWh withdrawn.
                      Appendix A default 0.0, "Disabled", and itself an open question (§8.3).
        rate_normaal / rate_dal   the two FIXED rates, excl. energy tax and VAT (§6.5's
                      `where(tariff_zone == DAL, cfg.rate_dal, cfg.rate_normaal)`). Stored
                      whatever the contract type, like everything else here.

    **Nothing in this object is forced, and nothing in it is cleared when `simulate_cost` is
    false.** Appendix A lists every field here as inert-but-RETAINED; see the module comment for
    why that is the opposite treatment from `economic_guard` and why it is not an inconsistency.

    Not modelled, deliberately, for two different reasons — do not collapse them:

      * VARIABLE's dated `rate_schedule` and TIERED's tier table each need a STRUCTURE rather
        than a scalar (a dated schedule, a tier table), and each belongs with the §6.5 code that
        reads it. Neither contract type is built this increment.
      * `feedin_floor_period` and `supplier_settlement` are plain SCALARS — appendix A gives
        "calendar month" and `hourly` — and are absent for a different reason: nothing consumes
        them yet. §6.5 leaves the lawful period open (§8.14), and `supplier_settlement` is read
        by §6.16's price bracketing, not by §6.5 at all. Adding either now would be a field no
        code reads.
    """

    contract: Contract = Contract.DYNAMIC
    supplier_markup: float = 0.0205
    energy_tax_excl_vat: float = 0.09161
    vat_rate: float = 0.21
    feedin_alpha: float = 0.50
    feedin_beta: float = 0.0000
    feedin_floor_mode: FeedinFloorMode = FeedinFloorMode.MONTHLY
    tlk_mode: TlkMode = TlkMode.FLAT
    tlk_eur_per_kwh: float = 0.0400
    dal_start_hour: float = 23
    dal_end_hour: float = 7
    dal_weekends: bool = True
    degradation_eur_per_kwh: float = 0.0
    # §2.3's Fixed sub-panel wireframe, NOT appendix A — which tabulates no fixed-contract rates
    # at all. Same provenance as PolicyConfig's bands, and marked as such for the same reason: a
    # reader checking the shipped defaults against appendix A must not conclude these two drifted.
    rate_normaal: float = 0.1350
    rate_dal: float = 0.1180


# ── The whole parameter set ──────────────────────────────────────────────────────────────────


@dataclass
class SimulationConfig:
    """One run's parameters: the `cfg` of §6.6–§6.9, with the two run-wide flags.

        battery / grid / policy / topology / pricing   the five groups above. **Copied on
                      construction** — see `__post_init__`.
        has_pv        appendix A default true. "Asked explicitly, never inferred" (§8.16) — which
                      is why it is a field here and not read off whether a solar slot is mapped.
                      `SimulationFrame.has_pv_series` reports the DATA side of the same question;
                      the two can legitimately disagree (a user with PV whose sensor is unmapped),
                      and neither overrides the other.
        has_battery   whether the household ALREADY owns a battery, default false. Like `has_pv`
                      it is asked explicitly, never inferred (§8.16), and it gates only which
                      slots panel ① offers: the existing battery's charge/discharge series are
                      used to reconstruct house load net of it (§6.3). It says nothing about the
                      battery being SIMULATED — panel ②'s battery is a replacement, so no part of
                      the dispatch core reads this flag.
        simulate_cost appendix A default false — energy-only, so a first result needs no contract
                      knowledge (§8.18). It gates the whole `pricing` group: panel ② hides the
                      box, §6.5 skips the pricing package outright, and `validate()` runs no
                      pricing check. What it does NOT do is clear any of those parameters.
        dp_soc_levels / dp_action_levels   §6.12's DP discretisation, appendix A's 101 and 41.
                      Shared by BOTH perfect-foresight runs (D and E) — the two objectives differ
                      only in `transition_cost`, so a single pair of grid sizes is correct.

    Construction NEVER raises, even on nonsense input: see the module comment and `validate()`.
    """

    battery: BatteryConfig = field(default_factory=BatteryConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    topology: TopologyConfig = field(default_factory=TopologyConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)
    has_pv: bool = True
    has_battery: bool = False
    simulate_cost: bool = False
    # §6.12's DP discretisation, appendix A: `dp_soc_levels` 101, `dp_action_levels` 41, both
    # "shared by both perfect-foresight runs". They sit flat on SimulationConfig rather than in one
    # of the four groups because the groups mirror panel-②'s form boxes one-to-one and these are not
    # a form box — they are run-wide numerical tuning, in the same category as `simulate_cost`.
    # Stored as given rather than derived: the grid sizes ARE the parameters, and appendix A's two
    # numbers are what fixture 6's bound is measured at.
    dp_soc_levels: int = 101
    dp_action_levels: int = 41

    def __post_init__(self) -> None:
        """Defensively copy the five sub-configs, then normalise the forced settings.

        **The copy is not paranoia about aliasing in general — it is required by the forcing.**
        `_force_invariants` WRITES to the sub-objects (it clears `pv_coupling`, sets `coupling` to
        AC, clears `economic_guard`). Without the copy, a caller who shares one group between two
        configs has the second construction silently rewrite the first:

            shared = BatteryConfig()
            c1 = SimulationConfig(battery=shared, has_pv=True)   # c1.coupling would become AC
            c2 = SimulationConfig(battery=shared, has_pv=False)  #   ...because of THIS line

        That is a realistic Phase-6 shape: "clone this config", or a with-PV / without-PV
        comparison, naturally reuses a group. A shallow `dataclasses.replace` is enough — every
        field in the five groups is a float, bool, None or enum, all immutable, so there is nothing
        deeper to share.

        `pricing` is copied along with the rest even though `_force_invariants` never writes to it
        (appendix A: cost parameters are retained, not forced). The second reason for the copy
        stands on its own — a caller who hands the same `PricingConfig` to two configs and then
        edits one must not move the other — and a group that is copied only while something
        happens to write to it is a copy that silently disappears the day that write is removed.

        Note the `default_factory` on each field is already correct and unrelated: two default
        `SimulationConfig()`s each build their own groups and never shared one.
        """
        self.battery = dataclasses.replace(self.battery)
        self.grid = dataclasses.replace(self.grid)
        self.policy = dataclasses.replace(self.policy)
        self.topology = dataclasses.replace(self.topology)
        self.pricing = dataclasses.replace(self.pricing)
        self._force_invariants()

    def _force_invariants(self) -> None:
        """Normalise the two settings the spec says are FORCED, not merely hidden.

        Called from `__post_init__` and again at the top of `validate()`. It is a normalisation of
        the STORED values, so that a persisted parameter file, a debugger view or a `repr()` shows
        the state the spec describes rather than a superseded one.

        **It is not what makes the forcing safe.** `self.economic_guard` and `self.pv_coupling` are
        properties that apply the forcing ON READ, so a consumer that mutates `simulate_cost` after
        construction and never calls `validate()` still cannot observe a forbidden value. Making
        correctness depend on the caller having validated would be the same defect in a new place.

        1. `economic_guard` off without a cost model (§6.7, appendix A). The guard's condition is
           `st.p_export_net[i] <= 0`; that array does not exist in an energy-only run, so leaving
           the flag true would either crash §6.7 or make it read an invented zero and suppress
           every grid discharge — a large, silent change to the kWh answer.

        2. Without PV: `topology.pv_coupling = None` and `battery.coupling = AC` (§2.5). Not an
           approximation — `eta_c_dc` multiplies `chg_pv` only, and `chg_pv` is identically zero
           when `pv` is all zeros, so the two settings give bit-identical results. Forcing them
           keeps the result object from reporting a coupling for a PV array that is not there.

        Note what is NOT forced, first: **the whole of `pricing`.** `simulate_cost = false` clears
        no pricing field and no property masks one. Appendix A puts `economic_guard` and the cost
        parameters on opposite sides of exactly this line — the cost parameters are "retained at
        their stored values", `economic_guard` is "additionally FORCED off rather than merely
        hidden" — and the reason is what reads them. `economic_guard` is a DISPATCH input: left
        true, §6.7 reads `p_export_net`, an array an energy-only run never built. A rate is read
        only by the §6.5 pricing package, which that same run skips outright rather than calling
        with neutral parameters, so a stored rate cannot reach a number. Forcing it would buy no
        safety and would throw away the user's configuration on a checkbox toggle.

        Note what is NOT forced, second: `policy.charge_policy` is left alone when `has_pv` is
        false. §6.6 is explicit that P1 charges nothing and P3 degenerates to P2 there — "already
        computes the right answer" — so rewriting a stored P3 to P2 would change nothing about the
        run while silently discarding the user's answer if they later turn PV back on. Which
        policies panel ② should OFFER is a separate question; see `offerable_charge_policies`.
        """
        if not self.simulate_cost:
            self.policy.economic_guard = False
        if not self.has_pv:
            self.topology.pv_coupling = None
            self.battery.coupling = Coupling.AC

    # ── Convenience accessors the §6.6–§6.8 pseudocode reads as `cfg.<name>` ────────────────
    #
    # Flat accessors so the core matches the spec's pseudocode, and — for the derived quantities —
    # so there is exactly one place each is computed. None of them is cached; see the module
    # comment before "optimising" that.

    @property
    def band_a(self) -> float:
        """§6.6 reads `cfg.band_a`."""
        return self.policy.band_a

    @property
    def band_b(self) -> float:
        return self.policy.band_b

    @property
    def band_c(self) -> float:
        return self.policy.band_c

    @property
    def band_d(self) -> float:
        return self.policy.band_d

    @property
    def max_charge_kw(self) -> float:
        return self.battery.max_charge_kw

    @property
    def max_discharge_kw(self) -> float:
        return self.battery.max_discharge_kw

    @property
    def soc_min_kwh(self) -> float:
        return self.battery.soc_min_kwh

    @property
    def soc_max_kwh(self) -> float:
        return self.battery.soc_max_kwh

    @property
    def initial_soc_kwh(self) -> float:
        return self.battery.initial_soc_kwh

    @property
    def eta_c(self) -> float:
        return self.battery.eta_c

    @property
    def eta_d(self) -> float:
        return self.battery.eta_d

    @property
    def eta_c_dc(self) -> float:
        return self.battery.eta_c_dc

    @property
    def coupling(self) -> Coupling:
        """§6.8 step 3's `cfg.coupling`. AC whenever there is no PV, whatever is stored (§2.5)."""
        if not self.has_pv:
            return Coupling.AC
        return self.battery.coupling

    @property
    def pv_coupling(self) -> PvCoupling | None:
        """§2.5(a) / §4.5's `topology.pv_coupling`. None whatever is stored when `has_pv` is False.

        The forcing is applied here rather than only in `_force_invariants` so the result object
        cannot report a coupling for a PV array that is not there even if nobody validated. The
        raw answer stays on `topology.pv_coupling`, so turning PV back on restores the user's
        illustrated choice instead of resetting it to the default.
        """
        if not self.has_pv:
            return None
        return self.topology.pv_coupling

    @property
    def max_import_kw(self) -> float:
        """The EXACT connection cap §6.8 step 6 compares against. Panel ② prints the display one."""
        return self.grid.max_import_kw

    @property
    def max_import_kw_display(self) -> float:
        """The rounded cap, for panel ② only — see `connection_capacity_kw_display`."""
        return self.grid.max_import_kw_display

    @property
    def max_export_kw(self) -> float:
        """§6.8 step 6 reads `cfg.max_export_kw`; the None-means-follow-import case is resolved."""
        return self.grid.effective_max_export_kw

    @property
    def allow_grid_export(self) -> bool:
        return self.policy.allow_grid_export

    @property
    def economic_guard(self) -> bool:
        """§6.7's `cfg.economic_guard`. Always False without a cost model, whatever is stored.

        Forced on READ, not merely normalised in `_force_invariants`, so a caller that flips
        `simulate_cost` off after construction — or sets `policy.economic_guard = True` directly —
        and never validates still cannot get §6.7 to read `p_export_net`, an array that does not
        exist in an energy-only run. The raw choice stays on `policy.economic_guard` so appendix
        A's "retained at their stored values" holds when cost simulation is turned back on.
        """
        if not self.simulate_cost:
            return False
        return self.policy.economic_guard

    @property
    def standby_kw(self) -> float:
        """Standby draw in kW, the unit §6.9 adds to the load (the field is in watts)."""
        return _num(self.battery.standby_w) / 1000.0

    # ── UI gating (NOT dispatch semantics) ──────────────────────────────────────────────────

    @property
    def battery_phases_offered(self) -> bool:
        """Whether §2.5(b)'s phase selector is shown — 3-phase connections only.

        A UI question. The stored `topology.battery_phases` is not cleared when this is False; see
        `TopologyConfig`.

        Routed through `_finite` so a `phases` the object cannot read as a number never opens a
        control — the answer for a broken field is "do not offer it", not a crash in the renderer.
        """
        return _finite(self.grid.phases) == 3.0

    def offerable_charge_policies(self) -> tuple[ChargePolicy, ...]:
        """Which charge policies panel ② should OFFER (§2.3 "without PV", §6.6).

        **This is a UI-gating query and nothing else.** §6.6 states plainly that the dispatch code
        "needs no branch on `has_pv` — it already computes the right answer — and should not
        acquire one". So the branch lives here, in a method whose name says it is about what to
        show, and not in `charge_policy`, the bands, or anything §6.6 reads. A caller that
        simulates with P3 and no PV gets the correct P2 behaviour; this method only says panel ②
        should not have offered P3 in the first place, because two identical-looking options that
        do the same thing is a bad form, not a wrong number.

        Without PV: P1 (solar surplus only) charges nothing at all and P3 is indistinguishable
        from P2, so only P2 is offered.
        """
        if self.has_pv:
            return (ChargePolicy.P1, ChargePolicy.P2, ChargePolicy.P3)
        return (ChargePolicy.P2,)

    @property
    def effective_charge_policy(self) -> ChargePolicy:
        """The charge policy that will actually RUN, as opposed to the one stored.

        Without PV, P1 charges nothing and P3 is indistinguishable from P2 (§6.6), so both behave
        as P2 — which is exactly why `_force_invariants` does NOT rewrite the stored field: the
        run is already correct, and keeping the answer means turning PV back on restores the
        user's choice rather than silently resetting it to P2.

        That preservation is right for storage and wrong for DISPLAY. A collapsed summary reading
        `charge P3` beside a panel showing P3 greyed out and P2 selected contradicts itself. This
        property is the display-side answer; it is deliberately NOT read by the dispatch core,
        which §6.6 requires to acquire no `has_pv` branch at all.
        """
        if not self.has_pv and self.policy.charge_policy in (ChargePolicy.P1, ChargePolicy.P3):
            return ChargePolicy.P2
        return self.policy.charge_policy

    def offerable_discharge_policies(self) -> tuple[DischargePolicy, ...]:
        """Which discharge policies panel ② should offer — all three, always (§6.7).

        Present for symmetry with the charge side and because it is the natural place a reader
        looks for the answer. §6.7 is explicit that "all three remain available and distinct
        without PV", where the deficit `max(0, load − pv)` is simply the whole load; only D1's
        LABEL changes ("serve house load"), which is panel ②'s business, not this object's.
        """
        return (DischargePolicy.D1, DischargePolicy.D2, DischargePolicy.D3)

    def bands_overlap(self) -> bool:
        """Whether [A,B] and [C,D] intersect — the condition behind §7.3 check 12.

        Both bands are closed intervals (§6.6/§6.7 compare with `<=` at both ends), so touching at
        a single point counts as an overlap: a spot price exactly equal to both B and C would
        satisfy both band tests and fire both requests. Empty bands (A > B or C > D) never fire,
        so they cannot overlap with anything; that is handled by the interval test itself
        returning False rather than by a special case.

        Compares the funnelled values so a non-numeric band cannot raise here; such a band is
        reported as a blocking issue by `validate()`.
        """
        a, b = _num(self.policy.band_a), _num(self.policy.band_b)
        c, d = _num(self.policy.band_c), _num(self.policy.band_d)
        if a > b or c > d:
            return False
        return a <= d and c <= b

    # ── Validation ──────────────────────────────────────────────────────────────────────────

    def validate(self) -> ValidationResult:
        """§7.3 checks 11 (block) and 12 (warn), plus the adjacent cases the spec leaves open.

        Returns rather than raises: an invalid parameter set has to be constructible so panel ②
        can render the user's value back with the error attached to its field.

        **Blocking — check 11 verbatim, plus states that are not representable rather than merely
        aggressive.** The spec's list is `soc_min < soc_max`, powers > 0, `rte_min < RTE <= 1.0`.
        Added to it: SoC percentages outside 0–100, a negative capacity or standby, and any field
        that is not a finite number at all. Those are not settings a knowledgeable user might
        deliberately push — a −5% SoC, a −2 kWh battery or a capacity of `None` has no physical
        reading, and every derived quantity computed from one is nonsense. A blocking rule for
        them is a reading of check 11's intent (it already blocks on the SoC pair and on
        non-positive powers), not an invention beyond it.

        **Warning — check 12 verbatim, plus the cases where the spec is silent.** Where the spec
        does not say to block, this warns, on the principle that the simulator should not refuse a
        run it can compute correctly:

          * Band overlap — check 12 says so explicitly; §6.7 nets the requests at runtime.
          * An INVERTED band (A > B or C > D). The band simply never fires, which is a
            well-defined simulation — the battery does no grid charging, or no in-band discharge.
            It is nearly always a typo, so it warrants a warning, but blocking would refuse a run
            that has a correct answer.
          * `initial_soc_pct` outside [min, max]. Also well-defined: §6.9 starts from that SoC and
            the first §6.8 step clamps back into the window. Worth flagging because the first few
            intervals will not behave as the user expects, not worth blocking.
          * `eta_c_dc > 1`, reachable from a high round-trip plus the default +0.04 bonus. Not
            clamped silently (that would hide the user's own two numbers combining badly); check
            11's bound is on the round-trip figure, which is the number the user typed.

        **The pricing checks run ONLY when `simulate_cost` is true**, funnel included. Panel ②
        hides the entire Pricing box in energy-only mode (§2.3), so a blocking error keyed to
        `pricing.vat_rate` there would refuse a run the user cannot see the cause of, let alone
        fix — and it would refuse it over a parameter that changes no number, since §6.5's whole
        package is skipped in that mode. Note this is a gate on REPORTING, not on storage: the
        stored values are untouched either way (appendix A's retention rule), so turning cost
        simulation on surfaces exactly the issues that were always latent in them.

        The forced invariants are re-applied first. `validate()` is the point the run precondition
        passes through, so it is where a config that has been mutated since construction gets its
        stored values normalised again. The read-path properties already made the forcing safe;
        this keeps what is stored honest as well.
        """
        self._force_invariants()

        errors: list[ConfigIssue] = []
        warnings: list[ConfigIssue] = []
        b, g, p, pr = self.battery, self.grid, self.policy, self.pricing

        # ---- non-numeric / non-finite inputs ---------------------------------------------------
        # Checked FIRST and per field, because everything below compares numbers: an empty Phase-6
        # form field arrives as None, a text input as a str, an upstream division as nan/inf.
        # Construction and every derived read survive those (see the module comment); this is where
        # the user is told, against the input they typed. A field reported here is also skipped by
        # the range checks below — "capacity must be > 0 (got None)" alongside "capacity must be a
        # number" is two errors on one input for one mistake.
        non_numeric: set[str] = set()
        numeric_fields: tuple[tuple[str, object], ...] = (
            ("battery.usable_capacity_kwh", b.usable_capacity_kwh),
            ("battery.min_soc_pct", b.min_soc_pct),
            ("battery.max_soc_pct", b.max_soc_pct),
            ("battery.initial_soc_pct", b.initial_soc_pct),
            ("battery.max_charge_kw", b.max_charge_kw),
            ("battery.max_discharge_kw", b.max_discharge_kw),
            ("battery.roundtrip_efficiency", b.roundtrip_efficiency),
            ("battery.roundtrip_dc_bonus", b.roundtrip_dc_bonus),
            ("battery.standby_w", b.standby_w),
            ("grid.phases", g.phases),
            ("grid.fuse_a", g.fuse_a),
            ("policy.band_a", p.band_a),
            ("policy.band_b", p.band_b),
            ("policy.band_c", p.band_c),
            ("policy.band_d", p.band_d),
        )
        # The Pricing box's numerics join the SAME funnel, but only when the box exists. See the
        # docstring: in energy-only mode panel ② does not show these fields and §6.5 does not read
        # them, so reporting on them would be an error with no input to attach itself to.
        if self.simulate_cost:
            numeric_fields += (
                ("pricing.supplier_markup", pr.supplier_markup),
                ("pricing.energy_tax_excl_vat", pr.energy_tax_excl_vat),
                ("pricing.vat_rate", pr.vat_rate),
                ("pricing.feedin_alpha", pr.feedin_alpha),
                ("pricing.feedin_beta", pr.feedin_beta),
                ("pricing.tlk_eur_per_kwh", pr.tlk_eur_per_kwh),
                ("pricing.dal_start_hour", pr.dal_start_hour),
                ("pricing.dal_end_hour", pr.dal_end_hour),
                ("pricing.degradation_eur_per_kwh", pr.degradation_eur_per_kwh),
                ("pricing.rate_normaal", pr.rate_normaal),
                ("pricing.rate_dal", pr.rate_dal),
            )
        for name, value in numeric_fields:
            if _finite(value) is None:
                non_numeric.add(name)
                errors.append(
                    ConfigIssue(
                        name,
                        "not_a_number",
                        f"{name.split('.')[-1]} must be a finite number (got {value!r})",
                    )
                )
        # The two Optional fields: None is a legitimate value with a defined meaning ("not
        # overridden" / "follow import"), so only a present-but-unusable value is an error.
        for name, value in (
            ("grid.max_import_kw_override", g.max_import_kw_override),
            ("grid.max_export_kw", g.max_export_kw),
        ):
            if value is not None and _finite(value) is None:
                non_numeric.add(name)
                errors.append(
                    ConfigIssue(
                        name,
                        "not_a_number",
                        f"{name.split('.')[-1]} must be a finite number or unset (got {value!r})",
                    )
                )

        def numeric(name: str) -> bool:
            """Whether `name` survived the funnel — the range checks below only run if it did."""
            return name not in non_numeric

        # ---- check 11: soc_min < soc_max ------------------------------------------------------
        # Strict inequality, as written: an equal pair gives a zero-width operating window in which
        # the battery can neither charge nor discharge, so the run would be a no-op reported as a
        # result. That is exactly the misleading number §1 says the app must refuse.
        if (
            numeric("battery.min_soc_pct")
            and numeric("battery.max_soc_pct")
            and b.min_soc_pct >= b.max_soc_pct
        ):
            errors.append(
                ConfigIssue(
                    "battery.min_soc_pct",
                    "soc_window_empty",
                    f"min SoC ({b.min_soc_pct}%) must be below max SoC ({b.max_soc_pct}%)",
                )
            )

        # SoC percentages are percentages OF usable capacity, so outside 0–100 they describe a
        # state the battery cannot be in. Reported on the specific field so the form marks the
        # right input, not the pair.
        for name, value in (("min_soc_pct", b.min_soc_pct), ("max_soc_pct", b.max_soc_pct)):
            if numeric(f"battery.{name}") and not (0.0 <= value <= 100.0):
                errors.append(
                    ConfigIssue(
                        f"battery.{name}",
                        "soc_pct_out_of_range",
                        f"{name} must be between 0 and 100 (got {value})",
                    )
                )
        if numeric("battery.initial_soc_pct") and not (0.0 <= b.initial_soc_pct <= 100.0):
            errors.append(
                ConfigIssue(
                    "battery.initial_soc_pct",
                    "soc_pct_out_of_range",
                    f"initial SoC must be between 0 and 100 (got {b.initial_soc_pct})",
                )
            )

        # ---- check 11: powers > 0 -------------------------------------------------------------
        # Strictly positive, as written. A zero charge power is a battery that can never charge —
        # again a run whose answer is trivially "no change" dressed up as a simulation.
        for name, value in (
            ("max_charge_kw", b.max_charge_kw),
            ("max_discharge_kw", b.max_discharge_kw),
        ):
            if numeric(f"battery.{name}") and value <= 0.0:
                errors.append(
                    ConfigIssue(
                        f"battery.{name}",
                        "power_not_positive",
                        f"{name} must be greater than 0 (got {value})",
                    )
                )
        # The connection caps are powers too, and §6.8 step 6 divides nothing by them but does
        # compare against them; a non-positive cap would make every interval hit the limit.
        #
        # The issue is keyed to the field the user actually typed in, which is the OVERRIDE when
        # one is set and the fuse otherwise — Phase 6 renders these inline against the input, and
        # blaming a perfectly good 25 A fuse for a -1 kW override would point the user at the wrong
        # box. Note `_finite` here, not `is not None`: a non-numeric override has already been
        # reported above and falls through to the fuse derivation, so it must not claim this key.
        #
        # Skipped entirely when one of the inputs it derives from was already reported as
        # non-numeric: a `phases=None` derives a 0.0 cap, and "max import must be greater than 0"
        # keyed to a perfectly good 25 A fuse is a second, misleading error for a mistake the user
        # has already been told about on the right field.
        import_inputs_ok = override_set = False
        if not numeric("grid.max_import_kw_override"):
            # A present-but-unusable override: already reported on its own field, and the cap has
            # fallen back to the fuse derivation, so there is nothing further to say here.
            pass
        elif _finite(g.max_import_kw_override) is not None:
            import_inputs_ok, override_set = True, True  # the override IS the cap
        else:
            import_inputs_ok = numeric("grid.phases") and numeric("grid.fuse_a")
            override_set = False
        if import_inputs_ok and g.max_import_kw <= 0.0:
            errors.append(
                ConfigIssue(
                    "grid.max_import_kw_override" if override_set else "grid.fuse_a",
                    "power_not_positive",
                    f"max import must be greater than 0 (got {g.max_import_kw} kW)",
                )
            )
        # Likewise, and one step further: when `max_export_kw` is unset the export cap simply IS
        # the import cap, so a bad import figure would otherwise be reported twice — once against
        # the field the user typed in and once against an export field they never touched. Only an
        # EXPLICIT export value is checked here; the follow-import case is already covered above.
        if _finite(g.max_export_kw) is not None and g.effective_max_export_kw < 0.0:
            errors.append(
                ConfigIssue(
                    "grid.max_export_kw",
                    "power_negative",
                    f"max export cannot be negative (got {g.effective_max_export_kw} kW)",
                )
            )

        # ---- check 11: rte_min < RTE <= 1.0 ---------------------------------------------------
        # Note the asymmetry, which is the spec's: the lower bound is STRICT and configurable
        # (`rte_min`, appendix A), the upper bound is inclusive and is physics. 1.0 is a lossless
        # battery — unphysical but a legitimate idealisation to run; above 1.0 is energy creation.
        if numeric("battery.roundtrip_efficiency") and not (
            RTE_MIN < b.roundtrip_efficiency <= 1.0
        ):
            errors.append(
                ConfigIssue(
                    "battery.roundtrip_efficiency",
                    "rte_out_of_range",
                    f"round-trip efficiency must be above {RTE_MIN} and at most 1.0 "
                    f"(got {b.roundtrip_efficiency})",
                )
            )

        # ---- structurally impossible values ---------------------------------------------------
        if numeric("battery.usable_capacity_kwh") and b.usable_capacity_kwh <= 0.0:
            errors.append(
                ConfigIssue(
                    "battery.usable_capacity_kwh",
                    "capacity_not_positive",
                    f"usable capacity must be greater than 0 (got {b.usable_capacity_kwh})",
                )
            )
        if numeric("battery.standby_w") and b.standby_w < 0.0:
            errors.append(
                ConfigIssue(
                    "battery.standby_w",
                    "standby_negative",
                    f"standby draw cannot be negative (got {b.standby_w} W)",
                )
            )
        # `_finite` first so `phases=True` is rejected as non-numeric rather than passing this
        # test as 1 — the derivation and the check have to agree on what a phase count is.
        # §6.12's DP grids. Two levels is the smallest discretisation that still HAS an interior —
        # a single SoC level or a single action would make the DP's state or action space
        # degenerate and its answer meaningless rather than merely coarse. Blocking rather than
        # warning because there is no correct number to report from such a run; note the DP's own
        # `linspace` would also divide by `n − 1`.
        for name, value in (
            ("dp_soc_levels", self.dp_soc_levels),
            ("dp_action_levels", self.dp_action_levels),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                errors.append(
                    ConfigIssue(
                        name,
                        "dp_levels_too_few",
                        f"{name} must be an integer of at least 2 (got {value!r})",
                    )
                )

        if numeric("grid.phases") and g.phases not in (1, 3):
            errors.append(
                ConfigIssue(
                    "grid.phases",
                    "phases_unsupported",
                    f"connection must be 1-phase or 3-phase (got {g.phases})",
                )
            )

        # ---- §6.5 pricing ranges — cost mode only ---------------------------------------------
        # Same gate as the funnel above, for the same reason. Everything here BLOCKS: unlike a
        # band, none of these has a well-defined simulation outside its range. A VAT rate of 3.0
        # or an α of −2 does not produce a coarse or surprising euro figure, it produces a
        # confident wrong one, which is the outcome §1 says the app must refuse over.
        if self.simulate_cost:
            # α and VAT are fractions by construction: `import_price` multiplies by `1 + vat_rate`
            # and `compensation = alpha * bare + beta`. Both bounds are INCLUSIVE — 0 VAT and a
            # 0 or 1.0 α are all meaningful settings (§6.5's preset table lists α = 0.00 for a
            # flat feed-in rate and α = 1.00 for spot), so only outside [0, 1] is unrepresentable.
            for name, value in (("vat_rate", pr.vat_rate), ("feedin_alpha", pr.feedin_alpha)):
                if numeric(f"pricing.{name}") and not (0.0 <= value <= 1.0):
                    errors.append(
                        ConfigIssue(
                            f"pricing.{name}",
                            "fraction_out_of_range",
                            f"{name} must be between 0 and 1 (got {value})",
                        )
                    )
            # Three charges that have no negative reading. Note what is NOT here: `feedin_beta`
            # and `supplier_markup` are signed on purpose — §6.5's "Spot minus fee" preset is
            # β = −0.0200, and a markup can in principle be a discount.
            #
            # `rate_normaal`/`rate_dal` are checked for finiteness only, and that is a DEFERRAL
            # rather than a judgement that a negative supply rate is meaningful. They belong to
            # the FIXED contract, which is not built this increment (only DYNAMIC is), so no code
            # reads them yet and any bound written now would be guessed rather than derived from
            # a consumer. Whoever builds FIXED should decide it against §6.5 — the obvious
            # `< 0.0` check would fit beside the three below.
            for name, value in (
                ("energy_tax_excl_vat", pr.energy_tax_excl_vat),
                ("tlk_eur_per_kwh", pr.tlk_eur_per_kwh),
                ("degradation_eur_per_kwh", pr.degradation_eur_per_kwh),
            ):
                if numeric(f"pricing.{name}") and value < 0.0:
                    errors.append(
                        ConfigIssue(
                            f"pricing.{name}",
                            "rate_negative",
                            f"{name} cannot be negative (got {value})",
                        )
                    )
            # The dal window's two ends are hours-of-day, so [0, 24). 24 itself is excluded
            # because it is 0 of the next day, not an hour this one has.
            #
            # **A window that wraps midnight is NORMAL and is not checked for.** Appendix A's
            # default is 23 → 7, i.e. start > end, which is what a night tariff looks like
            # everywhere in the Netherlands. An "inverted range" check of the shape used on the
            # price bands would flag the shipped default, which is how that mistake announces
            # itself; there is no inversion to detect here, only two independent hours.
            for name, value in (
                ("dal_start_hour", pr.dal_start_hour),
                ("dal_end_hour", pr.dal_end_hour),
            ):
                if numeric(f"pricing.{name}") and not (0.0 <= value < 24.0):
                    errors.append(
                        ConfigIssue(
                            f"pricing.{name}",
                            "hour_out_of_range",
                            f"{name} must be an hour in [0, 24) (got {value})",
                        )
                    )

            # ---- the three enum-typed selectors -----------------------------------------------
            # Checked by TYPE, not by range, and checked here rather than left to the reader's
            # goodwill because §6.5 dispatches on these with an if/elif/else chain: a `tlk_mode`
            # of None or the bare string "flat" (not the enum) falls to the `else` and reaches
            # `tiered_tlk_rate` with no tier table, and a bad `contract` silently prices as
            # whichever branch is last. A wrong euro figure from a mistyped enum is exactly the
            # confident-wrong-answer §1 refuses, so it blocks.
            #
            # This is stricter than the module's older enum fields (`charge_policy`, `coupling`,
            # `battery_phases`), which are unvalidated. That is a gap in those, not a precedent to
            # follow — see `dp_soc_levels` above for the same argument applied to a non-float.
            # `dal_weekends` is deliberately NOT here: every Python object is truthy or falsy, so
            # `bool(x)` has a defined answer for anything the form can submit, and there is no
            # such thing as an unrepresentable value for it.
            for name, value, enum_cls in (
                ("contract", pr.contract, Contract),
                ("feedin_floor_mode", pr.feedin_floor_mode, FeedinFloorMode),
                ("tlk_mode", pr.tlk_mode, TlkMode),
            ):
                if not isinstance(value, enum_cls):
                    errors.append(
                        ConfigIssue(
                            f"pricing.{name}",
                            "not_a_choice",
                            f"{name} must be one of "
                            f"{', '.join(m.value for m in enum_cls)} (got {value!r})",
                        )
                    )

        # ---- check 12: band overlap — WARN, never block ---------------------------------------
        # §7.3 check 12 and §6.7: "Validate at config time and warn ... At runtime, net the
        # requests". The netting is real code in §6.8 step 1, so an overlapping configuration is
        # fully simulatable; blocking it would refuse a run the spec describes how to compute.
        if self.bands_overlap():
            warnings.append(
                ConfigIssue(
                    "policy.band_b",
                    "bands_overlap",
                    f"charge band [{p.band_a}, {p.band_b}] overlaps discharge band "
                    f"[{p.band_c}, {p.band_d}]; charge and discharge requests will be netted",
                )
            )

        # ---- silent-typo warnings the spec does not legislate ---------------------------------
        if numeric("policy.band_a") and numeric("policy.band_b") and p.band_a > p.band_b:
            warnings.append(
                ConfigIssue(
                    "policy.band_a",
                    "band_inverted",
                    f"charge band lower bound ({p.band_a}) is above its upper bound ({p.band_b}); "
                    "the band will never fire",
                )
            )
        if numeric("policy.band_c") and numeric("policy.band_d") and p.band_c > p.band_d:
            warnings.append(
                ConfigIssue(
                    "policy.band_c",
                    "band_inverted",
                    f"discharge band lower bound ({p.band_c}) is above its upper bound "
                    f"({p.band_d}); the band will never fire",
                )
            )
        if (
            numeric("battery.min_soc_pct")
            and numeric("battery.max_soc_pct")
            and numeric("battery.initial_soc_pct")
            and not (b.min_soc_pct <= b.initial_soc_pct <= b.max_soc_pct)
        ):
            warnings.append(
                ConfigIssue(
                    "battery.initial_soc_pct",
                    "initial_soc_outside_window",
                    f"initial SoC ({b.initial_soc_pct}%) is outside the operating window "
                    f"[{b.min_soc_pct}%, {b.max_soc_pct}%] and will be clamped at the first step",
                )
            )
        if (
            numeric("battery.roundtrip_efficiency")
            and numeric("battery.roundtrip_dc_bonus")
            and b.eta_c_dc > 1.0
        ):
            warnings.append(
                ConfigIssue(
                    "battery.roundtrip_dc_bonus",
                    "dc_efficiency_above_unity",
                    f"round-trip {b.roundtrip_efficiency} plus DC bonus {b.roundtrip_dc_bonus} "
                    "exceeds 1.0; the DC charge path would create energy",
                )
            )

        return ValidationResult(tuple(errors), tuple(warnings))
