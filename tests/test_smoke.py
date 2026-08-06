"""Playwright smoke test for the frontend scaffold.

Asserts the page renders and the key visual items of the default variant (has_pv=True,
simulate_cost=False) are present or absent as the wireframes require. This is deliberately
about structure, not exact numbers — the numbers are static sample data and will be replaced
when the domain layer lands.

It also covers the pending affordance (docs/specs/02-ux-wireframes.md §2.1): the pending
controls open the "Not built yet" dialog, the thumbs-up acknowledges in place, and the
counter route (docs/specs/08-architecture.md §5.1) upserts once per key and 404s an unknown key.
The server runs against a throwaway data directory so the counter DB and the generated
config.toml never touch the working tree.

Phase 5's wizard adds three here (docs/specs/20-workspaces-ux.md §2′.8): the walk from step 1 to step
3, and two that genuinely need a browser. The first is the Blocked `[ Next → ]` on step 2 —
markup alone cannot establish that a Blocked control READS as blocked, since phase 4 shipped a
message present in the DOM and invisible on the page, so that test asserts a real bounding box,
computed opacity, and that a click does not advance. The second is the escape from the blocked
state (review finding R1), which depends on `applySetupGating` hiding the solar roster row and so
cannot be reproduced at route level at all.

One test here is about the BROWSER's storage rather than the page's markup:
`test_ha_fetch_scopes_its_slot_store_per_workspace` pins that `ha_fetch.js` keys its slot store
per workspace and discards the pre-workspaces global `ha.slots`
(docs/specs/20-workspaces-ux.md §2′.11). It belongs in a real browser because what it checks is what
that module DOES at load, which no source-level assertion can observe.

    uv run pytest tests/test_smoke.py

Requires the CSS built (npm run build:css) and Playwright's Chromium installed.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from playwright.sync_api import expect, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent

# The data directory the server subprocess was started with. Set by the `base_url` fixture, and
# read by `_seed_reconstructable_dataset` — the one place a test has to write a file the running
# server will read back. Declared here so the name exists before that fixture runs rather than
# appearing out of nowhere as a module attribute.
_SERVER_DATA_DIR: str | None = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url(tmp_path_factory, request):
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    # Isolate the counter DB + generated config.toml in a temp dir, not the repo's ./data.
    data_dir = tmp_path_factory.mktemp("data")
    # Published on the module so `server_data_dir` can hand it to a test that needs to put a
    # dataset where the server will find it. See that fixture for why that is worth doing.
    request.module._SERVER_DATA_DIR = str(data_dir)
    env = {**os.environ, "BATTERY_SIM_DATA_DIR": str(data_dir)}
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

    **The results URL is DERIVED, not read off the redirect.** Since phase 5 the create route
    redirects into the wizard's step 1 (`/w/{id}/edit?mode=wizard`, §2′.8), and roughly thirty tests
    below use this helper's return value as "the results page". Returning the redirect's own
    destination would silently move all of them onto a different screen. The destination itself is
    a behaviour with its own test — `test_the_list_creates_a_workspace_and_navigates_into_it` —
    rather than something this helper should be implicitly asserting.
    """
    req = Request(base_url + "/workspaces", data=b"", method="POST")
    with urlopen(req) as r:
        # urllib follows the 303, so the final URL is where the route sent the browser. Every
        # per-workspace URL carries the id in the same position, so the id survives the change.
        workspace_id = r.url.split("?")[0].rstrip("/").split("/")[-2]
    return f"{base_url}/w/{workspace_id}/results"


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

    # 3-phase through the real control, so the battery-phase selector is offered. The connection
    # is set on the EDIT screen since §2′.1 — §2′.4's preset dropdown, one select carrying both
    # `grid.phases` and `grid.fuse_a` as a "<phases>:<fuse>" token — not in the results pane, which
    # no longer draws either field.
    pg.goto(f"{base_url}/w/{workspace_id}/edit", wait_until="networkidle")
    pg.locator('select[name="grid.connection"]').select_option("3:25")
    pg.get_by_role("button", name="Save").click()
    pg.wait_for_load_state("networkidle")

    pg.goto(f"{base_url}/w/{workspace_id}/results", wait_until="networkidle")
    pg.locator("summary", has_text="More settings").click()

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
    #
    # The slot is addressed BY NAME (`data-slot="price_spot"`), not by `[data-slot-sources
    # *='backend_load'] .first`. That older selector meant "the first slot with any backend source"
    # and worked only while price_spot was the only such slot — it broke the moment the uploaded-CSV
    # source (also backend_load) was registered for the energy slots, since `.first` then landed on
    # grid_import_t1, whose drawer has no energy_charts radio. What this test needs is the slot that
    # offers `energy_charts`, and that slot is price_spot; naming it says so and cannot drift when
    # another source is added.
    pg.locator("#slot-roster .slot-source-btn[data-slot='price_spot']").click()
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
    # "Upload CSV" USED to be asserted here as a pending source radio — disabled, name
    # "drawer-source", feature key data_source_csv — inside the source-picker drawer. Step 6 of the
    # CSV-import work built its file/column/unit controls and the upload dialog, so the stub was
    # deleted and this assertion went with it, exactly as its own comment said it would. What the
    # radio does now is covered by the CSV drawer tests at the bottom of this file. Step 7 then
    # retired the `data_source_csv` key into `RETIRED_KEYS`, so nothing here looks for it; that
    # retirement is pinned in tests/test_workspace_data.py and tests/test_params_route.py.
    #
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


def test_thumbsup_links_to_a_prefilled_github_issue(page):
    # Clicking the thumbs-up used to flip the button to "✓ Noted" and POST to a counter route.
    # It is a LINK now: the request is filed as a GitHub issue and nothing is recorded locally,
    # so what this asserts is the composed href rather than an in-place acknowledgement.
    #
    # Uses panel ③'s "Export CSV" button: it is present unconditionally (unlike the Pricing box's
    # pending contract radios, which only exist once cost simulation is on) and results export
    # genuinely is still unbuilt.
    # Scoped to `button[...]`: #pending-dialog itself carries data-feature-key (the script parks
    # the clicked control's key there), so a bare attribute selector matches two elements once any
    # earlier test has opened the dialog.
    page.locator("button[data-feature-key=export_csv]").click()
    dialog = page.locator("#pending-dialog")
    assert dialog.get_by_role("heading", name="Not built yet").is_visible()

    link = dialog.get_by_role("link", name="I want this")
    href = link.get_attribute("href")
    assert href.startswith("https://github.com/knz/battery-sim/issues/new?"), href
    # The form, the title and the feature field are all pre-filled from the control that was
    # clicked — the whole point of composing the URL server-side (app/features.py).
    assert "template=feature.yml" in href
    assert "Export+CSV" in href
    assert "export_csv" in href
    # Opens in a new tab: the dialog is reached mid-analysis and navigating away would lose it.
    assert link.get_attribute("target") == "_blank"
    # Not followed. The suite must pass offline, and whether github.com is up is not this app's
    # defect — the same rule test_workspace_results.py applies to the footer's external links.
    page.keyboard.press("Escape")


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

    # Now it is live.
    yes = page.locator("#setup-simulate-cost input[value='yes']")
    assert not yes.is_disabled(), "saving the contract must unblock the toggle"
    yes.check()
    page.wait_for_load_state("networkidle")

    # **What is measured changed with §2′.1, and the CSS hazard did not.** The tinted set used to
    # be the Pricing box's inputs (`.cost-field`); that box moved to the edit-workspace screen,
    # which does not tint, so no `.cost-field` element is rendered anywhere today. The `.cost-label`
    # half is still live on this screen — the cost toggle's own label, the COST SAVINGS divider and
    # the euro headings — and it runs the same override risk against the same later daisyUI layer,
    # so it is what this test now measures.
    #
    # The toggle's label is used because it needs no dataset: this fixture has no data, so the
    # divider and the KPI tile below it do not render.
    tinted = page.locator("#setup-simulate-cost span.cost-label").first
    plain = page.locator("#setup-simulate-cost + p, label.label span.label-text").first
    tinted_color = tinted.evaluate("e => getComputedStyle(e).color")
    plain_color = plain.evaluate("e => getComputedStyle(e).color")
    assert tinted_color != plain_color, (
        f"the cost label renders {tinted_color}, identical to an untinted label — the rule is "
        "being overridden, most likely by a later CSS layer"
    )


def test_the_blocked_cost_toggle_reads_as_blocked_and_its_way_out_resolves(browser, base_url):
    """§2′.6's Blocked cost toggle, as a user SEES it, and the link that clears it.

    `test_the_cost_tint_actually_renders_and_is_not_merely_a_class_name` above already drives the
    Blocked→live transition, but it asserts the blocked half through `is_disabled()` alone — an
    ATTRIBUTE. §2.1's Blocked state is "greyed, with an adjacent affordance saying how to clear the
    precondition", and neither half of that is an attribute:

      * the greying is `.blocked-control { opacity: 0.55 }`, which is exactly the kind of rule this
        file has already watched fail silently. The tint next to it in `app.tailwind.css` parsed,
        shipped and rendered nothing because daisyUI restated the same property in a later cascade
        layer, while every class-name assertion passed. `.blocked-control` compiles unlayered today
        and so should win, but "should win" is what was believed about the tint too, so the dim is
        measured on COMPUTED opacity rather than inferred from the class being present.
      * the affordance is a LINK to the edit screen's Contract box. The test above asserts it is
        visible; visible is not the same as working. A dialog whose only action is a dead link
        leaves the user exactly where §2′.6 says they must not be — able to see that something
        blocks them and unable to reach what clears it. So it is followed, and the destination is
        asserted to be the Contract box on the edit screen.

    Its own workspace and its own context: `pricing_configured` is a stored flag and the module's
    shared workspace has it SET by the time the tint test has run, so this would otherwise pass or
    fail depending on test order.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(url, wait_until="networkidle")

    row = pg.locator("#setup-simulate-cost")
    # Blocked, not Inapplicable: still on screen. Hiding it is the wrong rendering.
    assert row.is_visible(), "the Blocked cost toggle must stay on screen"
    assert row.get_attribute("data-blocked") == "1", "this workspace should have no contract yet"
    assert pg.locator("#setup-simulate-cost input[value='yes']").is_disabled()

    # Dimmed, measured rather than assumed. The comparison is against a sibling label on the same
    # screen, so this does not pin the specific opacity — a design choice — only that the row
    # renders FAINTER than untinted copy, which is what "greyed" means to a reader.
    dim = float(row.evaluate("e => getComputedStyle(e).opacity"))
    assert 0.2 < dim < 0.9, (
        f"the Blocked row renders at opacity {dim} — .blocked-control is not taking effect, most "
        "likely overridden by a later cascade layer (the hazard the cost tint hit)"
    )

    # The affordance, followed. `[ Set up my contract → ]` must land on the edit screen with the
    # Contract box in view — the `#contract` anchor §2′.6 names.
    pg.locator("#cost-blocked-info").click()
    dialog = pg.locator("#cost-blocked-dialog")
    assert dialog.is_visible()
    link = dialog.get_by_role("link", name="Set up my contract")
    assert link.is_visible()
    link.click()
    pg.wait_for_load_state("networkidle")
    assert f"/w/{workspace_id}/edit" in pg.url, f"the way out must reach the edit screen: {pg.url}"
    assert pg.url.endswith("#contract"), f"and land on the Contract box: {pg.url}"
    # The anchor is real, not just a fragment in a URL — a dead anchor scrolls nowhere.
    target = pg.locator("#contract")
    assert target.count() == 1, "the edit screen has no #contract anchor to land on"
    assert target.is_visible()
    context.close()


# ── The workspace list (docs/specs/20-workspaces-ux.md §2′.2, §2′.3) ──────────────────────────────
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


def test_the_list_creates_a_workspace_and_starts_the_wizard(browser, base_url):
    """`[ + New analysis ]` is a real form POST that lands on step 1 of §2′.8's wizard.

    Driven end to end because the button, the route, the redirect and the destination are four
    separate things and a route test only sees the middle two.

    Phase 5 changed the destination from the results screen — which for a workspace created a
    moment ago is empty and says nothing about what to do next — to the edit screen in wizard mode.
    So this asserts the wizard is genuinely RUNNING, not merely that the edit screen rendered: the
    step indicator and the `[ Next → ]` footer are what distinguish the two, and landing on
    `/edit` without the mode would look identical to a URL check.
    """
    context, pg = _list_page(browser, base_url)
    before = pg.locator("[data-workspace-card]").count()

    pg.get_by_role("button", name="+ New analysis").first.click()
    pg.wait_for_load_state("networkidle")

    import re as _re

    assert _re.search(r"/w/[0-9a-f]{32}/edit\?mode=wizard$", pg.url), pg.url
    # Step 1, in the wizard: the edit screen's own field, the indicator, and the wizard footer.
    body = pg.locator("body").inner_text()
    assert "Grid connection" in body, body[:300]
    assert pg.locator("[data-wizard-step]").is_visible()
    assert "Step 1 of 3" in pg.locator("[data-wizard-step]").inner_text()
    assert pg.get_by_role("button", name="Next").is_visible()

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

def test_the_configure_analysis_button_reaches_the_edit_screen_and_saves(browser, base_url):
    """§2′.2's `[ Configure analysis ]` → §2′.4 → `[ Save ]` → the list, in a real browser.

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
    card.get_by_role("link", name="Configure analysis").click()
    pg.wait_for_load_state("networkidle")
    assert "/edit" in pg.url

    pg.fill("#edit-title", "Browser-named analysis")
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


# A stand-in for Home Assistant's WebSocket API, installed as `window.WebSocket` before any script
# runs. `HaClient` (ha_fetch.js) resolves the global at call time and speaks only four messages, so
# a stub that answers those exercises the real client, the real testConnection, and the real
# preselect path — everything except the socket itself. Driving this against a live HA is not an
# option in CI, and stubbing at any higher level (e.g. replacing testConnection) would stop testing
# the code that actually broke.
#
# The statistic ids mirror the shape a Dutch DSMR install produces, including the `_cost` siblings
# that sort adjacent to the energy sensors — that adjacency is the reason `guessId`'s first-match
# rule needs asserting rather than assuming.
_HA_WS_STUB = """
window.__haCalls = [];
class FakeHaSocket {
  constructor(url) {
    this.url = url;
    window.__haCalls.push(url);
    setTimeout(() => this.onmessage &&
      this.onmessage({data: JSON.stringify({type: 'auth_required'})}), 0);
  }
  send(raw) {
    const msg = JSON.parse(raw);
    const reply = (m) => setTimeout(() =>
      this.onmessage && this.onmessage({data: JSON.stringify(m)}), 0);
    if (msg.type === 'auth') { reply({type: 'auth_ok'}); return; }
    if (msg.type === 'recorder/list_statistic_ids') {
      const sums = window.__haSums || [
                    'sensor.energy_consumed_tariff_1', 'sensor.energy_consumed_tariff_1_cost',
                    'sensor.energy_consumed_tariff_2', 'sensor.energy_consumed_tariff_2_cost',
                    'sensor.energy_produced_tariff_1', 'sensor.energy_produced_tariff_2',
                    'sensor.gas_meter'];
      const means = ['sensor.epex_spot_data2_average_price', 'sensor.outside_temperature'];
      const ids = msg.statistic_type === 'mean' ? means : sums;
      reply({type: 'result', id: msg.id, success: true,
             result: ids.map((i) => ({statistic_id: i}))});
    }
  }
  close() { if (this.onclose) this.onclose(); }
}
window.WebSocket = FakeHaSocket;
"""


def _connect_ha(pg):
    """Fill in the shared connection modal and let the stubbed Test connection succeed.

    The button beside the Home Assistant radio is matched by position rather than by label: it
    reads "Configure…" until a connection has been tested and "✓ Connected" afterwards, and this
    helper is used on both sides of that change.
    """
    pg.locator("#drawer-source-list label", has=pg.locator(
        "input[value='home_assistant']")).locator("button").first.click()
    pg.locator("#ha-base-url").fill("https://ha.example:8123")
    pg.locator("#ha-token").fill("a-token")
    pg.locator("#ha-test-btn").click()
    expect(pg.locator("#ha-status")).to_contain_text("Connected", timeout=3000)
    pg.evaluate("() => document.getElementById('ha-config-dialog').close()")


# Strip a roster slot's server-seeded source/entity so it is genuinely unconfigured, BEFORE
# ha_fetch.js reads the attributes into `slotState`.
#
# The empty-state screen renders `app/sample_data.py`, which ships most slots already bound to a
# Home Assistant entity (`sensor.electricity_meter_import_t1` and friends). That is the FILLED
# state, not the one the regression lives in: a slot arriving with a `stat_id` seeds `draft.statId`,
# so the preselect has nothing left to decide and the bug is invisible.
#
# Clearing the attributes — rather than picking whichever slot the sample happens to leave blank —
# keeps the test on `grid_import_t1`, the slot the bug was reported against, and keeps it honest if
# the sample's bindings change.
#
# Done through the localStorage slot store rather than by rewriting the button's attributes: the
# store is the documented override (a current-generation entry is a pre-fetch customization and wins
# over the server's committed choice), whereas the attributes are read by a `defer` script during
# parse, which is racy to get in front of. An entry with an empty source and no statId is exactly
# what an unconfigured slot looks like.
def _make_slot_pristine(pg, base_url: str, workspace_id: str, slot: str = "grid_import_t1"):
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    gen = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )
    pg.evaluate(
        """([k, g, s]) => localStorage.setItem(k, JSON.stringify(
               {gen: g, slots: {[s]: {source: '', statId: ''}}}))""",
        [f"ha.slots.{workspace_id}", gen, slot],
    )
    pg.reload(wait_until="networkidle")


def test_a_successful_connection_preselects_the_slots_entity(browser, base_url):
    """A tested connection must fill the slot's entity <select>, guessed from the slot name.

    The regression this pins: on a FRESH workspace no slot has a committed source, so `draft.source`
    was null, no radio matched at render time, `onSelectSource` never fired — and `testConnection`'s
    refill (gated on `draft.source === 'home_assistant'`) never ran. The connection card said
    "Connected" while the entity select stayed empty. The drawer showed Home Assistant as chosen
    while the draft held nothing, so the two had to be brought into agreement.

    Driven through the real drawer on a fresh workspace because that mismatch only exists in the
    uncommitted state — any test that first stages a source would seed `draft.source` and walk past
    the bug.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.add_init_script(_HA_WS_STUB)
    _make_slot_pristine(pg, base_url, workspace_id)

    # Open the drawer for grid import T1 — stripped above, so it has no committed source.
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    assert pg.locator("#source-drawer").is_visible()

    # The radio the drawer SHOWS as chosen is Home Assistant, and the draft agrees: the entity
    # picker is revealed, which only onSelectSource does. Before the fix nothing was checked.
    ha_radio = pg.locator("#source-drawer input[name='drawer-source'][value='home_assistant']")
    assert ha_radio.is_checked(), "a fresh slot must stage its default source, not leave none checked"
    assert pg.locator("#drawer-ha-entity").is_visible(), "picking HA must reveal the entity picker"

    _connect_ha(pg)

    # The heuristic ran and landed on the energy sensor — not "", and not the `_cost` sibling that
    # sorts immediately after it.
    sel = pg.locator("#drawer-entity-select")
    expect(sel).to_have_value("sensor.energy_consumed_tariff_1", timeout=3000)
    assert sel.locator("option").count() > 1, "the select must be populated with the energy ids"

    # Confirm commits what was staged, so the guess reaches the row rather than dying in the draft.
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)
    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert "sensor.energy_consumed_tariff_1" in (stored or "")
    context.close()


def test_the_spot_price_slot_defaults_to_the_energy_charts_preset(browser, base_url):
    """price_spot is the one slot whose staged default is a preset, not Home Assistant.

    Every other slot takes the first browser_fetch source, because HA is where a household's own
    meter history comes from. The spot price is different: a household generally cannot supply it
    from its own HA history, while the Energy-Charts dataset is committed on disk and bridged live
    to the end of the window — it fills the slot with nothing to configure. Defaulting to HA here
    would preselect the one option that needs setup before it can produce anything.

    Note this pins the KEY, not the position: `price_spot` offers three sources (HA, energy_charts,
    entsoe_nl), so "the second one" and "the first backend_load one" would both pass by accident.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.add_init_script(_HA_WS_STUB)
    _make_slot_pristine(pg, base_url, workspace_id, slot="price_spot")

    pg.locator("#slot-roster .slot-source-btn[data-slot='price_spot']").click()
    assert pg.locator("#source-drawer").is_visible()

    ec_radio = pg.locator("#source-drawer input[name='drawer-source'][value='energy_charts']")
    assert ec_radio.is_checked(), "a fresh price_spot slot must stage the Energy-Charts preset"
    ha_radio = pg.locator("#source-drawer input[name='drawer-source'][value='home_assistant']")
    assert not ha_radio.is_checked(), "Home Assistant must not be the spot-price default"

    # The staged default is a real draft choice, not just a checked radio: Confirm commits it
    # without an entity, which only the backend branch allows.
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)
    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert "energy_charts" in (stored or ""), "the staged default must survive Confirm"
    context.close()


def test_a_manually_chosen_entity_survives_a_repopulate(browser, base_url):
    """The guess is a default, never an override — but only for an id the instance actually has.

    Two repopulate cases, and they resolve differently on purpose:

      * the chosen id IS offered — `draft.statId` wins over `guessId`, so a correction the user
        made by hand is not pulled back to the heuristic's pick;
      * the chosen id is NOT offered (a different Home Assistant, or a renamed entity) — it can be
        neither displayed nor fetched, so the guess takes over. Keeping it would leave the picker
        blank with no way to tell why, which is exactly the symptom this whole changelog is about.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.add_init_script(_HA_WS_STUB)
    _make_slot_pristine(pg, base_url, workspace_id)

    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    _connect_ha(pg)

    sel = pg.locator("#drawer-entity-select")
    expect(sel).to_have_value("sensor.energy_consumed_tariff_1", timeout=3000)

    # Override the guess by hand, the way a user corrects a wrong mapping.
    sel.select_option("sensor.energy_consumed_tariff_2")

    # Re-selecting the Home Assistant radio repopulates the select for this slot. The manual choice
    # must still be there — the guess would otherwise pull it back to _tariff_1.
    pg.locator("#source-drawer input[name='drawer-source'][value='home_assistant']").click()
    expect(sel).to_have_value("sensor.energy_consumed_tariff_2")

    # Now repopulate against an instance that does NOT offer that id, but DOES offer something the
    # heuristic recognises. An id this Home Assistant does not have is not a usable choice — it can
    # be neither shown nor fetched — so the guess takes over rather than leaving an empty picker.
    pg.evaluate(
        "() => { window.__haSums = ['sensor.energy_consumed_tariff_1', 'sensor.other']; }"
    )
    _connect_ha(pg)
    expect(sel).to_have_value("sensor.energy_consumed_tariff_1", timeout=3000)

    confirm = pg.locator("#drawer-confirm")
    assert not confirm.is_disabled(), "a fallen-back guess is still a committable choice"
    confirm.click()
    pg.wait_for_timeout(150)
    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert "sensor.energy_consumed_tariff_1" in (stored or ""), (
        "the fallback guess must be what gets committed"
    )
    context.close()


def _seed_reconstructable_dataset(workspace_id: str, *, has_pv: bool = False) -> None:
    """Put grid import + export T1 where the running server will find them (§2′.8's gate).

    Written in-process, into the SAME data directory the server subprocess was given, because the
    two agree on it through `BATTERY_SIM_DATA_DIR` and `config.data_dir()` resolves it per call.
    There is no browser path that produces a grid meter — a real fetch needs a Home Assistant — so
    the alternative would be leaving the far side of the gate untested in a browser entirely.

    T1 only, deliberately, and with no PV or battery series: this is exactly the minimum the gate
    accepts (D2), so a test that walks through on it is also asserting that minimum is enough.

    The two household answers are stored here as well, and that is not incidental. The gate is
    evaluated SERVER-SIDE at render, so flipping the radios in the browser does not unblock the
    button — the block only lifts on the next render, which is the POST's re-render or a reload.
    Appendix A defaults `has_pv` to true, so a workspace with import and export alone is blocked on
    the missing solar series until someone says there is no array.

    `has_pv` is therefore a PARAMETER rather than always false, and the two settings are two
    different fixtures: false gives a dataset that satisfies the gate under the stored answers (the
    walk-through test), true gives one that does not (the trap test — blocked on the solar series
    and on nothing else, which is the state review finding R1 is about). Hardcoding it false is why
    no test entered the trap before.
    """
    import numpy as np

    os.environ["BATTERY_SIM_DATA_DIR"] = _SERVER_DATA_DIR
    from app import dataset, simconfig_store
    from app.domain.frames import QUALITY_DTYPE, SeriesFrame
    from datetime import datetime, timezone

    cfg = simconfig_store.load(workspace_id)
    cfg.has_pv = has_pv
    cfg.has_battery = False
    simconfig_store.save(simconfig_store.clone(cfg), workspace_id)

    n = 48
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600 + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")

    def frame(name, value):
        return SeriesFrame(
            name, "energy", 3600, idx, np.full(n, value), np.zeros(n, dtype=QUALITY_DTYPE)
        )

    dataset.save_dataset(
        [frame("grid_import_t1", 2.0), frame("grid_export_t1", 0.5)],
        (datetime(2026, 1, 1, tzinfo=timezone.utc),
         datetime(2026, 1, 3, tzinfo=timezone.utc)),
        "test", [], None, workspace_id=workspace_id,
    )


def test_the_wizard_footer_walks_edit_to_data_to_results(browser, base_url):
    """§2′.8's wizard chain, now that step 2 exists and its `[ Next → ]` is gated.

    Phase 3 had to send `[ Next → ]` from step 1 straight to the results page because the
    configure-data screen did not exist. This walks the real sequence and is what would catch that
    temporary destination being left behind.

    Phase 5's gate is why the dataset is seeded before the walk: without it step 2's `[ Next → ]`
    is correctly Blocked and the walk cannot finish. The blocked case is its own test below.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    _seed_reconstructable_dataset(workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/edit?mode=wizard", wait_until="networkidle")
    # Step 1 says which step it is (§2′.8's indicator, D4).
    assert "Step 1 of 3" in pg.locator("[data-wizard-step]").inner_text()

    pg.get_by_role("button", name="Next").click()
    pg.wait_for_load_state("networkidle")
    assert "/data" in pg.url, f"step 1's Next should reach configure data, got {pg.url}"
    assert "mode=wizard" in pg.url, "the wizard mode must survive the step"
    assert "Step 2 of 3" in pg.locator("[data-wizard-step]").inner_text()

    # Step 2's Previous goes BACK to step 1, still in wizard mode.
    pg.get_by_role("link", name="Previous").click()
    pg.wait_for_load_state("networkidle")
    assert "/edit" in pg.url and "mode=wizard" in pg.url, pg.url

    # Forward again. The household answers submitted by step 2 are "no PV, no battery", which with
    # the seeded import/export pair is exactly the gate's minimum — so `[ Next → ]` is live.
    pg.get_by_role("button", name="Next").click()
    pg.wait_for_load_state("networkidle")
    pg.locator('input[name="setup_haspv"][value="0"]').check()
    pg.locator('input[name="setup_hasbattery"][value="0"]').check()
    pg.get_by_role("button", name="Next").click()
    pg.wait_for_load_state("networkidle")
    assert "/results" in pg.url, f"step 2's Next should reach results, got {pg.url}"
    # Step 3 has no wizard mode and no indicator (§2′.6: no footer, no mode).
    assert pg.locator("[data-wizard-step]").count() == 0
    context.close()


def test_the_blocked_next_states_its_reason_and_does_not_advance(browser, base_url):
    """§2′.8's gate, as a user sees it — which markup alone cannot establish.

    Phase 4 shipped a defect where a message was present in the DOM and invisible on the page, so
    a `<span>` full of the right words is not evidence that the Blocked state READS as blocked.
    Asserted here: the button is still on screen (not hidden — Blocked, not Inapplicable), the
    reason naming the missing series is legible at full strength and has a real bounding box, and
    clicking `[ Next → ]` does NOT reach the results screen.

    **The button is deliberately clickable** (review finding R1). It used to be `disabled` and the
    click was asserted to be a no-op; that turned out to trap the user — see
    `test_the_wizard_escapes_the_blocked_step_by_answering_no` below. The refusal now comes from
    the server, which re-renders step 2, so the user stays on the screen that says why rather than
    from a browser that swallows the click.

    The workspace is fresh, so nothing is loaded and every applicable slot is missing.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/data?mode=wizard", wait_until="networkidle")

    nxt = pg.get_by_role("button", name="Next")
    # Present and visible — Blocked, not Inapplicable. A hidden button is the wrong rendering.
    assert nxt.is_visible(), "the Blocked [ Next → ] must stay on screen"
    assert not nxt.is_disabled(), "the Blocked [ Next → ] must stay clickable (finding R1)"

    reason = pg.locator("[data-next-blocked-reason]")
    assert reason.is_visible(), "the reason must be on the page, not merely in the DOM"
    text = reason.inner_text()
    assert "Grid import T1" in text and "Grid export T1" in text, text
    # It has a real height — the phase-4 defect was an element present, sized zero and unreadable.
    box = reason.bounding_box()
    assert box is not None and box["height"] > 5, box

    # Not dimmed: the reason is the whole of the Blocked rendering now, so nothing here fades it.
    live = pg.evaluate(
        "() => getComputedStyle(document.querySelector('[data-next-blocked-reason]')).opacity"
    )
    assert float(live) > 0.9, f"the reason must NOT be dimmed (opacity {live})"
    assert pg.locator("[data-next-blocked] .blocked-control").count() == 0

    # Clicking submits, and the SERVER refuses: step 2 again, still blocked, never the results.
    nxt.click()
    pg.wait_for_load_state("networkidle")
    assert "/data" in pg.url, f"a blocked [ Next → ] must not advance, got {pg.url}"
    assert "/results" not in pg.url
    assert pg.locator("[data-next-blocked]").count() == 1, "still blocked, and still says why"
    context.close()


def test_the_wizard_escapes_the_blocked_step_by_answering_no(browser, base_url):
    """Review finding R1: the exact trap, walked end to end, and its exit.

    Only reachable through a browser, because it depends on `applySetupGating` running: the
    JavaScript hides the solar roster row the moment the radio flips, so the page stops asking for
    the series the footer is still blocked on. With a `disabled` `[ Next → ]` that state had no
    in-page exit at all — that button is the only submitter of the form the radio lives in,
    `[ Fetch history ]` is itself disabled with nothing staged, and `[ ← Previous ]` is a link that
    discards the answer and returns to the identical trap. Measured in Chromium at that point:
    `next_disabled=True`, solar row hidden, `fetch_disabled=True`.

    The path: a dataset of import + export T1 only, with `has_pv` left at appendix A's default of
    true, so step 2 renders blocked on the solar series alone. Flip the radio to No, click
    `[ Next → ]`, and the user must get out — the answer persisted and the block gone.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    _seed_reconstructable_dataset(workspace_id, has_pv=True)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/data?mode=wizard", wait_until="networkidle")

    # The trap's entry state: blocked on solar and nothing else, because import and export ARE
    # loaded. This is the assertion that keeps the test honest — a workspace blocked on everything
    # would not exercise the "answer that clears it" half.
    reason = pg.locator("[data-next-blocked-reason]").inner_text()
    assert "Solar production" in reason, reason
    assert "Grid import T1" not in reason, f"import is loaded and must not be named: {reason}"
    # And the escape hatch D8 claimed does not exist: nothing is staged, so a fetch is impossible.
    assert pg.locator("#ha-fetch-btn").is_disabled(), (
        "the precondition for the trap: [ Fetch history ] offers no way out either"
    )

    # The user does the obvious thing.
    pg.locator('input[name="setup_haspv"][value="0"]').check()
    # The roster stops asking for solar immediately (`applySetupGating`), which is the disagreement
    # the old D8 shrugged off — and, with a disabled button, the point of no return.
    pg.wait_for_timeout(100)

    nxt = pg.get_by_role("button", name="Next")
    assert not nxt.is_disabled(), "the answer that clears the block must be submittable"
    nxt.click()
    pg.wait_for_load_state("networkidle")

    # Out. The gate is met under the answer just given, so the wizard advances to step 3.
    assert "/results" in pg.url, f"the user must escape the blocked step, got {pg.url}"

    # And the answer stuck: back on step 2, no block, and the radio remembers "no".
    pg.goto(f"{base_url}/w/{workspace_id}/data?mode=wizard", wait_until="networkidle")
    assert pg.locator("[data-next-blocked]").count() == 0, "the block must be gone"
    assert pg.locator('input[name="setup_haspv"][value="0"]').is_checked()
    context.close()


# --- the CSV binding in the slot store (step 5 of the CSV-import brief, decision D-BIND) --------
#
# Decision D-BIND puts the per-slot `(upload_id, column, unit)` binding in browser `localStorage`,
# in the same `ha.slots.<workspace>` entry that already carries the HA statistic id, reconciled by
# the same `source_generation` number. That makes the whole mechanism a BROWSER behaviour: what the
# module does to localStorage at load, and what it puts on the wire at fetch. No route test can see
# either, which is why these live here rather than in `tests/test_slot_load.py`.
#
# The drawer cannot produce a binding yet — step 6 builds the file/column/unit controls and lifts the
# `PENDING_SOURCE_KEYS` filter that hides the radio. So the store is seeded directly, which is the
# same technique `_make_slot_pristine` above already uses and for the same reason: the store is the
# documented pre-fetch override, and a current-generation entry is authoritative over the server's
# committed choice. What is under test is the RESTORE-and-SEND half, which is the half step 5 built.

# A stand-in for our own ingest WebSocket, installed before any script runs. It records every frame
# the client sends and answers `done` with a plausible `result`, so `fetchHistory` runs to completion
# without a server round trip — the point is what the client SENDS, and asserting that against a real
# ingest endpoint would mean the test passing or failing on the server's validation instead.
#
# `window.__backendSent` is the observation. It is the only way to see `stagedBackendSlots`' output:
# the module is an IIFE with no exports, so there is nothing to call from the page.
_BACKEND_WS_STUB = """
window.__backendSent = [];
class FakeBackendSocket {
  constructor(url) {
    this.url = url;
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  send(raw) {
    const msg = JSON.parse(raw);
    window.__backendSent.push(msg);
    if (msg.type === 'done') {
      setTimeout(() => this.onmessage && this.onmessage({data: JSON.stringify(
        {type: 'result', dataset_id: 1, series: 1, warnings: [], grid: {}, generation: 1})}), 0);
    }
  }
  close() { if (this.onclose) this.onclose(); }
}
window.WebSocket = FakeBackendSocket;
"""


# A minimal well-formed wide CSV (§4.2a): a timestamp column plus two value columns, hourly,
# neither of them monotone (D-KIND rejects a column that only ever rises, so a ramp would be refused
# on parse and no upload would exist to bind to).
_WIDE_CSV = (
    "Tijdstip,Verbruik_T1,Zon\n"
    "01-01-2025 00:00:00,0.412,0.0\n"
    "01-01-2025 01:00:00,0.388,0.0\n"
    "01-01-2025 02:00:00,0.401,0.0\n"
    "01-01-2025 03:00:00,0.377,0.0\n"
)

# Three bindable columns, for the rebind-after-a-real-fetch regression below: it needs one column
# per slot, and the three slots it uses are the ones always visible regardless of the household's
# PV/battery answers (`solar_production` is `pv_only`). Longer than `_WIDE_CSV` because the fetch it
# feeds is a REAL one that persists a dataset rather than a stubbed socket that discards it — and
# each column is non-monotone, so none is refused on parse as a cumulative register (D-KIND).
_THREE_COLUMN_CSV = "Tijdstip,Verbruik_T1,Verbruik_T2,Teruglevering\n" + "".join(
    f"01-01-2025 {h:02d}:00:00,{0.4 + (h % 3) * 0.01:.3f},"
    f"{0.2 + (h % 4) * 0.01:.3f},{0.1 + (h % 5) * 0.01:.3f}\n"
    for h in range(24)
)


def _upload_csv(base_url: str, workspace_id: str, *, filename: str = "meterstanden_2025.csv",
                text: str = _WIDE_CSV, tz: str = "Europe/Amsterdam",
                delimiter: str | None = None) -> dict:
    """Upload one wide CSV through the real route and return its `_upload_json` dict.

    Done over HTTP rather than by writing the store row directly, because the id the drawer binds to
    has to be one the SERVER knows: since step 6 the client prunes a binding whose upload the list
    route does not report (the delete-cascade obligation D-BIND left to the browser), so a synthetic
    32-hex id is now cleared on load rather than restored. Uploading for real is also the only way to
    get a `columns` header for the column selector to offer.

    The multipart body is hand-built: `urllib` has no multipart encoder and the suite has no
    `requests`. `Sec-Fetch-Site` is sent because the route is same-site checked (`app/csrf.py`) —
    urllib sends neither that nor `Origin`, which the check deliberately lets through, but sending
    the header a browser would send keeps the test honest about what it is exercising.

    `delimiter=None` OMITS the part rather than sending `comma`, which is deliberate: it means every
    existing caller here exercises the route's absent-field default end to end over real HTTP, which
    is the shape an older client sends. Pass a name to send the part.
    """
    boundary = "----smokeboundary1234567890"
    delimiter_part = (
        ""
        if delimiter is None
        else (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="delimiter"\r\n\r\n{delimiter}\r\n'
        )
    )
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/csv\r\n\r\n{text}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="tz"\r\n\r\n{tz}\r\n'
        f"{delimiter_part}"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = Request(
        f"{base_url}/w/{workspace_id}/data/uploads",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    with urlopen(req) as r:
        assert r.status == 201, r.status
        return json.loads(r.read())["upload"]


def _seed_csv_binding(pg, base_url: str, workspace_id: str, *, gen_offset: int = 0,
                      slot: str = "grid_import_t1", upload_id: str = "a" * 32,
                      column: str = "Verbruik", unit: str = "kWh"):
    """Write a CSV-bound slot into `ha.slots.<workspace>` and reload so the module reads it.

    `gen_offset` shifts the stored generation relative to the server's: 0 means "current" (a live
    pre-fetch customization, which must be restored) and -1 means "stale" (a fetch has happened
    since, so the server is authoritative and the entry must be dropped). Both branches are
    behaviours the reconcile rule specifies, and only the browser can exercise them.

    `upload_id` defaults to a synthetic 32-hex id, and the choice matters more than it looks. Step 6's
    `pruneStaleCsvBindings` clears a binding whose upload the workspace does not list, so a synthetic
    id is a SECOND, independent reason for an entry to disappear. That is fine for a test whose subject
    is the reconcile rule (the stale-generation one: the entry is rejected before the prune could run,
    and the fetch button is the observation either way), but it is fatal to a test whose subject is the
    COMPLETENESS predicate — the entry would vanish whether or not the predicate still rejected it.

    So: a test that needs the entry restored, and equally a test that needs the predicate to be the
    only thing rejecting it, must pass a REAL id from `_upload_csv`.
    """
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    gen = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )
    slots = {slot: {"source": "csv_upload", "statId": "",
                    "uploadId": upload_id, "column": column, "unit": unit}}
    pg.evaluate(
        "([k, payload]) => localStorage.setItem(k, JSON.stringify(payload))",
        [f"ha.slots.{workspace_id}", {"gen": gen + gen_offset, "slots": slots}],
    )
    pg.reload(wait_until="networkidle")
    return gen


def test_a_stored_csv_binding_is_restored_and_sent_on_the_backend_load_message(browser, base_url):
    """The round trip step 5 built: store -> slotState -> the `backend_load` WS message.

    Three things are asserted, and they fail for three different reasons:

      * `[ Fetch history ]` is ENABLED after the reload. That needs the SOURCE to have survived, i.e.
        the seed loop to have restored the entry and `stagedBackendSlots` to have counted it.
      * the `backend_load` frame carries `binding` with all three fields in snake_case. That needs
        the three CSV FIELDS to have survived the seed loop and `stagedBackendSlots` to have attached
        them — a seed loop that copied only `source` and `statId` would pass the first assertion and
        fail this one, which is exactly the mutation worth catching.
      * the values are the ones stored, not defaults. A binding rebuilt from `|| ""` fallbacks would
        send empty strings and still have the right SHAPE.

    The upload is REAL as of step 6. It used to be a synthetic 32-hex id, which was enough while the
    client never asked the server what existed; now the drawer lists the workspace's uploads on load
    whenever a slot is CSV-bound, and prunes a binding whose file is not among them. A made-up id is
    therefore cleared before any of the three assertions can run.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.add_init_script(_BACKEND_WS_STUB)
    _seed_csv_binding(pg, base_url, workspace_id, upload_id=upload["id"],
                      column="Verbruik_T1", unit="Wh")

    fetch_btn = pg.locator("#ha-fetch-btn")
    assert not fetch_btn.is_disabled(), (
        "a restored CSV-bound slot must make a fetch possible — if this fails, the store entry was "
        "not restored into slotState at all"
    )

    fetch_btn.click()
    # The fetch is a chain of promises around the stubbed socket; wait for the frame rather than a
    # fixed delay.
    pg.wait_for_function(
        "() => (window.__backendSent || []).some(m => m.type === 'backend_load')", timeout=5000
    )
    sent = pg.evaluate("() => window.__backendSent")

    loads = [m for m in sent if m["type"] == "backend_load"]
    assert len(loads) == 1, sent
    msg = loads[0]
    assert msg["name"] == "grid_import_t1"
    assert msg["source"] == "csv_upload"
    # snake_case on the wire: `app/ingest_ws.py`'s protocol reads these keys, and the camelCase
    # spelling stops at the localStorage boundary.
    assert msg["binding"] == {
        "upload_id": upload["id"], "column": "Verbruik_T1", "unit": "Wh"
    }
    context.close()


def test_a_stale_generation_drops_a_binding_for_a_slot_the_server_did_not_commit(browser, base_url):
    """A stale entry does not RE-STAGE a slot: the source and statId still yield to the server.

    This is the half of the reconcile rule that survives the carry-forward exception (see the
    sibling test below and `ha_fetch.js`'s header). The workspace here has never been fetched, so
    NO slot has a committed server source; a mismatched-generation entry therefore has nothing to
    re-attach itself to and must leave the roster with nothing staged.

    Which is exactly why this test is no longer allowed to stand alone, and why its previous form
    was wrong. It used to be named `..._drops_the_stored_csv_binding` and was read as covering the
    whole rule. It could not: on a never-fetched workspace `source_generation` is 0 and no slot has
    a server source, so `[ Fetch history ]` is disabled because NOTHING IS STAGED — not because the
    binding was correctly dropped. Its own docstring claimed "a stale entry means a fetch has
    happened since it was written" while the fixture never made one happen. On a FETCHED workspace
    the same seeding left the button enabled and staged an empty `upload_id`, which is the bug the
    sibling test now covers. The assertion below is kept because it is true and worth pinning; the
    claim that it covers the stale case is what has been removed.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.add_init_script(_BACKEND_WS_STUB)
    # A generation that does not match the server's. `gen_offset=-1` is deliberately NOT used here:
    # this throwaway workspace has never been fetched, so its `source_generation` is 0 and -1 is
    # `loadSlotStore`'s own parse-error sentinel — which `ha_fetch.js` explicitly exempts from the
    # remove-stale-store branch (`slotStore.gen !== -1`), since removing a key it merely failed to
    # parse would destroy data it does not understand. Verified by running it: the entry survives at
    # -1. So the offset used is +1, a generation the server has not reached; what makes an entry apply
    # is EQUALITY with the server's, not being older than it, and either direction is a mismatch.
    _seed_csv_binding(pg, base_url, workspace_id, gen_offset=1)

    # Nothing staged: `source` came from the store and the store did not apply. The BINDING fields
    # of that entry are not carried either, because the carry is gated on the slot's SERVER source
    # being `csv_upload` and this server committed no source at all.
    assert pg.locator("#ha-fetch-btn").is_disabled(), (
        "a mismatched-generation entry must not re-stage a slot the server never committed"
    )
    context.close()


def _wait_for_fetch_reload(pg):
    """Wait out a real fetch, failing with the STATUS LINE rather than a bare timeout.

    `fetchHistory` ends success in a `window.location.reload()` 600ms after the "Imported N series"
    status, and ends failure by writing the reason into `#ha-fetch-status` and re-enabling the
    button. Waiting on the URL cannot tell those apart — the URL is the same either way — so this
    waits for the status to reach a terminal state and surfaces the failure text, which is the
    difference between a diagnosable assertion and a 20-second timeout with nothing in it.
    """
    pg.wait_for_function(
        "() => { const e = document.getElementById('ha-fetch-status');"
        "        return e && /Imported|✗/.test(e.textContent); }",
        timeout=20000,
    )
    status = pg.locator("#ha-fetch-status").inner_text()
    assert "✗" not in status, f"the fetch failed: {status}"
    # Then the reload it schedules.
    pg.wait_for_function(
        "() => document.readyState === 'complete' && "
        "     !/Imported/.test((document.getElementById('ha-fetch-status')||{}).textContent||'')",
        timeout=20000,
    )
    pg.wait_for_load_state("networkidle")


def test_rebinding_after_a_real_fetch_keeps_the_earlier_slots_bindings(browser, base_url):
    """The user's reported bug: bind two, fetch, bind a third, fetch again — and it failed.

    The failure was `Ingest rejected: backend_load binding for 'grid_import_t1' is missing
    'upload_id'`, naming an ALREADY-BOUND slot rather than the new one. A successful fetch bumps
    `source_generation` and reloads; the store, stamped at the old generation, then failed the
    `storeCurrent` check, so every slot fell into the seed loop's server-seeded branch — which
    restored `source: csv_upload` (the server did persist it) with an EMPTY binding, because under
    D-BIND the server has no binding to restore. `stagedBackendSlots` filters on the committed
    source, so it staged that slot and sent `upload_id: ""`, and the all-or-nothing reify took the
    newly-bound third slot down with it.

    This test deliberately does NOT use `_BACKEND_WS_STUB`. The stub is what left this uncovered:
    it persists nothing and never bumps the generation, so no stubbed test can ever reach the state
    "committed server source is `csv_upload` AND the local store is stale". It answers `done` with a
    plausible `result` and the page then reloads against a server whose generation is still 0, so
    the store still matches and the broken branch is never taken. The real ingest WebSocket is used
    instead: the first fetch genuinely persists a dataset, genuinely bumps the generation, and the
    reload genuinely re-renders the roster from the server's committed sources.

    The fetch window is `historyWindow()`'s trailing `HISTORY_DAYS` (730) from now, and the fixture
    CSV is dated 2025-01-01, so the data is inside the window — a fetch that loaded nothing would
    fail the reify and the test would not reach its assertions.

    What is NOT covered here: the HA arm. This fetch is backend-load-only, which is the sequence the
    user reported and the only one reachable without a Home Assistant to talk to. A mixed HA+CSV
    fetch takes the same seed loop and the same `stagedBackendSlots`, so the mechanism is shared,
    but that combination is not exercised.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    _upload_csv(base_url, workspace_id, text=_THREE_COLUMN_CSV)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    # Only the frames are observed; the socket itself is the real one. Wrapping `send` rather than
    # replacing `WebSocket` is what keeps the round trip real.
    pg.add_init_script("""
      window.__backendSent = [];
      const _send = WebSocket.prototype.send;
      WebSocket.prototype.send = function (raw) {
        try { window.__backendSent.push(JSON.parse(raw)); } catch (e) { /* binary */ }
        return _send.call(this, raw);
      };
    """)

    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    gen_before = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )

    # Steps 1-2: bind two slots.
    _bind_slot_via_drawer(pg, "grid_import_t1", "Verbruik_T1")
    _bind_slot_via_drawer(pg, "grid_export_t1", "Teruglevering")

    # Step 3: fetch for real. Success ends in a full page reload, so wait for that rather than for
    # the frame — the reload is the event that puts the client in the broken state.
    pg.locator("#ha-fetch-btn").click()
    _wait_for_fetch_reload(pg)

    gen_after = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )
    assert gen_after > gen_before, (
        "the first fetch must genuinely persist and bump the generation — otherwise this test is "
        f"not in the state it claims to be testing (before={gen_before}, after={gen_after})"
    )

    # The reload cleared the recorder, so re-arm it for the second fetch.
    pg.evaluate("() => { window.__backendSent = []; }")

    # Step 4: bind a third slot, on a page whose store is now stale.
    _bind_slot_via_drawer(pg, "grid_import_t2", "Verbruik_T2")

    # Step 5: fetch again. This is where it used to fail.
    pg.locator("#ha-fetch-btn").click()
    pg.wait_for_function(
        "() => (window.__backendSent || []).filter(m => m.type === 'backend_load').length >= 3",
        timeout=20000,
    )
    loads = [m for m in pg.evaluate("() => window.__backendSent") if m["type"] == "backend_load"]

    by_slot = {m["name"]: m for m in loads}
    assert set(by_slot) == {"grid_import_t1", "grid_export_t1", "grid_import_t2"}, sorted(by_slot)
    for name, msg in by_slot.items():
        binding = msg.get("binding") or {}
        # The assertion the bug fails. `upload_id` empty is what `app/ingest_ws.py` rejects, and it
        # is the two ALREADY-FETCHED slots that lose it, not the newly-bound one.
        assert binding.get("upload_id"), (
            f"{name} must still carry its upload id on the second fetch; got {binding!r}"
        )
        assert binding.get("column"), f"{name} must still carry its column; got {binding!r}"

    # And the reify actually succeeds end to end: a second reload rather than an error line.
    _wait_for_fetch_reload(pg)
    context.close()


def test_a_stale_binding_is_not_carried_onto_a_slot_the_server_committed_elsewhere(
    browser, base_url
):
    """The GUARD on the carry: `serverSource === CSV_SOURCE_KEY` in `ha_fetch.js`'s seed loop.

    The carry-forward exception exists because the server has no copy of a CSV binding (D-BIND), so
    dropping a stale store's binding fields destroys the only copy. But it is an exception to the
    reconcile rule, not a repeal of it, and the guard is what keeps the difference: a binding is
    re-attached only to a slot the SERVER ITSELF committed to `csv_upload`. A slot the server has
    since filled from a DIFFERENT source keeps the server's choice, and the orphaned binding goes
    with it — otherwise the carry would be a blanket override of the reconcile rule, re-staging
    browser-local state onto slots the server disagrees with.

    Found unpinned by mutation testing: with the guard removed
    (`var carry = carriedBindings[name] || null;`) the whole smoke suite still passed. The sibling
    `test_a_stale_generation_drops_a_binding_for_a_slot_the_server_did_not_commit` does not reach it
    — its workspace has never been fetched, so `serverSource` is empty AND the store's own generation
    check already rejects the entry, and removing the guard changes nothing there.

    What this needs and how it is built:

      * a FETCHED workspace, so `source_generation` has moved and the store is genuinely stale. That
        means a REAL fetch (not `_BACKEND_WS_STUB`, which persists nothing and never bumps the
        generation), for the reason the sibling test's docstring gives at length.
      * a slot whose SERVER-committed source is a backend source other than `csv_upload`. That slot
        is `price_spot` with `energy_charts`: `CsvSource.available_for` excludes `price_spot`
        (D-PRICE) and `EnergyChartsSource.available_for` allows only it, so the two sources are
        disjoint by construction and this is the one pair reachable without a live Home Assistant.
        (An energy slot committed to `home_assistant` would be the other shape of this test; the HA
        stub answers `list_statistic_ids` but not `statistics_during_period`, so no HA slot can be
        made to reify here. That arm is not covered.)
      * a stale store holding a COMPLETE `csv_upload` binding for that same slot, and for NO other
        slot — `carried` is a single flag over the whole loop, so an entry for the CSV slot would
        set it and mask the difference this test is looking for.

    The observation is the store rewrite, which is the surface the carry actually changes here.
    `stagedBackendSlots` attaches a `binding` only when the slot's source is `csv_upload`, and under
    the mutation `price_spot`'s source still comes from the server (`energy_charts`) — so the wire
    frame is identical either way and cannot discriminate. What the carry does change is the two
    bookkeeping writes beside it: `locallyCustomized[name] = true` and `carried = true`, which turn
    the stale store's REMOVAL into a REWRITE at the new generation. So:

      * guarded — nothing is carried, `carried` stays false, and the stale store is removed outright.
      * mutated — `price_spot` is carried, marked locally-customized, and written back. Its source is
        `energy_charts` (the server's, correctly) so `saveSlotStore`'s else-branch stores the bare
        key — a browser-local claim on a slot the server has already decided, resurrected from a
        store the reconcile rule had thrown away.

    Both are asserted: the store is gone, and the stale upload id is nowhere in `localStorage`.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id, text=_THREE_COLUMN_CSV)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.goto(f"{base_url}/w/{workspace_id}/data", wait_until="networkidle")
    gen_before = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )

    # One CSV slot so the fetch has an energy series to reify, plus `price_spot` on `energy_charts`
    # — the slot whose committed source this test needs to be something OTHER than `csv_upload`.
    _bind_slot_via_drawer(pg, "grid_import_t1", "Verbruik_T1")
    pg.locator("#slot-roster .slot-source-btn[data-slot='price_spot']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='energy_charts']").check()
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    pg.locator("#ha-fetch-btn").click()
    _wait_for_fetch_reload(pg)

    gen_after = pg.evaluate(
        "() => JSON.parse(document.getElementById('source-generation').textContent)"
    )
    assert gen_after > gen_before, (
        "the fetch must genuinely persist and bump the generation, or the store below would not be "
        f"stale and this test would not be in the state it claims (before={gen_before}, "
        f"after={gen_after})"
    )
    # The premise the guard is read against: the server really did commit `price_spot` to
    # `energy_charts`. Asserted rather than assumed — if this attribute were empty or `csv_upload`,
    # the test below would pass for a reason that has nothing to do with the guard.
    committed = pg.get_attribute(
        "#slot-roster .slot-source-btn[data-slot='price_spot']", "data-slot-source"
    )
    assert committed == "energy_charts", (
        f"price_spot's committed server source must be energy_charts, got {committed!r}"
    )

    # Now the stale store: a COMPLETE binding (a real upload id, so `pruneStaleCsvBindings` is not
    # what removes it) claiming `price_spot` for `csv_upload`, stamped at the PRE-fetch generation.
    # Only this slot, so `carried` reflects this slot alone.
    pg.evaluate(
        """([k, g, uid]) => localStorage.setItem(k, JSON.stringify({
               gen: g,
               slots: {price_spot: {source: 'csv_upload', statId: '',
                                    uploadId: uid, column: 'Verbruik_T1', unit: 'kWh'}}}))""",
        [f"ha.slots.{workspace_id}", gen_before, upload["id"]],
    )
    pg.reload(wait_until="networkidle")

    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert stored in (None, ""), (
        "a stale binding must NOT be carried onto a slot whose committed source is not csv_upload: "
        "nothing was carried, so the stale store must have been removed rather than rewritten. "
        f"Got {stored!r} — the carry guard (serverSource === CSV_SOURCE_KEY) is not holding."
    )
    assert upload["id"] not in (stored or ""), (
        f"the orphaned upload id must go with the binding, not survive in the store: {stored!r}"
    )

    # The row still reads as the server's choice, not as a CSV-bound slot.
    label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='price_spot'] .slot-source-label"
    ).inner_text()
    assert "Upload CSV" not in label, (
        f"price_spot must keep the server's committed source in the row label, got {label!r}"
    )
    context.close()


def test_a_partial_csv_binding_is_not_persisted_by_confirm(browser, base_url):
    """`saveSlotStore` stores a CSV slot only once it has BOTH a file and a column.

    Why this matters more than tidiness: a restored partial binding stages a `backend_load` slot with
    an empty `upload_id`, and under the all-or-nothing reify contract that one slot fails the WHOLE
    fetch, HA slots included. So "would this be fetchable if restored?" is the gate, and it is
    asserted by writing a partial entry and confirming an UNRELATED slot — which triggers a save that
    rewrites the whole store from `slotState`.

    The upload is REAL so that `saveSlotStore`'s gate is the only thing that can drop the entry. With
    a synthetic id, `pruneStaleCsvBindings` clears the slot on the eager list-on-load before Confirm
    ever runs, and the final assertion holds whether or not `csvBindingComplete` still requires a
    column — the test would pass for the wrong reason. See the READ-side test below for the same note.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.add_init_script(_BACKEND_WS_STUB)
    # A CSV entry with a file but NO column, restored at the current generation. It is tracked as
    # locally-customized, so the next save re-writes it — or drops it, which is the behaviour here.
    # The file is one the workspace lists, so the prune leaves it for the save gate to judge.
    _seed_csv_binding(pg, base_url, workspace_id, upload_id=upload["id"], column="")

    # Confirm a different slot, which is what makes saveSlotStore run over the whole store.
    pg.locator("#slot-roster .slot-source-btn[data-slot='price_spot']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='energy_charts']").check()
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert stored is not None and "energy_charts" in stored, stored
    # The incomplete CSV entry is gone rather than written back.
    assert "csv_upload" not in stored, (
        f"a binding with no column is not fetchable and must not be persisted: {stored}"
    )
    context.close()


def test_a_partial_csv_binding_already_in_the_store_is_not_restored(browser, base_url):
    """The READ side of the same rule: `usableStoreEntry` drops an incomplete entry on the way in.

    The test above only covers what a save WRITES, which leaves the case that matters more: an
    incomplete entry that is ALREADY in the store when the page loads, put there by a hand edit or by
    an older build whose gate differed.

    The upload is REAL, and that is load-bearing rather than incidental. With the synthetic 32-hex id
    `_seed_csv_binding` defaults to, a weakened `usableStoreEntry` restores the partial entry and then
    `pruneStaleCsvBindings` clears it on the eager list-on-load — the id is not in the workspace's
    list — so the assertion below would pass with the predicate bypassed entirely. Two independent
    mechanisms can remove the entry, and asserting only that it is GONE cannot tell which one did it.
    Binding to a file the server does list disarms the prune, which leaves the completeness gate as
    the only thing that can reject the entry. (Verified: weakening `csvBindingComplete` to require
    only a file fails this test with a real id and passes with a synthetic one.)

    Before `usableStoreEntry` the seed loop copied `uploadId` and
    `column` across verbatim, so such an entry was restored into `slotState`, counted by
    `stagedBackendSlots` (which filters only on the source being a backend key) and sent as
    `binding: {upload_id: …, column: "", unit: "kWh"}`. The server's shape check rejects the empty
    column, and under the all-or-nothing reify contract that failure takes the WHOLE fetch down —
    every HA slot with it — so the cost of restoring half a binding is not confined to the CSV slot.

    Asserted through `[ Fetch history ]` being disabled rather than by inspecting the store: what has
    to be false is that the slot is STAGED. This throwaway workspace has no other staged slot, so the
    button's state is a direct read of whether the entry survived, and it is the same observation the
    round-trip test above makes in the positive direction.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.add_init_script(_BACKEND_WS_STUB)
    # A file but no column, at the CURRENT generation — so the reconcile rule says "apply this", and
    # only the completeness gate can reject it. (The stale-generation path is a different test.) The
    # file is one the server lists, so the prune cannot be what removes the entry — see the docstring.
    _seed_csv_binding(pg, base_url, workspace_id, upload_id=upload["id"], column="")

    assert pg.locator("#ha-fetch-btn").is_disabled(), (
        "an incomplete stored binding must not leave a fetchable slot behind"
    )

    # And the slot did not merely fail to stage: it fell back to the server's committed source, which
    # for this fresh workspace is none at all. Nothing anywhere claims the slot is bound to a CSV.
    assert pg.evaluate(
        "() => (document.querySelector(\"#slot-roster .slot-source-btn[data-slot='grid_import_t1']\")"
        " || {}).textContent || ''"
    ).find("Upload CSV") == -1
    context.close()


# --- the CSV drawer UI (step 6 of the CSV-import brief) -----------------------------------------
#
# Step 5's tests above seed `localStorage` directly, because the drawer could not yet PRODUCE a
# binding — the radio was filtered out and there were no file/column/unit controls. Step 6 built
# them, so these drive the real UI: pick the radio, choose a file and a column, press Confirm, and
# check what reached the store and the roster row. Everything here is a browser behaviour (a modal,
# a fetch to the uploads routes, `localStorage`), which is why none of it can live at route level.
#
# Each test creates its own workspace (`_workspace_url`) so its uploads cannot be seen by another's:
# uploads are per-workspace (§5.2) and the file list is what several of these assert on.


def _open_csv_drawer(pg, base_url: str, workspace_id: str, slot: str = "grid_import_t1"):
    """Open `slot`'s drawer with the "Upload CSV" radio selected.

    The slot is made pristine first so nothing is pre-committed; the radio is then CHECKED rather
    than assumed, because `defaultSourceFor` prefers Home Assistant and every energy slot offers it.
    """
    _make_slot_pristine(pg, base_url, workspace_id, slot=slot)
    pg.locator(f"#slot-roster .slot-source-btn[data-slot='{slot}']").click()
    radio = pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']")
    expect(radio).to_have_count(1)
    radio.check()
    return radio


def test_the_csv_radio_is_selectable_and_reveals_its_controls_only_when_selected(browser, base_url):
    """The radio is live (step 4's pending stub is gone) and its controls are conditional.

    Two halves, and the second is the one with a trap in it. `csv_upload` is a `backend_load`
    source, exactly like `energy_charts` — so a controls block toggled on the source KIND would
    appear for `energy_charts` too. `onSelectSource` keys on the source KEY for this block, and this
    asserts that: picking a different source must hide it again.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()

    _make_slot_pristine(pg, base_url, workspace_id)
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()

    # The radio exists, is enabled, and is NOT the one selected by default (HA sorts first).
    radio = pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']")
    expect(radio).to_have_count(1)
    assert not radio.is_disabled(), "the pending stub is gone; the CSV radio must be selectable"
    assert not radio.is_checked()
    assert pg.locator("#drawer-csv-binding").is_hidden(), (
        "the binding controls must not show while another source is selected"
    )

    radio.check()
    expect(pg.locator("#drawer-csv-binding")).to_be_visible()
    expect(pg.locator("#drawer-csv-upload-btn")).to_be_visible()

    # Another source hides them again — the toggle is on the key, not the kind.
    pg.locator("#source-drawer input[name='drawer-source'][value='home_assistant']").check()
    assert pg.locator("#drawer-csv-binding").is_hidden()
    context.close()


def test_confirm_is_blocked_until_a_file_and_a_column_are_chosen(browser, base_url):
    """§2.2: "Confirm is enabled once a file and a column are chosen."

    This gate is what replaced the `PENDING_SOURCE_KEYS` filter that used to hide the radio, and it
    is load-bearing rather than cosmetic: an empty binding staged into a `backend_load` slot makes
    `CsvSource` raise, and the reify contract is all-or-nothing, so that one slot fails the whole
    fetch — every Home Assistant slot with it.

    The FILE is staged by default (there is one, and it is the obvious choice); the COLUMN is not,
    deliberately — nothing about a column says which series it is (§4.1), so pre-picking one would
    present an arbitrary guess as an answer. So the state right after checking the radio is exactly
    "file yes, column no", which is the state the gate has to catch.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    _open_csv_drawer(pg, base_url, workspace_id)

    expect(pg.locator("#drawer-csv-file")).to_have_value(upload["id"])
    expect(pg.locator("#drawer-csv-column")).to_have_value("")
    assert pg.locator("#drawer-confirm").is_disabled(), (
        "a file with no column is an incomplete binding and must not be confirmable"
    )

    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    expect(pg.locator("#drawer-confirm")).to_be_enabled()

    # Going back to the placeholder re-blocks it: the gate is live, not a one-way latch.
    pg.locator("#drawer-csv-column").select_option("")
    assert pg.locator("#drawer-confirm").is_disabled()
    context.close()


def test_the_column_selector_skips_the_timestamp_and_offers_names(browser, base_url):
    """`columns[0]` is the timestamp and is the one name `csv_wide` does not uniquify.

    The selector is built from `columns.slice(1)`, and the binding carries the NAME. Both matter: a
    header whose first VALUE column repeats the timestamp's name makes `columns.indexOf(name)`
    return 0, so an index-derived binding would silently bind the slot to the timestamp column.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    # A header whose value column duplicates the timestamp name — the exact index trap.
    _upload_csv(base_url, workspace_id, filename="dup.csv", text=(
        "Tijdstip,Tijdstip,Zon\n"
        "01-01-2025 00:00:00,0.4,0.0\n"
        "01-01-2025 01:00:00,0.3,0.0\n"
        "01-01-2025 02:00:00,0.5,0.0\n"
    ))

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    _open_csv_drawer(pg, base_url, workspace_id)

    # The selects are populated by the LIST route, so wait for the fetch rather than assuming it
    # has landed by the time the radio's `change` handler returns.
    expect(pg.locator("#drawer-csv-file")).to_contain_text("dup.csv", timeout=5000)

    # Placeholder + exactly the two VALUE columns. Three entries would mean the timestamp leaked in.
    values = pg.evaluate(
        "() => Array.from(document.getElementById('drawer-csv-column').options).map(o => o.value)"
    )
    assert values == ["", "Tijdstip", "Zon"], values
    context.close()


def test_a_cumulative_column_gets_small_print_and_confirm_stays_enabled(browser, base_url):
    """The whole behaviour change, from the user's side: a warning, not a block.

    A non-decreasing column used to fail the fetch with a rejection. It now gets one line of small
    print beside the column picker and nothing else — because the detector cannot tell a meter
    register from a column that merely rises throughout the file, and a morning-only solar export is
    exactly that shape (csv_wide.py's note at MONOTONIC_MIN_SAMPLES). Blocking cost a user with valid
    data their whole binding and gave them no way round it.

    Four claims, and the third is the one that would silently regress: the line appears for the
    suspect column, it does NOT appear for the ordinary column in the same file, Confirm is ENABLED
    while the line is showing, and switching between the two columns clears and re-shows it (so it is
    driven by the selection rather than latched on the first suspect column seen).
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    # `Meterstand` rises for 24 hours; `Verbruik` saws. 24 rows clears MONOTONIC_MIN_SAMPLES (12).
    _upload_csv(base_url, workspace_id, filename="meterstand.csv", text=(
        "Tijdstip,Meterstand,Verbruik\n"
        + "".join(
            f"01-01-2025 {i:02d}:00:00,{14200 + i * 0.5:.1f},{0.3 + 0.1 * (i % 3):.1f}\n"
            for i in range(24)
        )
    ))

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    _open_csv_drawer(pg, base_url, workspace_id)
    expect(pg.locator("#drawer-csv-file")).to_contain_text("meterstand.csv", timeout=5000)

    warning = pg.locator("#drawer-csv-cumulative")
    # Nothing selected yet, so nothing to warn about.
    expect(warning).to_be_hidden()

    pg.locator("#drawer-csv-column").select_option("Meterstand")
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("never decreases")
    # The point of the change: the user can proceed.
    expect(pg.locator("#drawer-confirm")).to_be_enabled()

    # The ordinary column in the same file gets no line — the verdict is per column, not per file.
    pg.locator("#drawer-csv-column").select_option("Verbruik")
    expect(warning).to_be_hidden()
    expect(pg.locator("#drawer-confirm")).to_be_enabled()

    # And back, so the line is recomputed from the selection rather than shown once and latched.
    pg.locator("#drawer-csv-column").select_option("Meterstand")
    expect(warning).to_be_visible()

    # Confirm really does commit, warning and all — the binding reaches the store.
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)
    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert "Meterstand" in (stored or ""), stored
    context.close()


def test_confirm_stages_the_binding_into_localstorage_and_labels_the_row(browser, base_url):
    """The whole drawer flow: pick, choose, Confirm — then the store and the row label.

    §2.2's row label is "Upload CSV · meterstanden_2025.csv · Verbruik_T1", and building it needs an
    id→filename map, because `slotState` holds only the upload id. The store, by contrast, holds the
    ID — a filename is not an identity and two exports may share one.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    _open_csv_drawer(pg, base_url, workspace_id)

    pg.locator("#drawer-csv-column").select_option("Zon")
    pg.locator("#source-drawer input[name='drawer-csv-unit'][value='Wh']").check()
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    stored = json.loads(pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')"))
    entry = stored["slots"]["grid_import_t1"]
    assert entry["source"] == "csv_upload"
    assert entry["uploadId"] == upload["id"]
    assert entry["column"] == "Zon"
    assert entry["unit"] == "Wh"

    label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='grid_import_t1'] .slot-source-label"
    )
    expect(label).to_have_text(f"Upload CSV · {upload['filename']} · Zon")

    # And it survives a plain refresh, which is what the store exists for. The label needs the
    # uploads listed again after the reload, so this also covers the eager list on load.
    pg.reload(wait_until="networkidle")
    expect(label).to_have_text(f"Upload CSV · {upload['filename']} · Zon", timeout=5000)
    context.close()


def test_an_upload_survives_cancel_but_the_binding_does_not(browser, base_url):
    """§2.2's one exception to the transactional drawer, asserted in both directions.

    An upload is a side effect on state SHARED across slots, exactly as a tested Home Assistant
    connection is, so Cancel does not undo it. The per-slot BINDING is not shared and is discarded
    like every other staged choice.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    _open_csv_drawer(pg, base_url, workspace_id)

    # No files yet: the drawer says so instead of showing two empty dropdowns.
    expect(pg.locator("#drawer-csv-no-files")).to_be_visible()

    # Upload from inside the dialog, the way a user does — through the real file input.
    pg.locator("#drawer-csv-upload-btn").click()
    expect(pg.locator("#csv-upload-dialog")).to_be_visible()
    pg.locator("#csv-upload-input").set_input_files({
        "name": "zonnepanelen_2025.csv", "mimeType": "text/csv",
        "buffer": _WIDE_CSV.encode("utf-8"),
    })
    expect(pg.locator("#csv-upload-status")).to_contain_text("Uploaded", timeout=5000)
    expect(pg.locator("#csv-upload-list")).to_contain_text("zonnepanelen_2025.csv")
    pg.evaluate("() => document.getElementById('csv-upload-dialog').close()")

    # The new file reached the drawer's selector without closing anything.
    expect(pg.locator("#drawer-csv-no-files")).to_be_hidden()
    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    expect(pg.locator("#drawer-confirm")).to_be_enabled()

    # Cancel. The BINDING is gone — nothing was committed and nothing stored.
    pg.locator("#drawer-cancel").click()
    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert "csv_upload" not in (stored or ""), stored
    label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='grid_import_t1'] .slot-source-label"
    )
    expect(label).to_have_text("Choose source…")

    # The UPLOAD is not: the server still has it, and re-opening the drawer offers it again.
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    expect(pg.locator("#drawer-csv-file")).to_contain_text("zonnepanelen_2025.csv", timeout=5000)
    context.close()


def test_removing_a_file_clears_the_slots_bound_to_it_and_says_which(browser, base_url):
    """The delete cascade, which under D-BIND can only run client-side.

    §2.2: "Removing a file that a slot still uses clears that slot's binding and returns it to
    'Choose source…', reported when the removal is confirmed." The server holds no binding, so it
    cannot cascade — the browser that holds it does, and this asserts all three parts: the binding
    is cleared, the row goes back to "Choose source…", and the user is told which series it hit.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.on("dialog", lambda d: d.accept())   # the [ remove ] confirmation
    _open_csv_drawer(pg, base_url, workspace_id)
    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='grid_import_t1'] .slot-source-label"
    )
    expect(label).to_contain_text(upload["filename"])

    # Remove the file from the dialog.
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    pg.locator("#drawer-csv-upload-btn").click()
    expect(pg.locator("#csv-upload-list")).to_contain_text(upload["filename"])
    pg.locator("#csv-upload-list button").first.click()

    # Reported: the status names the file AND the series that lost their binding. The roster's own
    # label for the slot is used, never the internal series name (§4.1).
    expect(pg.locator("#csv-upload-status")).to_contain_text("Removed", timeout=5000)
    expect(pg.locator("#csv-upload-status")).to_contain_text("Grid import T1")

    pg.evaluate("() => document.getElementById('csv-upload-dialog').close()")
    pg.locator("#drawer-cancel").click()

    # Cleared: the row is back to "Choose source…" and the store no longer holds the binding.
    expect(label).to_have_text("Choose source…")
    stored = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert upload["id"] not in (stored or ""), stored
    context.close()


def test_a_rejected_upload_is_reported_in_the_dialog_and_is_recoverable(browser, base_url):
    """§2.2: validation happens at upload and is panel-local, not run-fatal (§3.2).

    The rejection driven here is a 12-hour clock in the timestamp column, which is both the mistake
    a hand-edited Dutch export most often carries and the one the dialog's own bullet warns about.
    (A cumulative column is refused on COLUMN SELECTION rather than at upload — `column_frame`, not
    `parse_and_summarise` — so it is deliberately not the case under test here.)

    Three things are asserted: the message arrives through this step's `code` table rather than as
    the server's English sentence alone and carries the offending ROW, the dialog stays open with
    nothing stored, and the same input takes a good file straight afterwards.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    _open_csv_drawer(pg, base_url, workspace_id)
    pg.locator("#drawer-csv-upload-btn").click()

    twelve_hour = (
        "Tijdstip,Verbruik\n"
        "01-01-2025 00:00:00,0.4\n"
        "01-01-2025 06:00:00 PM,0.3\n"
    )
    pg.locator("#csv-upload-input").set_input_files({
        "name": "fout.csv", "mimeType": "text/csv", "buffer": twelve_hour.encode("utf-8"),
    })
    err = pg.locator("#csv-upload-error")
    expect(err).to_be_visible(timeout=5000)
    # The TRANSLATED wording from this step's `code` table, not the server's English message. The
    # two are deliberately distinguishable: the table's sentence opens "A timestamp could not be
    # read", the parser's opens "Row 3: could not read '…'". Asserting on a phrase both carry
    # ("24-hour clock") would pass with the table bypassed entirely.
    expect(err).to_contain_text("A timestamp could not be read")
    # The server's own message IS appended for this code, because it names the offending cell and
    # re-deriving that here would mean parsing English prose.
    expect(err).to_contain_text("06:00:00 PM")
    # The row travels separately from the message, so a code whose message is not shown still names
    # where the problem is. Row 3 counts the header as row 1, which is what the user's editor shows.
    expect(err).to_contain_text("row 3")
    expect(pg.locator("#csv-upload-dialog")).to_be_visible()
    # Nothing was stored: a rejected upload writes no row and no file.
    expect(pg.locator("#csv-upload-empty")).to_be_visible()

    # Recoverable: the same input takes a good file straight afterwards.
    pg.locator("#csv-upload-input").set_input_files({
        "name": "goed.csv", "mimeType": "text/csv", "buffer": _WIDE_CSV.encode("utf-8"),
    })
    expect(pg.locator("#csv-upload-status")).to_contain_text("Uploaded", timeout=5000)
    expect(pg.locator("#csv-upload-list")).to_contain_text("goed.csv")
    context.close()


def test_the_delimiter_radio_is_offered_and_its_answer_reaches_the_upload(browser, base_url):
    """§2.2: the field separator is answered per file, in the dialog, beside the zone.

    The whole path in one pass: the three radios exist with comma pre-checked, picking semicolon and
    choosing a semicolon-separated file uploads successfully, and the stored file is the tokenized
    one — two value columns, not none. That last assertion distinguishes "the answer was sent" from
    "the answer was ignored": read as comma, this file's header names a single column and the route
    would have refused it as `too_few_columns`.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    _open_csv_drawer(pg, base_url, workspace_id)
    pg.locator("#drawer-csv-upload-btn").click()
    expect(pg.locator("#csv-upload-dialog")).to_be_visible()

    radios = pg.locator("input[name=csv-upload-delimiter]")
    expect(radios).to_have_count(3)
    # Comma is pre-checked: the commonest export, and what a file uploaded before this option
    # existed was read as.
    expect(pg.locator("input[name=csv-upload-delimiter][value=comma]")).to_be_checked()
    for value in ("semicolon", "tab"):
        expect(pg.locator(f"input[name=csv-upload-delimiter][value={value}]")).to_have_count(1)

    pg.locator("input[name=csv-upload-delimiter][value=semicolon]").check()
    semicolon_csv = _WIDE_CSV.replace(",", ";")
    pg.locator("#csv-upload-input").set_input_files({
        "name": "puntkomma.csv", "mimeType": "text/csv",
        "buffer": semicolon_csv.encode("utf-8"),
    })
    expect(pg.locator("#csv-upload-status")).to_contain_text("Uploaded", timeout=5000)
    expect(pg.locator("#csv-upload-list")).to_contain_text("puntkomma.csv")
    # Tokenized under the declared separator: the list counts VALUE columns, so a file whose header
    # split into three fields shows 2. Read as comma it would have been refused outright.
    expect(pg.locator("#csv-upload-list")).to_contain_text("2 columns")
    context.close()


def test_a_failed_uploads_list_leaves_every_binding_alone(browser, base_url):
    """A network error listing the uploads must not be read as "the files are gone".

    The mutation this exists to catch is two lines: adding `csvUploads = [];
    pruneStaleCsvBindings();` to `refreshCsvUploads`' `.catch`. That reads plausible — the cache is
    stale, so clear it — and it passes every other test in this file, because no other test ever makes
    the LIST route fail. Its symptom is the worst one the drawer has: every CSV binding in the
    workspace silently disappears on a page load that happened to lose the request, and the rows go
    back to "Choose source…" with nothing to tell the user why.

    The two are only distinguishable when the list FAILS, because `pruneStaleCsvBindings` decides on
    `csvUploadById`, i.e. on the cache — so a cache emptied by an error is indistinguishable, from the
    prune's side, from a workspace whose files were all deleted. The rule the `.catch` encodes is that
    an unanswered question is not the answer "none": `csvUploadsLoaded` stays false, the cache is left
    as it was, and the prune is not consulted at all.

    The failure is injected with `page.route(...).abort()` rather than a 500 because it exercises the
    same branch (the fetch promise rejects) while also covering the case where nothing HTTP-shaped
    comes back at all — a dropped connection is the realistic version of this. It is installed after
    the binding is committed and before the reload, so what is under test is the eager list-on-load,
    which is the one that runs without the user doing anything.

    Asserted on both surfaces the binding shows on, because they fail separately: the ROW LABEL is
    rendered from `slotState`, and `localStorage` is what survives the next reload. A prune would
    clear both — the row would read "Choose source…" and the store would lose the entry.

    What the label reads AFTER the failed list is "Upload CSV · (file no longer available) ·
    Verbruik_T1", and that is correct rather than a partial regression: per decision 8 the filename
    comes from the cached list, so with no list the placeholder is the honest rendering — the row still
    says the slot is CSV-bound to that column. The distinction the assertion has to make is
    "unknown filename" versus "not bound at all", so it pins the SOURCE and the COLUMN and explicitly
    rejects "Choose source…"; pinning the filename would pin the cache, which the failure emptied by
    design.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()

    # Bind the slot for real through the drawer, so what the reload restores is what Confirm wrote.
    _open_csv_drawer(pg, base_url, workspace_id)
    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='grid_import_t1'] .slot-source-label"
    )
    expected_label = f"Upload CSV · {upload['filename']} · Verbruik_T1"
    expect(label).to_have_text(expected_label)
    before = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert upload["id"] in (before or ""), before

    # Now break the LIST route only — the page itself must still load. The POST to the same path is
    # not exercised here, and `route` matches on URL, so the handler checks the method and lets
    # anything else through rather than silently breaking uploads too.
    listed = {"n": 0}

    def _fail_list(route, request):
        if request.method == "GET":
            listed["n"] += 1
            route.abort("connectionfailed")
        else:
            route.continue_()

    pg.route("**/data/uploads", _fail_list)
    pg.reload(wait_until="networkidle")

    # The eager list ran (the slot arrived CSV-bound) and failed. Without this the rest of the test
    # would pass vacuously on a page that never asked.
    assert listed["n"] >= 1, "the eager list-on-load did not run, so nothing was under test"

    # The row still says the slot is CSV-bound to that column, rendered from `slotState` — which the
    # failed list must not have touched. A prune clears the slot WHOLE, so under the mutation this
    # reads "Choose source…" instead.
    expect(label).to_contain_text("Upload CSV")
    expect(label).to_contain_text("Verbruik_T1")
    assert "Choose source" not in label.text_content(), (
        "a failed uploads LIST must not return the row to the unbound state"
    )

    # And the store is byte-for-byte what it was. This is the assertion that matters most: the label
    # could in principle recover on a later successful list, but a store the prune has rewritten is
    # gone for good.
    after = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert after == before, (
        "a failed uploads LIST must not rewrite the slot store — every CSV binding in the workspace "
        f"is at stake.\nbefore: {before}\nafter:  {after}"
    )

    # A later successful list is still possible: the cache was left UNKNOWN rather than empty, so the
    # drawer asks again instead of trusting an empty answer. (This is the `csvUploadsLoaded` half of
    # the same rule.)
    pg.unroute("**/data/uploads", _fail_list)
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    expect(pg.locator("#drawer-csv-file")).to_contain_text(upload["filename"], timeout=5000)
    context.close()


def test_the_unit_radios_show_the_drafts_unit_and_not_the_previous_slots(browser, base_url):
    """The unit radios are page-level markup shared by every slot, so they must be re-synced.

    The mutation this exists to catch is deleting the `syncCsvUnitRadios()` call from
    `applyCsvChoice`. Nothing else notices: every other CSV test drives one slot per page, and the
    radios happen to start on the template's `checked` default (kWh), which agrees with
    `DEFAULT_CSV_UNIT`. The mismatch only appears on the SECOND slot of a session.

    What goes wrong without the sync: `#drawer-csv-binding` and its radios live once in the page, not
    once per slot, so they still hold the last slot's answer. Open a slot with no committed binding
    after committing a `Wh` one and the radios show `Wh` while `openDrawer` has seeded
    `draft.unit = DEFAULT_CSV_UNIT` — the drawer displays one unit and would commit the other. It is
    the same show/draft mismatch `defaultSourceFor` was added upstream to prevent, and it is
    user-visible rather than internal: pressing Confirm without touching the radios stores kWh from a
    drawer that read Wh, which silently scales the series by 1000.

    Asserted on the RENDERED radio state (`is_checked`) rather than on the draft, because the draft is
    not observable from the page and is not what the user is misled by. The second half then confirms
    the two agree in the direction that costs data: what Confirm writes is what was shown.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()

    # Slot A: commit a NON-default unit, which is what leaves the shared radios out of step.
    _open_csv_drawer(pg, base_url, workspace_id)
    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    pg.locator("#source-drawer input[name='drawer-csv-unit'][value='Wh']").check()
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)
    stored = json.loads(pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')"))
    assert stored["slots"]["grid_import_t1"]["unit"] == "Wh", stored

    # Slot B, in the SAME page and with no committed binding of its own, so `openDrawer` seeds
    # `draft.unit` with the default. `solar_production` offers `csv_upload` (every energy slot except
    # `power_grid` does) and has been left untouched by this test.
    pg.locator("#slot-roster .slot-source-btn[data-slot='solar_production']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    expect(pg.locator("#drawer-csv-binding")).to_be_visible()

    kwh = pg.locator("#source-drawer input[name='drawer-csv-unit'][value='kWh']")
    wh = pg.locator("#source-drawer input[name='drawer-csv-unit'][value='Wh']")
    assert kwh.is_checked(), (
        "a slot with no committed binding must SHOW the default unit (kWh) — the radios are shared "
        "page markup and were left on the previous slot's Wh"
    )
    assert not wh.is_checked()

    # The direction that costs data: Confirm without touching the radios must store the unit the
    # drawer displayed. This is the same assertion from the other side — it fails on the same
    # mutation, and it is the one that says why the mismatch is not merely cosmetic.
    pg.locator("#drawer-csv-column").select_option("Zon")
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)
    stored = json.loads(pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')"))
    assert stored["slots"]["solar_production"]["unit"] == "kWh", stored
    # Slot A is untouched by any of this: the binding is per slot even though the control is not.
    assert stored["slots"]["grid_import_t1"]["unit"] == "Wh", stored
    assert stored["slots"]["solar_production"]["uploadId"] == upload["id"], stored
    context.close()


# --- bindings surviving a change to a NEIGHBOURING binding (step 8) ------------------------------
#
# Validation-harness fixture 22 (`docs/specs/16-validation-harness.md:182-210`) asserts three things
# that all have the same shape: a change aimed at one file or one slot must leave the OTHER bindings
# where they were. Every CSV test above binds exactly one slot, so none of them can see the
# difference between "cleared the right slot" and "cleared everything" — the assertions pass either
# way when there is only one slot to clear.
#
# These three bind TWO slots (or upload two files) and assert on both surfaces the binding shows on,
# because they fail separately: the ROW LABEL is rendered from `slotState`, and `localStorage` is
# what survives the next reload.


def _bind_slot_via_drawer(pg, slot: str, column: str):
    """Bind `slot` to `column` of the drawer's default file, through the real UI.

    Deliberately NOT built on `_open_csv_drawer`, which makes the slot pristine first: the tests
    below open the drawer on a slot that is already bound (to rebind it) and on a second slot in a
    page where the first is bound, and `_make_slot_pristine` reloads the page after rewriting the
    store — which would erase the very binding under test.
    """
    pg.locator(f"#slot-roster .slot-source-btn[data-slot='{slot}']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    expect(pg.locator("#drawer-csv-binding")).to_be_visible()
    # The column select is filled from the LIST route, so wait for the option to exist rather than
    # racing `select_option` against the fetch.
    expect(pg.locator(f"#drawer-csv-column option[value='{column}']")).to_have_count(1, timeout=5000)
    pg.locator("#drawer-csv-column").select_option(column)
    expect(pg.locator("#drawer-confirm")).to_be_enabled()
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)


def test_a_rejected_upload_leaves_an_existing_binding_intact(browser, base_url):
    """Fixture 22, *At upload*: after a rejection the earlier file "is still listed and still bound".

    `tests/test_upload_routes.py:287` covers the server half — a rejected POST writes no row, so the
    earlier upload is still listed. It cannot cover the other half of that sentence: under D-BIND the
    BINDING lives in browser `localStorage`, so whether it survived is only visible here.

    The regression this catches is an error path that resets shared CSV state on the way out. The
    mutation is one line in `uploadCsvFile`'s `.catch` — `csvUploads = []; pruneStaleCsvBindings();`
    — and it reads plausible for the same reason the `refreshCsvUploads` version did (the cache may
    be inconsistent after a failure, so clear it). Its symptom is severe and silent: a user who
    picks the wrong file by mistake loses every CSV binding in the workspace, with the dialog showing
    only the parse error and nothing about the bindings. No other test can see it, because every
    other test that drives a rejected upload (`test_a_rejected_upload_is_reported_in_the_dialog_and_
    is_recoverable`) has no binding in place when the rejection happens.

    The rejection driven here is a 12-hour clock, the same one that test uses — it is refused by
    `parse_and_summarise`, so the POST comes back non-2xx and the client takes the `.catch`.

    Both surfaces are asserted, and additionally that the file is still OFFERED in the drawer's file
    select: "still listed" is the clause's own wording, and a cleared cache would empty that select
    while `localStorage` still held the id.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload = _upload_csv(base_url, workspace_id)

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()

    _open_csv_drawer(pg, base_url, workspace_id)
    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='grid_import_t1'] .slot-source-label"
    )
    expected_label = f"Upload CSV · {upload['filename']} · Verbruik_T1"
    expect(label).to_have_text(expected_label)
    before = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert upload["id"] in (before or ""), before

    # Now attempt a MALFORMED upload from the dialog and let it be rejected.
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    pg.locator("#drawer-csv-upload-btn").click()
    twelve_hour = (
        "Tijdstip,Verbruik\n"
        "01-01-2025 00:00:00,0.4\n"
        "01-01-2025 06:00:00 PM,0.3\n"
    )
    pg.locator("#csv-upload-input").set_input_files({
        "name": "fout.csv", "mimeType": "text/csv", "buffer": twelve_hour.encode("utf-8"),
    })
    err = pg.locator("#csv-upload-error")
    expect(err).to_be_visible(timeout=5000)
    # The rejection actually happened. Without this the rest would pass vacuously on an upload that
    # quietly succeeded.
    expect(err).to_contain_text("A timestamp could not be read")

    # "still listed": the good file is still in the dialog's list, and the bad one is not.
    expect(pg.locator("#csv-upload-list")).to_contain_text(upload["filename"])
    assert "fout.csv" not in pg.locator("#csv-upload-list").text_content()

    pg.evaluate("() => document.getElementById('csv-upload-dialog').close()")
    pg.locator("#drawer-cancel").click()

    # "still bound wherever it was bound", on both surfaces.
    expect(label).to_have_text(expected_label)
    after = pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')")
    assert after == before, (
        "a REJECTED upload must not rewrite the slot store — the binding it never touched is at "
        f"stake.\nbefore: {before}\nafter:  {after}"
    )

    # And the file is still offered for binding, which is what "listed" means from the drawer's side.
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    expect(pg.locator("#drawer-csv-file")).to_contain_text(upload["filename"], timeout=5000)
    context.close()


def test_rebinding_one_slot_leaves_the_other_slots_binding_alone(browser, base_url):
    """Fixture 22, *Reuse and replacement*: a rebind "touches no other slot".

    Two slots are bound to two different columns of the SAME upload — which is the reuse half of that
    clause, since one file legitimately feeds several series — and then the first is rebound to a
    third column. What must hold afterwards is that the second slot reads exactly what it read
    before.

    The regression this catches is a commit path that writes the draft to more than its own slot. The
    mutation is inside `confirmDraft`: assigning the new state to every CSV-bound slot rather than to
    `draft.slot`. Nothing above notices, because each of those tests has at most one CSV slot to
    overwrite, so a broadcast write and a targeted one produce the same store. The symptom is that
    correcting one series' column silently repoints every other series at it, and the fetch then
    succeeds — it is a wrong-numbers bug, not an error.

    `solar_production` is the second slot: every energy slot except `power_grid` offers `csv_upload`,
    and this one is untouched by the roster's household gating in the empty state.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    # A THREE-column file: `_WIDE_CSV` has only two value columns, and this test needs a third to
    # rebind to that is neither slot's current column.
    upload = _upload_csv(base_url, workspace_id, filename="drie_kolommen.csv", text=(
        "Tijdstip,Verbruik_T1,Verbruik_T2,Zon\n"
        "01-01-2025 00:00:00,0.412,0.221,0.0\n"
        "01-01-2025 01:00:00,0.388,0.244,0.0\n"
        "01-01-2025 02:00:00,0.401,0.198,0.0\n"
        "01-01-2025 03:00:00,0.377,0.233,0.0\n"
    ))

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()

    # Slot A → Verbruik_T1, slot B → Zon, same file.
    _open_csv_drawer(pg, base_url, workspace_id, slot="grid_import_t1")
    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)
    _bind_slot_via_drawer(pg, "solar_production", "Zon")

    a_label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='grid_import_t1'] .slot-source-label"
    )
    b_label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='solar_production'] .slot-source-label"
    )
    expect(a_label).to_have_text(f"Upload CSV · {upload['filename']} · Verbruik_T1")
    expect(b_label).to_have_text(f"Upload CSV · {upload['filename']} · Zon")

    # Rebind slot A to a THIRD column. The slot is not made pristine — the point is that a rebind
    # replaces a live binding, and clearing it first would test the fresh-bind path again.
    _bind_slot_via_drawer(pg, "grid_import_t1", "Verbruik_T2")

    # Slot A now reads the new column; slot B is exactly where it was.
    expect(a_label).to_have_text(f"Upload CSV · {upload['filename']} · Verbruik_T2")
    expect(b_label).to_have_text(f"Upload CSV · {upload['filename']} · Zon")

    stored = json.loads(pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')"))
    assert stored["slots"]["grid_import_t1"]["column"] == "Verbruik_T2", stored
    assert stored["slots"]["solar_production"] == {
        "source": "csv_upload", "statId": "", "uploadId": upload["id"],
        "column": "Zon", "unit": "kWh",
    }, (
        "rebinding grid_import_t1 must leave solar_production's binding untouched, field for "
        f"field: {stored}"
    )
    context.close()


def test_deleting_a_referenced_upload_leaves_the_other_files_bindings_intact(browser, base_url):
    """Fixture 22: deleting a referenced upload "clears that slot's binding and leaves the others".

    `test_removing_a_file_clears_the_slots_bound_to_it_and_says_which` covers the first half and the
    report, but it binds ONE slot to ONE file, so "leaves the others intact" is unasserted: with a
    single binding in the store, a cascade that clears only the matching slot and one that clears
    every CSV slot are indistinguishable.

    Here two DIFFERENT files are uploaded and a slot is bound to each. Deleting file 1 must clear
    slot A and leave slot B bound to file 2.

    The regression this catches is a cascade that decides on the SOURCE rather than on the upload id
    — `pruneStaleCsvBindings` dropping the `csvUploadById(st.uploadId)` early return, which is one
    line. That is a live risk rather than a hypothetical one, because the same function is called on
    every successful list (`refreshCsvUploads`), so the broadened version would clear every CSV
    binding in the workspace on an ordinary page load, not only on a delete.

    The report is also asserted to name only slot A's role label: telling the user that a series they
    did not touch went back to "Choose source…" would be wrong even if the store were right.
    """
    url = _workspace_url(base_url)
    workspace_id = url.rstrip("/").split("/")[-2]
    upload1 = _upload_csv(base_url, workspace_id, filename="verbruik_2025.csv")
    upload2 = _upload_csv(base_url, workspace_id, filename="zonnepanelen_2025.csv")

    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": "en", "url": base_url}])
    pg = context.new_page()
    pg.on("dialog", lambda d: d.accept())   # the [ remove ] confirmation

    # Slot A → file 1, slot B → file 2. The file select must be set explicitly here: it defaults to
    # one of the two, and which one is not what this test is about.
    _open_csv_drawer(pg, base_url, workspace_id, slot="grid_import_t1")
    expect(pg.locator(f"#drawer-csv-file option[value='{upload1['id']}']")).to_have_count(
        1, timeout=5000)
    pg.locator("#drawer-csv-file").select_option(upload1["id"])
    pg.locator("#drawer-csv-column").select_option("Verbruik_T1")
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    pg.locator("#slot-roster .slot-source-btn[data-slot='solar_production']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    expect(pg.locator(f"#drawer-csv-file option[value='{upload2['id']}']")).to_have_count(
        1, timeout=5000)
    pg.locator("#drawer-csv-file").select_option(upload2["id"])
    pg.locator("#drawer-csv-column").select_option("Zon")
    pg.locator("#drawer-confirm").click()
    pg.wait_for_timeout(150)

    a_label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='grid_import_t1'] .slot-source-label"
    )
    b_label = pg.locator(
        "#slot-roster .slot-source-btn[data-slot='solar_production'] .slot-source-label"
    )
    expect(a_label).to_have_text(f"Upload CSV · {upload1['filename']} · Verbruik_T1")
    expect(b_label).to_have_text(f"Upload CSV · {upload2['filename']} · Zon")

    # Remove file 1 from the dialog. The row is located by its upload id rather than by position:
    # the list's order is the server's and this test depends on which file goes.
    pg.locator("#slot-roster .slot-source-btn[data-slot='grid_import_t1']").click()
    pg.locator("#source-drawer input[name='drawer-source'][value='csv_upload']").check()
    pg.locator("#drawer-csv-upload-btn").click()
    expect(pg.locator("#csv-upload-list")).to_contain_text(upload1["filename"])
    pg.locator(f"#csv-upload-list [data-upload-id='{upload1['id']}'] button").click()

    status = pg.locator("#csv-upload-status")
    expect(status).to_contain_text("Removed", timeout=5000)
    expect(status).to_contain_text("Grid import T1")
    # Only slot A is reported. Naming the untouched series would be wrong even with a correct store.
    assert "Solar" not in status.text_content(), (
        f"the removal report must name only the series it cleared: {status.text_content()!r}"
    )
    # File 2 survives the removal of file 1 on the server side too.
    expect(pg.locator("#csv-upload-list")).to_contain_text(upload2["filename"])

    pg.evaluate("() => document.getElementById('csv-upload-dialog').close()")
    pg.locator("#drawer-cancel").click()

    # Slot A is cleared whole; slot B is untouched.
    expect(a_label).to_have_text("Choose source…")
    expect(b_label).to_have_text(f"Upload CSV · {upload2['filename']} · Zon")

    stored = json.loads(pg.evaluate(f"localStorage.getItem('ha.slots.{workspace_id}')"))
    assert upload1["id"] not in json.dumps(stored), stored
    assert stored["slots"]["solar_production"] == {
        "source": "csv_upload", "statId": "", "uploadId": upload2["id"],
        "column": "Zon", "unit": "kWh",
    }, (
        "deleting one upload must leave a slot bound to a DIFFERENT upload completely alone, field "
        f"for field: {stored}"
    )

    # And it survives the reload, which is the store's whole purpose: the eager list-on-load runs
    # `pruneStaleCsvBindings` again against a list that no longer has file 1, so a cascade keyed on
    # the source rather than the id would clear slot B here even if it spared it above.
    pg.reload(wait_until="networkidle")
    expect(b_label).to_have_text(f"Upload CSV · {upload2['filename']} · Zon", timeout=5000)
    context.close()
