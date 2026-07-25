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
