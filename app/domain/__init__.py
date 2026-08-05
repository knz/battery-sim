"""Pure domain layer for the Home Battery Simulator (docs/specs/08-architecture.md §5.1–5.2).

Arrays in, arrays and value objects out — no HTTP, no database, no clock. This is the part
the validation harness (docs/specs/16-validation-harness.md) tests against hand-computed fixtures,
and it is deliberately import-light: only numpy and the standard library.

Modules in this increment (the data-import path only — no simulation yet):
    frames      SeriesFrame, QualityFlags — the normalised per-series representation (§4.4).
    ingest      raw HA statistics rows → SeriesFrame: cumulative→delta, resets, gaps,
                native-resolution inference (§6.1), and price row handling (§4.3).
    normalize   grid selection and per-series reconciliation metadata for panel ① (§6.2).
"""
