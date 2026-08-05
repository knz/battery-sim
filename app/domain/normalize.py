"""Simulation-grid selection and per-series reconciliation metadata (specs §6.2).

This increment does not resample series onto the grid or run a simulation — that is a later
increment. What it does compute is the metadata panel ① shows (docs/specs/02-ux-wireframes.md §2.2
"Granularity, per series"): the chosen simulation grid, and how each series *would* reconcile
onto it — `exact`, `held`, or `averaged` — plus the price-granularity-lost diagnostic
(specs §6.2 note, §4.5 `diagnostics.price_granularity_lost`).

Keeping this pure and separate from the ingest means the "what the run uses" column is derived
from the same rule the simulation will later use, not a second copy of it.

Main items:
    choose_grid(frames, window)         coarsest covering energy resolution (specs §6.2).
    grid_facts(frames, window)          (grid_s, intervals) — the run's size, for the card too.
    reconciliation(frame, grid_s)       "exact" | "held" | "averaged" | "undefined".
    PRICE_GRANULARITY_LOST_FACTOR       downsample factor at/above which the ⚠ is raised (§6.2, 3b).
    grid_report(frames, window)         the panel-① granularity/grid view-model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.domain.frames import SeriesFrame

# A price averaged down by this factor or more raises diagnostics.price_granularity_lost
# and the ⚠ marker in panel ① (specs §6.2 note, §7.3 check 3b).
PRICE_GRANULARITY_LOST_FACTOR = 2

Reconciliation = Literal["exact", "held", "averaged", "undefined"]


def effective_window(
    frames: list[SeriesFrame], requested: tuple[datetime, datetime]
) -> tuple[datetime, datetime]:
    """The window the run can actually cover: the overlap of the energy series' coverage.

    The client's *requested* fetch bounds (wall-clock now − N days) rarely align to the data:
    the last interval a differenced meter series covers ends an interval before `now`, and the
    first covered interval starts at the first reading, not at exactly N days ago. Grid selection
    must test coverage against a window the data can actually span, or every series reads as
    "not covering" and the grid comes out undefined. So the effective window is the intersection
    of the energy series' coverage, clipped to the requested bounds. Falls back to `requested`
    when there are no energy series (nothing to intersect).
    """
    covs = [f.coverage() for f in frames if f.kind == "energy"]
    covs = [c for c in covs if c is not None]
    if not covs:
        return requested
    start = max(c[0] for c in covs)
    end = min(c[1] for c in covs)
    # Clip to the requested bounds, but never invert: if the intersection is empty, keep the
    # data-derived [start, end] so downstream still has a sane (possibly small) window.
    start = max(start, requested[0])
    end = min(end, requested[1])
    if end <= start:
        start = max(c[0] for c in covs)
        end = min(c[1] for c in covs)
    return start, end


def choose_grid(frames: list[SeriesFrame], window: tuple[datetime, datetime]) -> int | None:
    """The simulation grid: the coarsest native resolution among covering energy series (§6.2).

    Downsampling energy (summing deltas) is exact; upsampling would require inventing a
    within-interval profile and is forbidden. So the grid is the *max* energy resolution among
    series that cover the whole window. Returns None if no energy series covers the window (the
    caller reports this as "no simulatable data"), which keeps this function total.
    """
    resolutions = [
        f.resolution_s
        for f in frames
        if f.kind == "energy" and f.resolution_s is not None and f.covers(window)
    ]
    if not resolutions:
        return None
    return max(resolutions)


def grid_facts(
    frames: list[SeriesFrame], window: tuple[datetime, datetime]
) -> tuple[int | None, int | None]:
    """The run's size: `(grid_s, intervals)` over the effective window (specs §6.2).

    The three steps every caller needs together — narrow to `effective_window`, pick the grid on
    THAT window, count intervals in it. `grid_report` is the panel-① view built on top; this is
    the same answer without the per-series table, for callers that only need the size.

    It exists because the size was being derived twice. The workspace card
    (`workspaces._data_facts`) could not call `grid_report` — it has SQLite metadata, not frames —
    so it re-derived the pair from the stored window and an unfiltered `max(resolution_s)`, and
    the two answers diverged in both of the ways this function's two steps prevent:

      * **The window.** The stored window is the advertised *fetch* bounds; the run covers the
        energy series' coverage intersection. A three-hour auxiliary energy series alongside a
        two-day meter series makes those differ by a factor of 16 — measured, followup I2.
      * **The grid.** `choose_grid`'s `covers()` test drops a series that spans nothing, which an
        unfiltered `max()` over `series_meta` keeps — so an EMPTY energy series carrying a coarse
        resolution pulled the reported grid coarser than the run's.

    The card now persists what this returns at save time (`dataset.save_dataset`) instead of
    re-deriving it, so there is one implementation of "how big is this run" rather than two.

    Both elements are None when no energy series covers the window — `choose_grid` returning None
    is "nothing simulatable here", and a count against no grid would be an invention.
    """
    window = effective_window(frames, window)
    grid_s = choose_grid(frames, window)
    return grid_s, _interval_count(window, grid_s)


def reconciliation(frame: SeriesFrame, grid_s: int | None) -> Reconciliation:
    """How `frame` reconciles onto the grid (specs §6.2 table).

    energy: always `exact` (summed from a finer native resolution, or already at the grid;
            an energy series is never coarser than the grid by construction).
    price : `held` if coarser than the grid (forward-filled step function, exact),
            `averaged` if finer than the grid (averaged into buckets — the one lossy case),
            `exact` if equal.
    Irregular series (`resolution_s is None`) reconcile as `undefined` (specs §6.2, §8.20).
    """
    if frame.resolution_s is None or grid_s is None:
        return "undefined"
    if frame.kind == "energy":
        return "exact"
    # price
    if frame.resolution_s == grid_s:
        return "exact"
    if frame.resolution_s > grid_s:
        return "held"
    return "averaged"


def price_granularity_lost(frames: list[SeriesFrame], grid_s: int | None) -> dict:
    """The price-granularity-lost diagnostic (specs §6.2 note, §4.5).

    Set when a price series is averaged down onto the grid by PRICE_GRANULARITY_LOST_FACTOR or
    more. Returns `{"lost": bool, "native_resolution_s": int | None}`; native_resolution_s is
    the finest averaged price series' spacing (the one the user loses the most from).
    """
    if grid_s is None:
        return {"lost": False, "native_resolution_s": None}
    averaged = [
        f.resolution_s
        for f in frames
        if f.kind == "price"
        and f.resolution_s is not None
        and f.resolution_s < grid_s
        and grid_s / f.resolution_s >= PRICE_GRANULARITY_LOST_FACTOR
    ]
    if not averaged:
        return {"lost": False, "native_resolution_s": None}
    return {"lost": True, "native_resolution_s": min(averaged)}


def grid_report(frames: list[SeriesFrame], window: tuple[datetime, datetime]) -> dict:
    """Panel-① granularity/grid view-model (docs/specs/02-ux-wireframes.md §2.2).

    Returns the chosen grid, its interval count over the window, and one entry per series with
    its native resolution and reconciliation. `warn` is set only on `averaged` — the single
    lossy reconciliation, which is the whole point of the table (specs §2.2).

    Grid selection runs against the *effective* window (the data's actual coverage overlap),
    not the raw requested bounds, so hourly meter data whose coverage ends an interval short of
    a wall-clock `now` still yields an hourly grid rather than an undefined one. The grid and the
    count come from `grid_facts`, which the workspace card also persists through — the two views
    of "how big is this run" are the same computation, not two that agree by inspection.
    """
    window = effective_window(frames, window)
    grid_s, intervals = grid_facts(frames, window)
    series = []
    for f in frames:
        recon = reconciliation(f, grid_s)
        series.append(
            {
                "name": f.name,
                "native_resolution_s": f.resolution_s,
                "reconciliation": recon,
                "warn": recon == "averaged",
                "coverage": _coverage_dict(f),
            }
        )
    return {
        "grid_s": grid_s,
        "intervals": intervals,
        # The window grid selection actually ran on (data coverage overlap, §6.2), which the
        # panel-① coverage line and day count should reflect rather than the raw fetch bounds.
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()},
        "series": series,
        "price_granularity_lost": price_granularity_lost(frames, grid_s),
    }


def _coverage_dict(frame: SeriesFrame) -> dict | None:
    cov = frame.coverage()
    if cov is None:
        return None
    return {"start": cov[0].isoformat(), "end": cov[1].isoformat()}


def _interval_count(window: tuple[datetime, datetime], grid_s: int | None) -> int | None:
    if grid_s is None:
        return None
    span_s = (window[1] - window[0]).total_seconds()
    return int(span_s // grid_s)
