"""The uploaded-wide-CSV data source — a backend_load source per slot binding (§5.1, §4.2a).

The adapter that joins the two halves built before it: `app/uploads.py` stores an uploaded wide
file per workspace, `app/domain/csv_wide.py` interprets one purely, and this module is what the
slot-first source picker (specs §2.2) offers in a slot's drawer and what the backend calls when
that slot is loaded.

## Why this is `backend_load` and not a third kind

The bytes originate in the browser, which is the shape of a `browser_fetch` source — but they
arrive in a *separate, earlier* upload step (`POST /w/{id}/data/uploads`), and by the time a load
happens the file is ordinary server-side data under `<data_dir>/<workspace_id>/uploads/`. Nothing
about the load needs the browser: no credential is held there, no request is made from there, and
the load can run with no page open. That is exactly what the kind means (see `base.py`'s two
families), so CSV is `backend_load` and `SourceKind` gains no third member. The practical payoff is
that `ha_fetch.js` already stages `backend_load` slots by descriptor kind, so the reify path needs
no new JS branch to carry a CSV slot.

## Energy slots only (D-PRICE), minus `power_grid`

`available_for` gates on `SlotSpec.kind == "energy"`, so `price_spot` is not offered CSV (§4.2a:
units and kind are not in the file, and the two units the drawer offers are kWh and Wh — there is
no price unit on this path). Reading the slot's declared kind rather than matching the name
`price_spot` states the actual condition.

**But `SlotSpec.kind` is a lossy encoding of §4.1's Kind column, and `power_grid` is where it
loses something that matters here.** §4.1 gives that slot kind **power** — "Signed W, import
positive" — while `SeriesKind` is only `"energy" | "price"`, so `series_vocab.py` records it as
`"energy"` with a `# signed W; §4.1 power slot` comment. The kind gate alone therefore offered it,
and that is wrong in a way nothing downstream would catch: `column_frame` produces a frame whose
`values` are kWh-in-the-interval by definition, `UNIT_FACTORS` has no watt member, and a column of
`1500 / -800` would be stored as a kWh energy series with the numbers unchanged — off by whatever
the interval length is, with a plausible-looking result.

Its one specified consumer confirms which reading is intended: §6.17's `power_energy_consistency`
computes `power_mean_w / 1000 * dt_h` and compares that against an energy series, so the slot holds
a **mean power in watts**, not a per-interval amount. (§6.17 is not implemented yet, so nothing
reads the slot today — the exclusion is about not persisting a wrongly-scaled series in the
meantime, not about an existing consumer breaking.)

So `power_grid` is excluded by name, in `_EXCLUDED_SLOTS`, and the exclusion is the narrower claim
of the two: the kind gate says what CSV *can* express and this says which nominally-energy slot it
cannot. Supporting the slot properly means a watt unit on this path — a `W → kWh` factor needs the
interval length, which is `resolution_s` and is `None` for an irregular file — plus a drawer radio
for it. That is a real feature, not an oversight, and it is not in this increment.

An earlier version of this comment celebrated "a future energy slot is offered CSV automatically".
That rationale is what produced the `power_grid` defect, so it is withdrawn: a new slot needs a
deliberate answer about whether this format can express it, and the two constants below are where
that answer goes.

## The binding, and why `load` needs more than `(slot, window)`

Every other source can answer "load this slot over this window" from the slot alone: HA has one
statistic per slot, and the price sources have one series. A CSV upload has *many* columns and one
workspace has many uploads, so the load needs the per-slot binding `(upload_id, column, unit)` —
which is per-slot **configuration** (§5.1), not descriptor metadata. It arrives as **keyword-only
extras** on `load`, exactly as `EnergyChartsSource.load` takes its injected `opener`/`now`; the
`DataSource` protocol signature is deliberately NOT widened, since a protocol is the set of calls
every implementation must answer and only this one needs a binding.

**Both backend load paths thread it as of step 5 of the CSV-import brief.** `app/main.py`'s
`_load_backend_frame` (the ingest-WS reify path) and the `POST /w/{id}/data/slot/{slot}/load`
endpoint pass `workspace_id=ws.id` and `binding=` — and pass them ONLY to this source, because the
`DataSource` protocol is narrow and `EnergyChartsSource.load`'s extras are different ones
(`_CSV_SOURCE_KEY` there carries the argument).

**Where the binding comes from is the part with teeth.** It is not server state: decision D-BIND
files it under `localStorage ha.slots.<workspace>` beside the HA statistic id, as a pre-fetch
customization (`app/static/ha_fetch.js`'s two-carriers comment), and it reaches the server only on
the WS `backend_load` message. So `binding.upload_id` is **client-supplied**, and the
`uploads.get(workspace_id, binding.upload_id)` call in `load_with_warnings` is a security boundary
rather than a sanity check: it is workspace-scoped, so an id belonging to another workspace resolves
to None exactly as a nonexistent one does, and this module raises instead of reading it.

That same call is also where a **malformed** id is turned into a `CsvBindingError`.
`uploads._check_upload_id` — the traversal guard, unchanged and still admitting only 32 lowercase
hex — signals a bad id with a plain `ValueError`, and both callers classify by exception type, so
without the translation a `../../etc/passwd` id read as a load failure (502 on the endpoint) instead
of as the bad client input it is. Translating it here rather than at either caller keeps "a
`ValueError` out of the uploads store means the binding was malformed" in the one place that
interprets bindings.

**One consequence of `ha_fetch.js` staging `backend_load` slots by descriptor kind, still worth
stating.** A user who merely *selects* the CSV radio without completing the file/column choice
stages a bindingless `backend_load` slot, whose load raises here, which `_load_backend_frame` wraps
into an `IngestError`, which fails the **whole all-or-nothing fetch — including the HA slots that
were fine**. One unconfigured slot takes down the entire run.

That is still not reachable as shipped, and by the same guard as before: `renderSourceList` in
`app/static/ha_fetch.js` filters `csv_upload` out of the live radio list (`PENDING_SOURCE_KEYS`) and
shows the disabled pending stub instead, so the radio cannot be selected until step 6 builds the
file/column/unit controls. Step 5 threading the binding is a **precondition** for lifting that
filter, not the whole of it: step 6 must also keep Confirm disabled until the binding is complete,
or the same bindingless slot arrives from a completed-looking drawer.

## Windowing is done HERE, not in the parser

`csv_wide.column_frame` returns a frame covering the **whole file**, and that is right: the parse
is per file and the window is per load, so one parse can serve any window. It follows that this
module must slice, and that a `load` which forgot to would silently merge a year of readings into
a one-week dataset — a wrong answer with no error anywhere. `slice_to_window` is therefore a
separate, directly-tested pure function rather than three lines inline.

The window is **half-open** `[start, end)`, matching the rest of the pipeline
(`EnergyChartsSource` keeps bridge points on `start <= p.start < end`), so the interval starting
exactly at `end` belongs to the next window and is not double-counted by two adjacent loads.

A window reaching outside the file's coverage yields the **intersection**, which may be empty. It
is not an error, and it is not padded: §7.4 says "clamp to coverage and say so; never pad with
zeros", and a partly-covered window is an ordinary thing for a user to ask for — the file has the
coverage it has. The "say so" half is not this module's to do; the window-overlap check
(§7.3 check 5) runs once against the assembled dataset and sees each frame's actual coverage.

`resolution_s` is **re-inferred on the slice** rather than inherited from the file. The file-level
value is the modal spacing of the whole file, and a window can select a stretch whose spacing
differs (a supplier that changed from hourly to quarter-hourly mid-year) or is too short for a
modal answer at all. `infer_resolution_s` is reused, not reimplemented.

## Warnings

`column_frame` returns `CSV_GAP_CELLS`, `CSV_DST_AMBIGUOUS_HOUR` and `CSV_CUMULATIVE_COLUMN`
warnings, and §7.3's data-quality box wants the first two — the second by day. But
`DataSource.load` returns a frame and nothing
else, so there are two entry points: `load` satisfies the protocol and drops them, and
`load_with_warnings` returns `(frame, warnings)` for the caller that reports them. Both of
`app/main.py`'s backend-load paths call the latter as of step 5, and `_load_backend_frame` returns
`(frame, warnings)` for exactly that reason — a bare-frame return there would have dropped every
CSV warning before the quality box could see it, silently and for every fetch.

The per-sample warnings are **recomputed for the slice**, not passed through: a gap in March is not
a warning about a load of July, and the ambiguous-hour day list must name the days actually inside
the window or the quality box points the user at a date their run does not cover.

`CSV_CUMULATIVE_COLUMN` is the one warning that is passed THROUGH instead, because it is not a
per-sample fact and cannot be recounted: it says the whole column looks like a meter register
rather than per-interval amounts (`csv_wide._looks_cumulative`), which no window makes more or less
true and no quality bit records. It is non-blocking — the load succeeds and the frame is returned
as read — and the drawer's column picker carries the user-facing small print off the persisted
per-column verdict, so this warning is the fetch path's copy of the same fact rather than its only
appearance.

Main items:
    CsvBinding                            the per-slot binding: upload_id, column, unit.
    CsvBindingError                       raised when a CSV load has no usable binding.
    slice_to_window(frame, window)        pure: a frame restricted to [start, end).
    CsvSource                             the DataSource impl for every energy slot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from app import uploads
from app.domain import csv_wide
from app.domain.frames import QUALITY_DTYPE, QualityFlags, SeriesFrame
from app.domain.ingest import infer_resolution_s
from app.domain.series_vocab import SlotSpec
from app.sources.base import SourceDescriptor

# The one slot kind this source fills (D-PRICE, §4.2a). Read off `SlotSpec.kind` rather than
# compared against slot names — see the module comment.
_ENERGY_KIND = "energy"

# Slots that `_ENERGY_KIND` admits but this format cannot express, excluded by name because the
# reason is per-slot rather than per-kind. `power_grid` is §4.1's **power** slot (signed watts),
# recorded as `kind="energy"` only because `SeriesKind` has no third member; a kWh-per-interval
# frame is the wrong representation for it and there is no watt unit on this path. The module
# comment carries the full argument and what supporting it would take.
_EXCLUDED_SLOTS: frozenset[str] = frozenset({"power_grid"})

# Stable descriptor for the drawer. `key` is persisted with the slot's chosen source and must not
# change once shipped (specs §2.2). The label says "Upload CSV" because the user's action is an
# upload; the blurb states the two facts that decide whether they can use it — the shape of the
# file, and that one file can fill several slots, which is what makes the upload worth doing once.
#
# `label` and `blurb` are English source strings and pybabel cannot see them here; they are
# mirrored into `app/sample_data.py`'s `_SOURCE_STRINGS` with `_N(...)` for extraction, and the
# template translates them via `_()`. `tests/test_no_english_leakage.py` fails if that mirror is
# missing, which is the intended reminder.
_DESCRIPTOR = SourceDescriptor(
    key="csv_upload",
    label="Upload CSV",
    kind="backend_load",
    blurb=(
        "A file you upload: one timestamp column plus one column per measurement. One file "
        "can fill several slots — pick the column for this one."
    ),
)


class CsvBindingError(ValueError):
    """A CSV load was asked for without a usable `(upload_id, column, unit)` binding.

    Its own type rather than a bare `ValueError` so a caller can tell "this slot is not configured"
    apart from "the file is malformed" (`csv_wide.CsvFormatError`, also a `ValueError`). The first
    is a configuration gap the user fixes in the drawer; the second is a data problem reported
    against the file.

    **This is a 400, as of step 5 — and it had to be made one.** An earlier docstring claimed "both
    surface as a 4xx"; they did not. `load_slot`'s bare `except Exception` (`app/main.py`) maps every
    load failure to 502, so an unconfigured slot was reported as a bad gateway, with nothing upstream
    of this app to be one. `load_slot` now catches this type **above** that generic branch — ordering
    that matters, since this is a `ValueError` and the generic branch would otherwise swallow it —
    and answers 400: the condition is "you have not chosen a file and column yet", which is the
    client's input.

    On the WS reify path there is only one error shape (an `error` frame), so
    `_load_backend_frame` still turns this into an `IngestError`; what it gains is a message saying
    the slot is not fully configured rather than one blaming the source for a failed load.
    """


@dataclass(frozen=True)
class CsvBinding:
    """What one slot is bound to inside an uploaded file (§5.1: a per-slot parameter).

        upload_id  the app-assigned uuid4 hex naming the stored file. Validated by `uploads`
                   before it becomes a path component, so a binding restored from storage cannot
                   escape the uploads directory.
        column     the column name **as `csv_wide` reports it**, which may be a uniquified form
                   (`"A (2)"`, `"Column 4"`) rather than the raw header cell — see
                   `csv_wide._value_column_names`. Names are display-only to the user and are
                   never interpreted as series names (§4.2a).
        unit       the drawer's radio value, one of `csv_wide.UNIT_FACTORS` (kWh default, or Wh).

    The upload's declared timezone is deliberately NOT part of the binding. Under D-TZ the parse
    applies the zone once, at upload, and `uploads.Upload.tz` is a record of what was already done
    rather than an instruction — re-applying it here would shift an Amsterdam file twice.
    """

    upload_id: str
    column: str
    unit: str = "kWh"


def slice_to_window(
    frame: SeriesFrame, window: tuple[datetime, datetime]
) -> SeriesFrame:
    """`frame` restricted to the half-open window `[start, end)`, resolution re-inferred.

    Pure, and separate from `load` because it is the one piece of this module that can be wrong in
    a way nothing else notices: the parser hands back the whole file (module comment), so an
    unsliced load silently returns data outside the requested window.

    Both bounds are converted to UTC and reduced to whole seconds, matching the frame's
    `datetime64[s]` index — and both are rounded **up** (`math.ceil`), which is the only pair that
    preserves the window's meaning when a bound carries a fraction. Derived rather than guessed: a
    whole-second sample `s` is in `[start, end)` exactly when `s >= start and s < end`, and for
    integer `s` those are equivalent to `s >= ceil(start)` and `s < ceil(end)`.

    Flooring both, which this function originally did, is wrong at each end and in opposite
    directions: `[00:00:00.5, 01:00)` returned the sample at `00:00`, which is *outside* the
    requested window, and `[00:00, 00:00:00.5)` returned nothing, dropping a sample that *is*
    inside. (Flooring the start and ceiling the end — an "outward" rule that sounds right by analogy
    with §7.4's clamping — fixes only the second and keeps the first; the analogy does not hold,
    because clamping is about coverage the file lacks, not about which samples a bound admits.)
    Reachable rather than theoretical: `main._parse_window` uses `datetime.fromisoformat`, which
    accepts `2025-01-01T00:00:00.5+00:00`, though no current caller sends fractional seconds.

    `math.ceil` rather than `int()`, which truncates toward zero and would therefore round a
    pre-1970 bound the wrong way — unreachable for household energy data, but the correct spelling
    costs nothing.

    `np.searchsorted` is used rather than a boolean mask because the index is already ascending
    (`parse_wide_csv` sorts it — a non-ascending index would make this function silently wrong, and
    that ordering is the stated precondition).

    `side="left"` on both bounds is what makes the window half-open, and it also handles the one
    case where this index is **not strictly increasing**: an October Amsterdam export that writes
    the repeated hour twice resolves both rows to one UTC instant under D-DST, and a bound landing
    on that instant then includes both rows or neither — the pair is never split, which would
    otherwise halve that hour's energy silently.

    That case needs a **genuine 25-hour export** to arise, which is narrower than an earlier version
    of this comment claimed. A chronological 24-row hourly October file produces no duplicate at
    all: its single `02:00` local row resolves to `00:00Z` and `01:00Z` is simply absent — a missing
    hour, not a doubled one. Both shapes were checked rather than reasoned about, since the
    difference decides whether the tie-handling here is load-bearing for ordinary files (it is not)
    or only for the 25-row case (it is).

    An empty result is a legitimate answer (a window before or after the file's coverage), so the
    slice is returned as a zero-row frame. `SeriesFrame.__post_init__` accepts equal-length empty
    arrays, and `infer_resolution_s` returns None for fewer than two samples.
    """
    start, end = window
    # Both bounds round UP. See the docstring for the derivation — for integer-second samples,
    # `s >= start` is `s >= ceil(start)` and `s < end` is `s < ceil(end)`.
    start_s = np.datetime64(math.ceil(_as_utc(start).timestamp()), "s")
    end_s = np.datetime64(math.ceil(_as_utc(end).timestamp()), "s")

    # The two sides are what make the window half-open, and they are not interchangeable:
    # `side="left"` on the start includes a sample AT `start`, and `side="left"` on the end
    # excludes a sample AT `end` — including it would double-count that interval across two
    # adjacent windows. Ties matter here rather than being a corner case, because an October
    # Amsterdam file legitimately carries two samples at one instant (D-DST), and both are
    # included or excluded together by the same bound.
    lo = int(np.searchsorted(frame.index, start_s, side="left"))
    hi = int(np.searchsorted(frame.index, end_s, side="left"))
    # There is deliberately NO `hi = max(hi, lo)` clamp here. An earlier version had one, described
    # as defending against `end <= start` — but `searchsorted` is monotonic in its target, so
    # `end < start` already implies `hi <= lo`, and both a negative-width and a zero-width numpy
    # slice yield an empty array. The line could therefore never change an outcome: a review found it
    # survived deletion against every test, and no test could have killed it. An unreachable guard
    # carrying a justification for work it does not do is worse than its absence, so the reasoning
    # lives here instead. `main._parse_window` validates `end > start` upstream in any case; the
    # empty-window behaviour is pinned by test_slice_to_window_with_end_at_or_before_start_is_empty.

    index = frame.index[lo:hi]
    return SeriesFrame(
        name=frame.name,
        kind=frame.kind,
        # Re-inferred on the slice: the file's modal spacing is not necessarily the window's
        # (module comment).
        resolution_s=infer_resolution_s(index),
        index=index,
        values=frame.values[lo:hi],
        quality=frame.quality[lo:hi],
    )


def _as_utc(dt: datetime) -> datetime:
    """A window bound as tz-aware UTC. Naive is read as UTC, aware is converted.

    The same rule as `dataset._as_utc` and `uploads._to_utc`. The protocol documents `window` as
    tz-aware UTC, so the naive branch is a tolerance rather than a supported spelling — but
    treating a naive bound as UTC is the only reading consistent with the rest of the pipeline
    (§4.4), and silently comparing it against an aware datetime would raise instead.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _warnings_for_slice(
    column: str, frame: SeriesFrame, sliced: SeriesFrame
) -> list[dict]:
    """The §7.3 warnings for the *windowed* frame, recounted from its quality bits.

    Recomputed rather than filtered from `column_frame`'s output because the counts and the day
    list must describe the load, not the file: a gap in March is not a warning about a July run,
    and a quality box naming a day outside the window sends the user looking at data the run does
    not cover.

    The quality bitfield is the authority for both — `column_frame` raises `GAP_FILLED` on every
    empty cell and `DST_AMBIGUOUS` on every row the October fold resolution touched, and those bits
    travel with the samples through the slice. So counting bits on the slice cannot drift from what
    the frame actually carries, which re-deriving from the cells could. `frame` is unused for the
    counts and is taken only to keep the signature honest about what was sliced.

    Shape matches `ingest.energy_frame`'s `list[dict]` so the existing warning plumbing carries
    these unchanged; the codes are `csv_wide`'s.
    """
    del frame  # documented above: the slice's own quality bits are the authority.
    out: list[dict] = []

    gap_bit = QUALITY_DTYPE(QualityFlags.GAP_FILLED)
    gaps = int(np.count_nonzero(sliced.quality & gap_bit))
    if gaps:
        out.append({"code": "CSV_GAP_CELLS", "column": column, "count": gaps})

    amb_bit = QUALITY_DTYPE(QualityFlags.DST_AMBIGUOUS)
    amb_mask = (sliced.quality & amb_bit) != 0
    amb = int(np.count_nonzero(amb_mask))
    if amb:
        # `YYYY-MM-DD` strings off the UTC index, which is what §7.3's box needs to "name the
        # affected day". At the October transition the Amsterdam and UTC dates coincide (03:00
        # local is 01:00 UTC), so no local rendering is required — the same reasoning `csv_wide`
        # records where it builds this list.
        days = sorted({str(ts)[:10] for ts in sliced.index[amb_mask]})
        out.append(
            {
                "code": "CSV_DST_AMBIGUOUS_HOUR",
                "column": column,
                "count": amb,
                "days": days,
            }
        )
    return out


class CsvSource:
    """DataSource for an uploaded wide CSV, bound per slot to one column (§4.2a, §5.1)."""

    @property
    def descriptor(self) -> SourceDescriptor:
        return _DESCRIPTOR

    def available_for(self, slot: SlotSpec) -> bool:
        """True for every energy slot except `power_grid`; False for `price_spot` (§4.2a, D-PRICE).

        Two conditions, because they are two different claims. The kind gate says what this format
        can express at all — kWh-per-interval amounts, so not a price. The name exclusion handles
        `power_grid`, which §4.1 declares as signed watts but `SeriesKind` can only record as
        "energy"; see `_EXCLUDED_SLOTS` and the module comment.
        """
        return slot.kind == _ENERGY_KIND and slot.name not in _EXCLUDED_SLOTS

    def load(
        self,
        slot: SlotSpec,
        window: tuple[datetime, datetime],
        *,
        workspace_id: str | None = None,
        binding: CsvBinding | None = None,
        upload: uploads.Upload | None = None,
    ) -> SeriesFrame:
        """Load `slot` from its bound CSV column over `window` = (start, end), tz-aware UTC.

        `workspace_id` and `binding` are **keyword-only extras** beyond the `DataSource` protocol,
        following `EnergyChartsSource.load`'s precedent (module comment). Both are required in
        practice; they default to None only so the signature stays compatible with the protocol,
        and a call missing either raises `CsvBindingError` naming what is needed rather than
        failing obscurely later.

        `upload` is an optional injection: a caller that has already read the row (step 3's route,
        or a test) can pass it and save a query. When omitted the row is fetched here.

        Raises `CsvBindingError` for a missing binding or an upload this workspace does not have,
        `FileNotFoundError` when the row outlived its file, and `csv_wide.CsvFormatError` for a
        column that is unknown, non-numeric, or a cumulative register (D-KIND) — each with a
        message naming what the user can change. Callers translate these into their own error
        shape; `main.py`'s convention is 404 for unknown, 400 for bad input, 502 for load failure.
        """
        frame, _warnings = self.load_with_warnings(
            slot, window, workspace_id=workspace_id, binding=binding, upload=upload
        )
        return frame

    def load_with_warnings(
        self,
        slot: SlotSpec,
        window: tuple[datetime, datetime],
        *,
        workspace_id: str | None = None,
        binding: CsvBinding | None = None,
        upload: uploads.Upload | None = None,
    ) -> tuple[SeriesFrame, list[dict]]:
        """`load`, plus the §7.3 warnings for the windowed frame. The real implementation.

        Split from `load` because `DataSource.load` returns a frame and nothing else, while §7.3's
        data-quality box needs the gap and DST-ambiguity warnings — so the protocol call delegates
        here and drops them, and a caller that reports them calls this directly. That way there is
        one implementation and the protocol stays as narrow as it is for every other source.

        Sequence: resolve the binding → read the stored text (`uploads.read_text`, which validates
        both ids before touching the filesystem) → parse the whole file under the zone the upload
        RECORDS as already applied (D-TZ: `upload.tz` is not re-applied, it is what `parse_wide_csv`
        was given at upload, and passing it again reproduces the same UTC index rather than shifting
        it a second time) → promote the bound column to a frame → slice to the window.
        """
        if binding is None:
            raise CsvBindingError(
                f"slot {slot.name!r} has no CSV binding: an uploaded file, a column and a unit "
                "must be chosen in the source drawer before this slot can be loaded."
            )
        if not workspace_id:
            raise CsvBindingError(
                "loading a CSV slot needs the workspace the file was uploaded to; none was given."
            )
        if binding.unit not in csv_wide.UNIT_FACTORS:
            # Checked here as well as in `column_frame` so a bad unit is reported before the file is
            # read from disk and parsed — the unit comes from the drawer's radio and cannot be fixed
            # by anything the parse would discover.
            raise csv_wide.CsvFormatError(
                "bad_unit",
                f"Unknown unit {binding.unit!r}. Expected one of: "
                f"{', '.join(csv_wide.UNIT_FACTORS)}.",
            )

        if upload is None:
            try:
                upload = uploads.get(workspace_id, binding.upload_id)
            except ValueError as exc:
                # `uploads._check_upload_id` refuses anything that is not 32 lowercase hex — the
                # traversal guard — and signals it with a plain `ValueError`. That guard is right and
                # is deliberately not weakened; what is wrong is letting its exception escape from
                # here, because callers classify by TYPE: `load_slot` maps `CsvBindingError` to 400
                # and everything else to 502, so a `../../etc/passwd` upload_id — the most obviously
                # client-supplied bad input on this path — used to answer "bad gateway", and on the
                # WS path it read as a load failure rather than as an unconfigured slot.
                #
                # Translated HERE rather than at either caller because this is where the binding is
                # interpreted: the two call sites would otherwise each need to know that a
                # `ValueError` out of the uploads store means "the binding was malformed" and not
                # "the store broke". The message stays generic about the id and does not quote it —
                # `app/main.py`'s `delete_upload` records why a rejected id is not echoed back.
                raise CsvBindingError(
                    f"slot {slot.name!r} is bound to an upload id that is not a valid one. "
                    "Choose the file again in the source drawer."
                ) from exc
        if upload is None:
            raise CsvBindingError(
                f"slot {slot.name!r} is bound to uploaded file {binding.upload_id!r}, which this "
                "workspace no longer has. Upload the file again or choose another source."
            )

        # Raises FileNotFoundError if the row outlived its file — deliberately not softened into an
        # empty series: a bound slot whose file has vanished is a real failure the load path should
        # report (`uploads.read_text`).
        text = uploads.read_text(workspace_id, binding.upload_id)

        wide = csv_wide.parse_wide_csv(text, upload.tz)
        frame, file_warnings = csv_wide.column_frame(
            wide, binding.column, slot.name, binding.unit
        )
        # The per-SAMPLE warnings in `file_warnings` (gaps, ambiguous hours) are discarded on
        # purpose: the caller asked about a window, and `_warnings_for_slice` recounts them against
        # it (module comment). `CSV_CUMULATIVE_COLUMN` is the exception, and is carried through
        # rather than recounted, because it is not a per-sample fact at all — it is a claim about
        # the whole column, so there is nothing in the slice's quality bits to recount it from and
        # no window in which it stops being true. Dropping it would mean the one warning that says
        # the numbers may be wrong never reaches a fetch.
        sliced = slice_to_window(frame, window)
        carried = [w for w in file_warnings if w.get("code") == "CSV_CUMULATIVE_COLUMN"]
        return sliced, carried + _warnings_for_slice(binding.column, frame, sliced)
