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
    * the fragment carries REAL simulated figures, including an honestly-rendered negative saving;
    * bad inputs → clean 4xx (unknown preset, both period+range, end<=start, non-object body);
    * no dataset → 409;
    * §2.4's COST SAVINGS section, end to end: present exactly when the STORED `simulate_cost` is
      on, the "enable cost simulation" affordance offered exactly when it is not, the rendered
      energy half unchanged across the toggle (fixture 18 on the HTML rather than on the data),
      the Charts box gaining a euro option rather than swapping the kWh one, and the money
      benchmark gated on `simulate_cost` as well as on `with_benchmark`;
    * the Phase 7 cost tint: the COST SAVINGS half's divider, headings and MONEY SAVED tile carry
      .cost-label and their ENERGY SAVINGS counterparts do not;
    * §6.16's pricing-uncertainty caveat reaching the served markup with its figures substituted,
      and leaving it when the supplier bills the hourly mean (D10).
"""

from __future__ import annotations

import importlib
import re
from datetime import date, datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame
from tests.conftest import (
    WORKSPACE_ID,
    ids_inside,
    page,
    seed_workspace,
    split_panels,
    w,
)

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
    dataset.save_dataset(frames, (_WIN_START, _WIN_END), "test", [], None, workspace_id=WORKSPACE_ID)
    # The routes are workspace-scoped now, and `TestClient(app)` outside a `with` block skips the
    # lifespan that would have adopted this data dir's workspace — so create the row explicitly.
    seed_workspace()

    from app import main
    return TestClient(main.app)


def test_results_preset_returns_fragment(client):
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    body = r.text
    # The swap target root and the panel identity are present (it is the _panel_results fragment).
    assert 'id="panel-results"' in body
    assert "RESULTS" in body or "RESULTATEN" in body


def test_self_sufficiency_info_button_renders_on_both_paths(client):
    """The ⓘ next to SELF-SUFFICIENCY reaches the HTML on the full page AND the swapped fragment.

    The view-model side is pinned in test_results_view; this is the wiring. It matters on BOTH
    paths because the panel is replaced wholesale on every period change: the button's handler is
    delegated from `document` in ha_fetch.js and #slot-info-dialog lives outside the swap, so a
    fragment that renders the button keeps working — but only if the fragment renders it.
    """
    for body in (client.get(page()).text,
                 client.post(w("/results"), json={"period": "last_1_week"}).text):
        i = body.find("SELF-SUFFICIENCY")
        assert i != -1
        # The button belongs to THIS tile: look only at the markup up to the next tile.
        tile = body[i:i + 2000]
        assert "slot-info-btn" in tile
        assert 'data-info-title="Self-sufficiency"' in tile
        assert "the left figure is the baseline" in tile.lower()
        # The accessible name uses the sentence-case title, not the shouty display heading.
        assert 'aria-label="About SELF-SUFFICIENCY"' not in tile


def test_grid_import_baseline_row_info_button_renders(tmp_path, monkeypatch):
    """The ⓘ on "Grid import, no battery", whose body is an `_msg` pair rather than a flat string.

    Worth a route test of its own precisely because of that: the body carries runtime kWh figures,
    so it renders through the `msg()` macro into an HTML attribute. A pair reaching the attribute
    unrendered would show up here as a literal "%(meter)s".

    It does NOT use the `client` fixture: that dataset exports nothing, so the meter's import and
    run A's coincide, no discrepancy exists and the ⓘ is correctly absent. Simultaneous import and
    export in the same hour is the only thing that raises it (the §7.1 overlap), so this builds its
    own dataset with export — otherwise the test would pass while asserting nothing.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import dataset

    dataset.save_dataset(
        [_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 1.0),
         _energy("solar_production", 3.0)],
        (_WIN_START, _WIN_END), "test", [], None,
        workspace_id=WORKSPACE_ID,
    )
    seed_workspace()
    from app import main
    c = TestClient(main.app)

    for body in (c.get(page()).text,
                 c.post(w("/results"), json={"period": "last_1_week"}).text):
        i = body.find("Grid import, no battery")
        assert i != -1
        row = body[max(0, i - 900):i + 900]
        assert "slot-info-btn" in row
        assert 'data-info-title="Grid import, no battery"' in row
        # The pair was rendered: placeholders substituted, both figures present, and the caveat's
        # own wording (not a dict repr) in the attribute.
        assert "%(meter)s" not in row and "%(baseline)s" not in row
        assert "Your meter recorded" in row
        assert "msgid" not in row, "an unrendered _msg pair reached the attribute"


def test_results_default_body_is_full_year_clamped(client):
    # Empty body → default preset (last_1_year), clamped to the 30-day coverage.
    r = client.post(w("/results"), json={})
    assert r.status_code == 200
    assert 'id="panel-results"' in r.text


def test_results_explicit_range(client):
    r = client.post(
        w("/results"),
        json={"start": "2026-01-05T00:00:00Z", "end": "2026-01-12T00:00:00Z"},
    )
    assert r.status_code == 200
    assert 'id="panel-results"' in r.text


def test_an_explicit_range_comes_back_as_custom_not_as_the_nearest_preset(client):
    """The selector highlights "custom" for a range, and keeps the date fields open.

    `_period_selected_for` maps a window's SPAN back to the nearest preset, which is all it can do
    with two datetimes — so a 7-day explicit range used to come back highlighted as "1 week" with
    the picker hidden again, i.e. showing the user a preset they had not chosen and taking away the
    control they had just used. The route therefore tells the view-model that the request carried
    start/end (`results_from(custom_range=True)`), which is the only place that fact exists.
    """
    card, _ = split_panels(
        client.post(
            w("/results"),
            json={"start": "2026-01-05T00:00:00Z", "end": "2026-01-12T00:00:00Z"},
        ).text
    )
    # The custom button is active and NO preset is — exactly one choice reads as selected.
    assert 'id="results-period-custom"' in card
    custom_tag = re.search(r'<button[^>]*id="results-period-custom"[^>]*>', card).group(0)
    assert "btn-active" in custom_tag, custom_tag
    assert 'aria-expanded="true"' in custom_tag, custom_tag
    assert "btn-active" not in card[: card.index('id="results-period-custom"')], (
        "a preset is highlighted alongside custom"
    )
    # The date row is NOT hidden, and carries the applied window.
    row = re.search(r'<div[^>]*id="results-range"[^>]*>', card).group(0)
    assert "hidden" not in row, row
    assert 'value="2026-01-05"' in card
    assert 'value="2026-01-12"' in card


def test_a_preset_leaves_the_date_row_hidden_and_custom_inactive(client):
    """The other half of the same contract: a preset window is not "custom".

    Asserted because the flag defaults to False — a regression that dropped the argument at the
    call site would leave every window looking custom, and only this direction would catch it.
    """
    card, _ = split_panels(client.post(w("/results"), json={"period": "last_1_week"}).text)
    custom_tag = re.search(r'<button[^>]*id="results-period-custom"[^>]*>', card).group(0)
    assert "btn-active" not in custom_tag, custom_tag
    assert 'aria-expanded="false"' in custom_tag, custom_tag
    row = re.search(r'<div[^>]*id="results-range"[^>]*>', card).group(0)
    assert "hidden" in row, row
    # The preset the caller asked for is the one highlighted. `class` precedes `data-period` in the
    # tag, so match the whole button rather than assuming an attribute order.
    week = re.search(r'<button[^>]*data-period="last_1_week"[^>]*>', card).group(0)
    assert "btn-active" in week, week


def test_the_date_format_hint_is_inside_the_collapsible_picker(client):
    """The hint hides with the fields it describes.

    It explains which order the two date inputs are in, so on screen without them it explains the
    format of fields the reader cannot see. It was a SIBLING of the collapsible row at first, which
    left it visible under a collapsed picker — the `hidden` class governs one element, not the
    markup that happens to follow it. Asserted structurally rather than through the browser, since
    it is nesting that makes it true.
    """
    card, _ = split_panels(client.post(w("/results"), json={"period": "last_1_week"}).text)
    # Real containment, not index order: "the hint appears after the row's opening tag" is true of
    # the arrangement this test exists to reject, so only nesting answers the question.
    inside = ids_inside(card, "results-range")
    assert "results-range-format" in inside, (
        "the format hint is outside the collapsible picker, so it stays visible when it collapses"
    )
    # The fields it describes are in there too.
    assert "results-range-start" in inside and "results-range-end" in inside, inside
    # And it is the containing element that carries the hidden state.
    row_tag = re.search(r'<div[^>]*id="results-range"[^>]*>', card).group(0)
    assert "hidden" in row_tag, row_tag


def test_the_date_fields_are_prefilled_with_the_effective_window(client):
    """Opening the picker shows the range in force, not blank fields.

    The values are the EFFECTIVE window — after resolve_window clamps to coverage — so a request
    reaching past the data shows what was actually simulated. The fixture's coverage is 30 days, so
    a one-year preset clamps, and the fields must show the clamped ends rather than a year ago.
    """
    card, _ = split_panels(client.post(w("/results"), json={"period": "last_1_year"}).text)
    start = re.search(r'id="results-range-start"[^>]*value="([^"]*)"', card).group(1)
    end = re.search(r'id="results-range-end"[^>]*value="([^"]*)"', card).group(1)
    assert start and end, (start, end)
    # Clamped to the fixture's coverage, so the span is the ~30 days of data, not 365.
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days
    assert 0 < span <= 31, (start, end, span)


def test_results_headline_carries_real_simulated_figures(client):
    """The rendered fragment shows a REAL run, and renders a negative saving honestly end-to-end.

    The fixture is 2 kWh/h of import, no PV and no price, so over the clamped last-week window the
    simulated baseline imports 7 × 24 × 2 = 336 kWh. With no price series the default P3 charge
    band never opens (a NaN spot fails both band comparisons), so the battery only discharges its
    initial 5.0 kWh down to the 10% floor — 4.0 kWh withdrawn, 4.0 × sqrt(0.9) = 3.79 kWh delivered
    AC — while its standby draw costs 0.030 kW × 168 h = 5.04 kWh. The saving is therefore

        3.79 − 5.04 = −1.25 kWh

    i.e. NEGATIVE, which §7.2 item 9 says is correct output. The presentation must show it as a
    cost: the row is captioned "Extra grid import", not "avoided", and the with-battery import
    (337 kWh) is HIGHER than the baseline (336 kWh).
    """
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    assert "336 kWh" in r.text          # simulated baseline import
    assert "337 kWh" in r.text          # with battery — higher, because the battery cost energy
    assert "Extra grid import" in r.text
    assert "Grid import avoided" not in r.text
    assert "Discharged from the battery" in r.text
    # And the zero-battery caveat the previous increment always emitted is gone.
    assert "No battery is configured" not in r.text


def test_results_fragment_includes_data_glance_band(client):
    # The standalone POST /results fragment renders the repeated data-glance section (from the
    # shared _data_glance.html macro imported at the top of _panel_results.html) — proof the macro
    # import resolves in the standalone render() path, not just the full page. Panel ③'s copy
    # carries its OWN heading ("Your energy use during the selected period"), NOT panel ①'s title,
    # since it is scoped to the selected range.
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    # The panel-③ section heading (default EN locale). Its NL is "Je energieverbruik in de
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
    r = client.post(w("/results"), json={"period": "last_1_week"})
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
    # The old band's card frame is gone from this panel entirely. Scoped to the results half of the
    # response: the period card beside it IS a `card bg-base-100`, by the same house style every
    # top-level card on the screen uses, and it is not what this assertion is about.
    assert "card bg-base-100" not in split_panels(r.text)[1]
    # Casing is presentation: the msgid stays sentence-case, CSS uppercases it.
    assert "Energy savings" in r.text
    assert "ENERGY SAVINGS" not in r.text


def test_the_data_screen_renders_the_full_coverage_glance_after_the_quality_box(client):
    """§2.3a: the full-coverage glance sits AFTER the Data-quality box, framed as its peer.

    **On `/w/{id}/data` since phase 4.2**, not on the results page. It was panel ①'s copy and this
    test asserted its position relative to the `[ Next: parameters → ]` CTA and panel ②'s title;
    §2′.5 replaced that CTA with a footer and §2′.6 deleted panel ①, so both landmarks are gone and
    the ordering rule moved to the screen that still draws the two boxes.

    The results page's own copy — the RANGE-CLAMPED one, `frame='divider'` — is a different
    section with different figures and is covered by the tests below.
    """
    from tests.conftest import data_page

    r = client.get(data_page())
    assert r.status_code == 200
    body = r.text
    quality = body.index("Data quality")
    glance = body.index("Your data at a glance")
    assert quality < glance, "the glance must sit after the Data-quality box"
    # Framed as a peer of the Data-quality card (bg-base-200), not a free-standing band.
    assert 'class="card bg-base-200 border border-base-300" aria-label="Your data at a glance"' in body
    # …and it is inside the page's <main>, not appended after it with the shared dialogs.
    assert glance < body.index("</main>")


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
    #
    # The full-coverage copy is on `/w/{id}/data` since phase 4.2 (panel ① moved there in 4.1 and
    # was deleted from the results page in 4.2); the range-clamped copy is still inside the results
    # fragment. Two screens rather than two panels, but the same two render sites for one macro,
    # which is what the regression was about.
    from tests.conftest import data_page

    assert "Your data at a glance" in client.get(data_page(), headers={"Cookie": "lang=en"}).text
    r = client.get(data_page(), headers={"Cookie": "lang=nl"})
    assert r.status_code == 200
    assert "Je gegevens in één oogopslag" in r.text  # the section title (configure data)
    assert ">Net<" in r.text and ">Huishouden<" in r.text  # group headings from the macro body
    assert "Your data at a glance" not in r.text
    # The Grid group's "as your meter recorded them" caption is in the macro body too, so it must
    # translate in both copies like every other string there.
    assert "zoals je meter ze heeft geregistreerd" in r.text
    assert "as your meter recorded them" not in r.text
    # The results fragment renders the same macro through a different route.
    r3 = client.post(w("/results"), json={"period": "last_1_week"}, headers={"Cookie": "lang=nl"})
    assert "Je energieverbruik in de geselecteerde periode" in r3.text
    assert ">Net<" in r3.text
    assert "zoals je meter ze heeft geregistreerd" in r3.text


def test_range_picker_states_the_day_count(client):
    # The selected window's length is stated ONCE per panel, in the range picker's coverage line
    # (dates · N days · resolution). It used to be repeated under the glance heading below; that
    # copy is gone, so this line is now the only place panel ③ says how long the range is.
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    assert "· 7 days ·" in r.text
    assert "simulated hourly" in r.text


def test_slot_info_dialog_is_at_page_level(client):
    # Regression: the shared #slot-info-dialog used to live inside panel ①'s `.collapse-content`.
    # daisyUI puts `content-visibility: hidden` on a collapsed panel, and a <dialog> in such a
    # subtree still enters the top layer on showModal() — blocking every click on the page — but is
    # never painted. Collapsing panel ① and clicking any ⓘ in panel ③'s glance copy then froze the
    # page with no popup. It must sit at page level, outside every `.collapse`.
    body = client.get(page()).text
    assert body.count('id="slot-info-dialog"') == 1
    dialog_at = body.index('id="slot-info-dialog"')
    # The panels live in <main>; the shared dialogs come after it. #pending-dialog is already
    # page-level, so the info dialog belonging on the same side of </main> pins the placement.
    assert dialog_at > body.index("</main>")
    assert body.index('id="pending-dialog"') > body.index("</main>")


def test_results_unknown_preset_400(client):
    r = client.post(w("/results"), json={"period": "last_decade"})
    assert r.status_code == 400


def test_results_both_period_and_range_400(client):
    r = client.post(
        w("/results"),
        json={"period": "last_1_week", "start": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_results_inverted_range_400(client):
    r = client.post(
        w("/results"),
        json={"start": "2026-01-12T00:00:00Z", "end": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_results_bad_date_400(client):
    r = client.post(w("/results"), json={"start": "not-a-date", "end": "2026-01-12T00:00:00Z"})
    assert r.status_code == 400


def test_results_no_dataset_409(tmp_path, monkeypatch):
    # A fresh data dir with the workspace but NO dataset seeded → 409, not a 500 and not a 404.
    # The distinction matters now that the route resolves a workspace first: "this workspace has
    # no data" (409) and "there is no such workspace" (404) are different answers.
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    seed_workspace()
    from app import main
    c = TestClient(main.app)
    r = c.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 409


# ── POST /results/benchmark — the lazily-fetched §6.12 box ────────────────────────────────────
#
# Why the route exists: the DP behind that box costs ~2.3 s per pass on a year of hourly data
# (~4.6 s for both export baselines) against ~0.12 s for everything else on panel ③, and running it
# inline made GET / take 4.72 s. The panel now paints without it and the browser fetches this
# afterwards. These tests pin the contract that makes that safe: the same request shape and the same
# clean 4xx/409 conditions as POST /results, so a window the panel can render is never one the box
# rejects — and never a 500.


def test_results_omits_the_benchmark_and_carries_the_lazy_placeholder(client):
    """POST /results must NOT run the DP, and must leave the fetcher what it needs."""
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    html = r.text
    # The placeholder, its window request, and the loading state the fetcher replaces.
    assert 'id="benchmark-slot"' in html
    assert "data-benchmark-body=" in html
    assert "⟳" in html
    # None of the rendered box's own content is present — that is the DP not having run.
    assert "bench-track" not in html


def test_benchmark_route_returns_the_rendered_box(client):
    r = client.post(w("/results/benchmark"), json={"period": "last_1_week"})
    assert r.status_code == 200
    html = r.text
    assert "Benchmark: grid import avoided" in html
    # The three unconditional §2.4 rows, and the bars the panel fragment did not have.
    for label in ("No battery", "Your policy", "Perfect foresight"):
        assert label in html
    assert "bench-track" in html
    # The response is the BOX ALONE, not the whole panel — that is what makes it swappable into
    # #benchmark-slot without disturbing anything else.
    assert 'id="panel-results"' not in html
    assert "GRID IMPORT SAVED" not in html


def test_benchmark_route_accepts_an_explicit_range(client):
    r = client.post(
        w("/results/benchmark"),
        json={"start": "2026-01-05T00:00:00Z", "end": "2026-01-12T00:00:00Z"},
    )
    assert r.status_code == 200
    assert "Benchmark: grid import avoided" in r.text


def test_benchmark_route_accepts_the_placeholders_own_window_request(client):
    """The round trip the browser actually makes: read data-benchmark-body, POST it back.

    `results_from` emits the EFFECTIVE window (already clamped to coverage) rather than the preset,
    so the box is computed over exactly the window the rows beside it describe. Re-sending an
    already-clamped window must be accepted, not rejected as out of range.
    """
    import json
    import re

    panel = client.post(w("/results"), json={"period": "last_1_week"})
    assert panel.status_code == 200
    m = re.search(r'data-benchmark-body="([^"]*)"', panel.text)
    assert m, "the placeholder carries no window request for the fetcher to use"
    body = json.loads(m.group(1).replace("&#34;", '"').replace("&quot;", '"'))
    assert set(body) == {"start", "end"}
    r = client.post(w("/results/benchmark"), json=body)
    assert r.status_code == 200
    assert "Benchmark: grid import avoided" in r.text


def test_benchmark_route_unknown_period_400(client):
    r = client.post(w("/results/benchmark"), json={"period": "last_5_centuries"})
    assert r.status_code == 400


def test_benchmark_route_period_and_range_together_400(client):
    r = client.post(
        w("/results/benchmark"),
        json={"period": "last_1_week", "start": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_benchmark_route_inverted_range_400(client):
    r = client.post(
        w("/results/benchmark"),
        json={"start": "2026-01-12T00:00:00Z", "end": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_benchmark_route_bad_date_400(client):
    r = client.post(
        w("/results/benchmark"), json={"start": "not-a-date", "end": "2026-01-12T00:00:00Z"}
    )
    assert r.status_code == 400


def test_benchmark_route_no_dataset_409(tmp_path, monkeypatch):
    """A cleared dataset must degrade to a clean 409, so the box says so and the panel is unharmed."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    seed_workspace()
    from app import main
    c = TestClient(main.app)
    r = c.post(w("/results/benchmark"), json={"period": "last_1_week"})
    assert r.status_code == 409


# ══ Phase 6 — the §2.4 COST SAVINGS section, end to end through the routes ════════════════════
#
# The view-model tests in tests/test_results_view.py own the arithmetic and the capture-ratio
# shapes. These own what the PAGE does: that the section appears and disappears with the stored
# `simulate_cost`, that the energy half is untouched by the toggle (fixture 18, on the rendered
# HTML rather than on the view-model), and that the "enable cost simulation" affordance is present
# exactly when there is no section.
#
# The dataset the `client` fixture seeds carries no price series, which would make every euro
# figure NaN, so these tests use their own fixture with a spot price and a PV series.


def _price_frame(name: str, values, n: int = _HOURS):
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    vals = np.full(n, float(values)) if np.isscalar(values) else np.asarray(values, dtype=float)
    return SeriesFrame(name, "price", 3600, idx, vals, np.zeros(n, dtype=QUALITY_DTYPE))


@pytest.fixture()
def cost_client(tmp_path, monkeypatch):
    """A client over a priced dataset, with `simulate_cost` STORED ON.

    The flag is persisted through `simconfig_store` rather than patched into the route, because
    that is the path a user's answer in the setup band actually takes (Phase 5 wired it) and the
    routes all read the same stored config. Returns the client and the store module so a test can
    flip the toggle and re-request without rebuilding the dataset.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset, simconfig_store
    from app.domain.simconfig import SimulationConfig

    # A price with a real spread: six expensive hours a day, eighteen cheap ones, repeated over
    # the 30-day window. A flat price makes the bill a constant times a total, which would hide a
    # sign error in §6.10.
    prices = [0.30 if (h % 24) in (7, 8, 17, 18, 19, 20) else 0.04 for h in range(_HOURS)]
    dataset.save_dataset(
        [
            _energy("grid_import_t1", 2.0),
            _energy("grid_export_t1", 0.5),
            _energy("solar_production", 3.0),
            _price_frame("price_spot", prices),
        ],
        (_WIN_START, _WIN_END), "test", [], None,
        workspace_id=WORKSPACE_ID,
    )
    cfg = SimulationConfig()
    cfg.simulate_cost = True
    simconfig_store.save(cfg, WORKSPACE_ID)
    seed_workspace()

    from app import main
    return TestClient(main.app), simconfig_store


def test_cost_section_renders_when_simulate_cost_is_on(cost_client):
    """§2.4's COST SAVINGS section, on the page: the divider, the tile, the waterfall.

    Asserted on the section's own headings rather than on a euro amount, because the amounts move
    with the fixture while the structure is what §2.4 specifies.
    """
    client, _ = cost_client
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    assert "Cost savings" in r.text
    assert "MONEY SAVED" in r.text
    assert "Where the money comes from" in r.text
    assert "Net saving" in r.text
    # The tile's sentence (§2.4's wireframe), and a euro amount beside it.
    assert "without a battery" in r.text and "with one" in r.text
    assert "€" in r.text
    # …and the affordance to enable what is already enabled is NOT offered.
    assert "Want to know what this is worth in euros?" not in r.text


def test_cost_section_absent_and_affordance_offered_when_simulate_cost_is_off(cost_client):
    """§2.4 "Panel ③ without cost simulation", on the page — the same dataset, the toggle flipped.

    Two things the spec asks for by name: the section and everything in it is ABSENT (not a
    placeholder and not a zero — "a blank where a headline number would go reads as a failed
    calculation"), and a short affordance sits at the foot of the energy section linking back to
    the `simulate_cost` control in the setup band, "since it defaults off, some users will
    otherwise never discover that the app can do this at all".
    """
    client, store = cost_client
    from app.domain.simconfig import SimulationConfig

    store.save(SimulationConfig(), WORKSPACE_ID, pricing_configured=True)  # simulate_cost defaults to False
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    assert "Cost savings" not in r.text
    assert "MONEY SAVED" not in r.text
    assert "Where the money comes from" not in r.text
    assert "Net saving" not in r.text
    assert "Benchmark: money saved" not in r.text
    # The affordance, and the anchor it points at. **That anchor is the reason §2′.7 flagged this
    # box**: `#setup-simulate-cost` was an id in the setup band, which §2′.7 deleted. It is now the
    # id of the toggle's new home INSIDE this same fragment, so the link resolves to a control on
    # the page it is rendered on rather than to nothing.
    assert "Want to know what this is worth in euros?" in r.text
    assert "Enable cost simulation" in r.text
    assert 'href="#setup-simulate-cost"' in r.text
    assert 'id="setup-simulate-cost"' in r.text, "the anchor must resolve to a real element"
    # The energy section is complete, not truncated: §2.4 says the panel "is complete without the
    # second half rather than looking truncated".
    assert "Energy savings" in r.text
    assert "Where the energy comes from" in r.text


def test_the_invitation_points_at_the_contract_when_the_toggle_is_blocked(cost_client):
    """§2′.7: the invitation must "say something useful when the toggle it points at is blocked".

    The precondition (§2′.6) is `pricing_configured`, and without it the toggle is Blocked: its
    radios are disabled, so `[ Enable cost simulation ]` would send the reader to a control they
    cannot operate and explain nothing. The box therefore names the precondition and links to the
    screen that clears it — the SAME destination the Blocked toggle's ⓘ dialog offers, because
    there is one way to clear this.

    §2′.7 holds the box otherwise as it is, so its question is unchanged and asserted here too.
    """
    client, store = cost_client
    from app.domain.simconfig import SimulationConfig

    # simulate_cost off AND no contract configured: the Blocked branch.
    store.save(SimulationConfig(), WORKSPACE_ID, pricing_configured=False)
    r = client.post(w("/results"), json={"period": "last_1_week"})
    assert r.status_code == 200
    # The box is still there and still asks its question — §2′.7's hold.
    assert "Want to know what this is worth in euros?" in r.text
    # …but it does not offer a control the reader cannot use.
    assert "Enable cost simulation" not in r.text
    assert 'href="#setup-simulate-cost"' not in r.text
    # It points at the screen that clears the precondition, scoped to this workspace.
    assert f'href="/w/{WORKSPACE_ID}/edit#contract"' in r.text
    assert "Set up my contract" in r.text


def test_fixture_18_the_rendered_energy_half_is_unchanged_by_the_toggle(cost_client):
    """§6.14 fixture 18, on the RENDERED PAGE: "a user who ticks the box should see their kWh
    numbers stay exactly where they were, because a question about money is not a question about
    kilowatt-hours".

    The view-model tests assert this block by block on the data. This asserts it on the HTML,
    which is the thing the user actually sees — it catches a template change that reorders or
    re-labels a row without moving a number, which the view-model comparison cannot.

    The comparison is on the fragment UP TO the cost divider, so the added section is not itself
    the difference.
    """
    client, store = cost_client
    from app.domain.simconfig import SimulationConfig

    on = client.post(w("/results"), json={"period": "last_1_week"}).text
    store.save(SimulationConfig(), WORKSPACE_ID)
    off = client.post(w("/results"), json={"period": "last_1_week"}).text

    # Everything above the COST SAVINGS divider. With cost off the divider is absent, so the
    # energy half is the whole fragment up to the affordance that replaced it.
    marker_on = on.index("Cost savings")
    marker_off = off.index("Want to know what this is worth in euros?")
    head_on = on[:marker_on]
    head_off = off[:marker_off]
    # The chart's tab strip differs by one button (§2.4: "the Charts box GAINS options"), and the
    # affordance/divider boundary itself differs, so the comparison is on the FIGURES and LABELS
    # of the energy section rather than on the raw bytes.
    for label in ("Grid import, no battery", "Grid import, with battery",
                  "Charged into the battery", "Discharged from the battery",
                  "Conversion losses", "Standby consumption", "Grid export",
                  "GRID IMPORT SAVED", "SELF-SUFFICIENCY", "EQUIVALENT FULL CYCLES"):
        assert (label in head_on) == (label in head_off), label

    import re as _re

    def figures(html: str) -> list[str]:
        """Every kWh figure in the energy half, in document order."""
        return _re.findall(r"[\d,]+ kWh", html)

    assert figures(head_on) == figures(head_off)
    # The percentages too — the self-sufficiency arrow and the saving's delta.
    assert _re.findall(r"[+−]?[\d.]+ ?%", head_on) == _re.findall(r"[+−]?[\d.]+ ?%", head_off)


def test_the_monthly_chart_gains_a_euro_option_rather_than_swapping_the_kwh_one(cost_client):
    """§2.4: "The Charts box gains options rather than swapping them" — *Monthly savings (€)*
    BESIDE the kWh one, as separate views and not a dual axis.

    So with cost on there are two view buttons and two series in the data node; with cost off
    there is one button and the euro series is null. A dual axis would put both series in one
    trace, which is the reading §2.4 says the panel's two-section split exists to prevent.
    """
    client, store = cost_client
    import json as _json
    import re as _re

    on = client.post(w("/results"), json={"period": "last_1_week"}).text
    assert 'data-chart-view="kwh"' in on
    assert 'data-chart-view="eur"' in on
    assert "Monthly savings (€)" in on
    node = _json.loads(_re.search(
        r'<script id="monthly-data" type="application/json">(.*?)</script>', on, _re.S
    ).group(1))
    assert node["eur_values"] is not None
    # The two series describe the SAME buckets — one month, two bars, one window.
    assert len(node["eur_values"]) == len(node["values"])
    assert node["ytitle"] != node["eur_ytitle"]

    from app.domain.simconfig import SimulationConfig
    store.save(SimulationConfig(), WORKSPACE_ID)
    off = client.post(w("/results"), json={"period": "last_1_week"}).text
    assert 'data-chart-view="eur"' not in off
    assert "Monthly savings (€)" not in off
    node_off = _json.loads(_re.search(
        r'<script id="monthly-data" type="application/json">(.*?)</script>', off, _re.S
    ).group(1))
    # Fixture 19: null, never 0.0 and never an empty list a chart would draw as a flat line.
    assert node_off["eur_values"] is None
    # …and the kWh series is untouched (fixture 18).
    assert node_off["values"] == node["values"]


def test_the_money_benchmark_box_renders_from_the_shared_partial(cost_client):
    """§2.4's money box, through the lazy path — and proof `_benchmark_box.html` generalised.

    Both boxes render from ONE partial: it takes rows, a gloss, an optional title and an optional
    note, none of which is kWh-specific. The `with_benchmark=True` render is the only one that
    carries either, and it carries BOTH — run D and run E, gated together.

    A short window (a 7-day preset over a 30-day dataset) keeps the four DP passes cheap.
    """
    client, _ = cost_client
    r = client.get(page())
    assert r.status_code == 200
    # The lazy path: the initial paint carries the money slot as a PLACEHOLDER, not a computed
    # box — the heading and the spinner, none of the figures.
    assert 'id="cost-benchmark-slot"' in r.text
    assert "Benchmark: money saved" in r.text
    assert "computing" in r.text

    r = client.post(w("/results/benchmark"), json={"period": "last_1_week"})
    assert r.status_code == 200
    # With cost simulation on the response carries BOTH boxes, each wrapped with the slot it
    # belongs in, because both DPs ran on this request anyway. Returning one and discarding the
    # other would pay ~2.3 s for a result nobody sees.
    assert 'data-slot="benchmark-slot"' in r.text
    assert 'data-slot="cost-benchmark-slot"' in r.text
    assert "Benchmark: grid import avoided" in r.text
    assert "Benchmark: money saved" in r.text
    # The lazily-fetched money box carries the Phase 7 cost tint and the energy box does not —
    # this is the one path where the flag travels through Python (main.py passes `cost=True` to
    # the shared partial) rather than through a `{% with %}` in the template.
    import re

    assert re.search(r'cost-label[^>]*>\s*Benchmark: money saved\s*<', r.text)
    assert re.search(
        r'<h3(?![^>]*cost-label)[^>]*>\s*Benchmark: grid import avoided\s*<', r.text
    )


def test_the_benchmark_response_is_a_bare_energy_box_when_cost_is_off(client):
    """The energy path's fetch contract is unchanged by the money box existing.

    With cost simulation off there is no second box, so the response is `_benchmark_box.html`'s
    output alone — no `data-slot` wrappers — which is exactly the shape the results screen's handler
    consumed before this increment. Pinned so the two-box shape cannot become unconditional and
    silently change what an energy-only install receives.
    """
    r = client.post(w("/results/benchmark"), json={"period": "last_1_week"})
    assert r.status_code == 200
    assert "data-slot=" not in r.text
    assert "Benchmark: money saved" not in r.text


def test_the_money_box_is_gated_on_simulate_cost_as_well_as_on_with_benchmark(cost_client):
    """Run E is gated by BOTH flags — §6.12's table says the cost benchmark runs "only when
    cfg.simulate_cost", and the deliverable's latency rule says only `with_benchmark` pays for a
    DP. Asserted on the view-model through the same stored config the routes read, because no
    route renders the money box unasked — the panel paints a placeholder and the lazy fetch fills
    it (see `test_the_money_benchmark_box_renders_from_the_shared_partial`).
    """
    client, store = cost_client
    from app import dataset, results_view, simconfig_store
    from app.domain.simconfig import SimulationConfig

    loaded = dataset.load_latest(WORKSPACE_ID)
    window = results_view.resolve_window(loaded, period="last_1_week")

    # cost on, benchmark not asked for → no DP was paid for, so no box.
    r = results_view.results_from(loaded, window, cfg=simconfig_store.load(WORKSPACE_ID))
    assert "cost_benchmark" not in r
    assert r["cost"] is not None   # the cheap euro figures are there either way

    # cost off, benchmark asked for → run D ran, run E did not.
    r = results_view.results_from(
        loaded, window, cfg=SimulationConfig(), with_benchmark=True
    )
    assert "benchmark" in r
    assert "cost_benchmark" not in r

    # both → both boxes.
    r = results_view.results_from(
        loaded, window, cfg=simconfig_store.load(WORKSPACE_ID), with_benchmark=True
    )
    assert "benchmark" in r and "cost_benchmark" in r
    assert r["cost_benchmark"]["title"] == "Benchmark: money saved"


def test_the_cost_tint_marks_the_cost_section_and_not_the_energy_one(cost_client):
    """Phase 7: §2.4's COST SAVINGS half is tinted; the ENERGY SAVINGS half above it is not.

    The RULE, not every occurrence — the point of the change is that the marking is uniform, and
    pinning each heading would turn any restyling into a test edit. So: the cost divider and the
    cost headings carry .cost-label, their energy counterparts do not, and with cost simulation
    off nothing on the page carries it.

    Colour is never the only signal (§2.4 gives the section a divider and a heading, and this test
    keeps asserting those as text), so a reader who cannot distinguish the hue loses nothing.
    """
    import re

    client, store = cost_client
    on = client.post(w("/results"), json={"period": "last_1_week"}).text

    # The divider that opens the cost half is tinted; the one that opens the energy half is not.
    assert re.search(r'divider[^"]*cost-label"[^>]*>\s*Cost savings\s*<', on)
    assert re.search(r'divider(?:(?!cost-label)[^"])*"[^>]*>\s*Energy savings\s*<', on)

    # Headings inside the cost section, and their energy counterparts left plain.
    for tinted in ("Where the money comes from", "Benchmark: money saved"):
        assert re.search(r'cost-label[^>]*>\s*%s\s*<' % re.escape(tinted), on), tinted
    for plain in ("Where the energy comes from", "Secondary metrics", "Caveats for this run"):
        assert re.search(
            r'<h3(?![^>]*cost-label)[^>]*>\s*%s\s*<' % re.escape(plain), on
        ), plain

    # The MONEY SAVED tile's title, beside the untinted energy tiles in the row above it.
    assert re.search(r'stat-title[^"]*cost-label"[^>]*>\s*MONEY SAVED\s*<', on)
    assert re.search(r'<div class="stat-title text-xs">\s*GRID IMPORT SAVED\s*<', on)

    # Cost simulation off → the tinted SECTION does not exist, so nothing below the divider is
    # tinted. The cost TOGGLE's label still is, and deliberately: §2′.6 moved that control into
    # this fragment in phase 4.2, and it is the switch for cost simulation whether cost simulation
    # is currently on or not — the same reasoning that tinted it in the setup band before
    # (`test_the_setup_band_toggle_carries_the_cost_tint` in tests/test_params_route.py).
    from app.domain.simconfig import SimulationConfig

    store.save(SimulationConfig(), WORKSPACE_ID)
    off = client.post(w("/results"), json={"period": "last_1_week"}).text
    # Exactly one tinted thing, and it is the toggle's label.
    tinted = re.findall(r'cost-label[^>]*>\s*([^<]+?)\s*<', off)
    assert tinted == ["Simulate cost savings?"], tinted
    assert "cost-field" not in off      # no tinted INPUT: the Pricing box is not rendered here
    assert "Energy savings" in off      # …and the untinted half is untouched


# ── §6.16's pricing-uncertainty caveat, on the rendered page ─────────────────────────────────
#
# The view-model half is pinned in tests/test_results_view.py. This is the wiring, and it is not
# redundant: a caveat that exists in the view-model and never reaches the HTML is a defect this
# project has shipped twice (the workspace-edit settlement radio, and the ⓘ on the grid-import
# row). Both paths are exercised — the full page and the swapped fragment — because panel ③ is
# replaced wholesale on every period change.


def _price_frame_15min(name: str, values, n: int = _HOURS * 4):
    """A quarter-hourly price series over the same window `_price_frame` covers hourly.

    The width exists only where `simulation_frame` COLLAPSES several native price points into one
    grid interval (§6.16's D1), so a 15-minute price against hourly energy is the shape that
    produces one. `resolution_s` is 900 here and that is what makes the collapse happen.
    """
    idx = (
        np.arange(n).astype("timedelta64[s]") * 900
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    vals = np.full(n, float(values)) if np.isscalar(values) else np.asarray(values, dtype=float)
    return SeriesFrame(name, "price", 900, idx, vals, np.zeros(n, dtype=QUALITY_DTYPE))


@pytest.fixture()
def uncertainty_client(tmp_path, monkeypatch):
    """`cost_client`'s dataset with a QUARTER-HOURLY price, and the supplier billing that way.

    Both are required for a width to exist at all: the 15-minute price gives the collapse, and
    `SupplierSettlement.QUARTER_HOURLY` opens D10's gate (with the default HOURLY the hourly price
    IS what the household paid and there is nothing to caveat). Returns the client and the store
    so a test can close the gate and re-request against the same data.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset, simconfig_store
    from app.domain.simconfig import SimulationConfig, SupplierSettlement

    # Four quarters per hour with a wide, asymmetric intra-hour spread, so the hourly mean sits
    # well inside [min, max] and the width is comfortably above the whole-euro display threshold.
    quarters = [
        (0.02, 0.10, 0.40, 0.28)[q] if (h % 24) in (7, 8, 17, 18, 19, 20)
        else (0.05, 0.03, 0.06, 0.02)[q]
        for h in range(_HOURS) for q in range(4)
    ]
    dataset.save_dataset(
        [
            _energy("grid_import_t1", 2.0),
            _energy("grid_export_t1", 0.5),
            _energy("solar_production", 3.0),
            _price_frame_15min("price_spot", quarters),
        ],
        (_WIN_START, _WIN_END), "test", [], None,
        workspace_id=WORKSPACE_ID,
    )
    cfg = SimulationConfig()
    cfg.simulate_cost = True
    cfg.pricing.supplier_settlement = SupplierSettlement.QUARTER_HOURLY
    simconfig_store.save(cfg, WORKSPACE_ID)
    seed_workspace()

    from app import main
    return TestClient(main.app), simconfig_store


def test_the_pricing_uncertainty_caveat_reaches_the_html(uncertainty_client):
    """The sentence, its figure, and its "worst case" qualifier, in the served markup.

    Asserted on both the full page and the POST fragment. The figure is checked for having been
    SUBSTITUTED rather than for a particular amount — an `_msg` pair that reached the template
    unrendered would show up as a literal "%(width)s" or as a dict repr, which is the failure
    mode this test is really for.
    """
    client, _ = uncertainty_client
    for body in (client.get(page()).text,
                 client.post(w("/results"), json={"period": "last_1_week"}).text):
        assert "the electricity market prices every 15 minutes" in body
        assert "worst case" in body
        i = body.find("the electricity market prices every 15 minutes")
        sentence = body[i:i + 700]
        assert "%(width)s" not in sentence and "%(share)s" not in sentence
        assert "msgid" not in sentence, "an unrendered _msg pair reached the caveats box"
        # The euro figure was interpolated: a "€" inside the caveat's own text.
        assert "€" in sentence
        # And it sits in the caveats box rather than loose on the page.
        assert body.find("Caveats for this run") < i


def test_the_pricing_uncertainty_caveat_is_translated_on_the_dutch_page(uncertainty_client):
    """The Dutch caveat, in the served markup, with its figure substituted.

    Two things it pins that an English-only test cannot. First, that the Dutch msgstr exists and
    is compiled — a missing entry falls back to the English msgid, which renders without error
    and looks fine to anyone not reading it. Second, the wording of the closing clause: an
    earlier translation said "een echt uur ligt ergens tussen zijn kwartieren in", which reads as
    BETWEEN the quarters rather than within one, and so denies the very thing the sentence is
    explaining.
    """
    client, _ = uncertainty_client
    body = client.get(page(), headers={"Cookie": "lang=nl"}).text
    assert "de elektriciteitsmarkt rekent per 15 minuten af" in body
    i = body.find("de elektriciteitsmarkt rekent per 15 minuten af")
    sentence = body[i:i + 800]
    assert "In het slechtste geval" in sentence
    assert "%(width)s" not in sentence and "€" in sentence
    # Scoped to the SAVING, matching the English (see the results-view test of the same name).
    assert "verschuift de besparing op deze pagina" in sentence
    assert "eurobedragen op deze pagina" not in sentence
    # WITHIN one quarter, not between the quarters.
    assert "ligt ergens binnen een van zijn kwartieren" in sentence
    assert "tussen zijn kwartieren in" not in sentence


def test_the_caveat_leaves_the_page_when_the_supplier_bills_hourly(uncertainty_client):
    """D10 on the rendered page: same dataset, only the settlement answer changed.

    The negative half of the test above, and the one that shows the first is about the caveat
    rather than about some other text on a cost-enabled page.
    """
    client, store = uncertainty_client
    from app.domain.simconfig import SimulationConfig

    cfg = SimulationConfig()
    cfg.simulate_cost = True                 # cost section still present…
    store.save(cfg, WORKSPACE_ID)            # …but settlement back to the HOURLY default
    body = client.post(w("/results"), json={"period": "last_1_week"}).text
    assert "Cost savings" in body            # the fixture still prices the run
    assert "the electricity market prices every 15 minutes" not in body


# ── The opening window: default, remembered choice, and re-fetch behaviour ────────────────────
#
# The `client` fixture's dataset is 30 days of hourly grid data with no PV, so `default_window`
# resolves to the full coverage and reads as CUSTOM (30 days is not a full year). That is itself
# worth pinning: the ribbon opens on "custom" whenever the data is shorter than a year.


def _active_preset(html: str) -> str | None:
    """The token of the preset button carrying btn-active in the period card, or None."""
    m = re.search(r'class="btn btn-sm btn-active"\s+data-period="([^"]+)"', html)
    return m.group(1) if m else None


def test_opening_window_shows_the_derived_default_on_a_short_history(client):
    """30 days of data: no SPAN preset describes it, and the screen opens on the derived window.

    Since the "default" button was added, that is the button highlighted — it names the window in
    force, where "custom" only ever meant "none of the spans fit". The date fields consequently
    stay COLLAPSED on a first visit; they are still pre-filled with the window, so opening them
    shows what is in force rather than blank fields.
    """
    body = client.get(page()).text
    assert _active_preset(body) == "default"
    assert not re.search(r'id="results-period-custom"\s+class="btn btn-sm btn-active"', body)
    assert 'value="2026-01-01"' in body and 'value="2026-01-31"' in body


def test_preset_choice_is_remembered_across_a_reload(client):
    """A preset click is stored as its TOKEN and comes back on the next page load."""
    client.post(w("/results"), json={"period": "last_1_week"})
    from app import simconfig_store
    assert simconfig_store.load_results_period(WORKSPACE_ID) == {"preset": "last_1_week"}
    assert _active_preset(client.get(page()).text) == "last_1_week"


def test_custom_range_is_remembered_across_a_reload(client):
    """A typed range is stored as dates and comes back as custom, not snapped to a preset."""
    client.post(w("/results"), json={
        "start": "2026-01-05T00:00:00+00:00",
        "end": "2026-01-12T00:00:00+00:00",
    })
    from app import simconfig_store
    stored = simconfig_store.load_results_period(WORKSPACE_ID)
    assert stored is not None and "start" in stored
    body = client.get(page()).text
    assert _active_preset(body) is None
    assert 'value="2026-01-05"' in body and 'value="2026-01-12"' in body


def test_a_remembered_preset_follows_a_refetch(client):
    """The point of storing the TOKEN: re-fetching data that reaches further back moves the window.

    The stored preset is `last_1_week`, anchored to the coverage END. Replacing the dataset with
    one ending later must move the window with it rather than pin it to the old dates.
    """
    client.post(w("/results"), json={"period": "last_1_week"})
    from app import dataset

    n = 30 * 24
    idx = (np.arange(n).astype("timedelta64[s]") * 3600
           + np.datetime64("2026-06-01T00:00:00")).astype("datetime64[s]")
    frames = [
        SeriesFrame("grid_import_t1", "energy", 3600, idx, np.full(n, 2.0),
                    np.zeros(n, dtype=QUALITY_DTYPE)),
        SeriesFrame("grid_export_t1", "energy", 3600, idx, np.zeros(n),
                    np.zeros(n, dtype=QUALITY_DTYPE)),
    ]
    dataset.save_dataset(frames, (datetime(2026, 6, 1, tzinfo=timezone.utc),
                                  datetime(2026, 7, 1, tzinfo=timezone.utc)),
                         "test", [], None, workspace_id=WORKSPACE_ID)

    body = client.get(page()).text
    assert _active_preset(body) == "last_1_week"
    assert "2026-06-" in body            # the window moved to the new coverage


def test_a_stored_range_outside_new_coverage_flips_to_the_year_preset(client):
    """A typed range with no overlap after a re-fetch: fall back to `last_1_year` AND make that
    the stored choice, so the fallback is sticky rather than re-derived on every load."""
    client.post(w("/results"), json={
        "start": "2026-01-05T00:00:00+00:00",
        "end": "2026-01-12T00:00:00+00:00",
    })
    from app import dataset, simconfig_store

    # New data a year later — the stored January-2026 range does not overlap it at all.
    n = 30 * 24
    idx = (np.arange(n).astype("timedelta64[s]") * 3600
           + np.datetime64("2027-06-01T00:00:00")).astype("datetime64[s]")
    frames = [
        SeriesFrame("grid_import_t1", "energy", 3600, idx, np.full(n, 2.0),
                    np.zeros(n, dtype=QUALITY_DTYPE)),
        SeriesFrame("grid_export_t1", "energy", 3600, idx, np.zeros(n),
                    np.zeros(n, dtype=QUALITY_DTYPE)),
    ]
    dataset.save_dataset(frames, (datetime(2027, 6, 1, tzinfo=timezone.utc),
                                  datetime(2027, 7, 1, tzinfo=timezone.utc)),
                         "test", [], None, workspace_id=WORKSPACE_ID)

    body = client.get(page()).text
    # The STORED choice is now the preset — that is the sticky part being pinned here.
    assert simconfig_store.load_results_period(WORKSPACE_ID) == {"preset": "last_1_year"}
    # The window resolved from it covers the new data, and the ribbon shows a preset rather than
    # the custom fields. Which preset is highlighted is `_period_selected_for`'s pre-existing
    # nearest-span mapping, not this feature's: `last_1_year` clamps to the 30 days that exist, so
    # the nearest label is "1 month". Assert the shape, not that one label.
    assert _active_preset(body) is not None
    assert "2027-06-" in body


def test_the_benchmark_fetch_does_not_overwrite_a_stored_preset(client):
    """The benchmark route re-sends the RESOLVED window as an explicit start/end. If that were
    recorded, loading the benchmark box would silently convert the user's preset into a frozen
    custom range — so only /results writes, and this pins it."""
    client.post(w("/results"), json={"period": "last_1_week"})
    client.post(w("/results/benchmark"), json={
        "start": "2026-01-24T00:00:00+00:00",
        "end": "2026-01-31T00:00:00+00:00",
    })
    from app import simconfig_store
    assert simconfig_store.load_results_period(WORKSPACE_ID) == {"preset": "last_1_week"}


# ── The "default" button: reset to the data-derived window ───────────────────────────────────


def test_the_default_button_is_offered_and_active_on_a_first_visit(client):
    """It leads the ribbon, and it is what reads as active before the user has chosen anything —
    the screen IS showing the derived window, so that is the button that describes it."""
    body = client.get(page()).text
    assert 'data-period="default"' in body
    assert _active_preset(body) == "default"


def test_the_default_button_recomputes_and_is_remembered(client):
    """Pressing it stores the TOKEN, so the rule (not the dates it resolved to today) is what
    comes back."""
    r = client.post(w("/results"), json={"period": "default"})
    assert r.status_code == 200
    from app import simconfig_store
    assert simconfig_store.load_results_period(WORKSPACE_ID) == {"preset": "default"}
    assert _active_preset(r.text) == "default"
    assert _active_preset(client.get(page()).text) == "default"


def test_the_default_button_resets_a_custom_range(client):
    """The reason it exists: get back to the known-good period after typing a range."""
    client.post(w("/results"), json={
        "start": "2026-01-05T00:00:00+00:00",
        "end": "2026-01-12T00:00:00+00:00",
    })
    client.post(w("/results"), json={"period": "default"})
    from app import simconfig_store
    assert simconfig_store.load_results_period(WORKSPACE_ID) == {"preset": "default"}
    body = client.get(page()).text
    assert _active_preset(body) == "default"
    # Back to the full coverage of the fixture's 30 days, not the 7 typed days.
    assert 'value="2026-01-01"' in body and 'value="2026-01-31"' in body


def test_the_remembered_default_re_derives_after_a_refetch(client):
    """The point of storing the token: the window follows the data rather than freezing."""
    client.post(w("/results"), json={"period": "default"})
    from app import dataset

    n = 20 * 24
    idx = (np.arange(n).astype("timedelta64[s]") * 3600
           + np.datetime64("2026-09-01T00:00:00")).astype("datetime64[s]")
    frames = [
        SeriesFrame("grid_import_t1", "energy", 3600, idx, np.full(n, 2.0),
                    np.zeros(n, dtype=QUALITY_DTYPE)),
        SeriesFrame("grid_export_t1", "energy", 3600, idx, np.zeros(n),
                    np.zeros(n, dtype=QUALITY_DTYPE)),
    ]
    dataset.save_dataset(frames, (datetime(2026, 9, 1, tzinfo=timezone.utc),
                                  datetime(2026, 9, 21, tzinfo=timezone.utc)),
                         "test", [], None, workspace_id=WORKSPACE_ID)

    body = client.get(page()).text
    assert _active_preset(body) == "default"
    assert 'value="2026-09-01"' in body and 'value="2026-09-21"' in body


def test_the_default_button_narrows_to_pv_coverage(tmp_path, monkeypatch):
    """End to end through the route: with PV mapped part-way through, "default" lands on the PV
    window rather than the whole meter history."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import dataset

    pv_n = 10 * 24
    pv_idx = (np.arange(pv_n).astype("timedelta64[s]") * 3600
              + np.datetime64("2026-01-20T00:00:00")).astype("datetime64[s]")
    frames = [
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.5),
        SeriesFrame("solar_production", "energy", 3600, pv_idx, np.full(pv_n, 0.4),
                    np.zeros(pv_n, dtype=QUALITY_DTYPE)),
    ]
    dataset.save_dataset(frames, (_WIN_START, _WIN_END), "test", [], None,
                         workspace_id=WORKSPACE_ID)
    seed_workspace()
    from app import main
    client = TestClient(main.app)

    body = client.post(w("/results"), json={"period": "default"}).text
    assert 'value="2026-01-20"' in body     # PV start, not the meter's 2026-01-01
    assert _active_preset(body) == "default"


def test_default_combined_with_a_range_is_a_400(client):
    """It is still a preset for mutual-exclusivity purposes, not an escape hatch."""
    r = client.post(w("/results"), json={
        "period": "default", "start": "2026-01-05T00:00:00+00:00",
    })
    assert r.status_code == 400


# ── The coverage warning on the rendered page ─────────────────────────────────────────────────


def test_coverage_warning_absent_when_every_series_spans_the_window(client):
    assert "results-coverage-warning" not in client.get(page()).text


def test_coverage_warning_names_a_short_series(tmp_path, monkeypatch):
    """A PV series mapped part-way through: the warning appears, names the role, and states the
    span PV actually covers."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import dataset

    pv_n = 10 * 24
    pv_idx = (np.arange(pv_n).astype("timedelta64[s]") * 3600
              + np.datetime64("2026-01-20T00:00:00")).astype("datetime64[s]")
    frames = [
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.5),
        SeriesFrame("solar_production", "energy", 3600, pv_idx, np.full(pv_n, 0.4),
                    np.zeros(pv_n, dtype=QUALITY_DTYPE)),
    ]
    dataset.save_dataset(frames, (_WIN_START, _WIN_END), "test", [], None,
                         workspace_id=WORKSPACE_ID)
    seed_workspace()
    from app import main
    client = TestClient(main.app)

    # Ask for the full 30 days explicitly, so the window is wider than PV's coverage.
    body = client.post(w("/results"), json={
        "start": _WIN_START.isoformat(), "end": _WIN_END.isoformat(),
    }).text
    assert "results-coverage-warning" in body
    assert "Solar production" in body
    assert "2026-01-20" in body
