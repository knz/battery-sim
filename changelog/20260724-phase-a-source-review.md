# Phase A backend data-source layer — critical review

## Task Specification
Critical, read-only code review of the "Phase A" backend data-source layer on branch
feat/pending-affordance-backend. No code changes; findings only. Focus: bridge/merge
logic in energy_charts.py, EUR/MWh->EUR/kWh conversion, mixed native resolution,
purity/testability, DataSource Protocol, price_store CSV format, repo conventions,
test quality, seed script.

## Scope / files
- app/domain/sources/{base,home_assistant,energy_charts,energy_charts_api,price_store,registry,__init__}.py
- scripts/fetch_spot_prices.py
- tests/test_sources.py
- app/data/spot_prices/NL-2023.csv .. NL-2026.csv
Context: app/domain/{ingest,frames,series_vocab}.py, specs 06/08, AGENTS.md

## Findings (summary)
- Layering: I/O (network, file, wall clock) placed under app/domain/sources; spec 08 §5.1/§5.2
  say domain is pure (no HTTP/DB/clock). Adapters listed as CsvLoader/EntsoeClient. Should-fix.
- Mixed-resolution straddle: infer_resolution_s returns the modal spacing (e.g. 900s) for a
  window straddling the 2025-09-30 hourly->15min transition; the hourly half is then mislabelled.
  Latent correctness issue for downstream; no test covers it. Should-fix / document.
- Committed data transition is 2025-09-30T22:00->22:15, not 2025-10-23 as the review brief stated.
- Merge/boundary logic: verified correct (on-disk wins overlap, pre-window filtered, no dup/drop).
- Unit conversion: applied once in parse_price_response; CSV stores converted value; not doubled.
- bzn path traversal theoretically possible (year_path/glob) but bzn never user-controlled. Nit.
- tests pass (14). Missing: straddle-transition test, mixed-resolution assertion.

## Current Status
Review complete. Verdict: no hard blockers; two should-fix items (layering, mixed-resolution).
