"""The closed vocabulary of feature keys for pending controls (docs/specs/02-ux-wireframes.md §2.1).

A control that is specified but not yet built renders "pending": disabled, with a `[?]`
affordance that opens the shared dialog. The dialog offers a link to file a feature request as
a GitHub issue, pre-filled with the control's name. Each such control carries a short, stable
key naming it, plus a human-readable title that goes into the issue.

Nothing about a request is recorded locally: the issue on GitHub is the whole record. This
module therefore holds no counters — it names the pending controls and composes the URL that
reports one.

Main items:
  * FEATURE_KEYS / RETIRED_KEYS — the closed vocabulary, active and shipped.
  * FEATURE_TITLES — key → human-readable control name, shown in the issue.
  * title_for(key) / is_known(key) — accessors.
  * issue_url(key) — the pre-filled GitHub "new issue" URL for a key.

Ongoing-work rule — read before adding or removing an entry:
  * When you mark a NEW control pending, add its key to FEATURE_KEYS and its title to
    FEATURE_TITLES (and only here), then reference the key from the template via
    `feature_key="<key>"`. Choose `<box>_<control>` shaped names.
  * When you BUILD a feature, remove the control's pending markup from the template and move
    the key to RETIRED_KEYS. Keep its title: issues filed under that key are still open on
    GitHub and still have to be readable. Retire, do not delete.
  * Never rename a key or repoint it at a different control — it is the join between an issue
    already filed and the control it was about (same discipline as the series names in
    docs/specs/05-data-formats.md).

`_check_titles_cover_keys()` runs at import and fails loudly if a key has no title.
"""

from urllib.parse import urlencode

# The upstream repository that receives feature requests. Matches the "Source code available"
# link in app/templates/_footer.html, which is the only other place the slug appears.
GITHUB_REPO = "knz/battery-sim"

# The issue form the link targets, .github/ISSUE_TEMPLATE/feature.yml. A YAML *form* rather
# than a Markdown template because only a form supports per-field pre-filling: the `feature`
# query parameter below fills the form's `feature` input while leaving the rest for the user.
# With a Markdown template a `body` parameter would replace the template body outright.
_ISSUE_TEMPLATE = "feature.yml"

# Active pending controls. Keep in sync with the `feature_key="..."` attributes in the
# templates. See changelog/20260723-pending-affordance-impl.md for the allocation record.
FEATURE_KEYS: frozenset[str] = frozenset(
    {
        "export_csv",            # Export CSV button (panel ③ results)
        # The Pricing box's three unbuilt options (§2.3, §6.5). `Contract` and `TlkMode` carry
        # every value so the stored parameter set and the radio labels name the same things, but
        # only DYNAMIC and FLAT have a rate source behind them: FIXED reads a `tariff_zone` axis
        # that does not exist yet, VARIABLE needs a dated `rate_schedule` that `PricingConfig`
        # does not model, and TIERED needs a tier table plus an annualisation.
        "pricing_contract_fixed",     # "Fixed" contract radio (panel ②, Pricing)
        "pricing_contract_variable",  # "Variable" contract radio (panel ②, Pricing)
        "pricing_tlk_tiered",         # "tiered by annual volume" terugleverkosten radio
    }
)

# Retired keys — features that have shipped. The keys are never reused.
RETIRED_KEYS: frozenset[str] = frozenset(
    {
        # Shipped in Phase 6 as a real checkbox (_panel_params.html, `policy.allow_grid_export`),
        # so it is no longer pending. Retired rather than deleted, per the rule above.
        "discharge_allow_export",
        # Shipped in the cost-simulation increment: the setup band's "Simulate cost savings?"
        # radios now POST to /params, and panel ② draws the whole Pricing box behind the answer.
        "simulate_cost",
        # Shipped in the CSV-import increment: "Upload CSV" is a real source radio in the
        # per-slot source drawer, with an upload dialog and File/Column/Unit controls behind it
        # (app/static/ha_fetch.js, app/templates/workspace_data.html). The disabled stub that
        # used to render this key is gone.
        "data_source_csv",
        # Shipped as the Energy flows chart tab (three stacked-bar/average-day plots in panel ③).
        # See changelog/20260806-energy-flows-chart-tab.md.
        "chart_energy_flows",
        # Shipped as the SoC + price chart tab, whose first chart is a day × time-of-day heatmap
        # of run C's state of charge. See changelog/20260806-soc-price-chart-tab.md. The tab's
        # SECOND chart (the price half its name promises) is not built, but it is a placeholder
        # INSIDE a working tab rather than a pending control: there is no button to click and no
        # dialog to open, so it needs no key here. A key would make the retired/pending split
        # describe charts instead of controls, which is not what it tracks.
        "chart_soc_price",
    }
)

# Human-readable control names, one per key, active and retired alike. These name the control
# the way the UI does — the wording matches the `data-pending-name` on each trigger — so that
# someone reading the issue on GitHub recognises what was clicked.
#
# Deliberately NOT translated. The title crosses into a GitHub issue read by the maintainer
# alongside issues from every other locale, so it is stable English regardless of the UI
# language. The dialog around the link is translated; this string is not.
FEATURE_TITLES: dict[str, str] = {
    "export_csv": "Export CSV",
    "chart_soc_price": "SoC + price chart",
    "pricing_contract_fixed": "Fixed price contract",
    "pricing_contract_variable": "Variable price contract",
    "pricing_tlk_tiered": "Terugleverkosten tiered by annual volume",
    # Retired, kept readable for issues already filed (see the ongoing-work rule above).
    "discharge_allow_export": "Allow export to grid",
    "simulate_cost": "Simulate cost savings",
    "data_source_csv": "Upload CSV",
    "chart_energy_flows": "Energy flows chart",
}


def _check_titles_cover_keys() -> None:
    """Fail at import if a key has no title, rather than at click time with a bare key.

    The two collections are edited by hand and drift silently otherwise: a key added without a
    title would compose an issue naming the feature only by its internal slug.
    """
    missing = (FEATURE_KEYS | RETIRED_KEYS) - FEATURE_TITLES.keys()
    if missing:
        raise AssertionError(f"feature keys without a title in FEATURE_TITLES: {sorted(missing)}")


_check_titles_cover_keys()


def is_known(feature_key: str) -> bool:
    """True if the key names a currently-pending control."""
    return feature_key in FEATURE_KEYS


def title_for(feature_key: str) -> str:
    """The human-readable control name for a key, falling back to the key itself.

    The fallback never fires for a key in the vocabulary (`_check_titles_cover_keys` sees to
    that at import); it keeps a caller passing an unknown key from raising.
    """
    return FEATURE_TITLES.get(feature_key, feature_key)


def issue_url(feature_key: str) -> str:
    """The pre-filled GitHub "new issue" URL for a pending control.

    Fills the issue form's title and its `feature` field; the "why would you use it" field is
    left empty, since that answer is the reason the issue is worth filing at all. The key is
    carried alongside the title so an issue can be traced back to the exact control.
    """
    title = title_for(feature_key)
    query = urlencode(
        {
            "template": _ISSUE_TEMPLATE,
            "title": f"Feature request: {title}",
            "feature": f"{title} ({feature_key})",
        }
    )
    return f"https://github.com/{GITHUB_REPO}/issues/new?{query}"
