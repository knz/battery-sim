"""The edit-workspace screen and its two routes (specs/20-workspaces-ux.md §2′.4, §2′.6, §2′.8).

Phase 3 added `GET /w/{id}/edit` and `POST /w/{id}/edit`: the household's fixed facts — title,
postcode, grid connection and contract. What these tests pin is the part a status code cannot
see, and in every case it is a property the spec states explicitly and the obvious implementation
gets wrong:

  * **The connection dropdown does not SNAP.** A stored `(phases, fuse_a)` matching none of
    §2′.4's ten presets renders as an extra, marked, SELECTED entry. Rendering the nearest preset
    instead would raise `max_import_kw` — 1×20 A is 4.6 kW and 1×25 A is 5.75 kW — silently, on a
    screen opened to change something else. This is the single easiest thing here to get wrong,
    because snapping looks tidier and produces a shorter list.
  * **The Contract box is drawn with cost simulation OFF**, never greyed. §2′.4 calls this a
    deliberate exception to §2.3's Inapplicable rule; hiding it under `simulate_cost` is the
    intuitive move and the spec forbids it, partly because this box is what UNBLOCKS the cost
    toggle (§2′.6) — the two would otherwise wait on each other.
  * **`pricing_configured` is set here and never cleared automatically** (§2′.6). The store's
    `save(pricing_configured=None)` means "carry forward", so the failure mode to catch is a
    LATER save — a panel-② parameter change — resetting a flag it should not touch.
  * **A collapsed advanced pane round-trips.** The panes are `<details>`, so their inputs stay in
    the DOM and in the form body; a conditional render would submit a closed pane as cleared
    fields and wipe every override. Asserted from the rendered markup, since that is where the
    property lives.
  * **A blocking submission re-renders what the user TYPED**, not what is stored — the same
    guarantee `POST /params` gives, and the one thing a re-render from the stored config would
    silently break.
  * **The `sections` marker claims only the checkboxes this screen draws.** Inheritance protects
    ordinary fields, but checkboxes are its documented exception and are gated on that marker
    instead — so an over-claim CLEARS stored state. Phase 3 shipped two: the marker named
    `pricing`, which is panel ②'s `policy.economic_guard`, and the `topology.approximated` branch
    was ungated. The last group of tests covers both, plus the untick behaviour a merely-narrower
    marker would have cost.

The harness is the same shape as `tests/test_workspace_list.py`'s: a client over an empty temp
data dir plus the modules that write into it, with nothing seeded, so each test arranges exactly
the configuration it is about.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A client over an empty temp data dir, plus the modules that write into it.

    `monkeypatch.setenv` before any import that resolves the data dir, as everywhere else in this
    suite (and note followup I4: an in-test `monkeypatch.undo()` would redirect the rest of the
    test at the developer's real `./data`).
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import main, simconfig_store, workspaces

    return TestClient(main.app), {
        "simconfig_store": simconfig_store,
        "workspaces": workspaces,
    }


def _seed(mod, workspace_id: str = "w1", title: str = "Our house"):
    """Create the workspace row and return its (appendix-A default) config."""
    mod["workspaces"].create(title, workspace_id=workspace_id)
    return mod["simconfig_store"].load(workspace_id)


def _store(mod, cfg, workspace_id: str = "w1") -> None:
    """Persist `cfg`, cloned so the caller's object is not the one the store normalises."""
    mod["simconfig_store"].save(mod["simconfig_store"].clone(cfg), workspace_id)


def _backdate(mod, workspace_id: str, when: datetime) -> None:
    """Set the row's stored `updated_at` to a fixed past instant, writing the column directly.

    There is no app-level way to do this — `touch()` writes "now" and nothing else writes the
    column — so the test reaches for SQL. That is deliberate rather than a shortcut: the point of
    back-dating is to create a value the route's own clock CANNOT produce, which makes a
    subsequent `>` a real constraint on the route instead of a restatement of the fact that time
    moves forward. The alternative, freezing the clock, would mean patching `workspaces._now` and
    asserting against the frozen value — equivalent in strength but coupled to a private helper.
    """
    from app import db

    with db.connect() as conn:
        conn.execute(
            "UPDATE workspaces SET updated_at = ? WHERE id = ?",
            (when.isoformat(), workspace_id),
        )


def _select(html: str) -> str:
    """Just the connection `<select>`, so an assertion about it cannot be met by other markup."""
    m = re.search(r'<select name="grid\.connection".*?</select>', html, re.S)
    assert m is not None, "no connection dropdown on the edit screen"
    return m.group(0)


def _options(html: str) -> list[tuple[str, bool, str]]:
    """The dropdown as `(value, selected, label)` triples, in render order."""
    out = []
    for m in re.finditer(r'<option value="([^"]*)"([^>]*)>(.*?)</option>', _select(html), re.S):
        value, attrs, label = m.group(1), m.group(2), m.group(3)
        out.append((value, "selected" in attrs, label.strip()))
    return out


def _footer(html: str) -> str:
    """Just the footer `<div data-footer>` (§2′.8), so a mode assertion is about the buttons.

    Scoped deliberately: the page's inline script carries comments naming both modes' buttons, so
    `"Previous" not in html` over the whole document asserts nothing about which footer was drawn.
    """
    m = re.search(r"<div [^>]*data-footer.*?</div>", html, re.S)
    assert m is not None, "no footer on the edit screen"
    return m.group(0)


def _form(**over) -> dict:
    """A complete submission, as the browser sends it — every input on the screen is present.

    Written out in full rather than built from the render, because "the collapsed pane's inputs
    are still submitted" is a property some of these tests are ABOUT: a helper that scraped the
    rendered form would make the assertion circular.
    """
    body = {
        # Exactly what the template emits — pinned by `test_the_edit_screen_claims_only_the_
        # checkbox_it_draws`, because a helper that over-claims here would hide the review's
        # defect 1 rather than reproduce it.
        "sections": "grid pricing_advanced",
        "title": "Our house",
        "postcode": "",
        "grid.connection": "1:25",
        "grid.max_import_kw_override": "",
        "grid.max_export_kw": "",
        "pricing.contract": "dynamic",
        "pricing.supplier_markup": "0.0205",
        "pricing.energy_tax_excl_vat": "0.09161",
        "pricing.vat_rate": "21",
        "pricing.feedin_alpha": "0.50",
        "pricing.feedin_beta": "0.0000",
        "pricing.tlk_eur_per_kwh": "0.0400",
        "pricing.dal_start_hour": "23",
        "pricing.dal_end_hour": "7",
        "pricing.degradation_eur_per_kwh": "0.0000",
    }
    body.update(over)
    return body


# ── The connection dropdown (§2′.4) ───────────────────────────────────────────────────────────

def test_the_dropdown_offers_exactly_the_ten_presets(env):
    """§2′.4: ten options, and no "other…" and no free-text fuse field.

    The list is closed on purpose — these are the connections a Dutch household can actually
    have, so a value outside them is a mistake rather than an unusual case, and the free-text
    field it replaces mostly invited typos.
    """
    client, mod = env
    _seed(mod)

    options = _options(client.get("/w/w1/edit").text)
    assert [v for v, _s, _l in options] == [
        "1:10", "1:25", "1:35", "1:50",
        "3:25", "3:35", "3:40", "3:50", "3:63", "3:80",
    ]


def test_each_option_shows_its_derived_capacity(env):
    """§2′.4: every entry carries `connection_capacity_kw_display`, the ROUNDED figure.

    The exact value is what §6.8 step 6 compares the net flow against and is never printed. Both
    figures the specs publish are checked: 5.75 (two decimals, below 10 kW) and 17.3 (one, at or
    above), which is the magnitude-conditional rule `connection_capacity_kw_display` implements.
    """
    client, mod = env
    _seed(mod)

    labels = {v: label for v, _s, label in _options(client.get("/w/w1/edit").text)}
    assert "5.75 kW" in labels["1:25"]
    assert "17.3 kW" in labels["3:25"]


@pytest.mark.parametrize("phases,fuse_a", [(1, 20.0), (3, 16.0), (1, 6.0)])
def test_an_off_list_connection_renders_as_an_extra_selected_entry_not_snapped(
    env, phases, fuse_a
):
    """§2′.4, the rule this screen exists to get right: a stored off-list pair renders as ITSELF.

    Three things are asserted together, because any one of them alone would pass against a broken
    implementation: the eleven entries (so the presets were not replaced), the stored pair being
    among them AND selected (so it was not merely appended and ignored), and no PRESET being
    selected (so it was not snapped).

    Snapping is not a cosmetic difference. `grid.fuse_a` feeds `max_import_kw` directly, so
    turning a stored 1×20 A into 1×25 A raises the household's import cap by 1.15 kW and changes
    the simulated answer, without anything on screen saying so.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.grid.phases, cfg.grid.fuse_a = phases, fuse_a
    _store(mod, cfg)

    options = _options(client.get("/w/w1/edit").text)
    stored = f"{phases}:{int(fuse_a)}"

    assert len(options) == 11, "the ten presets plus the stored combination"
    selected = [(v, label) for v, is_sel, label in options if is_sel]
    assert len(selected) == 1 and selected[0][0] == stored
    # And it is MARKED as the user's own value, not passed off as a standard connection.
    assert "stored setting" in selected[0][1]


def test_a_listed_connection_adds_no_extra_entry(env):
    """The other half: an on-list stored pair gets exactly the ten presets, one of them selected.

    Without this the previous test is satisfied by an implementation that always appends the
    stored pair, which would show `1 × 25 A` twice on the common case.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.grid.phases, cfg.grid.fuse_a = 3, 63.0
    _store(mod, cfg)

    options = _options(client.get("/w/w1/edit").text)
    assert len(options) == 10
    assert [v for v, is_sel, _l in options if is_sel] == ["3:63"]


def test_selecting_a_preset_writes_both_grid_fields(env):
    """§2′.4: the dropdown writes the same `grid.phases` and `grid.fuse_a` the two controls did.

    One control writing two fields is the whole presentation change, so a save that moved only
    one of them would leave a connection the user never chose.
    """
    client, mod = env
    _seed(mod)

    client.post("/w/w1/edit", data=_form(**{"grid.connection": "3:40"}), follow_redirects=False)

    cfg = mod["simconfig_store"].load("w1")
    assert (cfg.grid.phases, cfg.grid.fuse_a) == (3, 40.0)


def test_an_unreadable_connection_value_leaves_the_stored_pair_alone(env):
    """A tampered or stale submission must not reset the connection to a default.

    The dropdown is a closed vocabulary the user cannot type into, so an unrecognised value is not
    a user mistake with an inline error to report — it is a POST that did not come from this
    screen. Keeping the stored pair is the same answer `_enum_or_keep` gives a radio group, and
    the safe direction: resetting would move `max_import_kw` on a submission nobody made.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.grid.phases, cfg.grid.fuse_a = 3, 63.0
    _store(mod, cfg)

    client.post("/w/w1/edit", data=_form(**{"grid.connection": "nonsense"}), follow_redirects=False)

    cfg = mod["simconfig_store"].load("w1")
    assert (cfg.grid.phases, cfg.grid.fuse_a) == (3, 63.0)


# ── The Contract box (§2′.4) ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("simulate_cost", [True, False])
def test_the_contract_box_is_always_shown(env, simulate_cost):
    """§2′.4, settled: always shown, never greyed, whatever `simulate_cost` says.

    The parametrisation is the assertion. Panel ② removes its whole Pricing box when cost
    simulation is off (§2.3 "Without cost simulation"), so applying the same rule here is the
    natural thing to do — and §2′.4 rules it out in so many words. Two reasons beyond "the
    contract is a fact about the household": a screen whose shape changed according to a toggle on
    a DIFFERENT screen would be hard to explain, and under §2′.6 this box is what unlocks that
    toggle, so greying it would make the two mutually blocking.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.simulate_cost = simulate_cost
    _store(mod, cfg)

    html = client.get("/w/w1/edit").text
    assert 'name="pricing.contract"' in html
    # The selectable option is enabled — "never greyed" is about the control, not just the text.
    dynamic = re.search(r'<input type="radio" name="pricing\.contract" value="dynamic"[^>]*>', html)
    assert dynamic is not None and "disabled" not in dynamic.group(0)


def test_the_unbuilt_contract_types_stay_pending_rather_than_absent(env):
    """§2′.4 / §2.1: FIXED and VARIABLE render disabled with their feature keys, not dropped.

    Same reasoning as the PV-gated charge policies in panel ②: a vanished option leaves the user
    unable to tell whether the app has the feature at all, while a disabled one with a `[?]` says
    what is missing and offers somewhere to register interest. The keys are `app/features.py`'s
    existing ones for the same two controls — a key names the FEATURE, not the screen it was
    clicked on, so interest from either place counts once.
    """
    from app import features

    client, mod = env
    _seed(mod)

    html = client.get("/w/w1/edit").text
    for value, key in (("fixed", "pricing_contract_fixed"), ("variable", "pricing_contract_variable")):
        radio = re.search(rf'<input type="radio" name="pricing\.contract" value="{value}"[^>]*>', html)
        assert radio is not None and "disabled" in radio.group(0)
        assert f'data-feature-key="{key}"' in html
        assert key in features.FEATURE_KEYS


def test_the_contract_choice_round_trips(env):
    """A submitted contract is PARSED and stored — a real change of state, in both directions.

    The version this replaces stored `dynamic` (the appendix-A default), submitted `contract=` —
    a key `_form` does not use, so it was ignored junk — and asserted `dynamic`. It passed with
    the whole `pricing.contract` block deleted from `parse_form`. Both directions are driven here
    so that a parser which merely inherits, or one which always writes the default, fails.
    """
    client, mod = env
    contract = _seed(mod).pricing.contract.__class__

    for stored, submitted in (("fixed", "dynamic"), ("dynamic", "fixed")):
        cfg = mod["simconfig_store"].load("w1")
        cfg.pricing.contract = contract(stored)
        _store(mod, cfg)
        assert mod["simconfig_store"].load("w1").pricing.contract.value == stored

        client.post(
            "/w/w1/edit",
            data=_form(**{"pricing.contract": submitted}),
            follow_redirects=False,
        )
        assert mod["simconfig_store"].load("w1").pricing.contract.value == submitted


# ── The postcode (§2′.4) ──────────────────────────────────────────────────────────────────────

def test_the_postcode_is_a_live_input_that_round_trips(env):
    """§2′.4: live, not pending — enabled, editable and persisted, though nothing reads it yet.

    Deliberately not a pending control: pending means "specified but not built" and offers a `[?]`
    to register interest, and neither fits a field that works exactly as it appears and simply has
    no consumer. A disabled box with a "not built yet" dialog would misdescribe it.
    """
    client, mod = env
    _seed(mod)

    html = client.get("/w/w1/edit").text
    field = re.search(r'<input type="text" name="postcode"[^>]*>', html)
    assert field is not None and "disabled" not in field.group(0)
    assert "data-feature-key" not in field.group(0)

    client.post("/w/w1/edit", data=_form(postcode="1012 AB"), follow_redirects=False)
    assert mod["simconfig_store"].load("w1").postcode == "1012 AB"
    assert 'value="1012 AB"' in client.get("/w/w1/edit").text


# ── The title (§2′.4) ─────────────────────────────────────────────────────────────────────────

def test_the_title_round_trips_through_the_workspaces_row(env):
    """§2′.4: the title is the `workspaces` table column, written via `workspaces.rename`.

    It is the one field on this screen that is not in the config document, which is the third
    reason phase 3 gave the screen its own route rather than reusing `POST /params` — that route
    has no business touching the workspace row beyond `touch()`.
    """
    client, mod = env
    _seed(mod, title="Our house")

    client.post("/w/w1/edit", data=_form(title="Dynamic contract test"), follow_redirects=False)

    assert mod["workspaces"].get("w1")["title"] == "Dynamic contract test"
    assert "Dynamic contract test" in client.get("/w/w1/edit").text


def test_an_empty_title_keeps_the_current_one(env):
    """A blank submission is not a request for a nameless card.

    The list screen identifies an analysis by its title and both confirmation dialogs quote it, so
    a stored empty string would leave a card the user cannot tell apart from any other. There is
    nothing on this screen a user could be trying to express by clearing the field.
    """
    client, mod = env
    _seed(mod, title="Our house")

    client.post("/w/w1/edit", data=_form(title="   "), follow_redirects=False)
    assert mod["workspaces"].get("w1")["title"] == "Our house"


# ── pricing_configured (§2′.6) ────────────────────────────────────────────────────────────────

def test_a_successful_save_sets_pricing_configured(env):
    """§2′.6: saving this screen is what "the user has told us what they pay" means.

    It is the flag that unblocks the cost toggle on the results screen, so nothing else may set it
    and this must.
    """
    client, mod = env
    _seed(mod)
    assert mod["simconfig_store"].is_pricing_configured("w1") is False

    client.post("/w/w1/edit", data=_form(), follow_redirects=False)
    assert mod["simconfig_store"].is_pricing_configured("w1") is True


def test_a_later_params_save_does_not_clear_pricing_configured(env):
    """§2′.6 "never cleared automatically", stated as the failure it guards against.

    `simconfig_store.save`'s `pricing_configured` defaults to `None`, meaning "carry the stored
    value forward"; only the edit-workspace save passes a bool, and it only ever passes True. The
    thing that would break this is an intermediate caller passing an explicit `False` — which
    would silently re-block the cost toggle for a user who had already answered.
    """
    client, mod = env
    _seed(mod)
    client.post("/w/w1/edit", data=_form(), follow_redirects=False)

    client.post("/w/w1/params", data={"sections": "setup battery grid charge discharge"})
    assert mod["simconfig_store"].is_pricing_configured("w1") is True


def test_a_blocking_submission_does_not_set_pricing_configured(env):
    """A save that did not happen is not a statement about what the household pays.

    The flag is set inside the branch that persists, so a submission that fails validation leaves
    it alone — the same discipline `touch()` follows on the same route.
    """
    client, mod = env
    _seed(mod)

    client.post("/w/w1/edit", data=_form(**{"grid.max_import_kw_override": "abc"}))
    assert mod["simconfig_store"].is_pricing_configured("w1") is False


# ── The advanced panes (§2′.4) ────────────────────────────────────────────────────────────────

def test_the_advanced_panes_are_details_elements_not_conditional_renders(env):
    """§2′.4: collapsing is a DISPLAY state, never a reset.

    Asserted on the markup because that is where the property lives: a `<details>` keeps its
    inputs in the DOM and therefore in the submitted form body whether it is open or closed,
    whereas rendering the contents only when open would submit a collapsed pane as a screenful of
    cleared fields and wipe every override the user had.
    """
    client, mod = env
    _seed(mod)

    html = client.get("/w/w1/edit").text
    # Matched with the attribute, not on the bare tag: an inline script comment in the page
    # mentions `<details>` by name, and counting that would make this assert nothing.
    assert len(re.findall(r"<details [^>]*data-advanced", html)) == 2
    # The inputs are present in the default (collapsed) render — the whole point.
    for name in ("grid.max_import_kw_override", "grid.max_export_kw", "pricing.supplier_markup"):
        assert f'name="{name}"' in html


def test_a_collapsed_advanced_pane_round_trips_its_overrides(env):
    """The behavioural half: a submission carrying the panes' fields preserves what is in them.

    This is what the `<details>` markup buys. The submitted body is written out in full (`_form`)
    rather than scraped from the render, so this test would still fail if the template ever
    stopped emitting the inputs — the two assertions are independent.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.grid.max_import_kw_override = 7.5
    cfg.grid.max_export_kw = 3.0
    cfg.pricing.supplier_markup = 0.0333
    cfg.pricing.dal_weekends = True
    _store(mod, cfg)

    client.post(
        "/w/w1/edit",
        data=_form(
            **{
                "grid.max_import_kw_override": "7.50",
                "grid.max_export_kw": "3.00",
                "pricing.supplier_markup": "0.0333",
                "pricing.dal_weekends": "1",
            }
        ),
        follow_redirects=False,
    )

    cfg = mod["simconfig_store"].load("w1")
    assert cfg.grid.max_import_kw_override == 7.5
    assert cfg.grid.max_export_kw == 3.0
    assert cfg.pricing.supplier_markup == 0.0333
    assert cfg.pricing.dal_weekends is True


def test_a_non_default_override_is_announced_on_the_collapsed_summary(env):
    """§2′.4: "N values overridden", so a non-default value cannot hide behind a closed box.

    Counted against a freshly-constructed `SimulationConfig` rather than a hardcoded table, so the
    count follows appendix A wherever appendix A moves.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.grid.max_import_kw_override = 7.5
    _store(mod, cfg)

    html = client.get("/w/w1/edit").text
    assert "1 value overridden" in html


def test_the_defaults_announce_nothing(env):
    """The other half: an untouched configuration shows no override badge at all.

    Without this the summary could read "0 values overridden" on every screen, which is noise on
    the common case and would make the real warning invisible.
    """
    client, mod = env
    _seed(mod)

    html = client.get("/w/w1/edit").text
    assert "overridden" not in html


# ── Validation and the error path (§2′.4, §7.3) ───────────────────────────────────────────────

def test_a_blocking_submission_re_renders_what_the_user_typed(env):
    """The same guarantee `POST /params` step 5 gives, on this screen's own renderer.

    Re-rendering the STORED config instead is the natural shortcut — the route already has it in
    hand — and it silently discards everything the user typed, which is the one thing the error
    path exists to prevent. Both halves are asserted: the bad value is back in its input with an
    error under it, and the good value typed alongside it survived too.
    """
    client, mod = env
    _seed(mod, title="Our house")
    _store(mod, mod["simconfig_store"].load("w1"))

    r = client.post(
        "/w/w1/edit",
        data=_form(**{"grid.max_import_kw_override": "abc", "title": "Typed but not saved"}),
    )

    assert r.status_code == 200
    assert 'value="abc"' in r.text
    assert "Typed but not saved" in r.text
    assert 'data-field-error="grid.max_import_kw_override"' in r.text
    # And nothing was stored — neither half of the submission.
    assert mod["workspaces"].get("w1")["title"] == "Our house"
    assert mod["simconfig_store"].load("w1").grid.max_import_kw_override is None


def test_a_blocking_issue_off_this_screen_is_surfaced_at_page_level(env):
    """`validate()` is whole-config; this screen draws four fields (§2′.4 and the phase-3 decision).

    A blocking issue keyed outside `EDITED_FIELDS` has no input here to attach to, so binding it
    inline is impossible — but dropping it would leave a save that refuses to happen with nothing
    on screen to explain why. It is rendered as a page-level alert instead, the same treatment
    `params_view` gives an issue keyed outside the panel's own field set.
    """
    client, mod = env
    cfg = _seed(mod)
    # A battery field this screen has no control for. Stored directly, so the submission itself is
    # clean and the only blocker is inherited from the document.
    cfg.battery.usable_capacity_kwh = -5.0
    _store(mod, cfg)

    r = client.post("/w/w1/edit", data=_form())

    assert r.status_code == 200
    assert 'role="alert"' in r.text
    assert "greater than zero" in r.text


# ── The footer (§2′.8) ────────────────────────────────────────────────────────────────────────

def test_the_card_footer_is_cancel_and_save(env):
    """§2′.8: reached from a card, the footer is `[ Cancel ] [ Save ]` and Save returns to the list."""
    client, mod = env
    _seed(mod)

    html = _footer(client.get("/w/w1/edit").text)
    assert ">Cancel<" in html and ">Save<" in html
    assert "Previous" not in html

    r = client.post("/w/w1/edit", data=_form(), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_the_wizard_footer_is_previous_and_next_and_next_persists(env):
    """§2′.8: in the wizard the footer is `[ ← Previous ] [ Next → ]`, and `[ Next → ]` PERSISTS.

    The wizard is not a transaction held in memory to be committed at the end — a workspace exists
    from the moment step 1 is completed, so an interrupted wizard leaves a usable workspace rather
    than nothing. That is what lets §2′.2's "configured, no data" card be a legitimate state.
    """
    client, mod = env
    _seed(mod)

    html = _footer(client.get("/w/w1/edit?mode=wizard").text)
    assert "Previous" in html and "Next" in html
    assert ">Save<" not in html

    r = client.post("/w/w1/edit?mode=wizard", data=_form(title="From the wizard"),
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] != "/"
    assert mod["workspaces"].get("w1")["title"] == "From the wizard"


def test_cancel_warns_about_unsaved_changes(env):
    """§2′.8: `[ Cancel ]` warns when there are unsaved changes, and the copy is the spec's.

    Asserted on the dialog's presence and its wording rather than on behaviour, since the dirty
    test itself is client-side. `[ Keep editing ]` carries `autofocus`: the safe option should be
    the one Enter takes.
    """
    client, mod = env
    _seed(mod)

    html = client.get("/w/w1/edit").text
    assert "Discard your changes?" in html
    assert "have not been saved" in html
    assert ">Keep editing<" in html and ">Discard changes<" in html
    keep = re.search(r'<button class="btn btn-ghost btn-sm" autofocus>Keep editing</button>', html)
    assert keep is not None, "[ Keep editing ] must be the default focus"


# ── Resolution (§5.1) ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("workspace_id", ["nope", "..", "%2e%2e%2fetc"])
def test_an_unknown_or_unsafe_workspace_is_a_404_on_both_verbs(env, workspace_id):
    """`deps.get_workspace`, not a hand-rolled check — both routes get the same answer.

    An id that cannot name a directory cannot name a workspace either, so a path-unsafe id is the
    same 404 as a well-formed unknown one. Unlike the two deletion routes, this screen keeps the
    404 rather than redirecting: an unknown id here is a bad ADDRESS with no end state to have
    already reached, and softening it would render an edit form for a workspace that does not
    exist.
    """
    client, mod = env
    _seed(mod)

    assert client.get(f"/w/{workspace_id}/edit").status_code == 404
    assert client.post(f"/w/{workspace_id}/edit", data=_form()).status_code == 404


def test_a_save_advances_updated_at_and_a_failed_one_does_not(env):
    """§2′.10: `touch()` on a save that HAPPENED, matching `POST /params`.

    The list screen's badge and its most-recently-updated-first ordering both read `updated_at`,
    so a submission that fails validation must leave it alone — the badge reports when the
    configuration was last STORED, and a blocking submission stored nothing.

    **The successful half is asserted against a BACK-DATED row, not against the row's own value
    a moment earlier.** This test used to end `assert updated_at >= before`, with `before` read
    from the same row seconds before — a comparison that holds whether or not the route wrote
    anything, since a clock never goes backwards. `tests/test_workspace_data.py` found the same
    shape in its own copy and measured the consequence: deleting `workspaces.touch` from the
    route left the whole non-browser suite green. Back-dating the stored value to a fixed instant
    in the past makes `>` a real constraint — nothing but a write can satisfy it — and lets the
    failed half assert exact equality against that same instant rather than against "unchanged".
    """
    client, mod = env
    _seed(mod)

    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    _backdate(mod, "w1", past)
    assert mod["workspaces"].get("w1")["updated_at"] == past

    client.post("/w/w1/edit", data=_form(**{"grid.max_import_kw_override": "abc"}))
    assert mod["workspaces"].get("w1")["updated_at"] == past, (
        "a blocking submission stored nothing, so it is not a 'last saved' event"
    )

    client.post("/w/w1/edit", data=_form(), follow_redirects=False)
    assert mod["workspaces"].get("w1")["updated_at"] > past, (
        "a successful save must call touch(); the row is still at its back-dated value, so "
        "nothing advanced it"
    )


def test_the_edit_screen_inherits_settings_it_does_not_draw(env):
    """The phase-3 decision in practice: `parse_form` builds the candidate on the STORED config.

    Every setting this screen has no control for — the whole battery box, the policies, the bands
    — is absent from its submission and can only survive by being inherited. Without that, a user
    who renamed their analysis would find their battery reset to appendix A's defaults.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.battery.usable_capacity_kwh = 22.0
    cfg.policy.band_b = 0.123
    _store(mod, cfg)

    client.post("/w/w1/edit", data=_form(title="Renamed"), follow_redirects=False)

    cfg = mod["simconfig_store"].load("w1")
    assert cfg.battery.usable_capacity_kwh == 22.0
    assert cfg.policy.band_b == 0.123


# ── The `sections` marker and the checkboxes this screen does NOT draw ─────────────────────────
#
# Inheritance protects ordinary fields, but checkboxes are its documented exception: an unticked
# box and an absent box look identical in a form body, so every checkbox path in `parse_form` is
# gated on the `sections` marker instead. That makes the marker a claim about which CONTROLS were
# rendered, and an over-claim is a silent clear of stored state. Phase 3 shipped two of them: the
# marker said `pricing`, which names panel ②'s `policy.economic_guard`, and the
# `topology.approximated` branch had no gate at all. Both are below, together with the untick
# behaviour a narrower marker must not cost.

def test_the_edit_screen_claims_only_the_checkbox_it_draws(env):
    """The rendered marker, against the checkboxes actually in the page.

    Asserted from the markup because the marker is a claim ABOUT the markup, and the two can only
    be kept honest by comparing them. `pricing` and `topology` name controls this screen does not
    have, so claiming either would hand it authority to clear them.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.simulate_cost = True
    _store(mod, cfg)

    html = client.get("/w/w1/edit").text
    sections = re.search(r'name="sections" value="([^"]*)"', html).group(1).split()

    assert "pricing_advanced" in sections and 'name="pricing.dal_weekends"' in html
    assert "pricing" not in sections and 'name="policy.economic_guard"' not in html
    assert "topology" not in sections and 'name="topology.approximated"' not in html


def test_a_stored_economic_guard_survives_a_save_from_this_screen(env):
    """Defect 1: this screen never draws the guard, so a save here must not touch it.

    Appendix A retains the guard across builds that do not show it; the edit screen is one of
    those, whatever `simulate_cost` says. `guard_was_submitted`'s server-side half does not help
    here — cost simulation is genuinely ON, so the only thing standing between the stored tick and
    a submission that never rendered the control is the marker being truthful.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.simulate_cost = True
    cfg.policy.economic_guard = True
    _store(mod, cfg)
    assert mod["simconfig_store"].load("w1").economic_guard is True

    r = client.post("/w/w1/edit", data=_form(title="Renamed"), follow_redirects=False)
    assert r.status_code == 303

    saved = mod["simconfig_store"].load("w1")
    assert saved.policy.economic_guard is True
    assert saved.economic_guard is True


def test_unticking_weekends_on_this_screen_still_turns_it_off(env):
    """The behaviour a naive fix for defect 1 would cost.

    Dropping `pricing` from the marker protects the guard, but `dal_weekends` is behind the same
    name — so an untick would read as "this build never drew it" and be ignored, leaving the user
    with a checkbox that cannot be cleared. The fix splits the name instead; this is the half that
    fails if the marker is merely narrowed.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.pricing.dal_weekends = True
    _store(mod, cfg)
    assert mod["simconfig_store"].load("w1").pricing.dal_weekends is True

    # Unticked: the browser omits the key entirely.
    client.post("/w/w1/edit", data=_form(), follow_redirects=False)
    assert mod["simconfig_store"].load("w1").pricing.dal_weekends is False

    client.post(
        "/w/w1/edit",
        data=_form(**{"pricing.dal_weekends": "1"}),
        follow_redirects=False,
    )
    assert mod["simconfig_store"].load("w1").pricing.dal_weekends is True


def test_a_stored_topology_approximation_survives_a_save_from_this_screen(env):
    """Defect 2: `approximated` is a deliberate acknowledgement, and this screen never asks for it.

    §2.5(b): the value records the user clicking "Continue with a 3-phase approximation", never a
    derivation. Clearing it re-raises the soft block on panel ② and drops the approximation caveat
    from the results, on a screen the user opened to change their postcode.

    The topology has to be genuinely unsupported for the branch to be reached at all — a 3×25 A
    connection (so the phase selector is offered) with a 1-phase battery.
    """
    client, mod = env
    from app.domain.simconfig import BatteryPhases
    from app.params_view import phase_topology_unsupported

    cfg = _seed(mod)
    cfg.grid.phases, cfg.grid.fuse_a = 3, 25.0
    cfg.topology.battery_phases = BatteryPhases.ONE_PHASE
    cfg.topology.approximated = True
    _store(mod, cfg)
    stored = mod["simconfig_store"].load("w1")
    assert phase_topology_unsupported(stored) is True, "the branch under test was not reached"
    assert stored.topology.approximated is True

    r = client.post(
        "/w/w1/edit",
        data=_form(title="Renamed", **{"grid.connection": "3:25"}),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert mod["simconfig_store"].load("w1").topology.approximated is True


# ── §2′.8's step indicator (D4) ───────────────────────────────────────────────────────────────


def test_the_step_indicator_is_absent_outside_the_wizard(env):
    """"Step 1 of 3" is meaningless from a card: there are no other steps to be one of."""
    client, mod = env
    _seed(mod)
    assert "data-wizard-step" not in client.get("/w/w1/edit").text


def test_the_step_indicator_says_step_1_of_3_in_the_wizard(env):
    """§2′.8 leaves the indicator optional; D4 takes it up.

    Without it the wizard is indistinguishable from the card path except by two button labels, so
    a user has no way to know how much is still ahead. Asserted inside the `data-wizard-step`
    element rather than as page text — this screen also carries an inline script.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/edit?mode=wizard").text
    m = re.search(r"<span[^>]*data-wizard-step>(.*?)</span>", html, re.S)
    assert m is not None, "no step indicator on the wizard's step 1"
    assert "Step 1 of 3" in m.group(1)


def test_the_step_indicator_sits_beside_the_screen_title(env):
    """§2′.8 places it "beside the screen title", so it must be in that heading row.

    Asserted as adjacency to the <h1> rather than as mere presence: an indicator rendered anywhere
    on the page would satisfy the test above while reading as an unattached fragment.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/edit?mode=wizard").text
    m = re.search(r"<h1[^>]*>.*?</h1>\s*(.*?)</div>", html, re.S)
    assert m is not None
    assert "data-wizard-step" in m.group(1)


def test_the_two_screens_use_the_same_indicator_msgid_with_a_different_number(env):
    """One catalog entry with two holes, not a literal per step (D7).

    Two literals would sit in the catalog as unrelated entries, so a translator could word "Step 1
    of 3" and "Step 2 of 3" differently, and a fourth step would need a catalog change rather than
    a template change. Driven in DUTCH, because that is where a second msgid — or a missing
    translation — is visible at all; in English an untranslated string is indistinguishable from a
    translated one.
    """
    client, mod = env
    _seed(mod)
    step1 = client.get("/w/w1/edit?mode=wizard", headers={"Cookie": "lang=nl"}).text
    step2 = client.get("/w/w1/data?mode=wizard", headers={"Cookie": "lang=nl"}).text

    one = re.search(r"<span[^>]*data-wizard-step>(.*?)</span>", step1, re.S).group(1).strip()
    two = re.search(r"<span[^>]*data-wizard-step>(.*?)</span>", step2, re.S).group(1).strip()
    assert "Step" not in one, f"the Dutch page leaked the English msgid: {one!r}"
    assert "Step" not in two, f"the Dutch page leaked the English msgid: {two!r}"
    # Same wording, differing only in the step number — which is what one msgid buys.
    assert one.replace("1", "#") == two.replace("2", "#"), (one, two)
