"""Playwright smoke test for the frontend scaffold.

Asserts the page renders and the key visual items of the default variant (has_pv=True,
simulate_cost=False) are present or absent as the wireframes require. This is deliberately
about structure, not exact numbers — the numbers are static sample data and will be replaced
when the domain layer lands.

It also covers the pending affordance (specs/02-ux-wireframes.md §2.1): the pending
controls open the "Not built yet" dialog, the thumbs-up acknowledges in place, and the
counter route (specs/08-architecture.md §5.1) upserts once per key and 404s an unknown key.
The server runs against a throwaway data directory so the counter DB and the generated
config.toml never touch the working tree.

One test here is about the BROWSER's storage rather than the page's markup:
`test_ha_fetch_scopes_its_slot_store_per_workspace` pins that `ha_fetch.js` keys its slot store
per workspace and discards the pre-workspaces global `ha.slots`
(specs/20-workspaces-ux.md §2′.11). It belongs in a real browser because what it checks is what
that module DOES at load, which no source-level assertion can observe.

    uv run pytest tests/test_smoke.py

Requires the CSS built (npm run build:css) and Playwright's Chromium installed.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    # Isolate the counter DB + generated config.toml in a temp dir, not the repo's ./data.
    env = {**os.environ, "BATTERY_SIM_DATA_DIR": str(tmp_path_factory.mktemp("data"))}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=REPO_ROOT,
        env=env,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urlopen(url + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        server.terminate()
        raise RuntimeError("server did not start")
    yield url
    server.terminate()
    server.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    # One Playwright/browser for the whole module — a second sync_playwright() context would
    # collide with the running asyncio loop.
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _workspace_url(base_url) -> str:
    """Create a workspace through the real route and return the URL of its three-panel page.

    `GET /` is the workspace LIST since phase 2, and a throwaway data directory starts with no
    workspaces at all — deliberately (§2′.2's empty state; phase 1's followup I7). So the page
    every structural test below asserts on has to be reached rather than assumed, and the honest
    way to reach it is to create a workspace the way a user does.

    Module-scoped via the fixtures that call it, so the whole file shares ONE workspace: several
    tests here mutate state (the setup-band radios persist, the thumbs-up upserts), and they
    already shared one before phase 2 gave that workspace an id.
    """
    req = Request(base_url + "/workspaces", data=b"", method="POST")
    with urlopen(req) as r:
        # urllib follows the 303, so the final URL is the destination the route redirected to.
        return r.url


def _select_tab(pg, tab: str):
    """Switch §2′.6's "More settings" pane to `tab` the way a user does — by clicking its label.

    The radio itself is deliberately off-screen (`.tab-radio` is `opacity:0; position:absolute`, so
    the tab strip is the `<label>`s), and Playwright refuses to click an invisible control. Going
    through the label is both what the user does and what proves the label/radio pairing works —
    `check(force=True)` on the radio would pass even with the `for=` attribute wrong.
    """
    pg.locator(f'label.tab[data-tab="{tab}"]').click()
    assert pg.locator(f"#params-tab-{tab}").is_checked(), f"clicking the {tab} label did not select it"


def _ws_path(workspace_url: str) -> str:
    """`/w/<id>` from a `…/w/<id>/results` URL, so the sibling screens can be reached from it."""
    return "/w/" + workspace_url.rstrip("/").split("/")[-2]


def _open(browser, base_url, lang, url=None):
    """Open a screen in a pinned language (cookie), with every collapsible expanded.

    The expand loop covers both idioms the app uses, because phase 4.2 changed which one the
    results screen carries: daisyUI `.collapse` sections (the configure-data screen's, and the
    results screen's until 4.2) and `<details data-advanced>` panes (§2′.6's "More settings", and
    §2′.4's advanced panes). A test that could not see inside the pane would pass on a screen whose
    pane never opens.
    """
    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": lang, "url": base_url}])
    pg = context.new_page()
    pg.goto(url or _workspace_url(base_url), wait_until="networkidle")
    for cb in pg.locator("section.collapse > input[type=checkbox]").all():
        cb.check()
    pg.evaluate("document.querySelectorAll('details[data-advanced]').forEach(d => d.open = true)")
    return pg


@pytest.fixture(scope="module")
def workspace_url(base_url):
    """One workspace for the whole module — see `_workspace_url`."""
    return _workspace_url(base_url)


@pytest.fixture(scope="module")
def page(browser, base_url, workspace_url):
    # English is pinned so the structural assertions are stable regardless of the test
    # environment's Accept-Language (the app itself auto-detects for real users).
    return _open(browser, base_url, "en", workspace_url)


@pytest.fixture(scope="module")
def page_nl(browser, base_url, workspace_url):
    return _open(browser, base_url, "nl", workspace_url)


@pytest.fixture(scope="module")
def data_page_en(browser, base_url, workspace_url):
    """The CONFIGURE-DATA screen for the module's workspace, in English.

    Phase 4.2 deleted panel ①, so the roster, the source drawer, the HA modal and the two scope
    radios exist on this screen and nowhere else (§2′.5). The tests that drive them take this
    fixture instead of `page`; the same module-scoped workspace, so they still share state with the
    rest of the file exactly as they did when both halves were one page.
    """
    return _open(browser, base_url, "en", base_url + _ws_path(workspace_url) + "/data")


@pytest.fixture(scope="module")
def data_page_nl(browser, base_url, workspace_url):
    return _open(browser, base_url, "nl", base_url + _ws_path(workspace_url) + "/data")


def test_the_results_screen_shows_the_battery_box_and_the_results_together(page):
    """§2′.6, and the constraint it is emphatic about: ONE screen, scrolling together.

    **This asserted the three stepper panels ("DATA / PARAMETERS / RESULTS") until phase 4.2.**
    §2′.5 moved panel ① to its own screen and §2′.6 replaced the other two with a capacity-first
    battery box above the results block — so the three labels are gone and the property worth
    pinning is the one that replaced them: the capacity input and the results are in the same
    document, both visible without navigating.

    §2′.6 calls this "the equivalent of §3.4's 'reopening panel ① or ② does not collapse panel ③'",
    which §3.4 names the single most important interaction detail in the app.
    """
    body = page.locator("body").inner_text()
    assert "RESULTS" in body
    assert "Usable capacity" in body
    # Both halves on one page, in this order, and both real elements.
    assert page.locator("#panel-params").count() == 1
    assert page.locator("#panel-results").count() == 1
    assert page.locator('input[name="battery.usable_capacity_kwh"]').is_visible()
    assert page.get_by_text("ENERGY SAVINGS").count() >= 1
    # Panel ① and the setup band are NOT here — they are the configure-data screen's (§2′.5).
    assert page.locator("#slot-roster").count() == 0
    assert page.locator("#setup-band").count() == 0
    assert "PARAMETERS" not in body and "DATA" not in body
    # No footer buttons (§2′.6): the screen is left through the back link.
    assert page.locator("[data-footer]").count() == 0
    assert page.get_by_role("button", name="Save").count() == 0
    assert page.get_by_role("link", name="Cancel").count() == 0


def test_energy_section_present(page):
    assert page.get_by_text("ENERGY SAVINGS").count() >= 1
    assert page.get_by_text("GRID IMPORT SAVED").count() >= 1


def test_cost_section_absent(page):
    # simulate_cost is off: the COST SAVINGS section and the Pricing box must not render.
    # Match whole strings (exact=True) so "cost" inside "simulate cost savings" does not
    # count as the COST SAVINGS divider.
    assert page.get_by_text("COST SAVINGS", exact=True).count() == 0
    assert page.get_by_text("MONEY SAVED", exact=True).count() == 0
    assert page.get_by_text("Energy tax", exact=True).count() == 0


def test_solar_row_present(data_page_en, page):
    """has_pv is on: the solar row is on the DATA screen, the PV selector on the RESULTS one.

    The pair used to sit on one page and phase 4.2 split them, so this now spans both screens —
    which is worth keeping as one test: they are two renderings of one answer, and a gate that
    stopped agreeing between them would be exactly the confusion §2′.7 warns about.

    VISIBILITY, not presence, for the row: gated rows are rendered-and-hidden so the radios can
    re-gate them client-side, so a `.count()` assertion would pass even with the row hidden.
    """
    assert data_page_en.locator('.slot-row[data-slot-row="solar_production"]').is_visible()
    # The illustrated selector is inside §2′.6's collapsible pane, on the Installation tab.
    _select_tab(page, "installation")
    assert page.get_by_text("How is your PV connected to the battery?").is_visible()


def test_existing_battery_rows_are_hidden_until_declared(data_page_en):
    # has_battery defaults off, so the two existing-battery slots are gated out of the roster.
    for slot in ("battery_charge", "battery_discharge"):
        assert not data_page_en.locator(f'.slot-row[data-slot-row="{slot}"]').is_visible()


def test_the_setup_toggles_re_gate_the_roster_live(data_page_en):
    """The regression this whole change exists for: the toggles must actually DO something.

    They were previously inert — no form, no handler, no route — so clicking one changed nothing
    and the radio snapped back on the next render. Here the roster must re-gate immediately,
    client-side, with no round-trip (the answers are persisted later, by the fetch button).
    """
    pg = data_page_en
    solar = pg.locator('.slot-row[data-slot-row="solar_production"]')
    charge = pg.locator('.slot-row[data-slot-row="battery_charge"]')

    assert solar.is_visible() and not charge.is_visible()

    # "No" to PV hides the solar row; "Yes" to an existing battery reveals its two slots.
    pg.locator('input[name="setup_haspv"][value="0"]').check()
    pg.locator('input[name="setup_hasbattery"][value="1"]').check()
    assert not solar.is_visible(), "answering No to PV must hide the solar slot"
    assert charge.is_visible(), "declaring a battery must reveal its slots"

    # Toggling back restores both — the answers gate the view, they do not destroy state.
    pg.locator('input[name="setup_haspv"][value="1"]').check()
    pg.locator('input[name="setup_hasbattery"][value="0"]').check()
    assert solar.is_visible()
    assert not charge.is_visible()


def test_slot_info_affordance(data_page_en):
    # The two corroboration slots (Grid power, House load) carry an `info` blurb, so the demo
    # renders an ⓘ button next to each. Clicking one fills and opens the shared #slot-info-dialog.
    #
    # On the CONFIGURE-DATA screen since phase 4.2, which is where the roster lives now (§2′.5).
    #
    # Counted over VISIBLE buttons only. The household box's "Do you already have a battery?" ⓘ
    # uses the same shared affordance, and the two existing-battery slots carry blurbs of their own
    # — but those rows are gated out while has_battery is false (the appendix-A default this demo
    # runs with), so they are rendered-but-hidden and must not be counted here.
    visible_info_btns = data_page_en.locator("#slot-roster .slot-info-btn:visible")
    assert visible_info_btns.count() == 2  # exactly the two visible rows with a blurb
    data_page_en.get_by_role("button", name="About House load").click()
    dialog = data_page_en.locator("#slot-info-dialog")
    assert dialog.get_by_text("House load", exact=True).is_visible()
    assert "reconstructs household load" in dialog.locator("#slot-info-body").inner_text()
    data_page_en.keyboard.press("Escape")


def test_the_info_dialog_paints_when_opened_from_inside_the_collapsed_advanced_pane(browser, base_url):
    """Regression, re-aimed at the collapsible §2′.6 introduced.

    The shared #slot-info-dialog used to live inside panel ①'s `.collapse-content`, which daisyUI
    gives `content-visibility: hidden` when collapsed. `showModal()` then still put the dialog in
    the top layer — blocking every click on the page — but the browser never painted it: no popup,
    frozen page.

    Panel ① is gone, but the shape is not: this screen's "More settings" pane and its three tab
    panels are the collapsibles that could bury the dialog now, and the ⓘ buttons that open it are
    INSIDE them (the contract-types ⓘ, the PV-blocked charge policies). So this drives it from
    there and asserts the dialog is PAINTED, not merely `open`.

    **It also covers a handler that phase 4.2 nearly lost.** The delegated `.slot-info-btn` click
    listener came from `ha_fetch.js`, which this screen stopped loading with the drawer; it is
    inlined in `workspace_results.html` now. Without it the dialog would never open at all, with
    nothing in the markup or the console to say so.
    """
    # Its OWN workspace and context: it turns PV off, which is what puts an ⓘ inside the pane at
    # all (the PV-requiring charge policies render disabled, each with a blurb), and the
    # module-scoped `page` fixture's workspace must not be left in that state.
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()

    # Answer "no PV" on the configure-data screen and save it, so the results screen renders the
    # disabled charge policies with their ⓘ blurbs. Through the real controls, not a config write.
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    pg.locator('input[name="setup_haspv"][value="0"]').check()
    pg.get_by_role("button", name="Save").click()
    pg.wait_for_load_state("networkidle")

    pg.goto(f"{base_url}/w/{workspace_id}/results", wait_until="networkidle")
    pg.evaluate("document.getElementById('params-advanced').open = true")
    _select_tab(pg, "dispatch")
    btn = pg.locator("#panel-params .slot-info-btn").first
    assert btn.count() >= 1, "no ⓘ inside the pane to drive this with"
    btn.scroll_into_view_if_needed()
    # Collapse the pane around the button, then fire the click through the delegated handler.
    pg.evaluate("document.getElementById('params-advanced').open = false")
    pg.evaluate("document.querySelector('#panel-params .slot-info-btn').click()")
    dialog = pg.locator("#slot-info-dialog")
    assert dialog.evaluate("d => d.open") is True, "the delegated ⓘ handler did not fire"
    # The real assertion: painted, not just open.
    assert dialog.is_visible()
    assert dialog.evaluate(
        "d => !d.closest('.collapse-content') && !d.closest('details')"
    ), "the dialog must not live inside a collapsible, or it is hidden when that one is closed"
    # It is FILLED, not an empty shell — the handler copies the button's data-* across.
    assert dialog.locator("#slot-info-title").inner_text().strip() != ""
    assert dialog.locator("#slot-info-body").inner_text().strip() != ""
    context.close()


def test_the_advanced_pane_survives_a_parameter_swap(browser, base_url):
    """§2′.6: the pane "preserves state and does not reset on collapse" — and not on a SWAP either.

    **This was a real defect, found by driving the screen rather than by any assertion on markup.**
    `POST /w/{id}/params` answers with a fresh render of the battery box, whose `<details>` has no
    `open` attribute and whose tab strip has `checked` on Battery — those are the template's
    defaults and the server has no idea what the user had open. Swapping that in verbatim closed
    the pane and reset the tab on every `[ Calculate → ]`, hiding the very field the user had just
    edited. The fix carries the two display bits across the swap (`readPaneState` /
    `applyPaneState` in `workspace_results.html`).

    It belongs in a browser because both halves of it are browser state: `details.open` is a
    property no server render can observe, and the swap only happens under the delegated fetch
    handler. Every non-browser test in the suite was green with the defect present.

    Its own workspace and context, since it persists a parameter.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/results", wait_until="networkidle")

    pg.locator("summary", has_text="More settings").click()
    _select_tab(pg, "dispatch")
    assert pg.evaluate("document.getElementById('params-advanced').open") is True
    band = pg.locator('input[name="policy.band_c"]')
    assert band.is_visible(), "the field under test is not on screen to begin with"

    band.fill("0.33")
    pg.get_by_role("button", name="Calculate").click()
    pg.wait_for_timeout(1500)

    assert pg.evaluate("document.getElementById('params-advanced').open") is True, (
        "the pane closed on the swap, hiding the field the user had just edited"
    )
    assert pg.locator("#params-tab-dispatch").is_checked(), "the tab reset on the swap"
    assert pg.locator('input[name="policy.band_c"]').is_visible()
    # The value really was persisted — otherwise this would be testing a swap that did nothing.
    assert pg.locator('input[name="policy.band_c"]').input_value() == "0.330"

    # A RESULTS-only swap (a period change) must not disturb it either: that fragment is a
    # different element, and a handler that reset the pane on any fetch would fail here.
    pg.locator("[data-period='last_1_week']").click()
    pg.wait_for_timeout(1000)
    assert pg.evaluate("document.getElementById('params-advanced').open") is True
    assert pg.locator("#params-tab-dispatch").is_checked()
    context.close()


def test_a_blocking_error_is_visible_after_a_swap(browser, base_url):
    """A blocking error inside the pane must be READABLE, not merely present in the DOM.

    **The defect this pins shipped past 41 route tests and 37 browser tests.** Those assert that a
    validation message is RENDERED — a substring check on the HTML — which stays true when the
    message is inside a collapsed `<details>` or on one of the two tabs that are not showing, where
    it is `display: none`. What the user saw was "✕ needs attention" and nothing else: no field, no
    message, no red input, while the config went unpersisted and the results below kept showing
    figures computed from a config they had not submitted.

    Two mechanisms had to fail together for that, and both are checked here: the server render must
    force the pane open on the offending tab, and `applyPaneState` must not re-close it while
    restoring the user's pre-submit display state.

    It belongs in a browser for the reason the sibling test above gives — `display: none` and
    `details.open` are browser state. `is_visible()` is the whole point; a substring assertion here
    would reproduce the blind spot rather than close it.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/results", wait_until="networkidle")

    # Put a bad value into a pane field, then CLOSE the pane before submitting — the state the
    # swap handler would otherwise faithfully restore over the error.
    pg.locator("summary", has_text="More settings").click()
    _select_tab(pg, "battery")
    pg.locator('input[name="battery.max_charge_kw"]').fill("-5")
    pg.locator("summary", has_text="More settings").click()
    assert pg.evaluate("document.getElementById('params-advanced').open") is False

    pg.get_by_role("button", name="Calculate").click()
    pg.wait_for_timeout(1500)

    assert pg.evaluate("document.getElementById('params-advanced').open") is True, (
        "the pane stayed closed over a blocking error the user cannot otherwise read"
    )
    alert = pg.locator("[data-hidden-errors]")
    assert alert.is_visible(), "the blocking message is in the DOM but not on screen"
    assert "greater than zero" in alert.inner_text()
    # And the inline message beside the labelled input is reachable too, on the right tab.
    assert pg.locator("#params-tab-battery").is_checked()
    assert pg.locator('input[name="battery.max_charge_kw"]').is_visible()
    context.close()


def test_the_tabbed_pane_shows_one_panel_at_a_time_and_gives_the_svgs_their_width(browser, base_url):
    """§2′.6's reason for tabs, checked in a real browser at a real width.

    Two things no markup assertion can answer, and the plan flagged the second by name:

      * exactly one panel is VISIBLE at a time while all three are in the DOM — the CSS rule is
        what makes the tabs work, and `.tab-panel { display:none }` losing its `:has()` selector
        would show all three stacked with every test still green;
      * the illustrated topology selector, three frames deep (pane → tab → card), still gets the
        width it needs. §2′.6 gave Installation its own tab precisely because "that selector … needs
        width and does not survive being nested that far", so a rendering where the SVGs came out a
        few dozen pixels wide would satisfy the spec's letter and defeat its purpose.

    Its own workspace, set to a 3-phase connection so the battery-phase selector renders too.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()

    # 3-phase through the real control, so the battery-phase selector is offered.
    pg.goto(f"{base_url}/w/{workspace_id}/results", wait_until="networkidle")
    pg.locator("summary", has_text="More settings").click()
    pg.locator('input[name="grid.phases"][value="3"]').check()
    pg.locator('input[name="grid.fuse_a"]').fill("25")
    pg.get_by_role("button", name="Calculate").click()
    pg.wait_for_timeout(1500)

    for tab in ("battery", "installation", "dispatch"):
        _select_tab(pg, tab)
        shown = [t for t in ("battery", "installation", "dispatch")
                 if pg.locator(f'[data-tab-panel="{t}"]').is_visible()]
        assert shown == [tab], f"selecting {tab} shows {shown}"
        # …while all three are still in the DOM, which is what keeps their inputs submittable.
        assert pg.locator("[data-tab-panel]").count() == 3

    _select_tab(pg, "installation")
    cards = pg.locator('[data-tab-panel="installation"] .radio-card')
    assert cards.count() == 5, f"expected 2 PV + 3 phase cards, got {cards.count()}"
    for i in range(cards.count()):
        svg = cards.nth(i).locator("svg").first.bounding_box()
        assert svg["width"] >= 200, f"card {i}'s illustration is only {svg['width']:.0f}px wide"
        assert svg["height"] >= 100, f"card {i}'s illustration is only {svg['height']:.0f}px tall"

    # …and nothing overflows the page sideways at this width.
    assert pg.evaluate("document.body.scrollWidth") <= pg.evaluate("document.body.clientWidth")

    # The active tab is visibly distinguished. The state lives on an off-screen radio, so this is
    # entirely down to the `:has(...:checked)` rules in app.tailwind.css — without them the strip
    # would look inert whichever tab was selected.
    #
    # Asserted on the BORDER and the WEIGHT, not on the colour. daisyUI's own `.tabs-bordered`
    # already tints a checked tab's text, so a colour comparison passes with our rules deleted —
    # which it was, until removing them left this test green. The underline and the bolding are
    # the signals those rules actually contribute.
    _select_tab(pg, "dispatch")
    active = pg.locator('label.tab[data-tab="dispatch"]')
    inactive = pg.locator('label.tab[data-tab="battery"]')

    def style(loc, prop):
        return loc.evaluate("e => getComputedStyle(e)['%s']" % prop)

    assert style(active, "borderBottomColor") != style(inactive, "borderBottomColor"), (
        "the selected tab has no underline distinguishing it from an unselected one"
    )
    # …and the underline is actually painted, not merely a different transparent value.
    assert "rgba(0, 0, 0, 0)" not in style(active, "borderBottomColor"), style(
        active, "borderBottomColor"
    )
    assert float(style(active, "fontWeight")) > float(style(inactive, "fontWeight")), (
        f"{style(active, 'fontWeight')} vs {style(inactive, 'fontWeight')}"
    )
    context.close()


def test_ha_fetch_scopes_its_slot_store_per_workspace(browser, base_url):
    """`ha.slots` is keyed per workspace, and a pre-existing global key is discarded (§2′.11).

    Driven in a real browser rather than asserted on the source, because the behaviour under test
    is what `ha_fetch.js` does to `localStorage` at load — the module reads `data-workspace-id`,
    derives its key from it, and removes the pre-workspaces global one. A source-level check would
    pass on a file that never runs (the module returns early when the roster is absent, and a
    syntax error would be invisible).

    A fresh context AND its own workspace are used so this cannot disturb the module-scoped
    `page` fixture's storage — the scoped key is per workspace, so sharing one would make the two
    write to the same entry.
    """
    url = _workspace_url(base_url)
    # The id is what the scoped localStorage key is built from, so it is read off the URL rather
    # than assumed to be `local` (workspaces get generated ids since phase 2).
    workspace_id = url.rstrip("/").split("/")[-2]
    scoped_key = f"ha.slots.{workspace_id}"
    # The CONFIGURE-DATA screen: `ha_fetch.js` gates itself on `#slot-roster` and phase 4.2 left
    # that roster on exactly one screen (§2′.5), so this is now the only page the module runs on.
    data_url = f"{base_url}/w/{workspace_id}/data"

    context = browser.new_context()
    pg = context.new_page()
    # Seed the pre-workspaces global key, as an upgraded installation's browser would hold it, then
    # load the page so the module runs against it.
    pg.goto(data_url, wait_until="networkidle")
    pg.evaluate("localStorage.setItem('ha.slots', JSON.stringify({gen: 0, slots: {a: 1}}))")
    pg.reload(wait_until="networkidle")

    # The legacy key is gone, and NOT copied into the workspace key: a mapping staged before the
    # upgrade must not come back looking deliberately staged in this workspace.
    assert pg.evaluate("localStorage.getItem('ha.slots')") is None
    assert pg.evaluate(f"localStorage.getItem({scoped_key!r})") is None

    # And a choice made now lands under the SCOPED key. Driven through the drawer, which is the
    # only thing that writes the store. A backend_load source is picked rather than Home Assistant
    # because Confirm gates the HA branch on a tested connection AND a chosen entity, neither of
    # which this page has; a backend source commits as soon as it is selected, and Confirm merely
    # stages it (the load happens on Fetch history, so nothing is contacted here).
    pg.locator("#slot-roster .slot-source-btn[data-slot-sources*='backend_load']").first.click()
    pg.locator("#source-drawer input[name='drawer-source'][value='energy_charts']").check()
    pg.locator("#drawer-confirm").click()

    stored = pg.evaluate(f"localStorage.getItem({scoped_key!r})")
    assert stored is not None, "the drawer wrote nothing under the workspace-scoped key"
    assert "energy_charts" in stored
    # The global key stays gone — the scoped write must not resurrect it.
    assert pg.evaluate("localStorage.getItem('ha.slots')") is None
    context.close()


def test_data_summary_absent_in_empty_state(page, data_page_en):
    # The full-coverage data summary (§2.3a) renders on the configure-data screen below the
    # data-quality box, but only once data has loaded. The smoke server runs against a throwaway
    # data dir with no persisted dataset (the empty state), so it must be absent on BOTH screens —
    # the data screen gates it on `has_dataset`, and the results screen renders only the
    # range-clamped copy, which needs a simulatable window it does not have either.
    assert page.get_by_text("Your data at a glance", exact=True).count() == 0
    assert data_page_en.get_by_text("Your data at a glance", exact=True).count() == 0


def test_pending_dialog_opens(page):
    page.get_by_role("button", name="Export CSV").click()
    assert page.get_by_text("Not built yet").first.is_visible()
    page.keyboard.press("Escape")


def test_new_pending_controls_marked(page, data_page_en):
    # "Upload CSV" is a pending source radio that lives inside the source-picker drawer
    # (moved there when panel ① went slot-first, 0594e34); open a slot's drawer to reveal it.
    # ha_fetch.js renders it as name="drawer-source", disabled, with feature key data_source_csv.
    # On the configure-data screen since phase 4.2 — that is where the drawer is now (§2′.5).
    data_page_en.locator(".slot-source-btn").first.click()
    assert data_page_en.locator("input[name=drawer-source][disabled]").count() >= 1
    data_page_en.keyboard.press("Escape")  # discards and closes, leaving no committed state

    # "Simulate cost savings?" is NOT a pending control and never becomes one: the cost path is
    # built, the radios POST, and the key is retired in app/features.py.
    assert page.locator("[data-feature-key=simulate_cost]").count() == 0
    # It IS disabled here, and the distinction matters. §2′.6 makes it **Blocked** — a real control
    # whose precondition (`pricing_configured`) is unmet — not Pending, which means "specified but
    # not built" and offers a [?] to register interest. This throwaway server has no contract
    # configured, so Blocked is the expected state, and the two are told apart by what sits beside
    # the control: an ⓘ that says how to clear the precondition, never a [?].
    toggle = page.locator("input[name='setup.simulate_cost']")
    assert toggle.count() == 2
    assert page.locator("input[name='setup.simulate_cost'][disabled]").count() == 2
    assert page.locator("#cost-blocked-info").count() == 1
    assert page.locator("#setup-simulate-cost [data-pending-name]").count() == 0

    # The two unbuilt chart tabs are still pending, and are on the page unconditionally.
    assert page.locator("[data-feature-key=chart_soc_price]").count() >= 1
    assert page.locator("[data-feature-key=chart_energy_flows]").count() >= 1


def test_thumbsup_acknowledges_in_place(page):
    # Clicking the thumbs-up flips the button to "✓ Noted" and shows the thanks line, without
    # reporting any failure. Uses panel ③'s "Export CSV" button: it is present unconditionally
    # (unlike the Pricing box's pending contract radios, which only exist once cost simulation is
    # on) and results export genuinely is still unbuilt. This test used the setup band's
    # "Simulate cost savings" control until the cost path was wired, and the Allow-export checkbox
    # before that; both are real settings now and carry no pending affordance.
    # Scoped to `button[...]`: #pending-dialog itself carries data-feature-key (the script parks
    # the clicked control's key there), so a bare attribute selector matches two elements once any
    # earlier test has opened the dialog.
    page.locator("button[data-feature-key=export_csv]").click()
    dialog = page.locator("#pending-dialog")
    assert dialog.get_by_role("heading", name="Not built yet").is_visible()
    dialog.get_by_role("button", name="I want this").click()
    assert dialog.get_by_text("✓ Noted").is_visible()
    assert dialog.get_by_text("Thanks. We have recorded that you want this.").is_visible()
    page.keyboard.press("Escape")


# ── Feature-interest counter route (specs/08-architecture.md §5.1) ─────────────


def _post(url: str) -> int:
    """POST with no body; return the HTTP status (treating a 4xx as its code, not an error)."""
    import urllib.error

    try:
        with urlopen(Request(url, method="POST"), timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def test_feature_interest_known_key(base_url):
    # A known key returns 204 (success), and a repeat click is still 204 (idempotent upsert).
    assert _post(base_url + "/feature-interest/export_csv") == 204
    assert _post(base_url + "/feature-interest/export_csv") == 204


def test_feature_interest_unknown_key(base_url):
    # A key outside the closed vocabulary is rejected.
    assert _post(base_url + "/feature-interest/definitely_not_a_key") == 404


def test_chart_rendered(page):
    # Plotly draws an <svg> into the chart container.
    assert page.locator("#monthly-chart svg").count() >= 1


# ── Bilingual ────────────────────────────────────────────────────────────────

def test_dutch_renders(page_nl, data_page_nl):
    # Known Dutch translations appear when the lang cookie is 'nl'.
    body = page_nl.locator("body").inner_text()
    assert "ENERGIEBESPARING" in body          # ENERGY SAVINGS
    assert "BESPAARDE NETAFNAME" in body        # GRID IMPORT SAVED
    # §2′.6's own strings, so this covers the phase-4.2 msgids and not only inherited ones.
    assert "Meer instellingen" in body         # More settings
    assert "Laden & ontladen" in body          # Charge & discharge
    assert "Kostenbesparing simuleren?" in body or "Simuleer kostenbesparing?" in body
    # And the English headlines are gone from the results.
    assert page_nl.get_by_text("GRID IMPORT SAVED", exact=True).count() == 0
    assert page_nl.get_by_text("More settings", exact=True).count() == 0

    # "Datakwaliteit" is the configure-data screen's since phase 4.2 (§2′.5), and it needs a
    # dataset — this throwaway server has none, so the ROSTER's Dutch chrome is what is asserted
    # instead. Kept in this test rather than dropped: the point is that both screens translate.
    data_body = data_page_nl.locator("body").inner_text()
    assert "Gegevens instellen" in data_body or "Data instellen" in data_body \
        or "Over je huishouden" in data_body, data_body[:400]


def test_language_toggle_present(page):
    # Both language options render as links to the /lang/ route.
    assert page.locator("a[href='/lang/en']").count() == 1
    assert page.locator("a[href='/lang/nl']").count() == 1


def test_lang_route_sets_cookie(base_url):
    # GET /lang/nl sets the cookie and 303-redirects.
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(base_url + "/lang/nl")
        code, cookie = None, ""
    except urllib.error.HTTPError as e:
        code = e.code
        cookie = e.headers.get("set-cookie", "")
    assert code == 303
    assert "lang=nl" in cookie


def test_the_cost_tint_actually_renders_and_is_not_merely_a_class_name(page, base_url):
    """The cost tint has to survive daisyUI's cascade, which class assertions cannot tell you.

    Asserted in a real browser on COMPUTED colour, because the first version of this feature
    passed every class-name test while rendering nothing: `.cost-field` and `.cost-label` were
    written into `@layer components`, daisyUI sets `.input`'s border and `.stat-title`'s color in
    a LATER layer, and a later layer wins over an earlier one however specific the earlier
    selector is. The cost inputs drew a border byte-identical to every other input's and the
    MONEY SAVED tile kept the default colour. Nothing in the HTML looked wrong.

    So this pins the OUTCOME, not the markup: a tinted element must differ from its untinted
    peer. It deliberately does not assert a specific colour value — the token is a design choice
    and may change, while "the tint is visible" is the requirement.
    """
    # The smoke fixture runs on an isolated empty data dir, so `simulate_cost` is at its
    # appendix-A default of false and no cost control exists yet. Turn it on through the real
    # controls, not by writing a config file, so this exercises the path a user takes to reach
    # these fields at all — and since phase 4.2 that path has TWO steps, which is the whole point
    # of §2′.6's Blocked state:
    #
    #   1. the toggle starts Blocked (no contract configured), so it cannot be clicked;
    #   2. saving the edit screen sets `pricing_configured`, and only then is it live.
    #
    # Driving both is what proves the precondition is real rather than decorative. The first
    # assertion would fail against a toggle that was merely styled grey.
    blocked_yes = page.locator("#setup-simulate-cost input[value='yes']")
    assert blocked_yes.is_disabled(), "the cost toggle must be Blocked without a contract"
    # The ⓘ beside it opens the dialog that says how to clear the precondition (§2′.6).
    page.locator("#cost-blocked-info").click()
    dialog = page.locator("#cost-blocked-dialog")
    assert dialog.is_visible()
    assert dialog.get_by_role("link", name="Set up my contract").is_visible()
    page.keyboard.press("Escape")

    # Clear the precondition through the real route: `[ Save ]` on the edit screen is the one write
    # that sets the flag (§2′.6).
    workspace_id = page.url.rstrip("/").split("/")[-2]
    page.goto(f"{base_url}/w/{workspace_id}/edit", wait_until="networkidle")
    page.get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")
    page.goto(f"{base_url}/w/{workspace_id}/results", wait_until="networkidle")

    # Now it is live, and turning it on draws the Pricing box.
    yes = page.locator("#setup-simulate-cost input[value='yes']")
    assert not yes.is_disabled(), "saving the contract must unblock the toggle"
    yes.check()
    # The POST swaps the box in with the pane closed, so re-open before measuring — a computed
    # style on a `display:none` subtree is not what the reader sees.
    page.wait_for_selector("input.cost-field", state="attached", timeout=10000)
    page.evaluate("document.querySelectorAll('details[data-advanced]').forEach(d => d.open = true)")
    _select_tab(page, "dispatch")
    page.wait_for_selector("input.cost-field", timeout=10000)

    tinted_input = page.locator("input.cost-field").first
    plain_input = page.locator("input[name='battery.usable_capacity_kwh']").first
    tinted_border = tinted_input.evaluate("e => getComputedStyle(e).borderColor")
    plain_border = plain_input.evaluate("e => getComputedStyle(e).borderColor")
    assert tinted_border != plain_border, (
        f"cost input border {tinted_border} is identical to an untinted input's — the rule is "
        "being overridden, most likely by a later CSS layer"
    )

    # A tinted heading must differ from an untinted one, and an untinted one must NOT pick the
    # tint up — otherwise the marking distinguishes nothing. The MONEY SAVED tile needs a
    # simulated dataset, which this fixture has no data for; the Pricing box's heading is on
    # screen and exercises the same rule against the same override risk.
    plain_h3 = page.locator("h3.text-base-content\\/70").first
    cost_h3 = page.locator("h3.cost-label").first
    assert cost_h3.evaluate("e => getComputedStyle(e).color") != plain_h3.evaluate(
        "e => getComputedStyle(e).color"
    ), "a cost heading renders the same colour as a plain one"


# ── The workspace list (specs/20-workspaces-ux.md §2′.2, §2′.3) ──────────────────────────────
#
# Phase 2's new screen, driven in a real browser rather than only through route tests. The reason
# is the one the previous two phases both learned the hard way: a route test seeds its own
# preconditions and asserts on markup, so it can be green about a screen that never renders — the
# fresh-install defect phase 1 shipped was invisible to 823 passing non-browser tests and surfaced
# only from the one test that drove a genuinely empty installation in a browser.
#
# These use their OWN browser context and their own workspaces, so they cannot disturb the
# module-scoped `page` fixture (which shares one workspace across the file).


def _list_page(browser, base_url):
    """A fresh English context on the workspace list at `/`."""
    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(base_url + "/", wait_until="networkidle")
    return context, pg


def test_the_list_creates_a_workspace_and_navigates_into_it(browser, base_url):
    """`[ + New analysis ]` is a real form POST that lands on the new workspace's page.

    Driven end to end because the button, the route, the redirect and the destination are four
    separate things and a route test only sees the middle two.
    """
    context, pg = _list_page(browser, base_url)
    before = pg.locator("[data-workspace-card]").count()

    pg.get_by_role("button", name="+ New analysis").first.click()
    pg.wait_for_load_state("networkidle")

    import re as _re

    assert _re.search(r"/w/[0-9a-f]{32}/results$", pg.url), pg.url
    # The results screen, not an error document. "PARAMETERS" until phase 4.2, which replaced
    # panel ② with §2′.6's capacity-first battery box — so the marker is the box's own field.
    body = pg.locator("body").inner_text()
    assert "Usable capacity" in body and "RESULTS" in body, body[:300]

    pg.goto(base_url + "/", wait_until="networkidle")
    assert pg.locator("[data-workspace-card]").count() == before + 1
    context.close()


def test_a_new_card_shows_the_no_data_variant(browser, base_url):
    """§2′.2's third card: the invitation, and `[ Results ]` / `[ Delete data ]` ABSENT.

    In a browser rather than only in markup because the Inapplicable rule is about what the user
    can SEE — a control rendered but hidden, or rendered disabled, would satisfy a naive markup
    check and be the wrong rendering. `is_visible()` is the assertion the rule actually makes.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    context, pg = _list_page(browser, base_url)

    card = pg.locator(f'[data-workspace-card][data-workspace-id="{workspace_id}"]')
    assert card.get_by_text("No data loaded yet.").is_visible()
    assert card.locator('a[href$="/results"]').count() == 0
    assert card.locator("[data-delete-data]").count() == 0
    # The three §2′.2 marks "always" are there and clickable.
    assert card.locator(f'a[href="/w/{workspace_id}/data"]').is_visible()
    assert card.locator(f'a[href="/w/{workspace_id}/edit"]').is_visible()
    assert card.locator("[data-delete-workspace]").is_visible()
    context.close()


def test_the_delete_dialog_names_the_workspace_and_deletes_it(browser, base_url):
    """§2′.3: the modal opens, quotes the title, and confirming returns to the re-rendered list.

    The title-quoting is the part that needs a browser: one dialog serves every card, and the
    title is written into it by script from the clicked card's `data-*`. A server-side test cannot
    see that happen, and getting it wrong would show the wrong household's name above a
    destructive button — which is exactly the confusion §2′.3 requires the quoting to prevent.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    context, pg = _list_page(browser, base_url)

    card = pg.locator(f'[data-workspace-card][data-workspace-id="{workspace_id}"]')
    title = card.locator("h3").inner_text().strip()
    card.locator("[data-delete-workspace]").click()

    dialog = pg.locator("#delete-workspace-dialog")
    assert dialog.is_visible()
    body = dialog.inner_text()
    assert f'"{title}"' in body, f"the dialog does not quote the workspace title: {body!r}"
    assert "This cannot be undone." in body

    # Cancel leaves the workspace alone — the safe path has to work, or the dialog is a trap.
    dialog.get_by_role("button", name="Cancel").first.click()
    pg.wait_for_timeout(100)
    assert card.count() == 1

    # Confirming deletes and returns to the list, where the card is gone.
    card.locator("[data-delete-workspace]").click()
    dialog.get_by_role("button", name="Delete analysis").click()
    pg.wait_for_load_state("networkidle")
    assert pg.url.rstrip("/") == base_url.rstrip("/")
    assert pg.locator(f'[data-workspace-card][data-workspace-id="{workspace_id}"]').count() == 0
    context.close()


def test_a_title_with_dollar_sequences_is_quoted_literally_in_the_dialog(browser, base_url):
    """A `$&` in the title must reach the dialog unchanged (phase-2 review, minor 6).

    `String.replace` gives its REPLACEMENT argument an escape syntax — `$&` re-inserts the matched
    text, `` $` `` and `$'` the text around it, `$$` a literal `$` — so the original
    `template.replace(/%\\(title\\)s/g, title)` turned a workspace called `My $& Analysis` into
    "My %(title)s Analysis": the placeholder reappeared in place of the name. Not a security
    problem, since the result is assigned with `textContent` and cannot become markup, but the
    dialog then names the workspace differently from the card that opened it, which defeats the
    reason §2′.3 quotes the title above a destructive button.

    **Why the title is set from the test rather than through the app.** There is no rename route
    until phase 3, so every workspace this server can create is called "My analysis". The card's
    `data-workspace-title` is set here directly, which is precisely the input the dialog script
    reads — so what is exercised is the substitution, which is where the defect was. The escaping
    of the title into the DOM is a separate property and is covered by the dialog using
    `textContent` at all.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    context, pg = _list_page(browser, base_url)

    tricky = "My $& $` $' $$ Analysis"
    card = pg.locator(f'[data-workspace-card][data-workspace-id="{workspace_id}"]')
    card.locator("[data-delete-workspace]").evaluate(
        "(el, t) => el.dataset.workspaceTitle = t", tricky
    )
    card.locator("[data-delete-workspace]").click()

    body = pg.locator("#delete-workspace-dialog").inner_text()
    assert f'"{tricky}"' in body, f"the title was mangled by the substitution: {body!r}"
    # The placeholder must not have reappeared, which is the shape the old bug took.
    assert "%(title)s" not in body
    context.close()


def test_the_delete_data_dialog_says_what_it_keeps(browser, base_url):
    """§2′.3: the data dialog must state what survives AND what does not, both truthfully.

    A deletion dialog that says only what it destroys makes the user guess at the rest, which is
    why the spec writes the kept/not-kept sentence into the copy rather than leaving it implied.
    Reached here through a workspace that HAS data, since the button is absent otherwise.

    The copy changed in the phase-2 review. It used to promise "your data sources stay chosen",
    which is false for any slot the user had actually fetched: a fetched slot's source key and HA
    statistic id live in `series_meta`, which is exactly what a data deletion removes. The dialog
    now says the sources have to be chosen again, and this asserts BOTH halves — that the settings
    are kept and that the sources are not — so a revert to the old promise fails here rather than
    only in the catalog tests.

    This test is also the real-browser check that the delete flow still works at all under the
    same-site check added in the same review (`app/csrf.py`): the POST below is an ordinary
    same-origin form submit from the app's own page, and a check that got the header logic wrong
    would 403 it here.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    # Give it a dataset the only way this out-of-process server allows: the backend_load slot
    # route, which loads one series server-side and merges it into a dataset. It is real
    # persistence through a real route, which is what makes the card's data variant render.
    import json as _json

    body = _json.dumps({
        "source": "energy_charts",
        "window": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-01-03T00:00:00+00:00"},
    }).encode()
    req = Request(
        f"{base_url}/w/{workspace_id}/data/slot/price_spot/load",
        data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(req, timeout=30) as r:
            assert r.status == 200
    except Exception as exc:  # the preset source is a network call; skip rather than fail on it
        pytest.skip(f"could not load a dataset for the data-delete dialog: {exc}")

    context, pg = _list_page(browser, base_url)
    card = pg.locator(f'[data-workspace-card][data-workspace-id="{workspace_id}"]')
    title = card.locator("h3").inner_text().strip()
    card.locator("[data-delete-data]").click()

    dialog = pg.locator("#delete-data-dialog")
    assert dialog.is_visible()
    body_text = dialog.inner_text()
    assert f'"{title}"' in body_text
    # What is kept…
    assert "Your connection, contract and battery settings are kept." in body_text
    # …and what is not, which the old copy claimed survived.
    assert "choose your data sources again" in body_text
    assert "stay chosen" not in body_text

    dialog.get_by_role("button", name="Delete data").click()
    pg.wait_for_load_state("networkidle")
    # Back on the list, and the card is in its no-data state rather than gone.
    card = pg.locator(f'[data-workspace-card][data-workspace-id="{workspace_id}"]')
    assert card.count() == 1
    assert card.get_by_text("No data loaded yet.").is_visible()
    context.close()


def test_the_empty_list_invites_creation_rather_than_showing_a_phantom(browser, tmp_path_factory):
    """A FRESH installation shows the empty list, not an analysis the user never made.

    This one runs its own server against its own untouched data directory, because that is the
    only way to observe a genuinely fresh install: the module-scoped `base_url` server has had
    workspaces created against it by every test above, so `/` there is never empty again.

    It is the browser counterpart of `tests/test_workspace_list.py`'s route-level version, and it
    exists for the reason phase 1's changelog records: the fresh-install path is exactly the one
    seeded fixtures cannot see, and the last defect on it was invisible to the whole non-browser
    suite.
    """
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "BATTERY_SIM_DATA_DIR": str(tmp_path_factory.mktemp("fresh"))}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
         "--log-level", "warning"],
        cwd=REPO_ROOT, env=env,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urlopen(url + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("server did not start")

        context = browser.new_context()
        context.add_cookies([{"name": "lang", "value": "en", "url": url}])
        pg = context.new_page()
        pg.goto(url + "/", wait_until="networkidle")

        assert pg.locator("[data-workspace-card]").count() == 0
        assert pg.get_by_text("You have no analyses yet.").is_visible()
        # And the invitation is a working control, not decoration.
        pg.get_by_role("button", name="+ New analysis").first.click()
        pg.wait_for_load_state("networkidle")
        pg.goto(url + "/", wait_until="networkidle")
        assert pg.locator("[data-workspace-card]").count() == 1
        context.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


# ── The edit-workspace screen (phase 3, §2′.4, §2′.8) ─────────────────────────────────────────

def test_the_update_button_reaches_the_edit_screen_and_saves(browser, base_url):
    """§2′.2's `[ Update ]` → §2′.4's screen → `[ Save ]` → back to the list, in a real browser.

    The whole round trip through the controls a user actually touches: the card's action, the
    title input, the connection dropdown, and the footer's `[ Save ]`. Asserted end to end rather
    than per route because the parts a route test cannot see are the ones that break — that the
    `<select>` posts a value the route can read back into two fields, and that a successful save
    lands on the re-rendered list rather than on a fragment.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(base_url + "/", wait_until="networkidle")

    card = pg.locator(f'[data-workspace-id="{workspace_id}"]')
    card.get_by_role("link", name="Update").click()
    pg.wait_for_load_state("networkidle")
    assert "/edit" in pg.url

    pg.fill("#edit-title", "Browser-named analysis")
    pg.fill("#edit-postcode", "1012 AB")
    pg.select_option("#edit-connection", "3:63")
    pg.get_by_role("button", name="Save").click()
    pg.wait_for_load_state("networkidle")

    # Back on the list, with the new title and the connection badge derived from the new pair.
    assert pg.url.rstrip("/") == base_url.rstrip("/")
    body = pg.locator("body").inner_text()
    assert "Browser-named analysis" in body
    assert "3×63 A" in body
    context.close()


def test_cancelling_with_unsaved_changes_prompts_and_can_be_kept(browser, base_url):
    """§2′.8: `[ Cancel ]` warns when there are unsaved changes, and `[ Keep editing ]` stays put.

    The dirty check is client-side, so this is the only place it can be exercised. Both halves
    matter and both are here: with nothing typed the button leaves IMMEDIATELY — §2′.8 is explicit
    that an unconditional prompt would be noise on the common case of opening a screen to look at
    it — and with something typed the dialog appears and `[ Keep editing ]` returns to the form
    with the typing intact.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/edit", wait_until="networkidle")

    # Nothing typed: no prompt, straight to the list.
    pg.get_by_role("link", name="Cancel").click()
    pg.wait_for_load_state("networkidle")
    assert pg.url.rstrip("/") == base_url.rstrip("/")

    # Something typed: the prompt appears and keeps the user on the screen.
    pg.goto(f"{base_url}/w/{workspace_id}/edit", wait_until="networkidle")
    pg.fill("#edit-title", "Typed but not saved")
    pg.get_by_role("link", name="Cancel").click()
    assert pg.locator("#discard-dialog").is_visible()
    pg.get_by_role("button", name="Keep editing").first.click()
    pg.wait_for_timeout(200)
    assert "/edit" in pg.url
    assert pg.input_value("#edit-title") == "Typed but not saved"
    context.close()


def test_a_collapsed_advanced_pane_still_submits_its_values(browser, base_url):
    """§2′.4: collapsing is a DISPLAY state, never a reset — checked through a real submit.

    This is the property `<details>` buys and the one a conditional render would break silently:
    the user opens Advanced, types an import override, collapses the pane again, saves — and the
    override must survive. Nothing but a browser can close the pane, which is why this is here as
    well as in the route tests.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/edit", wait_until="networkidle")

    pane = pg.locator("details[data-advanced]").first
    pane.locator("summary").click()
    pg.fill('input[name="grid.max_import_kw_override"]', "7.5")
    pane.locator("summary").click()          # collapse it again
    assert not pane.evaluate("el => el.open")

    pg.get_by_role("button", name="Save").click()
    pg.wait_for_load_state("networkidle")

    pg.goto(f"{base_url}/w/{workspace_id}/edit", wait_until="networkidle")
    assert pg.input_value('input[name="grid.max_import_kw_override"]') == "7.50"
    # And the collapsed summary says so, so it cannot hide there unnoticed. Compared
    # case-insensitively: the summary line carries Tailwind's `uppercase`, which is a CSS
    # transform, so `inner_text()` reports it as the browser paints it rather than as the
    # template wrote it.
    assert "1 value overridden" in pg.locator("body").inner_text().lower()
    context.close()


# ── The configure-data screen (phase 4.1, §2′.5, §2′.8, §2′.11) ────────────────────────────────


def test_the_configure_data_button_reaches_the_screen_and_saves(browser, base_url):
    """§2′.2's `[ Configure data ]` → §2′.5's screen → `[ Save ]` → back to the list.

    The round trip through the controls a user touches. What only a browser can check here is that
    the footer's `[ Save ]` — which sits OUTSIDE the form and reaches it through HTML's `form=`
    association — actually submits the household box, and that the answer comes back on a reload.
    A route test posts the fields directly and so cannot see the association at all.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(base_url + "/", wait_until="networkidle")

    card = pg.locator(f'[data-workspace-id="{workspace_id}"]')
    card.get_by_role("link", name="Configure data").click()
    pg.wait_for_load_state("networkidle")
    assert "/data" in pg.url, pg.url
    # The screen, not a 404 or the three-panel page.
    assert pg.locator("#slot-roster").count() == 1
    assert pg.locator("#panel-params").count() == 0

    # Answer both questions the non-default way, then save.
    pg.locator('input[name="setup_haspv"][value="0"]').check()
    pg.locator('input[name="setup_hasbattery"][value="1"]').check()
    pg.get_by_role("button", name="Save").click()
    pg.wait_for_load_state("networkidle")
    assert pg.url.rstrip("/") == base_url.rstrip("/")

    # Reopened, the screen reports what was stored — so the submit really went through the form.
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    assert pg.locator('input[name="setup_haspv"][value="0"]').is_checked()
    assert pg.locator('input[name="setup_hasbattery"][value="1"]').is_checked()

    # Leave the module's shared workspace as it was found (has_pv on, no battery), since other
    # tests in this file read the roster's PV-gated rows.
    pg.locator('input[name="setup_haspv"][value="1"]').check()
    pg.locator('input[name="setup_hasbattery"][value="0"]').check()
    pg.get_by_role("button", name="Save").click()
    pg.wait_for_load_state("networkidle")
    context.close()


def test_the_household_answers_regate_the_roster_without_a_round_trip(browser, base_url):
    """§2′.5: the two answers "still re-derive the roster in place".

    `applySetupGating` keys on the radio NAMES, so this is also the test that catches the names
    drifting to the `setup.`-prefixed form: a rename leaves the handler bound to nothing and the
    solar row simply stops responding. Asserted with no navigation between the two states, which is
    the "in place" part.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")

    pv_row = pg.locator("tr.slot-row[data-pv-only]").first
    pg.locator('input[name="setup_haspv"][value="1"]').check()
    assert pv_row.is_visible(), "the PV row should be shown when the answer is yes"

    pg.locator('input[name="setup_haspv"][value="0"]').check()
    assert not pv_row.is_visible(), "answering no should hide the PV row with no reload"

    pg.locator('input[name="setup_haspv"][value="1"]').check()
    assert pv_row.is_visible(), "and turning it back on should restore the row"
    context.close()


def test_leaving_with_a_staged_but_unfetched_slot_warns(browser, base_url):
    """§2′.8: the dirty test here is a slot mapping changed since the last fetch.

    The state is a generation-tagged `localStorage` entry (§2′.11), so this is the only place the
    check can be exercised at all. All three branches are here, because each is a different
    specified behaviour and two of them are the ones a naive check gets wrong:

      * a CURRENT-generation entry warns, and `[ Keep editing ]` stays on the screen;
      * a STALE-generation entry does NOT warn — the server already superseded it, so warning
        would be a prompt about a change that has taken effect;
      * no entry at all does not warn, which §2′.8 requires ("an unconditional prompt would be
        noise on the common case of opening a screen to look at it").
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    key = f"ha.slots.{workspace_id}"

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")

    # The generation the server rendered — what a staged entry has to match to count as unfetched.
    gen = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )

    # 1. Nothing staged: the back link leaves immediately.
    pg.evaluate("k => localStorage.removeItem(k)", key)
    pg.get_by_role("link", name="Cancel").click()
    pg.wait_for_load_state("networkidle")
    assert pg.url.rstrip("/") == base_url.rstrip("/"), "a clean screen must not prompt"

    # 2. A staged entry at the CURRENT generation: the warning fires and Keep editing stays.
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    pg.evaluate(
        """([k, g]) => localStorage.setItem(k, JSON.stringify(
               {gen: g, slots: {grid_import_t1: {source: 'home_assistant', statId: 'sensor.x'}}}))""",
        [key, gen],
    )
    pg.get_by_role("link", name="Cancel").click()
    assert pg.locator("#unfetched-dialog").is_visible(), "a staged slot must warn before leaving"
    body = pg.locator("#unfetched-dialog").inner_text()
    assert "not loaded your data yet" in body
    pg.get_by_role("button", name="Keep editing").first.click()
    pg.wait_for_timeout(200)
    assert "/data" in pg.url, "Keep editing must stay on the screen"

    # 3. The same entry at a STALE generation is not dirty: a fetch has superseded it.
    pg.evaluate(
        """([k, g]) => localStorage.setItem(k, JSON.stringify(
               {gen: g - 1, slots: {grid_import_t1: {source: 'home_assistant', statId: 'sensor.x'}}}))""",
        [key, gen],
    )
    pg.get_by_role("link", name="Cancel").click()
    pg.wait_for_load_state("networkidle")
    assert pg.url.rstrip("/") == base_url.rstrip("/"), (
        "a stale-generation entry must not warn — the server already superseded it"
    )

    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    pg.evaluate("k => localStorage.removeItem(k)", key)
    context.close()


def test_leaving_anyway_from_the_warning_actually_leaves(browser, base_url):
    """The other button on §2′.8's dialog: `[ Leave anyway ]` discards and navigates."""
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    key = f"ha.slots.{workspace_id}"

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    gen = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )
    pg.evaluate(
        """([k, g]) => localStorage.setItem(k, JSON.stringify(
               {gen: g, slots: {grid_import_t1: {source: 'home_assistant', statId: 'sensor.x'}}}))""",
        [key, gen],
    )

    pg.get_by_role("link", name="Cancel").click()
    assert pg.locator("#unfetched-dialog").is_visible()
    pg.get_by_role("button", name="Leave anyway").click()
    pg.wait_for_load_state("networkidle")
    assert pg.url.rstrip("/") == base_url.rstrip("/")

    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    pg.evaluate("k => localStorage.removeItem(k)", key)
    context.close()


def test_the_source_drawer_opens_on_the_configure_data_screen(browser, base_url):
    """§2′.5: the drawer stays a right-side overlay over THIS screen.

    `app/static/ha_fetch.js` needed no change to work here — it gates on `#slot-roster` and resolves
    everything else by id — and this is what actually verifies that claim rather than asserting it.
    A missing hook would leave the button inert, which no route test can see.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")

    drawer = pg.locator("#source-drawer")
    assert not drawer.is_visible(), "the drawer starts closed"

    pg.locator("#slot-roster .slot-source-btn").first.click()
    assert drawer.is_visible(), "the slot's source button must open the drawer"
    # It is populated for the clicked slot, not empty chrome.
    assert pg.locator("#drawer-source-list input[type=radio]").count() > 0

    # Cancel discards and closes, leaving the committed state untouched (§2.2).
    pg.locator("#drawer-cancel").click()
    pg.wait_for_timeout(150)
    assert not drawer.is_visible()
    context.close()


def test_the_wizard_footer_walks_edit_to_data_to_results(browser, base_url):
    """§2′.8's wizard chain, now that step 2 exists.

    Phase 3 had to send `[ Next → ]` from step 1 straight to the results page because the
    configure-data screen did not exist. This walks the real sequence and is what would catch that
    temporary destination being left behind.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/edit?mode=wizard", wait_until="networkidle")

    pg.get_by_role("button", name="Next").click()
    pg.wait_for_load_state("networkidle")
    assert "/data" in pg.url, f"step 1's Next should reach configure data, got {pg.url}"
    assert "mode=wizard" in pg.url, "the wizard mode must survive the step"

    # Step 2's Previous goes BACK to step 1, still in wizard mode.
    pg.get_by_role("link", name="Previous").click()
    pg.wait_for_load_state("networkidle")
    assert "/edit" in pg.url and "mode=wizard" in pg.url, pg.url

    # Forward again, then step 2's Next ends the wizard on the results screen.
    pg.get_by_role("button", name="Next").click()
    pg.wait_for_load_state("networkidle")
    pg.get_by_role("button", name="Next").click()
    pg.wait_for_load_state("networkidle")
    assert "/results" in pg.url, f"step 2's Next should reach results, got {pg.url}"
    context.close()
