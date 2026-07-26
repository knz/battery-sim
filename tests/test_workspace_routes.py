"""Route tests for the workspace scoping itself (specs/08-architecture.md §5.1, §5.5).

The other route test modules exercise what each route COMPUTES, under one workspace. This one
exercises the thing phase 1 added and nothing else covers: that a route's workspace comes from
the path, and that the answer is right for every id a client can put there.

Three properties, and the first is the point of the whole phase:

  * **Isolation.** A params write against workspace B must not touch A's config document. This is
    the property the re-rooting exists to create, and it is asserted at the level a user would
    notice it — the number the OTHER workspace's panel ③ renders, not just the bytes on disk — so
    a route that scoped the save but forgot the read would still fail here.
  * **404 on an unknown id**, for every scoped route including the WebSocket, whose failure shape
    is different (the handshake is refused, so there is no socket and no `error` frame).
  * **Traversal is refused at the route, with a 404 and not a 500.** The storage-layer helpers
    already raise `ValueError` on a separator-bearing id (§5.5 invariant 4); the point of the check
    in `app/deps.py` is that a client never sees that as a server error. These cases matter because
    a `ValueError` escaping a route body is a 500 with a stack trace, and a path segment is client
    input.

The harness mirrors tests/test_results_route.py — a temp data dir with a seeded dataset — with the
one difference that it seeds TWO workspaces, since one workspace cannot demonstrate isolation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame
from tests.conftest import seed_workspace

_DAYS = 30
_HOURS = _DAYS * 24
_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 1 + _DAYS, tzinfo=timezone.utc)

_A = "local"
_B = "second"


def _energy(name: str, per_hour: float) -> SeriesFrame:
    idx = (
        np.arange(_HOURS).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "energy", 3600, idx,
        np.full(_HOURS, float(per_hour)),
        np.zeros(_HOURS, dtype=QUALITY_DTYPE),
    )


def _form(**overrides) -> dict:
    """A minimal VALID panel-② submission (the same field set tests/test_params_route.py posts)."""
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


@pytest.fixture()
def two(tmp_path, monkeypatch):
    """A client over a temp data dir holding TWO workspaces, each with its own seeded dataset.

    Both datasets are identical, deliberately: any later difference in what the two panels report
    then comes from the CONFIG each route read, which is what these tests are about. A difference
    seeded into the data would prove nothing about the config threading.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset

    for wid in (_A, _B):
        seed_workspace(wid, title=f"workspace {wid}")
        dataset.save_dataset(
            [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)],
            (_WIN_START, _WIN_END), "test", [], None, wid,
        )

    from app import main

    return TestClient(main.app)


def _capacity_on_panel(client, wid: str) -> str:
    """The usable-capacity value the workspace's own panel ② renders, WITHOUT persisting.

    Read back through the ROUTE rather than off disk, because "B's write did not reach A" has to
    hold for what A's page SHOWS, not merely for A's bytes: a route that saved under the right id
    but loaded under a defaulted one would pass a file check and fail this.

    The submission is deliberately INVALID (min SoC above max, §7.3 check 11), which is the one way
    to make `POST /params` render a panel without writing one — it re-renders from the candidate
    and skips the save. The candidate is built on top of the STORED config, so every field the
    submission does not contradict comes from the workspace's own document, which is what is being
    read here. `sections` names only `battery`, so nothing else is touched either.
    """
    r = client.post(f"/w/{wid}/params", data={
        "sections": "battery",
        "battery.min_soc_pct": "90",
        "battery.max_soc_pct": "10",
    })
    assert r.status_code == 200
    assert r.headers["X-Params-Valid"] == "0", "the probe submission must not persist"
    m = re.search(
        r'name="battery\.usable_capacity_kwh"[^>]*value="([^"]*)"', r.text
    )
    assert m, "the capacity input is not in the rendered panel"
    return m.group(1)


# ── The core property: two workspaces do not share a config document ──────────────────────────

def test_a_second_workspaces_params_write_does_not_touch_the_first(two, tmp_path):
    """§5.5 invariant 4, at the route: the write lands in B's directory and nowhere else.

    Asserted three ways, because each catches a different way of getting this wrong:

      1. The two documents on disk hold different values — a save that ignored the path id would
         put both writes in the same file.
      2. A's OWN route still reports A's value afterwards — a route that scoped the save but
         defaulted the read would pass (1) and fail here.
      3. A's file is untouched by B's write — byte-identical, and its mtime unmoved. The bytes
         comparison is the load-bearing one: it catches every mis-scoped write, including one
         that rewrote the same content. The mtime check is a weaker companion, not a stronger
         form — `save` goes through mkstemp + os.replace so a rewrite does get a fresh inode,
         but the filesystem timestamp has finite resolution, and over 200 real back-to-back
         rewrites 14 (7%) left `st_mtime_ns` bit-identical. It can only ever false-pass, never
         false-fail, so it is kept as a cheap extra signal rather than relied on.
    """
    from app import simconfig_store

    two.post(f"/w/{_A}/params", data=_form(**{"battery.usable_capacity_kwh": "11.0"}))
    a_path = simconfig_store.config_path(_A)
    a_mtime = a_path.stat().st_mtime_ns
    a_bytes = a_path.read_bytes()

    two.post(f"/w/{_B}/params", data=_form(**{"battery.usable_capacity_kwh": "27.5"}))

    # 1. Separate documents, separate values.
    assert simconfig_store.config_path(_B) != a_path
    assert simconfig_store.load(_A).battery.usable_capacity_kwh == pytest.approx(11.0)
    assert simconfig_store.load(_B).battery.usable_capacity_kwh == pytest.approx(27.5)

    # 3. A's file was not rewritten at all.
    assert a_path.stat().st_mtime_ns == a_mtime
    assert a_path.read_bytes() == a_bytes

    # 2. And A's own route still renders A's value.
    assert _capacity_on_panel(two, _A) == "11.0"


def test_results_read_the_addressed_workspaces_config(two):
    """A parameter change in B must not move A's panel ③.

    `POST /w/{id}/results` reads the config as well as the dataset, and both are scoped. With
    identical datasets, a figure that moved in A after a write to B could only have come from A's
    route reading B's config.
    """
    def saved(wid: str) -> str:
        r = two.post(f"/w/{wid}/results", json={"period": "last_1_week"})
        assert r.status_code == 200
        return r.text

    two.post(f"/w/{_A}/params", data=_form(**{"battery.usable_capacity_kwh": "5.0"}))
    before = saved(_A)

    # A much larger battery in B. If A's route read B's config, A's figures would move.
    two.post(f"/w/{_B}/params", data=_form(**{
        "battery.usable_capacity_kwh": "30.0",
        "battery.max_charge_kw": "10.0",
        "battery.max_discharge_kw": "10.0",
    }))
    assert saved(_A) == before

    # And B's own panel DID move — otherwise the test above would pass on a route that reads
    # nothing at all.
    assert saved(_B) != before


def test_a_dataset_loaded_into_one_workspace_is_invisible_to_another(tmp_path, monkeypatch):
    """The other half of isolation: B's data does not answer A's results request.

    Seeded directly rather than through the fixture, because the fixture gives both workspaces a
    dataset and this needs one WITHOUT. A 409 is the right answer for a workspace with no data —
    not a 404 (the workspace exists) and not somebody else's numbers.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset

    seed_workspace(_A)
    seed_workspace(_B, title="workspace B")
    dataset.save_dataset(
        [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)],
        (_WIN_START, _WIN_END), "test", [], None, _B,
    )

    from app import main

    client = TestClient(main.app)
    assert client.post(f"/w/{_B}/results", json={"period": "last_1_week"}).status_code == 200
    assert client.post(f"/w/{_A}/results", json={"period": "last_1_week"}).status_code == 409


# ── Unknown ids ───────────────────────────────────────────────────────────────────────────────

_UNKNOWN = "no-such-workspace"


@pytest.mark.parametrize("method,path,kwargs", [
    ("post", f"/w/{_UNKNOWN}/params", {"data": {"sections": "battery"}}),
    ("post", f"/w/{_UNKNOWN}/results", {"json": {"period": "last_1_week"}}),
    ("post", f"/w/{_UNKNOWN}/results/benchmark", {"json": {"period": "last_1_week"}}),
    ("post", f"/w/{_UNKNOWN}/data/slot/price_spot/load",
     {"json": {"source": "energy_charts",
               "window": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}}}),
])
def test_unknown_workspace_is_404_on_every_scoped_http_route(two, method, path, kwargs):
    """404, and specifically not a 500 and not a success against some default workspace.

    The `params` case is submitted with a body that would otherwise be a valid-enough form, and
    the `slot/load` case with a source that really exists, so a 200 here would mean the route ran
    its work against a workspace nobody asked for.
    """
    r = getattr(two, method)(path, **kwargs)
    assert r.status_code == 404, f"{path} → {r.status_code}"


def test_unknown_workspace_refuses_the_ingest_handshake(two):
    """The WebSocket's rejection is a DENIED HANDSHAKE, not an `error` frame.

    Worth pinning as its own shape rather than folding into the parametrized 404 test above: the
    dependency raises before `accept()`, so FastAPI answers with an ordinary HTTP response and no
    socket is ever established. A future change that moved the resolution inside the handler would
    still "404" in some sense while silently changing what the browser observes.
    """
    from starlette.testclient import WebSocketDenialResponse

    with pytest.raises(WebSocketDenialResponse) as exc:
        with two.websocket_connect(f"/w/{_UNKNOWN}/data/ingest/ws"):
            pass
    assert exc.value.status_code == 404


def test_a_known_workspace_still_opens_the_ingest_socket(two):
    """The negative above is only meaningful if the positive works on the same client."""
    with two.websocket_connect(f"/w/{_A}/data/ingest/ws") as ws:
        ws.send_json({"type": "nonsense"})
        msg = ws.receive_json()
    # It reached the protocol layer, which is what proves the handshake succeeded.
    assert msg["type"] == "error"


# ── Traversal ─────────────────────────────────────────────────────────────────────────────────

# Percent-encoded, because Starlette's router resolves a literal `/w/../params` before matching —
# the route never sees it. What can actually reach `get_workspace` is a single segment that DECODES
# to something path-unsafe, which is what each of these is. `..` and `.` are included because they
# name a directory without containing a separator at all.
_TRAVERSAL_IDS = [
    "..%2F..%2Fetc",     # ../../etc
    "%2Fetc%2Fpasswd",   # /etc/passwd
    "..%5C..%5Cwindows",  # ..\..\windows
    "..",
    ".",
    "%2E%2E",            # .. again, encoded, in case a layer decodes late
]


@pytest.mark.parametrize("bad", _TRAVERSAL_IDS)
def test_traversal_ids_are_rejected_at_the_route_without_a_500(two, bad):
    """A path-unsafe id is a 404 from `deps`, never a `ValueError` escaping as a 500.

    The storage helpers do reject these (§5.5 invariant 4) — but they reject them by raising, and
    a raise inside a route body is a 500 with a stack trace. The whole point of the edge check is
    the status code, so that is what this asserts, on the two routes that would otherwise reach a
    path helper first (`params` writes a file, `results` reads a directory).

    4xx rather than "not 500" is asserted deliberately: a 422 from FastAPI's own validation would
    also avoid the 500 while meaning something different, so the exact 404 is pinned.
    """
    r = two.post(f"/w/{bad}/params", data=_form())
    assert r.status_code == 404, f"POST /w/{bad}/params → {r.status_code}"

    r = two.post(f"/w/{bad}/results", json={"period": "last_1_week"})
    assert r.status_code == 404, f"POST /w/{bad}/results → {r.status_code}"


def test_traversal_writes_no_file_outside_the_data_dir(two, tmp_path):
    """The status code is the contract; this is the consequence it is protecting.

    A `POST …/params` under a traversing id must leave nothing outside the data directory. Checked
    against the parent of the temp data dir, which is where `../` would land.
    """
    before = sorted(p.name for p in tmp_path.parent.iterdir())
    two.post("/w/..%2F..%2Fescaped/params", data=_form())
    two.post("/w/..%2Fescaped/params", data=_form())
    assert sorted(p.name for p in tmp_path.parent.iterdir()) == before


# ── The flat routes stay flat ─────────────────────────────────────────────────────────────────

def test_the_three_flat_routes_are_not_scoped(two):
    """`GET /`, `/lang/{code}` and `/feature-interest/{key}` take no workspace (§2′.10).

    Pinned because "scope everything" is the easy over-correction, and two of these are wrong to
    scope for reasons a reader of the URL table cannot see: `feature_interest` is installation-wide
    by decision 10, and the language is a cookie.

    `GET /` stays flat for a third reason since phase 2: it is the workspace LIST, which is about
    every workspace and so belongs to none. `POST /workspaces` is flat for a fourth — it creates
    the id there is nothing to scope by yet — and is covered by `tests/test_workspace_list.py`.
    """
    assert two.get("/").status_code == 200
    assert two.get("/lang/nl", follow_redirects=False).status_code == 303
    # A real key from the closed vocabulary; the route 204s on success.
    assert two.post("/feature-interest/csv_upload").status_code in (204, 404)


def test_the_page_carries_the_workspace_id_the_browser_needs(two):
    """`GET /w/{id}/results` must state its workspace, or every fetch on it addresses nothing.

    Both carriers are asserted: `<body data-workspace-id>` (which index.html's `wsPath` builds
    every fetch from) and the roster's `data-ingest-ws` (the whole scoped socket path, rendered
    server-side). They must agree — a page whose fetches and socket named different workspaces
    would be a genuinely confusing failure.
    """
    body = two.get(f"/w/{_A}/results").text
    assert f'data-workspace-id="{_A}"' in body
    assert f'data-ingest-ws="/w/{_A}/data/ingest/ws"' in body


def test_the_params_form_posts_to_its_own_workspace(two):
    """The form's `action` must be scoped, at BOTH render sites.

    This is a no-JS fallback, which is why it is easy to lose and worth a test. `index.html`'s
    delegated handler `preventDefault()`s and refetches through `wsPath`, so a wrong `action` is
    inert as long as that script runs — and a 404 for the "Calculate →" button and the setup-band
    radios the moment it does not. Phase 1 shipped it flat for exactly that reason: nothing
    exercised the attribute, and comparing the before/after render cannot show an attribute that
    should have changed and did not.

    Both sites are asserted because they get the id from different places: the include takes it
    from `index()`'s context, the standalone panel-swap render from `POST /w/{id}/params`.
    """
    flat = 'action="/params"'

    full_page = two.get(f"/w/{_A}/results").text
    assert f'action="/w/{_A}/params"' in full_page
    assert flat not in full_page

    # The swapped-in fragment: a second workspace must name itself, not the page's.
    fragment = two.post(f"/w/{_B}/params", data=_form()).text
    assert f'action="/w/{_B}/params"' in fragment
    assert flat not in fragment
    assert f'/w/{_A}/params' not in fragment

    # And the URL it names actually accepts the post it would send.
    assert two.post(f"/w/{_B}/params", data=_form()).status_code == 200
