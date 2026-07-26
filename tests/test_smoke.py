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


def _open(browser, base_url, lang, url=None):
    """Open the three-panel page in a pinned language (cookie), panels expanded."""
    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": lang, "url": base_url}])
    pg = context.new_page()
    pg.goto(url or _workspace_url(base_url), wait_until="networkidle")
    for cb in pg.locator("section.collapse > input[type=checkbox]").all():
        cb.check()
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


def test_three_panels_present(page):
    body = page.locator("body").inner_text()
    assert "DATA" in body
    assert "PARAMETERS" in body
    assert "RESULTS" in body


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


def test_solar_row_present(page):
    # has_pv is on: the solar sensor row and the PV-coupling selector are shown.
    # VISIBILITY, not presence: gated rows are now rendered-and-hidden so the setup radios can
    # re-gate them client-side, so a `.count()` assertion would pass even with the row hidden.
    assert page.locator('.slot-row[data-slot-row="solar_production"]').is_visible()
    assert page.get_by_text("How is your PV connected to the battery?").count() >= 1


def test_existing_battery_rows_are_hidden_until_declared(page):
    # has_battery defaults off, so the two existing-battery slots are gated out of the roster.
    for slot in ("battery_charge", "battery_discharge"):
        assert not page.locator(f'.slot-row[data-slot-row="{slot}"]').is_visible()


def test_the_setup_toggles_re_gate_the_roster_live(page):
    """The regression this whole change exists for: the toggles must actually DO something.

    They were previously inert — no form, no handler, no route — so clicking one changed nothing
    and the radio snapped back on the next render. Here the roster must re-gate immediately,
    client-side, with no round-trip (the answers are persisted later, by the fetch button).
    """
    solar = page.locator('.slot-row[data-slot-row="solar_production"]')
    charge = page.locator('.slot-row[data-slot-row="battery_charge"]')

    assert solar.is_visible() and not charge.is_visible()

    # "No" to PV hides the solar row; "Yes" to an existing battery reveals its two slots.
    page.locator('input[name="setup_haspv"][value="0"]').check()
    page.locator('input[name="setup_hasbattery"][value="1"]').check()
    assert not solar.is_visible(), "answering No to PV must hide the solar slot"
    assert charge.is_visible(), "declaring a battery must reveal its slots"

    # Toggling back restores both — the answers gate the view, they do not destroy state.
    page.locator('input[name="setup_haspv"][value="1"]').check()
    page.locator('input[name="setup_hasbattery"][value="0"]').check()
    assert solar.is_visible()
    assert not charge.is_visible()


def test_slot_info_affordance(page):
    # The two corroboration slots (Grid power, House load) carry an `info` blurb, so the demo
    # renders an ⓘ button next to each. Clicking one fills and opens the shared #slot-info-dialog.
    #
    # Counted over VISIBLE buttons only. The setup band's "Do you already have a battery?" ⓘ uses
    # the same shared affordance, and the two existing-battery slots carry blurbs of their own —
    # but those rows are gated out while has_battery is false (the appendix-A default this demo
    # runs with), so they are rendered-but-hidden and must not be counted here.
    visible_info_btns = page.locator("#slot-roster .slot-info-btn:visible")
    assert visible_info_btns.count() == 2  # exactly the two visible rows with a blurb
    page.get_by_role("button", name="About House load").click()
    dialog = page.locator("#slot-info-dialog")
    assert dialog.get_by_text("House load", exact=True).is_visible()
    assert "reconstructs household load" in dialog.locator("#slot-info-body").inner_text()
    page.keyboard.press("Escape")


def test_slot_info_dialog_works_when_panel_1_is_collapsed(page):
    # Regression: the shared #slot-info-dialog used to live inside panel ①'s `.collapse-content`,
    # which daisyUI gives `content-visibility: hidden` when collapsed. showModal() then still put
    # the dialog in the top layer — blocking every click on the page — but the browser never
    # painted it: no popup, frozen page. Reported against panel ③'s glance ⓘ with panel ① closed;
    # panel ①'s own roster ⓘ reproduces it identically, and works in the empty state this server
    # runs. Assert the dialog actually becomes VISIBLE (not merely `open`) with panel ① collapsed.
    toggle = page.locator('input[aria-label="Toggle Data panel"]')
    toggle.check()  # expand to reach the roster's ⓘ button
    btn = page.get_by_role("button", name="About House load")
    btn.scroll_into_view_if_needed()
    toggle.uncheck()  # collapse panel ① again; the delegated handler still fires
    page.evaluate("document.querySelector('.slot-info-btn').click()")
    dialog = page.locator("#slot-info-dialog")
    assert dialog.evaluate("d => d.open") is True
    # The real assertion: painted, not just open. This was False with the dialog inside the panel.
    assert dialog.is_visible()
    assert dialog.evaluate(
        "d => !d.closest('.collapse-content')"
    ), "the dialog must not live inside a collapse, or it is hidden when the panel is closed"
    page.keyboard.press("Escape")
    # The `page` fixture is module-scoped: restore panel ① to expanded, the state the other tests
    # in this file expect (several click controls inside it).
    toggle.check()


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
    # `/w/<id>/results` — the id is what the scoped localStorage key is built from, so it is read
    # off the URL rather than assumed to be `local` (workspaces get generated ids since phase 2).
    workspace_id = url.rstrip("/").split("/")[-2]
    scoped_key = f"ha.slots.{workspace_id}"

    context = browser.new_context()
    pg = context.new_page()
    # Seed the pre-workspaces global key, as an upgraded installation's browser would hold it, then
    # load the page so the module runs against it.
    pg.goto(url, wait_until="networkidle")
    pg.evaluate("localStorage.setItem('ha.slots', JSON.stringify({gen: 0, slots: {a: 1}}))")
    pg.reload(wait_until="networkidle")
    # Panels render collapsed; the roster's buttons are not clickable until panel ① is open.
    for cb in pg.locator("section.collapse > input[type=checkbox]").all():
        cb.check()

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


def test_data_summary_absent_in_empty_state(page):
    # The data summary (§2.3a) renders INSIDE panel ①, below the data-quality box, but only once
    # data has loaded. The smoke server runs against a throwaway data dir with no persisted
    # dataset (the empty state), so it must be absent — main.py drops `data_summary` from the
    # context when no dataset exists (§3.4). Its placement is covered in test_results_route.py,
    # which has a dataset to render.
    assert page.get_by_text("Your data at a glance", exact=True).count() == 0


def test_pending_dialog_opens(page):
    page.get_by_role("button", name="Export CSV").click()
    assert page.get_by_text("Not built yet").first.is_visible()
    page.keyboard.press("Escape")


def test_new_pending_controls_marked(page):
    # "Upload CSV" is a pending source radio that lives inside the source-picker drawer
    # (moved there when panel ① went slot-first, 0594e34); open a slot's drawer to reveal it.
    # ha_fetch.js renders it as name="drawer-source", disabled, with feature key data_source_csv.
    page.locator(".slot-source-btn").first.click()
    assert page.locator("input[name=drawer-source][disabled]").count() >= 1  # Upload CSV radio
    page.keyboard.press("Escape")  # Escape discards and closes the drawer (leaves no committed state)
    # The setup band's "Simulate cost savings?" is NO LONGER pending — the cost path is built, the
    # radios POST, and the key is retired in app/features.py. Both answers are live controls.
    assert page.locator("input[name='setup.simulate_cost'][disabled]").count() == 0
    assert page.locator("[data-feature-key=simulate_cost]").count() == 0
    # Panel ③'s two unbuilt chart tabs are still pending, and are on the page unconditionally.
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

def test_dutch_renders(page_nl):
    # Known Dutch translations appear when the lang cookie is 'nl'.
    body = page_nl.locator("body").inner_text()
    assert "ENERGIEBESPARING" in body          # ENERGY SAVINGS
    assert "BESPAARDE NETAFNAME" in body        # GRID IMPORT SAVED
    assert "Datakwaliteit" in body              # Data quality
    # And the English headline is gone from the results tiles.
    assert page_nl.get_by_text("GRID IMPORT SAVED", exact=True).count() == 0


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


def test_the_cost_tint_actually_renders_and_is_not_merely_a_class_name(page):
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
    # control — the setup band's radio, wired in Phase 5 — rather than by writing a config file,
    # so this also exercises the path a user takes to reach these fields at all.
    page.locator("#setup-band input[name='setup.simulate_cost'][value='yes']").check()
    # The POST swaps panel ② in re-collapsed, so re-expand before measuring — a computed style
    # on a `display:none` subtree is not what the reader sees.
    page.wait_for_selector("input.cost-field", state="attached", timeout=10000)
    for cb in page.locator("section.collapse > input[type=checkbox]").all():
        cb.check()
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
    # tint up — otherwise the marking distinguishes nothing. The MONEY SAVED tile lives in panel
    # ③ and needs a simulated dataset, which this fixture has no data for; panel ②'s Pricing
    # heading is on screen and exercises the same rule against the same override risk.
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
    # The three-panel page, not an error document.
    assert "PARAMETERS" in pg.locator("body").inner_text()

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
