"""Guards against English text surviving on a Dutch page.

The defect this exists for: view-models built display strings at runtime with f-strings, so their
msgid was never a compile-time constant and `pybabel extract` never saw them. The templates DID
pass them through `_()`, and both catalogs were 100% translated, so every conventional signal said
the page was fully bilingual — while a Dutch reader saw all three panel-③ caveats, the whole
benchmark gloss, the KPI deltas and half of panel ①'s data-quality box in English.

No string-spotting test catches that: you cannot assert on a string you did not know was there.
So this test works the other way round — it renders the real pages in Dutch and asserts that
nothing *looks like English prose*, with an explicit allowlist for the tokens that legitimately
stay untranslated (units, entity ids, ISO dates, proper nouns).

Scope note. `GET /` renders panel ③ from the sample view-model, which understates the problem —
the live figures come from `POST /results` and `POST /results/benchmark`, and those are where the
runtime strings are built. All three are exercised here for that reason.

The allowlist is the point of maintenance: when this test fails, the fix is normally to translate
the string, and only occasionally to add a token here. Adding a whole sentence to the allowlist
defeats the test.
"""

import importlib
import os
import re
import tempfile
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame
from tests.conftest import page, seed_workspace, w

# Words that are strong evidence of untranslated English prose. Deliberately closed-class
# (articles, prepositions, auxiliaries, determiners) — these are the words a translator always
# replaces, whereas nouns are often shared between English and Dutch ("import", "batterij").
ENGLISH_MARKERS = {
    "the", "your", "and", "of", "is", "are", "was", "were", "this", "that", "with",
    "from", "for", "not", "every", "which", "than", "have", "has", "been", "would",
    "could", "there", "their", "them", "they", "what", "when", "where", "into",
    "over", "under", "about", "because", "while", "after", "before", "does", "did",
}

# Tokens that legitimately appear in Dutch output. Each needs a reason.
ALLOWED_TOKENS = {
    # Units and symbols — not translated in either language.
    "kwh", "kw", "kwp", "wh", "w", "v", "a", "hz", "pp", "eur", "min", "s", "h",
    # Proper nouns / product names.
    "home", "assistant", "energy", "charts", "csv", "epex", "ha", "soc", "t1", "t2",
    "p1", "p2", "p3", "d1", "d2", "d3", "dc", "ac", "pv", "id", "url", "websocket",
    # Dutch words that collide with English markers or look English.
    "in", "van", "op", "is", "was", "de", "het", "een", "en", "of", "per", "over",
}

# Sentinel English fragments that must never appear. These are the exact strings the
# investigation measured leaking; listing them makes a regression name itself rather than
# surfacing as an opaque marker-count failure.
FORBIDDEN_FRAGMENTS = [
    "Your meter recorded",
    "Perfect foresight knows every future price",
    "captures",                      # "Your policy captures N percent of…"
    "throughput",
    "/ day",
    "simulated hourly",
    "simulated 15-min",
    "intervals",                     # "8,760 intervals" / "N interval(s) flagged as gaps"
    "hourly (full)",
    "none detected",
    "not mapped",
    "mapped, active",
    "mapped, flat",
    "averaged",
    "held",
    "Annualised projection is disabled",
    "Spot prices are recorded every",
    "Computed for the battery configured",
    "Reconstructed household load was negative",
    "days",                          # the coverage line's "(365 days)"
]


# ── The synthetic scenarios ──────────────────────────────────────────────────────────────────
#
# Every render below is driven from a dataset and a config this file builds, under a redirected
# BATTERY_SIM_DATA_DIR. The developer's real ./data is never read. That is the point: which boxes
# and caveats a Dutch page renders depends entirely on the stored dataset and config, so scanning
# whatever the developer happens to have made the test's coverage vary per machine
# (`followups.md` H13) — green here proved nothing about anyone else's machine, or about CI.
#
# The scenarios are chosen from the branches that gate user-visible prose, and there are several
# because a number of those branches are MUTUALLY EXCLUSIVE — no single run can show both sides:
#
#   * the negative-saving caveat has cost-off and cost-on wordings (`cost is None` in
#     results_view), and the cost-off one ends "a euro quantity this energy-only run does not
#     compute", which cost-on must never say;
#   * the `load_unreliable` note branches on whether a solar series exists at all
#     (summary_view.py's `has_pv_series`), blaming an unreported sensor in one and missing solar
#     data in the other;
#   * `phase_unsupported` (an unsupported topology the user has NOT accepted) and
#     `topology.approximated` (one they HAVE) are opposite states of the same choice;
#   * `solar_empty` needs a PV series that sums to almost nothing, which is not the healthy PV
#     the full scenario wants; and
#   * `annualisation_disabled` needs a window under 90 days, which the drift and floor caveats do
#     not want.
#
# A window is 40 days of hourly data unless the scenario says otherwise — long enough to simulate
# and to bucket into months, short enough that eight of these stay cheap. The DP grids are cut to
# 21×21 for the same reason: `POST /results/benchmark` is the only route that runs §6.12's DP, and
# nothing here asserts on the bound's tightness, only on the words around it.

_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HOURS = 40 * 24
_FAST_DP = {"dp_soc_levels": 21, "dp_action_levels": 21}


def _idx(n: int, step_s: int = 3600):
    return (
        np.arange(n).astype("timedelta64[s]") * step_s
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")


def _series(name: str, kind: str, values, n: int, step_s: int = 3600) -> SeriesFrame:
    vals = np.full(n, float(values)) if np.isscalar(values) else np.asarray(values, dtype=float)
    return SeriesFrame(name, kind, step_s, _idx(n, step_s), vals, np.zeros(n, dtype=QUALITY_DTYPE))


def _solar(n: int, peak: float = 3.0):
    """A daily PV bell, zero at night — the shape summary_view's solar figures expect."""
    h = np.arange(n) % 24
    return peak * np.maximum(0.0, np.sin((h - 6) * np.pi / 12.0))


def _spot(n: int, low: float = 0.02, high: float = 0.34):
    """A daily square wave, so the price box and the arbitrage caveats have something to say."""
    return np.where((np.arange(n) % 24) < 12, low, high)


def _visible_text(html: str) -> str:
    """Strip scripts, styles and tags, leaving what a reader sees."""
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"[ \t]+", " ", html)


def _frames_and_config(scenario: str):
    """The (frames, window_end, config-mutator) triple for one scenario.

    Kept as one function rather than eight fixtures so the scenarios can be read side by side —
    what makes each different from the others is the point, and that is invisible when they are
    spread across separate definitions.
    """
    n = _HOURS
    cfg_kw: dict = {"has_pv": True, "has_battery": False, "simulate_cost": False}
    topo: dict = {}

    if scenario == "full":
        # PV, an existing battery, cost simulation, an accepted 3-phase approximation, and spot
        # prices at a FINER resolution than the grid so the price-granularity caveat fires.
        frames = [
            _series("grid_import_t1", "energy", 1.4, n),
            _series("grid_export_t1", "energy", 0.3, n),
            _series("solar_production", "energy", _solar(n), n),
            _series("battery_charge", "energy", 0.2, n),
            _series("battery_discharge", "energy", 0.18, n),
            _series("price_spot", "price", _spot(n * 4), n * 4, step_s=900),
        ]
        cfg_kw.update(has_battery=True, simulate_cost=True)
        topo = {"approximated": True, "battery_phases": "one_phase"}

    elif scenario == "bare":
        # No PV, no battery, cost OFF. Lights the "enable cost simulation" affordance, the no-PV
        # policy labels and the greyed P1/P3 blurbs, and the cost-OFF negative-saving wording.
        frames = [
            _series("grid_import_t1", "energy", 1.2, n),
            _series("grid_export_t1", "energy", 0.0, n),
        ]
        cfg_kw.update(has_pv=False)

    elif scenario == "unreliable_nopv":
        # Large export with NO solar series: the reconstruction clamps hard and `load_unreliable`
        # takes its "you have not supplied any solar data" variant.
        frames = [
            _series("grid_import_t1", "energy", 0.2, n),
            _series("grid_export_t1", "energy", 2.5, n),
        ]
        cfg_kw.update(has_pv=False)

    elif scenario == "unreliable_pv":
        # The same clamp, but WITH a solar series present, which selects the other variant — the
        # one that blames export the PV sensor did not report.
        frames = [
            _series("grid_import_t1", "energy", 0.2, n),
            _series("grid_export_t1", "energy", 2.5, n),
            _series("solar_production", "energy", _solar(n, peak=0.4), n),
        ]

    elif scenario == "solar_empty":
        # A solar sensor mapped that reported essentially nothing (below PV_PRESENT_FLOOR_KWH over
        # the whole window) — the `solar_empty` note, and no Solar group.
        frames = [
            _series("grid_import_t1", "energy", 1.2, n),
            _series("grid_export_t1", "energy", 0.0, n),
            _series("solar_production", "energy", 0.0, n),
        ]

    elif scenario == "short_window":
        # Under the 90-day annualisation floor, so `annualisation_disabled` and its message render.
        n = 10 * 24
        frames = [
            _series("grid_import_t1", "energy", 1.2, n),
            _series("grid_export_t1", "energy", 0.1, n),
            _series("solar_production", "energy", _solar(n), n),
            _series("price_spot", "price", _spot(n), n),
        ]
        cfg_kw.update(simulate_cost=True)

    elif scenario == "phase_unsupported":
        # An unsupported battery topology the user has NOT accepted — the opposite state from
        # "full", and the one that raises check 18's warning rather than the pinned caveat.
        frames = [
            _series("grid_import_t1", "energy", 1.2, n),
            _series("grid_export_t1", "energy", 0.2, n),
            _series("solar_production", "energy", _solar(n), n),
        ]
        topo = {"approximated": False, "battery_phases": "three_times_one_phase"}

    else:  # pragma: no cover - a typo in SCENARIOS should fail loudly
        raise AssertionError(f"unknown scenario {scenario!r}")

    end = datetime.fromtimestamp(_WIN_START.timestamp() + n * 3600, tz=timezone.utc)
    return frames, end, cfg_kw, topo


def _build_config(cfg_kw: dict, topo: dict):
    """A SimulationConfig for one scenario, at the reduced DP grids."""
    from app.domain.simconfig import BatteryPhases, SimulationConfig

    cfg = SimulationConfig()
    for k, v in cfg_kw.items():
        setattr(cfg, k, v)
    for k, v in _FAST_DP.items():
        setattr(cfg, k, v)
    # A 3-phase connection is what makes the phase selector appear at all
    # (`battery_phases_offered`), so both topology scenarios need it.
    cfg.grid.phases = 3
    if "approximated" in topo:
        cfg.topology.approximated = topo["approximated"]
    if "battery_phases" in topo:
        cfg.topology.battery_phases = BatteryPhases(topo["battery_phases"])
    return cfg


# The scenarios, and what each is here to surface. The second element is the coverage floor: a
# marker that MUST appear in that scenario's rendered Dutch, checked by
# `test_each_scenario_still_surfaces_its_boxes` below. Without that check a change that stopped
# rendering a box would leave this file scanning less and still passing green — which is H13's
# failure mode returning in a new form.
#
# Markers are Dutch, because that is what these pages render; they are deliberately short and
# structural (a heading, a label) rather than whole sentences, so ordinary copy edits do not
# break the guard.
SCENARIOS = ["full", "bare", "unreliable_nopv", "unreliable_pv", "solar_empty",
             "short_window", "phase_unsupported"]


@pytest.fixture(scope="module")
def rendered(request):
    """Every scenario rendered in Dutch, as visible text — built once for the whole module.

    Module-scoped and computed in one pass because the renders are this file's entire cost: each
    scenario seeds a dataset, and `POST /results` simulates over it while `/results/benchmark`
    additionally runs §6.12's DP. The tests below are parametrized over scenario × page, so
    rendering per test would repeat the same work dozens of times — the mistake this file made
    before, at ~34s for six tests.

    Returns {scenario: {page: visible_text}}. All strings, so the tests cannot couple through it.
    """
    out: dict[str, dict[str, str]] = {}
    hdr = {"Cookie": "lang=nl"}
    prev = os.environ.get("BATTERY_SIM_DATA_DIR")

    with tempfile.TemporaryDirectory() as root:
        for scenario in SCENARIOS:
            # A fresh data dir per scenario: the dataset and the config are both persisted, and a
            # leftover from the previous scenario would silently change what the next one renders.
            d = os.path.join(root, scenario)
            os.makedirs(d, exist_ok=True)
            os.environ["BATTERY_SIM_DATA_DIR"] = d

            # config caches the resolved dir at import time in some paths, so reload the chain
            # that reads it before seeding (the idiom tests/test_slot_load.py uses).
            import app.config as config
            importlib.reload(config)
            import app.db as db
            importlib.reload(db)
            import app.dataset as dataset
            importlib.reload(dataset)
            import app.simconfig_store as simconfig_store
            importlib.reload(simconfig_store)

            # The data routes resolve a workspace from their path, and `TestClient(app)` outside a
            # `with` block never runs the lifespan that would create the default one — so the row
            # is seeded explicitly, exactly as tests/conftest.py's docstring describes.
            seed_workspace()

            frames, end, cfg_kw, topo = _frames_and_config(scenario)
            dataset.save_dataset(frames, (_WIN_START, end), "test", [], None)
            simconfig_store.save(_build_config(cfg_kw, topo))

            import app.main as main
            importlib.reload(main)
            client = TestClient(main.app)

            pages = {
                # The workspace LIST (phase 2's `GET /`): its own screen, with its own strings —
                # badges, the info box, the action set and the two deletion dialogs. Included
                # here because it is now the app's entry point and nothing else scans it.
                "/": client.get("/", headers=hdr),
                # The three-panel page, which was `GET /` until phase 2 relocated it.
                "/w/{id}/results": client.get(page(), headers=hdr),
                # The edit-workspace screen (phase 3, §2′.4): its own page with its own prose —
                # four box headings, five ⓘ blurbs, the footer and the discard dialog. Scanned
                # here rather than left to phase 6 because it is a new surface whose strings
                # nothing else looks at, and an unscanned new screen is the one this file's H13
                # reasoning says will quietly ship in English.
                "/w/{id}/edit": client.get(page().replace("/results", "/edit"), headers=hdr),
                # The configure-data screen (phase 4.1, §2′.5). A new surface with a lot of prose
                # nothing else scans: the roster's legend and role labels, the drawer's chrome, the
                # HA connection modal, the household box's ⓘ blurb, the footer, and three dialogs
                # including §2′.8's staged-but-unfetched wording. Scanned here for the same reason
                # the edit screen is — the strings that quietly ship in English are the ones on a
                # page no scan looks at.
                "/w/{id}/data": client.get(page().replace("/results", "/data"), headers=hdr),
                "/results": client.post(
                    w("/results"), json={"period": "last_1_year"}, headers=hdr
                ),
                "/results/benchmark": client.post(
                    w("/results/benchmark"), json={"period": "last_1_year"}, headers=hdr
                ),
            }
            for name, r in pages.items():
                assert r.status_code == 200, (
                    f"scenario {scenario!r}: {name} returned {r.status_code} — the fixture no "
                    f"longer produces a renderable dataset, so the scan below covers nothing"
                )
            out[scenario] = {k: _visible_text(r.text) for k, r in pages.items()}

    if prev is None:
        os.environ.pop("BATTERY_SIM_DATA_DIR", None)
    else:
        os.environ["BATTERY_SIM_DATA_DIR"] = prev
    return out


# The six surfaces scanned. Since the workspaces restructure these are four SCREENS plus two
# fragments: `/` is the list, `/w/{id}/results` is §2′.6's results screen (the battery box and the
# results, which phase 4.2 made of what was left of the three-panel page), `/w/{id}/edit` is
# §2′.4's, and `/w/{id}/data` is §2′.5's. All are scanned, because each carries prose nothing else
# looks at — and the phase-4 split moved a lot of prose between the first two.
_PAGES = [
    "/", "/w/{id}/results", "/w/{id}/edit", "/w/{id}/data",
    "/results", "/results/benchmark",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("page", _PAGES)
def test_no_forbidden_english_fragment_on_a_dutch_page(rendered, scenario, page):
    """Named regression check: the exact fragments measured leaking must be gone."""
    text = rendered[scenario][page]
    found = sorted({f for f in FORBIDDEN_FRAGMENTS if f in text})
    assert not found, f"{scenario}{page} still renders English fragments in Dutch: {found}"


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("page", _PAGES)
def test_no_english_prose_survives_on_a_dutch_page(rendered, scenario, page):
    """Open-ended check: no line should read as English prose.

    Two or more closed-class English markers in one line is the threshold — one can be a Dutch
    homograph ("in", "over", "was"), but two together is a sentence someone forgot to translate.
    """
    offenders = []
    for line in rendered[scenario][page].split("\n"):
        line = line.strip()
        if not line:
            continue
        words = [w for w in re.findall(r"[A-Za-z]+", line.lower()) if w not in ALLOWED_TOKENS]
        hits = [w for w in words if w in ENGLISH_MARKERS]
        if len(hits) >= 2:
            offenders.append((sorted(set(hits)), line[:160]))
    assert not offenders, (
        f"untranslated English prose on a Dutch page ({scenario}{page}):\n"
        + "\n".join(f"  {h}: {t}" for h, t in offenders)
    )


def test_the_scenarios_between_them_render_a_lot_of_prose(rendered):
    """The coverage floor: these pages must actually be full of text.

    A scan asserts the ABSENCE of English, so it passes trivially against a page that rendered
    nothing — an empty fallback, a 200 carrying an error stub, a dataset that stopped simulating.
    That is the failure mode `followups.md` H13 describes, and the one this whole rewrite exists
    to remove, so it is asserted rather than assumed.

    The thresholds are deliberately loose: this is a floor against collapse, not a golden-output
    test that ordinary copy edits would break.
    """
    for scenario in SCENARIOS:
        for page in _PAGES:
            text = rendered[scenario][page]
            words = len(re.findall(r"[A-Za-z]+", text))
            # The benchmark box is a handful of figures and one gloss sentence, and its SHORTEST
            # legitimate form is the "even perfect foresight could not have avoided any import"
            # case — which `unreliable_pv` reaches honestly, at 33 words. The floor sits below
            # that rather than above it, because the box collapsing to nothing is what this
            # guards against, not the box being terse.
            # The workspace list is one card and a handful of badges — no panels, no caveats — so
            # the panel floor does not apply to it. Its own floor sits below the ~110 words one
            # card plus the two dialogs render, for the same reason as the benchmark box's: this
            # guards against the screen collapsing to nothing, not against it being brief.
            # The edit screen is four boxes of controls with five ⓘ blurbs and a dialog — real
            # prose, but not three panels of caveats. Its floor sits below the ~150 words it
            # renders, guarding against collapse rather than asserting verbosity, for the same
            # reason as the list's.
            # The configure-data screen carries the roster, the drawer's chrome, the HA modal and
            # three dialogs, so it is prose-rich even in the empty state (~390 words there, more
            # once the quality box and the glance appear). The RESULTS screen lost panel ① in phase
            # 4.2 and gained §2′.6's own copy — the tab labels, the Blocked dialog, the "not the
            # nameplate figure" hint — and still renders ~570 words in the empty state. Both take
            # the same floor, which guards against collapse rather than asserting verbosity.
            floor = (
                25 if page == "/results/benchmark"
                else 60 if page == "/"
                else 100 if page == "/w/{id}/edit"
                else 200
            )
            assert words >= floor, (
                f"{scenario}{page} rendered only {words} words, below the {floor}-word floor — "
                f"the page has collapsed to an empty or error state and the English scan above "
                f"is passing against nothing"
            )


# What each scenario exists to put on the page, as a Dutch marker that must appear somewhere in
# its three renders. This is the coverage floor that matters: without it, a change that stopped
# rendering a box would leave the scan above passing while silently covering less — H13's failure
# mode in a new form.
#
# Markers are short and structural (a heading, a label, a distinctive clause) rather than whole
# sentences, so ordinary copy edits do not break the guard. Each names the branch it stands for.
_SCENARIO_MARKERS = {
    # cost simulation on → the euro half of the results and the spot-price slots. The waterfall
    # heading, not "Kostenbesparing": that is a SUBSTRING of the cost toggle's "Kostenbesparing
    # simuleren?", which renders whether cost simulation is on or off (it moved from the setup band
    # into the results block in phase 4.2, and is still drawn either way), so it would match a
    # scenario that had quietly lost its euro section entirely.
    "full": ["Waar het geld vandaan komt", "Spotprijs"],
    # PV asked and answered. The question is on the configure-data screen (§2′.7), and renders
    # either way, so the marker for the cost-OFF branch is the Pricing box being ABSENT — checked
    # separately below.
    "bare": ["Heb je zonnepanelen?"],
    # the reconstruction clamped hard → the unreliable-load warning and the clamp figure
    "unreliable_nopv": ["niet betrouwbaar", "afgekapt"],
    "unreliable_pv": ["niet betrouwbaar"],
    # a mapped solar sensor that reported nothing over the window
    "solar_empty": ["zonnesensor"],
    # under the 90-day annualisation floor
    "short_window": ["jaarprojectie is uitgeschakeld"],
    # an unsupported battery topology the user has NOT accepted → check 18's warning
    "phase_unsupported": ["niet in v1", "versie 1 niet volledig ondersteund"],
}


def test_each_scenario_still_surfaces_its_boxes(rendered):
    """Every scenario must still render the branch it was built to reach.

    The scenarios exist because several branches are mutually exclusive (see the note above
    `_frames_and_config`), so each one is the ONLY place some strings appear. If a scenario stops
    reaching its branch — a threshold moves, a default changes, a box is gated differently — the
    scan above keeps passing while quietly covering less. This is the check that fails instead.
    """
    for scenario, markers in _SCENARIO_MARKERS.items():
        # The markers live on the results and configure-data screens and the two fragments, not on
        # the list — the list carries none of those boxes. Joining all six is still right: a marker
        # only has to appear SOMEWHERE, and including the list costs nothing.
        blob = " ".join(rendered[scenario][p] for p in _PAGES)
        for marker in markers:
            assert marker in blob, (
                f"scenario {scenario!r} no longer renders {marker!r}, so the branch it exists to "
                f"cover is no longer being scanned for untranslated English"
            )


def test_the_marker_table_covers_every_scenario():
    """A scenario added without a marker would run without a coverage floor — fail instead."""
    missing = sorted(set(SCENARIOS) - set(_SCENARIO_MARKERS))
    assert not missing, f"scenarios with no coverage marker: {missing}"


def test_the_cost_branches_are_both_reached(rendered):
    """The cost-ON and cost-OFF halves must each be exercised by some scenario.

    This is the split that carries the most prose — the whole euro section, the pricing box and
    four euro-only caveats on one side, the "enable cost simulation" affordance and the cost-OFF
    negative-saving wording on the other. Asserted as presence-and-absence rather than as two
    markers, because "cost-OFF" is defined by the euro section NOT rendering, and a marker table
    cannot express that.
    """
    # The waterfall heading appears only inside the euro section. "Kostenbesparing" would be the
    # obvious marker and is the wrong one: the setup band renders "Kostenbesparing simuleren?"
    # in both branches, so a substring test on it passes even when the euro section is gone.
    euro_only = "Waar het geld vandaan komt"
    on = " ".join(rendered["full"][p] for p in _PAGES)
    off = " ".join(rendered["bare"][p] for p in _PAGES)
    assert euro_only in on, (
        "the cost-ON scenario no longer renders the euro section, so the euro caveats and the "
        "pricing box are not being scanned"
    )
    assert euro_only not in off, (
        "the cost-OFF scenario now renders the euro section, so the cost-OFF wordings — which "
        "only exist on that branch — are no longer reached by any scenario"
    )


def test_the_english_page_is_unaffected(rendered):
    """Sanity check on the test itself: the same pages in English are full of these markers, so a
    passing Dutch result means the strings were translated — not that the extractor is broken.

    Uses the plain app (no seeded dataset) because the point is about the LANGUAGE, not the data:
    the English page is full of English whether or not a dataset is stored.

    The workspace ROW still has to exist, since phase 2 the page is the scoped `/w/{id}/results`
    and an unknown id is a 404 — which would render as zero markers and look like `_visible_text`
    being broken, i.e. exactly the failure this test claims to distinguish. Seeded under the
    session-wide temp data dir `tests/conftest` sets up; the `rendered` fixture has already
    restored `BATTERY_SIM_DATA_DIR` to it by the time this runs.
    """
    from app.main import app as plain_app

    seed_workspace()
    hdr = {"Cookie": "lang=en"}
    text = _visible_text(TestClient(plain_app).get(page(), headers=hdr).text)
    words = re.findall(r"[A-Za-z]+", text.lower())
    # `word`, not `w` — `w` is conftest's URL helper, and shadowing it here would be a live
    # trap for the next person who adds a scoped request to this test.
    assert sum(word in ENGLISH_MARKERS for word in words) > 20, (
        "the English page should be full of English markers; if not, _visible_text is broken"
    )


# ── The validation messages ──────────────────────────────────────────────────────────────────
#
# `params_view.ISSUE_MESSAGES` is prose a user sees, and none of it renders from a stored config:
# each message needs a specific INVALID submission to surface. So it is driven through POST
# /params rather than through the dataset fixtures above.
#
# Driven off the table itself rather than a copied list of codes, so a message added later is
# covered without editing this file — the failure mode of a hardcoded list is that it silently
# stops covering what was added after it was written.


def _params_form(**overrides) -> dict:
    """A syntactically complete panel-② submission, valid unless an override breaks it."""
    form = {
        "battery.usable_capacity_kwh": "10", "battery.min_soc_pct": "10",
        "battery.max_soc_pct": "100", "battery.max_charge_kw": "5",
        "battery.max_discharge_kw": "5", "battery.roundtrip_efficiency": "90",
        "battery.roundtrip_dc_bonus": "0", "battery.standby_w": "30",
        "battery.initial_soc_pct": "50", "battery.coupling": "ac",
        "grid.phases": "3", "grid.fuse_a": "25",
        "policy.charge_policy": "P1", "policy.discharge_policy": "D1",
        "policy.band_a": "-1", "policy.band_b": "0.10",
        "policy.band_c": "0.20", "policy.band_d": "9.999",
        "dp_soc_levels": "21", "dp_action_levels": "21",
    }
    form.update(overrides)
    return form


# One submission per issue code, chosen to trigger exactly that check. A code with no entry here
# fails the completeness test below rather than being skipped quietly.
_ISSUE_TRIGGERS = {
    "not_a_number": {"battery.usable_capacity_kwh": "abc"},
    "soc_window_empty": {"battery.min_soc_pct": "90", "battery.max_soc_pct": "20"},
    "soc_pct_out_of_range": {"battery.min_soc_pct": "150"},
    "power_not_positive": {"battery.max_charge_kw": "0"},
    "power_negative": {"battery.roundtrip_dc_bonus": "-5"},
    "rte_out_of_range": {"battery.roundtrip_efficiency": "20"},
    "capacity_not_positive": {"battery.usable_capacity_kwh": "0"},
    "standby_negative": {"battery.standby_w": "-1"},
    "phases_unsupported": {"grid.phases": "2"},
    "dp_levels_too_few": {"dp_soc_levels": "1"},
    "bands_overlap": {"policy.band_b": "0.30", "policy.band_c": "0.10"},
    "band_inverted": {"policy.band_a": "0.50", "policy.band_b": "0.10"},
    "initial_soc_outside_window": {"battery.initial_soc_pct": "5"},
    "dc_efficiency_above_unity": {"battery.roundtrip_efficiency": "100",
                                  "battery.roundtrip_dc_bonus": "10"},
}


def test_every_issue_message_has_a_trigger():
    """`_ISSUE_TRIGGERS` must cover the whole table, so a message added later is not skipped."""
    from app.params_view import ISSUE_MESSAGES

    missing = sorted(set(ISSUE_MESSAGES) - set(_ISSUE_TRIGGERS))
    assert not missing, (
        f"validation messages with no trigger here, so their Dutch is never scanned: {missing}"
    )


@pytest.mark.parametrize("code", sorted(_ISSUE_TRIGGERS))
def test_validation_messages_are_dutch(code, tmp_path, monkeypatch):
    """Each validation message renders, and renders without English prose.

    Two assertions in one test on purpose: that the submission actually reached the check it was
    written for (otherwise the scan covers nothing), and that what came back reads as Dutch.

    Runs against an isolated data dir: POST /params PERSISTS the submitted parameter set, and
    seeding a workspace writes a row, so without the redirect this test would edit the developer's
    real instance as a side effect of running the suite.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.workspaces as workspaces
    importlib.reload(workspaces)

    seed_workspace()

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    r = client.post(w("/params"), data=_params_form(**_ISSUE_TRIGGERS[code]),
                    headers={"Cookie": "lang=nl"})
    assert r.status_code in (200, 422), f"{code}: POST /params returned {r.status_code}"
    text = _visible_text(r.text)

    offenders = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        words = [w for w in re.findall(r"[A-Za-z]+", line.lower()) if w not in ALLOWED_TOKENS]
        hits = [w for w in words if w in ENGLISH_MARKERS]
        if len(hits) >= 2:
            offenders.append((sorted(set(hits)), line[:160]))
    assert not offenders, (
        f"untranslated English in the panel-② error state for {code!r}:\n"
        + "\n".join(f"  {h}: {t}" for h, t in offenders)
    )
