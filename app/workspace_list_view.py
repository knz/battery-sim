"""The view-model for the workspace list screen (docs/specs/20-workspaces-ux.md §2′.2).

`app/workspaces.list_summaries(owner_id)` already returns exactly the facts a card states — three config
badges and five dataset facts — and deliberately reads them from SQLite metadata alone, without
loading a single `.npz`. What it does NOT do is decide how any of them is written, and that is
this module's whole job: turn a `WorkspaceSummary` into a dict `_workspace_card.html` can render
without doing arithmetic, date maths or locale reasoning in Jinja.

The split matters for one specific reason. §2′.2's card carries figures ("9,983 intervals") and a
timestamp, and both are locale-dependent: Dutch groups thousands with a point where English uses a
comma, and neither can be formatted while the view-model is built, because the request's locale is
not known there (`app/i18n.py`'s A6 note). So every figure leaves here as an `i18n.num()` pair and
is formatted by `templates/_msg.html` at render time, exactly as panel ① and panel ③ already do.
Nothing in this module formats a number.

## What is decided here, and why

**The connection badge is built from two fields, not typed** (§2′.2): `phases × fuse_a`, written
`1×25 A`. `fuse_a` is a float on `GridConfig` because a fuse can be 1.5 A in principle, but every
Dutch domestic fuse in §2′.4's preset list is a whole number, so a value that is integral is
written without its ".0" — "1×25 A", not "1×25.0 A". A non-integral value keeps its decimals
rather than being rounded into a different fuse. The badge is a msgid with two holes, so a
translator can reorder or respace it; it is not concatenated from fragments.

**The last-saved badge is Europe/Amsterdam**, per §2′.2, while everything stored and computed is
UTC (docs/specs/README.md). This module is the boundary where that conversion happens for the list, and
it is the only place the list screen knows about a timezone. The written form is
`YYYY-MM-DD HH:MM` — ISO date plus a 24-hour clock, the same reasoning `data_view._fmt_date`
gives for staying ISO in both locales: 07-24 and 24-07 are the same day written two ways and a
reader cannot tell which convention a page follows, whereas ISO is unambiguous and is what a Dutch
reader sees on a meter readout.

**The coverage line is one string with an arrow**, `start → end`, matching the wireframe and
`summary_view`'s existing `coverage` shape. Minute precision, because a coverage window that
starts at 09:00 is a fact the wireframe states.

**The three role facts are an ordered list, not three fields.** The card draws them as a grid and
the order is fixed by §2′.2 (grid consumption, grid production, PV production); making it a list
keeps that order in one place instead of in the template's markup. Each entry carries a `state` of
`loaded` / `not_loaded` / `not_applicable`, and the template maps a state to a glyph and a msgid.
`not_applicable` exists only for PV and only when `has_pv` is off — §2′.2 is explicit that a
deliberate configuration must not be reported as a missing input.

**No-data cards carry nothing else.** When `DataFacts.loaded` is false, `data.loaded` is false and
every other data field is absent. §2′.2 collapses the box to a one-line invitation and REMOVES
`[ Results ]` and `[ Delete data ]` — the Inapplicable rule from §2.1, absent and never greyed —
so the template branches on that one flag and the view-model does not offer values that would only
tempt it to render them anyway.

Main items:
    CONNECTION_BADGE   the msgid for the `%(phases)s×%(fuse)s A` badge.
    card(summary)      one `WorkspaceSummary` → the dict `_workspace_card.html` renders.
    cards(summaries)   the whole list, in the order `list_summaries` returned it.
"""

from __future__ import annotations

from datetime import datetime

from app.data_view import _res_msg
from app.i18n import DISPLAY_TZ, msg as _msg, msg_n as _msg_n, num
from app.sample_data import _N
from app.workspaces import WorkspaceSummary

# DISPLAY_TZ (Europe/Amsterdam) is the app-wide display convention and is re-exported here because
# this module's name has been the reference for it (§2′.2, docs/specs/README.md). It moved to
# `app.i18n` when `results_view` needed the same zone for the average-day profile: the two views do
# not import each other, and `i18n` is the leaf both already depend on for display conventions.
__all__ = ["DISPLAY_TZ", "CONNECTION_BADGE", "card", "cards"]

CONNECTION_BADGE = _N("%(phases)s×%(fuse)s A")
"""The connection badge (§2′.2): `1×25 A`, `3×63 A`.

A msgid with two holes rather than an f-string or a concatenation, for the reason `app/i18n.msg`
gives: a runtime-assembled string has no msgid `pybabel extract` can see. `_N` because a
module-level assignment is not a call the extractor recognises.

The "×" is U+00D7, not the letter x — it is the multiplication sign the wireframe uses and the one
a Dutch meter cabinet label uses.
"""

# The three role facts, in §2′.2's fixed order. Each is (key on DataFacts, label msgid).
_ROLES: tuple[tuple[str, str], ...] = (
    ("grid_consumption", _N("Grid consumption")),
    ("grid_production", _N("Grid production")),
    ("pv_production", _N("Solar production")),
)


def _fmt_fuse(fuse_a: float) -> str:
    """A fuse rating for the badge: "25" for 25.0, "1.5" for 1.5.

    `GridConfig.fuse_a` is a float because the field is a rating in amps and nothing forbids a
    fractional one, but every preset in §2′.4's list is whole. Writing "1×25.0 A" would put a
    decimal on a badge whose whole purpose is to be read at a glance, so an integral value loses
    its ".0" and anything else keeps its own precision rather than being rounded into a rating the
    household does not have.

    Deliberately NOT an `i18n.num()` pair. A fuse rating is an identifier of a connection type,
    not a quantity to be grouped and localised: "1×25 A" is written the same way in both languages
    and a 1600 A rating must not become "1.600 A" on a Dutch page, which is a different-looking
    number.
    """
    return str(int(fuse_a)) if float(fuse_a).is_integer() else str(fuse_a)


def _fmt_instant(dt: datetime) -> str:
    """A stored UTC instant as `YYYY-MM-DD HH:MM` in Europe/Amsterdam (§2′.2).

    ISO date, 24-hour clock, no seconds and no timezone suffix. Seconds are noise on a "last
    saved" badge, and the suffix would be the same on every card on the screen.

    A naive datetime is assumed UTC, matching `workspaces._parse` — which reads a stored timestamp
    written without an offset as UTC, for the same reason the rest of the pipeline does (§4.4).
    Doing the assumption here as well means this function is safe against a summary built from any
    other source, and costs one branch.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def _data(summary: WorkspaceSummary) -> dict:
    """The info-box half of a card (§2′.2), or `{"loaded": False}` when there is no dataset.

    The no-data case is the whole reason this returns a flag rather than a fully-populated dict
    with empty strings in it: §2′.2 collapses the box to a one-line invitation and removes the two
    buttons that need a dataset, so a template that has nothing to render is better served by
    having nothing to render than by being handed placeholders.
    """
    facts = summary.data
    if not facts.loaded:
        return {"loaded": False}

    roles = []
    for key, label in _ROLES:
        if key == "pv_production" and not facts.pv_applicable:
            # §2′.2: "not applicable", never "not loaded". The household said it has no PV, and a
            # deliberate configuration is not a missing input.
            state = "not_applicable"
        else:
            state = "loaded" if getattr(facts, key) else "not_loaded"
        roles.append({"label": label, "state": state})

    coverage = None
    if facts.window is not None:
        coverage = f"{_fmt_instant(facts.window[0])} → {_fmt_instant(facts.window[1])}"

    return {
        "loaded": True,
        "roles": roles,
        "coverage": coverage,
        # The interval count and the grid resolution as ONE counted sentence, so a translator can
        # place the resolution where the language wants it and so "1 interval" is not written "1
        # intervals". The count is an `i18n.num()` pair (formatted at render, A6) and the
        # resolution label is a NESTED message (`data_view._res_msg`), because interpolation runs
        # after translation and a bare English label substituted into a Dutch sentence stays
        # English. Both mechanisms already exist for panel ①'s box; this reuses them rather than
        # inventing a third.
        #
        # `intervals` is None when no energy series covers the window — there is no grid, so the
        # line is omitted rather than guessed at. Both numbers are the run's real size, stored at
        # save time by `normalize.grid_facts`; note the count is measured over the effective
        # window and is NOT this card's coverage span divided by the resolution (followup I2).
        "size": (
            None
            if facts.intervals is None
            else _msg_n(
                "%(count)s interval · %(res)s",
                "%(count)s intervals · %(res)s",
                facts.intervals,
                count=num(facts.intervals, "count"),
                res=_res_msg(facts.resolution_s),
            )
        ),
    }


def card(summary: WorkspaceSummary) -> dict:
    """One `WorkspaceSummary` → the dict `_workspace_card.html` renders (§2′.2).

    Three badges from the CONFIG and an info box from the DATASET, plus the two flags that decide
    which actions the card draws. §2′.2's action table is:

        [ Results ]             data is loaded     →  `has_data`
        [ Configure data ]      always             →  unconditional in the template
        [ Configure analysis ] always              →  unconditional in the template
        [ Delete data ]         data is loaded     →  `has_data`
        [ Delete analysis ]     always             →  unconditional in the template

    so `has_data` is the one condition, stated once here rather than as `card.data.loaded` written
    twice in the markup.

    The contract badge is the enum VALUE verbatim (§2.3: label and enum do not diverge) and is
    carried at full strength whether or not cost simulation is on — §2′.2 is explicit, and
    `WorkspaceSummary` deliberately does not carry `simulate_cost`, so conditioning it here is not
    even expressible.
    """
    return {
        "id": summary.id,
        "title": summary.title,
        "connection": _msg(
            CONNECTION_BADGE, phases=summary.phases, fuse=_fmt_fuse(summary.fuse_a)
        ),
        # Not translated, and not wrapped in a message: it is an enum value the app also writes
        # into the stored document, so a translated badge would name something the configuration
        # screen does not.
        "contract": summary.contract,
        "updated_at": _fmt_instant(summary.updated_at),
        "data": _data(summary),
        "has_data": summary.data.loaded,
    }


def cards(summaries: list[WorkspaceSummary]) -> list[dict]:
    """The whole list, in the order `workspaces.list_summaries(owner_id)` returned it.

    That order is most-recently-updated first (§2′.2), decided by SQL rather than here — a view
    that re-sorted would be a second definition of the ordering rule and could drift from the
    one the query states.
    """
    return [card(s) for s in summaries]
