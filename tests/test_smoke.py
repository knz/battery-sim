"""Playwright smoke test for the frontend scaffold.

Asserts the page renders and the key visual items of the default variant (has_pv=True,
simulate_cost=False) are present or absent as the wireframes require. This is deliberately
about structure, not exact numbers — the numbers are static sample data and will be replaced
when the domain layer lands.

    uv run pytest tests/test_smoke.py

Requires the CSS built (npm run build:css) and Playwright's Chromium installed.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=REPO_ROOT,
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
def page(base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.goto(base_url + "/", wait_until="networkidle")
        # Expand both collapsed panels so their contents are queryable.
        for cb in pg.locator("section.collapse > input[type=checkbox]").all():
            cb.check()
        yield pg
        browser.close()


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


def test_pending_dialog_opens(page):
    page.get_by_role("button", name="Export CSV").click()
    assert page.get_by_text("Not built yet").first.is_visible()
    page.keyboard.press("Escape")


def test_chart_rendered(page):
    # Plotly draws an <svg> into the chart container.
    assert page.locator("#monthly-chart svg").count() >= 1
