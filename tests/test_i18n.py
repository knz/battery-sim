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
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from app import i18n
from tests.conftest import data_page, page, seed_workspace, w


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
    happen first and substitution second — the reverse order would leave the msgid unmatched.

    The sample used to be "A → max import %(kw)s kW", the Grid connection box's fuse line. §2′.1
    moved that box to the edit-workspace screen, which prints the figure inside its connection
    dropdown instead, so the msgid stopped being extracted and the catalog no longer carries it.
    Any live msgid with a placeholder and a Dutch translation proves the same ordering.
    """
    out = _render("nl", "{{ _('%(n)s / day') | interpolate(n=17.3) }}")
    assert "17.3" in out
    assert "%(n)s" not in out
    assert "dag" in out  # the Dutch translation, not the English source


# ── 3. The locale race ─────────────────────────────────────────────────────────────────────────


def test_env_for_is_cached_per_locale():
    assert i18n.env_for("en") is i18n.env_for("en")
    assert i18n.env_for("en") is not i18n.env_for("nl")


def test_each_locale_env_resolves_its_own_catalog():
    src = "{{ _('%(n)s / day') }}"
    assert _render("en", src) == "%(n)s / day"
    assert "dag" in _render("nl", src)


def test_concurrent_mixed_locale_renders_do_not_cross_contaminate():
    """The regression test for the shared-env locale race.

    The old code installed the request's catalog onto one shared module-level environment and then
    rendered from it. Install-then-render is not atomic and the sync routes run in a threadpool, so
    an interleaving of install(en) / install(nl) / render(en) served Dutch under an English render.

    Driving both locales from many threads at once makes that interleaving overwhelmingly likely.
    With per-locale environments there is no post-startup mutation to interleave with, so every
    render must match the locale it asked for.
    """
    src = "{{ _('%(n)s / day') }}"
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
# `workspace_data.html`. That is the ONLY page rendering the block since phase 4.2: the results
# screen dropped the drawer, the HA modal and `ha_fetch.js` along with panel ① (§2′.6), so the
# block moved with the module that reads it. The block is easy to break silently in two ways, and
# neither shows up on the page:
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

    Goes through the real route rather than rendering the template with a hand-built context: the
    context is app/main.py's business, and duplicating it here would make this test fail whenever
    that context grows.

    Reads `/w/{id}/data`, the configure-data screen — the one page that still renders the block
    (module comment). It is a SCOPED route, so the workspace row has to exist before the request:
    `TestClient(app)` outside a `with` block runs no lifespan and this module seeds nothing else.
    It writes into the session-wide temp data dir `tests/conftest` sets up, never the developer's
    `./data`.
    """
    from starlette.testclient import TestClient

    from app.main import app

    seed_workspace()
    html = TestClient(app).get(data_page(), headers={"Cookie": f"lang={code}"}).text
    block = re.search(
        r'<script id="drawer-i18n" type="application/json">(.*?)</script>', html, re.S
    )
    assert block, "#drawer-i18n block missing from workspace_data.html"
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
# finished string (app/i18n.msg / .msg_n, aliased `_msg`/`_msg_n` in the view modules that build
# them — app/results_view.py and app/data_view.py), and `templates/_msg.html` renders it:
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
    m = {"msgid": "%(n)s / day", "params": {"n": "17.3"}}
    assert _msg_render("en", m) == "17.3 / day"
    nl = _msg_render("nl", m)
    assert "17.3" in nl and "%(n)s" not in nl and "dag" in nl


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


def test_msg_translates_a_nested_message_param():
    """A param that is itself a message is translated BEFORE it is substituted.

    The case this exists for is an embedded label — a resolution word like "hourly", which appears
    inside half a dozen larger sentences (app/data_view._res_msg). Passed as a bare string it would
    survive translation untouched, because interpolation runs after `_()` and never sees the msgid
    of a value. So the whole point is that the inner msgid gets its own lookup.
    """
    inner = {"msgid": "hourly", "params": {}}
    m = {"msgid": "%(res)s (full)", "params": {"res": inner}}
    assert _msg_render("en", m) == "hourly (full)"
    # A bare-string param must still pass through as data, untranslated.
    assert _msg_render("en", {"msgid": "%(res)s (full)", "params": {"res": "hourly"}}) \
        == "hourly (full)"


def test_msg_escapes_a_nested_message_only_once():
    """A nested message renders to Markup, so `interpolate` must not escape it a second time.

    Without that, a label containing a "&" (or the "·" a msgid may carry) would come out
    double-escaped as "&amp;amp;". The inner value's own params are still escaped, once.
    """
    inner = {"msgid": "%(v)s", "params": {"v": "a & b"}}
    out = _msg_render("en", {"msgid": "x: %(res)s", "params": {"res": inner}})
    assert out == "x: a &amp; b", out


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


# ── 6. A literal "%" is inert on EVERY path ────────────────────────────────────────────────────
#
# The A2 fix (newstyle=False) made "%" safe under `_()`. The (msgid, params) mechanism added
# afterwards re-opened the hazard for its own subset, because `interpolate` %-formats the
# translated string: "50% saved" rendered as "50{}aved" and "50%z" raised, i.e. a 500. That
# subset is the worst place for it — those msgids are full sentences a translator edits, and a
# Dutch string reading "50% lager" is ordinary copy nobody would think twice about. The failure
# would appear only in Dutch, on a page that renders fine in English.
#
# So: "%" is now doubled before substitution unless it begins a %(name)s placeholder. There is no
# escape sequence to remember — "%%" is two literal characters, not one.


@pytest.mark.parametrize(
    "msgid,params,expected",
    [
        ("50% saved", {}, "50% saved"),
        ("a 50%z thing", {}, "a 50%z thing"),          # would have raised ValueError
        ("100%% sure", {}, "100%% sure"),              # no escape sequence: %% is literal
        ("50% of the %(v)s", {"v": "x"}, "50% of the x"),   # literal AND placeholder together
        ("%(v)s 50%", {"v": "x"}, "x 50%"),            # trailing % (would have raised)
        ("up %(a)s%, down %(b)s%", {"a": "5", "b": "3"}, "up 5%, down 3%"),
    ],
)
def test_literal_percent_is_inert_in_a_message_pair(msgid, params, expected):
    assert _msg_render("en", {"msgid": msgid, "params": params}) == expected


def test_literal_percent_is_inert_in_a_counted_message():
    m = {"msgid": "%(n)s%% off", "plural": "%(n)s%% off", "n": 2, "params": {"n": 2}}
    assert _msg_render("en", m) == "2%% off"


def test_literal_percent_is_inert_in_a_translation():
    """The case that actually matters: the hazard is in the msgSTR, not the msgid. A translator
    writing an ordinary percentage must not be able to 500 the page."""
    assert i18n.interpolate("50% lager dan %(x)s", x="normaal") == "50% lager dan normaal"


def test_interpolate_still_substitutes_and_still_raises_on_missing():
    """The percent-escaping must not have broken either half of the contract above it."""
    assert i18n.interpolate("a %(x)s b", x=1) == "a 1 b"
    with pytest.raises(KeyError):
        i18n.interpolate("a %(x)s b")


def test_interpolate_preserves_the_markup_type_of_its_template():
    """Regression guard for a hole introduced (and caught) while adding the percent escaping.

    `interpolate` rewrites the template to double literal "%" signs. `re.sub` returns a plain str
    even for a Markup input, so the naive version handed back a str — and `str.__mod__` does not
    escape its operands. Every value substituted into a message would then have reached the page
    unescaped, which for panel ① means Home Assistant entity ids and other file-derived data.
    Escaping is not a property of the call site here; it is carried by the template's TYPE.
    """
    from markupsafe import Markup

    out = i18n.interpolate(Markup("v=%(v)s"), v="<script>x</script>")
    assert isinstance(out, Markup)
    assert "<script>" not in out and "&lt;script&gt;" in out

    # A plain str template must stay plain (its caller's {{ }} does the escaping).
    assert not isinstance(i18n.interpolate("v=%(v)s", v="x"), Markup)


def test_a_value_with_markup_cannot_reach_the_page_unescaped_through_msg():
    """The same guarantee at the level a view-model actually uses."""
    out = _msg_render("en", {"msgid": "id: %(v)s", "params": {"v": "<img src=x onerror=1>"}})
    assert "<img" not in out
    assert "&lt;img" in out


# ── 6. Locale-aware figures (A6) ────────────────────────────────────────────────────────────────
#
# Every figure the UI shows used to be formatted with a hardcoded English convention while the
# view-model was being BUILT — `f"{x:,.0f}"` — which is before the request's locale is known. Dutch
# swaps both separators against English, so a Dutch reader saw "3,924 kWh" and "0.094 €/kWh" where
# Dutch writes "3.924 kWh" and "0,094 €/kWh".
#
# The fix mirrors what `msg()` did for sentences: a view-model emits `i18n.num(value, kind)` — the
# NUMBER plus the name of a convention — and formatting happens at RENDER time, where the locale is.
# `format_num` is the formatter and takes the locale as a REQUIRED argument, so there is no way to
# call it without saying which language it is for; `num()` is the only locale-free spelling and it
# does not format. These pin the conventions, the render-time wiring, and the two places the old
# per-helper logic lived (the U+2212 minus and the signed-zero guard).


@pytest.mark.parametrize(
    "value,kind,en,nl",
    [
        # The two separators, swapped. This pair IS the defect.
        (3924.0, "kwh", "3,924 kWh", "3.924 kWh"),
        (0.094, "eur_kwh", "0.094 €/kWh", "0,094 €/kWh"),
        # Rounding to whole kWh, and a grouping boundary in both directions.
        (999.4, "kwh", "999 kWh", "999 kWh"),
        (1000.0, "kwh", "1,000 kWh", "1.000 kWh"),
        # Integer percent of a fraction, unspaced (§2.3a's band).
        (0.31, "pct", "31%", "31%"),
        # Signed percentage to one decimal (§2.4's tile delta).
        (15.9, "pct_signed", "+15.9 %", "+15,9 %"),
        (-34.21, "pct_signed", "−34.2 %", "−34,2 %"),
        # Percentage points: a signed COUNT of points, so it keeps a sign at zero.
        (21, "dec0_signed", "+21", "+21"),
        (0, "dec0_signed", "+0", "+0"),
        # A bare grouped count and the per-day cycle rate.
        (8760, "count", "8,760", "8.760"),
        (0.23, "dec2", "0.23", "0,23"),
        # Natural precision (`%g`), for a config value quoted back at the user.
        (0.95, "general", "0.95", "0,95"),
        (10.0, "general", "10", "10"),
    ],
)
def test_figures_use_each_locales_conventions(value, kind, en, nl):
    assert i18n.format_num(value, kind, "en") == en
    assert i18n.format_num(value, kind, "nl") == nl


@pytest.mark.parametrize("kind", sorted(i18n._NUM_KINDS))
def test_every_kind_renders_a_negative_with_u2212_and_never_an_ascii_hyphen(kind):
    """The U+2212 convention, across every kind and both locales.

    It is not decoration. Some figures are explicitly signed by this module and some carry babel's
    own sign, and both locales' CLDR minus IS the ASCII hyphen — so without the substitution one
    panel would show two different minus glyphs, which is the kind of inconsistency that survives
    until someone screenshots it. Asserted per kind because a new kind is exactly where it would be
    forgotten.
    """
    for locale in ("en", "nl"):
        out = i18n.format_num(-1234.5, kind, locale)
        assert "-" not in out, f"{kind}/{locale}: ASCII hyphen in {out!r}"
        assert i18n.MINUS in out, f"{kind}/{locale}: no U+2212 in {out!r}"


def test_a_signed_zero_is_never_printed_but_a_point_delta_keeps_its_sign():
    """Two deliberately different behaviours, both inherited from the f-strings they replace.

    A saving that rounds to zero prints "0 kWh" / "0.0 %": a signed zero is a formatting artefact,
    not a measurement, and it reads as a bug. A zero-point self-sufficiency change prints "+0",
    because `f"{0:+d} pp"` did. Zero-ness is asked of the ROUNDED TEXT, not the input — −0.04
    renders "0.0" and must not carry a minus, −0.06 renders "0.1" and must.
    """
    assert i18n.format_num(-0.4, "kwh_signed", "en") == "0 kWh"
    assert i18n.format_num(-0.04, "pct_signed", "en") == "0.0 %"
    assert i18n.format_num(-0.06, "pct_signed", "en") == "−0.1 %"
    assert i18n.format_num(0, "dec0_signed", "en") == "+0"


def test_num_rejects_an_unknown_kind_where_the_view_model_is_built():
    """At `num()`, not at render: a typo'd kind is a code bug and should fail before it reaches a
    page. The alternative is a KeyError inside a Jinja filter mid-render, or worse, a silent skip."""
    with pytest.raises(KeyError):
        i18n.num(1.0, "kwh_signd")


@pytest.mark.parametrize("value", [None, "abc"])
def test_a_non_numeric_value_renders_as_text_rather_than_raising(value):
    """`params_view`/`results_view` can be handed an unvalidated config whose fields are a raw
    string or None (SimulationConfig construction never raises, by design). Formatting defensively
    is cheaper than a 500 on the page the user is looking at."""
    out = i18n.format_num(value, "general", "nl")
    assert out == ("—" if value is None else "abc")


def test_a_figure_is_formatted_by_the_msg_macro_in_the_render_locale():
    """The render-time wiring: a bare `num()` dict, and one riding inside a message's params.

    The second is the case that matters — since steps 5a/5b/5c most figures reach the page as a
    param of a (msgid, params) pair, so the macro has to format them there, not only at top level.
    """
    assert _msg_render("en", i18n.num(3924.0, "kwh")) == "3,924 kWh"
    assert _msg_render("nl", i18n.num(3924.0, "kwh")) == "3.924 kWh"

    m = i18n.msg("%(kwh)s throughput", kwh=i18n.num(2410.0, "kwh"))
    assert _msg_render("en", m) == "2,410 kWh throughput"
    assert _msg_render("nl", m).startswith("2.410 kWh")


def test_a_zero_figure_renders_rather_than_being_swallowed_by_the_empty_guard():
    """`{"num": 0, ...}` must survive the macro's falsy guard. "0 kWh" is a real figure the panels
    print — the benchmark box's "No battery" row is exactly it — and a mapping is always truthy, so
    the guard only ever sees a string or None. Pinned because the ordering that makes it safe (the
    number branch first) is easy to lose in a later edit."""
    assert _msg_render("en", i18n.num(0, "kwh")) == "0 kWh"
    assert _msg_render("en", i18n.msg("%(v)s x", v=i18n.num(0.0, "count"))) == "0 x"


def test_month_abbreviations_come_from_the_catalog_of_each_locale():
    """The monthly chart's x-axis. It read from a table of English abbreviations in `results_view`,
    which put "Jan Feb Mar" on a Dutch page's axis; babel's CLDR data has every locale's."""
    assert [i18n.month_abbr(m, "en") for m in (1, 3, 5, 10)] == ["Jan", "Mar", "May", "Oct"]
    assert [i18n.month_abbr(m, "nl") for m in (1, 3, 5, 10)] == ["jan", "mrt", "mei", "okt"]
    # Out of range renders as its own number: a broken axis label is not worth a 500 on a page of
    # figures.
    assert i18n.month_abbr(13, "en") == "13"


def test_the_number_filters_are_bound_to_their_own_locale_on_every_environment():
    """`numfmt` and `monthname` take no locale argument at the call site — they cannot, because a
    template does not know one. They are closed over the locale by `env_for`, which is only sound
    because an environment is built once per locale and never mutated (the step-3 change). If a
    filter ever read an ambient locale instead, this would catch it."""
    for code, expected in (("en", "1,234"), ("nl", "1.234")):
        env = i18n.env_for(code)
        assert env.filters["numfmt"]({"num": 1234, "fmt": "count"}) == expected
        assert env.filters["monthname"](3) == ("Mar" if code == "en" else "mrt")


@pytest.fixture()
def seeded_client(tmp_path, monkeypatch):
    """A TestClient over a synthetic dataset, for the tests that need REAL rendered figures.

    Seeded rather than read from the developer's `./data`, for the reason `docs/specs/followups.md` H13
    gives: a test driven from whatever data happens to be on the machine covers something
    different on every machine, and covers nothing at all in a fresh checkout or in CI, where
    `POST /results` has no dataset and answers 409.

    The numbers are chosen so the assertions below have something to assert ON: 1.5 kWh/h over
    40 days is ~1,440 kWh, which is four digits and therefore GROUPED, and a spot price series
    puts a €/kWh figure on the page with three decimals. A dataset that produced only
    three-digit figures would pass the "must not use the wrong separator" half of each pair
    while silently testing nothing in the "must use the right one" half.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    import numpy as np

    from app.domain.frames import QUALITY_DTYPE, SeriesFrame

    n = 40 * 24
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")

    def frame(name, kind, values):
        vals = np.full(n, float(values)) if np.isscalar(values) else np.asarray(values, float)
        return SeriesFrame(name, kind, 3600, idx, vals, np.zeros(n, dtype=QUALITY_DTYPE))

    # The results route resolves a workspace from its path, and `TestClient(app)` outside a
    # `with` block never runs the lifespan that would create the default one.
    seed_workspace()

    from app import dataset

    dataset.save_dataset(
        [
            frame("grid_import_t1", "energy", 1.5),   # ≈1,440 kWh — four digits, so grouped
            frame("grid_export_t1", "energy", 0.2),
            frame("price_spot", "price", np.where((np.arange(n) % 24) < 12, 0.042, 0.287)),
        ],
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 2, 10, tzinfo=timezone.utc)),
        "test", [], None,
        workspace_id=dataset.db.WORKSPACE_ID,
    )

    from app import main

    return TestClient(main.app)


def test_the_rendered_dutch_pages_use_dutch_number_conventions(seeded_client):
    """End-to-end, on the real routes: the defect A6 was filed for, and its fix.

    The unit tests above pin the formatter and the macro; this pins the WIRING through the whole
    stack — view-model, template, route. It asserts on the SEPARATORS rather than on any particular
    figure: a grouped figure on a Dutch page must use "." and a decimal must use ",", and the
    reverse on an English one. `\\d{1,3},\\d{3}` on a Dutch page is the exact shape of the bug.

    Runs against the seeded dataset rather than the developer's own (H13): the figures need to be
    large enough to be GROUPED for the assertions to mean anything, and that is a property of the
    data, not something the previous version of this test could guarantee.
    """
    import re

    def visible(lang: str) -> str:
        r = seeded_client.post(w("/results"), json={"period": "last_1_year"},
                               headers={"Cookie": f"lang={lang}"})
        assert r.status_code == 200
        html = re.sub(r"<(script|style).*?</\1>", " ", r.text, flags=re.S)
        return re.sub(r"<[^>]+>", " ", html)

    en, nl = visible("en"), visible("nl")

    # A grouped kWh figure exists on both pages, written each locale's way and never the other's.
    assert re.search(r"\d{1,3},\d{3} kWh", en), "English should group thousands with a comma"
    assert not re.search(r"\d{1,3}\.\d{3} kWh", en), "English must not group with a point"
    assert re.search(r"\d{1,3}\.\d{3} kWh", nl), "Dutch should group thousands with a point"
    assert not re.search(r"\d{1,3},\d{3} kWh", nl), "Dutch must not group with a comma"

    # The spot-price line, which is where the decimal separator shows.
    assert re.search(r"\d,\d{3} €/kWh", nl), "Dutch should use a decimal comma for €/kWh"
    assert not re.search(r"\d\.\d{3} €/kWh", nl), "Dutch must not use a decimal point"
    assert re.search(r"\d\.\d{3} €/kWh", en), "English should use a decimal point for €/kWh"
