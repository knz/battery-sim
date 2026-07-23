"""Launch the app and capture a full-page screenshot for visual review.

This is the self-testing tool for iterating on the frontend: it starts the FastAPI app on a
free port, drives it with Playwright's bundled headless Chromium, and writes a full-page PNG.
Run it after template/CSS changes to eyeball the result.

    uv run python tests/screenshot.py [output.png] [--width 1280]

Default output is tests/artifacts/page.png. The server is started and torn down here, so
nothing needs to be running beforehand — but the CSS must be built (npm run build:css) and
Playwright's browser installed (uv run playwright install chromium).
"""

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(url: str, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"server did not come up at {url}")


def capture(out_path: Path, width: int = 1280, theme: str = "light") -> None:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=REPO_ROOT,
    )
    try:
        _wait_until_up(base + "/")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(base + "/", wait_until="networkidle")
            # Expand the two collapsed stepper panels so the screenshot shows everything.
            for checkbox in page.locator("section.collapse > input[type=checkbox]").all():
                checkbox.check()
            page.wait_for_timeout(400)  # let Plotly draw and layout settle
            out_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
        print(f"wrote {out_path}")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("output", nargs="?", default=str(REPO_ROOT / "tests/artifacts/page.png"))
    ap.add_argument("--width", type=int, default=1280)
    args = ap.parse_args()
    capture(Path(args.output), width=args.width)
