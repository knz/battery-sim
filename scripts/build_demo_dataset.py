#!/usr/bin/env python3
"""Build the committed demo dataset from a real workspace's `.npz` series.

The demo dataset (`app/data/demo/`) is what `app.demo` materializes into a workspace: a
three-month slice of a real Dutch PV household, carried in the repository as CSV plus a JSON
manifest. This script is the generator that produces those files, committed so the artifacts are
reproducible and reviewable rather than an opaque blob.

Why CSV and not the `.npz` the app reads: the `.npz` files are inert on their own. They hold only
`index_s` / `values` / `quality` — the slot length, the series kind and the coverage window all
live in SQLite (`datasets`, `series_meta`), and `series_meta.path` is stored ABSOLUTE, so a
committed data directory would point at the generating machine. `app.demo` therefore rebuilds the
metadata through `dataset.save_dataset()` at whatever data dir is active, and the committed form
only has to carry the numbers. CSV diffs and reviews in git; the `.npz` would not.

Prices are NOT emitted. The window's spot prices are already committed under
`app/data/spot_prices/NL-2026.csv` at 15-minute resolution, and were verified equal to the source
workspace's `price_spot.npz` over the window to within 0.0. `app.demo` slices them at load time,
so there is one source of truth for the price numbers.

## Anonymisation, and what it does not achieve

The source is the author's own household, so the raw window carries an occupancy signal: multi-day
stretches where grid import collapses read as travel. This script attenuates that. Days in the
quietest quarter of OVERNIGHT import have that import resampled from a median hour-of-day profile
of the remaining days, rescaled per day so the replacements vary the way real days do. Export, PV
and prices are left byte-exact.

State the limit plainly, because it is easy to overclaim here. The overnight baseload distribution
is CONTINUOUS — median 1.83 kWh, 10th percentile 1.02, minimum 0.90, no gap anywhere — so there is
no away/home boundary to detect and nothing that can be cleanly excised. Resampling a quantile
lifts the low tail (overnight min/median 0.49 → 0.58) and removes the multi-day runs that read as
travel, but a new bottom quartile always exists. This makes inference harder and less confident;
it does not make the data non-inferential. `select_quiet_nights` documents the two sharper rules
that were tried first and why measurement rejected both.

The daily rhythm and the household's scale remain visible by design — they are what make the demo
worth shipping, and neither identifies a household on its own.

Main items:
    WINDOW_START / WINDOW_END   the committed window, 2026-04-01 .. 2026-07-01 (exclusive).
    ENERGY_SERIES               the five energy slots carried in the demo.
    load_window()               read one `.npz` and slice it to the window.
    overnight_totals()          per-night grid import, the weather-independent occupancy proxy.
    select_quiet_nights()       the bottom-quartile-of-overnight-import rule.
    resample_quiet_nights()     replace those days' import with a rescaled typical profile.
    write_csv() / write_manifest()  emit the committed artifacts.
    main()                      wire it together and print a before/after report.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

# The committed window. End is EXCLUSIVE, matching the half-open convention SeriesFrame.coverage()
# uses (`last interval start + resolution`).
WINDOW_START = dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc)
WINDOW_END = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)

# The energy slots the demo carries, in §4.1 vocabulary order. `price_spot` is deliberately absent
# (see the module docstring); the two `price_spot_min`/`price_spot_max` files that exist in the
# source workspace are dead — their names fail `is_known_series`, so the app already drops them.
ENERGY_SERIES = (
    "grid_import_t1",
    "grid_import_t2",
    "grid_export_t1",
    "grid_export_t2",
    "solar_production",
)

# Hourly energy data. Asserted rather than inferred, so a source workspace at a different
# resolution fails loudly instead of producing a mislabelled manifest.
RESOLUTION_S = 3600

# Every day whose overnight import falls in the bottom `LOW_NIGHT_PCT` of the window is
# resampled. See `select_quiet_nights` for why the rule is a flat percentile of the overnight
# baseload rather than a cleverer away-vs-home classifier.
LOW_NIGHT_PCT = 25.0

# The overnight window, in UTC hours: from `NIGHT_FROM` through to `NIGHT_TO` the next morning.
# PV is zero throughout, so import here is household draw alone, independent of the weather.
NIGHT_FROM, NIGHT_TO = 23, 5

# Fixed seed for the per-day scale factors in `resample_quiet_nights`, so re-running this script over
# the same source reproduces the committed CSVs byte for byte.
_SMOOTHING_SEED = 20260807


def load_window(series_dir: Path, name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read `<series_dir>/<name>.npz` and slice it to [WINDOW_START, WINDOW_END).

    Returns `(index_s, values, quality)`. Raises if the file does not cover the window, so a
    source workspace missing the period fails here rather than silently emitting a short demo.
    """
    path = series_dir / f"{name}.npz"
    if not path.exists():
        raise SystemExit(f"missing source series: {path}")
    z = np.load(path, allow_pickle=False)
    idx, values, quality = z["index_s"], z["values"], z["quality"]
    lo, hi = int(WINDOW_START.timestamp()), int(WINDOW_END.timestamp())
    mask = (idx >= lo) & (idx < hi)
    if not mask.any():
        raise SystemExit(f"{name}: no data in {WINDOW_START.date()}..{WINDOW_END.date()}")
    idx, values, quality = idx[mask], values[mask], quality[mask]
    expected = (hi - lo) // RESOLUTION_S
    if len(idx) != expected:
        raise SystemExit(f"{name}: expected {expected} hourly slots in window, found {len(idx)}")
    steps = np.unique(np.diff(idx))
    if steps.size and (steps != RESOLUTION_S).any():
        raise SystemExit(f"{name}: non-hourly spacing in window: {sorted(steps.tolist())}")
    return idx, values, quality


def _day_of(ts: int) -> dt.date:
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date()


def overnight_totals(idx: np.ndarray, imp: np.ndarray) -> dict[dt.date, float]:
    """Grid import per night, summed over [NIGHT_FROM, NIGHT_TO) UTC.

    A night is attributed to the calendar day it STARTS on, so an evening and the small hours
    that follow it count as one observation rather than two halves of different days.
    """
    out: dict[dt.date, float] = {}
    for ts, a in zip(idx, imp):
        moment = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
        if moment.hour >= NIGHT_FROM or moment.hour < NIGHT_TO:
            night = (moment - dt.timedelta(hours=NIGHT_FROM)).date()
            out[night] = out.get(night, 0.0) + float(a)
    return out


def select_quiet_nights(idx: np.ndarray, imp: np.ndarray, pv: np.ndarray) -> list[dt.date]:
    """Days in the bottom `LOW_NIGHT_PCT` of overnight import — the low tail that gets resampled.

    Named for what it does rather than what it was for: this selects quiet nights, it does not
    identify absences, because the data does not support identifying them. Two sharper rules were
    tried first and rejected on measurement:

      * *Low daily import + high PV.* The PV term was meant to separate "away" from "overcast".
        It flagged 12 days, but it selects on sunshine as much as on occupancy, and it left a
        sustained mid-April low-import stretch untouched simply because those days were dull.
      * *Low daily import alone.* Confounded outright — a mild day with the heating off looks
        like an empty house.

    Measuring the overnight baseload (PV is zero, so this is household draw with the weather
    factored out) showed why no rule does better: the distribution is CONTINUOUS. Median 1.83
    kWh, 10th percentile 1.02, minimum 0.90 — the quietest nights sit about 45% below median with
    no gap anywhere, which is what a fridge-and-standby floor looks like, not a house that empties.

    So there is no away/home boundary to find, and a classifier that picks days out of a continuum
    would just be encoding a guess. The rule here is therefore deliberately blunt and uniform: the
    quietest quarter of nights gets resampled, whatever caused them. That covers the real absences
    without claiming to know which they were, and — because it is a flat percentile — it cannot be
    accused of cherry-picking the days that happened to look incriminating.

    `pv` is unused, kept in the signature so callers and tests need not change if a future rule
    reintroduces a production term.
    """
    del pv  # see docstring
    nights = overnight_totals(idx, imp)
    if not nights:
        return []
    cut = float(np.percentile(np.array(list(nights.values())), LOW_NIGHT_PCT))
    return [d for d in sorted(nights) if nights[d] <= cut]


def _typical_hourly_profile(
    idx: np.ndarray, values: np.ndarray, exclude: set[dt.date]
) -> np.ndarray:
    """Hour-of-day (UTC) shape for a lived-in day, over the days NOT in `exclude`.

    Median per hour gives the SHAPE, resisting single outlier days. But a median profile cannot
    be used as-is: summing 24 independently-taken medians lands well below the median DAILY
    total, because no single day sits at the median in every hour. Measured here, the raw
    median-of-medians came to 3.67 kWh/day against an all-days median of 5.05 — close enough to
    the absence days' own 3.33 that the replacement stayed in the bottom of the distribution and
    the absence detector re-flagged every day it had just smoothed.

    So the shape is rescaled to the median daily total of the retained days. That keeps the
    realistic hour-to-hour curve while putting the replaced days at a genuinely typical level.
    """
    buckets: dict[int, list[float]] = {h: [] for h in range(24)}
    daily: dict[dt.date, float] = {}
    for ts, v in zip(idx, values):
        day = _day_of(ts)
        if day in exclude:
            continue
        hour = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).hour
        buckets[hour].append(float(v))
        daily[day] = daily.get(day, 0.0) + float(v)
    shape = np.array([float(np.median(buckets[h])) if buckets[h] else 0.0 for h in range(24)])
    if not daily or shape.sum() <= 0:
        return shape
    return shape * (float(np.median(list(daily.values()))) / shape.sum())


def resample_quiet_nights(
    idx: np.ndarray,
    series: dict[str, np.ndarray],
    quiet_days: list[dt.date],
) -> dict[str, np.ndarray]:
    """Replace grid import on the selected quiet days with a rescaled typical hour-of-day profile.

    Import is what leaks occupancy — the collapse in evening and overnight draw is the signal —
    so import is what gets replaced: each quiet slot takes the median value for that hour-of-day
    over the retained days. T1/T2 are resampled independently, so the tariff-register split stays
    consistent with the tariff windows rather than being pooled and redistributed.

    Export and PV are left untouched, deliberately. An earlier version tried to rebalance export
    to hold `consumption = pv + import - export` fixed, on the theory that changing import without
    changing export distorts the implied consumption. Two measurements killed that:

      * 130 of the 288 slots selected by the original rule have ZERO export. They are night hours
        — exactly where the import correction is largest — so there is nothing to subtract from
        and the correction silently vanishes, which breaks the identity instead of preserving it.
      * The identity does not hold in the source data anyway: the raw window has 10 slots with
        negative implied consumption (min −2.26 kWh), because the meter and the inverter are not
        perfectly clock-aligned. Preserving an identity the real data violates is not a property
        worth engineering for.

    Since the app DERIVES consumption from these series rather than reading a stored consumption
    series, a resampled import simply yields a correspondingly resampled consumption. That is the
    intended outcome and it needs no compensating edit.

    Returns a new dict; the input arrays are not modified.
    """
    out = {k: v.copy() for k, v in series.items()}
    if not quiet_days:
        return out
    absent = set(quiet_days)
    days = np.array([_day_of(ts) for ts in idx])
    is_absent = np.array([d in absent for d in days])
    hours = np.array([dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).hour for ts in idx])

    # Per-day scale factors, so the replaced days are not all byte-identical. A run of days with
    # exactly the same total is its own conspicuous artifact — it advertises precisely which days
    # were scrubbed, which partly defeats the point. Factors are sampled deterministically (fixed
    # seed, so the committed artifacts are reproducible) from the spread of the retained days'
    # daily totals, giving the replacements the same day-to-day variability as real ones.
    rng = np.random.default_rng(_SMOOTHING_SEED)
    retained_totals = _daily_totals(
        idx, series["grid_import_t1"] + series["grid_import_t2"], exclude=absent
    )
    spread = np.array(sorted(retained_totals.values()))
    # Sample from the interquartile band only: the tails are the outliers (a heatwave, a quiet
    # weekend) and reproducing them here would just reintroduce conspicuous days.
    lo, hi = np.percentile(spread, 25), np.percentile(spread, 75)
    median = float(np.median(spread))
    factors = {d: float(rng.uniform(lo, hi) / median) for d in sorted(absent)}
    day_factor = np.array([factors.get(d, 1.0) for d in days])

    for name in ("grid_import_t1", "grid_import_t2"):
        profile = _typical_hourly_profile(idx, series[name], absent)
        out[name] = np.where(is_absent, profile[hours] * day_factor, series[name])
    return out


def _daily_totals(
    idx: np.ndarray, values: np.ndarray, exclude: set[dt.date] | None = None
) -> dict[dt.date, float]:
    """Sum `values` per UTC calendar day, skipping days in `exclude`."""
    skip = exclude or set()
    out: dict[dt.date, float] = {}
    for ts, v in zip(idx, values):
        day = _day_of(ts)
        if day in skip:
            continue
        out[day] = out.get(day, 0.0) + float(v)
    return out


def write_csv(path: Path, idx: np.ndarray, values: np.ndarray, quality: np.ndarray) -> None:
    """Emit `timestamp,value,quality`, ISO-8601 UTC, matching the spot-price CSV convention."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "value", "quality"])
        for ts, v, q in zip(idx, values, quality):
            stamp = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).isoformat()
            w.writerow([stamp, f"{float(v):.6f}", int(q)])


def write_manifest(path: Path, simconfig: dict, quiet_days: list[dt.date], stats: dict) -> None:
    """Emit the JSON sidecar `app.demo` reads: window, series roster, config, provenance."""
    doc = {
        "version": 1,
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "resolution_s": RESOLUTION_S,
        "series": [
            {"name": n, "kind": "energy", "resolution_s": RESOLUTION_S, "file": f"{n}.csv"}
            for n in ENERGY_SERIES
        ],
        "price_series": {
            "name": "price_spot",
            "kind": "price",
            "source": "app/data/spot_prices/NL-{year}.csv",
            "note": "Sliced from the bundled Energy-Charts spot prices at load time, not "
            "duplicated here. Verified equal to the source workspace's price_spot over "
            "this window.",
        },
        "simconfig": simconfig,
        "provenance": {
            "source": "A real Dutch three-phase PV household, hourly meter data.",
            "anonymisation": (
                "Occupancy patterns are attenuated, not removed. Days in the quietest "
                "quarter of overnight grid import had that import resampled from a median "
                "hour-of-day profile of the remaining days, rescaled per day so the "
                "replacements vary as real days do. Export, PV and prices are the original "
                "measurements. This lifts the low tail (overnight min/median 0.49 -> 0.58) "
                "and removes the multi-day low-import runs that read as travel, but the "
                "underlying distribution is continuous, so resampling a quantile moves the "
                "boundary rather than eliminating it: some inference remains possible."
            ),
            "resampled_days": [d.isoformat() for d in quiet_days],
            "totals_kwh": stats,
        },
    }
    path.write_text(json.dumps(doc, indent=2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--source",
        type=Path,
        default=Path("/home/kena/src/battery-sim/data/local"),
        help="workspace directory holding series/ and simconfig.json",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "app" / "data" / "demo",
        help="destination directory for the committed demo artifacts",
    )
    args = ap.parse_args()

    series_dir = args.source / "series"
    idx = None
    raw: dict[str, np.ndarray] = {}
    quality: dict[str, np.ndarray] = {}
    for name in ENERGY_SERIES:
        i, v, q = load_window(series_dir, name)
        if idx is None:
            idx = i
        elif not np.array_equal(i, idx):
            raise SystemExit(f"{name}: index does not align with the other series")
        raw[name] = v
        quality[name] = q
    assert idx is not None

    imp = raw["grid_import_t1"] + raw["grid_import_t2"]
    quiet_days = select_quiet_nights(idx, imp, raw["solar_production"])
    smoothed = resample_quiet_nights(idx, raw, quiet_days)

    def totals(d: dict[str, np.ndarray]) -> dict[str, float]:
        return {k: round(float(np.nansum(v)), 3) for k, v in d.items()}

    before, after = totals(raw), totals(smoothed)
    print(f"window {WINDOW_START.date()} .. {WINDOW_END.date()} ({len(idx)} hourly slots)")
    print(f"quiet days resampled: {len(quiet_days)} of {len(quiet_days) and len(idx) // 24}")
    for d in quiet_days:
        print(f"    {d} {d.strftime('%a')}")
    print("\ntotals (kWh)            before        after      delta")
    for k in ENERGY_SERIES:
        print(f"  {k:20s} {before[k]:10.1f} {after[k]:12.1f} {after[k] - before[k]:10.1f}")

    # Not an invariant — see `resample_quiet_nights` — but worth reporting, since a jump in the
    # negative-slot count would mean the resampling introduced artifacts the source did not have.
    cons_before = raw["solar_production"] + imp - (raw["grid_export_t1"] + raw["grid_export_t2"])
    imp_after = smoothed["grid_import_t1"] + smoothed["grid_import_t2"]
    cons_after = (
        smoothed["solar_production"]
        + imp_after
        - (smoothed["grid_export_t1"] + smoothed["grid_export_t2"])
    )
    print(
        f"\nimplied consumption total: {cons_before.sum():.1f} -> {cons_after.sum():.1f} kWh"
        f"  (negative slots: {(cons_before < 0).sum()} -> {(cons_after < 0).sum()})"
    )

    simconfig = json.loads((args.source / "simconfig.json").read_text())
    # The demo ships a config, not the author's retained UI state.
    simconfig.pop("retained", None)
    simconfig["postcode"] = ""
    # The source workspace runs P3/D3 (charge from surplus AND in-band grid, discharge to the
    # house AND in-band export) because that is the question its owner is asking. The demo ships
    # the appendix-A defaults P1/D1 instead: charge from solar surplus only, discharge to serve
    # household deficit only. That is the self-consumption battery most readers picture, it is
    # what a new workspace starts on, and — per §6.6/§6.7 — it is the pair that cannot conflict,
    # so the demo's flows read as the simple story rather than as price arbitrage.
    simconfig["policy"] = {**simconfig.get("policy", {}), "charge_policy": "P1",
                           "discharge_policy": "D1"}
    # A 6 kWh / 5 kW battery rather than the source workspace's 15 kWh / 7 kW: a commonly-sold
    # domestic size, so the demo answers "what would a typical battery have done for this
    # household" rather than showcasing an unusually large one.
    simconfig["battery"] = {**simconfig.get("battery", {}), "usable_capacity_kwh": 6,
                            "max_charge_kw": 5.0, "max_discharge_kw": 5.0}

    for name in ENERGY_SERIES:
        write_csv(args.out / f"{name}.csv", idx, smoothed[name], quality[name])
    write_manifest(args.out / "manifest.json", simconfig, quiet_days, after)
    print(f"\nwrote {len(ENERGY_SERIES)} CSV files + manifest.json to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
