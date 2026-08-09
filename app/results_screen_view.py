"""The view-model for the results screen's own chrome (docs/specs/20-workspaces-ux.md §2′.6).

`GET /w/{id}/results` renders panels ② and ③ combined, with ② reduced to a capacity-first battery
box. Almost all of what that screen draws already has a view-model: the parameter fields come from
`app/params_view.py` unchanged, and the result sections from `app/results_view.py` unchanged. This
module supplies only the three things §2′.6 ADDS, which neither of those knows about:

    the workspace title            shown in the header, as on the other two screens;
    the advanced pane's count      "N changed from default" on the collapsed summary;
    the cost toggle's Blocked flag `pricing_configured`, read by the route.

## The "N changed from default" count

§2′.6: the collapsed summary "should name how many values differ from the defaults", exactly as
§2′.4's advanced panes do. `advanced_changed_count` is that number, and it is deliberately the SAME
technique `workspace_edit_view._overridden_count` uses — comparison against a freshly-constructed
`SimulationConfig`, so the count follows appendix A wherever appendix A moves rather than being
pinned to a hardcoded table that would quietly go stale.

**What it counts is everything the pane holds, and nothing outside it.** `usable_capacity_kwh` is
excluded because it is drawn OUTSIDE the pane: a user who changed the one field they can see
already sees it, and counting it would make the summary say "1 changed" about a pane whose contents
are all still default. `ADVANCED_PATHS` is the enumeration, grouped by the tab that draws each
path, and the grouping is not decorative — it is what lets a test assert that the count covers the
tabs and only the tabs.

**Enum and boolean settings count too.** The charge policy, the discharge policy, the coupling, the
battery-phase topology, `allow_grid_export` and `economic_guard` are all settings a user can change
and then collapse the pane over, which is the situation the count exists for. `!=` compares them
correctly: enums compare by identity, booleans by value, and a raw string the user typed into a
numeric field compares unequal to the default number — which is the honest answer, since it
certainly is not the default.

**`economic_guard` is read off `cfg.policy`, not off `cfg.economic_guard`.** The property forces
False without a cost model (§2.3), so reading it would make the count drop when cost simulation is
switched off even though the stored answer is unchanged and appendix A says it is RETAINED. The
pane's summary should describe what is stored, since that is what comes back when the toggle
returns.

## `pricing_configured` is passed in, not read here

This module does no I/O, like every other view-model in the app. The flag comes from
`simconfig_store.is_pricing_configured(ws.id)`, which the route calls. §2′.6's name for it is
`pricing.configured`; the code's name is `retained.pricing_configured` (phase 0), and phase 3's
edit screen is the one write that sets it.

Main items:
    ADVANCED_PATHS              the dotted paths behind "More settings", grouped by tab.
    advanced_changed_count(cfg) how many of them differ from the appendix-A defaults.
    results_screen_view(...)    the dict `workspace_results.html` renders.
"""

from __future__ import annotations

from app import workspace_list_view
from app.domain.simconfig import SimulationConfig

# Every setting the "More settings" pane draws, grouped by the tab that draws it (§2′.6). The
# grouping is asserted by the tests, so a path added to a tab in the template and not here — or the
# other way round — shows up as a count that does not describe the pane.
#
# `battery.usable_capacity_kwh` is deliberately ABSENT: §2′.6 puts it in front of the pane, so it is
# not something a collapsed pane can hide. `battery.roundtrip_dc_bonus` is absent too — no screen
# draws an input for it (it is applied by §6.8's DC path from the coupling choice), so a count that
# included it would report a change the user cannot see or undo.
ADVANCED_PATHS: dict[str, tuple[str, ...]] = {
    # Tab 1 — Battery. §2.3's box 1 minus the capacity, plus the coupling the box reports.
    "battery": (
        "battery.min_soc_pct",
        "battery.max_soc_pct",
        "battery.max_charge_kw",
        "battery.max_discharge_kw",
        "battery.roundtrip_efficiency",
        "battery.standby_w",
        "battery.initial_soc_pct",
        "battery.coupling",
    ),
    # Tab 2 — Installation. §2.3's box 3, the illustrated topology selectors (§2.5).
    #
    # `topology.approximated` is NOT counted. It is not a setting the user chose in preference to a
    # default; it is an acknowledgement of a soft block that only exists while the selected
    # topology is unsupported, and the alert carrying it is on screen whenever it can be true. A
    # count including it would say "1 changed" about a pane whose visible warning already says so.
    "installation": (
        "topology.pv_coupling",
        "topology.battery_phases",
    ),
    # Tab 3 — Charge & discharge. §2.3's boxes 4 and 5, which share a tab because the overlap
    # warning compares their two band pairs (§2′.6).
    "dispatch": (
        "policy.charge_policy",
        "policy.band_a",
        "policy.band_b",
        "policy.discharge_policy",
        "policy.band_c",
        "policy.band_d",
        "policy.allow_grid_export",
        "policy.economic_guard",
    ),
}


def _get_path(cfg: SimulationConfig, path: str):
    """Read a dotted path off a config. Mirrors `params_view._get_path`.

    Duplicated rather than imported for the reason `workspace_edit_view` gives for its own copy:
    it is three lines, and importing a private helper across two view-models to save them would
    tie the two modules together for nothing.
    """
    obj = cfg
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def advanced_changed_count(cfg: SimulationConfig) -> int:
    """How many of `ADVANCED_PATHS` differ from the appendix-A defaults (§2′.6).

    Compared against a freshly-constructed `SimulationConfig` rather than a hardcoded table, so the
    count follows appendix A. See the module comment for why `usable_capacity_kwh` is not in the
    set, and for why the stored `policy.economic_guard` is read rather than the forced
    `cfg.economic_guard` property.
    """
    defaults = SimulationConfig()
    n = 0
    for paths in ADVANCED_PATHS.values():
        for path in paths:
            if _get_path(cfg, path) != _get_path(defaults, path):
                n += 1
    return n


def results_screen_view(
    cfg: SimulationConfig,
    title: str,
    *,
    pricing_configured: bool = False,
) -> dict:
    """The dict `workspace_results.html` renders for its own chrome (§2′.6). No I/O, no mutation.

    Everything else on the screen renders from `params` (`params_view.params_view`) and `results`
    (`results_view.results_from`, or the static sample), which this does not touch and does not
    wrap: a second layer over those would be a second place for the panel-② and panel-③ contracts
    to drift.

    `title` comes from the `workspaces` row, as on the other two screens — displayed only; renaming
    is the edit screen's job (§2′.4).

    `pricing_configured` decides whether the cost toggle is live or **Blocked** (§2′.6). Blocked,
    not Inapplicable, and the spec argues the distinction explicitly: the precondition is one screen
    away from met, so hiding the control would leave a user who wants euro figures with nothing to
    click and nothing to read. The route reads the flag from
    `simconfig_store.is_pricing_configured`; it is not read here because view-models do no I/O.

    There is no `wizard` key and no footer mode. §2′.6 gives this screen NO footer buttons in either
    mode: it is the end of both the card path and the wizard path, and it is left through the back
    link. A footer flag would be a flag with one value.
    """
    return {
        # Through `display_title` so the demo workspace's header follows the language toggle like
        # the rest of the page; a user-chosen title passes through untouched. Display only — the
        # edit screen deliberately does NOT do this, since its title is a rename field's value.
        "title": workspace_list_view.display_title(title),
        "pricing_configured": bool(pricing_configured),
        "advanced_changed": advanced_changed_count(cfg),
    }
