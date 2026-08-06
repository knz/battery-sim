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
     "rows": [[start_ms, mean], ...]}                        # price:  [start_ms, mean]

    {"type": "backend_load", "name": "price_spot",
     "source": "energy_charts",
     "window": {"start": "<iso>", "end": "<iso>"}}          # 0+ times: a STAGED backend-load slot

    {"type": "backend_load", "name": "grid_import_t1",
     "source": "csv_upload",
     "binding": {"upload_id": "<32 hex>", "column": "Verbruik_T1", "unit": "kWh"},
     "window": {"start": "<iso>", "end": "<iso>"}}          # a CSV slot: same message + a binding

    {"type": "done"}                                         # once, last

A fetch REIFIES the whole staged source config in one shot (specs §3.5, §2.2): the browser
streams the Home Assistant slots as `series`/`rows`, and declares each staged backend_load slot
(e.g. the Energy-Charts spot price) with a `backend_load` message. On `done` the route loads the
backend slots server-side and persists HA + backend series as ONE dataset. Nothing is written
before a fetch — configuring a slot only stages it client-side. This is why a fetch no longer
orphans an earlier backend-loaded price: there is no "earlier" dataset to orphan.

Server → client messages:

    {"type": "progress", "name": "<series>", "rows": <cumulative>}   # after each rows batch
    {"type": "result", "dataset_id": <int>, "series": <int>,
     "warnings": [...], "grid": {...}, "generation": <int>}          # on done, after persist
    {"type": "error", "message": "<why>"}                            # on any protocol/validation error

Rows may be split across many `rows` messages (the browser forwards them per HA fetch chunk,
specs §4.3 ha_chunk_days), so the accumulator buffers per series and only builds frames on
`done`. It never holds more than the buffered rows — no whole-payload materialisation beyond
that, which the fine-window cap (~10 trailing days, specs §4.3) keeps bounded.

The route reifies backend_load slots all-or-nothing: any load failure fails the whole fetch
(LOAD_FAILED) and persists nothing, so a fetch never yields a partial dataset.

The optional `binding` on a `backend_load` message (decision D-BIND of the CSV-import brief). Most
backend sources can answer "load this slot over this window" from the slot alone — Energy-Charts has
one series, so there is nothing more to say. An uploaded wide CSV has MANY columns and a workspace
has many uploads, so a CSV slot needs `(upload_id, column, unit)` as well, and this message is the
ONLY path that binding takes to the server: it is stored browser-side in
`localStorage ha.slots.<workspace>` beside the HA statistic id, exactly as a pre-fetch customization
(`app/static/ha_fetch.js`'s two-carriers comment), and the drawer's Confirm writes nothing
server-side. That keeps the drawer a pure staging surface, which is what makes "an upload survives
Cancel, the binding does not" true without a server write.

The consequence, and it is the reason the validation below is not cosmetic: **the `upload_id` is
client-supplied.** This module checks only its SHAPE — that a binding is an object carrying a
plausible id, a non-empty column name and a known unit — because the session is deliberately pure
and data-dir-free and cannot ask whether that upload exists. Whether the workspace actually HAS that
upload is checked where the load runs (`app/main.py` `_load_backend_frame` → `uploads.get`, which is
workspace-scoped), and a foreign or absent id fails the whole fetch there rather than reading another
workspace's file. Neither check is redundant: the shape check rejects a malformed message before any
I/O and names the field, the existence check is the security boundary.

Main items:
    IngestError                    protocol/validation failure carrying a user-facing message.
    IngestSession                  stateful accumulator: on_header / on_series / on_rows /
                                   on_backend_load / finish.
    BackendLoadRequest             one staged backend-load slot the route must load on `done`,
                                   with the optional per-slot `binding` (D-BIND) a CSV slot needs.
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


@dataclass
class BackendLoadRequest:
    """One staged backend-load slot the route must load server-side on `done` (specs §2.2).

    Carries the slot name, the source descriptor key, and the window to load. The session only
    records these (it stays pure and data-dir-free); the route does the actual `source.load` and
    folds the resulting frame into the same dataset as the HA series.

    `binding` is the per-slot extra a source may need beyond `(slot, window)` — today only the
    uploaded-CSV source, which needs `{upload_id, column, unit}` to know WHICH column of WHICH
    uploaded file this slot is (module comment, D-BIND). It is kept as the raw dict the client sent
    rather than converted to `csv_source.CsvBinding` here, for two reasons: this module has no
    business importing an adapter (it is the protocol layer, and `app/sources/` is I/O), and the
    field is generic by intent — a second source needing per-slot configuration reuses it without
    this module learning what that configuration means. The route translates it.

    None for a source that needs no binding, which is every source but CSV. A CSV slot arriving
    WITHOUT one is not rejected here: `available_for` and the binding requirement are the source's
    to state, and it raises `CsvBindingError` naming the slot, which the route maps to a clean
    failure. Rejecting it here would mean this module hardcoding which source keys need a binding —
    exactly the coupling the previous paragraph avoids.
    """

    name: str
    source: str
    window: tuple[datetime, datetime]
    binding: dict | None = None


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
    stat_id: str | None = None
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
    backend_loads: dict[str, BackendLoadRequest] = field(default_factory=dict)
    # The setup-band answers this fetch commits (specs §2.1), or None when the header carried
    # none. None means "leave the stored answer alone" — an older client that does not send them
    # must not silently reset the user's configuration. The route persists them on `done`.
    setup_has_pv: bool | None = None
    setup_has_battery: bool | None = None
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
        # The setup-band answers (specs §2.1). Absent → None → the stored answer is kept, so a
        # client that predates this field cannot reset the user's configuration. Anything present
        # is coerced with bool(), which is what a JSON true/false already is; a malformed value is
        # not worth failing an otherwise-good fetch over.
        if "has_pv" in msg:
            self.setup_has_pv = bool(msg.get("has_pv"))
        if "has_battery" in msg:
            self.setup_has_battery = bool(msg.get("has_battery"))
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
        # stat_id is the HA statistic id the browser fetched from (specs §2.2), persisted so a
        # fetched HA slot renders its entity after a reload. Optional: older callers omit it.
        self.buffers[name] = _SeriesBuffer(
            name=name, kind=slot.kind, unit=msg.get("unit"), stat_id=msg.get("stat_id")
        )

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
                # Only the first two elements are read. A price row used to carry the HA
                # statistic's own min/max in positions 2 and 3; those are gone (§6.16's bracket is
                # derived from the 15-minute values at grid reconciliation, not taken from the
                # source), and any extra elements a stale cached ha_fetch.js still sends are
                # ignored rather than rejected.
                target.price_rows.extend(
                    ingest.PriceRow(start_ms=int(r[0]), mean=_opt_float(r[1])) for r in rows
                )
        except (IndexError, TypeError, ValueError) as exc:
            raise IngestError(f"malformed row in {name!r}: {exc}") from exc
        return buf.row_count

    def on_backend_load(self, msg: dict) -> None:
        """Record one staged backend-load slot to reify on `done` (specs §2.2 reify-on-fetch).

        Validates the slot name against the closed vocabulary and the window shape (same rules as
        the header window); the source key and its kind/availability are checked by the route when
        it actually loads (it owns the registry). A slot declared as both a `series` (HA) and a
        `backend_load` in one fetch is a client bug — rejected here.

        An optional `binding` is validated for SHAPE only — see the module comment on why that is
        the honest division of labour and why it is not redundant with the route's existence check.
        The shape rules are deliberately weak and generic: an object, with a non-empty string
        `upload_id` and a non-empty string `column`, and `unit` a string when present. What counts
        as a valid unit is `csv_wide.UNIT_FACTORS`, and what counts as an existing upload is the
        `uploads` store — both are the source's and the route's business respectively, and importing
        either here would make the protocol layer depend on an adapter it otherwise knows nothing
        about. What this check buys is that a malformed message is refused before any file is opened,
        with a message naming the offending field rather than a `TypeError` from deep inside a load.
        """
        if not self._header_seen:
            raise IngestError("backend_load declared before header")
        name = msg.get("name")
        if not is_known_series(name):
            raise IngestError(f"unknown series name: {name!r}")
        if name in self.buffers:
            raise IngestError(f"slot {name!r} declared as both a fetched series and a backend load")
        if name in self.backend_loads:
            raise IngestError(f"backend_load declared twice: {name!r}")
        source = msg.get("source")
        if not source:
            raise IngestError(f"backend_load for {name!r} missing 'source'")
        win = msg.get("window") or {}
        try:
            start = datetime.fromisoformat(win["start"])
            end = datetime.fromisoformat(win["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestError(f"invalid backend_load window for {name!r}: {exc}") from exc
        if end <= start:
            raise IngestError(f"backend_load window end must be after start for {name!r}")
        binding = _check_binding_shape(name, msg.get("binding"))
        self.backend_loads[name] = BackendLoadRequest(
            name=name, source=source, window=(start, end), binding=binding
        )

    def finish(self) -> tuple[list[SeriesFrame], list[dict], tuple[datetime, datetime]]:
        if not self._header_seen or self.window is None:
            raise IngestError("done before header")
        # A fetch reifies the staged config: at least one HA series OR one backend-load slot.
        # (A backend-only fetch — energy_charts spot price with no HA slots — is valid.)
        if not self.buffers and not self.backend_loads:
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

        # Carry the HA statistic id onto the frame so save_dataset persists it (series_meta) and a
        # fetched HA slot can render its entity after a reload (specs §2.2).
        frame.stat_id = buf.stat_id
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


def _check_binding_shape(name: str, binding) -> dict | None:
    """The optional per-slot `binding` on a `backend_load` message, shape-checked. None passes.

    Absent is the normal case — every source but the uploaded CSV needs nothing beyond
    `(slot, window)` — so `None` is returned unchanged rather than treated as an error. A slot that
    NEEDS a binding and did not send one is the source's to reject (`CsvBindingError`), for the
    reason `BackendLoadRequest` records: knowing which source keys require configuration would
    couple this module to `app/sources/`.

    What is checked, and nothing more (module comment): it is an object; `upload_id` and `column` are
    non-empty strings; `unit`, when present, is a string. Not checked here, on purpose:

      * whether `unit` is one of `csv_wide.UNIT_FACTORS` — the parser owns that vocabulary and
        already raises `bad_unit` with the list, so duplicating it here would give two places to
        update when a unit is added;
      * whether `upload_id` has the 32-hex shape a generated id has — `uploads._check_upload_id`
        owns that, runs before the id becomes a path component, and is the traversal guard. A weaker
        copy here would look like the guard without being it;
      * whether the upload EXISTS — that needs the store, i.e. I/O, and is the route's job. It is
        also the security-relevant check, since the id is client-supplied.

    `column` is not validated against the file's header either: the header is in the file, which this
    module never opens. `column_frame` reports an unknown column by name.

    An empty-string `column` is rejected rather than passed through, because it is the one malformed
    value a half-built drawer will actually produce (a selector with no selection) and the resulting
    error otherwise names a missing column called `''`, which reads like a file problem rather than a
    configuration one.
    """
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise IngestError(
            f"backend_load binding for {name!r} must be an object, got {type(binding).__name__}"
        )
    upload_id = binding.get("upload_id")
    if not isinstance(upload_id, str) or not upload_id:
        raise IngestError(f"backend_load binding for {name!r} is missing 'upload_id'")
    column = binding.get("column")
    if not isinstance(column, str) or not column:
        raise IngestError(f"backend_load binding for {name!r} is missing 'column'")
    unit = binding.get("unit")
    if unit is not None and not isinstance(unit, str):
        raise IngestError(f"backend_load binding for {name!r} has a non-string 'unit'")
    return binding


def _opt_float(v) -> float | None:
    """Parse a possibly-null numeric cell to float, or None for null/NaN (a gap, specs §4.2)."""
    if v is None:
        return None
    f = float(v)
    if f != f:  # NaN
        return None
    return f
