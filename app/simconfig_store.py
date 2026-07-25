"""Persistence for the panel-② parameter set (specs §3.5 `PARAMS_CHANGED`, §5.1).

`app/domain/simconfig.py` deliberately owns no persistence ("No persistence and no UI wiring
here" — its module comment). This module is that missing half: it writes one `SimulationConfig`
per workspace to disk and reads it back, so a parameter change survives a restart (specs §3.5
lists `PARAMS_CHANGED` as a persistence point).

## Shape: one JSON document per workspace, not a SQLite table

    <data_dir>/<workspace>/simconfig.json

The dataset (app/dataset.py) splits itself between SQLite metadata and `.npz` arrays because it
is a growing collection of rows with a history. A parameter set is neither: there is exactly ONE
current config per workspace, it is a handful of scalars, and nothing ever queries across
configs. A single small document read whole and written whole is the matching shape, and it
makes the corrupt-file fallback below a two-line `try`. The directory is the same
`<data_dir>/<workspace>/` the series live under, resolved through the same traversal-rejecting
helper, so a workspace stays one directory on disk.

The document is versioned (`"version": 1`) and the version is CHECKED on read: a document
claiming any other version yields appendix-A defaults, exactly like an unparseable one, so a
future build's document is never misread as this one's. Within a version, unknown keys are
IGNORED and missing keys fall back to the appendix-A default for that field, which is what makes
an older file forward-compatible without a migration.

## Never raises on read — the app must always render

`load()` returns appendix-A defaults for every failure mode: no file, unreadable file, invalid
JSON, a JSON document that is not an object, an out-of-vocabulary enum value, a type that does
not belong in a field. This is the same principle as `SimulationConfig`'s non-raising
construction: a broken stored config must not take the page down. It is NOT a silent repair of
the user's values — a file that parses gives back exactly what it holds, including values that
`validate()` will report as blocking.

## `retained.economic_guard`: ONE slot, for the ONE field the config object normalises away

**This slot is single-purpose and must stay that way.** It is not the home of "the cost-only
parameters" as a class — it holds `economic_guard` and nothing else.

Appendix A draws a distinction that is easy to miss. The twelve cost-only parameters
(`energy_tax_excl_vat`, `vat_rate`, `supplier_markup`, `feedin_alpha`, `feedin_beta`,
`feedin_floor_mode`, `feedin_floor_period`, `tlk_eur_per_kwh`, `dal_start_hour`, `dal_end_hour`,
`dal_weekends`, `degradation_eur_per_kwh`, `supplier_settlement`) are merely INERT when
`simulate_cost` is off: nothing normalises them, so they retain themselves through
`parse_form`'s ordinary inherit-if-absent rule, which is already implemented and tested. They
must NOT be added here. Doing so would build a shadow copy of the parameter set with its own
drift surface, for no behaviour that is not already correct.

Those that live on `PricingConfig` are carried by the ordinary `"pricing"` group below, written
and read unconditionally — appendix A's retention is only half-honoured if the values survive in
process but not across a restart.

`economic_guard` is different, and appendix A says so separately: it is "*additionally* **forced**
off rather than merely hidden, because it reads a cost-model output"
(specs/appendix-a-defaults.md). It is the forcing, not the inertness, that puts it here. If a
second forced-off field ever appears, revisit this — but a list of two is still not a pattern.

**Being forced is exactly what `SimulationConfig` alone cannot survive, and this is the one
place it shows.** Its
`_force_invariants` normalises the STORED field, not merely the read path: constructing a config
with `simulate_cost=False` sets `policy.economic_guard = False` in `__post_init__`, and
`validate()` does it again. So the moment a config with cost simulation off is built — which is
every load, every parse, every clone — the user's raw True is gone from the object. That
normalisation is deliberate and well-argued in `simconfig.py` (a persisted or inspected config
should LOOK right, and the read-path property is what makes the forcing safe), but it means the
retained value has to live somewhere the forcing does not reach.

That somewhere is this document. `retained.economic_guard` is a slot beside the five groups,
written from the config's raw field only when it is meaningfully set and otherwise carried
forward from what was already on disk. On load, it is restored into `policy.economic_guard` when
`simulate_cost` is true — where the forcing does not apply, so it survives — and left in the slot
when it is false. Enabling cost simulation therefore restores the user's checkbox rather than
resetting it, which is what appendix A asks for, without touching the domain module.

`topology.pv_coupling` needs no such treatment: it is Optional, `None` is a legitimate persisted
value, and the illustrated selector re-answers the question the moment PV comes back.

Main items:
    config_path(workspace_id)     the JSON document's path.
    load(workspace_id)            the stored config, or appendix-A defaults on ANY failure.
    save(cfg, ..., guard_submitted)  write it atomically (temp file + replace).
    to_dict(cfg, retained, ...) / from_dict(d)   the serialisation, exposed for tests.
    clone(cfg)                    a copy, for deriving a candidate without touching the stored one.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from pathlib import Path

from app import config, db
from app.domain.simconfig import (
    BatteryConfig,
    BatteryPhases,
    ChargePolicy,
    Coupling,
    DischargePolicy,
    Contract,
    FeedinFloorMode,
    GridConfig,
    PolicyConfig,
    PricingConfig,
    PvCoupling,
    SimulationConfig,
    TlkMode,
    TopologyConfig,
)

_FILENAME = "simconfig.json"
_VERSION = 1


def _workspace_dir(workspace_id: str) -> Path:
    """`<data_dir>/<workspace>/`, created if missing. Rejects path traversal (§5.5 invariant 4).

    Same rule as `dataset._series_dir`, duplicated rather than imported so this module does not
    depend on the dataset layer for a directory both of them own equally.
    """
    if "/" in workspace_id or "\\" in workspace_id or workspace_id in ("", ".", ".."):
        raise ValueError(f"unsafe workspace_id: {workspace_id!r}")
    d = config.data_dir() / workspace_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path(workspace_id: str = db.WORKSPACE_ID) -> Path:
    """Where this workspace's parameter set is stored."""
    return _workspace_dir(workspace_id) / _FILENAME


# ── Serialisation ────────────────────────────────────────────────────────────────────────────


def to_dict(
    cfg: SimulationConfig,
    retained: dict | None = None,
    *,
    guard_submitted: bool = False,
) -> dict:
    """`cfg` as a JSON-safe document.

    Enums are written as their `.value` string, `None` stays `None`. The five groups keep their
    nesting so the document reads like the form boxes it came from, and so a dotted validation
    path ("battery.min_soc_pct") locates a value in the file by the same route.

    Written from the RAW dataclass fields, NOT from `SimulationConfig`'s forcing properties.

    `retained` is the previous document's `retained` block (`save()` reads it off disk). It is the
    home of the cost-only values the config object normalises away — see the module comment.

    **The carry-forward rule, and why it cannot read `cfg.simulate_cost`.** A `False` on the config
    is ambiguous: it is equally "the user unticked the box" and "`_force_invariants` wiped it
    because cost simulation is off". Conflating the two is exactly the reset appendix A forbids,
    and `cfg.simulate_cost` cannot disambiguate them — a config LOADED with cost off and then
    toggled on in memory reads `simulate_cost = True` with a field the forcing already cleared.

    So the config's value is taken only when it is `True` — which can only have come from a user
    ticking the box under a cost model, since nothing else survives the forcing — and the caller
    says so explicitly otherwise. `save(..., guard_submitted=True)` is how the route reports "this
    submission actually drew the checkbox, so its absence means unticked"; without it a stored
    `True` is carried forward untouched.
    """
    b, g, p, t, pr = cfg.battery, cfg.grid, cfg.policy, cfg.topology, cfg.pricing
    prior = retained if isinstance(retained, dict) else {}
    if bool(p.economic_guard) or guard_submitted:
        keep_guard = bool(p.economic_guard)
    else:
        keep_guard = bool(prior.get("economic_guard", p.economic_guard))
    return {
        "retained": {"economic_guard": keep_guard},
        "version": _VERSION,
        "has_pv": bool(cfg.has_pv),
        "has_battery": bool(cfg.has_battery),
        "simulate_cost": bool(cfg.simulate_cost),
        "dp_soc_levels": cfg.dp_soc_levels,
        "dp_action_levels": cfg.dp_action_levels,
        "battery": {
            "usable_capacity_kwh": b.usable_capacity_kwh,
            "min_soc_pct": b.min_soc_pct,
            "max_soc_pct": b.max_soc_pct,
            "max_charge_kw": b.max_charge_kw,
            "max_discharge_kw": b.max_discharge_kw,
            "roundtrip_efficiency": b.roundtrip_efficiency,
            "roundtrip_dc_bonus": b.roundtrip_dc_bonus,
            "standby_w": b.standby_w,
            "initial_soc_pct": b.initial_soc_pct,
            "coupling": _enum_value(b.coupling),
        },
        "grid": {
            "phases": g.phases,
            "fuse_a": g.fuse_a,
            "max_import_kw_override": g.max_import_kw_override,
            "max_export_kw": g.max_export_kw,
        },
        "policy": {
            "charge_policy": _enum_value(p.charge_policy),
            "discharge_policy": _enum_value(p.discharge_policy),
            "band_a": p.band_a,
            "band_b": p.band_b,
            "band_c": p.band_c,
            "band_d": p.band_d,
            "allow_grid_export": bool(p.allow_grid_export),
            # The RAW stored choice, not `cfg.economic_guard` — appendix A retention.
            "economic_guard": bool(p.economic_guard),
        },
        "topology": {
            "pv_coupling": _enum_value(t.pv_coupling),
            "battery_phases": _enum_value(t.battery_phases),
            "approximated": bool(t.approximated),
        },
        # Written unconditionally, whatever `simulate_cost` says. Appendix A calls the cost
        # parameters inert-but-RETAINED, and a document that only carried them when the box was
        # ticked would honour that in memory and lose it at the next restart — the same
        # half-retention the `retained` block exists to avoid for `economic_guard`. Nothing here
        # is forced, so the raw fields are the stored values already.
        "pricing": {
            "contract": _enum_value(pr.contract),
            "supplier_markup": pr.supplier_markup,
            "energy_tax_excl_vat": pr.energy_tax_excl_vat,
            "vat_rate": pr.vat_rate,
            "feedin_alpha": pr.feedin_alpha,
            "feedin_beta": pr.feedin_beta,
            "feedin_floor_mode": _enum_value(pr.feedin_floor_mode),
            "tlk_mode": _enum_value(pr.tlk_mode),
            "tlk_eur_per_kwh": pr.tlk_eur_per_kwh,
            "dal_start_hour": pr.dal_start_hour,
            "dal_end_hour": pr.dal_end_hour,
            "dal_weekends": bool(pr.dal_weekends),
            "degradation_eur_per_kwh": pr.degradation_eur_per_kwh,
            "rate_normaal": pr.rate_normaal,
            "rate_dal": pr.rate_dal,
        },
    }


def _enum_value(value):
    """`value.value` for an Enum, the value itself otherwise (covers None and already-str)."""
    return value.value if hasattr(value, "value") else value


def _enum_or_default(enum_cls, raw, default):
    """`enum_cls(raw)` if `raw` names a member, else `default`.

    A stored value outside the vocabulary (an older build's spelling, a hand-edited file) must not
    raise — see the module comment. It falls back to the appendix-A default for that field rather
    than to None, so the config stays a config.
    """
    try:
        return enum_cls(raw)
    except (ValueError, KeyError, TypeError):
        return default


def _number_or_default(raw, default):
    """A stored int/float as itself; anything else (str, None, bool, list) → `default`.

    The stored document is machine-written, so a non-number here means the file was hand-edited or
    written by a different build. `SimulationConfig` would hold such a value and `validate()` would
    block on it — but a user cannot fix a value they never typed and cannot see, so a stored
    non-number falls back to the default instead. The FORM layer is where a user-supplied bad value
    is preserved and reported (app/params_view.py); this is the disk layer.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    return raw


def _optional_number(raw, default):
    """Like `_number_or_default`, but `None` is a legitimate value (override / export unset)."""
    if raw is None:
        return None
    return _number_or_default(raw, default)


def from_dict(doc: object) -> SimulationConfig:
    """A stored document → `SimulationConfig`, filling every missing or unusable field.

    Never raises. A `doc` that is not a mapping yields plain defaults, as does an empty one; each
    group is read independently, so a document missing its `grid` block keeps the appendix-A grid
    and the battery values it does carry.
    """
    if not isinstance(doc, dict):
        return SimulationConfig()

    # The version is CHECKED, not merely written. A document from a future build may spell a
    # field differently or mean something different by the same name, and reading it as v1 would
    # silently apply values the writer did not mean. An unknown version is treated like any other
    # unreadable document: appendix-A defaults. An ABSENT version is accepted as v1, so a
    # hand-written minimal document and every test fixture still parse.
    version = doc.get("version", _VERSION)
    if version != _VERSION:
        return SimulationConfig()

    dflt = SimulationConfig()
    b_raw = doc.get("battery") if isinstance(doc.get("battery"), dict) else {}
    g_raw = doc.get("grid") if isinstance(doc.get("grid"), dict) else {}
    p_raw = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    t_raw = doc.get("topology") if isinstance(doc.get("topology"), dict) else {}
    r_raw = doc.get("pricing") if isinstance(doc.get("pricing"), dict) else {}
    db_, dg, dp, dt = dflt.battery, dflt.grid, dflt.policy, dflt.topology
    dr = dflt.pricing

    battery = BatteryConfig(
        usable_capacity_kwh=_number_or_default(
            b_raw.get("usable_capacity_kwh"), db_.usable_capacity_kwh
        ),
        min_soc_pct=_number_or_default(b_raw.get("min_soc_pct"), db_.min_soc_pct),
        max_soc_pct=_number_or_default(b_raw.get("max_soc_pct"), db_.max_soc_pct),
        max_charge_kw=_number_or_default(b_raw.get("max_charge_kw"), db_.max_charge_kw),
        max_discharge_kw=_number_or_default(b_raw.get("max_discharge_kw"), db_.max_discharge_kw),
        roundtrip_efficiency=_number_or_default(
            b_raw.get("roundtrip_efficiency"), db_.roundtrip_efficiency
        ),
        roundtrip_dc_bonus=_number_or_default(
            b_raw.get("roundtrip_dc_bonus"), db_.roundtrip_dc_bonus
        ),
        standby_w=_number_or_default(b_raw.get("standby_w"), db_.standby_w),
        initial_soc_pct=_number_or_default(b_raw.get("initial_soc_pct"), db_.initial_soc_pct),
        coupling=_enum_or_default(Coupling, b_raw.get("coupling"), db_.coupling),
    )
    grid = GridConfig(
        phases=_number_or_default(g_raw.get("phases"), dg.phases),
        fuse_a=_number_or_default(g_raw.get("fuse_a"), dg.fuse_a),
        max_import_kw_override=_optional_number(g_raw.get("max_import_kw_override"), None),
        max_export_kw=_optional_number(g_raw.get("max_export_kw"), None),
    )
    policy = PolicyConfig(
        charge_policy=_enum_or_default(
            ChargePolicy, p_raw.get("charge_policy"), dp.charge_policy
        ),
        discharge_policy=_enum_or_default(
            DischargePolicy, p_raw.get("discharge_policy"), dp.discharge_policy
        ),
        band_a=_number_or_default(p_raw.get("band_a"), dp.band_a),
        band_b=_number_or_default(p_raw.get("band_b"), dp.band_b),
        band_c=_number_or_default(p_raw.get("band_c"), dp.band_c),
        band_d=_number_or_default(p_raw.get("band_d"), dp.band_d),
        allow_grid_export=bool(p_raw.get("allow_grid_export", dp.allow_grid_export)),
        economic_guard=bool(p_raw.get("economic_guard", dp.economic_guard)),
    )
    # Restore the retained cost-only choice (module comment). Only meaningful with cost simulation
    # ON — with it off, `SimulationConfig.__post_init__` would force the field back to False the
    # instant it were set, and the value stays parked in the `retained` block until it is useful.
    retained = doc.get("retained") if isinstance(doc.get("retained"), dict) else {}
    if bool(doc.get("simulate_cost", dflt.simulate_cost)) and "economic_guard" in retained:
        policy.economic_guard = bool(retained["economic_guard"])

    topology = TopologyConfig(
        # `pv_coupling` is Optional, and None is what `_force_invariants` stores for a no-PV
        # config — so an explicit null must round-trip as None rather than falling back to the
        # DC-hybrid default. Only an absent key or an unrecognised string takes the default.
        pv_coupling=(
            None
            if ("pv_coupling" in t_raw and t_raw.get("pv_coupling") is None)
            else _enum_or_default(PvCoupling, t_raw.get("pv_coupling"), dt.pv_coupling)
        ),
        battery_phases=_enum_or_default(
            BatteryPhases, t_raw.get("battery_phases"), dt.battery_phases
        ),
        approximated=bool(t_raw.get("approximated", dt.approximated)),
    )
    # Read whatever `simulate_cost` says, for the retention rule appendix A states: the stored
    # values are what enabling cost simulation later restores. An absent `pricing` block — every
    # document written before the group existed — takes the appendix-A defaults field by field,
    # which is the same forward-compatibility rule the other four groups get.
    pricing = PricingConfig(
        contract=_enum_or_default(Contract, r_raw.get("contract"), dr.contract),
        supplier_markup=_number_or_default(r_raw.get("supplier_markup"), dr.supplier_markup),
        energy_tax_excl_vat=_number_or_default(
            r_raw.get("energy_tax_excl_vat"), dr.energy_tax_excl_vat
        ),
        vat_rate=_number_or_default(r_raw.get("vat_rate"), dr.vat_rate),
        feedin_alpha=_number_or_default(r_raw.get("feedin_alpha"), dr.feedin_alpha),
        feedin_beta=_number_or_default(r_raw.get("feedin_beta"), dr.feedin_beta),
        feedin_floor_mode=_enum_or_default(
            FeedinFloorMode, r_raw.get("feedin_floor_mode"), dr.feedin_floor_mode
        ),
        tlk_mode=_enum_or_default(TlkMode, r_raw.get("tlk_mode"), dr.tlk_mode),
        tlk_eur_per_kwh=_number_or_default(r_raw.get("tlk_eur_per_kwh"), dr.tlk_eur_per_kwh),
        dal_start_hour=_number_or_default(r_raw.get("dal_start_hour"), dr.dal_start_hour),
        dal_end_hour=_number_or_default(r_raw.get("dal_end_hour"), dr.dal_end_hour),
        dal_weekends=bool(r_raw.get("dal_weekends", dr.dal_weekends)),
        degradation_eur_per_kwh=_number_or_default(
            r_raw.get("degradation_eur_per_kwh"), dr.degradation_eur_per_kwh
        ),
        rate_normaal=_number_or_default(r_raw.get("rate_normaal"), dr.rate_normaal),
        rate_dal=_number_or_default(r_raw.get("rate_dal"), dr.rate_dal),
    )
    return SimulationConfig(
        battery=battery,
        grid=grid,
        policy=policy,
        topology=topology,
        pricing=pricing,
        has_pv=bool(doc.get("has_pv", dflt.has_pv)),
        has_battery=bool(doc.get("has_battery", dflt.has_battery)),
        simulate_cost=bool(doc.get("simulate_cost", dflt.simulate_cost)),
        dp_soc_levels=_int_or_default(doc.get("dp_soc_levels"), dflt.dp_soc_levels),
        dp_action_levels=_int_or_default(doc.get("dp_action_levels"), dflt.dp_action_levels),
    )


def _int_or_default(raw, default: int) -> int:
    """A stored integer as itself, anything else (including a float or bool) → `default`."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return default
    return raw


# ── Read / write ─────────────────────────────────────────────────────────────────────────────


def load(workspace_id: str = db.WORKSPACE_ID) -> SimulationConfig:
    """The workspace's stored parameter set, or appendix-A defaults.

    **Never raises, for any reason.** Absent file, unreadable file, invalid JSON, a JSON value
    that is not an object, an unsafe workspace id — all give `SimulationConfig()`. The panel must
    always render (deliverable 1), and a config the app cannot read is indistinguishable, to the
    user, from never having configured one.
    """
    try:
        path = config_path(workspace_id)
        if not path.exists():
            return SimulationConfig()
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return SimulationConfig()
    return from_dict(doc)


def _retained_block(workspace_id: str) -> dict:
    """The stored `retained` block, or `{}`. Never raises, for the same reason `load()` does not."""
    try:
        path = config_path(workspace_id)
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return {}
    block = doc.get("retained") if isinstance(doc, dict) else None
    return block if isinstance(block, dict) else {}


def save(
    cfg: SimulationConfig,
    workspace_id: str = db.WORKSPACE_ID,
    *,
    guard_submitted: bool = False,
) -> Path:
    """Write `cfg` to the workspace's document and return the path.

    Atomic: written to a sibling temp file and `os.replace`d in, so a crash or a concurrent read
    mid-write cannot leave a truncated document behind — and `load()`'s fallback therefore covers
    a genuinely corrupt file rather than a routine race.

    The temp file's name is UNIQUE PER WRITER (`tempfile.mkstemp`), not a fixed `.json.tmp`. Two
    overlapping saves — two browser tabs, or a double-click on "Calculate →" — would otherwise
    write the same path, and the first `os.replace` would consume it out from under the second,
    which then fails with `FileNotFoundError`. That is an `OSError`, so the route turned it into
    a 500; measured at 44% failures with three concurrent submitters. `mkstemp` also creates the
    file 0600, which is tighter than the rest of the data directory (the SQLite file and the
    `.npz` arrays are created at the process umask), so the mode is relaxed to match before the
    replace — the document holds no secret and an inconsistent mode inside one data dir is a
    surprise. A failed write unlinks its own temp file rather than leaving litter behind.

    `guard_submitted` says the caller's submission actually drew the `economic_guard` checkbox, so
    an unticked box means unticked rather than absent. Default False, which carries the stored
    value forward — see `to_dict`'s carry-forward rule and the module comment.

    Unlike `load`, this DOES propagate an I/O error: a save that silently did nothing would tell
    the user their parameters were stored when they were not. The route decides what to do with it.
    """
    path = config_path(workspace_id)
    # Carry forward the retained cost-only block (module comment). Read from disk rather than
    # threaded through the caller so a save can never DROP a value the caller never saw — the
    # form layer works with a `SimulationConfig`, which by construction cannot carry it.
    payload = json.dumps(
        to_dict(
            cfg,
            retained=_retained_block(workspace_id),
            guard_submitted=guard_submitted,
        ),
        indent=2,
        sort_keys=False,
    )
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o666 & ~_umask())
        os.replace(tmp, path)
    finally:
        # A successful `os.replace` already moved the temp file away; this only fires when the
        # write or the replace failed, and then it is the difference between reporting the error
        # and reporting it while leaving a stray file in the user's data directory.
        tmp.unlink(missing_ok=True)
    return path


def _umask() -> int:
    """The process umask, read the only way POSIX offers: set it and put it back.

    Needed because `tempfile.mkstemp` hardcodes 0600, while every other file in the data
    directory is created at the default umask. Racy in principle against another thread creating
    a file in the same instant; harmless here, and the alternative is a hardcoded mode that
    ignores the operator's umask entirely.
    """
    current = os.umask(0o022)
    os.umask(current)
    return current


def clone(cfg: SimulationConfig) -> SimulationConfig:
    """A deep-enough copy of `cfg`.

    `SimulationConfig.__post_init__` already `dataclasses.replace`s each group, and every field in
    those groups is immutable (float/bool/None/enum), so re-constructing from the five groups is a
    full copy. Used by the form layer to derive a candidate config from the stored one without
    mutating what is on disk.

    **Every group has to be named here.** This rebuilds the config field by field rather than
    copying it, so a group left out is not aliased — it is silently replaced by its appendix-A
    default. `/params` builds its candidate on `clone`, which would make any parameter submission
    reset the omitted group. That is the defect `test_clone_preserves_has_battery` exists for.
    """
    return SimulationConfig(
        battery=dataclasses.replace(cfg.battery),
        grid=dataclasses.replace(cfg.grid),
        policy=dataclasses.replace(cfg.policy),
        topology=dataclasses.replace(cfg.topology),
        pricing=dataclasses.replace(cfg.pricing),
        has_pv=cfg.has_pv,
        has_battery=cfg.has_battery,
        simulate_cost=cfg.simulate_cost,
        dp_soc_levels=cfg.dp_soc_levels,
        dp_action_levels=cfg.dp_action_levels,
    )
