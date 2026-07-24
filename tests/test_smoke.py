"""Playwright smoke test for the frontend scaffold.

Asserts the page renders and the key visual items of the default variant (has_pv=True,
simulate_cost=False) are present or absent as the wireframes require. This is deliberately
about structure, not exact numbers — the numbers are static sample data and will be replaced
when the domain layer lands.

It also covers the pending affordance (specs/02-ux-wireframes.md §2.1): the four pending
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
    assert page.get_by_text("Solar production").count() >= 1
    assert page.get_by_text("How is your PV connected to the battery?").count() >= 1


def test_slot_info_affordance(page):
    # The two corroboration slots (Grid power, House load) carry an `info` blurb, so the demo
    # renders an ⓘ button next to each. Clicking one fills and opens the shared #slot-info-dialog.
    info_btns = page.locator(".slot-info-btn")
    assert info_btns.count() == 2  # exactly the two rows with a blurb; no icon on the others
    page.get_by_role("button", name="About House load").click()
    dialog = page.locator("#slot-info-dialog")
    assert dialog.get_by_text("House load", exact=True).is_visible()
    assert "reconstructs household load" in dialog.locator("#slot-info-body").inner_text()
    page.keyboard.press("Escape")


def test_data_summary_band_absent_in_empty_state(page):
    # The data summary band (§2.3a) is shown only once data has loaded. The smoke server runs
    # against a throwaway data dir with no persisted dataset (the empty state), so the band must
    # be absent — main.py drops `data_summary` from the context when no dataset exists (§3.4).
    assert page.get_by_text("Your data at a glance", exact=True).count() == 0


def test_pending_dialog_opens(page):
    page.get_by_role("button", name="Export CSV").click()
    assert page.get_by_text("Not built yet").first.is_visible()
    page.keyboard.press("Escape")


def test_new_pending_controls_marked(page):
    # The two controls marked pending in this increment render disabled with a [?] affordance.
    # "Upload CSV" is a pending source radio that now lives inside the source-picker drawer
    # (moved there when panel ① went slot-first, 0594e34); open a slot's drawer to reveal it.
    # ha_fetch.js renders it as name="drawer-source", disabled, with feature key data_source_csv.
    page.locator(".slot-source-btn").first.click()
    assert page.locator("input[name=drawer-source][disabled]").count() >= 1  # Upload CSV radio
    page.keyboard.press("Escape")  # Escape discards and closes the drawer (leaves no committed state)
    # "Simulate cost savings?" — the "Yes" answer is disabled with a [?] pending marker
    # (cost machinery not built yet; lives in the setup band since c8f3254).
    assert page.locator("input[name=setup_cost][disabled]").count() >= 1
    assert page.locator("[data-feature-key=simulate_cost]").count() >= 1


def test_thumbsup_acknowledges_in_place(page):
    # Clicking the thumbs-up flips the button to "✓ Noted" and shows the thanks line, without
    # reporting any failure. Uses the Allow-export control so it is independent of other tests.
    page.locator("[data-feature-key=discharge_allow_export]").click()
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
