"""Panel ② — the parameter form: coercion in, view-model out (specs §2.3, §2.5, §7.3).

Two jobs, both of which `app/domain/simconfig.py` deliberately refuses:

    parse_form(form, base)  a submitted HTML form → a candidate `SimulationConfig`.
    params_view(cfg, ...)   a `SimulationConfig` → the dict `_panel_params.html` renders.

## Coercion is THIS layer's job, and that is the resolved Phase-2 question

`simconfig._finite()` rejects `str` on purpose: "Parsing is the form layer's job and it has to
happen before the value is stored, or the object's declared types stop meaning anything". This
module is that layer. `"3"` becomes `3`, `"5.0"` becomes `5.0`, `"90"` in a percent-typed field
becomes `0.90` where the stored field is a fraction, and — the important half — anything that is
NOT a plainly-written decimal number is passed through UNCHANGED as the raw string. "Plainly
written" is checked by a narrow pattern rather than by asking `int()`/`float()`, which accept
underscore grouping, non-ASCII digits and the words `nan`/`inf`; see `coerce_number`.

That last rule is what makes the error path work. A field the user typed `abc` into arrives at
`SimulationConfig` as the string `"abc"`; construction does not raise (Phase 2 guarantees it),
`validate()` reports `not_a_number` against that field's dotted path, and the re-render puts
`abc` back in the input with the error under it. Coercing an unparseable value to a default, or
to `None`, would lose what the user typed and is the one thing deliverable 2 forbids.

An EMPTY field is different from an unparseable one: it becomes `None`, which `validate()` also
reports as `not_a_number` (the funnel treats it identically) but which renders back as an empty
input rather than as the word "None".

## Percent-typed fields

Three fields are stored as fractions and shown as percentages: `roundtrip_efficiency` (90 in the
form, 0.90 stored) and `roundtrip_dc_bonus` (4 in the form, 0.04 stored). The SoC percentages are
NOT among them — `min_soc_pct`/`max_soc_pct`/`initial_soc_pct` are stored as percentages already
(their names say so), so they pass through untouched. Getting this backwards silently scales the
whole simulation by 100, so the conversion lives in ONE place per direction (`_pct_to_frac` /
`_frac_to_pct`) and the field table below names which fields use it.

## Validation surfacing (§7.3)

`validate()` returns dotted-path-keyed issues. `field_messages()` turns them into
`{dotted_path: [message, …]}` for the template to look up beside each input, translating by
`ConfigIssue.code` (a stable machine id) rather than by the developer-facing English `message` —
`ISSUE_MESSAGES` is that table. A code with no entry falls back to the issue's own message, so a
new check surfaces something readable rather than nothing.

    check 11 → errors   → blocking, rendered inline, the config is NOT persisted.
    check 12 → warnings → rendered inline, the config IS persisted (§6.7 nets the requests).
    check 18 → soft     → `topology.approximated`; see `phase_topology_notice`.

**No `_()`-wrapped string here may contain a literal `%`.** `app/i18n.py` installs gettext with
`newstyle=True`, which %-formats the result of `_()`: a bare `%` is eaten before a letter and
raises `ValueError` before a non-ASCII character. Messages that need a percentage use the word
"percent" or a `%(name)s` placeholder in a STATIC msgid (which is exactly what newstyle is for).

Main items:
    FIELDS                       the form-name → dotted-path → coercion table.
    parse_form(form, base)       coerce a submitted form into a candidate config.
    params_view(cfg, result)     the panel-② view-model, including the collapsed summary line.
    summary_line(cfg)            §2.3's collapsed one-liner, computed from the config.
    field_messages(result)       dotted path → translated messages, for inline binding.
"""

from __future__ import annotations

import re

from app.domain.simconfig import (
    BatteryPhases,
    ChargePolicy,
    Coupling,
    DischargePolicy,
    PvCoupling,
    SimulationConfig,
    ValidationResult,
)
from app.sample_data import _N
from app.simconfig_store import clone

# ── Coercion primitives ──────────────────────────────────────────────────────────────────────

# What counts as a number a user typed: ASCII digits, an optional leading sign, at most one
# decimal point, an optional exponent. Narrower than `int()`/`float()` accept on purpose — see
# `coerce_number`. `1.` and `.5` are allowed because a browser number input produces them.
# `re.ASCII` is load-bearing: without it `\d` matches every Unicode decimal digit, which is
# exactly how "١٢" reached `int()` and became 12.
_NUMERIC = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)


def coerce_number(raw: object) -> object:
    """A form value as a number where it parses, unchanged where it does not.

    The three outcomes, all deliberate (see the module comment):

        "" or None      → None    the user cleared the field; renders back empty.
        "3" / " 5.0 "   → 3 / 5.0 a number; note ints stay ints, so `phases` is `3` not `3.0`
                                  and `simconfig`'s `phases not in (1, 3)` check works.
        "abc" / "1,5"   → "abc"   passed through RAW so validate() reports it against this field
                                  and the re-render shows the user what they typed.

    A comma decimal separator is NOT silently accepted. Dutch users type `1,5`, and reading it as
    1.5 here would be a guess about intent that could as easily mean a thousands separator; the
    honest outcome is a field error naming the value, which is what falling through gives.

    **The shape is checked before `int`/`float` are asked**, because Python's parsers accept
    three things a user did not type intending that value: `"1_000"` (underscore grouping) →
    1000, `"١٢"` (Arabic-Indic digits, which `int()` accepts as any Unicode decimal digit) → 12,
    and `"nan"`/`"inf"` → a non-finite float. The first two silently change the number; the third
    was already blocked by `validate()`, but only after rendering back into the input as the word
    `nan` rather than as what the user typed. `_NUMERIC` is deliberately narrow — ASCII digits, an
    optional sign, one decimal point, an optional exponent — so all three fall through to the raw
    string and get a field error, which is the outcome every other unusable entry gets.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return raw
    text = str(raw).strip()
    if text == "":
        return None
    if not _NUMERIC.fullmatch(text):
        return raw  # raw string, preserved for the error path
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return raw  # raw string, preserved for the error path


def coerce_optional_number(raw: object) -> object:
    """`coerce_number`, for the two fields where None has a MEANING rather than being empty.

    `grid.max_import_kw_override` (None = derive from the fuse) and `grid.max_export_kw`
    (None = follow import). Identical behaviour to `coerce_number` — the difference is entirely in
    `validate()`, which does not report None against these two — but named separately so the call
    site says which of the two None-meanings applies.
    """
    return coerce_number(raw)


def _pct_to_frac(raw: object) -> object:
    """A percentage from the form → the fraction the config stores (90 → 0.90).

    Non-numeric input passes through UNSCALED, so the raw string still reaches `validate()` and
    the user still sees what they typed. Dividing a string is not attempted.
    """
    value = coerce_number(raw)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return value / 100.0
        except OverflowError:
            # An int too large to be a float, which `int()` happily parses from a long digit
            # string. Scaling is impossible, so the raw value passes through and `validate()`
            # reports it — the same outcome `_finite` gives it. See `_fmt`.
            return value
    return value


def _frac_to_pct(value: object) -> object:
    """The inverse, for rendering (0.90 → 90). Non-numeric passes through unchanged.

    An int beyond float range passes through UNSCALED for the same reason `_pct_to_frac` does:
    the value is already unusable and on its way to a field error, and raising in a render path
    is the one outcome that is not allowed.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return value * 100.0
        except OverflowError:
            return value
    return value


def _enum_or_keep(enum_cls, raw, current):
    """`enum_cls(raw)` when `raw` names a member, else the CURRENT value.

    Radio groups are a closed vocabulary the user cannot type into: an unrecognised value means a
    tampered or stale POST, not a user mistake, so there is nothing to report inline and the
    right answer is to leave the setting as it was rather than to reset it to a default.
    """
    if raw is None:
        return current
    try:
        return enum_cls(raw)
    except (ValueError, KeyError, TypeError):
        return current


def _checkbox(form, name: str) -> bool:
    """An HTML checkbox: present in the form body means checked, absent means unchecked.

    Unchecked checkboxes are simply not submitted, which is why this reads presence rather than
    value — and why every checkbox must be inside the submitted form for its OFF state to be
    recorded at all.
    """
    return name in form


# ── The field table ──────────────────────────────────────────────────────────────────────────

# form field name → (dotted config path, coercion). The dotted path is the SAME key
# `ConfigIssue.field` carries, which is what lets the template look up an error beside the input
# that produced it without a second mapping. Percent-typed fields are marked by their coercion.
FIELDS: tuple[tuple[str, str, object], ...] = (
    ("battery.usable_capacity_kwh", "battery.usable_capacity_kwh", coerce_number),
    ("battery.min_soc_pct", "battery.min_soc_pct", coerce_number),
    ("battery.max_soc_pct", "battery.max_soc_pct", coerce_number),
    ("battery.max_charge_kw", "battery.max_charge_kw", coerce_number),
    ("battery.max_discharge_kw", "battery.max_discharge_kw", coerce_number),
    # Shown as a percentage (90), stored as a fraction (0.90). See the module comment.
    ("battery.roundtrip_efficiency", "battery.roundtrip_efficiency", _pct_to_frac),
    ("battery.roundtrip_dc_bonus", "battery.roundtrip_dc_bonus", _pct_to_frac),
    ("battery.standby_w", "battery.standby_w", coerce_number),
    ("battery.initial_soc_pct", "battery.initial_soc_pct", coerce_number),
    ("grid.phases", "grid.phases", coerce_number),
    ("grid.fuse_a", "grid.fuse_a", coerce_number),
    ("grid.max_import_kw_override", "grid.max_import_kw_override", coerce_optional_number),
    ("grid.max_export_kw", "grid.max_export_kw", coerce_optional_number),
    ("policy.band_a", "policy.band_a", coerce_number),
    ("policy.band_b", "policy.band_b", coerce_number),
    ("policy.band_c", "policy.band_c", coerce_number),
    ("policy.band_d", "policy.band_d", coerce_number),
)

# The percent-typed fields, for the RENDER direction. Derived from FIELDS so the two directions
# cannot drift: a field converted on the way in is converted on the way out.
_PCT_FIELDS = frozenset(path for _, path, fn in FIELDS if fn is _pct_to_frac)


def _get_path(cfg: SimulationConfig, path: str):
    """Read a dotted path off a config ("battery.min_soc_pct")."""
    obj = cfg
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _set_path(cfg: SimulationConfig, path: str, value) -> None:
    """Write a dotted path on a config. Only two levels deep exist, but the loop is general."""
    parts = path.split(".")
    obj = cfg
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], value)


# ── Parsing a submission ─────────────────────────────────────────────────────────────────────


def parse_form(form, base: SimulationConfig | None = None) -> SimulationConfig:
    """A submitted panel-② form → a candidate `SimulationConfig`. Never raises.

    `form` is anything with `.get(name)` and `in` (a Starlette `FormData`, or a plain dict in
    tests). `base` is the config the form was rendered from; every setting the submission does not
    carry is inherited from it, which is what makes a partial POST safe and what preserves the
    cost-only parameters appendix A says are RETAINED — they are never in an energy-only form, so
    they can only survive by being inherited.

    A field PRESENT but empty is a user clearing it (`None`, reported by `validate()`); a field
    ABSENT is a control the current UI does not show, and keeps the base value. The two are
    distinguished by membership, not by truthiness — `"0"` is a present, meaningful value.

    Checkboxes are the exception to "absent means inherit": an unchecked checkbox is never
    submitted, so its absence is indistinguishable from the control not existing. They are read
    only when the form declares the section they belong to, via the `sections` marker below.
    """
    cfg = clone(base) if base is not None else SimulationConfig()

    for name, path, coerce in FIELDS:
        if name not in form:
            continue
        _set_path(cfg, path, coerce(form.get(name)))

    # Radio groups / selects — a closed vocabulary, so an unrecognised value keeps the current one.
    if "battery.coupling" in form:
        cfg.battery.coupling = _enum_or_keep(
            Coupling, form.get("battery.coupling"), cfg.battery.coupling
        )
    if "policy.charge_policy" in form:
        cfg.policy.charge_policy = _enum_or_keep(
            ChargePolicy, form.get("policy.charge_policy"), cfg.policy.charge_policy
        )
    if "policy.discharge_policy" in form:
        cfg.policy.discharge_policy = _enum_or_keep(
            DischargePolicy, form.get("policy.discharge_policy"), cfg.policy.discharge_policy
        )
    if "topology.pv_coupling" in form:
        cfg.topology.pv_coupling = _enum_or_keep(
            PvCoupling, form.get("topology.pv_coupling"), cfg.topology.pv_coupling
        )
        # §2.5(a) and §6.8 read the same answer through two fields: `topology.pv_coupling` is the
        # illustrated choice reported in the result object, `battery.coupling` is what the battery
        # step reads. The selector sets both, or the user's picture and the simulated efficiency
        # would disagree.
        if isinstance(cfg.topology.pv_coupling, PvCoupling):
            cfg.battery.coupling = Coupling(cfg.topology.pv_coupling.value)
    if "topology.battery_phases" in form:
        cfg.topology.battery_phases = _enum_or_keep(
            BatteryPhases, form.get("topology.battery_phases"), cfg.topology.battery_phases
        )

    # Checkboxes. `policy.allow_grid_export` is a physical permission and exists in both modes;
    # `policy.economic_guard` only exists with a cost model, so it is read only when the form says
    # its section was rendered — otherwise an energy-only submission would clear the user's stored
    # choice, which is precisely the reset appendix A forbids.
    if _section(form, "discharge"):
        cfg.policy.allow_grid_export = _checkbox(form, "policy.allow_grid_export")
    if _section(form, "pricing"):
        cfg.policy.economic_guard = _checkbox(form, "policy.economic_guard")

    # §2.5(b) check 18: the soft block. `approximated` is the record of a DELIBERATE user choice
    # (the "Continue with a 3-phase approximation" button), never derived — see `TopologyConfig`.
    # It is cleared whenever the chosen topology is a supported one, so a user who moves back to
    # the 3-phase inverter is no longer carrying an approximation caveat they did not earn.
    if phase_topology_unsupported(cfg):
        cfg.topology.approximated = _checkbox(form, "topology.approximated")
    else:
        cfg.topology.approximated = False

    # `_force_invariants` runs on construction, not on mutation, so re-apply it here: the fields
    # above were written directly onto the sub-objects. `validate()` would do it too, but the
    # caller may inspect the config before validating.
    cfg._force_invariants()
    return cfg


def guard_was_submitted(form, stored: SimulationConfig) -> bool:
    """Whether this submission drew the `economic_guard` checkbox (i.e. the Pricing box).

    The persistence layer needs this to tell "the user unticked the guard" from "this build never
    showed it" — see `simconfig_store.to_dict`'s carry-forward rule. Exposed as a named query
    rather than leaving the route to spell `_section(form, "pricing")`, because what the route is
    asserting is about the checkbox, not about a box name.

    **Both halves are required, and the second is the server's own.** `sections` is an
    unprotected hidden field: a client that claims it rendered the Pricing box gets the box's
    authority over the stored `economic_guard`, and with cost simulation off — where the box is
    never drawn — that authority is enough to clear the value appendix A says must be RETAINED.
    `stored.simulate_cost` is the server's independent answer to "could this form have drawn the
    box at all", so the claim is believed only where it is possible. The three legitimate cases
    are unaffected: with cost on, the box IS drawn and `sections` decides ticked from unticked;
    with cost off it never was, and the stored value carries forward.
    """
    return _section(form, "pricing") and bool(stored.simulate_cost)


def _section(form, name: str) -> bool:
    """Whether the submitted form declared it rendered section `name`.

    The form carries a hidden `sections` field listing the boxes it drew ("battery grid discharge
    …"). Checkboxes need it: an unchecked box and an absent box look identical in a form body, so
    without this marker there is no way to tell "the user unticked it" from "this build never
    showed it", and one of those must not overwrite stored state.
    """
    raw = form.get("sections")
    if not raw:
        return False
    return name in str(raw).split()


# ── check 18: the unsupported phase topology (§2.5b, §7.3) ───────────────────────────────────


def phase_topology_unsupported(cfg: SimulationConfig) -> bool:
    """Whether the selected battery-phase topology is one v1 does not model (§2.5b).

    Only `three_phase` is modelled. The other two are offered, labelled "not in v1", and selecting
    one raises the soft block. The question only arises where the selector is SHOWN — a 1-phase
    connection does not offer it, and the stored value is inert there (see `TopologyConfig`), so a
    stored `one_phase` on a 1-phase connection must not pin a caveat to the results.
    """
    if not cfg.battery_phases_offered:
        return False
    return cfg.topology.battery_phases != BatteryPhases.THREE_PHASE


# ── Validation surfacing ─────────────────────────────────────────────────────────────────────

# `ConfigIssue.code` → the user-facing English msgid. Keyed by CODE, not by the issue's own
# `message`: the message is developer-facing and free to be reworded (`ConfigIssue`'s docstring
# says so), while these are catalog entries whose text must stay stable to stay translated.
#
# `%(name)s` placeholders are safe here — they are static msgids, which is what gettext's newstyle
# formatting exists for. A LITERAL `%` would not be; see the module comment.
ISSUE_MESSAGES: dict[str, str] = {
    "not_a_number": _N("Enter a number."),
    "soc_window_empty": _N("Minimum state of charge must be below the maximum."),
    "soc_pct_out_of_range": _N("Must be between 0 and 100."),
    "power_not_positive": _N("Must be greater than zero."),
    "power_negative": _N("Cannot be negative."),
    "rte_out_of_range": _N("Round-trip efficiency must be above 50 and at most 100."),
    "capacity_not_positive": _N("Usable capacity must be greater than zero."),
    "standby_negative": _N("Standby draw cannot be negative."),
    "phases_unsupported": _N("The connection must be 1-phase or 3-phase."),
    "dp_levels_too_few": _N("Must be a whole number of at least 2."),
    "bands_overlap": _N(
        "The charge band and the discharge band overlap; charge and discharge "
        "requests will be netted against each other."
    ),
    "band_inverted": _N("The lower bound is above the upper bound, so this band never fires."),
    "initial_soc_outside_window": _N(
        "The initial state of charge is outside the operating window and will be "
        "clamped at the first interval."
    ),
    "dc_efficiency_above_unity": _N(
        "The round-trip efficiency plus the DC bonus exceeds 100, so the DC charge "
        "path would create energy."
    ),
}


def issue_message(issue) -> str:
    """The user-facing (still-English) message for one issue; the template calls `_()` on it.

    Falls back to the issue's developer message when the code has no catalog entry, so a check
    added later surfaces something readable rather than an empty error slot.
    """
    return ISSUE_MESSAGES.get(issue.code, issue.message)


def field_messages(result: ValidationResult) -> dict[str, dict]:
    """`{dotted_path: {"errors": [...], "warnings": [...]}}` for inline rendering.

    Grouped per field rather than returned flat because the template renders errors next to ONE
    input at a time and needs both severities for that input: a field can carry a blocking error
    and a warning at once (an inverted band whose bounds also overlap the other band).
    """
    out: dict[str, dict] = {}
    for issue in result.errors:
        out.setdefault(issue.field, {"errors": [], "warnings": []})["errors"].append(
            issue_message(issue)
        )
    for issue in result.warnings:
        out.setdefault(issue.field, {"errors": [], "warnings": []})["warnings"].append(
            issue_message(issue)
        )
    return out


# ── The collapsed summary line (§2.3) ────────────────────────────────────────────────────────


def _fmt(value, places: int) -> str:
    """A field value for display: numbers formatted, anything else shown as the user typed it.

    A config carrying a raw string (the error path) still has to render a summary line and still
    has to put that string back in its input, so this never assumes a number.

    **Deliberately NOT locale-aware**, unlike the figures in panels ① and ③ (A6, `app/i18n.num`).
    Its output is the `value=` of a `<input type="number">` (`_panel_params.html`), which the
    browser parses and `coerce_number` parses again on submit — and `coerce_number` REJECTS "1,5"
    on purpose, because a comma there could as easily be a thousands separator as a decimal point
    and guessing would silently change the user's number. A localised value here would therefore
    round-trip a Dutch user's own stored setting into a field error on the next save. This is a
    machine-readable form value that happens to be visible, not a figure being presented.

    `summary_line` below shares it, and shares the reasoning by consequence: the collapsed line is
    a compact technical readout of those same field values (see its own docstring), so the two
    agreeing matters more than either matching prose conventions.

    Fixed-point formatting of an int goes through float, so an int too large to be a float raises
    `OverflowError` here for the same reason it did in `_finite` — and this is the RENDER path,
    which runs for a blocking config too. It falls back to `str(value)`, which shows the user
    their digits back unabbreviated; that is what the error path is supposed to do anyway.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return f"{value:.{places}f}"
        except (OverflowError, ValueError):
            return str(value)
    if value is None:
        return ""
    return str(value)


def _g(value) -> str:
    """A number at its own natural precision (`%g`), anything else via `_fmt`'s rules.

    For values whose precision was already decided elsewhere — `max_import_kw_display` being the
    one that matters — where imposing a second, fixed precision would undo the first.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return f"{value:g}"
        except (OverflowError, ValueError):
            return str(value)
    return _fmt(value, 0)


def summary_line(cfg: SimulationConfig) -> str:
    """§2.3's collapsed one-liner, computed from `cfg`.

    Shape, from the wireframe:
    `10.0 kWh · 5.0/5.0 kW · 90% · charge P3 · discharge P1 · energy only`

    The final clause is §2.2's cost mode: `energy only` when `simulate_cost` is off, and the
    contract name when it is on — the contract model does not exist yet (out of scope here), so
    cost-on renders `cost` until §6.5 lands rather than naming a contract that is not stored.

    **Not translated, and not passed through `_()`.** It is built at runtime from user numbers and
    contains a literal `%`, which `newstyle=True` gettext would eat or raise on (see the module
    comment). The parts that ARE words ("charge", "discharge", "energy only") are short, and
    translating them would mean assembling a msgid at runtime — exactly the trap. Left as a
    compact technical readout, consistent with the panel-① summary line beside it.

    The percentage is written with the `%` character directly into a plain f-string that never
    reaches gettext, which is safe; nothing here is wrapped in `_()`.
    """
    cap = _fmt(cfg.battery.usable_capacity_kwh, 1)
    chg = _fmt(cfg.battery.max_charge_kw, 1)
    dis = _fmt(cfg.battery.max_discharge_kw, 1)
    rte_pct = _frac_to_pct(cfg.battery.roundtrip_efficiency)
    rte = _fmt(rte_pct, 0)
    charge = _policy_key(cfg.policy.charge_policy)
    discharge = _policy_key(cfg.policy.discharge_policy)
    mode = "energy only" if not cfg.simulate_cost else "cost"
    return (
        f"{cap} kWh · {chg}/{dis} kW · {rte}% · "
        f"charge {charge} · discharge {discharge} · {mode}"
    )


def _policy_key(value) -> str:
    """A policy enum's short key ("P3"), or the raw value if something else got stored."""
    return value.value if hasattr(value, "value") else str(value)


# ── The view-model ───────────────────────────────────────────────────────────────────────────

# Charge-policy labels (§2.3). `pv_only` mirrors the wireframe's `[PV only]` marker, but which
# options are OFFERED comes from `cfg.offerable_charge_policies()` — the config's own gating
# query — not from this table (deliverable 6).
_CHARGE_LABELS: dict[ChargePolicy, str] = {
    ChargePolicy.P1: _N("Solar surplus only (net zero at the grid)"),
    ChargePolicy.P2: _N("Grid charge when spot price is in band"),
    ChargePolicy.P3: _N("Both"),
}
_CHARGE_PV_ONLY = frozenset({ChargePolicy.P1, ChargePolicy.P3})

# D1's label CHANGES without PV (§2.3 "Without PV"): the original names a comparison against
# solar that the user has told us does not exist. Behaviour is identical either way.
_DISCHARGE_LABELS: dict[DischargePolicy, str] = {
    DischargePolicy.D1: _N("Serve house load when consumption exceeds solar"),
    DischargePolicy.D2: _N("Maximise discharge when spot price is in band"),
    DischargePolicy.D3: _N("Both"),
}
_D1_LABEL_NO_PV = _N("Serve house load")

_PHASE_LABELS: dict[BatteryPhases, str] = {
    BatteryPhases.ONE_PHASE: _N("1-phase battery"),
    BatteryPhases.THREE_PHASE: _N("3-phase inverter"),
    BatteryPhases.THREE_TIMES_ONE_PHASE: _N("3 × 1-phase batteries"),
}
_PHASE_SUPPORTED = frozenset({BatteryPhases.THREE_PHASE})


def params_view(
    cfg: SimulationConfig,
    result: ValidationResult | None = None,
    *,
    save_error: bool = False,
) -> dict:
    """The dict `_panel_params.html` renders. Pure presentation over `cfg` — no I/O, no mutation.

    `result` is the validation of THIS config; when omitted it is computed here, so a caller that
    only wants to render (GET /) does not have to. Note `validate()` re-applies the forced
    invariants, so calling it is also what keeps a rendered config normalised.

    Every field value is rendered from the config, including a raw string the user typed into a
    numeric input — that is the whole point of the error path (deliverable 2). Values are
    stringified through `_fmt`, so a stored 10.0 renders as "10.0" and a stored "abc" as "abc".

    Gating (deliverable 6) uses the config's OWN queries — `offerable_charge_policies()`,
    `offerable_discharge_policies()`, `battery_phases_offered` — never a re-derivation of the same
    rules here, which would be a second place for them to drift.

    `save_error` says the config was valid but could not be written to disk (a read-only or full
    data directory). It is a flag, not a message: the underlying `OSError` text is a path and an
    errno, which is not what a user needs, and the template's sentence says the thing that
    matters — these values apply now and will not survive a restart. Passed in rather than
    detected here because this function does no I/O.
    """
    if result is None:
        result = cfg.validate()
    messages = field_messages(result)

    def field(path: str, places: int = 1) -> dict:
        """One input's render state: its value, its dotted name, and its inline messages."""
        value = _get_path(cfg, path)
        if path in _PCT_FIELDS:
            value = _frac_to_pct(value)
        msg = messages.get(path, {})
        return {
            "name": path,
            "value": _fmt(value, places),
            "errors": msg.get("errors", []),
            "warnings": msg.get("warnings", []),
            "invalid": bool(msg.get("errors")),
        }

    offerable_charge = cfg.offerable_charge_policies()
    charge_policies = [
        {
            "key": p.value,
            "label": _CHARGE_LABELS[p],
            "pv_only": p in _CHARGE_PV_ONLY,
            "selected": cfg.policy.charge_policy == p,
        }
        for p in offerable_charge
    ]
    discharge_policies = [
        {
            "key": p.value,
            "label": (
                _D1_LABEL_NO_PV
                if (p is DischargePolicy.D1 and not cfg.has_pv)
                else _DISCHARGE_LABELS[p]
            ),
            "selected": cfg.policy.discharge_policy == p,
        }
        for p in cfg.offerable_discharge_policies()
    ]

    # §2.3 "Without PV": the charge box collapses to P2 alone, "rendered as a single labelled
    # option rather than a one-item radio group". The template needs to know which shape to draw,
    # and the honest test is whether the config offers exactly one — not `not has_pv` restated.
    charge_single = len(charge_policies) == 1

    phases_offered = cfg.battery_phases_offered
    battery_phases = [
        {
            "key": p.value,
            "label": _PHASE_LABELS[p],
            "supported": p in _PHASE_SUPPORTED,
            "selected": cfg.topology.battery_phases == p,
        }
        for p in BatteryPhases
    ]

    return {
        "summary": summary_line(cfg),
        "valid": not result.blocking,
        # The four field boxes, each keyed by its dotted path so an error finds its input.
        "battery": {
            "capacity": field("battery.usable_capacity_kwh", 1),
            "min_soc": field("battery.min_soc_pct", 0),
            "max_soc": field("battery.max_soc_pct", 0),
            "max_charge": field("battery.max_charge_kw", 1),
            "max_discharge": field("battery.max_discharge_kw", 1),
            "rte": field("battery.roundtrip_efficiency", 0),
            "standby": field("battery.standby_w", 0),
            "initial_soc": field("battery.initial_soc_pct", 0),
            "coupling": _enum_value(cfg.battery.coupling),
        },
        "grid": {
            "phases": _fmt(cfg.grid.phases, 0),
            "phases_field": field("grid.phases", 0),
            "fuse": field("grid.fuse_a", 0),
            # The ROUNDED figure, display only — `connection_capacity_kw_display`'s whole purpose.
            # The exact value is what §6.8 step 6 compares against and is never shown.
            #
            # Rendered with `:g`, NOT with a fixed number of decimals: that helper has ALREADY
            # made the precision decision (two decimals below 10 kW, one at or above, so that both
            # published figures — 5.75 and 17.3 — come out exactly as appendix A prints them).
            # Re-padding to a fixed width here would turn 17.3 back into 17.30 and contradict it.
            "max_import": _g(cfg.max_import_kw_display),
            "max_import_override": field("grid.max_import_kw_override", 2),
            "max_export": field("grid.max_export_kw", 2),
            "export_follows_import": cfg.grid.max_export_kw is None,
        },
        "charge_policies": charge_policies,
        "charge_single": charge_single,
        "charge_band": {"a": field("policy.band_a", 3), "b": field("policy.band_b", 3)},
        "discharge_policies": discharge_policies,
        "discharge_band": {"c": field("policy.band_c", 3), "d": field("policy.band_d", 3)},
        "allow_grid_export": bool(cfg.policy.allow_grid_export),
        # The FORCED value, not the stored one: without a cost model the guard is off whatever is
        # stored, and the control is absent anyway (§2.3). The stored choice survives on disk.
        "economic_guard": cfg.economic_guard,
        # §7.3 check 12 — the wireframe's alert, now reflecting reality rather than a literal.
        # `overlap` drives which of the two sentences the template shows.
        "bands_overlap": cfg.bands_overlap(),
        "band_values": {
            "a": _fmt(cfg.policy.band_a, 3),
            "b": _fmt(cfg.policy.band_b, 3),
            "c": _fmt(cfg.policy.band_c, 3),
            "d": _fmt(cfg.policy.band_d, 3),
        },
        # §2.5 topology.
        "pv_coupling": _enum_value(cfg.pv_coupling),
        "battery_phases_offered": phases_offered,
        "battery_phases": battery_phases,
        # check 18: shown when the CURRENT selection is unsupported. `approximated` says the user
        # already accepted the soft block, which switches the dialog to a persistent caveat.
        "phase_unsupported": phase_topology_unsupported(cfg),
        "approximated": bool(cfg.topology.approximated),
        # Which boxes this render drew, echoed back in a hidden field so `parse_form` can tell an
        # unticked checkbox from an absent control. See `_section`.
        "sections": " ".join(_sections_for(cfg)),
        # Non-field-bound issues, rendered as a panel-level list so nothing is silently dropped
        # when a check keys a field the form does not draw (e.g. dp_soc_levels).
        "other_errors": [
            issue_message(i) for i in result.errors if i.field not in _RENDERED_FIELDS
        ],
        # Valid, but not written to disk — see the docstring.
        "save_error": bool(save_error),
    }


def _sections_for(cfg: SimulationConfig) -> list[str]:
    """The boxes this config causes the panel to render (§2.3 "Without PV"/"Without cost")."""
    out = ["battery", "grid", "charge", "discharge"]
    if cfg.has_pv or cfg.battery_phases_offered:
        out.append("topology")
    if cfg.simulate_cost:
        out.append("pricing")
    return out


def _enum_value(value):
    """An enum's `.value`, or the value itself (covers None and an already-plain value)."""
    return value.value if hasattr(value, "value") else value


# Every dotted path the form draws an input for. An issue keyed outside this set has no input to
# attach to, so `params_view` surfaces it at panel level instead of dropping it.
_RENDERED_FIELDS = frozenset(path for _, path, _fn in FIELDS)
