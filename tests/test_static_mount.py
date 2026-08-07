"""The `/static` mount actually SERVES its files, not just that pages link to them.

`app/main.py:260` mounts `app/static` with Starlette's `StaticFiles`. Nothing else in the
unpackaged suite fetches `/static/*` at all: the two references elsewhere
(`tests/test_workspace_data.py:382`, `tests/test_workspace_results.py:824`) assert that the
`href`/`src` STRING appears in the rendered HTML, which stays true even if the mount is broken,
misconfigured, or pointed at the wrong directory. Until this file, that gap was covered only by
`tests/test_packaged.py::test_static_files_are_bundled`, which runs in the dispatch-only Release
workflow — so a broken mount would have surfaced days later, at release time.

Two assertions per asset, and the second is the one with teeth:

  * a 200 shows the mount is wired and the file is where the mount expects it;
  * a size floor shows the REAL asset is being served rather than a stub or an empty file. A
    Tailwind build that wrote nothing, or a partially-copied asset, returns 200 for a 0-byte body
    and would satisfy the status check alone.

The floor is 1000 bytes, matching the packaged test's, and both assets clear it by two orders of
magnitude (app.css ~100 KB, ha_fetch.js ~125 KB), so it will not go off on ordinary growth or
shrinkage — it is a stub detector, not a size budget.

Deliberately NOT asserted here: anything about app.css's CONTENT. The `css-freshness` job in
`.github/workflows/test.yml` regenerates it with Tailwind and fails on any diff, so it already
owns that property; duplicating it would give two tests that fail together for one cause.

Runs under `TestClient` rather than a live uvicorn subprocess — verified that the mount is served
on that path, so nothing here needs the slower fixture `tests/test_smoke.py` uses.

Main items:
    ASSETS      the served paths, with the floor each must clear.
    test_the_static_mount_serves_its_assets
"""

import pytest
from starlette.testclient import TestClient

from app import main

# The two files the app cannot render a working page without: the Tailwind output every template
# links, and the Home Assistant fetch module `app/templates/_panel_data.html` loads.
ASSETS = ("/static/app.css", "/static/ha_fetch.js")

_STUB_FLOOR = 1000


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


@pytest.mark.parametrize("path", ASSETS)
def test_the_static_mount_serves_its_assets(client, path):
    response = client.get(path)

    assert response.status_code == 200, (
        f"{path} did not serve — the StaticFiles mount in app/main.py is broken or pointed at "
        f"the wrong directory. Got {response.status_code}."
    )
    assert len(response.content) > _STUB_FLOOR, (
        f"{path} served only {len(response.content)} bytes, which is too small to be the real "
        "asset. A 200 with an empty or stub body means the file exists but was not built."
    )
