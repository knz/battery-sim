"""Panel ① view-model from a persisted dataset (specs/02-ux-wireframes.md §2.2).

Bridges the persisted `LoadedDataset` (app/dataset.py) to the dict the `_panel_data.html`
template consumes. Before this increment the template rendered a static sample
(app/sample_data.py); once a real Home Assistant dataset has been fetched and persisted, this
module builds the panel from it instead — real coverage, the chosen simulation grid, per-series
native resolutions and reconciliation (§6.2), and the gap/reset counts recovered from the
per-interval quality flags (§4.4).

What it does NOT populate yet — because those computations are later increments — is left out
rather than faked: the negative-load reconstruction warning (§6.3), the tariff-register
identification (§6.4, cost-sim), and the resolution-bias diagnostic (§6.13). The template
renders these blocks conditionally, so a real dataset simply omits the ones not yet computed.

The role labels mirror the sample's, keyed by series name, so the same translation msgids apply.

**Every sentence and label this module emits is a `(msgid, params)` pair, not a formatted string**
(`app/i18n.msg` / `.msg_n`, aliased `_msg` / `_msg_n`; rendered by `templates/_msg.html`). They
used to be f-strings, which made each msgid a runtime value `pybabel extract` could never see, so
the whole data-quality box rendered in English on a Dutch page. Splitting the constant text from
the runtime figures makes the msgid a compile-time literal again. Counted messages ("3 intervals")
use `_msg_n`, so a count of one does not read "1 intervals". The resolution label `_fmt_res`
returns is itself a msgid and travels as a NESTED message, since interpolation happens after
translation and would otherwise substitute an untranslated English word into a Dutch sentence.

**And every FIGURE is an `i18n.num()` pair, not a formatted number** (A6). The counts in this box
run to thousands, and Dutch groups them with a point where English uses a comma ("8.760" against
"8,760"), so a count formatted here — before the request's locale is known — is formatted in the
wrong language half the time. The number and the name of a convention travel as a param and
`templates/_msg.html` formats them at render time. Dates do NOT follow: `_fmt_date` stays ISO in
both locales, deliberately, for the reasons its own docstring gives.

Each mapping row now also carries per-slot source provenance (specs §2.2 slot-first sources):
`source` (the descriptor key of the source that produced the series, or None) and `sources` (the
sources the drawer may offer for that slot, as small {key,label,kind,blurb} dicts). Phase C's
source-picker drawer renders these; the current template ignores the extra keys, so the shape
stays a superset and nothing breaks between phases.

Main items:
    ROLE_LABEL                 series name → human role label (translation msgid).
    _fmt_res(seconds)          seconds → a resolution label; the label is a msgid.
    _res_msg(seconds)          the same label as a nested `_msg` pair, for embedding in a sentence.
    panel_data_from(dataset)   the panel-① dict; shape-compatible with sample_data._panel_data.
"""

from __future__ import annotations

import numpy as np

from app.dataset import LoadedDataset
from app.domain import normalize
from app.domain.frames import QualityFlags, SeriesFrame
from app.i18n import msg as _msg, msg_n as _msg_n, num
from app.sample_data import _N
from app.sources import registry

# Human role labels, keyed by internal series name (specs §4.1). These are the same English
# msgids the static sample uses, so the existing catalog covers them.
ROLE_LABEL: dict[str, str] = {
    "grid_import_t1": "Grid import T1",
    "grid_import_t2": "Grid import T2",
    "grid_export_t1": "Grid export T1",
    "grid_export_t2": "Grid export T2",
    "solar_production": "Solar production",
    "battery_charge": "Battery charge",
    "battery_discharge": "Battery discharge",
    "price_spot": "Spot price",
    "power_grid": "Grid power",
    "house_load": "House load",
}


# The fixed resolution labels, as msgids. `_N` is a no-op tagger whose only job is to be an
# extraction keyword: a dict literal is not a call Babel recognises, so without it these five
# words never reach the catalog and every sentence that embeds one leaks an English word into a
# Dutch page. They are words, not figures, which is why they are translated rather than passed
# through as data.
_RES_LABELS: dict[int, str] = {
    300: _N("5-min"),
    900: _N("15-min"),
    1800: _N("30-min"),
    3600: _N("hourly"),
    86400: _N("daily"),
}
_RES_IRREGULAR = _N("irregular")
# The fallback for a resolution with no named label. A msgid with a hole rather than an f-string,
# so "%(n)ss" can be reordered or spaced differently by a translator. `_N` for the same reason as
# above: a module-level assignment is not a call `pybabel extract` recognises, and this msgid is
# referenced from two places rather than written literally inside a `_msg(...)` call.
_RES_SECONDS = _N("%(n)ss")


def _fmt_res(seconds: int | None) -> str:
    """Seconds → a human resolution label in ENGLISH ("hourly", "15-min", "5-min", …).

    Kept returning a plain string because `results_view` embeds it in the one deliberately
    untranslated field it still emits (`results["period"]`, the unsplit fallback line). Everything
    that reaches a reader goes through `_res_msg` instead, which wraps the same label as a message
    so the template translates it. The two share `_RES_LABELS`, so the English wording cannot
    drift between them.
    """
    if seconds is None:
        return _RES_IRREGULAR
    label = _RES_LABELS.get(seconds)
    return label if label is not None else _RES_SECONDS % {"n": seconds}


def _res_msg(seconds: int | None) -> dict:
    """The resolution label as a `_msg` pair, for embedding in a larger sentence.

    Sentences interpolate this as a NESTED message (`templates/_msg.html`): a bare string param is
    substituted after translation and so would stay English, whereas a nested message is
    translated on its own first. The unnamed-resolution case carries its second count as a
    parameter rather than being formatted into the msgid.
    """
    if seconds is None:
        return _msg(_RES_IRREGULAR)
    label = _RES_LABELS.get(seconds)
    if label is not None:
        return _msg(label)
    return _msg(_RES_SECONDS, n=num(seconds, "count"))


def _fmt_date(dt) -> str:
    """A datetime as an ISO date ("2026-07-24"), the same form in every locale — deliberately.

    Dates were in A6's scope and were considered. Babel's short date for `nl` is "24-07-2026" and
    for `en` "7/24/26", and the pair is the argument against using them: 07/24 and 24-07 are the
    same day written two ways, so a reader who is unsure which convention a page follows cannot
    tell them apart, and the coverage line's whole job is to say unambiguously which days the run
    spans. ISO is unambiguous, is what a Dutch reader sees on every meter readout, and is already
    what `summary_view` emits in `coverage` — where `_data_glance.html` SPLITS the string on " → "
    to show a start date on its own, so the shape is a contract rather than free presentation.

    The one date-adjacent thing that IS localised is the monthly chart's month names, which are
    words rather than digits and read plainly wrong in the other language (see `i18n.month_abbr`).
    """
    return dt.date().isoformat()


def _count_flag(frames: list[SeriesFrame], flag: QualityFlags) -> int:
    total = 0
    for f in frames:
        if len(f.quality):
            total += int((np.asarray(f.quality) & int(flag)).astype(bool).sum())
    return total


def panel_data_from(dataset: LoadedDataset) -> dict:
    """Build the panel-① view-model from a persisted dataset (specs §2.2).

    Shape-compatible with sample_data._panel_data() so the template renders either — including
    the message shape: for every field the template RENDERS, the sample emits the same
    `(msgid, params)` pair shape this does, and reuses THESE msgids wherever the two word a field
    identically (`tests/test_data_summary.py` asserts that, so the pair cannot silently become two
    catalog entries). The four the sample words differently (gaps, registers, price_warning,
    load_warning — its wireframe copy predates what the real pipeline computes) carry their own
    msgids, and `registers` is a plain string on the sample side rather than a pair, which the
    `msg()` macro's bare-string branch handles.

    One field is deliberately outside that guarantee: `mapping[*].entity` is a pair here and a
    plain id string in the sample. No template reads it (the picker renders `stat_id`), so the
    divergence is inert — but it is why this says "every field the template renders" rather than
    "every field".

    Fields the real pipeline does not yet compute are omitted; the template guards on presence.
    """
    frames = dataset.frames
    report = normalize.grid_report(frames, dataset.window)
    grid_s = report["grid_s"]
    # Use the effective window (data coverage overlap) for coverage/day display, not the raw
    # fetch bounds — the two differ by up to an interval and the effective one is what the run
    # spans (specs §6.2).
    from datetime import datetime as _dt

    win_start = _dt.fromisoformat(report["window"]["start"])
    win_end = _dt.fromisoformat(report["window"]["end"])
    window = (win_start, win_end)

    # Mapping table: the FULL slot roster (specs §2.2 slot-first). One row per SERIES_SLOTS
    # entry whether or not a series is present, so the user can pick a source for a slot that has
    # no data yet. A present slot carries its fetched entity string and persisted source; an
    # absent slot carries entity=None and source=None. The template gates the pv_only /
    # battery_only rows against the setup answers.
    from app.domain.series_vocab import SERIES_SLOTS

    present = {f.name: f for f in frames}
    series_sources = getattr(dataset, "series_sources", {}) or {}
    mapping = []
    for slot in SERIES_SLOTS:
        f = present.get(slot.name)
        mapping.append(
            {
                "name": slot.name,
                "role": ROLE_LABEL.get(slot.name, slot.name),
                "req": slot.requirement,
                # Optional per-series explanation for the picker's ⓘ affordance (specs §4.1);
                # None for slots that carry no blurb, so the template renders no icon.
                "info": slot.info,
                # Present: the "(res, N intervals)" coverage message. Absent: None (no data yet).
                # Counted, so a one-interval slot does not read "1 intervals"; the resolution is a
                # nested message so it is translated rather than substituted as an English word.
                "entity": (
                    _msg_n(
                        "(%(res)s, %(n)s interval)",
                        "(%(res)s, %(n)s intervals)",
                        len(f.values),
                        res=_res_msg(f.resolution_s),
                        n=num(len(f.values), "count"),
                    )
                    if f is not None
                    else None
                ),
                "pv_only": slot.pv_only,
                "battery_only": slot.battery_only,
                # Slot-first provenance (specs §2.2): the source that produced this series (its
                # descriptor key, or None when the slot is unfilled), and the sources the drawer
                # may offer for this slot. Phase C's source-picker drawer renders these.
                "source": series_sources.get(slot.name),
                # The HA statistic id this slot was fetched from (specs §2.2), so the source picker
                # renders a fetched HA slot's entity after a reload without any client state. None
                # for a non-HA source, an unfilled slot, or a row written before stat_id was stored.
                "stat_id": (f.stat_id if f is not None else None),
                "sources": [
                    {"key": d.key, "label": d.label, "kind": d.kind, "blurb": d.blurb}
                    for d in registry.sources_for(slot)
                ],
            }
        )

    # Per-series granularity table (§2.2). "recorded" is the native resolution; "uses" is the
    # reconciliation onto the grid, with the lossy (averaged) case marked.
    #
    # Each cell is a message with the resolution label nested inside it, rather than a label with
    # a suffix glued on. ", averaged" is not a suffix in every language — Dutch puts the qualifier
    # elsewhere — so the whole cell has to be one msgid the translator can rearrange.
    grid_msg = _res_msg(grid_s)
    by_name = {f.name: f for f in frames}
    series_rows = []
    for entry in report["series"]:
        recon = entry["reconciliation"]
        if recon == "averaged":
            uses, warn = _msg("%(res)s, averaged", res=grid_msg), True
        elif recon == "held":
            uses, warn = _msg("%(res)s, held", res=grid_msg), False
        elif recon == "undefined":
            uses, warn = _msg("undefined"), False
        else:
            uses, warn = grid_msg, False
        # "Recorded at" shows the native resolution, plus the finer copy over its sub-window when
        # one was fetched (specs §4.3, §2.2 — the two-line granularity cell).
        recorded = [_msg("%(res)s (full)", res=_res_msg(entry["native_resolution_s"]))]
        f = by_name.get(entry["name"])
        if f is not None and f.fine_resolution_s and f.fine_coverage:
            fine_days = (f.fine_coverage[1] - f.fine_coverage[0]).days
            recorded.append(_msg_n(
                "%(res)s (last %(n)s day)",
                "%(res)s (last %(n)s days)",
                fine_days,
                res=_res_msg(f.fine_resolution_s),
                n=num(fine_days, "count"),
            ))
        series_rows.append(
            {
                "name": ROLE_LABEL.get(entry["name"], entry["name"]),
                "recorded": recorded,
                "uses": uses,
                "warn": warn,
            }
        )

    gaps = _count_flag(frames, QualityFlags.GAP_FILLED)
    resets = _count_flag(frames, QualityFlags.RESET_CORRECTED)
    days = (window[1] - window[0]).days

    intervals = report["intervals"] or 0
    quality: dict = {
        # The dates are pure data and stay literal; only the day count carries a word, so it is
        # the part with a msgid. Counted — a one-day window read "(1 days)".
        "coverage": _msg_n(
            "%(dates)s   (%(n)s day)",
            "%(dates)s   (%(n)s days)",
            days,
            dates=f"{_fmt_date(window[0])} → {_fmt_date(window[1])}",
            n=num(days, "count"),
        ),
        "grid": _msg_n(
            "%(res)s  ·  %(n)s interval",
            "%(res)s  ·  %(n)s intervals",
            intervals,
            res=grid_msg,
            n=num(intervals, "count"),
        ),
        "series": series_rows,
        # "N interval(s)" was a written-out plural — legible but ungrammatical, and untranslatable
        # into a language whose plural rule is not "add s". `_msg_n` picks the form from the same
        # count the sentence prints, so the two cannot drift.
        "gaps": (
            _msg_n("%(n)s interval flagged as gaps",
                   "%(n)s intervals flagged as gaps", gaps, n=num(gaps, "count"))
            if gaps else _msg("none detected")
        ),
        # Not counted: the English carries no noun to pluralise. A translator whose language needs
        # one can still say so — the msgid is a whole clause, so it is theirs to rephrase.
        "resets": (
            _msg("%(n)s detected and corrected", n=num(resets, "count")) if resets
            else _msg("none detected")
        ),
        "registers": _register_summary(present),
    }
    if report["price_granularity_lost"]["lost"]:
        native = report["price_granularity_lost"]["native_resolution_s"]
        quality["price_warning"] = _msg(
            "Your prices change every %(native)s but the run is %(res)s, so the "
            "run sees one averaged price per interval and cannot act on within-interval swings.",
            native=_res_msg(native),
            res=grid_msg,
        )

    return {
        # Counted even though the two English forms are identical: "series" is invariant in
        # English but not in Dutch ("1 serie" / "4 series"), and a count of one is reachable.
        "summary": _msg_n(
            "Home Assistant · %(n)s series · simulated %(res)s",
            "Home Assistant · %(n)s series · simulated %(res)s",
            len(frames),
            n=num(len(frames), "count"),
            res=grid_msg,
        ),
        "days": days,
        "source": "Home Assistant",
        # Connection block: after a fetch the browser holds the token; the server only knows a
        # dataset exists. The template's connection card is driven client-side (ha_fetch.js).
        "ha": None,
        "mapping": mapping,
        "quality": quality,
    }


def _register_summary(present: dict[str, SeriesFrame]) -> dict:
    """T1/T2 mapping summary (specs §6.4 availability — the always-shown, contract-free fact).

    Returns a `_msg` pair. The two per-register marks ("not mapped" / "mapped, active" /
    "mapped, flat") are nested messages inside the sentence rather than strings pasted into it, so
    each is translated on its own and the sentence around them stays one reorderable msgid.
    """
    def mark(name: str) -> dict:
        f = present.get(name)
        if f is None:
            return _msg("not mapped")
        active = len(f.values) and float(np.nansum(f.values)) > 0
        return _msg("mapped, active") if active else _msg("mapped, flat")

    return _msg(
        "import T1 %(t1)s · T2 %(t2)s",
        t1=mark("grid_import_t1"),
        t2=mark("grid_import_t2"),
    )
