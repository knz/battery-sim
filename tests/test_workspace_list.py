"""The workspace list screen and its routes (docs/specs/20-workspaces-ux.md §2′.2, §2′.3).

Phase 2 turned `GET /` into a list of analyses and moved the three-panel page to
`GET /w/{id}/results`. What these tests pin is the part of that a route status code cannot see:
which badges a card draws from a config, which buttons the no-data variant OMITS, what each of
the two deletions leaves behind, and that the list's ordering means anything.

Five groups, each for a property the spec is explicit about and the implementation could plausibly
get wrong:

  * **The badge set.** Connection is `phases × fuse_a` rendered from `GridConfig`, contract is the
    enum VALUE, and the contract badge is shown at FULL STRENGTH whether or not cost simulation is
    on (§2′.2). The last one is the easy mistake — greying or hiding it under `simulate_cost` is
    the intuitive thing to do and the spec forbids it.
  * **The no-data variant.** `[ Results ]` and `[ Delete data ]` must be ABSENT, not disabled —
    §2.1's Inapplicable rule, which is about rendering and so cannot be checked anywhere but here.
  * **Delete data keeps the configuration and drops a fetched slot's source mapping** — the split
    §2′.3 now sets out. The mapping for a fetched slot lives in `series_meta`, which IS the data;
    only a pre-fetch staged choice in `localStorage` survives, and the backend's obligation to
    that is not to reset `source_generation`.
  * **Delete analysis removes everything keyed by the id**, and everything in the database now is
    — `feature_interest`, the one installation-wide table, was removed when feature requests moved
    to GitHub issues. What is asserted here instead is that an old installation's copy is dropped.
  * **A fresh install shows the empty list**, not a phantom workspace (phase 1's followup I7), and
    the list orders by config-save time with `POST /params` as the event that advances it (§2′.10).
  * **The three state-changing routes are same-site only** (`app/csrf.py`, followups B6), and a
    replayed deletion returns to the list rather than dropping the user onto a JSON 404.

The harness is deliberately smaller than `tests/test_results_route.py`'s: most of these assert on
markup or on rows, so a full simulatable dataset is only built where a card genuinely needs one.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame

_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 3, tzinfo=timezone.utc)
_HOURS = 48


def _energy(name: str, per_hour: float = 1.0, step_s: int = 3600) -> SeriesFrame:
    n = int((_WIN_END - _WIN_START).total_seconds() // step_s)
    idx = (
        np.arange(n).astype("timedelta64[s]") * step_s
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "energy", step_s, idx,
        np.full(n, float(per_hour)),
        np.zeros(n, dtype=QUALITY_DTYPE),
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A client over an empty temp data dir, plus the modules that write into it.

    Returns `(client, modules)` so a test can seed exactly what it needs. Nothing is seeded here:
    several of these tests are ABOUT the empty state, and a fixture that created a workspace would
    make that untestable.

    `monkeypatch.setenv` before any import that resolves the data dir, as everywhere else in this
    suite — and note followup I4: `monkeypatch.undo()` inside a test would revert this and
    redirect the rest of it at the developer's real `./data`.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset, db, main, simconfig_store, workspaces

    return TestClient(main.app), {
        "dataset": dataset,
        "db": db,
        "simconfig_store": simconfig_store,
        "workspaces": workspaces,
    }


def _card_html(html: str, workspace_id: str) -> str:
    """Just the one card's markup, so an assertion about card A cannot be satisfied by card B.

    Slices from that card's opening `<article>` to its closing tag. Crude, and deliberately so — a
    real parser would be a dependency for one substring extraction, and the template renders one
    `<article data-workspace-card>` per card with the id on it, containing no nested `<article>`.

    Bounded at `</article>` rather than at the NEXT `<article>`, which is the version that silently
    does the wrong thing: the last card on the page has no next one, so the slice would run to the
    end of the document and pick up the two page-level deletion dialogs — making an assertion that
    a no-data card omits `[ Delete data ]` fail against the dialog it opens.
    """
    anchor = html.find(f'data-workspace-id="{workspace_id}"')
    assert anchor != -1, f"no card for workspace {workspace_id!r} on the list"
    start = html.rfind("<article", 0, anchor)
    end = html.find("</article>", start)
    assert start != -1 and end != -1, "the card markup is not one <article> element"
    return html[start:end]


def _role_row(card: str, label: str) -> str:
    """The one info-box row for `label`, so a claim about the PV line cannot be met by a grid line.

    Each role renders as `<div class="flex items-baseline gap-2">` holding the label span and the
    state span (`_workspace_card.html`). This slices from the label back to that opening `<div>`
    and forward to the row's end.

    It exists because the whole-card version of the assertion is not the assertion it looks like:
    `"not loaded" not in card` passes whenever every OTHER role happens to be loaded, which is what
    the PV fixtures arrange, so the test stayed green independently of what the PV row said.
    """
    anchor = card.find(f">{label}<")
    assert anchor != -1, f"no info-box row labelled {label!r} on the card: {card}"
    start = card.rfind("<div", 0, anchor)
    end = card.find("</div>", card.find("</span>", anchor))
    assert start != -1 and end != -1, "the role row is not one <div> element"
    return card[start:end]


# ── The empty state (followup I7) ─────────────────────────────────────────────────────────────

def test_a_fresh_install_shows_the_empty_list_not_a_phantom_workspace(env):
    """§2′.2: a fresh installation shows the empty list and the invitation to create.

    This is followup I7 closed. Phase 1's lifespan created a `local` row when it was missing,
    because `GET /` was the single-page UI and every control on it 404'd without one. With `/` as
    the list, that row would BE the phantom analysis §2′.2 says must not appear — a card the user
    never made, on the screen whose whole job is to list what they did make.

    Asserted through the real lifespan (`with TestClient(...)`), because that is the only way the
    startup step runs at all; a client built outside a `with` block would pass this trivially.
    """
    client, mod = env
    with client:
        r = client.get("/")
    assert r.status_code == 200
    assert "data-workspace-card" not in r.text
    assert mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID) == []


def test_the_migration_still_adopts_a_genuine_pre_index_installation(env):
    """The other half of I7: `migrate_local()` stays, and must still run on startup.

    Removing the lifespan's `create` must not have removed the ADOPTION with it. A user upgrading
    from a pre-index build has a `local/` directory with a real config in it, and their analysis
    has to appear on the list rather than being replaced by an empty state.
    """
    client, mod = env
    mod["simconfig_store"].save(mod["simconfig_store"].load("local"), "local")

    with client:
        r = client.get("/")
    assert 'data-workspace-id="local"' in r.text


# ── The badges (§2′.2) ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "phases,fuse_a,expected",
    [
        (1, 25.0, "1×25 A"),
        (3, 25.0, "3×25 A"),
        (3, 63.0, "3×63 A"),
        # A whole rating loses its ".0" — the field is a float and "1×25.0 A" would put a decimal
        # on a badge whose job is to be read at a glance.
        (1, 35.0, "1×35 A"),
    ],
)
def test_the_connection_badge_is_built_from_the_config(env, phases, fuse_a, expected):
    """§2′.2: `phases × fuse_a`, derived from `GridConfig` and never typed."""
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    cfg = mod["simconfig_store"].load("w1")
    cfg.grid.phases = phases
    cfg.grid.fuse_a = fuse_a
    mod["simconfig_store"].save(mod["simconfig_store"].clone(cfg), "w1")

    assert expected in _card_html(client.get("/").text, "w1")


@pytest.mark.parametrize("simulate_cost", [True, False])
def test_the_contract_badge_is_the_enum_value_at_full_strength(env, simulate_cost):
    """§2′.2: the enum VALUE verbatim, shown at full strength whether or not cost sim is on.

    The parametrisation is the point. Conditioning this badge on `simulate_cost` is the intuitive
    thing to do — the contract only prices anything when cost simulation is on — and §2′.2 rules
    it out explicitly: the badge reports a fact about the household's contract, which is true
    either way, and consistent badge geometry across cards is worth more than annotating a
    distinction the card has no room to explain.

    "At full strength" is asserted as the absence of the muting classes the app uses elsewhere for
    a de-emphasised control, not merely as the text being present — a greyed badge would still
    contain its own text.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    cfg = mod["simconfig_store"].load("w1")
    cfg.simulate_cost = simulate_cost
    mod["simconfig_store"].save(mod["simconfig_store"].clone(cfg), "w1")

    card = _card_html(client.get("/").text, "w1")
    contract = cfg.pricing.contract
    value = getattr(contract, "value", contract)
    badge = re.search(r'<span class="badge[^"]*">\s*' + re.escape(value) + r'\s*</span>', card)
    assert badge, f"the contract badge for {value!r} is not on the card"
    assert "opacity-" not in badge.group(0)
    assert "text-base-content/" not in badge.group(0)


def test_the_last_saved_badge_is_rendered_in_amsterdam_time(env):
    """§2′.2: `updated_at`, in Europe/Amsterdam — while storage is UTC throughout.

    Pinned with a January instant (CET, UTC+1) and a July one (CEST, UTC+2), because a conversion
    written as a fixed offset passes one and fails the other, and a page that showed UTC would
    pass neither.
    """
    from app import workspace_list_view

    winter = datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc)
    assert workspace_list_view._fmt_instant(winter) == "2026-01-15 11:30"
    assert workspace_list_view._fmt_instant(summer) == "2026-07-15 12:30"


# ── The info box and the no-data variant (§2′.2, §2.1's Inapplicable rule) ───────────────────

def test_a_card_with_data_states_the_three_roles_and_the_coverage(env):
    """§2′.2's info box: the three role facts, the coverage window and the size line."""
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1"), _energy("grid_export_t1"), _energy("solar_production")],
        (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )

    card = _card_html(client.get("/").text, "w1")
    assert "Grid consumption" in card
    assert "Grid production" in card
    assert "Solar production" in card
    # Coverage, in Amsterdam time: the window starts at 00:00 UTC, which is 01:00 CET.
    assert "2026-01-01 01:00 → 2026-01-03 01:00" in card
    # 48 hours at an hourly grid.
    assert "48 intervals" in card and "hourly" in card


def test_pv_reads_not_applicable_rather_than_not_loaded_without_pv(env):
    """§2′.2: with `has_pv` off the PV line says "not applicable", never "not loaded".

    The two are different facts and the card must not report a deliberate configuration as a
    missing input. Asserted as presence-and-absence, because "not applicable" appearing somewhere
    on the card would not by itself prove the PV line stopped saying "not loaded".

    **Both halves are scoped to the PV ROW.** Over the whole card, `"not loaded" not in card`
    passes for a reason that has nothing to do with PV — the fixture loads both grid slots, so no
    row says it. The assertion would have survived a PV line reading "not loaded" as long as the
    grid rows stayed filled, which is the one thing it is supposed to catch.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    cfg = mod["simconfig_store"].load("w1")
    cfg.has_pv = False
    mod["simconfig_store"].save(mod["simconfig_store"].clone(cfg), "w1")
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1"), _energy("grid_export_t1")],
        (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )

    card = _card_html(client.get("/").text, "w1")
    pv_row = _role_row(card, "Solar production")
    assert "not applicable (no PV)" in pv_row
    assert "not loaded" not in pv_row
    # And the grid rows are untouched by the has_pv answer — so the assertion above is about PV
    # rather than about the info box having stopped reporting states at all.
    assert "loaded" in _role_row(card, "Grid consumption")


def test_the_no_data_card_omits_results_and_delete_data(env):
    """§2′.2 + §2.1: the two data-dependent actions are ABSENT, not greyed.

    This is the Inapplicable rule, and the distinction it draws is the reason for the test: a
    `disabled` `[ Results ]` would satisfy any assertion about the user being unable to press it,
    and would still be the wrong rendering — it invites the user to work out how to un-grey a
    control when the line directly above already says there is no data.

    So both halves are asserted: the two buttons are gone entirely (not merely disabled), and the
    three that §2′.2 marks "always" are still there.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)

    card = _card_html(client.get("/").text, "w1")
    assert "No data loaded yet." in card
    # Absent, in both spellings: no link to the results screen and no delete-data control at all.
    assert "/w/w1/results" not in card
    assert "data-delete-data" not in card
    assert "disabled" not in card
    # And the unconditional three are present.
    assert "/w/w1/data" in card
    assert "/w/w1/edit" in card
    assert "data-delete-workspace" in card


def test_a_card_with_data_offers_results_and_delete_data(env):
    """The other side of the branch above, so a card that omitted them ALWAYS would fail."""
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1")], (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )

    card = _card_html(client.get("/").text, "w1")
    assert 'href="/w/w1/results"' in card
    assert "data-delete-data" in card


def test_the_card_actions_are_links_not_fetches(env):
    """The three navigational actions are `<a href>`, per the plan.

    Pinned because the alternative is available and wrong: this repo has a hand-rolled
    `fetch` + `outerHTML` swap layer on the results screen, and reaching for it here would couple the list
    to machinery that exists to keep panel ② and panel ③ on screen together — a problem the list
    does not have — and would break every card action when a script fails to load.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1")], (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )

    card = _card_html(client.get("/").text, "w1")
    for target in ("/w/w1/results", "/w/w1/data", "/w/w1/edit"):
        # The anchor and its href asserted TOGETHER. Asserting `'<a class="btn' in card` inside
        # this loop — which is what it used to do — is loop-invariant: it says only that the card
        # contains at least one anchor somewhere, so markup with one `<a>` and two
        # `<button data-fetch-target>`s passed it unchanged, which is the exact regression the
        # test exists to catch.
        assert re.search(
            rf'<a class="btn[^"]*"\s+href="{re.escape(target)}"', card
        ), f"{target} is not an <a href>: {card}"


# ── Creating (§2′.2's [ + New analysis ]) ────────────────────────────────────────────────────

def test_creating_a_workspace_redirects_into_it(env):
    """`POST /workspaces` creates and 303s into step 1 of §2′.8's wizard.

    Two properties, and both matter. The shape: a POST that writes, then a redirect, so a reload of
    the destination does not create a second workspace. And the destination: `[ + New analysis ]`
    starts the WIZARD, so it is the edit screen in wizard mode — not the results screen, which for
    a workspace created a moment ago is empty and says nothing about what to do next. Phase 5
    changed this; the route documented it as a placeholder until then.

    The mode is asserted because it is what makes the destination the wizard rather than a bare
    edit screen: without it the user lands on step 1 with a `[ Cancel ] [ Save ]` footer and there
    is no wizard at all.
    """
    client, mod = env
    r = client.post("/workspaces", follow_redirects=False)
    assert r.status_code == 303

    location = r.headers["location"]
    assert re.fullmatch(r"/w/[0-9a-f]{32}/edit\?mode=wizard", location), location
    # The row exists and the destination renders, rather than 404ing from `deps.get_workspace`.
    assert len(mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)) == 1
    assert client.get(location).status_code == 200
    # And it really rendered the wizard: step 1's footer, not the card path's.
    assert "Next" in client.get(location).text


def test_each_create_makes_a_separate_workspace(env):
    """Two presses give two cards, not one — the id is generated, not the constant `local`."""
    client, _ = env
    first = client.post("/workspaces", follow_redirects=False).headers["location"]
    second = client.post("/workspaces", follow_redirects=False).headers["location"]
    assert first != second
    assert client.get("/").text.count("data-workspace-card") == 2


# ── Deleting (§2′.3) ─────────────────────────────────────────────────────────────────────────

def test_delete_data_keeps_the_config_and_drops_a_fetched_source_mapping(env):
    """§2′.3: the CONFIGURATION survives; a FETCHED slot's source mapping does not.

    This test used to claim the opposite, and was green while claiming it. Its docstring said the
    per-slot source choices "live in the browser's `localStorage`", so the only thing it checked
    was that the delete left `source_generation` and the config document alone — neither of which
    is where a fetched slot's mapping actually lives.

    It lives in `series_meta`, which IS the data: a fetch stores the source key and the HA
    statistic id beside the series, and the roster renders the slot's source from the dataset on
    reload (`app/static/ha_fetch.js`, branch 1 of "Two things carry a source choice across a
    reload"). So deleting the measurements un-chooses every fetched slot, and the dialog copy now
    says so. Both directions are asserted here — the mapping is present before and gone after —
    because an assertion that it is absent afterwards would also pass if it had never been stored.

    What DOES survive is branch 2, a pre-fetch staged choice in `localStorage`, and the backend's
    one obligation to it is not to reset `source_generation` — the counter the browser reconciles
    a staged mapping against. That is still checked, now as the narrower claim it always was.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    cfg = mod["simconfig_store"].load("w1")
    cfg.battery.usable_capacity_kwh = 17.5
    mod["simconfig_store"].save(mod["simconfig_store"].clone(cfg), "w1")
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1")], (_WIN_START, _WIN_END), "test", [],
        {"grid_import_t1": "home_assistant"}, workspace_id="w1",
    )
    generation = mod["db"].bump_source_generation("w1")

    # Before: the fetched slot's source is recorded server-side, which is the property the old
    # docstring denied existed.
    before = mod["dataset"].load_latest("w1")
    assert before.series_sources == {"grid_import_t1": "home_assistant"}

    r = client.post("/w/w1/data/delete", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    # The dataset is gone, and with it the mapping — `series_meta` holds neither.
    assert mod["dataset"].load_latest("w1") is None
    with mod["dataset"].connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM series_meta WHERE workspace_id = ?", ("w1",)
        ).fetchone()[0] == 0

    # What §2′.3 says is kept, is kept: the configuration document and the workspace row.
    assert mod["simconfig_store"].config_path("w1").exists()
    assert mod["simconfig_store"].load("w1").battery.usable_capacity_kwh == pytest.approx(17.5)
    assert mod["workspaces"].get("w1") is not None
    # And the counter a STAGED (pre-fetch) mapping is reconciled against is untouched.
    assert mod["db"].source_generation("w1") == generation

    # And the card is back in its no-data state rather than gone from the list.
    card = _card_html(client.get("/").text, "w1")
    assert "No data loaded yet." in card


def test_delete_data_does_not_advance_the_last_saved_badge(env):
    """§2′.10: a config SAVE is the one event that advances `updated_at`.

    A deletion is not a save, and bumping here would reorder the list behind a deletion for the
    same reason §2′.10 forbids a data load doing it.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1")], (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )
    before = mod["workspaces"].get("w1")["updated_at"]

    client.post("/w/w1/data/delete")
    assert mod["workspaces"].get("w1")["updated_at"] == before


def test_delete_analysis_removes_everything_keyed_by_the_id(env):
    """§2′.3: the workspace row, every keyed row, and the directory."""
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1")], (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )
    mod["db"].bump_source_generation("w1")
    directory = mod["simconfig_store"].config_path("w1").parent
    assert directory.exists()

    r = client.post("/w/w1/delete", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    assert mod["workspaces"].get("w1") is None
    assert mod["dataset"].load_latest("w1") is None
    assert mod["db"].source_generation("w1") == 0
    assert not directory.exists()
    assert "data-workspace-card" not in client.get("/").text


def test_an_old_feature_interest_table_is_dropped_on_connect(env):
    """The retired counter table is removed from installations that still carry it (app/db.py).

    This test used to assert the opposite property — that `feature_interest` survived the deletion
    of the last workspace, because it was installation-wide (§2′.10). Feature requests are GitHub
    issues now and nothing is recorded locally, so the table has no reader or writer; leaving it
    in the file would state a behaviour the app no longer has.

    Recreated by hand here because a fresh database never has it: what is under test is the
    upgrade path from an installation that predates the change.
    """
    _, mod = env
    db = mod["db"]
    with db.connect() as conn:
        conn.execute(
            """CREATE TABLE feature_interest (
                   feature_key      TEXT    NOT NULL PRIMARY KEY,
                   count            INTEGER NOT NULL DEFAULT 0,
                   last_clicked_at  TEXT    NOT NULL
               )"""
        )
        conn.execute(
            "INSERT INTO feature_interest VALUES ('export_csv', 1, '2026-01-01T00:00:00+00:00')"
        )

    # The next connect is what drops it — the same path any request takes.
    with db.connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "feature_interest" not in names
    # The workspace index in the same file is untouched by the drop.
    assert "workspaces" in names and "workspace_state" in names


@pytest.mark.parametrize("route", ["/w/nope/delete", "/w/nope/data/delete"])
def test_the_deletions_redirect_rather_than_404_an_unknown_workspace(env, route):
    """§2′.3: after confirming, the user stays on the list — including on a REPLAYED deletion.

    This used to assert 404, and 404 is what the user actually saw: a raw
    `{"detail":"no such workspace"}` JSON body, reached by nothing more exotic than a double-click
    on the dialog's submit button (the form has no submit-disable) or Back-then-resubmit. A second
    delete has already achieved the end state it asked for, so the honest answer is the list.

    `GET /w/{id}/results` deliberately keeps its 404 — see the companion assertion below.
    """
    client, _ = env
    r = client.post(route, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_a_replayed_deletion_lands_on_the_list_and_deletes_nothing_else(env):
    """The realistic path to the above: delete, then submit the same form again.

    Two things have to hold, and the second is why this is not just a status-code check: the
    replay must not be treated as a fresh deletion of anything. The other workspace is still here
    afterwards.
    """
    client, mod = env
    mod["workspaces"].create("Gone", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["workspaces"].create("Kept", workspace_id="w2", owner_id=mod["workspaces"].OWNER_ID)

    assert client.post("/w/w1/delete", follow_redirects=False).status_code == 303
    replay = client.post("/w/w1/delete", follow_redirects=False)
    assert replay.status_code == 303
    assert replay.headers["location"] == "/"
    assert [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)] == ["w2"]


def test_an_unknown_workspace_still_404s_where_there_is_no_end_state_to_reach(env):
    """The other side of the softening above: only the DELETIONS redirect.

    `GET /w/{id}/results` on an unknown id is a bad address, not a request whose end state has
    already been achieved, and rendering the list for it would hide a broken link. Pinned so the
    redirect-on-missing behaviour does not spread from `get_optional_workspace` to every route.
    """
    client, _ = env
    assert client.get("/w/nope/results").status_code == 404


@pytest.mark.parametrize("route", ["/w/..%2F..%2Fescaped/delete", "/w/..%2Fescaped/data/delete"])
def test_the_deletions_refuse_a_traversing_id_without_touching_the_filesystem(env, route):
    """A path segment is client input, and `workspaces._workspace_dir` raises `ValueError` on a
    separator-bearing id — which an unguarded route would turn into a 500 with a stack trace.

    These are the two most dangerous routes in the app to get this wrong on, since both DELETE, so
    the edge check is asserted here as well as in `tests/test_workspace_routes.py`.

    **These particular spellings never reach the route at all** — Starlette's router resolves the
    decoded `..` segments and matches nothing, so the 404 comes from the router. That is checked
    here because it is a real part of the defence, but it is not the part that would break: an id
    that DOES reach the route and is still path-unsafe (a bare `..`, a separator the router leaves
    alone) is handled by `deps.get_optional_workspace`, which returns None rather than letting a
    `ValueError` out of `workspaces._workspace_dir` as a 500.

    What matters either way, and what the last assertion pins: nothing is destroyed. The real
    workspace beside the traversing request is untouched.
    """
    client, mod = env
    mod["workspaces"].create("Kept", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)

    assert client.post(route, follow_redirects=False).status_code == 404
    assert mod["workspaces"].get("w1") is not None


@pytest.mark.parametrize("route", ["/w/../delete", "/w/.%2E/data/delete"])
def test_a_path_unsafe_id_that_reaches_the_route_never_reaches_the_filesystem(env, route):
    """The half of the traversal defence that is this app's rather than the router's.

    `workspaces._workspace_dir` raises `ValueError` on a separator-bearing or dot id, which an
    unguarded route turns into a 500 with a stack trace. `deps.get_optional_workspace` applies the
    same syntactic rule the storage layer does and answers None, so the route redirects without
    ever naming a directory. Asserted as "not a 500" rather than as one exact status, because the
    router normalises some of these spellings and not others and which it handles is not this
    app's contract.
    """
    client, mod = env
    mod["workspaces"].create("Kept", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)

    r = client.post(route, follow_redirects=False)
    assert r.status_code < 500, r.text
    assert mod["workspaces"].get("w1") is not None


# ── Ordering and `touch()` (§2′.10, followup I6) ─────────────────────────────────────────────

def test_the_list_is_ordered_most_recently_updated_first(env):
    """§2′.2's ordering, and the event that drives it.

    Two properties in one test because neither means anything alone: the list orders by
    `updated_at`, and `POST /w/{id}/params` — the config save — is what advances it. Phase 1 left
    `touch()` with no caller (followup I6), which would have made every card sort by its creation
    time forever while the query still looked correct.
    """
    client, mod = env
    mod["workspaces"].create("First", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["workspaces"].create("Second", workspace_id="w2", owner_id=mod["workspaces"].OWNER_ID)

    order = [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)]
    assert order == ["w2", "w1"], "a newly created workspace sorts first"

    r = client.post("/w/w1/params", data=_params_form())
    assert r.headers["X-Params-Valid"] == "1"

    assert [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)] == ["w1", "w2"]
    # And the rendered list agrees with the query — a template that iterated in another order
    # would pass the assertion above and still show the wrong screen.
    html = client.get("/").text
    assert html.index('data-workspace-id="w1"') < html.index('data-workspace-id="w2"')


def test_an_invalid_params_submission_does_not_advance_the_badge(env):
    """`updated_at` is the time the configuration was STORED, so a rejected save must not move it.

    §7.3 check 11 (min SoC above max) blocks the save; the panel comes back with the user's values
    and the errors attached, and nothing was written — so the "last saved" badge must still report
    the previous save.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    before = mod["workspaces"].get("w1")["updated_at"]

    r = client.post("/w/w1/params", data=_params_form(**{
        "battery.min_soc_pct": "90", "battery.max_soc_pct": "10",
    }))
    assert r.headers["X-Params-Valid"] == "0"
    assert mod["workspaces"].get("w1")["updated_at"] == before


def test_a_data_load_does_not_reorder_the_list(env):
    """§2′.10, stated as the property it exists to protect.

    `updated_at` is the CONFIG's save time precisely so that fetching history does not move a card
    to the top — a list that reordered itself behind a load would be a surprise every time.
    """
    client, mod = env
    mod["workspaces"].create("First", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    mod["workspaces"].create("Second", workspace_id="w2", owner_id=mod["workspaces"].OWNER_ID)
    order = [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)]

    mod["dataset"].save_dataset(
        [_energy("grid_import_t1")], (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )
    assert [s.id for s in mod["workspaces"].list_summaries(mod["workspaces"].OWNER_ID)] == order


def _params_form(**overrides) -> dict:
    """A minimal VALID panel-② submission (the field set tests/test_params_route.py posts)."""
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


# ── The header (§2′.2) ───────────────────────────────────────────────────────────────────────

def test_the_header_drops_the_workspace_badge_and_the_gear(env):
    """§2′.2: both are removed, from the list AND from the relocated results screen.

    Asserted on both screens because the badge lived on the page, not on the list — a change that
    only built a new header for the new screen would leave the old one intact and pass a
    list-only check.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)

    for html in (client.get("/").text, client.get("/w/w1/results").text):
        assert "workspace: local" not in html
        assert ">⚙<" not in html
        # The two things the header keeps: a way back or a name, and the language toggle.
        assert 'href="/lang/nl"' in html
        assert 'href="/lang/en"' in html

    # What the header CARRIES differs by screen, and phase 4.2 changed the results one. The list
    # is the app's home and names the app; the results screen names the ANALYSIS, as §2′.6's
    # wireframe does and as the edit and configure-data screens already did. Asserted rather than
    # loosened away, because "the header still says something" is not a property.
    assert "Home Battery Simulator" in client.get("/").text
    results = client.get("/w/w1/results").text
    assert ">Test</span>" in results, "the results header must name the analysis"
    assert 'href="/"' in results, "…and carry the back link that is the only way to leave it"


# ── Cross-site protection on the state-changing routes (app/csrf.py, followup B6) ─────────────
#
# The reason these exist: a single `POST /w/local/delete` carrying a foreign `Origin` was accepted
# and destroyed the workspace — its rows, its `simconfig.json` and its whole directory — and
# `local` is the id EVERY migrated pre-index installation has, so no guessing was needed. The fix
# is a same-site header check rather than a token, which keeps the app's no-session/no-secret
# property; the reasoning and the one case it deliberately leaves open are in `app/csrf.py`.

_STATE_CHANGING = ["/workspaces", "/w/w1/delete", "/w/w1/data/delete"]


def _seed_for_csrf(mod):
    """A workspace with a config document and a dataset — something a forged POST could destroy."""
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)
    cfg = mod["simconfig_store"].load("w1")
    cfg.battery.usable_capacity_kwh = 17.5
    mod["simconfig_store"].save(mod["simconfig_store"].clone(cfg), "w1")
    mod["dataset"].save_dataset(
        [_energy("grid_import_t1")], (_WIN_START, _WIN_END), "test", [], None, workspace_id="w1",
    )


@pytest.mark.parametrize("route", _STATE_CHANGING)
def test_a_cross_site_origin_is_rejected_with_403(env, route):
    """The reproduced attack, on each of the three routes."""
    client, mod = env
    _seed_for_csrf(mod)

    r = client.post(
        route, headers={"Origin": "https://evil.example"}, follow_redirects=False
    )
    assert r.status_code == 403


@pytest.mark.parametrize("route", _STATE_CHANGING)
def test_a_cross_site_sec_fetch_site_is_rejected_with_403(env, route):
    """The modern signal, asserted separately: it is trusted ahead of `Origin`.

    Sent with a same-origin `Origin` on purpose. `Sec-Fetch-Site: cross-site` is set by the browser
    and cannot be forged by page script, so it must win — a check that consulted `Origin` first
    would pass this and would be trusting the weaker of the two headers.
    """
    client, mod = env
    _seed_for_csrf(mod)

    r = client.post(
        route,
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_a_rejected_cross_site_delete_destroys_nothing(env):
    """The point of the 403: not the status code, but that the data is still there.

    A check that ran after the deletion, or a dependency declared on the wrong route, would return
    403 over an already-destroyed workspace. So this asserts the workspace row, the config
    document with its own value, and the dataset — each of which the reproduced attack removed.
    """
    client, mod = env
    _seed_for_csrf(mod)

    assert client.post(
        "/w/w1/delete", headers={"Origin": "https://evil.example"}, follow_redirects=False
    ).status_code == 403

    assert mod["workspaces"].get("w1") is not None
    assert mod["simconfig_store"].config_path("w1").exists()
    assert mod["simconfig_store"].load("w1").battery.usable_capacity_kwh == pytest.approx(17.5)
    assert mod["dataset"].load_latest("w1") is not None


def test_a_rejected_cross_site_data_delete_keeps_the_dataset(env):
    """The same, for the other deletion — which destroys measurements rather than the workspace."""
    client, mod = env
    _seed_for_csrf(mod)

    assert client.post(
        "/w/w1/data/delete", headers={"Origin": "https://evil.example"}, follow_redirects=False
    ).status_code == 403
    assert mod["dataset"].load_latest("w1") is not None


def test_a_rejected_cross_site_create_makes_no_workspace(env):
    """`POST /workspaces` is covered too: a forged create is noise on the user's list."""
    client, _ = env
    assert client.post(
        "/workspaces", headers={"Origin": "https://evil.example"}, follow_redirects=False
    ).status_code == 403
    assert client.get("/").text.count("data-workspace-card") == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": "http://testserver"},
        {"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"},
    ],
    ids=["sec-fetch-same-origin", "sec-fetch-none", "origin-only", "both"],
)
def test_the_apps_own_form_post_is_accepted(env, headers):
    """Every header shape a same-origin form POST can arrive with must pass.

    Four shapes, because browsers differ and the check has two branches: modern browsers send
    `Sec-Fetch-Site: same-origin`; a bookmark or typed URL sends `none`; browsers predating
    `Sec-Fetch-*` send `Origin` alone, which is why the fallback exists at all. A check that
    handled only the first would 403 the app's own delete button on an older browser.

    Driven through the real form-post route, so this is the flow the dialog performs.
    `tests/test_smoke.py` asserts the same thing through an actual browser.
    """
    client, mod = env
    _seed_for_csrf(mod)

    r = client.post("/w/w1/data/delete", headers=headers, follow_redirects=False)
    assert r.status_code == 303
    assert mod["dataset"].load_latest("w1") is None


def test_a_request_with_neither_header_is_allowed_and_that_is_the_documented_gap(env):
    """The deliberate hole in the check, pinned so it is a decision rather than a drift.

    No browser issues a cross-origin POST without at least one of the two headers, so this branch
    is not reachable from a browser attack; what reaches it is `curl`, a local script, or a proxy
    that strips headers — the user acting on their own machine. Closing it would need a token,
    which is the option `app/csrf.py`'s decision excluded.

    Asserted rather than left implicit because a future reader tightening this to a reject would
    be making a real product change (every non-browser client breaks), and should have to change a
    test that says so.
    """
    client, mod = env
    _seed_for_csrf(mod)

    r = client.post("/w/w1/data/delete", follow_redirects=False)
    assert r.status_code == 303
    assert mod["dataset"].load_latest("w1") is None


def test_an_opaque_null_origin_is_rejected(env):
    """`Origin: null` is a sandboxed iframe or a `file://` page, never the app's own document."""
    client, mod = env
    _seed_for_csrf(mod)

    assert client.post(
        "/w/w1/delete", headers={"Origin": "null"}, follow_redirects=False
    ).status_code == 403
    assert mod["workspaces"].get("w1") is not None


def test_params_is_deliberately_not_covered(env):
    """The asymmetry `app/csrf.py` and followups B6 record, asserted so it stays deliberate.

    `POST /w/{id}/params` is an idempotent overwrite of one local parameter set with values a
    forging page chooses blind and cannot read back — the threat B6 originally weighed and
    accepted. What changed in phase 2 is irreversible DELETION, which is what the check covers.

    This test exists in the shape it does on purpose: it does not claim the omission is *right*,
    it claims it is *current and known*. If the judgement is revisited, adding the dependency to
    `params` should make a test that names the decision fail, rather than silently changing an
    unstated behaviour.
    """
    client, mod = env
    mod["workspaces"].create("Test", workspace_id="w1", owner_id=mod["workspaces"].OWNER_ID)

    r = client.post(
        "/w/w1/params",
        headers={"Origin": "https://evil.example"},
        data=_params_form(),
    )
    assert r.status_code == 200
