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

import re

import pytest
from starlette.testclient import TestClient

from app.main import app

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


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _visible_text(html: str) -> str:
    """Strip scripts, styles and tags, leaving what a reader sees."""
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"[ \t]+", " ", html)


@pytest.fixture(scope="module")
def dutch_text(client) -> dict[str, str]:
    """The three renders that between them contain every user-facing string, as visible text.

    Module-scoped because the renders are the expensive part of this file by a wide margin: on a
    machine with a real `data/` directory, `POST /results` runs a simulation over the stored
    dataset, and the three renders together cost ~5.7s. Both tests below are parametrized over
    the same three pages, so computing them per test ran the same three renders six times — ~34s
    to arrive at the same HTML — and each call discarded two of the three pages it had just built.

    The strip to visible text is cached here too rather than in the tests, because that is what
    both tests actually consume; caching the raw HTML would leave `_visible_text` running six
    times over the same markup.

    Returned strings are immutable and the tests only read them, so sharing across tests cannot
    couple them. What this fixture does NOT fix is the coverage question in `followups.md` H13:
    which boxes these pages render still depends on the developer's stored dataset and config,
    so a green run here still does not prove the catalogs are complete.
    """
    hdr = {"Cookie": "lang=nl"}
    index = client.get("/", headers=hdr)
    results = client.post("/results", json={"period": "last_1_year"}, headers=hdr)
    bench = client.post("/results/benchmark", json={"period": "last_1_year"}, headers=hdr)
    for name, r in (("/", index), ("/results", results), ("/results/benchmark", bench)):
        assert r.status_code == 200, f"{name} returned {r.status_code}"
    return {
        "/": _visible_text(index.text),
        "/results": _visible_text(results.text),
        "/results/benchmark": _visible_text(bench.text),
    }


@pytest.mark.parametrize("page", ["/", "/results", "/results/benchmark"])
def test_no_forbidden_english_fragment_on_a_dutch_page(dutch_text, page):
    """Named regression check: the exact fragments measured leaking must be gone."""
    text = dutch_text[page]
    found = sorted({f for f in FORBIDDEN_FRAGMENTS if f in text})
    assert not found, f"{page} still renders English fragments in Dutch: {found}"


@pytest.mark.parametrize("page", ["/", "/results", "/results/benchmark"])
def test_no_english_prose_survives_on_a_dutch_page(dutch_text, page):
    """Open-ended check: no line should read as English prose.

    Two or more closed-class English markers in one line is the threshold — one can be a Dutch
    homograph ("in", "over", "was"), but two together is a sentence someone forgot to translate.
    """
    offenders = []
    for line in dutch_text[page].split("\n"):
        line = line.strip()
        if not line:
            continue
        words = [w for w in re.findall(r"[A-Za-z]+", line.lower()) if w not in ALLOWED_TOKENS]
        hits = [w for w in words if w in ENGLISH_MARKERS]
        if len(hits) >= 2:
            offenders.append((sorted(set(hits)), line[:160]))
    assert not offenders, "untranslated English prose on a Dutch page:\n" + "\n".join(
        f"  {h}: {t}" for h, t in offenders
    )


def test_the_english_page_is_unaffected(client):
    """Sanity check on the test itself: the same pages in English are full of these markers, so a
    passing Dutch result means the strings were translated — not that the extractor is broken."""
    hdr = {"Cookie": "lang=en"}
    text = _visible_text(client.get("/", headers=hdr).text)
    words = re.findall(r"[A-Za-z]+", text.lower())
    assert sum(w in ENGLISH_MARKERS for w in words) > 20, (
        "the English page should be full of English markers; if not, _visible_text is broken"
    )
