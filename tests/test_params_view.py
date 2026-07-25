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
    Coupling,
    DischargePolicy,
    PolicyConfig,
    PvCoupling,
    SimulationConfig,
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
    """`app/i18n.py` installs gettext with newstyle=True, so a literal `%` in a translated string
    is eaten before a letter and RAISES before a non-ASCII character. These strings all go through
    `_()` in the template, so none may contain one. (`%(name)s` in a STATIC msgid is fine — that is
    what newstyle exists for — but none of these needs one.)"""
    for code, msg in params_view.ISSUE_MESSAGES.items():
        assert "%" not in msg, f"{code} carries a literal percent sign"


# ── The collapsed summary line (§2.3) ────────────────────────────────────────────────────────


def test_summary_line_is_computed_from_the_config():
    """The wireframe shape, from real values — not the sample literal it replaced."""
    assert params_view.summary_line(SimulationConfig()) == (
        "10.0 kWh · 5.0/5.0 kW · 90% · charge P3 · discharge D1 · energy only"
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
    """Panel ② prints `connection_capacity_kw_display`, never the exact cap §6.8 compares against."""
    view = params_view.params_view(SimulationConfig())
    assert view["grid"]["max_import"] == "5.75"          # 1 × 25 A, appendix A's published figure
    cfg = SimulationConfig()
    cfg.grid.phases = 3
    assert params_view.params_view(cfg)["grid"]["max_import"] == "17.3"   # not 17.25, not 17.2


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
    store.save(cfg)

    back = store.load()
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
    assert not store.config_path().exists()
    assert store.load() == SimulationConfig()


def test_a_corrupt_file_gives_defaults_and_does_not_raise(store):
    """Deliverable 1: a broken stored config must not take the page down.

    Four shapes of broken, because they fail at four different points: unparseable JSON, a JSON
    value that is not an object, a document whose groups are the wrong type, and an out-of-
    vocabulary enum.
    """
    store.save(SimulationConfig())
    for corrupt in ('{not json at all', '"a bare string"', '{"battery": 7}',
                    '{"policy": {"charge_policy": "P9"}}'):
        store.config_path().write_text(corrupt, encoding="utf-8")
        cfg = store.load()                       # must not raise
        assert cfg.battery.usable_capacity_kwh == 10.0
        assert cfg.policy.charge_policy is ChargePolicy.P3


def test_an_unknown_key_is_ignored_and_a_missing_group_falls_back(store):
    """Forward-compatibility WITHIN a version: an older document still yields a usable config.

    The version is the SAME one this build writes — see the next test for what a different
    version does. What is asserted here is that extra keys and absent groups are tolerated.
    """
    store.config_path().write_text(
        json.dumps({"version": 1, "battery": {"usable_capacity_kwh": 12.0}, "unknown": 1}),
        encoding="utf-8",
    )
    cfg = store.load()
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
    store.config_path().write_text(
        json.dumps({"version": 99, "battery": {"usable_capacity_kwh": 42.0}}),
        encoding="utf-8",
    )
    assert store.load().battery.usable_capacity_kwh == 10.0    # the default, not 42

    store.config_path().write_text(
        json.dumps({"battery": {"usable_capacity_kwh": 42.0}}), encoding="utf-8"
    )
    assert store.load().battery.usable_capacity_kwh == 42.0    # no version → v1


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
    store.save(on, guard_submitted=True)
    assert store.load().economic_guard is True

    # Cost simulation off: the guard is forced off in effect, and the panel does not draw the box.
    off = store.load()
    off.simulate_cost = False
    store.save(off)                                   # an energy-only submission
    assert store.load().economic_guard is False       # forced, per §6.7

    # Back on: the user's choice is restored, not reset.
    again = store.load()
    again.simulate_cost = True
    store.save(again)
    assert store.load().economic_guard is True


def test_unticking_the_guard_under_cost_simulation_really_clears_it(store):
    """The other half of the retention rule — retention must not become a value that cannot be
    turned off. A submission that DREW the checkbox and did not tick it clears the stored True."""
    store.save(
        SimulationConfig(policy=PolicyConfig(economic_guard=True), simulate_cost=True),
        guard_submitted=True,
    )
    cleared = store.load()
    cleared.policy.economic_guard = False
    store.save(cleared, guard_submitted=True)
    assert store.load().economic_guard is False


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
    store.save(SimulationConfig())
    leftovers = list(store.config_path().parent.glob("*.tmp"))
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
                store.save(SimulationConfig(battery=BatteryConfig(usable_capacity_kwh=capacity)))
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
    doc = json.loads(store.config_path().read_text(encoding="utf-8"))
    assert doc["battery"]["usable_capacity_kwh"] in (1.0, 2.0, 3.0)
    assert store.load().battery.usable_capacity_kwh in (1.0, 2.0, 3.0)
    # And no writer left its temp file behind.
    assert list(store.config_path().parent.glob("*.tmp")) == []


def test_the_saved_document_uses_the_same_mode_as_the_rest_of_the_data_dir(store):
    """`tempfile.mkstemp` creates 0600; every other file in the data dir is created at the umask.

    Not a security property — the document holds no secret — but an inconsistent mode inside one
    data directory is a surprise for anyone backing it up or reading it as another user. The
    control is a file written the ordinary way in the same directory, which is exactly what the
    dataset layer does, so this compares against the operator's actual umask rather than a
    hardcoded 0644.
    """
    import stat

    store.save(SimulationConfig())
    control = store.config_path().parent / "control.txt"
    control.write_text("x", encoding="utf-8")

    assert stat.S_IMODE(store.config_path().stat().st_mode) == stat.S_IMODE(
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
