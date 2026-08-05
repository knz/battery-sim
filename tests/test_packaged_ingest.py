"""Phase 5 levels 1 and 2: the Home Assistant ingest protocol, driven against a PACKAGED artifact.

Runs against whichever packaged artifact is pointed at, and against BOTH when both are:

    BATTERY_SIM_PACKAGED_BINARY=dist/battery-sim/battery-sim \
    BATTERY_SIM_APPIMAGE=dist/Home-Battery-Simulator-x86_64.AppImage \
    uv run pytest tests/test_packaged_ingest.py

Skipped entirely when neither variable is set — the same gating idiom as `tests/test_packaged.py`
and `tests/test_appimage.py`, and for the same reason: an ordinary run has nothing built to test.

## What this file adds that the two files beside it do not

`tests/test_packaged.py::test_the_websocket_route_works` already opens one raw `ws://` against the
ONEDIR bundle. This file differs on three axes, each of which is a real gap rather than a
restatement:

  * **The artifact.** Every check below is parametrized over the onedir binary AND the AppImage.
    The AppImage is a different payload — a different `sys.path`, a repacked `_internal/`, an
    AppRun that rewrites the environment — and `tests/test_appimage.py` never opens a WebSocket
    against it at all. Nothing before this file asserted that the ingest route survives the
    AppImage repack.

  * **Both directions of the protocol, on a frame the SERVER originates.** A handshake proves the
    upgrade path exists; it does not prove the server can encode a frame back. `test_level1_*`
    sends one header and requires the server's own reply, which is the half a broken bundle would
    lose without failing the upgrade.

  * **A recorded HA row batch, replayed over a real socket, then read back over HTTP.**
    `tests/test_ingest_ws.py` replays the same batch through FastAPI's `TestClient` — in-process,
    against the source tree, with no `websockets` implementation involved at all, because
    `TestClient` speaks ASGI directly and never performs an HTTP upgrade. Level 2 here is that
    same body sent through a genuine socket to a frozen process, with the persisted result then
    queried through the app's own HTML.

## A note on how much level 1 is worth, stated honestly

Phase 3 (§12.6 of `changelog/20260805-desktop-packaging.md`) measured that because
`app/desktop.py` pins `ws="websockets-sansio"` rather than uvicorn's default `"auto"`, a MISSING
WebSocket implementation is a `ModuleNotFoundError` at server startup, not a silent single-route
failure. So level 1 does NOT catch the failure R2 was originally written about — the server never
starts, and every test in every packaged file fails first.

What it still covers is narrower and worth naming precisely: an implementation that IMPORTS but
cannot complete an upgrade or carry a frame in the frozen environment. That covers a partial
`websockets` collection (the sansio impl present, a submodule it reaches lazily absent), a
protocol module the AppImage's repack relocates, and any future change of the pin back to
`"auto"` — which would restore exactly the silent trap. It is a regression guard on a property no
HTTP test observes, not the primary defence it was planned as.

Main items:
    ARTIFACTS               (label, launch-argv) for each artifact the gates name.
    packaged_server         one artifact running on a free port; torn down by exact PID.
    seeded_workspace        a real workspace id, created before any socket is opened.
    _ws_url                 the ingest URL for a workspace on a running server.
    test_level1_*           raw `ws://` upgrade, a server-originated frame, and the 404 trap.
    test_level2_*           the recorded HA batch replayed, persisted, and read back.
"""

import asyncio
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

_ENV_BINARY = "BATTERY_SIM_PACKAGED_BINARY"
_ENV_APPIMAGE = "BATTERY_SIM_APPIMAGE"


def _artifacts() -> list[tuple[str, list[str]]]:
    """Every packaged artifact the environment points at, as `(label, argv-prefix)`.

    Both gates rather than one, so a single pytest invocation covers the onedir bundle and the
    AppImage. The labels are what pytest prints in the test id, so a failure names which artifact
    broke without anyone having to decode a path.
    """
    out = []
    binary = os.environ.get(_ENV_BINARY)
    if binary:
        out.append(("onedir", [str(Path(binary).resolve())]))
    appimage = os.environ.get(_ENV_APPIMAGE)
    if appimage:
        out.append(("appimage", [str(Path(appimage).resolve())]))
    return out


ARTIFACTS = _artifacts()

pytestmark = pytest.mark.skipif(
    not ARTIFACTS,
    reason=f"set {_ENV_BINARY} and/or {_ENV_APPIMAGE} to run the packaged ingest checks",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module", params=ARTIFACTS, ids=lambda a: a[0])
def packaged_server(request, tmp_path_factory):
    """One artifact running with `--no-browser`, yielding its base URL.

    `BATTERY_SIM_DATA_DIR` is REMOVED and `XDG_DATA_HOME` redirected, the same combination
    `tests/test_packaged.py::packaged_server` uses: with the variable set, the `sys.frozen` branch
    of `app/config.py::data_dir` never runs and the artifact would be writing somewhere the test
    chose rather than somewhere it chose.

    The deadline is the AppImage's 40s rather than the onedir bundle's 20s, because one fixture
    serves both and an AppImage mounts before it runs.
    """
    label, argv = request.param
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    work = tmp_path_factory.mktemp(f"run-{label}")
    xdg = work / "xdg"
    xdg.mkdir()

    env = {k: v for k, v in os.environ.items() if k != "BATTERY_SIM_DATA_DIR"}
    env["XDG_DATA_HOME"] = str(xdg)

    proc = subprocess.Popen(
        [*argv, "--no-browser", "--port", str(port)],
        cwd=str(work),  # NOT the repository — a user runs this from anywhere.
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"the {label} artifact exited early:\n{proc.stdout.read()}")
        try:
            urlopen(url + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError(f"the {label} artifact did not answer within 40s")

    yield url

    # By this process's own handle, and nothing else. A pattern-based kill would be actively
    # wrong: whoever runs these tests very likely has their own copy of the app running.
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def seeded_workspace(packaged_server):
    """A fresh workspace id, created through the app's own `POST /workspaces`.

    **Function-scoped on purpose, unlike the module-scoped one in `tests/test_packaged.py`.**
    Level 2 persists a dataset into whatever workspace it is given and then asserts on the
    configure-data screen; sharing one workspace across tests would let an earlier ingest satisfy
    a later assertion.

    **And it must exist before any socket is opened.** An unknown workspace id fails the ingest
    route's HANDSHAKE with an HTTP 404 rather than with an in-protocol error, by design (see the
    route in `app/main.py`). A test that skipped this step would see a connection failure against
    a perfectly good bundle and report a packaging bug that is not there — the specific
    misdiagnosis §10 of the changelog records. `test_level1_an_unknown_workspace_fails_the_handshake`
    pins that behaviour deliberately so the trap stays documented in executable form.
    """
    req = Request(packaged_server + "/workspaces", data=b"", method="POST")
    with urlopen(req, timeout=15) as r:
        return r.url.split("?")[0].rstrip("/").split("/")[-2]


def _ws_url(base_url: str, workspace_id: str) -> str:
    return base_url.replace("http://", "ws://") + f"/w/{workspace_id}/data/ingest/ws"


def _get(url: str, lang: str | None = None) -> tuple[int, str]:
    headers = {"Accept-Language": lang} if lang else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=15) as r:
            return r.status, r.read().decode("utf-8")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8")


# ── Level 1: the raw `ws://` upgrade against the packaged artifact ────────────────────────────


def test_level1_a_raw_websocket_upgrade_completes(packaged_server, seeded_workspace):
    """A genuine HTTP upgrade to the ingest route, on the frozen artifact.

    This is the half `tests/test_packaged.py` shares, kept here so the AppImage gets it too: the
    upgrade is what proves uvicorn's pinned `websockets-sansio` implementation is present AND
    functional in this bundle, rather than merely importable.

    The `origin` header is supplied because that is what a real browser sends, and the packaged
    app's whole premise (phase 5 level 3) is a page at `http://127.0.0.1:<port>` opening this
    socket. Sending a different origin would exercise a request no browser makes.
    """
    websockets = pytest.importorskip("websockets")

    async def upgrade():
        async with websockets.connect(
            _ws_url(packaged_server, seeded_workspace), origin=packaged_server
        ) as ws:
            # `response` carries the server's handshake reply; a completed upgrade is the assertion.
            return ws.response.status_code if hasattr(ws, "response") else 101

    assert asyncio.run(upgrade()) in (101, 200)


def test_level1_the_server_answers_a_header_frame(packaged_server, seeded_workspace):
    """One frame in, one frame out — the direction a handshake alone does not prove.

    **A well-formed header draws no reply**: `app/ingest_ws.py::on_header` records the window and
    returns, and only a `rows` batch produces `progress`. So a test that sent a valid header and
    waited would hang on a working server. This sends a header whose window is INVALID (`end`
    before `start`), which `on_header` rejects with an `IngestError` that the route turns into an
    `error` frame — a frame the SERVER originates, encodes, and puts on the wire.

    That is the property under test. A frozen bundle whose WebSocket implementation can accept an
    upgrade but cannot encode an outbound frame passes every HTTP check in
    `tests/test_packaged.py` and fails here. Asserting on the error TEXT as well as the type keeps
    it from passing on any old frame the server might emit — the reply has to be the one this
    specific message provokes.
    """
    websockets = pytest.importorskip("websockets")

    async def exchange():
        async with websockets.connect(
            _ws_url(packaged_server, seeded_workspace), origin=packaged_server
        ) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "header",
                        "source": "home_assistant",
                        "window": {
                            "start": "2025-01-02T00:00:00+00:00",
                            "end": "2025-01-01T00:00:00+00:00",
                        },
                    }
                )
            )
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=20))

    reply = asyncio.run(exchange())
    assert reply["type"] == "error", reply
    assert "window end must be after start" in reply["message"], reply


def test_level1_an_unknown_workspace_fails_the_handshake(packaged_server):
    """The documented trap, pinned so a future reader cannot rediscover it the expensive way.

    An unknown workspace id is rejected by `deps.get_workspace` BEFORE `ws.accept()`, and FastAPI
    answers a rejected WebSocket dependency with an ordinary HTTP 404 instead of upgrading. The
    client therefore sees a connection failure with a 404 status, not an `error` frame — which
    looks exactly like "this bundle has no WebSocket support" to anyone who has not read the
    route.

    Asserting the STATUS CODE and not merely "it failed" is what makes this useful: a bundle that
    genuinely lacked WebSocket support would fail this connection too, but with a different shape.
    """
    websockets = pytest.importorskip("websockets")

    async def connect_unknown():
        async with websockets.connect(_ws_url(packaged_server, "no-such-workspace")):
            pass

    with pytest.raises(Exception) as excinfo:
        asyncio.run(connect_unknown())
    assert "404" in str(excinfo.value), (
        "an unknown workspace should fail the handshake with HTTP 404. A different failure here "
        "means the rejection is happening somewhere other than the workspace dependency — check "
        "that the WebSocket implementation is present in the bundle before blaming the route. "
        f"Got: {excinfo.value!r}"
    )


# ── Level 2: a recorded HA row batch, replayed against the packaged server ────────────────────

# The batch is the one `tests/test_ingest_ws.py::_drive_valid_ingest` replays in-process: three
# hourly readings each of a cumulative import register, a cumulative export register, and a spot
# price, over a two-hour window. Copied rather than imported because that module's helper drives a
# FastAPI `TestClient` (synchronous `send_json`/`receive_json`) while this one drives a real
# `websockets` socket (async), so only the DATA transfers — and the data is the part that matters.
# The `stat_id` is carried through deliberately: it is what the read-back assertion below keys on.
_WINDOW = {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"}
_STAT_ID = "sensor.meter_import_t1"
_RECORDED_BATCH = [
    (
        {"name": "grid_import_t1", "kind": "energy", "unit": "kWh", "stat_id": _STAT_ID},
        [[1784505600000, 5127.0], [1784509200000, 5127.5], [1784512800000, 5128.4]],
    ),
    (
        {"name": "grid_export_t1", "kind": "energy", "unit": "kWh"},
        [[1784505600000, 590.0], [1784509200000, 590.0], [1784512800000, 590.2]],
    ),
    (
        {"name": "price_spot", "kind": "price", "unit": "EUR/kWh"},
        [[1784505600000, 0.2955], [1784509200000, 0.2899], [1784512800000, 0.2924]],
    ),
]


async def _replay(ws_url: str, origin: str) -> dict:
    """Send the recorded batch through a real socket and return the final `result` frame."""
    import websockets

    async with websockets.connect(ws_url, origin=origin, max_size=64 * 2**20) as ws:
        await ws.send(json.dumps({"type": "header", "source": "home_assistant", "window": _WINDOW}))
        for series, rows in _RECORDED_BATCH:
            await ws.send(json.dumps({"type": "series", **series}))
            await ws.send(json.dumps({"type": "rows", "name": series["name"], "rows": rows}))
            progress = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            assert progress["type"] == "progress", progress
            assert progress["name"] == series["name"], progress
            assert progress["rows"] == len(rows), progress
        await ws.send(json.dumps({"type": "done"}))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=30))


def test_level2_a_recorded_ha_batch_replays_and_persists(packaged_server, seeded_workspace):
    """The whole ingest path — upgrade, three series, `done`, persistence — on a frozen process.

    The assertions on the `result` frame mirror
    `tests/test_ingest_ws.py::test_valid_ingest_persists_and_reports`, which makes them the useful
    kind: the packaged build must produce the SAME answer the source tree does, and the source
    tree's expectation is already pinned by a test that runs on every ordinary pytest invocation.
    A divergence here is a packaging defect by construction.

    `grid_s == 3600` is worth keeping specifically. It is computed by the reconciliation code in
    `app/domain`, which is numpy-backed — so a bundle whose numpy collection were damaged would
    complete the socket exchange and then get this wrong, rather than failing anywhere visible.
    """
    pytest.importorskip("websockets")

    result = asyncio.run(
        _replay(_ws_url(packaged_server, seeded_workspace), origin=packaged_server)
    )

    assert result["type"] == "result", result
    assert result["series"] == 3, result
    assert result["dataset_id"] >= 1, result
    assert result["grid"]["grid_s"] == 3600, result["grid"]
    price = next(s for s in result["grid"]["series"] if s["name"] == "price_spot")
    assert price["reconciliation"] == "exact", price


def test_level2_the_replayed_rows_are_queryable_afterwards(packaged_server, seeded_workspace):
    """The rows LANDED — asserted through the app's own HTML, not through the socket's own reply.

    The `result` frame above is the server describing what it believes it did. This reads the
    persisted dataset back out of a separate HTTP request to the configure-data screen, which
    renders from `dataset.load_latest`. Two independent code paths have to agree for this to pass,
    and the write path has to have actually reached disk in the frozen process's per-user data
    directory rather than only an in-memory session.

    The three assertions are chosen to fail on different things:

      * `Data quality` appears only once a dataset exists (specs §2′.5), so it distinguishes a
        loaded dataset from the empty state.
      * `import T1 mapped` comes from the register summary, computed off the differenced frames —
        so it needs the ENERGY series to have been differenced, not merely stored.
      * `data-slot-stat-id="sensor.meter_import_t1"` round-trips the statistic id that the header
        of the recorded batch carried, through `series_meta` and back into server-rendered markup.
        That is the one assertion which proves the specific bytes sent over the socket are what
        came back, rather than any dataset at all.
    """
    pytest.importorskip("websockets")

    result = asyncio.run(
        _replay(_ws_url(packaged_server, seeded_workspace), origin=packaged_server)
    )
    assert result["type"] == "result", result

    status, page = _get(f"{packaged_server}/w/{seeded_workspace}/data", lang="en")
    assert status == 200, page[:500]
    assert "Data quality" in page, "the configure-data screen still shows the empty state"
    assert "import T1 mapped" in page, "the register summary did not render the ingested import"
    assert f'data-slot-stat-id="{_STAT_ID}"' in page, (
        "the HA statistic id from the replayed batch did not survive to the rendered page — the "
        "rows may have been accepted over the socket without being persisted"
    )
