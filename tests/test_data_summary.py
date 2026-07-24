"""Unit tests for the data summary band's sample view-model (specs/02-ux-wireframes.md §2.3a).

These check the shape app/sample_data._data_summary() produces and that sample_view() carries it,
without launching a browser or seeding a dataset (the smoke test covers empty-state absence). The
band is a spec + UI shell this increment; when the real §6.3/§6.11 battery-free computation lands
these become the contract the computed view-model must also satisfy.
"""

from app.sample_data import _data_summary, sample_view


def test_sample_view_includes_data_summary():
    # sample_view() carries the band unconditionally (main.py drops it in the empty state).
    assert "data_summary" in sample_view()


def test_summary_always_present_groups():
    # Grid and Household are always present (specs §2.3a table): they need no PV, no battery, no
    # price — only the meter registers and the load reconstruction.
    s = _data_summary()
    assert set(s["grid"]) == {"imported", "exported"}
    assert set(s["household"]) >= {"consumption", "self_sufficiency", "net_battery"}


def test_summary_existing_battery_variant():
    # The sample demos the existing-battery variant (confirmed with the user): the battery group
    # is present, and Household is flagged net_of the existing battery so the template labels it.
    s = _data_summary()
    assert s["battery"] is not None
    assert set(s["battery"]) == {"charged", "discharged"}
    assert s["household"]["net_battery"] is True


def test_summary_optional_groups_are_omit_not_zero():
    # The optional groups are separate keys the template guards on, so a no-PV / no-battery /
    # no-price dataset omits them (renders None) rather than showing 0 (specs §2.4). Here the
    # sample has all three, but the keys must exist so the template's `{% if %}` guards resolve.
    s = _data_summary()
    for key in ("solar", "battery", "price"):
        assert key in s
