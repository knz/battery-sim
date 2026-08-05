"""Panel ② form layer + parameter persistence (specs §2.3, §2.5, §7.3, appendix A).

Two modules under test, both new in the panel-② increment:

    app/params_view.py      form coercion in, view-model out; validation surfacing.
    app/simconfig_store.py  the persisted parameter set.

The domain object itself (`app/domain/simconfig.py`) is covered by tests/test_simconfig.py; what
is asserted here is the wiring around it — that a form string becomes a number, that an
unparseable one survives into the re-render instead of being swallowed, that a stored config
round-trips, that a corrupt file degrades to defaults rather than raising, and that the cost-only
retention appendix A requires actually holds across a `simulate_cost` toggle.

Route-level behaviour (POST /params, and a parameter change moving panel ③'s figures) is in
tests/test_params_route.py.
"""

from __future__ import annotations

import json

import pytest

from app import params_view
from app.domain.simconfig import (
    BatteryConfig,
    BatteryPhases,
    ChargePolicy,
    Contract,
    Coupling,
    DischargePolicy,
    PolicyConfig,
    PvCoupling,
    SimulationConfig,
    SupplierSettlement,
    TlkMode,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """`app.simconfig_store` bound to a throwaway data dir (config.data_dir() reads the env)."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import simconfig_store

    return simconfig_store


# A minimally complete energy-only submission, as the rendered form posts it. Individual tests
# override the one field they are about.
def _form(**overrides) -> dict:
    base = {
        "sections": "battery grid charge discharge topology",
        "battery.usable_capacity_kwh": "10.0",
        "battery.min_soc_pct": "10",
        "battery.max_soc_pct": "100",
        "battery.max_charge_kw": "5.0",
        "battery.max_discharge_kw": "5.0",
        "battery.roundtrip_efficiency": "90",
        "battery.standby_w": "30",
        "battery.initial_soc_pct": "50",
        "grid.phases": "1",
        "grid.fuse_a": "25",
        "grid.max_import_kw_override": "",
        "grid.max_export_kw": "",
        "policy.band_a": "-0.050",
        "policy.band_b": "0.040",
        "policy.band_c": "0.180",
        "policy.band_d": "9.999",
        "policy.charge_policy": "P3",
        "policy.discharge_policy": "D1",
        "topology.pv_coupling": "dc_hybrid",
    }
    base.update(overrides)
    return base


# ── Coercion (the resolved "_finite rejects str" question) ───────────────────────────────────


def test_coercion_turns_form_strings_into_numbers():
    """`"3"` → `3`, and an int stays an int so `phases not in (1, 3)` still works.

    `simconfig._finite` rejects `str` on purpose and says parsing "is the form layer's job". This
    is that layer doing it. The int/float distinction is not cosmetic: `GridConfig.phases` is
    compared against the literal tuple `(1, 3)`, which `3.0` would also satisfy but which reads
    wrong in a persisted document and in a debugger.
    """
    cfg = params_view.parse_form(_form(**{"grid.phases": "3", "battery.max_charge_kw": "7.5"}))
    assert cfg.grid.phases == 3
    assert isinstance(cfg.grid.phases, int)
    assert cfg.battery.max_charge_kw == 7.5
    assert not cfg.validate().blocking


def test_percent_typed_fields_are_scaled_both_ways():
    """Round-trip efficiency is entered as 90 and stored as 0.90 — and rendered back as 90.

    Getting this backwards scales the whole simulation by 100 silently, so both directions are
    asserted together rather than in separate tests that could drift apart.
    """
    cfg = params_view.parse_form(_form(**{"battery.roundtrip_efficiency": "85"}))
    assert cfg.battery.roundtrip_efficiency == pytest.approx(0.85)
    view = params_view.params_view(cfg)
    assert view["battery"]["rte"]["value"] == "85"


def test_an_empty_field_becomes_none_and_blocks():
    """A cleared numeric input arrives as None, blocks as `not_a_number`, and renders back empty.

    Distinct from an unparseable value: the user cleared the field rather than mistyping it, so
    the input must come back empty and not carrying the word "None".
    """
    cfg = params_view.parse_form(_form(**{"battery.usable_capacity_kwh": ""}))
    assert cfg.battery.usable_capacity_kwh is None
    result = cfg.validate()
    assert result.blocking
    assert "battery.usable_capacity_kwh" in result.fields_with_errors()
    view = params_view.params_view(cfg, result)
    assert view["battery"]["capacity"]["value"] == ""
    assert view["battery"]["capacity"]["invalid"] is True


def test_a_non_numeric_value_is_preserved_not_discarded():
    """`abc` reaches the config as the raw string, blocks, and is rendered back verbatim.

    This is the whole error contract: construction never raises (Phase 2's guarantee), the value
    the user typed survives into the re-render, and the error is keyed to that field. Coercing it
    to a default here would lose what they typed, which is the one thing the form must not do.
    """
    cfg = params_view.parse_form(_form(**{"battery.max_charge_kw": "abc"}))
    assert cfg.battery.max_charge_kw == "abc"
    result = cfg.validate()
    assert "battery.max_charge_kw" in result.fields_with_errors()
    view = params_view.params_view(cfg, result)
    assert view["battery"]["max_charge"]["value"] == "abc"
    assert view["battery"]["max_charge"]["errors"]


def test_a_comma_decimal_is_a_field_error_not_a_silent_guess():
    """`1,5` is not read as 1.5. A Dutch decimal comma and a thousands separator look identical."""
    cfg = params_view.parse_form(_form(**{"battery.usable_capacity_kwh": "1,5"}))
    assert cfg.battery.usable_capacity_kwh == "1,5"
    assert "battery.usable_capacity_kwh" in cfg.validate().fields_with_errors()


@pytest.mark.parametrize(
    "typed",
    [
        "1_000",   # Python's underscore grouping; `int()` reads it as 1000
        "١٢",      # Arabic-Indic digits; `int()` reads any Unicode decimal digit
        "nan",     # accepted by float(), and it used to render back as the word "nan"
        "inf",
        "-inf",
    ],
)
def test_python_numeric_spellings_a_user_did_not_type_are_field_errors(typed):
    """`int()`/`float()` accept three things nobody types into a kWh box meaning that value.

    The first two silently CHANGE the number (1_000 → 1000, ١٢ → 12). `nan`/`inf` were already
    blocked by `validate()`, but only after coercing to a float that rendered back into the input
    as the word `nan` rather than as what the user typed. All five now fall through to the raw
    string, which gets the same field error every other unusable entry gets, and renders verbatim.
    """
    cfg = params_view.parse_form(_form(**{"battery.usable_capacity_kwh": typed}))
    assert cfg.battery.usable_capacity_kwh == typed
    result = cfg.validate()
    assert "battery.usable_capacity_kwh" in result.fields_with_errors()
    view = params_view.params_view(cfg, result)
    assert view["battery"]["capacity"]["value"] == typed


@pytest.mark.parametrize(
    "typed,expected",
    [("12", 12), ("-3", -3), ("1.5", 1.5), (".5", 0.5), ("1.", 1.0), ("1e3", 1000.0),
     ("+7", 7), (" 5.0 ", 5.0)],
)
def test_the_narrowed_pattern_still_accepts_everything_a_number_input_produces(typed, expected):
    """The counterpart to the test above: tightening must not reject ordinary entries.

    `.5` and `1.` in particular are shapes a browser `<input type="number">` really emits.
    """
    value = params_view.coerce_number(typed)
    assert value == expected
    assert not isinstance(value, str)


def test_absent_fields_inherit_from_the_base_config():
    """A partial submission changes only what it carries — that is what retains everything else."""
    base = params_view.parse_form(_form(**{"battery.usable_capacity_kwh": "18"}))
    partial = params_view.parse_form({"sections": "battery", "battery.min_soc_pct": "15"}, base)
    assert partial.battery.min_soc_pct == 15
    assert partial.battery.usable_capacity_kwh == 18   # inherited, not reset


# ── Validation surfacing (§7.3 checks 11 and 12) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "overrides, field, code",
    [
        # check 11 verbatim: soc_min < soc_max, powers > 0, rte_min < RTE <= 1.0.
        ({"battery.min_soc_pct": "90", "battery.max_soc_pct": "80"},
         "battery.min_soc_pct", "soc_window_empty"),
        ({"battery.max_charge_kw": "0"}, "battery.max_charge_kw", "power_not_positive"),
        ({"battery.max_discharge_kw": "-1"}, "battery.max_discharge_kw", "power_not_positive"),
        ({"battery.roundtrip_efficiency": "40"},
         "battery.roundtrip_efficiency", "rte_out_of_range"),
        ({"battery.roundtrip_efficiency": "120"},
         "battery.roundtrip_efficiency", "rte_out_of_range"),
        # The adjacent structurally-impossible states check 11's intent covers.
        ({"battery.usable_capacity_kwh": "0"},
         "battery.usable_capacity_kwh", "capacity_not_positive"),
        ({"battery.standby_w": "-5"}, "battery.standby_w", "standby_negative"),
        ({"battery.min_soc_pct": "-5"}, "battery.min_soc_pct", "soc_pct_out_of_range"),
        ({"battery.usable_capacity_kwh": "x"},
         "battery.usable_capacity_kwh", "not_a_number"),
    ],
)
def test_check_11_conditions_render_inline_against_the_right_field(overrides, field, code):
    """Each blocking condition keys its OWN input, and the view-model marks that input invalid.

    The dotted path is the contract between `ConfigIssue.field` and the rendered `name=` — an
    error keyed to the wrong field points the user at the wrong box, which is worse than no error.
    """
    cfg = params_view.parse_form(_form(**overrides))
    result = cfg.validate()
    assert result.blocking
    assert field in result.fields_with_errors()
    assert any(i.code == code for i in result.errors if i.field == field)
    # And it reaches the renderer keyed by that same path, with a translated-ready message.
    messages = params_view.field_messages(result)
    assert messages[field]["errors"]
    assert params_view.ISSUE_MESSAGES[code] in messages[field]["errors"]


def test_check_12_band_overlap_warns_and_still_allows():
    """§7.3 check 12 / §6.7: overlapping bands are netted at runtime, so this warns, never blocks."""
    cfg = params_view.parse_form(_form(**{"policy.band_b": "0.500", "policy.band_c": "0.100"}))
    result = cfg.validate()
    assert not result.blocking          # allowed
    assert any(i.code == "bands_overlap" for i in result.warnings)
    view = params_view.params_view(cfg, result)
    assert view["bands_overlap"] is True
    assert view["valid"] is True


def test_the_non_overlapping_case_reports_no_overlap():
    """The defaults do not overlap, so the alert reflects that rather than a hard-coded literal."""
    view = params_view.params_view(params_view.parse_form(_form()))
    assert view["bands_overlap"] is False


def test_issue_messages_carry_no_literal_percent_sign():
    """A CONVENTION check, not a crash guard — the crash it once guarded against is gone.

    `app/i18n.py` used to install gettext with `newstyle=True`, which %-formatted the result of
    `_()`: a literal `%` was eaten before a letter and RAISED before a non-ASCII character. It now
    installs with `newstyle=False`, so a literal `%` is inert.

    The rule is still worth pinning: these strings all go through `_()` in the template, their
    English text is the msgid, and rewording one to add a `%` sign would invalidate its translation
    for no gain. (`%(name)s` in a static msgid is fine — `app/i18n.interpolate` substitutes it after
    translation — but none of these needs one.)"""
    for code, msg in params_view.ISSUE_MESSAGES.items():
        assert "%" not in msg, f"{code} carries a literal percent sign"


# ── The collapsed summary line (§2.3) ────────────────────────────────────────────────────────


def test_summary_line_is_computed_from_the_config():
    """The wireframe shape, from real values — not the sample literal it replaced."""
    assert params_view.summary_line(SimulationConfig()) == (
        "10.0 kWh · 5.0/5.0 kW · 90% · charge P1 · discharge D1 · energy only"
    )


def test_summary_line_moves_with_the_config():
    cfg = params_view.parse_form(
        _form(**{
            "battery.usable_capacity_kwh": "20",
            "battery.max_charge_kw": "7",
            "battery.max_discharge_kw": "3",
            "battery.roundtrip_efficiency": "85",
            "policy.charge_policy": "P2",
            "policy.discharge_policy": "D3",
        })
    )
    assert params_view.summary_line(cfg) == (
        "20.0 kWh · 7.0/3.0 kW · 85% · charge P2 · discharge D3 · energy only"
    )


def test_summary_line_survives_an_invalid_config():
    """A config holding a raw string still renders a line — the panel must draw while invalid."""
    cfg = params_view.parse_form(_form(**{"battery.usable_capacity_kwh": "abc"}))
    assert params_view.summary_line(cfg).startswith("abc kWh")


# ── UI gating (§2.3 "Without PV" / "Without cost simulation", §2.5) ──────────────────────────


def test_without_pv_p1_and_p3_are_disabled_not_dropped():
    """§2.3 "Without PV": all three charge policies are still LISTED, but P1/P3 come back
    disabled and carrying a reason, D1 is relabelled, pv_coupling is null, and the topology box
    is not drawn.

    The disable-don't-hide shape is a deliberate departure from §2.3's original "collapses to P2
    alone": an option that vanishes leaves the user unable to tell the feature exists, whereas a
    greyed one with a reason says what to change. `offerable_charge_policies()` still reports
    only P2 — it stayed the SIMULATION-side gate — and this view layer turns that into a
    `disabled` flag rather than a filter.
    """
    cfg = SimulationConfig(has_pv=False)
    view = params_view.params_view(cfg)
    assert [p["key"] for p in view["charge_policies"]] == ["P1", "P2", "P3"]
    disabled = {p["key"]: p["disabled"] for p in view["charge_policies"]}
    assert disabled == {"P1": True, "P2": False, "P3": True}
    # Each disabled option explains itself; the usable one carries no blurb.
    for p in view["charge_policies"]:
        assert bool(p["info"]) is p["disabled"]
    assert view["discharge_policies"][0]["label"] == "Discharge battery to cover house load"
    assert view["pv_coupling"] is None
    assert cfg.coupling is Coupling.AC
    # 1-phase connection + no PV → the box is empty, so it is not rendered (§2.3).
    assert "topology" not in view["sections"].split()


def test_with_pv_every_charge_policy_is_enabled():
    """The counterpart: with PV nothing is greyed, and no option carries a "needs PV" blurb."""
    view = params_view.params_view(SimulationConfig(has_pv=True))
    assert [p["key"] for p in view["charge_policies"]] == ["P1", "P2", "P3"]
    assert not any(p["disabled"] for p in view["charge_policies"])
    assert not any(p["info"] for p in view["charge_policies"])


def test_without_pv_a_three_phase_connection_still_shows_the_phase_selector():
    """§2.5(b) is INDEPENDENT of PV — it describes how the inverter sits across L1/L2/L3."""
    cfg = SimulationConfig(has_pv=False)
    cfg.grid.phases = 3
    view = params_view.params_view(cfg)
    assert view["battery_phases_offered"] is True
    assert "topology" in view["sections"].split()


def test_the_phase_selector_is_absent_on_a_one_phase_connection():
    view = params_view.params_view(SimulationConfig())   # appendix A default: 1 phase
    assert view["battery_phases_offered"] is False


def test_without_cost_simulation_the_guard_is_off_and_the_pricing_section_is_absent():
    """§2.3 "Without cost simulation": economic_guard hidden and FORCED off; no Pricing box."""
    cfg = SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=False)
    view = params_view.params_view(cfg)
    assert view["economic_guard"] is False
    assert "pricing" not in view["sections"].split()


def test_the_fuse_figure_is_the_rounded_display_value():
    """The connection prints `connection_capacity_kw_display`, never the exact cap §6.8 compares
    against.

    Panel ② printed it until §2′.1 moved the Grid connection box to the edit-workspace screen, so
    the assertion follows the figure to `workspace_edit_view._fmt_kw`. What is being pinned is
    unchanged: the display helper has ALREADY decided the precision, and re-padding to a fixed
    width would turn 17.3 into 17.30 and contradict appendix A's published figures.
    """
    from app.workspace_edit_view import connection_options

    def kw(cfg):
        return next(o["kw"] for o in connection_options(cfg) if o["selected"])

    cfg = SimulationConfig()
    assert kw(cfg) == "5.75"          # 1 × 25 A, appendix A's published figure
    cfg.grid.phases = 3
    assert kw(cfg) == "17.3"          # not 17.25, not 17.2


# ── check 18: the unsupported phase topology (§2.5b, §7.3) ───────────────────────────────────


def test_an_unsupported_phase_topology_is_flagged_only_where_the_selector_is_shown():
    """The soft block fires on a 3-phase connection; on 1-phase the stored value is inert (§2.5b).

    A stored `one_phase` on a 1-phase connection must not pin an approximation caveat to the
    results — the user was never offered the choice there.
    """
    cfg = SimulationConfig()
    cfg.topology.battery_phases = BatteryPhases.ONE_PHASE
    assert params_view.phase_topology_unsupported(cfg) is False   # 1-phase: not offered
    cfg.grid.phases = 3
    assert params_view.phase_topology_unsupported(cfg) is True


def test_approximated_records_a_deliberate_choice_and_is_cleared_when_supported():
    """§2.5b: `approximated` is the record of clicking Continue, never derived from the selection.

    So selecting an unsupported topology WITHOUT ticking Continue leaves it false; ticking it sets
    it; and moving back to the supported 3-phase inverter clears it, so no one carries a caveat
    they no longer earn.
    """
    three_phase = {"grid.phases": "3", "topology.battery_phases": "one_phase"}
    assert params_view.parse_form(_form(**three_phase)).topology.approximated is False
    accepted = params_view.parse_form(_form(**three_phase, **{"topology.approximated": "1"}))
    assert accepted.topology.approximated is True
    back = params_view.parse_form(
        _form(**{"grid.phases": "3", "topology.battery_phases": "three_phase",
                 "topology.approximated": "1"})
    )
    assert back.topology.approximated is False


# ── Persistence ──────────────────────────────────────────────────────────────────────────────


def test_persistence_round_trips_through_a_fresh_load(store):
    """save → (a fresh read, as after a restart) → the same values.

    `load()` reads the file every call and holds no module state, so a second call IS the restart
    case: nothing computed in this process carries over.
    """
    cfg = params_view.parse_form(
        _form(**{
            "battery.usable_capacity_kwh": "18.5",
            "battery.min_soc_pct": "5",
            "battery.max_charge_kw": "9",
            "grid.phases": "3",
            "grid.fuse_a": "35",
            "policy.charge_policy": "P2",
            "policy.discharge_policy": "D2",
            "policy.band_b": "0.075",
            "topology.pv_coupling": "ac",
        })
    )
    store.save(cfg, store.db.WORKSPACE_ID)

    back = store.load(store.db.WORKSPACE_ID)
    assert back.battery.usable_capacity_kwh == 18.5
    assert back.battery.min_soc_pct == 5
    assert back.battery.max_charge_kw == 9
    assert back.grid.phases == 3
    assert back.grid.fuse_a == 35
    assert back.policy.charge_policy is ChargePolicy.P2
    assert back.policy.discharge_policy is DischargePolicy.D2
    assert back.policy.band_b == 0.075
    assert back.topology.pv_coupling is PvCoupling.AC
    assert back.battery.coupling is Coupling.AC   # the selector sets both (§2.5a / §6.8)


def test_an_absent_file_gives_appendix_a_defaults(store):
    """The state a workspace is in before anything has been configured."""
    assert not store.config_path(store.db.WORKSPACE_ID).exists()
    assert store.load(store.db.WORKSPACE_ID) == SimulationConfig()


def test_a_corrupt_file_gives_defaults_and_does_not_raise(store):
    """Deliverable 1: a broken stored config must not take the page down.

    Four shapes of broken, because they fail at four different points: unparseable JSON, a JSON
    value that is not an object, a document whose groups are the wrong type, and an out-of-
    vocabulary enum.
    """
    store.save(SimulationConfig(), store.db.WORKSPACE_ID)
    for corrupt in ('{not json at all', '"a bare string"', '{"battery": 7}',
                    '{"policy": {"charge_policy": "P9"}}'):
        store.config_path(store.db.WORKSPACE_ID).write_text(corrupt, encoding="utf-8")
        cfg = store.load(store.db.WORKSPACE_ID)                       # must not raise
        assert cfg.battery.usable_capacity_kwh == 10.0
        assert cfg.policy.charge_policy is ChargePolicy.P1


def test_an_unknown_key_is_ignored_and_a_missing_group_falls_back(store):
    """Forward-compatibility WITHIN a version: an older document still yields a usable config.

    The version is the SAME one this build writes — see the next test for what a different
    version does. What is asserted here is that extra keys and absent groups are tolerated.
    """
    store.config_path(store.db.WORKSPACE_ID).write_text(
        json.dumps({"version": 1, "battery": {"usable_capacity_kwh": 12.0}, "unknown": 1}),
        encoding="utf-8",
    )
    cfg = store.load(store.db.WORKSPACE_ID)
    assert cfg.battery.usable_capacity_kwh == 12.0    # the value it did carry
    assert cfg.grid.fuse_a == 25.0                    # the group it did not
    assert cfg.battery.min_soc_pct == 10.0            # the field it did not


def test_a_document_from_an_unknown_version_yields_defaults(store):
    """`"version"` is CHECKED, not merely written.

    A future build may spell a field differently or mean something different by the same name;
    reading its document as v1 would silently apply values it did not mean. An unknown version is
    treated like any other unreadable document — appendix-A defaults — rather than being parsed
    field by field. An ABSENT version is still accepted as v1, so a hand-written minimal document
    parses.
    """
    store.config_path(store.db.WORKSPACE_ID).write_text(
        json.dumps({"version": 99, "battery": {"usable_capacity_kwh": 42.0}}),
        encoding="utf-8",
    )
    assert store.load(store.db.WORKSPACE_ID).battery.usable_capacity_kwh == 10.0    # the default, not 42

    store.config_path(store.db.WORKSPACE_ID).write_text(
        json.dumps({"battery": {"usable_capacity_kwh": 42.0}}), encoding="utf-8"
    )
    assert store.load(store.db.WORKSPACE_ID).battery.usable_capacity_kwh == 42.0    # no version → v1


def test_cost_only_params_are_retained_across_a_simulate_cost_toggle(store):
    """Appendix A: cost-only parameters are RETAINED, so re-enabling restores the user's setup.

    `economic_guard` is the one modelled so far, and it is the hard case: `_force_invariants`
    clears the STORED field the moment a config is built with cost simulation off, so the value
    cannot live on the config across the toggle. It lives in the document's `retained` block —
    see simconfig_store's module comment.

    `guard_submitted` is what distinguishes "the user unticked it" from "this form never drew the
    box": only the first may clear a stored True.
    """
    on = SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=True)
    store.save(on, store.db.WORKSPACE_ID, guard_submitted=True)
    assert store.load(store.db.WORKSPACE_ID).economic_guard is True

    # Cost simulation off: the guard is forced off in effect, and the panel does not draw the box.
    off = store.load(store.db.WORKSPACE_ID)
    off.simulate_cost = False
    store.save(off, store.db.WORKSPACE_ID)            # an energy-only submission
    assert store.load(store.db.WORKSPACE_ID).economic_guard is False       # forced, per §6.7

    # Back on: the user's choice is restored, not reset.
    again = store.load(store.db.WORKSPACE_ID)
    again.simulate_cost = True
    store.save(again, store.db.WORKSPACE_ID)
    assert store.load(store.db.WORKSPACE_ID).economic_guard is True


def test_unticking_the_guard_under_cost_simulation_really_clears_it(store):
    """The other half of the retention rule — retention must not become a value that cannot be
    turned off. A submission that DREW the checkbox and did not tick it clears the stored True."""
    store.save(
        SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=True),
        store.db.WORKSPACE_ID,
        guard_submitted=True,
    )
    cleared = store.load(store.db.WORKSPACE_ID)
    cleared.policy.economic_guard = False
    store.save(cleared, store.db.WORKSPACE_ID, guard_submitted=True)
    assert store.load(store.db.WORKSPACE_ID).economic_guard is False


def test_guard_was_submitted_needs_the_servers_agreement_not_only_the_forms_claim():
    """`sections` is client-controlled; `simulate_cost` is what the server itself last stored.

    Case 4 is the defect: with cost simulation off, the Pricing box is never DRAWN, so a form
    claiming it was is stale or forged. Believing it granted the box's authority to clear the
    retained `economic_guard` — precisely the reset appendix A forbids. The three legitimate
    cases must keep working, which is what the first three assertions are for.
    """
    cost_on = SimulationConfig(simulate_cost=True)
    cost_off = SimulationConfig(simulate_cost=False)
    drew = {"sections": "battery grid charge discharge pricing"}
    did_not = {"sections": "battery grid charge discharge"}

    assert params_view.guard_was_submitted(drew, cost_on) is True       # box drawn
    assert params_view.guard_was_submitted(did_not, cost_on) is False   # cost on, box not drawn
    assert params_view.guard_was_submitted(did_not, cost_off) is False  # never drawn
    assert params_view.guard_was_submitted(drew, cost_off) is False     # the forged claim


def test_save_is_atomic_and_leaves_no_temp_file(store):
    store.save(SimulationConfig(), store.db.WORKSPACE_ID)
    leftovers = list(store.config_path(store.db.WORKSPACE_ID).parent.glob("*.tmp"))
    assert leftovers == []


def test_concurrent_saves_neither_raise_nor_corrupt_the_document(store):
    """Overlapping writers must all succeed and leave one readable document.

    The regression this pins: `save()` used a FIXED temp filename shared by every writer, so two
    overlapping saves wrote the same path and the first `os.replace` consumed it out from under
    the second, which then raised `FileNotFoundError` — an `OSError`, which the route turns into
    a 500. Two browser tabs, or a double-click on "Calculate →", reach it. Measured at 44%
    failures over HTTP before the fix.

    The previous test above cannot catch this: it is single-threaded, so its `*.tmp` glob is
    empty for any implementation that unlinks or replaces its temp file at all.
    """
    import threading

    failures: list[BaseException] = []

    def hammer(capacity: float) -> None:
        for _ in range(30):
            try:
                store.save(SimulationConfig(battery=BatteryConfig(usable_capacity_kwh=capacity)), store.db.WORKSPACE_ID)
            except BaseException as exc:  # noqa: BLE001 — the assertion is that there are none
                failures.append(exc)

    threads = [threading.Thread(target=hammer, args=(float(i),)) for i in (1, 2, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert failures == []
    # The winner is whichever replace landed last, but it must be a COMPLETE document from one
    # writer — never a blend or a truncation.
    doc = json.loads(store.config_path(store.db.WORKSPACE_ID).read_text(encoding="utf-8"))
    assert doc["battery"]["usable_capacity_kwh"] in (1.0, 2.0, 3.0)
    assert store.load(store.db.WORKSPACE_ID).battery.usable_capacity_kwh in (1.0, 2.0, 3.0)
    # And no writer left its temp file behind.
    assert list(store.config_path(store.db.WORKSPACE_ID).parent.glob("*.tmp")) == []


def test_the_saved_document_uses_the_same_mode_as_the_rest_of_the_data_dir(store):
    """`tempfile.mkstemp` creates 0600; every other file in the data dir is created at the umask.

    Not a security property — the document holds no secret — but an inconsistent mode inside one
    data directory is a surprise for anyone backing it up or reading it as another user. The
    control is a file written the ordinary way in the same directory, which is exactly what the
    dataset layer does, so this compares against the operator's actual umask rather than a
    hardcoded 0644.
    """
    import stat

    store.save(SimulationConfig(), store.db.WORKSPACE_ID)
    control = store.config_path(store.db.WORKSPACE_ID).parent / "control.txt"
    control.write_text("x", encoding="utf-8")

    assert stat.S_IMODE(store.config_path(store.db.WORKSPACE_ID).stat().st_mode) == stat.S_IMODE(
        control.stat().st_mode
    )


def test_the_summary_reports_the_effective_charge_policy_not_the_stored_one():
    """A stored P3 with no PV runs as P2 (§6.6), and the summary must say so.

    Caught by eyeballing a rendered no-PV page: the collapsed line read `charge P3` while the
    charge box below showed P3 greyed out and P2 selected — the summary contradicting the panel
    it summarises. The stored answer is deliberately preserved (turning PV back on restores the
    user's choice), so this is a DISPLAY fix, not a normalisation.
    """
    cfg = SimulationConfig(has_pv=False, policy=PolicyConfig(charge_policy=ChargePolicy.P3))
    assert cfg.policy.charge_policy is ChargePolicy.P3, "the stored answer must be preserved"
    assert cfg.effective_charge_policy is ChargePolicy.P2
    assert "charge P2" in params_view.summary_line(cfg)
    assert "charge P3" not in params_view.summary_line(cfg)


def test_no_disabled_charge_policy_is_ever_rendered_as_selected():
    """The radio group must always have exactly one enabled, checked option.

    Checking a disabled radio both misreports what will run and leaves the box with no usable
    selection — the user sees a greyed tick they cannot move.
    """
    for stored in (ChargePolicy.P1, ChargePolicy.P2, ChargePolicy.P3):
        view = params_view.params_view(
            SimulationConfig(has_pv=False, policy=PolicyConfig(charge_policy=stored))
        )
        selected = [p for p in view["charge_policies"] if p["selected"]]
        assert len(selected) == 1, f"stored={stored}: expected exactly one selected option"
        assert selected[0]["disabled"] is False, f"stored={stored}: a disabled option was checked"
        assert selected[0]["key"] == "P2"


def test_with_pv_the_stored_charge_policy_is_reported_unchanged():
    """The counterpart: with PV, effective == stored for every policy."""
    for stored in (ChargePolicy.P1, ChargePolicy.P2, ChargePolicy.P3):
        cfg = SimulationConfig(has_pv=True, policy=PolicyConfig(charge_policy=stored))
        assert cfg.effective_charge_policy is stored
        assert f"charge {stored.value}" in params_view.summary_line(cfg)


# ── §2.3's Pricing box ───────────────────────────────────────────────────────────────────────


# The energy-only `_form` plus every `pricing.*` control, in ONE submission carrying every section
# marker. No live screen posts exactly this shape any more — §2′.1 split the controls across two,
# with the results screen posting `setup battery charge discharge topology pricing` and the edit
# screen `grid pricing_advanced`. It is kept combined DELIBERATELY, because what these tests
# exercise is `parse_form`, which is shared by both screens and must coerce every path it declares
# whichever form carries it. The per-screen marker discipline is asserted where it lives: by
# `test_the_sections_marker_names_exactly_the_checkboxes_this_render_draws` against the real
# renders, and by `_sections_for`'s own tests below.
def _cost_form(**overrides) -> dict:
    base = _form()
    base["sections"] = (
        "setup battery grid charge discharge topology pricing pricing_advanced"
    )
    base["setup.simulate_cost"] = "yes"
    base.update({
        "pricing.contract": "dynamic",
        "pricing.supplier_markup": "0.0205",
        "pricing.energy_tax_excl_vat": "0.09161",
        "pricing.vat_rate": "21",
        "pricing.feedin_alpha": "0.50",
        "pricing.feedin_beta": "0.0000",
        "pricing.tlk_mode": "flat",
        "pricing.tlk_eur_per_kwh": "0.0400",
        "pricing.dal_start_hour": "23",
        "pricing.dal_end_hour": "7",
        "pricing.dal_weekends": "1",
        "pricing.degradation_eur_per_kwh": "0.0000",
    })
    base.update(overrides)
    return base


# §2′.1 moved the Pricing box to the edit-workspace screen, so the RENDER half of these round-trips
# is `workspace_edit_view`'s, not `params_view`'s. `parse_form` — the coercion half — is still
# shared by both screens and is still what the tests below drive, so the pairs stay here together
# rather than being split across two files by which module happens to draw the input.
def _rendered(cfg, result=None) -> dict:
    """`pricing.*` fields as the edit screen renders them, keyed by dotted path."""
    from app import workspace_edit_view

    return workspace_edit_view.edit_view(cfg, "Our house", result=result)["pricing_advanced"]


def _contracts(cfg) -> list[dict]:
    """The contract radios as the edit screen offers them."""
    from app import workspace_edit_view

    return workspace_edit_view.edit_view(cfg, "Our house")["contracts"]


def _tlk_modes(cfg) -> list[dict]:
    """The terugleverkosten-mode radios as the edit screen offers them."""
    from app import workspace_edit_view

    return workspace_edit_view.edit_view(cfg, "Our house")["tlk_modes"]


def test_every_pricing_field_coerces_and_round_trips():
    """One submission carrying the whole box, checked field by field against what it should store.

    Asserted as one test rather than parametrised because the failure mode being guarded against
    is a field missing from `FIELDS` altogether — a per-field test would simply not exist for the
    field that was forgotten, and would pass.
    """
    cfg = params_view.parse_form(_cost_form(**{
        "pricing.supplier_markup": "0.0300",
        "pricing.energy_tax_excl_vat": "0.1000",
        "pricing.feedin_alpha": "1.00",
        "pricing.feedin_beta": "-0.0200",
        "pricing.tlk_eur_per_kwh": "0.0500",
        "pricing.dal_start_hour": "22",
        "pricing.dal_end_hour": "6",
        "pricing.degradation_eur_per_kwh": "0.0150",
    }))
    pr = cfg.pricing
    assert cfg.simulate_cost is True
    assert pr.contract is Contract.DYNAMIC
    assert pr.supplier_markup == 0.03
    assert pr.energy_tax_excl_vat == 0.1
    assert pr.feedin_alpha == 1.0
    assert pr.feedin_beta == -0.02          # signed on purpose (§6.5's "Spot minus fee" preset)
    assert pr.tlk_mode is TlkMode.FLAT
    assert pr.tlk_eur_per_kwh == 0.05
    assert pr.dal_start_hour == 22
    assert pr.dal_end_hour == 6
    assert pr.dal_weekends is True
    assert pr.degradation_eur_per_kwh == 0.015
    assert not cfg.validate().blocking


def test_vat_is_entered_as_a_percentage_and_stored_as_a_fraction():
    """21 in the form, 0.21 on the config, 21 back in the input.

    The same trap as `roundtrip_efficiency`, and worse here: `import_price` multiplies by
    `1 + vat_rate`, so storing 21 instead of 0.21 would price every imported kWh at 22× its cost
    without raising anything. Both directions are asserted together so they cannot drift apart.
    """
    cfg = params_view.parse_form(_cost_form(**{"pricing.vat_rate": "21"}))
    assert cfg.pricing.vat_rate == pytest.approx(0.21)
    assert _rendered(cfg)["pricing.vat_rate"]["value"] == "21"

    # And a non-default value, so the test cannot pass on the appendix-A default alone.
    other = params_view.parse_form(_cost_form(**{"pricing.vat_rate": "9"}))
    assert other.pricing.vat_rate == pytest.approx(0.09)
    assert _rendered(other)["pricing.vat_rate"]["value"] == "9"


def test_feedin_alpha_is_not_percent_typed():
    """α is a FRACTION in the form as well as on the config — §2.3's wireframe shows `α [ 0.50 ]`.

    Worth pinning next to the VAT test: α and VAT sit two rows apart in the same box and are both
    bounded to [0, 1], so treating α as percent-typed is the natural mistake. It would store 0.005
    for a typed 0.50 and halve nothing while looking plausible.
    """
    cfg = params_view.parse_form(_cost_form(**{"pricing.feedin_alpha": "0.50"}))
    assert cfg.pricing.feedin_alpha == 0.50
    assert _rendered(cfg)["pricing.feedin_alpha"]["value"] == "0.50"


def test_a_bad_pricing_value_survives_into_the_re_render_with_its_error():
    """The error contract, applied to the new box: the raw string is kept and keyed to its input."""
    cfg = params_view.parse_form(_cost_form(**{"pricing.vat_rate": "abc"}))
    assert cfg.pricing.vat_rate == "abc"          # unscaled — `_pct_to_frac` does not divide a str
    result = cfg.validate()
    assert "pricing.vat_rate" in result.fields_with_errors()
    vat = _rendered(cfg, result)["pricing.vat_rate"]
    assert vat["value"] == "abc"
    assert vat["invalid"] is True


def test_a_bad_pricing_value_does_not_block_an_energy_only_run():
    """§2.3 / `validate()`: the pricing checks are gated on `simulate_cost`.

    A field the panel does not draw must not refuse a run — the user has no input to fix it in.
    The value is still STORED (appendix A's retention), so turning cost simulation on surfaces the
    issue that was always latent in it.
    """
    cfg = params_view.parse_form(_cost_form(**{"pricing.vat_rate": "abc"}))
    cfg.simulate_cost = False
    assert not cfg.validate().blocking
    cfg.simulate_cost = True
    assert cfg.validate().blocking


def test_the_pricing_box_is_absent_from_the_sections_without_cost_simulation():
    """`sections` is the machine-readable half of "the whole box is absent" (§2.3)."""
    assert "pricing" not in params_view.params_view(SimulationConfig(simulate_cost=False))[
        "sections"
    ].split()
    assert "pricing" in params_view.params_view(SimulationConfig(simulate_cost=True))[
        "sections"
    ].split()


def test_fixed_and_variable_are_pending_and_dynamic_is_not():
    """§2.3 lists all three contract types; only DYNAMIC has a rate source behind it (§6.5).

    The pending pair is DISABLED, not dropped, and each carries the feature key the interest route
    accepts — asserted against `app.features` rather than against a literal, so a key renamed in
    one place and not the other fails here.
    """
    from app import features

    by_key = {c["key"]: c for c in _contracts(SimulationConfig(simulate_cost=True))}
    assert set(by_key) == {"dynamic", "fixed", "variable"}
    assert by_key["dynamic"]["pending"] is False
    assert by_key["dynamic"]["feature_key"] is None
    for key in ("fixed", "variable"):
        assert by_key[key]["pending"] is True
        assert features.is_known(by_key[key]["feature_key"])


def _settlements(cfg) -> list[dict]:
    """The supplier-settlement radios as the edit screen offers them."""
    from app import workspace_edit_view

    return workspace_edit_view.edit_view(cfg, "Our house")["settlements"]


def test_the_settlement_radios_offer_both_answers_with_hourly_preselected():
    """Neither member is pending, unlike the two selectors beside it — both are implemented.

    So there is no `feature_key` to check and nothing is disabled; what matters is that the
    shipped config comes back with appendix A's `hourly` marked, since that is the answer that
    leaves §6.16's caveat suppressed.
    """
    by_key = {s["key"]: s for s in _settlements(SimulationConfig(simulate_cost=True))}
    assert set(by_key) == {"hourly", "quarter_hourly"}
    assert by_key["hourly"]["selected"] is True
    assert by_key["quarter_hourly"]["selected"] is False
    assert all("pending" not in s and "feature_key" not in s for s in by_key.values())


def test_a_stored_quarter_hourly_settlement_is_reported_as_selected():
    """The round-trip half: what is stored is what the screen shows, not the default."""
    cfg = SimulationConfig(simulate_cost=True)
    cfg.pricing.supplier_settlement = SupplierSettlement.QUARTER_HOURLY
    selected = [s for s in _settlements(cfg) if s["selected"]]
    assert [s["key"] for s in selected] == ["quarter_hourly"]


def test_the_settlement_radio_parses_and_an_absent_group_keeps_the_stored_answer():
    """`parse_form` reads the radio, and a submission without it inherits rather than resets.

    The `in form` guard is what makes the second half true. A radio group with a checked default
    always submits from the real screen, so absence means a partial POST — and a partial POST
    must not silently rewrite an answer the user gave on a screen it did not carry.
    """
    cfg = params_view.parse_form(
        _cost_form(**{"pricing.supplier_settlement": "quarter_hourly"})
    )
    assert cfg.pricing.supplier_settlement is SupplierSettlement.QUARTER_HOURLY

    stored = SimulationConfig(simulate_cost=True)
    stored.pricing.supplier_settlement = SupplierSettlement.QUARTER_HOURLY
    kept = params_view.parse_form(_cost_form(), base=stored)
    assert kept.pricing.supplier_settlement is SupplierSettlement.QUARTER_HOURLY

    # An unrecognised value keeps the stored answer too — `_enum_or_keep`, not a default.
    bad = params_view.parse_form(
        _cost_form(**{"pricing.supplier_settlement": "per_second"}), base=stored
    )
    assert bad.pricing.supplier_settlement is SupplierSettlement.QUARTER_HOURLY


def test_tiered_terugleverkosten_is_pending_and_flat_is_not():
    """Same treatment for `TlkMode`: §2.3 draws both rows, §6.5 builds only FLAT."""
    from app import features

    by_key = {m["key"]: m for m in _tlk_modes(SimulationConfig(simulate_cost=True))}
    assert by_key["flat"]["pending"] is False
    assert by_key["tiered"]["pending"] is True
    assert features.is_known(by_key["tiered"]["feature_key"])


def test_a_stored_pending_contract_is_still_reported_as_selected():
    """A hand-edited document can hold `variable`, which no UI path can produce (followup H6).

    Showing `dynamic` selected instead would misreport what is about to run. The box reports the
    stored answer and leaves the radio disabled, which is honest in both directions.
    """
    cfg = SimulationConfig(simulate_cost=True)
    cfg.pricing.contract = Contract.VARIABLE
    selected = [c for c in _contracts(cfg) if c["selected"]]
    assert [c["key"] for c in selected] == ["variable"]
    assert selected[0]["pending"] is True


def test_the_feedin_pair_round_trips_without_the_preset_shortcut():
    """α and β remain fully editable now that §6.5's preset SELECT is gone.

    That select was a way of TYPING the two fields — client-side only, never a stored value — and
    it lived in the Pricing box on the results screen. §2′.1 moved the box to the edit-workspace
    screen, which renders α and β as plain numeric fields and has no equivalent select, so the
    shortcut is currently absent from the app rather than relocated (recorded as a follow-up in
    changelog/20260728-results-screen-leftover-boxes.md).

    This test replaces the one that asserted the preset rows. What it pins is the part that
    actually matters and that the removal could have broken: both values still coerce, still
    store and still render back. A user who wants "Legal minimum" now types 0.50 and 0.0000 —
    which is exactly what the preset wrote into the two inputs.
    """
    # Appendix A's default pair IS §6.5's "Legal minimum" row.
    default = SimulationConfig(simulate_cost=True)
    assert (default.pricing.feedin_alpha, default.pricing.feedin_beta) == (0.50, 0.0000)

    cfg = params_view.parse_form(_cost_form(**{
        "pricing.feedin_alpha": "0.73",
        "pricing.feedin_beta": "0.0031",
    }))
    assert (cfg.pricing.feedin_alpha, cfg.pricing.feedin_beta) == (0.73, 0.0031)
    rendered = _rendered(cfg)
    assert rendered["pricing.feedin_alpha"]["value"] == "0.73"
    assert rendered["pricing.feedin_beta"]["value"] == "0.0031"


def test_economic_guard_round_trips_under_cost_simulation():
    """It is a real control now: submitted → stored, unticked → cleared, forced off without cost."""
    on = params_view.parse_form(_cost_form(**{"policy.economic_guard": "1"}))
    assert on.policy.economic_guard is True
    assert on.economic_guard is True                  # the read path agrees, cost being on

    off = params_view.parse_form(_cost_form())        # the box was drawn and left unticked
    assert off.policy.economic_guard is False

    # Energy-only: the control is absent, so the read path forces it off whatever is stored. Note
    # the `setup` marker without a `pricing` one — that IS the form the panel renders once the
    # band's answer is "no", and the shape the retention rule has to survive.
    energy_only = params_view.parse_form(
        _form(sections="setup battery grid charge discharge topology",
              **{"setup.simulate_cost": "no"}),
        on,
    )
    assert energy_only.simulate_cost is False
    assert energy_only.economic_guard is False


def test_the_summary_line_names_the_contract_with_cost_on():
    """§2.1: the final clause is `energy only`, or the contract name when cost simulation is on."""
    assert params_view.summary_line(SimulationConfig(simulate_cost=False)).endswith("energy only")
    assert params_view.summary_line(SimulationConfig(simulate_cost=True)).endswith("dynamic")

    cfg = SimulationConfig(simulate_cost=True)
    cfg.pricing.contract = Contract.FIXED
    assert params_view.summary_line(cfg).endswith("fixed")


def test_the_setup_band_radio_toggles_simulate_cost():
    """Followup B2: the band is editable now, which is what makes the Pricing box reachable.

    Read only when the submission declares the `setup` section, so a partial POST that does not
    carry the band cannot silently answer "no" for the user.
    """
    on = params_view.parse_form(_cost_form())
    assert on.simulate_cost is True

    off = params_view.parse_form(_cost_form(**{"setup.simulate_cost": "no"}), on)
    assert off.simulate_cost is False

    # No `setup` marker: the band was not part of this submission, so the answer is inherited.
    inherited = params_view.parse_form({"sections": "battery"}, on)
    assert inherited.simulate_cost is True


def test_the_pricing_values_survive_an_energy_only_submission(store):
    """Appendix A's retention rule, end to end and through disk.

    The whole box is absent with cost simulation off, so an energy-only POST carries none of these
    fields — they can only survive by `parse_form` inheriting them from the stored config and by
    `to_dict` writing them unconditionally. This is the reason both of those rules exist.
    """
    configured = params_view.parse_form(_cost_form(**{
        "pricing.supplier_markup": "0.0777",
        "pricing.vat_rate": "9",
        "pricing.feedin_beta": "-0.0200",
        "pricing.dal_start_hour": "21",
        "pricing.degradation_eur_per_kwh": "0.0250",
        "policy.economic_guard": "1",
    }))
    store.save(configured, store.db.WORKSPACE_ID, guard_submitted=True)

    # Turn cost simulation off through the band, submitting the form the panel then renders:
    # no `pricing` section, and none of the pricing fields.
    off = params_view.parse_form(
        _form(sections="setup battery grid charge discharge topology",
              **{"setup.simulate_cost": "no"}),
        store.load(store.db.WORKSPACE_ID),
    )
    assert off.simulate_cost is False
    store.save(off, store.db.WORKSPACE_ID, guard_submitted=params_view.guard_was_submitted(
        {"sections": "setup battery grid charge discharge topology"}, configured
    ))

    back = store.load(store.db.WORKSPACE_ID)
    assert back.pricing.supplier_markup == 0.0777
    assert back.pricing.vat_rate == pytest.approx(0.09)
    assert back.pricing.feedin_beta == -0.02
    assert back.pricing.dal_start_hour == 21
    assert back.pricing.degradation_eur_per_kwh == 0.025
    assert back.economic_guard is False        # forced off, but only in effect

    # Turning it back on restores every one of them, the guard included.
    on_again = params_view.parse_form(
        _form(sections="setup battery grid charge discharge topology",
              **{"setup.simulate_cost": "yes"}),
        back,
    )
    store.save(on_again, store.db.WORKSPACE_ID)
    restored = store.load(store.db.WORKSPACE_ID)
    assert restored.simulate_cost is True
    assert restored.pricing.supplier_markup == 0.0777
    assert restored.economic_guard is True     # the `retained` slot did its job
