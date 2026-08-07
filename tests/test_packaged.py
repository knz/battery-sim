"""End-to-end checks against the BUILT PyInstaller bundle, not against the source tree.

Skipped unless `BATTERY_SIM_PACKAGED_BINARY` points at the executable that
`packaging/build-linux.sh` produces:

    packaging/build-linux.sh
    BATTERY_SIM_PACKAGED_BINARY=dist/battery-sim/battery-sim uv run pytest tests/test_packaged.py

Gated rather than always-on because an ordinary `pytest` run has no bundle to test, and because
building one takes minutes. The gate is an env var and not a marker so that CI can turn it on for
the packaging job alone.

## Why these particular checks, and why they cannot be done against the source tree

Every failure this file exists to catch is invisible from a source checkout, because a source
checkout has the whole site-packages tree and the whole repository on disk. Three shapes:

  * **A missing hidden import.** uvicorn resolves its protocol implementations from import
    STRINGS at runtime (`uvicorn/config.py`: WS_PROTOCOLS and friends), so PyInstaller cannot see
    them and a bundle can simply lack one. The WebSocket implementation is the dangerous case:
    without it, exactly one route — the Home Assistant ingest — breaks, and every HTTP test and
    every page stays green. `test_the_websocket_route_works` is the defence, and it is the reason
    this file exists at all.

  * **A missing data directory.** Templates, static files, locale catalogs and the shipped
    spot-price CSVs all resolve through `Path(__file__)`. A wrong `datas` entry in the spec
    surfaces as a 500 on whichever page needs it first, hours after the build.

  * **A data directory in the wrong PLACE.** `app/config.py::data_dir` has a `sys.frozen` guard
    that redirects the default away from `_REPO_ROOT / "data"` — which, inside a bundle, means
    inside the bundle. `test_the_data_directory_is_per_user_and_not_inside_the_bundle` is the only
    test in the suite that can observe that guard doing its job, because `sys.frozen` is only ever
    true here.

Main items:
    BINARY                          the bundle under test, or None when the gate is off.
    packaged_server                 the binary running on a free port, torn down by exact PID.
    _seeded_workspace               a real workspace, created before any WebSocket is opened.
    _fetch_in(url, lang)            a page rendered under an `Accept-Language` header.
    _NL_TRANSLATED                  msgid/msgstr pairs that only the Dutch catalog can produce.
    test_it_serves / _static / _templates_and_data …
    test_the_dutch_message_catalog_is_bundled   the `.mo` catalogs, by translated text.
    test_babel_locale_data_is_bundled           the CLDR data, by number separators.
    test_the_cldr_locale_data_is_in_the_bundle  the CLDR data, by reading `_internal` directly.
    test_the_websocket_route_works  a raw ws:// upgrade plus one in-protocol exchange.

Those last three are deliberately three tests and not one. An earlier version folded the catalog
check into the Babel check, and because the combined test asserted only on number separators, a
bundle missing the entire Dutch catalog passed it — see
`test_the_dutch_message_catalog_is_bundled` for the incident. One assertion per bundle entry is
what keeps a green run meaningful.

## Why the CLDR data is checked TWICE, differently

`test_babel_locale_data_is_bundled` probes it through a rendered page;
`test_the_cldr_locale_data_is_in_the_bundle` reads the files under `_internal`. The second was
added because the first is coupled to things a packaging test should not depend on: `f42690f` put
the month labels behind `{% if results.monthly_saved_eur %}`, and a TEMPLATE change failed a
PACKAGING test — days later, at release time, since this file only runs on a dispatch.

The end-to-end half now also runs unpackaged, on every push, as
`tests/test_i18n.py::test_the_chart_month_labels_are_localised_end_to_end`, where seeding a year
of data is a fixture rather than a built artifact. See
`changelog/20260807-packaged-test-coverage-implementation.md`; whether the page-rendering probe
here should now be narrowed or dropped is still open.
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

_ENV_BINARY = "BATTERY_SIM_PACKAGED_BINARY"

_binary = os.environ.get(_ENV_BINARY)
BINARY = Path(_binary).resolve() if _binary else None

pytestmark = pytest.mark.skipif(
    BINARY is None,
    reason=f"set {_ENV_BINARY} to the built bundle's executable to run the packaged checks",
)


def _free_port() -> int:
    """Same idiom as `tests/test_smoke.py::_free_port`."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def packaged_server(tmp_path_factory):
    """Run the built binary with `--no-browser` and yield `(base_url, data_dir)`.

    `XDG_DATA_HOME` is redirected at a temp directory and `BATTERY_SIM_DATA_DIR` is explicitly
    REMOVED from the environment. That combination is the point rather than mere hygiene: with the
    env var set, the launcher's `resolve_data_dir` would decide the location and the `sys.frozen`
    branch of `app/config.py::data_dir` would never run. Unsetting it forces the frozen default to
    be exercised, into a directory the test can then assert about.

    `--no-browser` because a native window (or a browser tab) on a CI machine is neither wanted nor
    available; the server is driven over HTTP, which is what `UiMode.NONE` exists for.
    """
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    xdg = tmp_path_factory.mktemp("xdg")

    env = {k: v for k, v in os.environ.items() if k != "BATTERY_SIM_DATA_DIR"}
    env["XDG_DATA_HOME"] = str(xdg)

    server = subprocess.Popen(
        [str(BINARY), "--no-browser", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Same 20s deadline and 0.2s poll as the smoke test's startup wait. A cold start of a frozen
    # bundle is slower than a source run — the bootloader unpacks and the PYZ archive is read.
    deadline = time.time() + 20
    while time.time() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"the packaged server exited early:\n{server.stdout.read()}")
        try:
            urlopen(url + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        server.terminate()
        raise RuntimeError("the packaged server did not start")

    yield url, xdg / "battery-sim"

    # Terminate THIS process by its own handle and nothing else. A pattern-based kill would be
    # wrong here in a way that matters: a developer running these tests is very likely to have
    # their own copy of the app running on this machine.
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


@pytest.fixture(scope="module")
def _seeded_workspace(packaged_server):
    """A real workspace id, created through the app's own POST route.

    **The WebSocket test depends on this and would misreport without it.** An unknown workspace id
    fails the ingest route's HANDSHAKE with an HTTP 404 rather than with an in-protocol error (by
    design — see the route in `app/main.py`). So a bundle whose WebSocket support is perfectly
    intact looks broken if the test opens `ws://…/w/<made-up-id>/…`, and the packaging bug this
    file is meant to catch would be indistinguishable from the test's own mistake.
    """
    base_url, _ = packaged_server
    from urllib.request import Request

    req = Request(base_url + "/workspaces", data=b"", method="POST")
    with urlopen(req) as r:
        return r.url.split("?")[0].rstrip("/").split("/")[-2]


def _get(url: str) -> tuple[int, bytes]:
    from urllib.error import HTTPError

    try:
        with urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, e.read()


def test_it_serves_the_workspace_list(packaged_server):
    base_url, _ = packaged_server
    status, body = _get(base_url + "/")
    assert status == 200
    assert b"<html" in body.lower()


def test_the_data_directory_is_per_user_and_not_inside_the_bundle(packaged_server):
    """The `sys.frozen` guard's whole purpose, and the only place it can be observed.

    Two assertions, and the second is the one with teeth. That the per-user directory exists shows
    the guard chose a location; that no file was written under the bundle shows it did not choose
    `_REPO_ROOT / "data"`, which inside a frozen build resolves into the bundle itself — read-only
    on a signed macOS .app, and under onefile a temp directory deleted on exit, taking every
    workspace with it.
    """
    _, data_dir = packaged_server
    assert data_dir.is_dir(), f"the frozen build did not create {data_dir}"
    # The launcher writes this; its presence proves real state landed here rather than the
    # directory merely having been created. This used to be `config.toml`, written by an
    # import-time `config.load()` — a call that went with the feature-interest telemetry, leaving
    # the app writing no config file at all.
    assert (data_dir / "desktop.lock").is_file()

    bundle_root = BINARY.parent
    stray = [p for p in bundle_root.rglob("desktop.lock")]
    assert not stray, f"the frozen build wrote state into the bundle: {stray}"


def test_the_single_instance_lock_records_the_live_port(packaged_server):
    _, data_dir = packaged_server
    state = json.loads((data_dir / "desktop.lock").read_text())
    assert set(state) == {"port", "pid"}
    assert state["port"] == int(packaged_server[0].rsplit(":", 1)[1])


def test_static_files_are_bundled(packaged_server):
    """`app/static` reached the bundle — the Tailwind output and the HA fetch module."""
    base_url, _ = packaged_server
    for path in ("/static/app.css", "/static/ha_fetch.js"):
        status, body = _get(base_url + path)
        assert status == 200, path
        assert len(body) > 1000, f"{path} is suspiciously small ({len(body)} bytes)"


def test_the_build_info_module_is_readable_as_a_FILE_in_the_bundle():
    """`_internal/app/_build_info.py` must exist ON DISK, not only inside the PYZ archive.

    Two different consumers, and only one of them can use the imported copy:

      * the application imports it, and gets the compiled copy out of the PYZ;
      * `packaging/build-appimage.sh` READS IT AS A FILE, to put the commit SHA into the
        .desktop entry's X-AppImage-Version.

    The spec's DATAS list collects it a second time for the second consumer. This test exists
    because the first version of that change did NOT — the module was only in the PYZ, the
    script's lookup found nothing on every build, and the AppImage silently shipped a version
    string with no SHA in it. Nothing failed; the label was just quietly wrong.
    """
    binary = Path(os.environ[_ENV_BINARY]).resolve()
    build_info = binary.parent / "_internal" / "app" / "_build_info.py"

    assert build_info.is_file(), (
        f"{build_info} is missing. packaging/build-appimage.sh reads this path to stamp the "
        "commit SHA into the desktop entry; without it the AppImage loses its provenance "
        "silently. Check the DATAS list in packaging/battery-sim.spec."
    )
    text = build_info.read_text()
    assert "BUILD_SHA" in text
    assert "BUILD_SHA_SOURCE" in text


def test_templates_and_the_shipped_data_render_a_results_screen(packaged_server, _seeded_workspace):
    """One page that needs `app/templates` AND `app/data` — the committed spot prices.

    A results screen prices its counterfactual off the shipped ENTSO-E/Energy-Charts CSVs, so a
    200 here exercises both `datas` entries at once.
    """
    base_url, _ = packaged_server
    status, body = _get(f"{base_url}/w/{_seeded_workspace}/results")
    assert status == 200
    assert b"kWh" in body


def _fetch_in(url: str, lang: str) -> str:
    """`url` rendered under `Accept-Language: lang`.

    A header rather than the `lang` cookie the smoke tests pin, because what the two locale tests
    below check is the whole negotiation path — `app/i18n.py::resolve_locale` picking a locale and
    the catalog for it actually loading — and the header is the input a real first-time visitor
    arrives with.
    """
    from urllib.request import Request

    req = Request(url, headers={"Accept-Language": lang})
    with urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8")


# Strings that exist ONLY in the Dutch catalog, paired with the English source strings they
# replace. Verified against `app/locales/nl/LC_MESSAGES/messages.mo` — each is a real msgid/msgstr
# pair, not a coincidence of Dutch and English spelling — and all three are section HEADINGS on
# the results screen, so they are rendered on a page this file already fetches.
#
# Three rather than one so that a single msgid being retired upstream fails loudly on that pair
# instead of silently weakening the check to nothing.
_NL_TRANSLATED = [
    ("Batterij", "Battery"),
    ("Laadstrategie", "Charge policy"),
    ("Waar de energie vandaan komt", "Where the energy comes from"),
]

_HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.DOTALL | re.IGNORECASE)


def _headings(page: str) -> list[str]:
    """The text of every `<h1>`..`<h6>` on the page, tags stripped and whitespace collapsed.

    The locale assertions run against these rather than against the raw HTML, and that is a
    correctness point rather than tidiness. The results screen carries inline `<script>` blocks
    whose COMMENTS are English prose — one of them contains the word "Battery" — so a raw
    substring search for an untranslated English heading finds a JavaScript comment and reports a
    translation failure that is not one. Headings are markup the translation actually owns.
    """
    out = []
    for raw in _HEADING_RE.findall(page):
        text = re.sub(r"<[^>]+>", " ", raw)
        out.append(" ".join(text.split()))
    return out


def test_the_dutch_message_catalog_is_bundled(packaged_server, _seeded_workspace):
    """`app/locales/nl` reached the bundle AND its `.mo` is actually being read.

    **This test exists because its absence let a real hole through.** The check here used to be
    folded into the Babel test below, which asserts only on number separators — and those come
    from Babel's CLDR data, not from the gettext catalogs. A review built a bundle with
    `_internal/app/locales/nl/` deleted outright and the whole packaged suite stayed green, while
    that bundle served "New analysis" to a Dutch request. For a product whose users are Dutch
    households, shipping it fully untranslated is close to the worst outcome the packaging step
    can produce, and nothing was watching for it.

    `app/desktop.py::check_assets` does not backstop it either: `_ASSET_DIRS` asks whether
    `locales/` is a non-empty directory, which stays true when only the `nl/` subtree is removed.

    The assertion is two-sided on purpose. Requiring the Dutch string to be PRESENT catches the
    missing catalog; requiring the English source string to be ABSENT catches the subtler case
    where the catalog is present but not consulted, which would otherwise look identical to a
    passing run for any msgid whose translation happens to be reachable some other way.

    Both sides run against the page's HEADINGS rather than its raw HTML — see `_headings` for the
    false positive that costs.
    """
    base_url, _ = packaged_server
    page = _fetch_in(f"{base_url}/w/{_seeded_workspace}/results", "nl")
    headings = _headings(page)
    assert headings, "the Dutch results screen rendered no headings at all"

    for dutch, english in _NL_TRANSLATED:
        assert dutch in headings, (
            f"{dutch!r} is not a heading on the Dutch results screen — the nl catalog is not in "
            f"the bundle, or is not being loaded. Headings seen: {headings}"
        )
        assert english not in headings, (
            f"{english!r} was served untranslated to a Dutch request — the nl catalog is present "
            "but not being consulted"
        )


def test_babel_locale_data_is_bundled(packaged_server, _seeded_workspace):
    """Babel's CLDR data reached the bundle — a SEPARATE entry from the message catalogs.

    `collect_data_files("babel")` in the spec, and it is the easy one to lose: it is data rather
    than importable modules, so nothing in the import graph refers to it and PyInstaller would not
    collect it on its own. Its absence raises `UnknownLocaleError` out of `Locale.parse`, at
    runtime and in the packaged build only.

    Since the CLDR set is now TRIMMED to `app/i18n.py::SUPPORTED` (see
    `packaging/battery_sim_babel_locales.py`), this test also guards the trim: a keep-set that
    dropped one of the app's own languages would fail here rather than on a user's machine.

    Two independent assertions, because they catch different mistakes:

    **Number separators** isolate Babel from the gettext catalogs the test above covers. Dutch
    groups thousands with `.` and takes `,` as the decimal point, English the reverse; no message
    catalog can produce that difference, and a bundle without `nl.dat` cannot produce the Dutch
    form at all — it raises `UnknownLocaleError` and the page 500s.

    **Month names** catch the case the separators cannot: a silent fall back to `root`. `root` and
    `en` format numbers IDENTICALLY, so an over-aggressive trim that dropped `en.dat` while keeping
    `root` would satisfy the separator check while quietly serving `M01 M02 M03` where a reader
    expects `Jan Feb Mar`. That is the specific way an English bundle can look right and be wrong,
    and it is only visible here.
    """
    base_url, _ = packaged_server
    url = f"{base_url}/w/{_seeded_workspace}/results"
    nl, en = _fetch_in(url, "nl"), _fetch_in(url, "en")

    # A grouped four-digit-or-more number, in each locale's own convention.
    assert re.search(r"\d{1,3}\.\d{3}", nl), "no Dutch-grouped number on the nl results screen"
    assert re.search(r"\d{1,3},\d{3}", en), "no English-grouped number on the en results screen"

    # The monthly chart's axis, rendered by the `monthname` filter (`app/i18n.py::month_abbr`)
    # straight out of CLDR. `M01`-style labels are root's placeholders and mean the real locale
    # data was not found.
    assert re.search(r"\bMar\b", en), "no CLDR English month abbreviation on the en results screen"
    assert re.search(r"\bmrt\b", nl), "no CLDR Dutch month abbreviation on the nl results screen"
    for page, lang in ((en, "en"), (nl, "nl")):
        assert not re.search(r"\bM0[1-9]\b", page), (
            f"the {lang} results screen shows root's placeholder month labels — Babel fell back "
            "to `root`, so that locale's .dat file is missing from the bundle"
        )


def test_the_websocket_route_works(packaged_server, _seeded_workspace):
    """The check this whole file is built around — see the module docstring.

    `app/desktop.py` pins `ws="websockets-sansio"` and the spec lists the matching module as a
    hidden import. Neither half is observable from a source run, where the module is on the path
    regardless. If the hidden import were dropped, uvicorn's `import_from_string` would fail and
    this test is the only one in the suite that would notice.

    The exchange goes past the handshake deliberately. An upgrade that completes proves the
    protocol implementation loaded; a `progress` frame coming back proves it can actually carry
    frames in both directions, which is what the Home Assistant ingest needs.
    """
    import asyncio

    websockets = pytest.importorskip("websockets")

    base_url, _ = packaged_server
    ws_url = base_url.replace("http://", "ws://") + f"/w/{_seeded_workspace}/data/ingest/ws"

    async def exchange():
        # `origin` supplied because the app's CSRF posture inspects it; without one the connection
        # is still allowed, but sending it is what a real browser does.
        async with websockets.connect(ws_url, origin=base_url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "header",
                        "source": "home_assistant",
                        "window": {
                            "start": "2025-01-01T00:00:00+00:00",
                            "end": "2025-01-02T00:00:00+00:00",
                        },
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "series",
                        "name": "grid_import_t1",
                        "unit": "kWh",
                        "kind": "energy",
                        "resolution_minutes": 60,
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "rows",
                        "name": "grid_import_t1",
                        "rows": [[1735689600000, 0.5], [1735693200000, 0.7]],
                    }
                )
            )
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=15))

    reply = asyncio.run(exchange())
    assert reply == {"type": "progress", "name": "grid_import_t1", "rows": 2}


def test_the_cldr_locale_data_is_in_the_bundle():
    """Babel's CLDR `.dat` files reached `_internal`, asserted on the FILES rather than on a page.

    The bundle-level half of what `test_babel_locale_data_is_bundled` above checks end to end, and
    it exists because that test's probe is coupled to things it has no business depending on. It
    renders a results screen and greps for month names, so `f42690f` broke it by putting the month
    node behind `{% if results.monthly_saved_eur %}` — a template change, failing a packaging test,
    discovered days later at release time. This one reads the filesystem: no route, no template, no
    view-model, no simulation.

    The end-to-end property is not lost by having this — it moved to
    `tests/test_i18n.py::test_the_chart_month_labels_are_localised_end_to_end`, where it runs on
    every push and where seeding a year of data is a fixture rather than a built artifact.

    **The keep-set is IMPORTED, not restated.** `babel_locale_keep_set()` is the same function
    `packaging/hooks/hook-babel.py` filters with, so this asserts that what the hook intended to
    keep actually arrived. A hardcoded `{"en", "nl", "root"}` here would pass even after someone
    added a language to `SUPPORTED` and the trim silently failed to follow — which is precisely the
    regression the trim can introduce.

    `root.dat` matters as much as the language files: babel's `localedata.load` merges it underneath
    every other locale, so losing it breaks all of them at once rather than one. It is in the
    keep-set for that reason, and is covered here by iterating that set.
    """
    # `packaging/` is not a package and is not importable by default; anchored to THIS file's
    # repository rather than to the bundle's location, which the env var may point anywhere.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    try:
        from battery_sim_babel_locales import babel_locale_keep_set
    finally:
        sys.path.pop(0)

    locale_data = BINARY.parent / "_internal" / "babel" / "locale-data"
    assert locale_data.is_dir(), (
        f"{locale_data} is missing entirely — babel's CLDR data did not reach the bundle. "
        "Check that packaging/hooks/hook-babel.py is on hookspath and still collects."
    )

    present = {p.stem for p in locale_data.glob("*.dat")}
    missing = babel_locale_keep_set() - present
    assert not missing, (
        f"the CLDR data for {sorted(missing)} is missing from the bundle. These are the locales "
        "packaging/hooks/hook-babel.py's keep-set says to ship; without one of them "
        "`Locale.parse` falls back to `root` and that language formats numbers and month names "
        f"wrongly. Present: {sorted(present)}"
    )

    # `global.dat` lives OUTSIDE locale-data/ and carries the territory and `parent_exceptions`
    # tables `Locale.parse` needs for ANY locale — the hook keeps it deliberately (see `_keep`),
    # so its absence would mean the filter over-matched.
    assert (BINARY.parent / "_internal" / "babel" / "global.dat").is_file(), (
        "babel/global.dat is missing — the locale-data filter in packaging/hooks/hook-babel.py "
        "over-matched and removed a file outside locale-data/."
    )


def test_the_bundle_carries_no_development_directories():
    """`external_data/`, `node_modules/`, `tests/` and `docs/specs/` must not be in the bundle.

    A cheap structural assertion next to `build-linux.sh`'s size gate. The gate catches a large
    leak by weight; this catches a small one by name, and names which directory leaked rather than
    leaving someone to read a `du` listing.
    """
    internal = BINARY.parent / "_internal"
    for forbidden in ("external_data", "node_modules", "tests", "specs", "changelog"):
        assert not (internal / forbidden).exists(), f"{forbidden}/ leaked into the bundle"
