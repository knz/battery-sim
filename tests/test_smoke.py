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


def _open(browser, base_url, lang):
    """Open the page in a pinned language (cookie), panels expanded."""
    context = browser.new_context()
    context.add_cookies([{"name": "lang", "value": lang, "url": base_url}])
    pg = context.new_page()
    pg.goto(base_url + "/", wait_until="networkidle")
    for cb in pg.locator("section.collapse > input[type=checkbox]").all():
        cb.check()
    return pg


@pytest.fixture(scope="module")
def page(browser, base_url):
    # English is pinned so the structural assertions are stable regardless of the test
    # environment's Accept-Language (the app itself auto-detects for real users).
    return _open(browser, base_url, "en")


@pytest.fixture(scope="module")
def page_nl(browser, base_url):
    return _open(browser, base_url, "nl")


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
