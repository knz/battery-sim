"""The configure-data screen and its two routes (specs/20-workspaces-ux.md §2′.5, §2′.8, §2′.11).

Phase 4.1 added `GET /w/{id}/data` and `POST /w/{id}/data`: panel ① promoted to a screen of its
own. Most of that screen is a MOVE — the roster, the drawer, the HA modal, the quality box and the
glance keep their markup and their behaviour — so what these tests pin is the part that is new, or
that the move could silently break:

  * **The move actually shares the markup.** The roster's ids and data-* attributes are a contract
    with `app/static/ha_fetch.js`: `#slot-roster` gates the whole module, `data-ingest-ws` carries
    the scoped socket path, and `applySetupGating` keys on the two radio NAMES. A screen that
    rendered a near-copy would pass a "looks like a roster" assertion and still have a dead drawer,
    so these tests name the specific hooks rather than the visible text.
  * **The two radios keep the names `setup_haspv` / `setup_hasbattery`.** The missing `setup.`
    prefix is load-bearing in two directions: index.html submits `#params-form` for anything named
    `setup.*`, and `params_view.parse_form` reads `setup.has_pv` behind a section gate. Renaming
    them would enlist these answers into panel ②'s form and into a different commit point.
  * **The form carries no `sections` field and the POST never reaches `parse_form`.** Phase 3
    shipped two data-loss defects through that marker (a section name is a claim about which
    CONTROLS were rendered), and this screen draws zero checkboxes. The test asserts the ABSENCE of
    the marker, because the failure mode is a future edit adding one "for consistency".
  * **A save that fails is REPORTED.** The underlying writer has a never-raises twin that the
    ingest-WS path depends on; reusing it here would return 303 and render a saved-looking screen
    with nothing on disk. That is the defect this file's last group exists for.
  * **`pricing_configured` is not touched.** §2′.6 makes the EDIT screen the one write that means
    "the user told us what they pay". A data save that set the flag would unblock the results
    screen's cost toggle from the wrong screen.
  * **The data-dependent boxes appear only once data has loaded**, per §2′.5's wireframe. Asserting
    they are absent in the empty state is as important as asserting they appear with a dataset:
    both directions are the specified behaviour.

Every regex below is scoped to a real element (an id, a `name=`, a `data-footer` wrapper) rather
than to prose, because this page also carries ~200 lines of inline script and comments whose text
mentions most of the things being asserted. Phase 3 shipped two tests that passed against a script
comment; the footer and `<details>` assertions there are the precedent for scoping.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame

_WIN = (
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    datetime(2026, 1, 31, tzinfo=timezone.utc),
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A client over an empty temp data dir, plus the modules that write into it.

    `monkeypatch.setenv` before any import that resolves the data dir, as everywhere else in this
    suite (and note followup I4: an in-test `monkeypatch.undo()` would redirect the rest of the
    test at the developer's real `./data`).
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset, db, main, simconfig_store, workspaces

    return TestClient(main.app), {
        "dataset": dataset,
        "db": db,
        "main": main,
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


def _energy(name: str, per_interval: float, n: int = 720) -> SeriesFrame:
    """One hourly energy series, flat, starting 2026-01-01 — enough for a real view-model."""
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "energy", 3600, idx, np.full(n, float(per_interval)),
        np.zeros(n, dtype=QUALITY_DTYPE),
    )


def _price(name: str, eur_per_kwh: float, n: int = 720) -> SeriesFrame:
    """One hourly price series — a dataset that LOADED but has no grid to simulate.

    `_WINDOW_SLOTS` (app/domain/reconcile.py) is the four grid-meter registers, so a dataset built
    from this alone makes `summary_view.data_summary_from` return None while the quality box still
    has content. That is the state the two boxes' gates have to tell apart.
    """
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "price", 3600, idx, np.full(n, float(eur_per_kwh)),
        np.zeros(n, dtype=QUALITY_DTYPE),
    )


def _seed_dataset(mod, workspace_id: str = "w1") -> None:
    """Persist a minimal grid-meter dataset, so the data-dependent boxes have something to show."""
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)],
        _WIN, "test", [], None, workspace_id,
    )


def _radio(html: str, name: str, value: str) -> str:
    """One radio input's tag, so an assertion about it cannot be met by other markup."""
    m = re.search(r'<input type="radio" name="%s" value="%s"[^>]*/?>' % (name, value), html)
    assert m is not None, f"no {name}={value} radio on the configure-data screen"
    return m.group(0)


def _footer(html: str) -> str:
    """Just the footer wrapper's contents.

    Scoped for the reason phase 3's changelog records: `"Previous" not in html` passed against an
    inline script COMMENT naming both modes' buttons, so a footer-mode assertion has to look at the
    footer rather than at the page.
    """
    m = re.search(r'<div class="[^"]*" data-footer>(.*?)</div>', html, re.S)
    assert m is not None, "no data-footer wrapper on the configure-data screen"
    return m.group(1)


# ── The screen renders, and renders the shared panel-① content ────────────────────────────────


def test_the_screen_renders_for_a_known_workspace(env):
    client, mod = env
    _seed(mod)
    resp = client.get("/w/w1/data")
    assert resp.status_code == 200
    # Not an empty body and not the list page: the screen's own heading, as an <h1>.
    assert re.search(r"<h1[^>]*>\s*Configure data\s*</h1>", resp.text)


def test_an_unknown_workspace_is_a_404(env):
    """`deps.get_workspace` 404s an unknown id before the route body runs."""
    client, _ = env
    assert client.get("/w/nope/data").status_code == 404


@pytest.mark.parametrize("bad", ["../etc", "a/b"])
def test_a_path_unsafe_workspace_id_is_refused(env, bad):
    """A traversal-shaped id must not resolve, on this route as on every other scoped one."""
    client, _ = env
    assert client.get(f"/w/{bad}/data").status_code == 404


def test_the_household_box_is_titled_and_draws_both_radios(env):
    """§2′.5's one visual change: the two questions get a titled box.

    The title is asserted as a heading element, not as loose text, so the ⓘ blurb and the inline
    script's comments cannot satisfy it.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert re.search(r"<h2[^>]*>\s*About your household\s*</h2>", html)
    # Both groups, both options each — four radios, in the box.
    for name in ("setup_haspv", "setup_hasbattery"):
        for value in ("1", "0"):
            _radio(html, name, value)


def test_the_radios_keep_the_undotted_names(env):
    """`setup_haspv`, NOT `setup.has_pv` — see the module docstring.

    A rename would silently enlist these answers into `#params-form` (index.html submits anything
    named `setup.*`) and into `parse_form`'s section-gated branch, which is a different commit
    point with different semantics.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert 'name="setup_haspv"' in html
    assert 'name="setup_hasbattery"' in html
    assert 'name="setup.has_pv"' not in html
    assert 'name="setup.has_battery"' not in html


def test_the_stored_answers_are_the_checked_radios(env):
    """The box reports what is stored, in both directions."""
    client, mod = env
    cfg = _seed(mod)
    cfg.has_pv = False
    cfg.has_battery = True
    _store(mod, cfg)

    html = client.get("/w/w1/data").text
    assert "checked" in _radio(html, "setup_haspv", "0")
    assert "checked" not in _radio(html, "setup_haspv", "1")
    assert "checked" in _radio(html, "setup_hasbattery", "1")
    assert "checked" not in _radio(html, "setup_hasbattery", "0")


def test_the_roster_carries_the_hooks_ha_fetch_js_depends_on(env):
    """The roster is the real one, not a look-alike.

    `#slot-roster` is the module gate in `app/static/ha_fetch.js` (it returns immediately when the
    node is absent), and `data-ingest-ws` carries the whole workspace-scoped socket path, rendered
    server-side so that file never builds a URL. A screen missing either renders a roster that
    cannot fetch anything.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert 'id="slot-roster"' in html
    assert 'data-ingest-ws="/w/w1/data/ingest/ws"' in html
    assert 'id="ha-fetch-btn"' in html
    # At least one real slot row with its per-slot source button.
    assert 'class="slot-row' in html
    assert "slot-source-btn" in html
    assert re.search(r'data-slot-sources="[^"]+"', html)


def test_the_drawer_and_the_ha_modal_are_present_at_page_level(env):
    """§2′.5: the drawer stays a right-side overlay over this screen, with Confirm/Cancel intact."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    for node_id in (
        "source-drawer", "drawer-source-list", "drawer-confirm", "drawer-cancel",
        "drawer-entity-select", "ha-config-dialog", "ha-base-url", "ha-token",
        "ha-test-btn", "ha-status", "slot-info-dialog", "pending-dialog",
    ):
        assert f'id="{node_id}"' in html, f"missing #{node_id}"


def test_the_screen_loads_ha_fetch_js_and_its_runtime_context(env):
    """The script, plus the two JSON blocks it reads: the i18n strings and the generation."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert "/static/ha_fetch.js" in html
    assert 'id="drawer-i18n"' in html
    assert 'id="source-generation"' in html
    assert f'data-workspace-id="w1"' in html


def test_the_generation_is_the_stored_one(env):
    """The dirty check compares against this number, so it must be the workspace's own."""
    client, mod = env
    _seed(mod)
    mod["db"].bump_source_generation("w1")
    mod["db"].bump_source_generation("w1")
    html = client.get("/w/w1/data").text
    m = re.search(r'<script id="source-generation" type="application/json">(.*?)</script>', html)
    assert m is not None
    assert m.group(1).strip() == "2"


# ── The data-dependent boxes, in both directions (§2′.5 "Present once data has loaded") ───────


def test_the_quality_box_and_glance_are_absent_before_any_data(env):
    """Both are "present once data has loaded"; before that there is nothing to report."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert 'id="data-quality"' not in html
    assert "at a glance" not in html


def test_the_quality_box_and_glance_appear_once_data_has_loaded(env):
    """With a real dataset both boxes render, from the same view-model panel ① uses."""
    client, mod = env
    _seed(mod)
    _seed_dataset(mod)
    html = client.get("/w/w1/data").text
    assert 'id="data-quality"' in html
    assert "at a glance" in html
    # The quality box's real content, not just its shell.
    assert "Coverage" in html
    assert "Simulation grid" in html


def test_a_dataset_with_no_simulatable_grid_keeps_the_quality_box(env):
    """The two boxes answer to different gates, and one gate for both was a review finding.

    A price-only dataset is a real intermediate state — the spot-price preset is a `backend_load`
    source that loads on its own, before any meter is mapped — and `data_summary_from` returns None
    for it, because there is no grid to summarise. Gating the quality box on that same key made it
    vanish exactly here: a user whose fetch produced an unusable dataset saw a roster, no glance and
    no quality box, which is indistinguishable from having fetched nothing at all. This is the
    screen whose whole job is saying WHY the data cannot be used, so the box has to stay.

    The glance is correctly absent — it reports figures that need a grid.
    """
    client, mod = env
    _seed(mod)
    mod["dataset"].save_dataset(
        [_price("price_spot", 0.10)], _WIN, "test", [], None, "w1"
    )

    html = client.get("/w/w1/data").text
    assert 'id="data-quality"' in html
    assert "at a glance" not in html
    # The box's real content, so this cannot pass against an empty shell.
    assert "Coverage" in html


def test_the_roster_renders_before_any_data(env):
    """The roster is NOT data-gated — it is how the user supplies the data in the first place."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert 'id="slot-roster"' in html


# ── The footer, in both modes (§2′.8) ─────────────────────────────────────────────────────────


def test_the_card_footer_is_cancel_and_save(env):
    client, mod = env
    _seed(mod)
    footer = _footer(client.get("/w/w1/data").text)
    assert "Cancel" in footer
    assert "Save" in footer
    assert "Previous" not in footer
    assert "Next" not in footer


def test_the_wizard_footer_is_previous_and_next(env):
    client, mod = env
    _seed(mod)
    footer = _footer(client.get("/w/w1/data?mode=wizard").text)
    assert "Previous" in footer
    assert "Next" in footer
    assert "Cancel" not in footer
    # "Save" must not appear as a BUTTON here; the wizard's right button is `[ Next → ]`.
    assert not re.search(r"<button[^>]*>\s*Save\s*</button>", footer)


def test_the_wizard_previous_goes_back_to_step_one_in_wizard_mode(env):
    """§2′.8: `[ ← Previous ]` goes back a step, keeping entries — so back to the EDIT screen.

    And it must stay in wizard mode, or step 1 would render a `[ Cancel ] [ Save ]` footer in the
    middle of a wizard run.
    """
    client, mod = env
    _seed(mod)
    footer = _footer(client.get("/w/w1/data?mode=wizard").text)
    assert 'href="/w/w1/edit?mode=wizard"' in footer


def test_both_footer_modes_guard_only_the_leaving_button(env):
    """§2′.8: the dirty check guards what LEAVES, never `[ Save ]` / `[ Next → ]`."""
    client, mod = env
    _seed(mod)
    for url in ("/w/w1/data", "/w/w1/data?mode=wizard"):
        footer = _footer(client.get(url).text)
        assert footer.count("data-leave") == 1, url
        # The guarded control is the link, not the submit button.
        assert re.search(r"<a[^>]*data-leave", footer), url
        assert not re.search(r"<button[^>]*data-leave", footer), url


def test_the_back_link_is_guarded_too(env):
    """§2′.8: the back link behaves as `[ Cancel ]`, so the same check guards it."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    header = re.search(r"<header.*?</header>", html, re.S)
    assert header is not None
    assert "data-leave" in header.group(0)


def test_the_next_parameters_cta_is_gone(env):
    """§2′.5: the CTA is REPLACED by the footer. It must not also be here."""
    client, mod = env
    _seed(mod)
    assert "Next: parameters" not in client.get("/w/w1/data").text


def test_the_mode_survives_into_the_form_action_and_a_hidden_field(env):
    """The wizard mode must survive a re-render, so it travels both ways."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data?mode=wizard").text
    assert 'action="/w/w1/data?mode=wizard"' in html
    assert re.search(r'<input type="hidden" name="mode" value="wizard"', html)


def test_the_save_error_notice_keeps_the_wizard_footer(env):
    """A failed save must not drop the user out of the wizard.

    The re-render is the only path that shows the notice, so this is where the mode surviving a
    re-render is actually observable.
    """
    client, mod = env
    _seed(mod)

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    original = mod["main"]._write_setup_answers
    mod["main"]._write_setup_answers = boom
    try:
        resp = client.post(
            "/w/w1/data?mode=wizard",
            data={"setup_haspv": "1", "setup_hasbattery": "0", "mode": "wizard"},
            follow_redirects=False,
        )
    finally:
        mod["main"]._write_setup_answers = original

    assert resp.status_code == 200
    footer = _footer(resp.text)
    assert "Next" in footer
    assert "Cancel" not in footer


# ── The POST: what it writes, and what it must not touch ──────────────────────────────────────


def test_the_answers_round_trip_through_the_post(env):
    """Both directions, through the real route, read back off the store."""
    client, mod = env
    cfg = _seed(mod)
    cfg.has_pv = True
    cfg.has_battery = False
    _store(mod, cfg)

    resp = client.post(
        "/w/w1/data",
        data={"setup_haspv": "0", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    stored = mod["simconfig_store"].load("w1")
    assert stored.has_pv is False
    assert stored.has_battery is True

    # And back, so a test cannot pass by storing the value it then asserts.
    client.post(
        "/w/w1/data",
        data={"setup_haspv": "1", "setup_hasbattery": "0"},
        follow_redirects=False,
    )
    stored = mod["simconfig_store"].load("w1")
    assert stored.has_pv is True
    assert stored.has_battery is False


def test_a_card_save_returns_to_the_list_and_the_wizard_advances(env):
    """§2′.8: `[ Save ]` persists and returns to the list; `[ Next → ]` persists and advances."""
    client, mod = env
    _seed(mod)

    resp = client.post(
        "/w/w1/data", data={"setup_haspv": "1", "setup_hasbattery": "0"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    resp = client.post(
        "/w/w1/data?mode=wizard", data={"setup_haspv": "1", "setup_hasbattery": "0"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/w/w1/results"


def test_an_absent_radio_leaves_the_stored_answer_alone(env):
    """A group the submission did not carry is not the user answering "no".

    This is the property that makes the POST safe to send from a partial form, and it is the
    analogue of `parse_form`'s inherit-if-absent rule for a route that does not use it.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.has_pv = True
    cfg.has_battery = True
    _store(mod, cfg)

    client.post("/w/w1/data", data={"setup_haspv": "0"}, follow_redirects=False)
    stored = mod["simconfig_store"].load("w1")
    assert stored.has_pv is False       # submitted
    assert stored.has_battery is True   # absent, so untouched


def test_turning_pv_off_re_applies_the_forced_invariants(env):
    """§2.5: PV off forces `pv_coupling` to None and `battery.coupling` to AC.

    Asserted through the route, end to end, because it is the user-visible property: a household
    that says it has no solar must not keep a stored DC coupling for an array it does not have.

    **What this test does NOT prove, having been measured:** it is not a test of the clone in
    `_write_setup_answers`. Dropping that clone was tried and this test still passed, because
    `simconfig_store.save` re-applies the invariants itself on the write path (`to_dict`), so the
    normalisation happens either way. The clone there is defence in depth — it keeps the in-memory
    object consistent for anything that inspects it before the save — rather than the mechanism this
    property rests on. Recorded here so a future reader does not mistake a passing test for
    coverage of that line.
    """
    from app.domain.simconfig import Coupling, PvCoupling

    client, mod = env
    cfg = _seed(mod)
    cfg.has_pv = True
    cfg.topology.pv_coupling = PvCoupling.DC_HYBRID
    cfg.battery.coupling = Coupling.DC_HYBRID
    _store(mod, cfg)
    assert mod["simconfig_store"].load("w1").battery.coupling is Coupling.DC_HYBRID

    client.post(
        "/w/w1/data", data={"setup_haspv": "0", "setup_hasbattery": "0"},
        follow_redirects=False,
    )
    stored = mod["simconfig_store"].load("w1")
    assert stored.has_pv is False
    assert stored.battery.coupling is Coupling.AC
    assert stored.topology.pv_coupling is None


def test_the_post_does_not_set_pricing_configured(env):
    """§2′.6: the EDIT screen is what means "the user told us what they pay".

    A data save that set the flag would unblock the results screen's cost toggle from a screen that
    never asked about money. The store's default is "carry forward", which this relies on.
    """
    client, mod = env
    _seed(mod)
    assert mod["simconfig_store"].is_pricing_configured("w1") is False

    client.post(
        "/w/w1/data", data={"setup_haspv": "1", "setup_hasbattery": "0"},
        follow_redirects=False,
    )
    assert mod["simconfig_store"].is_pricing_configured("w1") is False


def test_an_already_configured_pricing_flag_survives_this_save(env):
    """The other direction: carry-forward must not CLEAR it either."""
    client, mod = env
    cfg = _seed(mod)
    mod["simconfig_store"].save(
        mod["simconfig_store"].clone(cfg), "w1", pricing_configured=True
    )
    assert mod["simconfig_store"].is_pricing_configured("w1") is True

    client.post(
        "/w/w1/data", data={"setup_haspv": "1", "setup_hasbattery": "0"},
        follow_redirects=False,
    )
    assert mod["simconfig_store"].is_pricing_configured("w1") is True


def test_a_successful_save_advances_updated_at(env):
    """§2′.10: a config save is what moves the list's ordering and its "last saved" badge.

    Asserted through the ORDER of two workspaces, not as `after >= before` on one. That comparison
    was the original here and it cannot fail: `updated_at` comes from a monotonic clock, so it holds
    whether or not the route touches anything — deleting `workspaces.touch` from the route left the
    whole non-browser suite green. Ordering is the property the list screen actually reads.
    """
    client, mod = env
    _seed(mod)
    mod["workspaces"].create("Second", workspace_id="w2")
    # w2 was touched last, so it leads.
    assert [s.id for s in mod["workspaces"].list_summaries()] == ["w2", "w1"]

    client.post(
        "/w/w1/data", data={"setup_haspv": "0", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    assert [s.id for s in mod["workspaces"].list_summaries()] == ["w1", "w2"]


def test_a_save_that_stored_nothing_does_not_advance_updated_at(env):
    """A body carrying neither radio writes nothing, so it is not a "last saved" event.

    `_write_setup_answers` returns early when both answers are None. Touching anyway would move the
    workspace to the top of the list with its badge advanced for a save that wrote nothing — which
    is what the route did until review, while its comment claimed the opposite. Only reachable by a
    hand-made POST, since a rendered form always submits both radios.
    """
    client, mod = env
    _seed(mod)
    mod["workspaces"].create("Second", workspace_id="w2")
    assert [s.id for s in mod["workspaces"].list_summaries()] == ["w2", "w1"]

    r = client.post("/w/w1/data", data={}, follow_redirects=False)
    assert r.status_code == 303
    assert [s.id for s in mod["workspaces"].list_summaries()] == ["w2", "w1"]


def test_the_post_leaves_settings_it_does_not_draw_alone(env):
    """The whole rest of the config survives a save from this screen.

    The analogue of the edit screen's inheritance test, and the failure would be just as silent: a
    user who answered "no solar" would find their battery reset to appendix A's defaults.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.battery.usable_capacity_kwh = 17.5
    cfg.grid.fuse_a = 63.0
    cfg.grid.phases = 3
    _store(mod, cfg)

    client.post(
        "/w/w1/data", data={"setup_haspv": "0", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    stored = mod["simconfig_store"].load("w1")
    assert stored.battery.usable_capacity_kwh == 17.5
    assert stored.grid.fuse_a == 63.0
    assert stored.grid.phases == 3


def test_the_post_404s_for_an_unknown_workspace(env):
    client, _ = env
    resp = client.post(
        "/w/nope/data", data={"setup_haspv": "1"}, follow_redirects=False
    )
    assert resp.status_code == 404


# ── The `sections` marker: absent, and it must stay absent ────────────────────────────────────


def test_the_screen_renders_no_sections_marker(env):
    """This screen draws no checkbox, so it claims no section.

    Asserted as an absence because the failure mode is a future edit adding a marker "for
    consistency" with the other two forms — and `parse_form` gates every checkbox on it, so a
    marker claiming a section whose checkbox this screen never drew CLEARS that stored value. Phase
    3 shipped exactly that twice.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert 'name="sections"' not in html


def test_the_screen_draws_no_checkbox_at_all(env):
    """The premise of the test above. If this ever fails, the marker question reopens."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert 'type="checkbox"' not in html


def test_a_save_from_this_screen_preserves_the_stored_checkbox_settings(env):
    """The behavioural consequence, through the real route.

    `policy.economic_guard` and `topology.approximated` are the two settings phase 3's marker
    defects cleared. Neither is drawn here, and this screen's POST does not reach `parse_form` at
    all — so both must come back untouched. Driven end-to-end rather than by inspecting the form,
    because that is the property that actually matters to the user.
    """
    client, mod = env
    cfg = _seed(mod)
    cfg.simulate_cost = True
    cfg.policy.economic_guard = True
    _store(mod, cfg)
    assert mod["simconfig_store"].load("w1").policy.economic_guard is True

    client.post(
        "/w/w1/data", data={"setup_haspv": "0", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    assert mod["simconfig_store"].load("w1").policy.economic_guard is True


def test_a_save_from_this_screen_preserves_a_topology_approximation(env):
    """The second of phase 3's two defects, on this screen's path.

    `topology.approximated` records a DELIBERATE user acknowledgement (§2.5(b)'s soft block) and is
    never derived, so clearing it would re-raise a block the user already answered and drop the
    approximation caveat from the results. The in-test assertion that the topology really is
    unsupported keeps the branch under test genuinely reachable.
    """
    from app.domain.simconfig import BatteryPhases
    from app.params_view import phase_topology_unsupported

    client, mod = env
    cfg = _seed(mod)
    cfg.grid.phases = 3
    cfg.grid.fuse_a = 25.0
    cfg.topology.battery_phases = BatteryPhases.ONE_PHASE
    cfg.topology.approximated = True
    _store(mod, cfg)

    stored = mod["simconfig_store"].load("w1")
    assert phase_topology_unsupported(stored) is True, "the branch under test is not reachable"
    assert stored.topology.approximated is True

    client.post(
        "/w/w1/data", data={"setup_haspv": "0", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    assert mod["simconfig_store"].load("w1").topology.approximated is True


# ── The save-error path: a failure must be reported, never swallowed ──────────────────────────


def test_a_failing_save_is_reported_rather_than_redirecting(env):
    """The defect this route nearly shipped.

    The writer has a never-raises twin (`_persist_setup_answers`) that the ingest-WS path depends
    on: it runs after a fetch has already persisted a dataset, so it must not fail a fetch whose
    real work succeeded. Reusing it here would mean a `[ Save ]` against an unwritable data dir
    logged a warning, returned 303, and showed the user a successfully-saved screen with nothing
    saved. The route uses the RAISING variant and renders the notice instead.

    Not a 500 either: an unwritable data directory is a foreseeable local condition, the same
    treatment `POST /params` and `POST /w/{id}/edit` give it.
    """
    client, mod = env
    _seed(mod)

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    original = mod["main"]._write_setup_answers
    mod["main"]._write_setup_answers = boom
    try:
        resp = client.post(
            "/w/w1/data",
            data={"setup_haspv": "0", "setup_hasbattery": "1"},
            follow_redirects=False,
        )
    finally:
        mod["main"]._write_setup_answers = original

    assert resp.status_code == 200, "a failed save must not redirect as if it had worked"
    assert "could not be saved" in resp.text
    # And it is the screen, re-rendered — not a bare error body.
    assert 'id="slot-roster"' in resp.text


def test_a_failing_save_does_not_advance_updated_at(env):
    """The badge reports when the configuration was last STORED, and nothing was."""
    client, mod = env
    _seed(mod)
    before = mod["workspaces"].list_summaries()[0].updated_at

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    original = mod["main"]._write_setup_answers
    mod["main"]._write_setup_answers = boom
    try:
        client.post(
            "/w/w1/data", data={"setup_haspv": "0"}, follow_redirects=False
        )
    finally:
        mod["main"]._write_setup_answers = original

    assert mod["workspaces"].list_summaries()[0].updated_at == before


def test_the_never_raises_writer_still_never_raises(env):
    """The ingest-WS path's contract, pinned where the split could break it.

    `_persist_setup_answers` is now a wrapper over the raising `_write_setup_answers`. If a
    refactor ever collapses the two back together, the WS `done` handler would start failing
    fetches whose dataset is already on disk.
    """
    client, mod = env
    _seed(mod)

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    original = mod["main"]._write_setup_answers
    mod["main"]._write_setup_answers = boom
    try:
        # Must not raise.
        mod["main"]._persist_setup_answers("w1", True, False)
    finally:
        mod["main"]._write_setup_answers = original


def test_both_writers_agree_on_what_committing_the_answers_means(env):
    """§2′.5: the answers are "still committed with the fetch", and now also by `[ Save ]`.

    Two writers for one pair of answers is a drift risk, so they share a body. Driving each and
    comparing the stored result is what pins that they still do.
    """
    client, mod = env
    _seed(mod)

    mod["main"]._persist_setup_answers("w1", False, True)
    by_fetch = mod["simconfig_store"].load("w1")

    _store(mod, _seed(mod, workspace_id="w2", title="Other"))
    client.post(
        "/w/w2/data", data={"setup_haspv": "0", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    by_save = mod["simconfig_store"].load("w2")

    assert (by_fetch.has_pv, by_fetch.has_battery) == (False, True)
    assert (by_save.has_pv, by_save.has_battery) == (False, True)
    assert by_fetch.battery.coupling == by_save.battery.coupling
    assert by_fetch.topology.pv_coupling == by_save.topology.pv_coupling


# ── The dirty warning's server-side half (§2′.8, §2′.11) ──────────────────────────────────────


def test_the_screen_carries_the_unfetched_dialog_and_its_copy(env):
    """§2′.8 gives this screen its OWN warning, not the edit screen's "Discard your changes?".

    The wording is the point: what is at stake here is a mapping that never took effect, not typed
    text about to be lost, so the two dialogs are deliberately different copy.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    dialog = re.search(r'<dialog id="unfetched-dialog".*?</dialog>', html, re.S)
    assert dialog is not None, "no staged-but-unfetched dialog on the configure-data screen"
    body = dialog.group(0)
    assert "You have not loaded your data yet" in body
    assert "Keep editing" in body
    assert "Leave anyway" in body
    # Not the edit screen's copy.
    assert "Discard your changes?" not in html


def test_the_dialogs_default_focus_is_the_safe_option(env):
    """`[ Keep editing ]` takes Enter; `[ Leave anyway ]` must not be autofocused."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    dialog = re.search(r'<dialog id="unfetched-dialog".*?</dialog>', html, re.S).group(0)
    autofocused = re.search(r"<button[^>]*autofocus[^>]*>(.*?)</button>", dialog, re.S)
    assert autofocused is not None
    assert "Keep editing" in autofocused.group(1)


def test_the_dirty_check_reads_the_generation_tagged_store(env):
    """§2′.11: the check is keyed on `ha.slots.<workspace>` compared against `source_generation`.

    Asserted on the rendered script because that is where the check lives — it is browser state, so
    there is no server-side behaviour to drive here. What this pins is that the check reads the
    per-WORKSPACE key and compares the generation at all: a check keyed on the global `ha.slots`
    would fire for a mapping staged in a different analysis, and one that ignored the generation
    would fire forever after the first fetch.

    The behavioural half of this is a Playwright test, which is the only place a real
    `localStorage` exists.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert "'ha.slots.' + WORKSPACE_ID" in html
    assert "obj.gen !== serverGen()" in html
