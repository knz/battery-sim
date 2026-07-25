"""Unit tests for the translation mechanism itself (app/i18n.py).

Three things are pinned here, each of which was a real defect or a live trap before the section-A
i18n pass (see changelog/20260725-followups-section-a-investigation.md):

1. **The percent trap.** The i18n extension used to be installed with `newstyle=True`, which runs
   printf substitution on the *result* of every `_()`. A literal "%" in a translatable string was
   therefore a hazard: "50% saved" silently rendered as "50{}aved", and "50%z" raised ValueError —
   a 500 on a page the user was reading. `test_literal_percent_*` pins the fixed behaviour so the
   trap cannot return unnoticed.

2. **Explicit interpolation.** With newstyle off, strings carrying real placeholders go through
   `i18n.interpolate` (exposed to templates as a filter). `test_interpolate_*` covers substitution
   and the loud-failure-on-missing-key contract.

3. **The locale race.** Environments used to be one shared module-level object mutated with the
   request's catalog immediately before rendering — not atomic, and the sync routes run in a
   threadpool. `test_concurrent_mixed_locale_renders_do_not_cross_contaminate` drives both locales
   from many threads at once; it is the only test here that would have failed before the change.
"""

import concurrent.futures

import pytest

from app import i18n


# ── 1. The percent trap ────────────────────────────────────────────────────────────────────────


def _render(code: str, source: str, **ctx) -> str:
    """Render a template string through the real per-locale environment."""
    return i18n.env_for(code).from_string(source).render(**ctx)


@pytest.mark.parametrize(
    "text",
    [
        "50% saved",          # "% s" was eaten as a %s conversion -> "50{}aved"
        "a 50%z thing",       # "%z" raised ValueError -> 500
        "100% of the time",   # "% o" -> octal conversion
        "up 5%, down 3%",
    ],
)
def test_literal_percent_survives_translation(text):
    """A literal ASCII % passes through `_()` unchanged, whatever follows it.

    Under the old newstyle=True install these either corrupted the string or raised. The fullwidth
    "％" workaround the README used to mandate is no longer needed.
    """
    assert _render("en", "{{ _(s) }}", s=text) == text


def test_literal_percent_survives_in_dutch_too():
    """The same holds for a non-default catalog: nothing re-formats a translated result."""
    assert _render("nl", "{{ _(s) }}", s="50% saved") == "50% saved"


# ── 2. Explicit interpolation ──────────────────────────────────────────────────────────────────


def test_interpolate_substitutes_named_placeholders():
    assert i18n.interpolate("max import %(kw)s kW", kw=17.3) == "max import 17.3 kW"


def test_interpolate_handles_repeated_and_multiple_placeholders():
    out = i18n.interpolate("[%(a)s, %(b)s] vs [%(a)s, %(c)s]", a=1, b=2, c=3)
    assert out == "[1, 2] vs [1, 3]"


def test_interpolate_raises_on_missing_key():
    """A placeholder with no value is a caller bug; failing loudly beats shipping a half-filled
    string to the user, which is what a .get()-style default would do."""
    with pytest.raises(KeyError):
        i18n.interpolate("max import %(kw)s kW")


def test_interpolate_available_as_a_template_filter():
    """Templates use it as `_('… %(kw)s …') | interpolate(kw=…)`, so it must be registered on
    every per-locale environment — env_for builds each one from scratch."""
    for code in i18n.SUPPORTED:
        out = _render(code, "{{ 'v=%(x)s' | interpolate(x=7) }}")
        assert out == "v=7"


def test_interpolated_string_is_translated_before_substitution():
    """The Dutch catalog carries this msgid with its placeholder intact, so translation must
    happen first and substitution second — the reverse order would leave the msgid unmatched."""
    out = _render("nl", "{{ _('A → max import %(kw)s kW') | interpolate(kw=17.3) }}")
    assert "17.3" in out
    assert "%(kw)s" not in out
    assert "afname" in out  # the Dutch translation, not the English source


# ── 3. The locale race ─────────────────────────────────────────────────────────────────────────


def test_env_for_is_cached_per_locale():
    assert i18n.env_for("en") is i18n.env_for("en")
    assert i18n.env_for("en") is not i18n.env_for("nl")


def test_each_locale_env_resolves_its_own_catalog():
    src = "{{ _('A → max import %(kw)s kW') }}"
    assert _render("en", src) == "A → max import %(kw)s kW"
    assert "afname" in _render("nl", src)


def test_concurrent_mixed_locale_renders_do_not_cross_contaminate():
    """The regression test for the shared-env locale race.

    The old code installed the request's catalog onto one shared module-level environment and then
    rendered from it. Install-then-render is not atomic and the sync routes run in a threadpool, so
    an interleaving of install(en) / install(nl) / render(en) served Dutch under an English render.

    Driving both locales from many threads at once makes that interleaving overwhelmingly likely.
    With per-locale environments there is no post-startup mutation to interleave with, so every
    render must match the locale it asked for.
    """
    src = "{{ _('A → max import %(kw)s kW') }}"
    expected = {code: _render(code, src) for code in ("en", "nl")}
    assert expected["en"] != expected["nl"], "test is vacuous if the catalogs agree"

    def one(i: int) -> tuple[str, str]:
        code = "en" if i % 2 == 0 else "nl"
        return code, _render(code, src)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(one, range(400)))

    mismatches = [(c, got) for c, got in results if got != expected[c]]
    assert not mismatches, f"{len(mismatches)} renders got the wrong locale's catalog"


# ── 4. The drawer/fetcher JS string block ──────────────────────────────────────────────────────
#
# ha_fetch.js reads its user-facing strings from the #drawer-i18n JSON block rendered by
# index.html. The block is easy to break silently in two ways, and neither shows up on the page:
#
#   * a key used by the JS but absent from the block falls back to the English literal baked into
#     the t()/ti() call site, so the UI stays in English with nothing flagged;
#   * a string carrying a runtime value is useless if its placeholders are lost in translation,
#     and the Dutch strings deliberately REORDER them ("%(slot)s ophalen"), which is exactly why
#     the values are not concatenated in JS.

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_PATH = REPO_ROOT / "app" / "static" / "ha_fetch.js"


def _drawer_i18n(code: str) -> dict:
    """The #drawer-i18n payload as the browser would parse it, for one locale.

    Goes through the real route rather than rendering index.html with a hand-built context: the
    template's context is app/main.py's business, and duplicating it here would make this test
    fail whenever that context grows.
    """
    from starlette.testclient import TestClient

    from app.main import app

    html = TestClient(app).get("/", headers={"Cookie": f"lang={code}"}).text
    block = re.search(
        r'<script id="drawer-i18n" type="application/json">(.*?)</script>', html, re.S
    )
    assert block, "#drawer-i18n block missing from index.html"
    return json.loads(block.group(1))


def test_every_js_string_key_is_rendered():
    """Every key ha_fetch.js looks up must exist in the block, or the UI silently falls back to
    the English literal baked into the call site."""
    js = JS_PATH.read_text(encoding="utf-8")
    used = set(re.findall(r'\bti?\(\s*"([a-z0-9_]+)"', js))
    rendered = set(_drawer_i18n("en"))
    assert used, "found no t()/ti() call sites — the scraping regex is probably wrong"
    assert used <= rendered, f"keys used in JS but not rendered: {sorted(used - rendered)}"


def test_drawer_strings_are_actually_translated_in_dutch():
    """Every drawer string should differ between EN and NL, bar a few that legitimately match.

    A string that is identical in both is usually one that never made it into the catalogs: the
    Dutch render then falls back to the English source and nothing on the page says so. Comparing
    the two locales is the cheapest way to notice.
    """
    en, nl = _drawer_i18n("en"), _drawer_i18n("nl")
    same = [k for k in en if en[k] == nl[k]]
    # A few are legitimately identical across locales (proper nouns, symbols, "Token"-likes).
    allowed = {"ha_source", "failed_reason", "ha_error"}
    unexpected = sorted(set(same) - allowed)
    assert not unexpected, f"identical in EN and NL — probably not extracted: {unexpected}"


def test_placeholder_carrying_strings_keep_their_placeholders_in_both_locales():
    """A translation that drops or renames a placeholder renders a literal '%(slot)s' to the user.
    The Dutch strings deliberately reorder them (e.g. '%(slot)s ophalen'), which is the whole
    reason the value is not concatenated in JS — so the names must survive, not the positions."""
    for code in i18n.SUPPORTED:
        block = _drawer_i18n(code)
        for key, names in {
            "fetching_slot": {"slot", "n", "total"},
            "loading_slot": {"slot"},
            "imported_series": {"count"},
            "connected_counts": {"energy", "price"},
            "ingest_rejected": {"reason"},
            "ws_open_failed": {"url"},
            "ws_connect_failed": {"url"},
        }.items():
            found = set(re.findall(r"%\((\w+)\)s", block[key]))
            assert found == names, f"{code}/{key}: expected {sorted(names)}, got {sorted(found)}"


def test_no_user_facing_literal_left_in_the_status_calls():
    """setStatus() renders straight into the page, so a bare string literal there is untranslated
    text on a Dutch page. Every call must route through t()/ti() or a variable."""
    js = JS_PATH.read_text(encoding="utf-8")
    offenders = [
        m.group(0)
        for m in re.finditer(r'setStatus\([^,]+,\s*"([^"]+)"', js)
        if m.group(1).strip()
    ]
    assert not offenders, f"untranslated literals passed to setStatus: {offenders}"


def test_all_msgids_in_the_block_are_extractable():
    """Guards the extractor gap directly: re-extract and assert every string the block renders is
    a known msgid. Catches a future rewrite that puts them back somewhere Babel cannot see."""
    pot = REPO_ROOT / "app" / "locales" / "messages.pot"
    known = set(re.findall(r'^msgid ((?:"[^"]*"\s*)+)', pot.read_text(encoding="utf-8"), re.M))
    known = {"".join(re.findall(r'"([^"]*)"', k)) for k in known}
    missing = [v for v in _drawer_i18n("en").values() if v and v not in known]
    assert not missing, f"rendered but absent from messages.pot: {missing}"


# ── 5. The _msg.html macro and catalog placeholder parity ──────────────────────────────────────
#
# View-models that need runtime figures in a sentence emit a (msgid, params) pair rather than a
# finished string (app/results_view.py's _msg/_msg_n), and `templates/_msg.html` renders it:
# translate the constant msgid, THEN substitute. These pin the macro's contract and the catalog
# invariant `i18n.interpolate`'s docstring relies on.

MSG_TPL = '{% from "_msg.html" import msg with context %}{{ msg(m) }}'


def _msg_render(code: str, m) -> str:
    return i18n.env_for(code).from_string(MSG_TPL).render(m=m)


@pytest.mark.parametrize("empty", ["", None, {}])
def test_msg_renders_nothing_for_an_empty_value(empty):
    """The guard exists because `_('')` returns the catalog's METADATA entry — the whole PO header,
    "Project-Id-Version: … POT-Creation-Date: …" — dumped onto the page. `None` would render the
    string "None". A view-model leaving a field unset must produce nothing, not either of those."""
    out = _msg_render("en", empty)
    assert out == "", f"expected empty output, got {out[:80]!r}"


def test_msg_renders_a_plain_string_through_gettext():
    assert _msg_render("nl", "Not built yet") == "Nog niet gebouwd"


def test_msg_substitutes_pair_params_after_translating():
    m = {"msgid": "A → max import %(kw)s kW", "params": {"kw": "17.3"}}
    assert _msg_render("en", m) == "A → max import 17.3 kW"
    nl = _msg_render("nl", m)
    assert "17.3" in nl and "%(kw)s" not in nl and "afname" in nl


@pytest.mark.parametrize("n,expected", [(1, "1 interval"), (2, "2 intervals"), (0, "0 intervals")])
def test_msg_uses_ngettext_for_counted_messages(n, expected):
    """The counted branch is what fixes "1 intervals". It is also the branch with the least natural
    coverage — the HTTP routes only ever render it at one count — so it is pinned directly."""
    m = {
        "msgid": "simulated %(res)s · %(n)s interval",
        "plural": "simulated %(res)s · %(n)s intervals",
        "n": n,
        "params": {"res": "hourly", "n": n},
    }
    assert _msg_render("en", m) == f"simulated hourly · {expected}"


def test_msg_escapes_interpolated_values():
    """The macro runs in an autoescaping environment; a value carrying markup must not become live
    HTML just because it took the translate-then-interpolate path."""
    m = {"msgid": "value: %(v)s", "params": {"v": "<b>x</b>"}}
    assert "<b>" not in _msg_render("en", m)


def test_catalog_translations_keep_every_placeholder_their_msgid_has():
    """The invariant `i18n.interpolate` degrades on rather than raising.

    A translation that drops a `%(name)s` renders a sentence missing a figure — readable, but
    wrong, and only in that language. interpolate() deliberately does not raise for it (that would
    turn a one-catalog wording defect into a 500), so the catalogs are where it has to be caught.
    """
    import re as _re
    from pathlib import Path as _Path

    failures = []
    for code in i18n.SUPPORTED:
        po = _Path(__file__).resolve().parent.parent / "app" / "locales" / code / "LC_MESSAGES" / "messages.po"
        text = po.read_text(encoding="utf-8")
        # entries are blank-line separated; join continuation strings per field
        for entry in text.split("\n\n"):
            if "msgid " not in entry or "Project-Id-Version" in entry:
                continue

            def _field(name: str) -> str | None:
                m = _re.search(rf'^{name}((?:\s*"[^"]*")+)', entry, _re.M)
                return "".join(_re.findall(r'"([^"]*)"', m.group(1))) if m else None

            src = _field("msgid")
            if not src:
                continue
            want = set(_re.findall(r"%\((\w+)\)s", src))
            if not want:
                continue
            for field in ("msgstr", r"msgstr\[0\]", r"msgstr\[1\]"):
                got_text = _field(field)
                if not got_text:
                    continue
                got = set(_re.findall(r"%\((\w+)\)s", got_text))
                if got != want:
                    failures.append(f"{code}: {src[:60]!r} has {sorted(want)}, translation has {sorted(got)}")
    assert not failures, "translations dropped or renamed placeholders:\n" + "\n".join(failures)
