"""Route tests for POST /results and index()'s computed panel ③ (specs §2.4, §3.2).

These exercise the Phase-2 wiring end-to-end through the FastAPI app: a synthetic dataset is
persisted into a temporary data dir (BATTERY_SIM_DATA_DIR), then the results route is driven with
presets, an explicit range, and the error inputs it must reject cleanly (never a 500).

The dataset is seeded with app.dataset.save_dataset over hand-built SeriesFrames (the same shape
tests/test_data_summary.py uses), so the route's real load_latest → resolve_window → results_from
path runs against known totals. The data dir is redirected per-test to a tmp path so the user's
real ./data is never touched; app.config.data_dir() reads the env var on each call, so the redirect
takes effect without reimporting app.main.

Covered:
    * a preset ("last_1_week") and the default (empty body) → 200 + an HTML fragment rooted at
      #panel-results;
    * an explicit start/end range → 200;
    * the fragment carries the zero-battery headline (import with battery == baseline);
    * bad inputs → clean 4xx (unknown preset, both period+range, end<=start, non-object body);
    * no dataset → 409.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame

# A fixed hourly window so totals are exact: 30 days × 24 h of 1 h intervals from 2026-01-01 UTC.
_DAYS = 30
_HOURS = _DAYS * 24
_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 1 + _DAYS, tzinfo=timezone.utc)


def _energy(name: str, per_interval: float, n: int = _HOURS) -> SeriesFrame:
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "energy", 3600, idx, np.full(n, float(per_interval)),
        np.zeros(n, dtype=QUALITY_DTYPE),
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient over a fresh temp data dir holding one seeded dataset.

    Redirects BATTERY_SIM_DATA_DIR to a tmp path (config.data_dir() reads it per call), then
    persists a minimal grid-meter dataset so load_latest() in the route returns it. app.main is
    imported after the env is set; its CONFIG/templates are data-dir-independent, so a plain import
    is enough — no reload gymnastics.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset  # imported under the redirected data dir

    frames = [
        _energy("grid_import_t1", 2.0),   # 2 kWh/h × 720 h = 1,440 kWh imported
        _energy("grid_export_t1", 0.0),
    ]
    dataset.save_dataset(frames, (_WIN_START, _WIN_END), "test", [], None)

    from app import main
    return TestClient(main.app)


def test_results_preset_returns_fragment(client):
    r = client.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    body = r.text
    # The swap target root and the panel identity are present (it is the _panel_results fragment).
    assert 'id="panel-results"' in body
    assert "RESULTS" in body or "RESULTATEN" in body


def test_results_default_body_is_full_year_clamped(client):
    # Empty body → default preset (last_1_year), clamped to the 30-day coverage.
    r = client.post("/results", json={})
    assert r.status_code == 200
    assert 'id="panel-results"' in r.text


def test_results_explicit_range(client):
    r = client.post(
        "/results",
        json={"start": "2026-01-05T00:00:00Z", "end": "2026-01-12T00:00:00Z"},
    )
    assert r.status_code == 200
    assert 'id="panel-results"' in r.text


def test_results_zero_battery_headline(client):
    # The zero-battery invariant is visible in the rendered fragment: import "with battery" equals
    # the baseline import, and grid-import-saved is 0.
    r = client.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    # Both breakdown rows show the same import figure (equal by construction this increment).
    # 7 days × 24 h × 2 kWh = 336 kWh over the clamped last-week window.
    assert "336 kWh" in r.text
    assert "0 kWh" in r.text  # avoided / charged / discharged all zero


def test_results_fragment_includes_data_glance_band(client):
    # The standalone POST /results fragment renders the repeated data-glance section (from the
    # shared _data_glance.html macro imported at the top of _panel_results.html) — proof the macro
    # import resolves in the standalone render() path, not just the full page. Panel ③'s copy
    # carries its OWN heading ("Your energy use during the selected period"), NOT panel ①'s title,
    # since it is scoped to the selected range.
    r = client.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    # The panel-③ section heading (default EN locale). Its NL is "Uw energieverbruik in de
    # geselecteerde periode".
    assert "Your energy use during the selected period" in r.text
    # Panel ①'s own title must NOT leak into panel ③'s copy.
    assert "Your data at a glance" not in r.text
    # And a group heading from the body, so it is the section body and not just an aria-label echo.
    assert "Imported" in r.text


def test_results_data_glance_styled_like_energy_savings(client):
    # Panel ③'s copy is framed to match the "Energy savings" section below it (§2.4): a
    # `divider divider-start` heading and NO card frame around the figures. Both dividers carry
    # the same classes, so the two sections read as peers.
    r = client.post("/results", json={"period": "last_1_week"})
    divider_cls = 'class="divider divider-start text-xs font-semibold uppercase tracking-wider'
    # Two dividers: the glance section and Energy savings, identically styled.
    assert r.text.count(divider_cls) == 2
    # The glance heading is inside a divider, not a card header. The title appears twice — the
    # section's aria-label first, then the divider's own text — so anchor on the second.
    head = r.text.index(
        "Your energy use during the selected period",
        r.text.index("Your energy use during the selected period") + 1,
    )
    assert divider_cls in r.text[head - 300 : head]
    # The old band's card frame is gone from this panel entirely.
    assert "card bg-base-100" not in r.text
    # Casing is presentation: the msgid stays sentence-case, CSS uppercases it.
    assert "Energy savings" in r.text
    assert "ENERGY SAVINGS" not in r.text


def test_index_renders_data_glance_inside_panel_1(client):
    # §2.3a: the full-coverage "Your data at a glance" figures render INSIDE panel ① — after the
    # Data-quality box, before the "Next: parameters →" CTA — not as a band between panels ① and ②.
    # (It used to be _panel_summary.html, included from index.html; that wrapper is gone.)
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    quality = body.index("Data quality")
    glance = body.index("Your data at a glance")
    cta = body.index("Next: parameters")
    assert quality < glance < cta, "the glance section must sit between Data quality and the CTA"
    # Panel ② must start only AFTER the CTA — i.e. the section is inside panel ①, not between the
    # two panels. "PARAMETERS" is panel ②'s collapsed-title label.
    assert cta < body.index("PARAMETERS")
    # Framed as a peer of the Data-quality card (bg-base-200), not the old free-standing band.
    assert 'class="card bg-base-200 border border-base-300" aria-label="Your data at a glance"' in body


def test_data_glance_is_translated_in_both_copies(client):
    # Regression: _data_glance.html is a MACRO, and `{% from … import %}` without `with context`
    # does not pass the importing template's context — including the gettext functions Jinja's i18n
    # extension installs per request. The macro's strings then FROZE at whichever locale rendered
    # first in the process and never changed again: a server that served an English page first
    # showed English inside the band forever (title, group headings, the ⓘ aria-labels), in BOTH
    # copies, while the rest of the page translated normally.
    #
    # Request English FIRST — that ordering is what reproduces it. Rendering Dutch first would
    # freeze the macro on Dutch and the Dutch assertions below would pass with the bug present.
    assert "Your data at a glance" in client.get("/", headers={"Cookie": "lang=en"}).text
    r = client.get("/", headers={"Cookie": "lang=nl"})
    assert r.status_code == 200
    assert "Uw gegevens in één oogopslag" in r.text  # the section title (panel ①)
    assert ">Net<" in r.text and ">Huishouden<" in r.text  # group headings from the macro body
    assert "Your data at a glance" not in r.text
    # The panel-③ fragment renders the same macro through a different route.
    r3 = client.post("/results", json={"period": "last_1_week"}, headers={"Cookie": "lang=nl"})
    assert "Uw energieverbruik in de geselecteerde periode" in r3.text
    assert ">Net<" in r3.text


def test_range_picker_states_the_day_count(client):
    # The selected window's length is stated ONCE per panel, in the range picker's coverage line
    # (dates · N days · resolution). It used to be repeated under the glance heading below; that
    # copy is gone, so this line is now the only place panel ③ says how long the range is.
    r = client.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    assert "· 7 days ·" in r.text
    assert "simulated hourly" in r.text


def test_slot_info_dialog_is_at_page_level(client):
    # Regression: the shared #slot-info-dialog used to live inside panel ①'s `.collapse-content`.
    # daisyUI puts `content-visibility: hidden` on a collapsed panel, and a <dialog> in such a
    # subtree still enters the top layer on showModal() — blocking every click on the page — but is
    # never painted. Collapsing panel ① and clicking any ⓘ in panel ③'s glance copy then froze the
    # page with no popup. It must sit at page level, outside every `.collapse`.
    body = client.get("/").text
    assert body.count('id="slot-info-dialog"') == 1
    dialog_at = body.index('id="slot-info-dialog"')
    # The panels live in <main>; the shared dialogs come after it. #pending-dialog is already
    # page-level, so the info dialog belonging on the same side of </main> pins the placement.
    assert dialog_at > body.index("</main>")
    assert body.index('id="pending-dialog"') > body.index("</main>")


def test_results_unknown_preset_400(client):
    r = client.post("/results", json={"period": "last_decade"})
    assert r.status_code == 400


def test_results_both_period_and_range_400(client):
    r = client.post(
        "/results",
        json={"period": "last_1_week", "start": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_results_inverted_range_400(client):
    r = client.post(
        "/results",
        json={"start": "2026-01-12T00:00:00Z", "end": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_results_bad_date_400(client):
    r = client.post("/results", json={"start": "not-a-date", "end": "2026-01-12T00:00:00Z"})
    assert r.status_code == 400


def test_results_no_dataset_409(tmp_path, monkeypatch):
    # A fresh data dir with NO dataset seeded → the route reports 409, not a 500.
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import main
    c = TestClient(main.app)
    r = c.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 409
