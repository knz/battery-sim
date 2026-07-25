"""The closed vocabulary of feature keys for pending controls (specs/02-ux-wireframes.md §2.1).

A control that is specified but not yet built renders "pending": disabled, with a `[?]`
affordance that opens the shared dialog and offers a thumbs-up. Each such control carries a
short, stable key naming it in the `feature_interest` counter table and in the outbound POST
body. The keys are a **closed vocabulary**: allocated when a control is first marked pending,
never reused for anything else, and kept after the feature ships (the counter row outlives the
key so historical interest is not lost).

Ongoing-work rule — read before adding or removing an entry:
  * When you mark a NEW control pending, add its key here (and only here) and reference it from
    the template via `feature_key="<key>"`. Choose `<box>_<control>` shaped names.
  * When you BUILD a feature, remove the control's pending markup from the template. Leave this
    key in place (retired, not deleted) so the counter row keeps its meaning. Move it under the
    "Retired" list below rather than removing the line.
  * Never rename a key or repoint it at a different control — that would make every historical
    counter row a lie (same discipline as the series names in specs/05-data-formats.md).

The route POST /feature-interest/{feature_key} rejects any key not in FEATURE_KEYS.
"""

# Active pending controls. Keep in sync with the `feature_key="..."` attributes in the
# templates. See changelog/20260723-pending-affordance-impl.md for the allocation record.
FEATURE_KEYS: frozenset[str] = frozenset(
    {
        "export_csv",            # Export CSV button (panel ③ results)
        "simulate_cost",         # Also simulate cost savings toggle (panel ②)
        "data_source_csv",       # Upload CSV source radio (panel ①)
        "chart_soc_price",       # SoC + price chart tab (panel ③ charts)
        "chart_energy_flows",    # Energy flows chart tab (panel ③ charts)
    }
)

# Retired keys — features that have shipped. Their counter rows are kept; the keys are never
# reused.
RETIRED_KEYS: frozenset[str] = frozenset(
    {
        # Shipped in Phase 6 as a real checkbox (_panel_params.html, `policy.allow_grid_export`),
        # so it is no longer pending. Retired rather than deleted, per the rule above.
        "discharge_allow_export",
    }
)


def is_known(feature_key: str) -> bool:
    """True if the key names a currently-pending control (accepted by the interest route)."""
    return feature_key in FEATURE_KEYS
