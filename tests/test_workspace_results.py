"""The results screen (specs/20-workspaces-ux.md §2′.6, §2′.7).

Phase 4.2 turned `GET /w/{id}/results` from the three-panel page into the screen §2′.6 specifies:
panels ② and ③ combined, with ② reduced to a capacity-first battery box. Most of the CONTENT is a
rearrangement — every field, gate and validation rule §2.3 specifies is unchanged and is covered
where it already was (`tests/test_params_view.py`, `tests/test_params_route.py`) — so what this
file pins is what the rearrangement is, and what it could silently break.

  * **Capacity is OUTSIDE the pane and everything else is inside it.** That is the whole shape
    §2′.6 argues for ("one field in front of a collapsed pane means the common path is a single
    input away from a result"), and it is a two-sided property: a test that only checked the
    capacity renders would pass on the old panel.
  * **The pane is a `<details>` and the tabs are CSS, never conditional rendering.** A collapsed
    pane whose inputs are absent from the DOM submits as CLEARED fields, and so does an unopened
    tab. This is data loss, not a display bug, so the tests drive an actual round trip: submit the
    form as the browser would build it and check the values come back.
  * **The overlap warning is below BOTH bands, on the shared tab.** §2′.6 gives the reason —
    "splitting them would put that warning on one tab while the values it indicts sat on the
    other" — so the assertion is about ORDER within one panel, not about mere presence.
  * **The cost toggle is Blocked, not Inapplicable, without `pricing_configured`.** Blocked means
    on screen, greyed, with an adjacent affordance saying how to clear the precondition. Both
    halves are asserted: the control exists AND it cannot be used, plus the ⓘ and where its link
    goes. A test that only checked for `disabled` would pass on a control nobody can find.
  * **The screen has NO footer buttons** (§2′.6). It is the end of both paths and is left through
    the back link, so an added `[ Save ]` / `[ Next → ]` is a spec violation, not a nicety.
  * **Panel ① and the setup band are gone from here.** Asserted by their hooks (`#slot-roster`,
    `#setup-band`, `data-ingest-ws`, the `ha_fetch.js` tag), not by prose, because prose about them
    survives in the comments.
  * **The dangling anchor.** `#setup-simulate-cost` existed only in the deleted setup band. Every
    link to it must resolve to an element on the page that renders the link.
  * **The `sections` marker still names exactly the checkboxes drawn.** Phase 3 shipped two silent
    clears through this marker; 4.2 moved a control that the marker covers, so the four
    checkbox-bearing config shapes are re-derived here rather than assumed.

Every regex is scoped to a real element (an id, a `name=`, a `data-*` hook) rather than to prose:
this page carries ~350 lines of inline script and comments that mention most of what is asserted,
and a phase-3 test passed against a script comment.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A client over an empty temp data dir, plus the modules that write into it.

    `monkeypatch.setenv` before any import that resolves the data dir, as everywhere else in this
    suite (and note followup I4: an in-test `monkeypatch.undo()` would redirect the rest of the
    test at the developer's real `./data`).
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset, db, main, params_view, simconfig_store, workspaces

    return TestClient(main.app), {
        "dataset": dataset,
        "db": db,
        "main": main,
        "params_view": params_view,
        "simconfig_store": simconfig_store,
        "workspaces": workspaces,
    }


def _seed(mod, workspace_id: str = "w1", title: str = "Our house"):
    """Create the workspace row and return its (appendix-A default) config."""
    mod["workspaces"].create(title, workspace_id=workspace_id)
    return mod["simconfig_store"].load(workspace_id)


def _get(client, workspace_id: str = "w1", **kw) -> str:
    r = client.get(f"/w/{workspace_id}/results", **kw)
    assert r.status_code == 200, r.status_code
    return r.text


# ── The capacity-first shape (§2′.6) ──────────────────────────────────────────────────────────


def _pane_span(html: str) -> tuple[int, int]:
    """The character range of the "More settings" `<details>`.

    Found by its id and closed by matching `<details>`/`</details>` nesting, because the pane
    CONTAINS another `<details>` (the Pricing box's Advanced) and a naive `.index('</details>')`
    would stop at the inner one — which would make every "inside the pane" assertion below quietly
    weaker than it reads.
    """
    start = html.index('id="params-advanced"')
    start = html.rindex("<details", 0, start)
    depth = 0
    for m in re.finditer(r"<details\b|</details>", html[start:]):
        depth += 1 if m.group(0).startswith("<details") else -1
        if depth == 0:
            return start, start + m.end()
    raise AssertionError("the More settings pane is never closed")


def test_usable_capacity_renders_outside_the_pane(env):
    """§2′.6: "Usable capacity … alone up front", with everything else behind the pane.

    Both sides, because either alone is satisfiable by the old panel: the capacity input must be
    BEFORE the `<details>` opens, and the pane must actually hold the rest.
    """
    client, mod = env
    _seed(mod)
    html = _get(client)

    cap = re.search(r'<input[^>]*name="battery\.usable_capacity_kwh"[^>]*>', html)
    assert cap, "the usable-capacity input is not rendered at all"
    pane_start, pane_end = _pane_span(html)
    assert cap.start() < pane_start, "usable capacity must sit BEFORE the More settings pane"

    # …and its ⓘ, which §2′.6 draws beside it.
    assert "not the nameplate figure" in html[:pane_start]

    # The rest is inside. `min_soc` is the first row of §2′.6's own wireframe for the pane.
    pane = html[pane_start:pane_end]
    for inside in ("battery.min_soc_pct", "battery.max_charge_kw", "policy.band_a",
                   "policy.charge_policy"):
        assert f'name="{inside}"' in pane, inside
        assert f'name="{inside}"' not in html[:pane_start], f"{inside} leaked out of the pane"


def test_the_pane_summary_counts_the_values_that_differ_from_the_defaults(env):
    """§2′.6: the collapsed summary "should name how many values differ from the defaults".

    Driven through the store so the count describes a real stored config, and asserted in three
    states — none, one, two — because a badge that always said the same number would pass a
    single-state check.
    """
    client, mod = env
    cfg = _seed(mod)

    # Appendix-A defaults: nothing differs, so there is no badge at all.
    html = _get(client)
    assert "data-changed-count" not in html
    assert "changed from default" not in html

    cfg.battery.min_soc_pct = 20.0
    mod["simconfig_store"].save(cfg, "w1")
    html = _get(client)
    badge = re.search(r"data-changed-count[^>]*>\s*([^<]*?)\s*<", html)
    assert badge, "no count badge after changing one pane value"
    assert badge.group(1) == "1 changed from default", badge.group(1)

    cfg.battery.standby_w = 45.0
    mod["simconfig_store"].save(cfg, "w1")
    html = _get(client)
    badge = re.search(r"data-changed-count[^>]*>\s*([^<]*?)\s*<", html)
    assert badge.group(1) == "2 changed from default", badge.group(1)


def test_the_count_reads_the_stored_economic_guard_not_the_cost_forced_one():
    """`economic_guard` is RETAINED on disk while cost simulation is off (appendix A).

    `SimulationConfig.economic_guard` is a PROPERTY that forces False without a cost model (§6.7,
    "forced on READ … so a caller that flips `simulate_cost` off after construction … still cannot
    get §6.7 to read `p_export_net`"). `results_screen_view.ADVANCED_PATHS` therefore names
    `policy.economic_guard`, the stored field, so the pane's count describes what is on disk and
    comes back when the toggle returns.

    **A unit test, not a route test, and that is the finding rather than a shortcut.** Mutating the
    path to the property left the entire suite green, so this was written to close the gap — and it
    could not be closed through `GET /w/{id}/results`, because `simconfig_store.load` only lifts
    the retained guard back into `policy` when `simulate_cost` is on (see its `retained` docstring).
    The divergent state is therefore unreachable from the store today, and the difference between
    the two spellings is latent rather than live. It is still worth pinning: the count is a pure
    function of a config, `parse_form` can hand it one built any way at all, and a retention rule
    that only holds because of where its caller happens to read from is one refactor from not
    holding at all.
    """
    from app.domain.simconfig import SimulationConfig
    from app.results_screen_view import advanced_changed_count

    cfg = SimulationConfig()
    assert advanced_changed_count(cfg) == 0, "appendix-A defaults must count as unchanged"

    cfg.policy.economic_guard = True   # the stored answer
    cfg.simulate_cost = False          # …which the property forces False on read
    assert cfg.economic_guard is False, "the forcing property changed — this test's premise is"
    assert cfg.policy.economic_guard is True

    assert advanced_changed_count(cfg) == 1, (
        "the count is reading the cost-forced guard rather than the stored one, so a retained "
        "setting would hide behind a closed pane"
    )


def test_the_capacity_is_not_counted_by_the_pane_summary(env):
    """The count describes the PANE, and the capacity is not in it (§2′.6 puts it in front).

    A count including it would say "1 changed" about a pane whose contents are all still default,
    which is the opposite of what the summary is for — it exists so a non-default value cannot hide
    behind a closed box, and the capacity is the one value that cannot hide.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.battery.usable_capacity_kwh = 17.5
    mod["simconfig_store"].save(cfg, "w1")

    html = _get(client)
    assert 'value="17.5"' in html, "the changed capacity is not even rendered"
    assert "data-changed-count" not in html, "the capacity must not be counted by the pane summary"


# ── The three tabs (§2′.6) ────────────────────────────────────────────────────────────────────


def test_the_pane_holds_three_tabs_with_battery_selected_by_default(env):
    """§2′.6 names the three and says which one opens: "Battery is the default tab"."""
    client, mod = env
    _seed(mod)
    html = _get(client)
    pane_start, pane_end = _pane_span(html)
    pane = html[pane_start:pane_end]

    radios = re.findall(r'<input[^>]*name="params-tab"[^>]*>', pane)
    assert len(radios) == 3, radios

    ids = [re.search(r'id="([^"]+)"', r).group(1) for r in radios]
    assert ids == ["params-tab-battery", "params-tab-installation", "params-tab-dispatch"], ids

    checked = [r for r in radios if "checked" in r]
    assert len(checked) == 1, "exactly one tab must open by default"
    assert 'id="params-tab-battery"' in checked[0], "Battery must be the default tab"

    # Each radio has a label pointing at it — the tab strip is the labels, since the radios are
    # visually hidden. A `for=` that named nothing would leave the strip inert.
    for tab_id in ids:
        assert f'for="{tab_id}"' in pane, tab_id
    # …and each tab has a panel.
    for tab in ("battery", "installation", "dispatch"):
        assert f'data-tab-panel="{tab}"' in pane, tab


def test_every_tabs_inputs_are_in_the_dom_whichever_tab_is_selected(env):
    """The tabs are presentation only: no input is conditionally rendered (§2′.6).

    This is the data-loss test, not a layout one. The form posts every control it contains
    regardless of CSS visibility (`display:none` does not exclude a field; only `disabled` does), so
    a tab that rendered its panel only when selected would submit the other two as cleared.

    Asserted on ONE render, which is the point: all three panels' fields are present at once, with
    only the Battery tab checked.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.simulate_cost = True
    cfg.grid.phases = 3  # so the Installation tab's phase selector exists
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)

    html = _get(client)
    pane = html[slice(*_pane_span(html))]
    assert 'id="params-tab-battery"' in pane and "checked" in pane

    expected = {
        "battery": ("battery.min_soc_pct", "battery.standby_w", "grid.fuse_a"),
        "installation": ("topology.pv_coupling", "topology.battery_phases"),
        "dispatch": ("policy.charge_policy", "policy.band_c", "policy.allow_grid_export",
                     "pricing.contract", "pricing.dal_weekends"),
    }
    for tab, names in expected.items():
        panel_start = pane.index(f'data-tab-panel="{tab}"')
        for name in names:
            assert f'name="{name}"' in pane, f"{name} is not rendered at all ({tab} tab)"
            assert pane.index(f'name="{name}"') > panel_start, f"{name} is not inside {tab}"


def test_a_collapsed_pane_round_trips_its_values_instead_of_clearing_them(env):
    """The `<details>` rule, driven as a real POST: submitting a closed pane must change nothing.

    §2′.6 and §2′.4 both state it, and the failure mode is silent: rendering the pane's contents
    only when it is open would submit a screenful of empty fields and wipe every setting behind it.
    A closed `<details>` still contributes its inputs to `FormData`, so the browser sends them —
    which is exactly what this reproduces by posting the form's own fields back.

    The pane is closed on a fresh render (no `open` attribute), so the render under test IS the
    collapsed one. Both sides of the contract are exercised: the template renders the fields, and
    the parser reads them.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.battery.min_soc_pct = 22.0
    cfg.battery.standby_w = 41.0
    cfg.policy.band_c = 0.29
    cfg.policy.allow_grid_export = False
    mod["simconfig_store"].save(cfg, "w1")

    html = _get(client)
    pane_start = _pane_span(html)[0]
    assert "<details" in html[pane_start:pane_start + 40]
    assert " open" not in html[pane_start:html.index(">", pane_start)], "the pane must start closed"

    # Post the form exactly as a browser would build it from THIS render: every named input inside
    # #panel-params, with unchecked checkboxes omitted (which is what a browser does).
    r = client.post("/w/w1/params", data=_form_body(html))
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "1", "the round trip must not invent a validation error"

    stored = mod["simconfig_store"].load("w1")
    assert stored.battery.min_soc_pct == 22.0
    assert stored.battery.standby_w == 41.0
    assert stored.policy.band_c == 0.29
    assert stored.policy.allow_grid_export is False


def _form_body(html: str) -> dict:
    """The form body a browser would send for `#panel-params`, from the rendered HTML.

    Named inputs only, `disabled` ones dropped and unchecked checkboxes omitted — the three rules a
    browser applies. Radios contribute only the checked member. Written against the rendered page
    rather than hand-listing the fields, so a field the template stops drawing is a field this stops
    sending, which is what makes the round-trip tests above discriminate.
    """
    section = html[html.index('id="panel-params"'):]
    body: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", section):
        name = re.search(r'name="([^"]+)"', tag)
        if not name or "disabled" in tag:
            continue
        key = name.group(1)
        if key == "params-tab":
            continue  # not a config field; the tab radios carry no dotted path
        value = re.search(r'value="([^"]*)"', tag)
        if 'type="checkbox"' in tag or 'type="radio"' in tag:
            if "checked" in tag:
                body[key] = value.group(1) if value else "on"
        else:
            body[key] = value.group(1) if value else ""
    return body


# ── Charge and discharge share a tab, with the warning below both (§2′.6) ─────────────────────


def test_the_overlap_warning_sits_below_both_bands_on_the_shared_tab(env):
    """§2′.6's reason for the shared tab, asserted as ORDER rather than as presence.

    "The bands must not overlap, and §2.3's overlap warning compares band A/B against band C/D.
    Splitting them would put that warning on one tab while the values it indicts sat on the other."
    So: both band pairs and the warning are in the SAME tab panel, and the warning comes last.
    """
    client, mod = env
    cfg = _seed(mod)
    # An overlapping pair, so the warning branch (not the reassurance branch) is the one rendered.
    cfg.policy.band_a, cfg.policy.band_b = 0.05, 0.30
    cfg.policy.band_c, cfg.policy.band_d = 0.20, 0.60
    mod["simconfig_store"].save(cfg, "w1")

    html = _get(client)
    pane = html[slice(*_pane_span(html))]
    panel_start = pane.index('data-tab-panel="dispatch"')
    # The next tab panel, or the end of the pane — the warning must be before it.
    panel_end = len(pane)

    a = pane.index('name="policy.band_a"')
    d = pane.index('name="policy.band_d"')
    warn = pane.index("data-band-overlap")
    assert panel_start < a < d < warn < panel_end, (panel_start, a, d, warn)
    # It is the WARNING branch, and it names all four bands (§7.3 check 12).
    assert "alert-warning" in pane[warn - 120:warn + 40]
    assert "overlap" in pane[warn:warn + 400]

    # The two policy boxes are stacked inside this one panel, not split across tabs.
    for other in ("battery", "installation"):
        other_at = pane.index(f'data-tab-panel="{other}"')
        assert not (other_at < a < pane.index('data-tab-panel="dispatch"')), other


def test_the_non_overlapping_case_renders_the_reassurance_in_the_same_place(env):
    """The other branch of the same alert — same hook, same position, different wording.

    Both branches are asserted because the template has two of them and a test on one would let the
    other drift out of the tab it belongs to.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.policy.band_a, cfg.policy.band_b = 0.02, 0.08
    cfg.policy.band_c, cfg.policy.band_d = 0.30, 0.90
    mod["simconfig_store"].save(cfg, "w1")

    html = _get(client)
    pane = html[slice(*_pane_span(html))]
    warn = pane.index("data-band-overlap")
    assert pane.index('name="policy.band_d"') < warn
    assert "alert-success" in pane[warn - 120:warn + 40]
    assert "do not overlap" in pane[warn:warn + 400]


def test_the_installation_tab_holds_the_illustrated_selectors(env):
    """§2′.6: Installation holds §2.3's box 3 — the SVG choosers, at the pane's full width.

    Asserted on the SVGs, not on the radios: §2′.6's reason for giving this group a tab of its own
    is that "that selector is itself a visual chooser with SVG options … it needs width and does not
    survive being nested that far", so a radio group rendered without its illustration would satisfy
    a `name=` check and miss the point entirely.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.grid.phases = 3  # offers the battery-phase selector as well as the PV one
    mod["simconfig_store"].save(cfg, "w1")

    html = _get(client)
    pane = html[slice(*_pane_span(html))]
    panel = pane[pane.index('data-tab-panel="installation"'):pane.index('data-tab-panel="dispatch"')]

    assert 'name="topology.pv_coupling"' in panel
    assert 'name="topology.battery_phases"' in panel
    # The illustrations themselves, and the card wrapper that gives them their width.
    assert panel.count("<svg") >= 4, panel.count("<svg")
    assert panel.count("radio-card") >= 4


def test_the_installation_tab_says_so_when_there_is_nothing_to_configure(env):
    """§2.3's "Without PV": on a 1-phase connection the box "empties entirely".

    §2.3 says not to render it in that case, which a tab cannot do — a tab strip with a dead third
    entry is worse than an empty panel — so the panel states the reason instead. Pinned because the
    alternative (a silently blank panel) is what a naive implementation produces.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.has_pv = False
    cfg.grid.phases = 1
    mod["simconfig_store"].save(cfg, "w1")

    html = _get(client)
    pane = html[slice(*_pane_span(html))]
    panel = pane[pane.index('data-tab-panel="installation"'):pane.index('data-tab-panel="dispatch"')]

    assert 'name="topology.pv_coupling"' not in panel
    assert 'name="topology.battery_phases"' not in panel
    assert "Nothing to configure here" in panel
    # The tab itself is still offered — the strip must not lose an entry.
    assert 'id="params-tab-installation"' in pane


# ── The cost toggle (§2′.6, §2′.7) ────────────────────────────────────────────────────────────


def test_the_cost_toggle_sits_in_the_results_block_under_the_period_selector(env):
    """§2′.6: "inside the results block, under the period selector and above the result sections".

    Position, because that is what the spec states and because the toggle would work equally well
    in the battery box — which is the placement §2′.6 rules out by name.
    """
    client, mod = env
    _seed(mod)
    html = _get(client)

    panel = html[html.index('id="panel-results"'):]
    toggle = panel.index('id="setup-simulate-cost"')
    period = panel.index('id="results-period"')
    energy = panel.index("Energy savings")
    assert period < toggle < energy, (period, toggle, energy)

    # In the results block and NOT in the battery box (§2′.6 rules that out explicitly).
    box = html[html.index('id="panel-params"'):html.index('id="panel-results"')]
    assert 'name="setup.simulate_cost"' not in box


def test_the_cost_toggle_posts_with_the_battery_boxs_form(env):
    """It is drawn in one fragment and submits with the other, via `form="params-form"`.

    That association is what makes one POST re-render both halves consistently; without it the
    toggle would either need its own fetch path or would post without the parameter fields. Both
    ends are asserted — the attribute, and a form with that id actually existing on the page.
    """
    client, mod = env
    _seed(mod)
    mod["simconfig_store"].save(mod["simconfig_store"].load("w1"), "w1", pricing_configured=True)
    html = _get(client)

    radios = re.findall(r'<input[^>]*name="setup\.simulate_cost"[^>]*>', html)
    assert len(radios) == 2, radios
    for r in radios:
        assert 'form="params-form"' in r, r
    assert 'id="params-form"' in html


def test_the_cost_toggle_is_blocked_without_a_configured_contract(env):
    """§2′.6's Blocked state: greyed, disabled, with an ⓘ that says how to clear it.

    Blocked, NOT Inapplicable, and the spec argues the distinction: "hiding the toggle would leave
    a user who wants euro figures with nothing to click and nothing to read." So the assertions are
    two-sided — the control is PRESENT, and it cannot be used.
    """
    client, mod = env
    _seed(mod)
    assert mod["simconfig_store"].is_pricing_configured("w1") is False

    html = _get(client)
    radios = re.findall(r'<input[^>]*name="setup\.simulate_cost"[^>]*>', html)
    assert len(radios) == 2, "Blocked must not hide the control (that would be Inapplicable)"
    for r in radios:
        assert "disabled" in r, r
    # Greyed, and marked as such for anything that reads the DOM.
    row = re.search(r'<div[^>]*id="setup-simulate-cost"[^>]*>', html)
    assert row and 'data-blocked="1"' in row.group(0)
    assert "blocked-control" in row.group(0)
    # The adjacent affordance §2.1's Blocked state requires.
    assert 'id="cost-blocked-info"' in html


def test_the_cost_toggle_is_live_once_the_contract_is_configured(env):
    """The other side: with the flag set the control is ordinary, and the ⓘ is gone.

    Both directions matter — a toggle that was always Blocked would pass the test above.
    """
    client, mod = env
    cfg = _seed(mod)
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)

    html = _get(client)
    radios = re.findall(r'<input[^>]*name="setup\.simulate_cost"[^>]*>', html)
    assert len(radios) == 2
    for r in radios:
        assert "disabled" not in r, r
    row = re.search(r'<div[^>]*id="setup-simulate-cost"[^>]*>', html)
    assert "data-blocked" not in row.group(0)
    assert "blocked-control" not in row.group(0)
    # No ⓘ: there is no unmet precondition to explain.
    assert 'id="cost-blocked-info"' not in html


def test_the_checked_radio_follows_the_stored_answer(env):
    """The toggle reports what is stored, in both states and independently of Blocked.

    A workspace with cost simulation ON and no contract configured is reachable (§2′.10's migration
    sets the flag from `simulate_cost`, but a hand-edited document need not), and the honest
    rendering is a CHECKED toggle the user cannot change from here. Asserting that combination is
    what stops "blocked" being implemented as "forced to No".
    """
    client, mod = env
    cfg = _seed(mod)

    def checked(html: str) -> str:
        for r in re.findall(r'<input[^>]*name="setup\.simulate_cost"[^>]*>', html):
            if "checked" in r:
                return re.search(r'value="([^"]+)"', r).group(1)
        raise AssertionError("neither radio is checked")

    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)
    assert checked(_get(client)) == "no"

    cfg.simulate_cost = True
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)
    assert checked(_get(client)) == "yes"

    # Cost on, contract flag off: still checked "yes", still Blocked.
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=False)
    html = _get(client)
    assert checked(html) == "yes"
    assert 'data-blocked="1"' in html


def test_the_blocked_dialog_transcribes_the_spec_and_links_to_the_contract_box(env):
    """§2′.6 draws this dialog, and its `[ Set up my contract → ]` destination by name:
    "navigates to the workspace's edit screen with the Contract box in view".

    The link TARGET is asserted to resolve, not merely to exist — "with the Contract box in view"
    is the requirement, and a `#contract` fragment pointing at nothing lands the user at the top of
    a screen with the box below the fold while passing an `href` check.
    """
    client, mod = env
    _seed(mod)
    html = _get(client)

    dialog_at = html.index('id="cost-blocked-dialog"')
    dialog = html[dialog_at:html.index("</dialog>", dialog_at)]
    assert "Set up your contract first" in dialog
    assert "what you pay for electricity" in dialog
    assert "You have not set those up for this analysis yet." in dialog
    assert 'href="/w/w1/edit#contract"' in dialog

    # The dialog is at PAGE level, outside both swappable fragments and outside every collapsible.
    assert dialog_at > html.index("</main>")

    # …and the fragment it names is a real element on the edit screen.
    edit = client.get("/w/w1/edit")
    assert edit.status_code == 200
    assert 'id="contract"' in edit.text
    # Specifically the Contract box, not some unrelated element that happens to carry the id.
    box_at = edit.text.index('id="contract"')
    assert ">Contract<" in edit.text[box_at:box_at + 400]


# ── The invitation box, and the anchor the setup band's deletion left dangling (§2′.7) ────────


def test_the_invitation_boxs_anchor_resolves_on_the_page_that_renders_it(env):
    """`#setup-simulate-cost` existed only in the deleted setup band (§2′.7's own warning).

    With the toggle live, the box keeps §2.4's wording and its anchor — and the anchor must now
    resolve to the toggle's new home, which is inside the SAME fragment. The id is asserted to
    exist, which is the assertion the old test could not make (the target was in a different file).
    """
    client, mod = env
    cfg = _seed(mod)
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)

    html = _get(client)
    assert "Want to know what this is worth in euros?" in html
    assert 'href="#setup-simulate-cost"' in html
    assert 'id="setup-simulate-cost"' in html
    # Exactly one target, or the fragment is ambiguous.
    assert html.count('id="setup-simulate-cost"') == 1


def test_the_invitation_box_offers_the_contract_when_the_toggle_is_blocked(env):
    """§2′.7: it must "say something useful when the toggle it points at is blocked".

    A `[ Enable cost simulation ]` button pointing at a disabled control explains nothing, so the
    Blocked branch names the precondition and links where the ⓘ dialog links. §2′.7 holds the box
    otherwise as it is, so the question it asks is unchanged and is asserted here too.
    """
    client, mod = env
    _seed(mod)
    html = _get(client)

    box_at = html.index("data-cost-invitation")
    box = html[box_at:html.index("</div>", html.index("</a>", box_at))]
    assert "Want to know what this is worth in euros?" in box  # §2′.7's hold
    assert "Enable cost simulation" not in box
    assert 'href="#setup-simulate-cost"' not in box
    assert 'href="/w/w1/edit#contract"' in box


def test_the_invitation_box_is_absent_once_cost_simulation_is_on(with_data):
    """It invites what is already enabled otherwise — unchanged behaviour, re-pinned here because
    4.2 added a second branch to the box and a branch is a place to get a gate wrong.

    Needs a real priced dataset: the box is gated on `results.cost`, which `results_from` emits
    only when the toggle is on AND there is something to price. Against the static sample there is
    no `cost` block whatever the toggle says, so this would assert on the energy-only render and
    pass for the wrong reason.
    """
    client, mod = with_data
    cfg = mod["simconfig_store"].load("w1")
    cfg.simulate_cost = True
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)

    html = _get(client)
    assert "Cost savings" in html, "the cost section did not render — the gate under test is inert"
    assert "data-cost-invitation" not in html
    assert "Want to know what this is worth in euros?" not in html


# ── What the screen no longer has (§2′.5, §2′.6, §2′.7) ───────────────────────────────────────


def test_the_screen_has_no_footer_buttons(env):
    """§2′.6: "There is nothing to cancel or save … This is the one screen where the wizard's
    `[ Previous ] / [ Next ]` and the card's `[ Cancel ] / [ Save ]` do not apply."

    Also checked with `?mode=wizard`, because that is the query the other two screens use to switch
    footers and the natural mistake is to honour it here.
    """
    client, mod = env
    _seed(mod)
    for url in ("/w/w1/results", "/w/w1/results?mode=wizard"):
        r = client.get(url)
        assert r.status_code == 200
        html = r.text
        assert "data-footer" not in html, url
        # The footer partials' own strings, as whole button/link labels.
        for label in ("Save", "Next →", "← Previous", "Cancel"):
            assert not re.search(
                r"<(?:button|a)\b[^>]*>\s*%s\s*</(?:button|a)>" % re.escape(label), html
            ), f"{label} on {url}"
        # The back link IS present — §2′.6 says the screen is left through it.
        assert re.search(r'<a[^>]*href="/"[^>]*>\s*← Your analyses\s*</a>', html), url


def test_panel_1_and_the_setup_band_are_gone_from_this_screen(env):
    """Asserted on the HOOKS, not on prose: the comments in this page still mention all of it.

    Every id and attribute below is a contract something else depends on, so their absence here is
    what says the deletion was complete rather than partial — a leftover `#slot-roster` with no
    `ha_fetch.js` behind it would be a dead roster that looks alive.
    """
    client, mod = env
    _seed(mod)
    html = _get(client)

    for hook in (
        'id="slot-roster"',          # panel ①'s roster
        'id="setup-band"',           # the setup band's root
        'id="source-drawer"',        # the source drawer
        'id="ha-config-dialog"',     # the HA connection modal
        'id="source-generation"',    # the generation node ha_fetch.js reconciles against
        'id="drawer-i18n"',          # the drawer's runtime strings
        "data-ingest-ws",            # the scoped ingest socket path
        'name="setup_haspv"',        # the household box's radios
        'name="setup_hasbattery"',
        "/static/ha_fetch.js",       # the module itself
    ):
        assert hook not in html, hook

    # …and the panel chrome that framed them.
    assert "PARAMETERS" not in html
    assert "Next: parameters" not in html
    assert 'class="badge badge-neutral">①<' not in html
    assert 'class="badge badge-neutral">②<' not in html


def test_the_dead_partials_are_gone_from_the_tree(env):
    """`_setup_band.html` and `_panel_data.html` are deleted, not merely un-included.

    An orphaned template renders nowhere and is invisible to every other test in this suite, so it
    would sit in the tree accumulating drift against the partials that replaced it. 4.1's changelog
    named both as 4.2's to remove; this is what makes that stick.
    """
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "app" / "templates"
    assert not (templates / "_setup_band.html").exists()
    assert not (templates / "_panel_data.html").exists()
    assert not (templates / "index.html").exists()
    # …and the screen that replaced index.html is there.
    assert (templates / "workspace_results.html").exists()


def test_the_household_macro_no_longer_carries_its_untitled_branch(env):
    """`_data_household.html`'s `titled=False` branch was panel ①'s and has no caller left.

    Asserted on the SOURCE because a dead template branch renders nowhere: nothing else in this
    suite can see it, and the next reader would take an unreachable conditional for a live one.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "app" / "templates" / "_data_household.html").read_text(encoding="utf-8")
    assert "titled" not in src.split("#}", 1)[1], "the titled= branch survives in the macro body"
    assert "{% macro household_box(cfg) %}" in src


# ── The screen's own chrome ───────────────────────────────────────────────────────────────────


def test_the_header_names_the_analysis_and_links_back(env):
    """§2′.6's wireframe: "← Your analyses" and the analysis title, as on the other two screens."""
    client, mod = env
    _seed(mod, title="Our house, dynamic contract")
    html = _get(client)

    header = html[html.index("<header"):html.index("</header>")]
    assert "Our house, dynamic contract" in header
    assert 'href="/"' in header
    assert "← Your analyses" in header


def test_a_title_with_markup_is_escaped_in_the_header(env):
    """The title is user input and reaches the header; it must be text, never markup."""
    client, mod = env
    _seed(mod, title="<script>alert(1)</script>")
    html = _get(client)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_params_form_action_is_scoped_at_this_render_site(env):
    """The no-JS fallback. The delegated handler intercepts the submit, so a flat action is inert
    while the script runs — and a 404 the moment it does not."""
    client, mod = env
    _seed(mod)
    html = _get(client)
    assert 'action="/w/w1/params"' in html
    assert 'action="/params"' not in html


def test_every_link_and_form_action_on_the_page_resolves(env):
    """No dangling href and no 404-ing action — the class of defect §2′.7 flagged by name.

    Fragment links are checked against the ids on the page; path links and form actions are
    requested. External and `javascript:` links are not expected here and their absence is asserted
    rather than skipped over.
    """
    client, mod = env
    _seed(mod)
    html = _get(client)

    ids = set(re.findall(r'\bid="([^"]+)"', html))
    hrefs = set(re.findall(r'href="([^"]+)"', html))
    assert hrefs, "no links at all — the scraping is wrong"

    for href in sorted(hrefs):
        assert not href.startswith(("http://", "https://", "javascript:")), href
        if href.startswith("#"):
            assert href[1:] in ids, f"fragment {href} resolves to nothing"
            continue
        path, _, frag = href.partition("#")
        r = client.get(path)
        assert r.status_code == 200, f"{href} → {r.status_code}"
        if frag:
            assert f'id="{frag}"' in r.text, f"{href}: no #{frag} on the target page"

    for action in set(re.findall(r'action="([^"]+)"', html)):
        r = client.post(action, data={})
        assert r.status_code != 404, f"{action} → 404"


# ── The `sections` marker: what each render claims (the phase-3 hazard) ───────────────────────


_CHECKBOXES = {
    "policy.allow_grid_export": "discharge",
    "policy.economic_guard": "pricing",
    "pricing.dal_weekends": "pricing_advanced",
    "topology.approximated": "topology",
}
"""Every checkbox `params_view.parse_form` gates, and the section marker that gates it.

The map is the contract this file's marker tests check: for each config shape, a checkbox is drawn
if and only if its marker is claimed. Getting that wrong in either direction is a defect — an
unclaimed drawn checkbox can never be unticked, and a claimed undrawn one is CLEARED on every save,
which is how phase 3 lost `policy.economic_guard` and `topology.approximated`.
"""


@pytest.mark.parametrize(
    "shape",
    ["defaults", "cost_on", "no_pv_1_phase", "three_phase_unsupported", "cost_on_no_pv"],
)
def test_the_sections_marker_names_exactly_the_checkboxes_this_render_draws(env, shape):
    """The phase-3 rule, re-derived for every config shape this screen has.

    A section name is a claim about WHICH CONTROLS WERE RENDERED. This does not assert an expected
    marker string — that would just restate `_sections_for` — it reads the rendered HTML and checks
    the two implications against `_CHECKBOXES`:

      * a DRAWN checkbox must have its marker claimed, or unticking it can never take effect;
      * an UNCLAIMED marker must draw none of its checkboxes, or the reverse.

    **`topology.approximated` is the one entry whose second implication does not hold, and that is
    correct.** The `topology` marker is claimed whenever the topology BOX is drawn, but the
    approximation checkbox only exists while the SELECTED phase topology is unsupported (§2.5b's
    soft block). `parse_form` handles the gap deliberately — inside a form that drew the box, it
    sets `approximated = False` whenever the topology is a supported one, "so a user who moves back
    to the 3-phase inverter is no longer carrying an approximation caveat they did not earn". The
    clearing is the specified behaviour there, not the phase-3 defect, so this test asserts that
    exact shape rather than exempting the field.
    """
    from app.domain.simconfig import BatteryPhases

    client, mod = env
    cfg = _seed(mod)
    configured = False
    if shape == "cost_on":
        cfg.simulate_cost, configured = True, True
    elif shape == "no_pv_1_phase":
        cfg.has_pv, cfg.grid.phases = False, 1
    elif shape == "three_phase_unsupported":
        cfg.grid.phases = 3
        cfg.topology.battery_phases = BatteryPhases.ONE_PHASE
    elif shape == "cost_on_no_pv":
        cfg.simulate_cost, configured = True, True
        cfg.has_pv, cfg.grid.phases = False, 1
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=configured)

    html = _get(client)
    claimed = set(re.search(r'name="sections" value="([^"]*)"', html).group(1).split())
    assert claimed, "the form must carry a sections marker"

    for name, marker in _CHECKBOXES.items():
        drawn = bool(re.search(r'<input[^>]*type="checkbox"[^>]*name="%s"' % re.escape(name), html))
        if drawn:
            assert marker in claimed, (
                f"{shape}: {name} is drawn but {marker!r} is not claimed — unticking it would "
                "never take effect"
            )
        elif marker in claimed and name != "topology.approximated":
            raise AssertionError(
                f"{shape}: {marker!r} is claimed but {name} is not drawn — a save would CLEAR the "
                "stored value"
            )

    # The `topology` exemption above is only sound because the clearing is deliberate. Pin that
    # rather than leaving the exemption unexplained: with the box drawn and a SUPPORTED topology
    # selected, a save clears `approximated`, which is what §2.5b asks for.
    if "topology" in claimed and 'name="topology.approximated"' not in html:
        stored = mod["simconfig_store"].load("w1")
        stored.topology.approximated = True
        mod["simconfig_store"].save(stored, "w1", pricing_configured=configured)
        client.post("/w/w1/params", data=_form_body(_get(client)))
        assert mod["simconfig_store"].load("w1").topology.approximated is False, (
            "a supported topology must not keep an approximation caveat the user did not earn"
        )


def test_an_unsupported_topology_keeps_its_acknowledgement_across_a_save(env):
    """The other side of the same rule: where the checkbox IS drawn, its ticked state round-trips.

    This is the phase-3 defect in its original form — an over-claiming marker cleared a deliberate
    user acknowledgement — so it is driven end to end on the shape where the control exists. It is
    also the test that would fail if the Installation TAB were conditionally rendered, since the
    checkbox lives inside it and an unopened tab that dropped its inputs would submit as unticked.
    """
    from app.domain.simconfig import BatteryPhases

    client, mod = env
    cfg = _seed(mod)
    cfg.grid.phases = 3
    cfg.topology.battery_phases = BatteryPhases.ONE_PHASE
    cfg.topology.approximated = True
    mod["simconfig_store"].save(cfg, "w1")

    html = _get(client)
    box = re.search(r'<input[^>]*name="topology\.approximated"[^>]*>', html)
    assert box and "checked" in box.group(0), "the acknowledgement is not rendered as ticked"

    client.post("/w/w1/params", data=_form_body(html))
    assert mod["simconfig_store"].load("w1").topology.approximated is True


def test_the_setup_marker_is_claimed_because_the_cost_toggle_is_drawn(env):
    """`setup` names `setup.simulate_cost`, which §2′.7 moved but did not rename.

    The marker is claimed on every render of this screen, and it must be: the toggle is a radio
    group, so without the marker `parse_form` could not tell "the user answered No" from "this
    submission did not carry the toggle", and answering No would silently do nothing.
    """
    client, mod = env
    cfg = _seed(mod)
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)
    html = _get(client)

    claimed = re.search(r'name="sections" value="([^"]*)"', html).group(1).split()
    assert "setup" in claimed
    assert 'name="setup.simulate_cost"' in html
    # …and the OTHER control that marker used to cover is not on this screen (§2′.7 moved it).
    assert 'name="setup.has_pv"' not in html


def test_answering_no_to_the_cost_toggle_actually_turns_it_off(env):
    """The end-to-end consequence of the marker being right, driven as the browser drives it.

    The failure this guards is silent: with `setup` missing from the marker, `parse_form` skips the
    branch entirely and the answer is discarded with a 200 and a re-rendered page. Both directions
    are exercised so a parser that ignored the field in one direction cannot pass.
    """
    client, mod = env
    cfg = _seed(mod)
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)

    body = _form_body(_get(client))
    body["setup.simulate_cost"] = "yes"
    r = client.post("/w/w1/params", data=body)
    assert r.status_code == 200 and r.headers["X-Params-Valid"] == "1"
    assert mod["simconfig_store"].load("w1").simulate_cost is True

    body = _form_body(_get(client))
    body["setup.simulate_cost"] = "no"
    r = client.post("/w/w1/params", data=body)
    assert r.status_code == 200 and r.headers["X-Params-Valid"] == "1"
    assert mod["simconfig_store"].load("w1").simulate_cost is False


def test_a_blocked_toggles_radios_are_not_submittable(env):
    """Blocked is enforced in the markup, not only in the styling.

    `disabled` is what stops the browser sending a value the server would honour — the route has no
    check of its own, deliberately (§2′.6 makes the edit screen the only place the precondition is
    cleared, and adding a second gate here would put the rule in two places). So the attribute IS
    the enforcement from this side, and `_form_body` — which drops disabled inputs exactly as a
    browser does — is what shows it works.
    """
    client, mod = env
    _seed(mod)  # pricing_configured stays False

    body = _form_body(_get(client))
    assert "setup.simulate_cost" not in body, "a Blocked toggle must not contribute a value"


# ── The results half is unchanged (§2′.6 "What is unchanged") ─────────────────────────────────


# A fixed hourly window so the results half has something real to simulate over: 30 days × 24 h of
# 1 h intervals from 2026-01-01 UTC, matching tests/test_results_route.py's fixture.
_DAYS = 30
_HOURS = _DAYS * 24
_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 1 + _DAYS, tzinfo=timezone.utc)


def _energy(name: str, per_interval: float, n: int = _HOURS) -> SeriesFrame:
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "energy", 3600, idx, np.full(n, float(per_interval)),
        np.zeros(n, dtype=QUALITY_DTYPE),
    )


def _price(name: str, per_interval: float, n: int = _HOURS) -> SeriesFrame:
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "price", 3600, idx, np.full(n, float(per_interval)),
        np.zeros(n, dtype=QUALITY_DTYPE),
    )


@pytest.fixture()
def with_data(env):
    """`env`, plus a persisted dataset the results half can actually simulate over.

    A spot price is included so the `cost_on` cases below have something to price — without it
    `results_from` emits no `cost` block whatever the toggle says, and a test about the cost section
    would be asserting on the energy-only render.
    """
    client, mod = env
    _seed(mod)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.4),
         _energy("solar_production", 3.0), _price("price_spot", 0.12)],
        (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )
    return client, mod


def test_editing_a_parameter_does_not_navigate_away_from_the_figures(with_data):
    """§2′.6 "What is unchanged": "editing a parameter still does not navigate away".

    The mechanism is that `POST /w/{id}/params` answers with a FRAGMENT and a 200 — never a
    redirect — which the page swaps in place. A route that started redirecting (as the edit and
    configure-data screens do) would take the reader away from the results a capacity change was
    made to see, which is the one thing §2′.6 is most insistent about.
    """
    client, mod = with_data
    before = _get(client)
    assert "GRID IMPORT SAVED" in before, "no figures on screen to navigate away from"

    body = _form_body(before)
    body["battery.usable_capacity_kwh"] = "25"
    r = client.post("/w/w1/params", data=body, follow_redirects=False)

    assert r.status_code == 200, "a parameter edit must not redirect"
    assert "location" not in {k.lower() for k in r.headers}
    # The response is the battery box alone, for an in-place swap — not a whole page.
    assert r.text.lstrip().startswith("<section") or 'id="panel-params"' in r.text[:400]
    assert "<!doctype" not in r.text.lower()
    assert mod["simconfig_store"].load("w1").battery.usable_capacity_kwh == 25.0

    # …and the figures are still there on the next render, over the same window.
    after = _get(client)
    assert "GRID IMPORT SAVED" in after


def test_the_battery_box_and_the_results_are_one_document(with_data):
    """§2′.6's central constraint: they "are on one screen and scroll together".

    Asserted as both fragments being in one response with no navigation between them, in that
    order. This is the property that would be lost by giving the parameters a route of their own,
    which §2′.6 rules out by name.
    """
    client, _ = with_data
    html = _get(client)
    box = html.index('id="panel-params"')
    results = html.index('id="panel-results"')
    assert box < results
    # In the same <main>, so they scroll together rather than being separate scroll regions.
    main = html[html.index("<main"):html.index("</main>")]
    assert 'id="panel-params"' in main and 'id="panel-results"' in main
    # Counted on the ELEMENTS, not on every occurrence of the string: the script block below
    # mentions both ids in `getElementById` calls, and a bare `.count()` matched them too.
    assert len(re.findall(r'<section[^>]*id="panel-params"', html)) == 1
    assert len(re.findall(r'<section[^>]*id="panel-results"', html)) == 1


def test_the_recompute_fragment_carries_the_cost_toggle_in_the_stored_state(with_data):
    """A range change re-renders the results block, which now CONTAINS the toggle.

    So `POST /w/{id}/results` has to supply the toggle's state and its Blocked flag, or every
    recompute would swap in a toggle that had forgotten both — reachable by clicking a period
    button, which is the most ordinary thing on the screen. Asserted in both Blocked states,
    because a fragment that hardcoded either would pass a single-state check.
    """
    client, mod = with_data
    cfg = mod["simconfig_store"].load("w1")

    r = client.post("/w/w1/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    assert 'id="setup-simulate-cost"' in r.text
    assert 'data-blocked="1"' in r.text, "Blocked must survive a recompute"

    mod["simconfig_store"].save(cfg, "w1", pricing_configured=True)
    r = client.post("/w/w1/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    assert 'id="setup-simulate-cost"' in r.text
    assert "data-blocked" not in r.text
    # The workspace id the Blocked branch's links are built from reaches the fragment too.
    mod["simconfig_store"].save(cfg, "w1", pricing_configured=False)
    r = client.post("/w/w1/results", json={"period": "last_1_week"})
    assert 'href="/w/w1/edit#contract"' in r.text


def test_a_refused_recompute_keeps_the_previous_figures_rather_than_blanking_them(with_data):
    """§3.1's `RESULTS_STALE`, as the page implements it: the spinner appears, the panel does not.

    The implementation is `#results-recalculating` being un-hidden for the duration of a recompute
    while the previous panel stays in the DOM — the recompute REPLACES it only once a response
    arrives, and its `.catch` leaves the last good panel alone on failure. Both halves are pinned:
    the affordance exists in the rendered fragment (so there is something to un-hide), and a failed
    recompute does not blank anything.

    **What this does NOT pin, despite what its original name claimed: the DIMMING.** §2′.6 says
    "`RESULTS_STALE` still renders the previous results dimmed rather than blanking them", and the
    app has never dimmed anything — the pre-4.2 page did not either, so §2′.6's "still" is honoured
    literally and phase 4.2 changed nothing here. The half that IS implemented (not blanking) is
    what this test covers; the dimming is an open spec point, recorded in `followups.md`, not a
    regression. The test was renamed because a green test named for `RESULTS_STALE` dimming reads as
    coverage of a thing that does not exist.
    """
    client, _ = with_data
    html = _get(client)
    # The affordance is rendered hidden, ready to be shown — not absent and created by script.
    spinner = re.search(r'<span[^>]*id="results-recalculating"[^>]*>', html)
    assert spinner, "no ⟳ recalculating affordance to show"
    assert "hidden" in spinner.group(0)

    # A recompute the server refuses must not blank the panel: the route answers 4xx and the
    # browser's handler keeps the last good fragment. Asserted on the route's side of that
    # contract — a 200 with an empty body would defeat the client's `.catch`.
    bad = client.post("/w/w1/results", json={"period": "last_decade"})
    assert bad.status_code == 400
    assert 'id="panel-results"' not in bad.text

    # …and the page still renders its figures afterwards.
    assert "GRID IMPORT SAVED" in _get(client)


# ── A blocking error must be READABLE, not merely rendered (§2′.6's pane, review finding 1) ───


def _post_params(client, **over) -> str:
    """Submit `#panel-params` and return the re-rendered fragment."""
    body = {
        "sections": "setup battery grid charge discharge",
        "battery.usable_capacity_kwh": "10",
    }
    body.update(over)
    return client.post("/w/w1/params", data=body).text


def _details_tag(html: str) -> str:
    m = re.search(r'<details[^>]*id="params-advanced"[^>]*>', html)
    assert m is not None, "no advanced pane in the re-rendered panel"
    return m.group(0)


def _checked_tab(html: str) -> str | None:
    m = re.findall(r'id="(params-tab-[a-z]+)"[^>]*checked', html.replace("\n", " "))
    return m[0] if m else None


def test_a_blocking_error_inside_the_pane_forces_it_open(env):
    """§2′.6's pane must not be able to hide the reason a run refused to happen.

    The pre-4.2 panel force-opened itself on an invalid render (`{% if not params.valid %}checked`
    on its collapse toggle). The reshape replaced that collapse with a `<details>` plus three tabs
    and dropped the compensation, so a bad value inside the pane produced "✕ needs attention" and
    nothing else: the message was in the DOM, `display: none`, the config was not persisted, and
    the results below still showed figures from the config the user had NOT submitted.
    """
    client, mod = env
    _seed(mod)

    html = _post_params(client, **{"battery.max_charge_kw": "-5"})
    assert "open" in _details_tag(html)
    # And the message is outside the pane, where no collapse or tab can hide it.
    assert "data-hidden-errors" in html
    assert "Must be greater than zero." in html


def test_a_valid_submission_leaves_the_pane_closed(env):
    """The other direction: the force-open is for errors only.

    Without this, the pane would spring open on every `[ Calculate → ]` and the collapsed-by-default
    rule §2′.6 states would be dead.
    """
    client, mod = env
    _seed(mod)

    html = _post_params(client)
    assert "open" not in _details_tag(html)
    assert "data-hidden-errors" not in html


def test_the_pane_opens_on_the_tab_holding_the_error(env):
    """Reopening is half the fix; landing on the right tab is the other half.

    Two of the three tabs are always hidden, so a pane that reopens on Battery while the offending
    input sits on Charge & discharge still shows the user nothing.
    """
    client, mod = env
    _seed(mod)

    assert _checked_tab(_post_params(client, **{"policy.band_a": "abc"})) == "params-tab-dispatch"
    assert _checked_tab(_post_params(client, **{"battery.max_charge_kw": "-5"})) == "params-tab-battery"
    # Nothing blocking → Battery keeps §2′.6's default.
    assert _checked_tab(_post_params(client)) == "params-tab-battery"


def test_the_hidden_error_alert_does_not_repeat_one_message(env):
    """Two checks can key one field; the same sentence twice reads as a rendering bug."""
    client, mod = env
    _seed(mod)

    html = _post_params(client, **{"battery.min_soc_pct": "150"})
    m = re.search(r'<div role="alert"[^>]*data-hidden-errors>(.*?)</div>', html, re.S)
    assert m is not None
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    assert text.count("Must be between 0 and 100.") == 1
