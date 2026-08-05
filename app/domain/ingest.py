"""Raw statistics rows → SeriesFrame (specs §6.1, §4.3).

This is the pure normalisation the backend performs on rows the browser fetched from Home
Assistant (docs/specs/06-home-assistant-ingestion.md, browser-side fetch increment). It never does
I/O: it takes plain Python lists of rows and a series role, and returns a `SeriesFrame`
(app/domain/frames.py).

Two row shapes arrive, matching the two HA statistic kinds (specs §4.3):

  * **energy** — from a `total`/`total_increasing` sensor. Each row carries `sum` (a meter
    register HA has already reset-corrected) and, redundantly, `change` (HA's own per-interval
    delta). We difference `sum` ourselves via `cumulative_to_delta` rather than trust `change`,
    because the reset semantics and the ambiguous-decrease handling in §6.1 are ours to own and
    must match the CSV path exactly. HA's reset correction on `sum` means genuine resets are
    rare here, but the logic is applied uniformly.

  * **price** — from a `measurement` sensor. Each row carries `mean`, the price the run uses. No
    differencing: a price is a step function valid from the interval start. The statistic's own
    `min`/`max` columns are neither fetched nor parsed: the §6.16 bracket is derived from the
    15-minute values at grid reconciliation (`simframe._resample_price_stats`), so the source's
    idea of an intra-interval spread is not needed and would not be used.

Native resolution is inferred from the spacing of the rows themselves (specs §4.2, §4.4): the
modal gap between consecutive interval starts. Irregular spacing yields `resolution_s = None`.

Main items:
    RESET_TOLERANCE_KWH, RESET_FLOOR_KWH   §6.1 reset heuristics.
    GAP_FACTOR                             spacing multiple above which a gap is declared.
    Row types                              EnergyRow, PriceRow — the parsed WS payload rows.
    cumulative_to_delta(ts, values)        §6.1 register→delta with reset/gap flagging.
    infer_resolution_s(index)              modal spacing, or None if irregular.
    energy_frame(...) / price_frame(...)   assemble a SeriesFrame from parsed rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.frames import QUALITY_DTYPE, QualityFlags, SeriesFrame

# --- module constants (ingest heuristics, specs §6.1) --------------------------------------
RESET_TOLERANCE_KWH = 0.01  # a negative step smaller than this is float noise, not a reset
RESET_FLOOR_KWH = 1.0       # register restarting below this reads as a genuine reset

# A gap is declared when the spacing to the next row exceeds GAP_FACTOR × the native
# resolution (specs §6.1 gap handling). 1.5 tolerates minor jitter in HA's hourly timestamps
# while still catching a missed interval (2× spacing).
GAP_FACTOR = 1.5

# Fraction of a millisecond, in seconds — HA timestamps are millisecond epochs, so spacings
# are integer seconds after conversion; this guards the resolution mode against float dust.
_SECOND = 1


@dataclass
class EnergyRow:
    """One HA energy-statistics row (specs §4.3): epoch-ms start, reset-corrected `sum`."""

    start_ms: int
    sum: float | None


@dataclass
class PriceRow:
    """One HA price-statistics row (specs §4.3): epoch-ms start and mean price."""

    start_ms: int
    mean: float | None


def _index_from_ms(starts_ms: np.ndarray) -> np.ndarray:
    """Epoch-milliseconds → datetime64[s] UTC index (interval starts)."""
    # HA statistics starts are whole seconds in practice; integer-divide ms→s.
    return (starts_ms // 1000).astype("datetime64[s]")


def infer_resolution_s(index: np.ndarray) -> int | None:
    """Native spacing in seconds — the modal gap between interval starts, or None if irregular.

    "Irregular" (specs §4.4) means no single spacing dominates: here, the modal gap covers
    fewer than half the gaps. A series with one dominant spacing plus a few gaps (missed
    intervals) is still regular — the gaps are handled separately in cumulative_to_delta.
    """
    if len(index) < 2:
        return None
    diffs = np.diff(index).astype("timedelta64[s]").astype(np.int64)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        return None
    values, counts = np.unique(diffs, return_counts=True)
    mode = int(values[np.argmax(counts)])
    # A spacing is "dominant" only if it covers *more than* half the gaps. With every gap
    # distinct (no repeat), the mode count is 1 and the series is irregular (specs §4.4).
    if counts.max() <= len(diffs) / 2:
        return None
    return mode if mode > 0 else None


def cumulative_to_delta(
    index: np.ndarray, values: np.ndarray, resolution_s: int | None
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Meter register → per-interval deltas, with reset and gap flagging (specs §6.1).

    `values` is the cumulative register aligned to `index` (interval starts). Returns
    `(deltas, flags, warnings)` where deltas has length `len(index) - 1` — one per interval
    *between* readings — aligned to the interval start `index[:-1]`, matching the spec's
    "aligned to interval start". `flags` is the per-interval QualityFlags array; `warnings` is
    a list of dicts for ambiguous register decreases (specs §6.1 AMBIGUOUS_REGISTER_DECREASE).

    Reset logic (specs §6.1), applied element-wise to each negative step:
      * drop < RESET_TOLERANCE_KWH        → float noise; delta = 0, no flag.
      * next reading < RESET_FLOOR_KWH    → genuine reset; delta = new reading, RESET_CORRECTED.
      * otherwise                         → ambiguous; delta = 0, RESET_CORRECTED + a warning.

    Gaps (specs §6.1): where the spacing to the next reading exceeds GAP_FACTOR × resolution,
    the interval is a gap — its delta is emitted as NaN (excluded from every sum) and flagged
    GAP_FILLED, rather than interpolated, which would invent a load profile.
    """
    n = len(index)
    if n == 0:
        empty = np.array([], dtype=np.float64)
        return empty, np.array([], dtype=QUALITY_DTYPE), []
    if n == 1:
        # A single reading yields no interval delta.
        return np.array([], dtype=np.float64), np.array([], dtype=QUALITY_DTYPE), []

    d = np.diff(values)
    flags = np.zeros(n - 1, dtype=QUALITY_DTYPE)
    warnings: list[dict] = []

    neg = np.where(d < 0)[0]
    for i in neg:
        drop = -d[i]
        nxt = values[i + 1]
        if drop < RESET_TOLERANCE_KWH:
            d[i] = 0.0
        elif nxt < RESET_FLOOR_KWH:
            d[i] = nxt  # energy since the reset is the new reading
            flags[i] |= QualityFlags.RESET_CORRECTED
        else:
            d[i] = 0.0
            flags[i] |= QualityFlags.RESET_CORRECTED
            warnings.append(
                {
                    "code": "AMBIGUOUS_REGISTER_DECREASE",
                    "index": int(i),
                    "start": str(index[i]),
                    "drop_kwh": float(drop),
                }
            )

    # Gap detection from the spacing between readings.
    if resolution_s is not None:
        spacing = np.diff(index).astype("timedelta64[s]").astype(np.int64)
        gap = spacing > GAP_FACTOR * resolution_s
        if gap.any():
            d = d.astype(np.float64)
            d[gap] = np.nan
            flags[gap] |= QUALITY_DTYPE(QualityFlags.GAP_FILLED)

    return d, flags, warnings


def _clean_energy_values(rows: list[EnergyRow]) -> tuple[np.ndarray, np.ndarray]:
    """Extract (starts_ms, sum) as arrays, dropping rows whose `sum` is missing (a gap)."""
    kept = [r for r in rows if r.sum is not None]
    starts = np.array([r.start_ms for r in kept], dtype=np.int64)
    sums = np.array([float(r.sum) for r in kept], dtype=np.float64)
    return starts, sums


def energy_frame(name: str, rows: list[EnergyRow]) -> tuple[SeriesFrame, list[dict]]:
    """Build an energy SeriesFrame from HA `sum`-statistics rows (specs §6.1, §4.3).

    The register (`sum`) is differenced into per-interval kWh deltas by `cumulative_to_delta`.
    The frame's index is the interval starts (all but the last reading, since a delta spans two
    readings). Returns `(frame, warnings)`.
    """
    rows = sorted(rows, key=lambda r: r.start_ms)
    starts, sums = _clean_energy_values(rows)
    full_index = _index_from_ms(starts)
    resolution_s = infer_resolution_s(full_index)

    deltas, flags, warnings = cumulative_to_delta(full_index, sums, resolution_s)
    index = full_index[:-1] if len(full_index) else full_index

    frame = SeriesFrame(
        name=name,
        kind="energy",
        resolution_s=resolution_s,
        index=index,
        values=deltas,
        quality=flags,
    )
    return frame, warnings


def price_frame(name: str, rows: list[PriceRow]) -> SeriesFrame:
    """Build a price SeriesFrame from HA `measurement`-statistics rows (specs §4.3).

    No differencing: `mean` is the price valid from the interval start. A row whose `mean` is
    missing is a gap; prices are forward-filled at grid reconciliation (specs §6.1), so here the
    missing interval is simply dropped and its absence shows up as a spacing gap.
    """
    rows = sorted(rows, key=lambda r: r.start_ms)
    kept = [r for r in rows if r.mean is not None]
    starts = np.array([r.start_ms for r in kept], dtype=np.int64)
    index = _index_from_ms(starts)
    values = np.array([float(r.mean) for r in kept], dtype=np.float64)
    resolution_s = infer_resolution_s(index)

    return SeriesFrame(
        name=name,
        kind="price",
        resolution_s=resolution_s,
        index=index,
        values=values,
        quality=np.zeros(len(index), dtype=QUALITY_DTYPE),
    )
