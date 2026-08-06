"""The configure-data screen and its two routes (docs/specs/20-workspaces-ux.md §2′.5, §2′.8, §2′.11).

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

Phase 5 added the last two groups: **§2′.8's step-2 gate** and the step indicator. The gate blocks
the wizard's `[ Next → ]` until §6.3's load reconstruction is computable, and three things about it
are worth stating up front, because each is a way the tests could look right and prove nothing.

  * **Every conditional role is driven in BOTH directions.** A test that only checks solar is
    required when `has_pv` would pass against an implementation that required it always — which
    would block every PV-less household permanently. So each of the four conditional cases has its
    negative twin.
  * **T2 is asserted NOT to block.** §2′.8's parenthetical reads as if all four registers were
    required; the code requires T1 only, deliberately (D2), and a single-tariff household has no T2
    meter. This is the most likely thing in the phase to be "fixed" back into a defect.
  * **The gate is checked server-side too, and that half is driven by a crafted POST.** A
    `disabled` attribute is a rendering, not a guarantee; followup L3 is this project's live example
    of one being walked past.

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
    mod["workspaces"].create(title, workspace_id=workspace_id, owner_id=mod["workspaces"].OWNER_ID)
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
        _WIN, "test", [], None, workspace_id=workspace_id,
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


@pytest.mark.parametrize("gone", ["price_spot_min", "price_spot_max"])
def test_the_bracket_slots_are_out_of_the_vocabulary(gone):
    """D3: the two intra-hour bracket slots are never asked for again.

    §6.16's bracket is now DERIVED from `price_spot`'s own interval spacing
    (simframe `_resample_price_stats`), so there is no user-supplied min/max series. The
    vocabulary is the gate for ingest as well as for the roster: a payload naming one of these
    would be rejected by `is_known_series`.
    """
    from app.domain.series_vocab import SERIES_SLOTS, SLOT_BY_NAME, is_known_series

    assert gone not in SLOT_BY_NAME
    assert not is_known_series(gone)
    assert gone not in {s.name for s in SERIES_SLOTS}


def test_the_slot_vocabulary_has_exactly_one_price_slot():
    """The bracket is derived from ONE series, so a second price slot would have no consumer."""
    from app.domain.series_vocab import SERIES_SLOTS

    assert [s.name for s in SERIES_SLOTS if s.kind == "price"] == ["price_spot"]


def test_the_cost_only_slot_vocabulary_is_gone():
    """D6: `cost_only` / `cost_optional` existed only for the two bracket slots.

    With those removed the flag would be permanently False and the requirement level would have
    no members, so both leave `SlotSpec` rather than lingering as unreachable branches.
    """
    from app.domain.series_vocab import SlotSpec, SERIES_SLOTS

    assert not hasattr(SlotSpec("x", "energy", "optional"), "cost_only")
    assert all(s.requirement != "cost_optional" for s in SERIES_SLOTS)


def test_the_roster_renders_no_row_for_the_removed_bracket_slots(env):
    """The removal reaches the RENDERED page, not just the view-model.

    The roster template is this project's least-covered layer, and a `cost_only` row was
    rendered-but-hidden rather than omitted — so a leftover would have shipped as invisible
    markup that `applySetupGating` could still un-hide. Asserting the served HTML is what pins
    D3; the `◒` marker and its legend clause go with the rows.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    # The roster really rendered, so the absences below are not vacuous.
    assert 'data-slot-row="price_spot"' in html
    for gone in ("price_spot_min", "price_spot_max"):
        assert gone not in html
    assert "Spot price (min)" not in html
    assert "Spot price (max)" not in html
    assert "data-cost-only" not in html
    assert "◒" not in html
    assert "simulate costs (intra-hour price bracketing)" not in html


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


def test_the_retired_csv_key_renders_nowhere_on_this_screen(env):
    """`data_source_csv` was retired when the CSV-import work built the "Upload CSV" source.

    This screen is where it matters: the disabled stub that used to carry the key lived in this
    panel's source drawer, so a leftover would be here and nowhere else. Asserting only
    `key not in FEATURE_KEYS` in the features tests would not catch that — a live `[?]` beside a
    shipped control sends the user to an issue form for something they can already use.

    The CSV feature's own markup must still be here, so the absence below is about the pending
    affordance rather than about the feature having gone missing. What is checked is the binding
    controls, not the source radio: `ha_fetch.js` builds the radio list at runtime from the
    per-slot source vocabulary, so no `value="csv_upload"` is in the served HTML.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text
    assert 'id="drawer-csv-binding"' in html, "the CSV binding controls are missing"
    assert "data_source_csv" not in html
    assert 'data-feature-key="data_source_csv"' not in html
    from app import features
    assert "data_source_csv" not in features.FEATURE_KEYS
    assert features.title_for("data_source_csv") == "Upload CSV"


def test_an_empty_workspace_claims_no_entity_bindings(env):
    """The empty state must not hand the drawer the SAMPLE's entity mappings.

    `_data_page` seeds its context from `sample_view()`, and the sample depicts a FILLED screen:
    its mapping rows carry `source: "home_assistant"` and ids like
    `sensor.electricity_meter_import_t1`. Left in place on a workspace with no dataset, those reach
    the roster as `data-slot-source` / `data-slot-stat-id`, and `ha_fetch.js` believes them — it
    seeds `draft.statId` from the attribute, which suppresses the entity guess and leaves the
    picker showing an id that exists on no real Home Assistant. That was the reported bug: a
    successful "Test connection" followed by an empty entity select.

    The rows themselves must survive (the roster still renders every slot's role, marker and
    sources), so this asserts the provenance is gone rather than the roster.
    """
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data").text

    assert 'data-slot="grid_import_t1"' in html, "the roster must still render its slots"
    assert re.search(r'data-slot-stat-id="[^"]+"', html) is None, (
        "an empty workspace must claim no statistic id for any slot"
    )
    assert re.search(r'data-slot-source="[^"]+"', html) is None, (
        "an empty workspace must claim no committed source for any slot"
    )
    # The specific ids the sample ships, named so a future sample rename cannot quietly re-leak.
    for sample_id in (
        "sensor.electricity_meter_import_t1",
        "sensor.electricity_meter_export_t1",
        "sensor.solar_total_production",
    ):
        assert sample_id not in html, f"sample entity {sample_id} leaked into an empty workspace"


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
        [_price("price_spot", 0.10)], _WIN, "test", [], None, workspace_id="w1"
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
    """§2′.8: `[ Save ]` persists and returns to the list; `[ Next → ]` persists and advances.

    The dataset and the two "no" answers are what make the wizard half REACHABLE: phase 5's gate
    refuses the advance until the house load is reconstructable, so without them this asserts the
    gate rather than the advance. `_seed_dataset` supplies grid import and export T1; declaring no
    PV and no battery is what makes those two the whole requirement.
    """
    client, mod = env
    _seed(mod)
    _seed_dataset(mod)

    resp = client.post(
        "/w/w1/data", data={"setup_haspv": "0", "setup_hasbattery": "0"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    resp = client.post(
        "/w/w1/data?mode=wizard", data={"setup_haspv": "0", "setup_hasbattery": "0"},
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
    mod["workspaces"].create("Second", workspace_id="w2", owner_id=mod["workspaces"].OWNER_ID)
    # w2 was touched last, so it leads.
    assert [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)] == ["w2", "w1"]

    client.post(
        "/w/w1/data", data={"setup_haspv": "0", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    assert [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)] == ["w1", "w2"]


def test_a_save_that_stored_nothing_does_not_advance_updated_at(env):
    """A body carrying neither radio writes nothing, so it is not a "last saved" event.

    `_write_setup_answers` returns early when both answers are None. Touching anyway would move the
    workspace to the top of the list with its badge advanced for a save that wrote nothing — which
    is what the route did until review, while its comment claimed the opposite. Only reachable by a
    hand-made POST, since a rendered form always submits both radios.
    """
    client, mod = env
    _seed(mod)
    mod["workspaces"].create("Second", workspace_id="w2", owner_id=mod["workspaces"].OWNER_ID)
    assert [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)] == ["w2", "w1"]

    r = client.post("/w/w1/data", data={}, follow_redirects=False)
    assert r.status_code == 303
    assert [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)] == ["w2", "w1"]


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
    before = mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)[0].updated_at

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

    assert mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)[0].updated_at == before


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


# ── §2′.8's step-2 gate: `[ Next → ]` is Blocked until the house load is reconstructable ───────
#
# The condition is `data_screen_view.load_gate` and it is checked twice on purpose: once to draw
# the button, once inside the POST. Both halves are driven here, and each missing-series case is
# its own test rather than a parametrised sweep, because they fail for different reasons — the
# has_pv / has_battery cases are about a role being CONDITIONALLY required, and getting one of
# those backwards would leave a user permanently blocked by a series they were never asked for.
#
# The most likely thing here to regress is T2. §2′.8's parenthetical reads as if it required all
# four registers; the code requires T1 only (D2), a single-tariff household has no T2 at all, and
# the T2 tests below are what stop a well-meaning "the spec says both" edit from locking those
# users out.


def _blocked_reason(html: str) -> str:
    """The Blocked button's adjacent reason. Fails if there is none.

    Scoped to `data-next-blocked-reason` rather than searched for as prose, for this file's usual
    reason: the page carries ~200 lines of script and comments, and phase 3 shipped two tests that
    passed against a comment.
    """
    m = re.search(
        r"<span[^>]*data-next-blocked-reason>(.*?)</span>", html, re.S
    )
    assert m is not None, "no Blocked reason beside [ Next → ]"
    return m.group(1)


def _is_blocked(html: str) -> bool:
    """Whether the footer drew the Blocked `[ Next → ]`, by its wrapper's marker attribute."""
    return "data-next-blocked" in _footer(html)


def _next_button(html: str) -> str:
    """The `[ Next → ]` submit button's tag, so its attributes can be asserted on it specifically.

    It must never carry `disabled`, in either branch — see
    `test_the_blocked_next_button_is_still_clickable` for why that is the point rather than an
    omission.
    """
    footer = _footer(html)
    m = re.search(r"<button[^>]*>\s*Next[^<]*</button>", footer, re.S)
    assert m is not None, f"no [ Next → ] button in the footer: {footer}"
    return m.group(0)


def _full_dataset(mod, workspace_id: str = "w1", extra=()) -> None:
    """Import + export T1, plus whatever `extra` series the case under test needs."""
    frames = [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.5)]
    frames += [_energy(name, 0.5) for name in extra]
    mod["dataset"].save_dataset(frames, _WIN, "test", [], None, workspace_id=workspace_id)


def _answers(mod, *, has_pv: bool, has_battery: bool, workspace_id: str = "w1") -> None:
    cfg = mod["simconfig_store"].load(workspace_id)
    cfg.has_pv = has_pv
    cfg.has_battery = has_battery
    _store(mod, cfg, workspace_id)


def test_the_gate_is_met_with_import_and_export_and_no_pv_or_battery(env):
    """The minimum §6.3 needs from a household with neither an array nor a battery.

    Two series, and `[ Next → ]` is live: no `data-next-blocked` wrapper, no `disabled`, no reason.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    _full_dataset(mod)

    html = client.get("/w/w1/data?mode=wizard").text
    assert not _is_blocked(html)
    assert "disabled" not in _next_button(html)


def test_no_dataset_at_all_blocks_and_names_every_applicable_series(env):
    """The empty state. Nothing loaded is not "some of it is missing" — all of it is.

    The message names each applicable slot rather than saying "load data first", per §2′.8: the
    roster that would fix it is directly above, so the sentence and the table are read together.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=True)

    html = client.get("/w/w1/data?mode=wizard").text
    assert _is_blocked(html)
    reason = _blocked_reason(html)
    for label in (
        "Grid import T1", "Grid export T1", "Solar production",
        "Battery charge", "Battery discharge",
    ):
        assert label in reason, f"{label} not named in {reason!r}"


def test_the_blocked_next_button_is_still_clickable(env):
    """Review finding R1: a `disabled` `[ Next → ]` here was a trap with no in-page exit.

    That button is the ONLY submitter of `#data-form`, and the `has_pv` / `has_battery` radios live
    inside that form. On the commonest first run — appendix A defaults `has_pv` on, the household
    has no array, the fetch produces import + export alone — step 2 renders blocked on the solar
    series. The user answers "no, I have no solar", `applySetupGating` hides the solar roster row,
    and a disabled button refuses to submit the very answer that clears the block. `[ Fetch
    history ]` is disabled too with nothing staged, and `[ ← Previous ]` is a plain link that
    discards the answer, so the round trip returns to the identical trap.

    So the block is stated, not enforced, in the rendering: no `disabled` and no `.blocked-control`
    dim (a dimmed-but-clickable control contradicts §2.1's meaning of the dim). The reason beside
    it is what carries the Blocked state, and `POST /w/{id}/data` is the enforcement — it persists
    the answers first, then re-renders step 2, which is exactly what springs the trap.

    The browser-level counterpart is `test_the_wizard_escapes_the_blocked_step_by_answering_no`
    in `tests/test_smoke.py`; this one pins the markup that makes it possible.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=True)   # nothing loaded: every slot is missing

    html = client.get("/w/w1/data?mode=wizard").text
    assert _is_blocked(html), "the precondition: this case must be the blocked branch"
    assert "disabled" not in _next_button(html)
    # And the dim is gone with it, so the affordance does not say "unusable" while being usable.
    assert "blocked-control" not in _footer(html)
    # The reason still has to be there — §2.1 requires the block to remain explained.
    assert "Solar production" in _blocked_reason(html)


def test_a_missing_grid_import_blocks_and_names_it(env):
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    mod["dataset"].save_dataset(
        [_energy("grid_export_t1", 0.5)], _WIN, "test", [], None, workspace_id="w1"
    )

    html = client.get("/w/w1/data?mode=wizard").text
    assert _is_blocked(html)
    reason = _blocked_reason(html)
    assert "Grid import T1" in reason
    assert "Grid export T1" not in reason, "a series that IS loaded must not be named"


def test_a_missing_grid_export_blocks_and_names_it(env):
    """Export as well as import: §6.3 is `imp − exp + …`, so a one-sided meter is not enough."""
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1", 2.0)], _WIN, "test", [], None, workspace_id="w1"
    )

    html = client.get("/w/w1/data?mode=wizard").text
    assert _is_blocked(html)
    reason = _blocked_reason(html)
    assert "Grid export T1" in reason
    assert "Grid import T1" not in reason


def test_a_declared_array_with_no_solar_series_blocks(env):
    """§2′.8: without it the reconstruction attributes PV output to a house that is not there.

    That is check 7's negative-load symptom (§7.3), which is why the array's series is required
    rather than merely useful.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    _full_dataset(mod)

    html = client.get("/w/w1/data?mode=wizard").text
    assert _is_blocked(html)
    assert "Solar production" in _blocked_reason(html)


def test_a_declared_array_with_its_solar_series_passes(env):
    """The other direction, so the test above cannot pass by requiring solar unconditionally."""
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    _full_dataset(mod, extra=("solar_production",))

    assert not _is_blocked(client.get("/w/w1/data?mode=wizard").text)


def test_no_declared_array_does_not_require_a_solar_series(env):
    """A household with no array has nothing to attribute, so there is nothing to require.

    Getting this backwards would block every PV-less household forever behind a message naming a
    sensor they do not have.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    _full_dataset(mod)

    html = client.get("/w/w1/data?mode=wizard").text
    assert not _is_blocked(html)


def test_a_declared_battery_needs_both_of_its_series(env):
    """Charge AND discharge — §6.3 subtracts one and adds the other, so one alone is half a term."""
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=True)

    _full_dataset(mod)
    reason = _blocked_reason(client.get("/w/w1/data?mode=wizard").text)
    assert "Battery charge" in reason and "Battery discharge" in reason

    # Only one of the pair: still blocked, and only the absent one is named.
    _full_dataset(mod, extra=("battery_charge",))
    html = client.get("/w/w1/data?mode=wizard").text
    assert _is_blocked(html)
    reason = _blocked_reason(html)
    assert "Battery discharge" in reason
    assert "Battery charge" not in reason

    # Both: live.
    _full_dataset(mod, extra=("battery_charge", "battery_discharge"))
    assert not _is_blocked(client.get("/w/w1/data?mode=wizard").text)


def test_no_declared_battery_does_not_require_the_battery_series(env):
    """The counterpart of the PV case, and the same failure if inverted."""
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    _full_dataset(mod)

    assert not _is_blocked(client.get("/w/w1/data?mode=wizard").text)


def test_an_absent_t2_register_pair_does_NOT_block(env):
    """D2, and the single most likely thing in this phase to regress.

    §2′.8's parenthetical — "both T1/T2 register pairs" — reads as if four registers were required.
    Three places in the code say otherwise and they are right: `series_vocab.SERIES_SLOTS` marks
    both T2 slots "optional", `reconcile._combined` folds the registers so an absent T2 contributes
    zero, and `workspaces._data_facts` gates the card badge on T1 with the note that T1's presence
    answers whether the role is filled. A single-tariff household HAS no T2 meter, so requiring it
    would lock those users out of the wizard behind a message naming a series they cannot supply.

    Asserted twice over: the gate passes, and neither T2 label appears anywhere in the footer.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    _full_dataset(mod)   # T1 only, deliberately

    html = client.get("/w/w1/data?mode=wizard").text
    assert not _is_blocked(html), "T1-only must satisfy the gate"
    footer = _footer(html)
    assert "Grid import T2" not in footer
    assert "Grid export T2" not in footer


def test_a_missing_spot_price_does_NOT_block(env):
    """§2′.8 says so directly: the gate is "a lower bar than a full run".

    The spot price is needed for dispatch, not for load, and step 3 renders the battery-free glance
    from load alone. A workspace can therefore pass this gate and still be unable to simulate —
    which is the results screen's problem to state in context, not the wizard's to pre-empt.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    _full_dataset(mod)
    assert "price_spot" not in {"grid_import_t1", "grid_export_t1"}

    html = client.get("/w/w1/data?mode=wizard").text
    assert not _is_blocked(html)
    assert "Spot price" not in _footer(html)


def test_there_is_no_minimum_duration(env):
    """§2′.8: "the gate is about which series exist, not how long they run".

    Three hours of data advances. §2.4's short-window box already caveats what a brief window
    distorts, so a duration rule here would duplicate that judgement with less context.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1", 2.0, n=3), _energy("grid_export_t1", 0.5, n=3)],
        (datetime(2026, 1, 1, tzinfo=timezone.utc),
         datetime(2026, 1, 1, 3, tzinfo=timezone.utc)),
        "test", [], None, workspace_id="w1",
    )

    assert not _is_blocked(client.get("/w/w1/data?mode=wizard").text)


# ── The gate is a WIZARD gate: the card path is untouched ─────────────────────────────────────


def test_the_card_footer_is_never_blocked(env):
    """§2′.8 blocks the wizard's forward step, not `[ Save ]`.

    `[ Save ]` persists two booleans and returns to the list; greying it because the dataset is
    incomplete would refuse a save that has nothing to do with the dataset — and would leave a user
    who came from a card unable to record "yes, I have solar", which is the very answer that makes
    the roster ask for the series they are missing.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=True)   # nothing loaded: the gate is unmet

    footer = _footer(client.get("/w/w1/data").text)
    assert "data-next-blocked" not in footer
    assert not re.search(r"<button[^>]*disabled", footer)
    assert "Save" in footer

    # And the view-model says so too, not just the template. The rendered assertion above is
    # currently satisfied twice over — the Blocked branch is nested inside the wizard branch — so
    # dropping `and wizard` from the view-model leaves it green. Asserted here so the flag itself
    # carries the rule, and a template that ever drew the block outside the wizard branch could not
    # do so from a card.
    from app.data_screen_view import data_screen_view as build

    cfg = mod["simconfig_store"].load("w1")
    assert build(cfg, "t", wizard=False, missing_for_load=["grid_import_t1"])["next_blocked"] is False
    assert build(cfg, "t", wizard=True, missing_for_load=["grid_import_t1"])["next_blocked"] is True


def test_a_card_save_still_redirects_to_the_list_with_the_gate_unmet(env):
    """The behavioural half: the card path's POST is not gated either."""
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=True)

    resp = client.post(
        "/w/w1/data", data={"setup_haspv": "1", "setup_hasbattery": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_the_step_indicator_is_absent_outside_the_wizard(env):
    """D4: the indicator says which step of THREE this is, which is meaningless from a card."""
    client, mod = env
    _seed(mod)
    assert "data-wizard-step" not in client.get("/w/w1/data").text


def test_the_step_indicator_says_step_2_of_3_in_the_wizard(env):
    """§2′.8's suggested indicator, taken up (D4). Step 2, because this is the middle screen."""
    client, mod = env
    _seed(mod)
    html = client.get("/w/w1/data?mode=wizard").text
    m = re.search(r"<span[^>]*data-wizard-step>(.*?)</span>", html, re.S)
    assert m is not None, "no step indicator on the wizard's step 2"
    assert "Step 2 of 3" in m.group(1)


# ── The server-side half: `disabled` is a rendering, not a guarantee ──────────────────────────


def test_a_crafted_wizard_post_cannot_walk_past_the_gate(env):
    """D3, and the reason it exists: followup L3 is this project's live example.

    There, a hand-made `POST /w/{id}/params` walks past a `disabled` cost toggle into a state no
    affordance offers. The same shape is available here — the wizard's `[ Next → ]` is a plain form
    submit, and nothing but the attribute stops a request that omits it. So the route re-checks the
    condition and re-renders step 2 instead of redirecting.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    _full_dataset(mod)   # import + export, but the declared array's series is missing

    resp = client.post(
        "/w/w1/data?mode=wizard",
        data={"setup_haspv": "1", "setup_hasbattery": "0", "mode": "wizard"},
        follow_redirects=False,
    )
    assert resp.status_code == 200, "the advance must be refused, not granted"
    assert "location" not in resp.headers
    # It re-rendered STEP 2, in wizard mode, with the block and its reason — not a bare error.
    assert 'id="slot-roster"' in resp.text
    assert _is_blocked(resp.text)
    assert "Solar production" in _blocked_reason(resp.text)


def test_the_refused_advance_still_persisted_the_answers(env):
    """§2′.8 makes `[ Next → ]` a save that also advances; refusing the advance is not a rollback.

    A user who flips "yes, I have solar" and is then told the solar series is missing has had their
    answer recorded — which is what makes the roster below the message ask for that series.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    _full_dataset(mod)

    resp = client.post(
        "/w/w1/data?mode=wizard",
        data={"setup_haspv": "1", "setup_hasbattery": "0", "mode": "wizard"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert mod["simconfig_store"].load("w1").has_pv is True


def test_the_guard_reads_the_ANSWERS_JUST_SUBMITTED_not_the_stored_ones(env):
    """The ordering the route depends on: persist, then gate.

    Gating on the pre-POST config would let a user who has just declared an array advance past a
    check that still thought they had none — the advance and the answer would disagree, and step 3
    would be computed for a household the config no longer describes.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    _full_dataset(mod)
    # Stored answers alone would pass the gate. The submission is what must decide.
    assert not _is_blocked(client.get("/w/w1/data?mode=wizard").text)

    resp = client.post(
        "/w/w1/data?mode=wizard",
        data={"setup_haspv": "0", "setup_hasbattery": "1", "mode": "wizard"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    reason = _blocked_reason(resp.text)
    assert "Battery charge" in reason and "Battery discharge" in reason


def test_a_wizard_post_with_the_gate_met_advances(env):
    """The positive path through the same guard, so it cannot pass by refusing everything."""
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    _full_dataset(mod, extra=("solar_production",))

    resp = client.post(
        "/w/w1/data?mode=wizard",
        data={"setup_haspv": "1", "setup_hasbattery": "0", "mode": "wizard"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/w/w1/results"


# ── The gate and the card's DataFacts must not disagree (D1) ──────────────────────────────────


@pytest.mark.parametrize(
    "loaded",
    [
        (),
        ("grid_import_t1",),
        ("grid_export_t1",),
        ("grid_import_t1", "grid_export_t1"),
        ("grid_import_t1", "solar_production"),
        ("grid_import_t1", "grid_export_t1", "solar_production"),
        ("grid_import_t1", "grid_export_t1", "grid_import_t2", "grid_export_t2"),
    ],
)
@pytest.mark.parametrize("has_pv", [True, False])
def test_the_gate_and_the_cards_data_facts_agree_on_their_shared_roles(env, loaded, has_pv):
    """D1's cheap guard against two implementations of one predicate drifting apart.

    `workspaces._data_facts` answers the same question from SQLite metadata for the §2′.2 card
    badges; the gate answers it from the loaded frames. Reuse was rejected — `DataFacts` has no
    existing-battery fields and its one consumer does not want them, and it would mean a second
    query for facts the data screen already holds — so the duplication is deliberate and this is
    what stops it drifting. The THREE roles they share are grid import, grid export and PV.

    **What this does NOT cover, having been measured.** Making the gate demand the T2 registers —
    the D2 regression — leaves this test green, because T2 is not one of the three shared roles and
    a missing T2 does not change the answer for any of them. `test_an_absent_t2_register_pair_does
    _NOT_block` is the only thing standing there. Recorded so a future reader does not mistake this
    for wider coverage than it has.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=has_pv, has_battery=False)
    if loaded:
        mod["dataset"].save_dataset(
            [_energy(name, 1.0) for name in loaded], _WIN, "test", [], None, workspace_id="w1"
        )

    from app import data_screen_view

    missing = data_screen_view.load_gate(set(loaded), has_pv=has_pv, has_battery=False)
    facts = [s for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID) if s.id == "w1"][0].data

    # `DataFacts.loaded` false means every other field is meaningless and left at its default
    # (its own docstring), so the comparison is only defined when something is loaded.
    if not facts.loaded:
        assert not loaded
        return

    assert facts.grid_consumption is ("grid_import_t1" not in missing)
    assert facts.grid_production is ("grid_export_t1" not in missing)
    # `pv_production` folds in the applicability the gate expresses by not requiring the role.
    assert facts.pv_production is (has_pv and "solar_production" not in missing)
    assert facts.pv_applicable is has_pv


# ── The card's run size is the results screen's run size (followup I2) ───────────────────────


def _res_energy(name: str, res_s: int, n: int, start: str = "2026-01-01T00:00:00") -> SeriesFrame:
    """An energy series at an ARBITRARY resolution — `_energy` is fixed hourly.

    The I2 cases turn on two energy series at DIFFERENT resolutions covering different spans, so
    they need both knobs. Flat values: nothing here reads them.
    """
    idx = (
        np.arange(n).astype("timedelta64[s]") * res_s + np.datetime64(start)
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "energy", res_s, idx, np.full(n, 1.0), np.zeros(n, dtype=QUALITY_DTYPE)
    )


def _card_facts(mod, workspace_id: str = "w1"):
    return [s for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID) if s.id == workspace_id][0].data


# Each case is (label, frames, requested window). The assertion is the same for all of them and
# is the point of the group: whatever `normalize.grid_report` says the run's grid and interval
# count are, the card says the same. The first two are the shapes that were MEASURED wrong before
# the size was persisted (followup I2); the rest guard the ordinary cases against a fix that
# only works for the pathological ones.
_SIZE_CASES = [
    (
        # I2's own fixture. The stored window is two days, but the three-hour solar series cuts
        # the effective window to three hours — so the run is 3 intervals where dividing the
        # stored window by the resolution said 48.
        "a short auxiliary series narrows the window",
        [
            _res_energy("grid_import_t1", 900, 192),
            _res_energy("solar_production", 3600, 3),
        ],
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc)),
    ),
    (
        # The other measured divergence, and the one I2 named as the cause: an EMPTY energy
        # series carries a coarse `resolution_s` into `max()` but covers nothing, so
        # `choose_grid` drops it and an unfiltered metadata read did not.
        "an empty energy series does not coarsen the grid",
        [
            _res_energy("grid_import_t1", 900, 192),
            _res_energy("solar_production", 3600, 0),
        ],
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc)),
    ),
    (
        "two series at the same resolution over the same span",
        [_res_energy("grid_import_t1", 900, 192), _res_energy("grid_export_t1", 900, 192)],
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc)),
    ),
    (
        "a coarser series that still covers the whole window sets the grid",
        [_res_energy("grid_import_t1", 900, 192), _res_energy("solar_production", 3600, 48)],
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc)),
    ),
]


@pytest.mark.parametrize(
    "frames,window", [c[1:] for c in _SIZE_CASES], ids=[c[0] for c in _SIZE_CASES]
)
def test_the_card_reports_the_same_run_size_as_the_results_screen(env, frames, window):
    """Followup I2: two derivations of "how big is this run" that disagreed.

    The card used to compute the pair from `series_meta` alone — the stored window divided by an
    unfiltered `max(resolution_s)` — because it has metadata and not frames. That is wrong in the
    two ways the first two cases pin. `dataset.save_dataset` now stores what `normalize.grid_facts`
    returns and the card reads it back, so this asserts the two agree rather than asserting a
    hard-coded number: a change to §6.2's grid rule should move both sides together, and a test
    against a literal would then fail for the wrong reason.

    The count is asserted NOT to be the naive derivation as well, on the cases where those differ.
    Without that, an implementation that reverted to dividing the stored window would still pass
    the agreement check on the ordinary cases and this group would be worth much less.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    mod["dataset"].save_dataset(list(frames), window, "test", [], None, workspace_id="w1")

    from app.domain import normalize

    report = normalize.grid_report(list(frames), window)
    facts = _card_facts(mod)

    assert facts.resolution_s == report["grid_s"]
    assert facts.intervals == report["intervals"]


def test_the_interval_count_is_not_the_stored_window_divided_by_the_resolution(env):
    """The specific defect, stated as its own assertion so the fix cannot silently revert.

    On I2's fixture the naive derivation gives 48 and the run is 3. The test above would catch a
    revert too, but only by comparing two numbers that both moved; this names the wrong answer.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    window = (datetime(2026, 1, 1, tzinfo=timezone.utc),
              datetime(2026, 1, 3, tzinfo=timezone.utc))
    mod["dataset"].save_dataset(
        [_res_energy("grid_import_t1", 900, 192), _res_energy("solar_production", 3600, 3)],
        window, "test", [], None, workspace_id="w1",
    )

    facts = _card_facts(mod)
    naive = int((window[1] - window[0]).total_seconds() // facts.resolution_s)
    assert naive == 48, "the fixture no longer reproduces I2's divergence"
    assert facts.intervals == 3, facts.intervals


def test_merging_one_series_updates_the_stored_run_size(env):
    """`upsert_series` holds ONE frame, and the size is a property of the whole dataset.

    A spot price attached to an existing energy dataset (§4.3, the slot-first merge) must not
    leave the row describing the dataset as it was, nor recompute the size from the incoming
    series alone — which for a price series would mean no energy coverage at all. So that path
    reads the siblings back and recomputes over the merged set.

    Driven with an ENERGY series, because a price series does not participate in the grid and
    would leave the size unchanged whether the recompute happened or not — a case that passes for
    both implementations proves nothing.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    window = (datetime(2026, 1, 1, tzinfo=timezone.utc),
              datetime(2026, 1, 3, tzinfo=timezone.utc))
    mod["dataset"].save_dataset(
        [_res_energy("grid_import_t1", 900, 192)], window, "test", [], None, workspace_id="w1"
    )
    before = _card_facts(mod)
    assert before.intervals == 192, before.intervals

    # A three-hour solar series narrows the coverage intersection the count is measured over.
    mod["dataset"].upsert_series(
        _res_energy("solar_production", 3600, 3), "test", window, workspace_id="w1"
    )

    from app.domain import normalize

    merged = [_res_energy("grid_import_t1", 900, 192), _res_energy("solar_production", 3600, 3)]
    report = normalize.grid_report(merged, window)
    after = _card_facts(mod)
    assert after.resolution_s == report["grid_s"]
    assert after.intervals == report["intervals"]
    assert after.intervals != before.intervals, "the merge did not update the stored size"


def test_a_row_written_before_the_columns_existed_falls_back_to_the_old_derivation(env):
    """An existing local DB keeps its card line rather than losing the count (the chosen policy).

    Simulated by NULLing the two columns on a saved dataset, which is exactly the state
    `_migrate`'s `ALTER TABLE` leaves a pre-existing row in. The fallback is the old derivation,
    so it reproduces the old (wrong) 48 — asserted deliberately: the policy is "no regression for
    rows we cannot recompute without reading frames", not "right everywhere". A new load
    overwrites it with the real value, which the first assertion's `before` state pins.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)
    window = (datetime(2026, 1, 1, tzinfo=timezone.utc),
              datetime(2026, 1, 3, tzinfo=timezone.utc))
    mod["dataset"].save_dataset(
        [_res_energy("grid_import_t1", 900, 192), _res_energy("solar_production", 3600, 3)],
        window, "test", [], None, workspace_id="w1",
    )
    assert _card_facts(mod).intervals == 3

    with mod["dataset"].connect() as conn:
        conn.execute("UPDATE datasets SET grid_s = NULL, n_intervals = NULL")

    facts = _card_facts(mod)
    assert facts.resolution_s == 3600, "the fallback should still report a resolution"
    assert facts.intervals == 48, "the fallback is the old derivation, wrong and non-blank"


def test_the_migration_adds_the_columns_to_a_pre_existing_datasets_table(env):
    """`CREATE TABLE IF NOT EXISTS` never alters a table, so the ALTER path has to work.

    `datasets` had no migration list before this change — only `series_meta` did — so this pins
    the half of `_migrate` that is new. The old table is built by hand at the pre-change shape;
    `connect()` must then bring it forward and a save must succeed against it.
    """
    client, mod = env
    from app import db

    with db.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS datasets")
        conn.execute(
            """CREATE TABLE datasets (
                   id            INTEGER PRIMARY KEY AUTOINCREMENT,
                   workspace_id  TEXT    NOT NULL,
                   source_type   TEXT    NOT NULL,
                   window_start  TEXT    NOT NULL,
                   window_end    TEXT    NOT NULL,
                   fetched_at    TEXT    NOT NULL,
                   warnings_json TEXT    NOT NULL DEFAULT '[]'
               )"""
        )

    with mod["dataset"].connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(datasets)").fetchall()}
    assert {"grid_s", "n_intervals"} <= cols, cols

    _seed(mod)
    _answers(mod, has_pv=False, has_battery=False)
    mod["dataset"].save_dataset(
        [_res_energy("grid_import_t1", 900, 192)],
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc)),
        "test", [], None, workspace_id="w1",
    )
    assert _card_facts(mod).intervals == 192


def test_the_blocked_reason_is_dutch_on_a_dutch_page(env):
    """The whole sentence AND the series names, both translated.

    The names are the point: they come from the view-model as English `ROLE_LABEL` msgids and the
    template translates each with `_()`, the same way `_data_roster.html` renders `_(row.role)`.
    Pre-translating them in Python would format them before the request's locale is known, and
    joining them into the sentence in Python would make it a fragment concatenation — this test is
    what would catch either, because in English both mistakes are invisible.
    """
    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=False)

    reason = _blocked_reason(
        client.get("/w/w1/data?mode=wizard", headers={"Cookie": "lang=nl"}).text
    )
    assert "Solar production" not in reason, f"an English role label leaked: {reason!r}"
    assert "to continue" not in reason, f"the English sentence leaked: {reason!r}"
    # The catalog's own Dutch for `solar_production`, read from the compiled translation rather
    # than written out here, so this cannot drift from what the roster shows.
    from app.i18n import env_for

    assert env_for("nl").globals["gettext"]("Solar production") in reason, reason


def test_the_named_series_use_the_same_strings_as_the_roster_rows(env):
    """§2′.8's point: "the user is looking at the roster that would fix it".

    A message that named "PV output" beside a roster row saying "Solar production" would send the
    user looking for a row that is not there. The labels come from the one `ROLE_LABEL` table, and
    this drives both renderings to check they still do.
    """
    from app.data_view import ROLE_LABEL

    client, mod = env
    _seed(mod)
    _answers(mod, has_pv=True, has_battery=True)

    html = client.get("/w/w1/data?mode=wizard").text
    reason = _blocked_reason(html)
    roster = re.search(r'<table.*?</table>', html, re.S)
    assert roster is not None, "no roster table to compare against"

    for role in ("grid_import_t1", "grid_export_t1", "solar_production",
                 "battery_charge", "battery_discharge"):
        label = ROLE_LABEL[role]
        assert label in reason, f"{label} not named in the block reason"
        assert label in roster.group(0), f"{label} is not the roster's word for {role}"


# ── Old .npz files carrying the removed price bracket still load (D7) ────────────────────────


def test_a_price_npz_written_with_the_old_bracket_arrays_still_loads(env, tmp_path):
    """Users have `price_spot.npz` files on disk holding `value_min`/`value_max` arrays.

    `SeriesFrame` carried an intra-interval bracket taken from an HA `measurement` statistic, and
    `_save_frame` wrote it into the same .npz as two extra arrays. Nothing ever read it — the
    §6.16 bracket is derived from the 15-minute values at grid reconciliation — so it was removed.
    The loader must ignore the leftover arrays rather than fail on them, which it does by reading
    only the three keys it names.

    Written the way the OLD code wrote it (np.savez with five arrays into the real per-workspace
    path), then read back through the real `load_latest`, so this exercises the shipped path and
    not a hand-built reimplementation of it.
    """
    client, mod = env
    dataset = mod["dataset"]
    _seed(mod)

    n = 4
    idx = (np.arange(n).astype("timedelta64[s]") * 3600
           + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    price = SeriesFrame("price_spot", "price", 3600, idx,
                        np.array([0.20, 0.25, 0.30, 0.22]), np.zeros(n, dtype=QUALITY_DTYPE))
    energy = _res_energy("grid_import_t1", 3600, n)
    dataset.save_dataset([energy, price], _WIN, "test", [], None, workspace_id="w1")

    # Re-write the price .npz in the pre-removal shape: the three current arrays plus the two
    # bracket arrays the old writer appended.
    path = tmp_path / "w1" / "series" / "price_spot.npz"
    assert path.exists(), sorted((tmp_path / "w1" / "series").iterdir())
    np.savez(
        path,
        index_s=idx.astype("datetime64[s]").astype(np.int64),
        values=price.values,
        quality=price.quality,
        value_min=np.array([0.19, 0.24, 0.28, 0.21]),
        value_max=np.array([0.21, 0.27, 0.33, 0.24]),
    )

    loaded = dataset.load_latest("w1")
    assert loaded is not None
    back = next(f for f in loaded.frames if f.name == "price_spot")
    assert np.allclose(back.values, [0.20, 0.25, 0.30, 0.22])
    assert not hasattr(back, "value_min") and not hasattr(back, "value_max")


def test_a_saved_bracket_slot_series_is_not_restored_after_the_slots_were_removed(env, tmp_path):
    """D3's returning-user case: `price_spot_min`/`price_spot_max` rows already on disk.

    Nothing deletes them, and `_restore_frames` reads `series_meta` BY NAME — so without a
    vocabulary filter they would load into `LoadedDataset.frames` while being invisible in the
    roster, which is built from SERIES_SLOTS. That is not inert: `normalize.grid_report` gives
    every frame its own granularity row and `normalize.price_granularity_lost` counts every
    `kind == "price"` frame, so the user would see a phantom series and a price-granularity
    warning raised on a slot the UI no longer has.

    The row and the .npz are deliberately left on disk; this pins the READ side only.
    """
    client, mod = env
    dataset = mod["dataset"]
    _seed(mod)

    n = 4
    idx = (np.arange(n).astype("timedelta64[s]") * 900
           + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    price = SeriesFrame("price_spot", "price", 3600, idx,
                        np.array([0.20, 0.25, 0.30, 0.22]), np.zeros(n, dtype=QUALITY_DTYPE))
    energy = _res_energy("grid_import_t1", 3600, n)
    dataset.save_dataset([energy, price], _WIN, "test", [], None, workspace_id="w1")

    # Forge the pre-removal state: a 15-minute bracket series with its own row and .npz, exactly
    # as `save_dataset` would have written it when the slot still existed.
    orphan = tmp_path / "w1" / "series" / "price_spot_min.npz"
    np.savez(
        orphan,
        index_s=idx.astype("datetime64[s]").astype(np.int64),
        values=np.array([0.19, 0.24, 0.28, 0.21]),
        quality=np.zeros(n, dtype=QUALITY_DTYPE),
    )
    with dataset.connect() as conn:
        ds_id = conn.execute("SELECT MAX(id) FROM datasets").fetchone()[0]
        conn.execute(
            "INSERT INTO series_meta (dataset_id, workspace_id, name, kind, resolution_s, path,"
            " source_type) VALUES (?, 'w1', 'price_spot_min', 'price', 900, ?, 'home_assistant')",
            (ds_id, str(orphan)),
        )

    loaded = dataset.load_latest("w1")
    assert loaded is not None
    assert "price_spot_min" not in [f.name for f in loaded.frames]
    assert "price_spot_min" not in loaded.series_sources
    # The vocabulary members around it still load, so this is not an empty result.
    assert {"price_spot", "grid_import_t1"} <= {f.name for f in loaded.frames}

    # And the two diagnostics that read `kind == "price"` across all frames no longer see it.
    from app.domain import normalize
    report = normalize.grid_report(loaded.frames, loaded.window)
    assert "price_spot_min" not in [s["name"] for s in report["series"]]
    assert normalize.price_granularity_lost(loaded.frames, 3600) == {
        "lost": False, "native_resolution_s": None
    }

    # The file itself is untouched: declining to load is not deleting the user's data.
    assert orphan.exists()

