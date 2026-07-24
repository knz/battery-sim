"""WebSocket ingest protocol: browser-fetched HA rows → persisted SeriesFrames (specs §4.3, §5.1).

The browser fetches statistics from the user's Home Assistant instance directly (browser-fetch
increment) and streams the raw rows to the backend over a WebSocket. This module defines that
protocol and the pure accumulator that turns the streamed messages into SeriesFrames; the
FastAPI endpoint in app/main.py is a thin shell around `IngestSession`.

WebSocket only (NDJSON was considered and dropped): WS is supported by every browser without
the HTTP/2 request-streaming dependency, and it gives per-chunk progress back to the UI.

Protocol — client → server messages (JSON per WS text frame):

    {"type": "header", "source": "home_assistant",
     "window": {"start": "<iso>", "end": "<iso>"}}          # once, first

    {"type": "series", "name": "grid_import_t1", "kind": "energy",
     "unit": "kWh"}                                          # once per mapped series

    {"type": "rows", "name": "grid_import_t1",
     "rows": [[start_ms, sum], ...]}                         # energy: [start_ms, sum]
    {"type": "rows", "name": "price_spot",
     "rows": [[start_ms, mean, min, max], ...]}              # price:  [start_ms, mean, min, max]

    {"type": "done"}                                         # once, last

Server → client messages:

    {"type": "progress", "name": "<series>", "rows": <cumulative>}   # after each rows batch
    {"type": "result", "dataset_id": <int>, "series": <int>,
     "warnings": [...], "grid": {...}}                               # on done, after persist
    {"type": "error", "message": "<why>"}                            # on any protocol/validation error

Rows may be split across many `rows` messages (the browser forwards them per HA fetch chunk,
specs §4.3 ha_chunk_days), so the accumulator buffers per series and only builds frames on
`done`. It never holds more than the buffered rows — no whole-payload materialisation beyond
that, which the fine-window cap (~10 trailing days, specs §4.3) keeps bounded.

Main items:
    IngestError                    protocol/validation failure carrying a user-facing message.
    IngestSession                  stateful accumulator: on_header / on_series / on_rows / finish.
    build_frames(buffers, ...)     pure: buffered rows → (frames, warnings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain import ingest
from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SLOT_BY_NAME, is_known_series


class IngestError(Exception):
    """A protocol or validation error. Its message is safe to show the user (specs §3.2 LOAD_FAILED)."""


# The two native resolutions a single HA series arrives at (specs §4.3): the full-window
# hourly copy the run uses, and the trailing 5-minute copy for the resolution-bias diagnostic.
# "hour" is the main copy; anything else is treated as the finer copy.
MAIN_PERIOD = "hour"


@dataclass
class _PeriodRows:
    """Rows for one (series, period) — kept apart so the two resolutions are never differenced
    across each other (the bug that concatenating them causes: a spurious register decrease at
    the hourly→5-minute boundary)."""

    energy_rows: list[ingest.EnergyRow] = field(default_factory=list)
    price_rows: list[ingest.PriceRow] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.energy_rows) + len(self.price_rows)


@dataclass
class _SeriesBuffer:
    """Per-series accumulation state during a streamed ingest, split by period (specs §4.3)."""

    name: str
    kind: str
    unit: str | None
    by_period: dict[str, _PeriodRows] = field(default_factory=dict)

    def period(self, period: str) -> _PeriodRows:
        return self.by_period.setdefault(period, _PeriodRows())

    @property
    def row_count(self) -> int:
        return sum(p.count for p in self.by_period.values())


@dataclass
class IngestSession:
    """Stateful accumulator for one streamed ingest (specs §4.3 browser→backend hand-off).

    The FastAPI WS route drives it: `on_header`, then `on_series`/`on_rows` interleaved, then
    `finish`. Each `on_*` validates its message and raises IngestError on anything malformed,
    which the route turns into an `error` frame and a LOAD_FAILED. `finish` builds and returns
    the frames + warnings; persistence is the route's job (kept out of here so this stays pure
    and unit-testable without a data dir).
    """

    source: str | None = None
    window: tuple[datetime, datetime] | None = None
    buffers: dict[str, _SeriesBuffer] = field(default_factory=dict)
    _header_seen: bool = False

    def on_header(self, msg: dict) -> None:
        if self._header_seen:
            raise IngestError("duplicate header")
        self.source = msg.get("source", "home_assistant")
        window = msg.get("window") or {}
        try:
            start = datetime.fromisoformat(window["start"])
            end = datetime.fromisoformat(window["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestError(f"invalid header window: {exc}") from exc
        if end <= start:
            raise IngestError("header window end must be after start")
        self.window = (start, end)
        self._header_seen = True

    def on_series(self, msg: dict) -> None:
        if not self._header_seen:
            raise IngestError("series declared before header")
        name = msg.get("name")
        if not is_known_series(name):
            raise IngestError(f"unknown series name: {name!r}")
        if name in self.buffers:
            raise IngestError(f"series declared twice: {name!r}")
        slot = SLOT_BY_NAME[name]
        kind = msg.get("kind", slot.kind)
        if kind != slot.kind:
            raise IngestError(
                f"series {name!r} declared kind {kind!r} but the slot is {slot.kind!r}"
            )
        self.buffers[name] = _SeriesBuffer(name=name, kind=slot.kind, unit=msg.get("unit"))

    def on_rows(self, msg: dict) -> int:
        name = msg.get("name")
        buf = self.buffers.get(name)
        if buf is None:
            raise IngestError(f"rows for undeclared series: {name!r}")
        rows = msg.get("rows")
        if not isinstance(rows, list):
            raise IngestError(f"rows for {name!r} is not a list")
        # Each rows batch declares its native period (specs §4.3). Default "hour" keeps older
        # single-resolution callers working. Batches of the same (series, period) accumulate;
        # different periods stay in separate buffers so they are never differenced together.
        period = msg.get("period", MAIN_PERIOD)
        target = buf.period(period)
        try:
            if buf.kind == "energy":
                target.energy_rows.extend(
                    ingest.EnergyRow(start_ms=int(r[0]), sum=_opt_float(r[1])) for r in rows
                )
            else:
                target.price_rows.extend(
                    ingest.PriceRow(
                        start_ms=int(r[0]),
                        mean=_opt_float(r[1]),
                        min=_opt_float(r[2]) if len(r) > 2 else None,
                        max=_opt_float(r[3]) if len(r) > 3 else None,
                    )
                    for r in rows
                )
        except (IndexError, TypeError, ValueError) as exc:
            raise IngestError(f"malformed row in {name!r}: {exc}") from exc
        return buf.row_count

    def finish(self) -> tuple[list[SeriesFrame], list[dict], tuple[datetime, datetime]]:
        if not self._header_seen or self.window is None:
            raise IngestError("done before header")
        if not self.buffers:
            raise IngestError("no series were sent")
        frames, warnings = build_frames(self.buffers)
        return frames, warnings, self.window


def build_frames(
    buffers: dict[str, _SeriesBuffer],
) -> tuple[list[SeriesFrame], list[dict]]:
    """Buffered rows → SeriesFrames + collected warnings (pure; specs §6.1, §4.3).

    Each series may carry two native resolutions (specs §4.3): the full-window hourly copy the
    run uses, and a trailing 5-minute copy. The MAIN frame is built from the coarsest period
    present (hourly in practice) — that is the resolution the simulation grid uses (§6.2). A
    finer period does NOT extend the main frame; differencing across the two would fabricate a
    register decrease at the boundary. Instead the finer copy contributes only its resolution
    and coverage, attached as `fine_resolution_s`/`fine_coverage` for the §4.3/§4.5 reporting
    and the resolution-bias diagnostic (§6.13, a later increment).
    """
    frames: list[SeriesFrame] = []
    warnings: list[dict] = []
    for name, buf in buffers.items():
        periods = buf.by_period
        if not periods:
            continue
        main_period, fine_period = _split_periods(periods)

        main_rows = periods[main_period]
        if buf.kind == "energy":
            frame, warns = ingest.energy_frame(name, main_rows.energy_rows)
            for w in warns:
                w["series"] = name
            warnings.extend(warns)
        else:
            frame = ingest.price_frame(name, main_rows.price_rows)

        if fine_period is not None:
            fine_frame = _period_frame(name, buf.kind, periods[fine_period])
            frame.fine_resolution_s = fine_frame.resolution_s
            frame.fine_coverage = fine_frame.coverage()

        frames.append(frame)
    return frames, warnings


def _split_periods(periods: dict[str, _PeriodRows]) -> tuple[str, str | None]:
    """Pick the main (coarsest) period and the finer one, if any (specs §4.3).

    Prefers the explicit MAIN_PERIOD ("hour") as main when present; otherwise the period with
    the fewest rows over the same span is coarser and becomes main. The finer period is the one
    that is not main. With a single period there is no fine copy.
    """
    keys = list(periods.keys())
    if len(keys) == 1:
        return keys[0], None
    if MAIN_PERIOD in periods:
        others = [k for k in keys if k != MAIN_PERIOD]
        # If several finer copies were sent, keep the densest (most rows) as the fine copy.
        fine = max(others, key=lambda k: periods[k].count)
        return MAIN_PERIOD, fine
    # No explicit hour: the sparser period is the coarser (main).
    ordered = sorted(keys, key=lambda k: periods[k].count)
    return ordered[0], ordered[-1]


def _period_frame(name: str, kind: str, rows: _PeriodRows) -> SeriesFrame:
    if kind == "energy":
        frame, _ = ingest.energy_frame(name, rows.energy_rows)
        return frame
    return ingest.price_frame(name, rows.price_rows)


def _opt_float(v) -> float | None:
    """Parse a possibly-null numeric cell to float, or None for null/NaN (a gap, specs §4.2)."""
    if v is None:
        return None
    f = float(v)
    if f != f:  # NaN
        return None
    return f
