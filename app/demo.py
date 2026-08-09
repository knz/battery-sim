"""Materialize the committed demo dataset into a real workspace.

The demo dataset is a three-month slice (2026-04-01 → 2026-07-01) of a real Dutch PV household,
carried in the repository under `app/data/demo/` as CSV plus a JSON manifest. This module turns
those files into a workspace the app can open: index row, config document, series and metadata.
It is what the "load demo workspace" action on the workspace list calls, and what tests use when
they need a realistic multi-month dataset instead of a hand-built pair of frames.

## Why a loader, rather than committing a data directory

The `.npz` files the app reads are inert on their own. They carry only `index_s` / `values` /
`quality` — the slot length, the series kind, the coverage window and the fetch provenance all
live in SQLite (`datasets`, `series_meta` in `app/dataset.py`). Worse, `series_meta.path` is
stored as an ABSOLUTE string, so a committed `data/` tree would point at whatever machine
generated it, and `dataset._restore_frames` skips rows whose file is missing *silently* — the
failure would present as a mysteriously empty workspace rather than an error.

So the committed form carries numbers only, and `materialize()` rebuilds the metadata by calling
`dataset.save_dataset()` against whatever data dir is active. That is the same path a real HA
fetch takes, which is the point: the demo workspace is not a special case downstream.

## Prices

The manifest names no price file. The window's spot prices are already committed under
`app/data/spot_prices/` at 15-minute resolution and were verified equal, to 0.0, to the source
household's own `price_spot` series over this window — so duplicating them here would create a
second source of truth for the same numbers. `_price_frame()` slices them through
`app.sources.price_store.load_range` at materialization time, and raises if the committed price
data no longer covers the window (e.g. after a refresh that dropped old years) rather than
quietly producing a demo with no prices.

## Anonymisation

The household series are not verbatim. Days in the quietest quarter of overnight grid import had
that import resampled from a typical hour-of-day profile, to attenuate the occupancy signal —
multi-day stretches of collapsed import that read as travel. Export, PV and prices are the
original measurements. `scripts/build_demo_dataset.py` documents the rule, the two sharper rules
that measurement rejected, and — importantly — the limit: the overnight baseload distribution is
continuous, so this makes occupancy inference harder and less confident, not impossible. Treat
the demo as representative real data, not as anonymised data.

Main items:
    DEMO_DIR                 app/data/demo, the committed dataset root.
    DEMO_TITLE               the default workspace title.
    ManifestError            raised when the committed dataset is missing or inconsistent.
    load_manifest()          parse and validate manifest.json.
    materialize(...)         create a workspace from the committed dataset; returns its id.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app import dataset, simconfig_store, workspaces
from app.domain.frames import QUALITY_DTYPE, SeriesFrame
from app.sources import price_store

# The committed dataset lives beside the code, not under the runtime data dir: it is shipped
# content, versioned with the app, the same reasoning as `price_store.PRICE_DATA_DIR`.
DEMO_DIR = Path(__file__).resolve().parent / "data" / "demo"

DEMO_TITLE = "Demo household"

# Recorded on the dataset row so the provenance is visible in the app rather than only in this
# docstring. It is not one of the real source types (`home_assistant`, `csv`, …) precisely so
# that nothing downstream mistakes a demo run for measured data of the user's own.
DEMO_SOURCE_TYPE = "demo"

_MANIFEST_VERSION = 1


class ManifestError(RuntimeError):
    """The committed demo dataset is missing, unparseable, or internally inconsistent.

    Raised rather than falling back to a default, because every failure here means the shipped
    artifacts are wrong — a bug to fix at build time, not a condition to paper over at runtime.
    """


def load_manifest(demo_dir: Path = DEMO_DIR) -> dict:
    """Read and validate `manifest.json`, returning the parsed document."""
    path = demo_dir / "manifest.json"
    if not path.exists():
        raise ManifestError(f"demo manifest not found: {path}")
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(f"demo manifest is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ManifestError("demo manifest is not a JSON object")
    if doc.get("version") != _MANIFEST_VERSION:
        raise ManifestError(
            f"demo manifest version {doc.get('version')!r}, expected {_MANIFEST_VERSION}"
        )
    for key in ("window", "resolution_s", "series", "simconfig"):
        if key not in doc:
            raise ManifestError(f"demo manifest is missing {key!r}")
    return doc


def _window(doc: dict) -> tuple[datetime, datetime]:
    """The manifest's window as tz-aware UTC datetimes, half-open [start, end)."""
    try:
        start = datetime.fromisoformat(doc["window"]["start"])
        end = datetime.fromisoformat(doc["window"]["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"demo manifest has an unreadable window: {exc}") from exc
    if start.tzinfo is None or end.tzinfo is None:
        raise ManifestError("demo manifest window must carry a UTC offset")
    if end <= start:
        raise ManifestError("demo manifest window ends at or before it starts")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _read_series_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse one `timestamp,value,quality` CSV into the three SeriesFrame arrays."""
    if not path.exists():
        raise ManifestError(f"demo series file not found: {path}")
    stamps: list[np.datetime64] = []
    values: list[float] = []
    quality: list[int] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header != ["timestamp", "value", "quality"]:
            raise ManifestError(f"{path.name}: unexpected header {header!r}")
        for lineno, row in enumerate(reader, start=2):
            if not row:
                continue
            try:
                moment = datetime.fromisoformat(row[0]).astimezone(timezone.utc)
                values.append(float(row[1]))
                quality.append(int(row[2]))
            except (IndexError, ValueError) as exc:
                raise ManifestError(f"{path.name}:{lineno}: unreadable row: {exc}") from exc
            # datetime64[s] wants a naive UTC value; the tz is carried by convention (specs §4.4).
            stamps.append(np.datetime64(moment.replace(tzinfo=None), "s"))
    return (
        np.array(stamps, dtype="datetime64[s]"),
        np.array(values, dtype=np.float64),
        np.array(quality, dtype=QUALITY_DTYPE),
    )


def _energy_frames(doc: dict, demo_dir: Path) -> list[SeriesFrame]:
    """Build one SeriesFrame per committed energy series, checking each against the window."""
    start, end = _window(doc)
    frames: list[SeriesFrame] = []
    for spec in doc["series"]:
        index, values, quality = _read_series_csv(demo_dir / spec["file"])
        frame = SeriesFrame(
            name=spec["name"],
            kind=spec["kind"],
            resolution_s=spec["resolution_s"],
            index=index,
            values=values,
            quality=quality,
        )
        if not frame.covers((start, end)):
            raise ManifestError(
                f"{spec['name']}: committed data does not cover the manifest window "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        frames.append(frame)
    if not frames:
        raise ManifestError("demo manifest lists no series")
    return frames


def _price_frame(doc: dict) -> SeriesFrame:
    """Slice the bundled spot prices to the manifest window (see the module docstring)."""
    start, end = _window(doc)
    points = price_store.load_range(start, end)
    if not points:
        raise ManifestError(
            f"the committed spot-price data does not cover {start.date()}..{end.date()}; "
            f"the demo dataset expects it under {price_store.PRICE_DATA_DIR}"
        )
    index = np.array(
        [np.datetime64(p.start.astimezone(timezone.utc).replace(tzinfo=None), "s") for p in points],
        dtype="datetime64[s]",
    )
    values = np.array([p.price_eur_kwh for p in points], dtype=np.float64)
    # Spacing is uniform in the committed files, but derive it rather than assume: a future
    # refresh could ship a different native resolution and a hard-coded 900 would mislabel it.
    steps = np.unique(np.diff(index).astype("int64")) if len(index) > 1 else np.array([])
    resolution_s = int(steps[0]) if steps.size == 1 else None
    spec = doc.get("price_series") or {}
    return SeriesFrame(
        name=spec.get("name", "price_spot"),
        kind=spec.get("kind", "price"),
        resolution_s=resolution_s,
        index=index,
        values=values,
        quality=np.zeros(len(index), dtype=QUALITY_DTYPE),
    )


def materialize(
    *,
    title: str = DEMO_TITLE,
    workspace_id: str | None = None,
    owner_id: str = workspaces.OWNER_ID,
    demo_dir: Path = DEMO_DIR,
) -> str:
    """Create a workspace from the committed demo dataset and return its id.

    Writes, in order: the workspace index row, the config document, then the series and their
    metadata through `dataset.save_dataset()` — the same call the real ingest paths make, so the
    resulting workspace is indistinguishable downstream from a fetched one apart from its
    `source_type`.

    A fresh workspace is created on every call rather than an existing one being overwritten.
    Loading the demo twice gives two independent copies, which is the safe behaviour for a button
    a user may press more than once: nothing they already have can be clobbered.
    """
    doc = load_manifest(demo_dir)
    window = _window(doc)
    frames = _energy_frames(doc, demo_dir) + [_price_frame(doc)]

    wid = workspaces.create(title, workspace_id=workspace_id, owner_id=owner_id)
    simconfig_store.save(
        simconfig_store.from_dict(doc["simconfig"]),
        wid,
        pricing_configured=True,
    )
    dataset.save_dataset(
        frames,
        window,
        DEMO_SOURCE_TYPE,
        [],
        {frame.name: DEMO_SOURCE_TYPE for frame in frames},
        workspace_id=wid,
    )
    return wid
