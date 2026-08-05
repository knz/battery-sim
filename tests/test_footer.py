"""The site footer (`app/templates/_footer.html`).

The footer states two things the user is entitled to see on any screen: that the app keeps their
data local, and who wrote it under what licence. Its defining property is therefore that it is on
EVERY screen — which is exactly the property a per-screen test file would not pin, because there
is no base template here and "on every screen" is four separate `{% include %}`s that a fifth
screen would silently not inherit. So the coverage lives in one file and loops over the screens.

What is pinned here:

  * **Presence on all four screens** — workspaces, edit, data, results. The loop is the test; add a
    screen and add it to `_SCREENS`.
  * **The attribution sentence renders as MARKUP, not as escaped text.** It is one msgid with four
    `%(name)s` holes filled with `Markup` anchors, and the failure mode if the `| e | interpolate
    | safe` chain is disturbed is a footer reading `<a href="...">Raphael Poss</a>` literally. A
    test that only asserted the visible words would pass while that was broken.
  * **The three external URLs** are the ones intended, since a typo in a licence or source link is
    both plausible and not otherwise caught.
  * **The warranty dialog ships with the page and the button is wired to it.** The dialog is
    opened by script from a `data-open-warranty` button, so what is checkable server-side is that
    both halves are present and agree on the id.
  * **It is translated** — the Dutch render carries neither of the two English lines. The catalogs
    could be complete and the footer still ship English if a string were left outside `_()`.

The i18n scan in `tests/test_no_english_leakage.py` covers the Dutch prose more thoroughly than
the one assertion here; this file's Dutch test is about the footer specifically being wired
through gettext at all.

    uv run pytest tests/test_footer.py
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tests.conftest import seed_workspace

# The author, licence and repository links. Kept in one place because `tests/
# test_workspace_results.py` allows exactly these three through its "no external links" assertion,
# and the two lists must not drift.
AUTHOR_URL = "https://raphaelposs.com"
SOURCE_URL = "https://github.com/knz/battery-sim"
LICENSE_URL = "https://github.com/knz/battery-sim/blob/master/LICENSE"

PRIVACY_EN = "This application does not collect your data and does not send it remotely."


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A client over an empty temp data dir with one workspace seeded.

    `monkeypatch.setenv` before importing `app.main`, as everywhere else in this suite — the app
    modules resolve the data dir per call, so the env var is enough and no reload is needed.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import main

    seed_workspace()
    return TestClient(main.app)


# Every screen that includes the footer. `GET` on each renders a full page; the results and data
# screens render without a dataset, which is fine — the footer does not depend on one.
_SCREENS = [
    ("workspaces", "/"),
    ("edit", "/w/local/edit"),
    ("data", "/w/local/data"),
    ("results", "/w/local/results"),
]


@pytest.mark.parametrize("name,url", _SCREENS, ids=[n for n, _ in _SCREENS])
def test_the_footer_is_on_every_screen(client, name, url):
    """The privacy line and the attribution line, on all four screens."""
    r = client.get(url)
    assert r.status_code == 200, f"{url} → {r.status_code}"
    assert PRIVACY_EN in r.text, f"no privacy line on the {name} screen"
    assert "is a digital creation of" in r.text, f"no attribution line on the {name} screen"


@pytest.mark.parametrize("name,url", _SCREENS, ids=[n for n, _ in _SCREENS])
def test_the_warranty_dialog_ships_with_every_screen(client, name, url):
    """Both halves of the popup: the button that opens it and the dialog it opens."""
    r = client.get(url)
    assert 'id="warranty-dialog"' in r.text, f"no warranty dialog on the {name} screen"
    assert "data-open-warranty" in r.text, f"no warranty button on the {name} screen"


def test_the_attribution_line_renders_as_markup_not_as_escaped_text(client):
    """The `| e | interpolate(...) | safe` chain, which is the fiddly part of the partial.

    The sentence is a single translatable msgid with `%(name)s` holes filled by `Markup` anchors.
    If the chain is disturbed the anchors arrive as visible text — the words are all still on the
    page, so only an assertion about the MARKUP catches it.
    """
    html = client.get("/").text

    # Anchored on the href and the tag, NOT on the full class string — the styling is a separate
    # concern with its own tests below, and pinning it here made this test fail for a restyle that
    # had nothing to do with escaping.
    assert f'<a class="link' in html and f'href="{AUTHOR_URL}"' in html
    assert "data-open-warranty>NO WARRANTY</button>" in html
    # The tell-tale of a broken chain: the anchor escaped into the visible sentence.
    assert "&lt;a class=" not in html
    assert "&lt;button" not in html
    # And no unfilled hole survived — a missing key would raise, but a surplus one degrades.
    assert "%(author)s" not in html
    assert "%(app)s" not in html


def test_the_links_are_underlined_at_rest(client):
    """daisyUI's `link-hover` hides the underline until `:hover`.

    The first draft used `link link-hover`, which rendered the four pieces as undifferentiated
    grey text inside an already-dimmed footer — nothing said "clickable" until the pointer was
    already on it. This is a markup-level proxy for that defect: the real property is the computed
    `text-decoration-line`, which only a browser can report, but `link-hover` is the one class
    that would silently turn it off and it is cheap to exclude here.
    """
    html = client.get("/").text
    i = html.index("<footer")
    footer = html[i : html.index("</footer>", i)]

    assert "link-hover" not in footer, "link-hover hides the underline until :hover"
    assert footer.count("class=\"link ") == 4, "expected four `link`-styled pieces in the footer"


def test_the_warranty_control_is_marked_as_opening_an_explanation(client):
    """It is a <button>, not an <a> — it expands a term rather than navigating.

    The dotted underline is the convention for that, and it is what distinguishes this piece from
    the three anchors beside it in the same sentence.
    """
    html = client.get("/").text
    i = html.index("data-open-warranty")
    tag = html[html.rindex("<button", 0, i) : html.index(">", i)]

    assert "decoration-dotted" in tag, "the warranty control should be dotted, not solid"


def test_the_external_links_are_the_intended_urls(client):
    """A typo in the licence or source URL is plausible and nothing else would catch it."""
    html = client.get("/").text

    assert f'href="{AUTHOR_URL}"' in html
    assert f'href="{SOURCE_URL}"' in html
    assert f'href="{LICENSE_URL}"' in html
    # Every external link opens in a new tab without handing the opener over.
    for url in (AUTHOR_URL, SOURCE_URL, LICENSE_URL):
        i = html.index(f'href="{url}"')
        assert 'rel="noopener noreferrer"' in html[i : i + 200], f"{url} has no rel=noopener"


def test_the_footer_is_translated(client):
    """The Dutch render carries the Dutch lines and neither English one.

    A string left outside `_()` would ship English here while both catalogs read as complete.
    """
    html = client.get("/", headers={"Accept-Language": "nl"}).text

    assert "Deze app verzamelt je gegevens niet" in html
    assert "is gemaakt door" in html
    assert PRIVACY_EN not in html
    assert "is a digital creation of" not in html


def test_the_dutch_footer_addresses_the_reader_informally(client):
    """The app's Dutch is informal throughout ("Je analyses", "waar je over gaat").

    Legal-sounding copy invites the formal register, and the footer's first draft was written in
    it — which would have made the disclaimer the only part of the UI addressing the reader as
    "u". Asserted on the dialog's prose, which is where the pronouns actually occur.
    """
    html = client.get("/", headers={"Accept-Language": "nl"}).text
    i = html.index('id="warranty-dialog"')
    dialog = html[i : html.index("</dialog>", i)]

    assert "ligt bij jou" in dialog
    assert "draag je zelf" in dialog
    for formal in (" uw ", " u zelf ", "aan uw "):
        assert formal not in dialog, f"formal register leaked into the footer: {formal!r}"


def test_the_warranty_dialog_states_what_is_disclaimed(client):
    """The popup's job: name the disclaimer, and point at the binding text rather than replace it.

    Asserted on substrings rather than whole paragraphs so ordinary rewording does not break the
    test — what is pinned is that each of the three claims is present, not its phrasing.
    """
    html = client.get("/").text

    assert "without warranty of any kind" in html          # AGPL §15
    assert "not liable for any damages" in html            # AGPL §16
    assert "not financial advice" in html                  # the risk specific to this program
    assert "sections 15 and 16" in html                    # and it does not replace the licence
    assert f'href="{LICENSE_URL}"' in html
