# ENTSO-E NL day-ahead price extraction

## Task Specification

Write a script that extracts NL (Netherlands) day-ahead prices from the raw ENTSO-E
dumps in `external_data/entso-e/` into files usable as an **alternate data source** in
the application. Time granularity changed over the years; keep the finest granularity
available.

## Source data survey (measured)

`external_data/entso-e/` — 49 files, `YYYY_MM_EnergyPrices_12.1.D_r3.1.csv`,
2022-07 through 2026-07, 429 MB total. **Tab-separated**, header:

```
InstanceCode  DateTime(UTC)  ResolutionCode  AreaCode  AreaDisplayName
AreaTypeCode  AreaMapCode  ContractType  Sequence  Price[Currency/MWh]
Currency  UpdateTime(UTC)
```

NL selection: `AreaMapCode == "NL"`, `AreaTypeCode == "BZN"`,
`AreaCode == 10YNL----------L`, `ContractType == "Day-ahead"`, `Currency == EUR`.
Only one NL bidding zone appears in the corpus (checked several months) — no
ambiguity between multiple NL area rows.

Granularity transition (measured, not assumed):
- 2022-07 … 2025-08: `PT60M` only.
- 2025-09: **both** — 718 PT60M rows (through `2025-09-30 21:00 UTC`) and 8 PT15M rows
  (from `2025-09-30 22:00 UTC`). No timestamp collision; the two regimes abut cleanly at
  the 15-minute switchover (00:00 local CEST on 1 Oct 2025).
- 2025-10 onward: `PT15M` only.

So "keep the finest granularity" needs no downsampling and no overlap-resolution in
practice — but the script still resolves per-timestamp collisions by preferring the
finest resolution, so the rule is enforced rather than assumed from this corpus.

## High-Level Decisions

- **Reuse the existing committed price-store format** rather than inventing one.
  `app/sources/price_store.py` already defines: one CSV per calendar year,
  `app/data/spot_prices/NL-YYYY.csv`, header `timestamp,price_eur_kwh`, ISO-8601 UTC
  interval start, price already converted to EUR/kWh, sorted and de-duplicated, native
  interval preserved (never resampled — specs §6.2 owns resampling). The raw ENTSO-E
  data maps onto this exactly; only the ingest path differs.
- **Write to a separate directory, not over the existing dataset.** The current
  `app/data/spot_prices/` is produced by `scripts/fetch_spot_prices.py` from the
  energy-charts API. The ENTSO-E extract is an *alternate* source, so it must not
  clobber the API-derived one; the two can then be compared.
- Unit conversion: `Price[Currency/MWh] / 1000` → EUR/kWh, formatted `%.6f` to match
  `price_store._fmt_price`.

## Requirements Changes (user answers, mid-conversation)

Three decisions taken by the user after the survey:

1. **Output** → `app/data/spot_prices_entsoe/`, same `NL-YYYY.csv` naming, separate from
   the API-derived `app/data/spot_prices/` so neither clobbers the other.
2. **Resolution column** → yes, add it. This *diverges* from the existing 2-column
   `price_store.py` format, so that reader cannot be reused; a sibling reader is needed
   (see below). Chose `resolution_s` in **seconds** (3600 / 900) over the raw ENTSO-E
   `PT60M` / `PT15M` tokens, to match `SeriesFrame.resolution_s` used downstream — no
   token parsing at read time.
3. **Scope** → script *plus* runtime source wiring, so the extract is selectable in the
   app in this same change.

## Files Modified

- `scripts/extract_entsoe_prices.py` (new) — streaming extractor over the raw TSVs.
- `app/sources/entsoe_store.py` (new) — reader/writer for the 3-column format.
- `app/sources/entsoe.py` (new) — `EntsoeSource`, a backend_load source for `price_spot`.
- `app/sources/registry.py` — register `EntsoeSource`.
- `tests/test_sources.py` — extractor, store round-trip, and registry tests.
- `app/data/spot_prices_entsoe/NL-{2022..2026}.csv` (generated output).

## Rationales and Alternatives

- **Sibling store rather than extending `price_store.py`.** The added third column breaks
  `price_store._read_file`'s strict header check. Extending that module to accept both
  shapes would make one reader serve two formats and put a conditional in the hot read
  path; a separate `entsoe_store.py` keeps each format's reader simple and leaves the
  existing committed dataset's contract untouched.
- **No API bridge in `EntsoeSource`.** Unlike `EnergyChartsSource`, this source is backed
  by a static raw corpus with no live endpoint behind it, so a window extending past the
  last extracted interval just returns what exists rather than fetching.
- **Finest-granularity as an enforced rule, not an assumption.** The corpus as measured
  has no timestamp collisions between PT60M and PT15M, so no resolution conflict actually
  arises today. The extractor still resolves collisions by preferring the finest
  resolution, so a future re-dump that does overlap is handled rather than silently
  picking whichever row was read last.

## Known Limitation (carried, not introduced)

`ingest.price_frame` infers a single modal `resolution_s` per frame and has no per-row
resolution parameter. So for a window straddling the 2025-09-30 switchover the on-disk
`resolution_s` column is correct but the resulting frame still collapses to one value —
the same limitation already documented at `app/sources/energy_charts.py:134`. Making the
column authoritative belongs to the specs §6.2 grid-selector work. The column is still
written because it makes the data correct at rest.

## Verification

Extraction over the full 49-file corpus, ~4 s, streaming (no file read whole):

| year | rows | resolutions | expected |
|------|------|-------------|----------|
| 2022 |  4416 | 4416×3600s          | 184 days × 24 h (Jul–Dec) ✓ |
| 2023 |  8760 | 8760×3600s          | 365 × 24 ✓ |
| 2024 |  8784 | 8784×3600s          | 366 × 24 (leap) ✓ |
| 2025 | 15390 | 6550×3600s, 8840×900s | hourly to 09-30 21:00Z + quarter-hourly after ✓ |
| 2026 | 19864 | 19864×900s          | partial year, corpus ends 2026-07 |

Every year matches interval arithmetic exactly, including the 2025 split. Zero gaps and zero
resolution collisions reported.

**Cross-validation against the independent Energy-Charts dataset** (the strongest check
available, since the two origins share no code or transport): on 2023, 2024 and 2025 the two
agree on **every interval, with max delta 0.000000** — 32,934 rows, no discrepancies. For 2026
the ENTSO-E extract has 192 extra quarter-hours (two days) because the raw dumps run past the
last API fetch; all 19,672 shared intervals match exactly.

Test suite: 791 passed, 2 skipped (both pre-existing skips). `tests/test_sources.py` grew from
21 to 35 tests.

## Obstacles and Solutions

- 429 MB of raw input across 49 files → stream line-by-line, never load a whole file.
- Raw dumps are CRLF-terminated; stripping only `\n` left a trailing `\r` on the last column and
  the header check caught it on the first run → strip `\r\n` throughout. The strict header
  check earning its keep immediately is the reason it was written.
- Two existing registry tests asserted the exact source list for `price_spot` → updated; the
  bracket-slot test needed no change and now also confirms the new source correctly declines
  slots it cannot fill.

## Translations (not in the approved plan; added on discovery)

The new source's descriptor `label` and `blurb` are user-visible in the source-picker drawer,
and the app ships a Dutch UI. Left alone they would have rendered as English text in a Dutch
drawer. Following the workflow documented in `babel.cfg`:

- `app/sample_data.py` — added the two new strings to `_SOURCE_STRINGS`. Descriptor strings
  live in `app/sources/*.py` where pybabel does not discover them, so that list is what gets
  them into the catalog; its comment says to keep it in step with the descriptors.
- Ran extract → update (`--no-fuzzy-matching`, required per babel.cfg) → compile; wrote the
  Dutch translations by hand, matching the existing entry's register (informal *je*, "NL
  day-ahead spotprijzen" kept untranslated) and the `en` catalog's explicit-identity
  convention. Verified both locales resolve at runtime; no `#, fuzzy` entries introduced.

## Decisions taken without asking (flagged for review)

- **`external_data/` added to `.gitignore`.** 429 MB of raw all-Europe dumps, of which only the
  extracted NL slice is needed and committed. Re-downloadable from the ENTSO-E platform. Easy
  to reverse if the raw corpus should be committed after all.
- **Registration order**: Energy-Charts before ENTSO-E, so the live-bridging source stays the
  default for windows reaching the present.

## Specs updated

Three spec files described the price slot as having exactly one preset source:

- `specs/02-ux-wireframes.md` — the slot now offers two preset sources; notes why both exist.
- `specs/06-home-assistant-ingestion.md` — retitled the section, added an ENTSO-E subsection,
  and disambiguated the "one outbound request" paragraph (only Energy-Charts makes it).
- `specs/08-architecture.md` — added `EntsoeSource` to the source list and corrected the
  "needs no configuration" paragraph to cover both.

`specs/15-data-quality-and-limits.md` needed no change: its egress note is specifically about
the Energy-Charts fetch, and this source adds no egress.

## Current Status

Complete. Extractor, store, source, registration, tests and spec updates all landed; output
files generated and cross-validated. Nothing committed to git — the working tree holds the
changes for review.

Possible follow-ups, none blocking and none decided:

- The per-row `resolution_s` is still write-only (see the limitation above); consuming it
  belongs to the §6.2 grid-selector work.
- The two datasets now overlap almost entirely. Whether to keep both long-term, or treat
  ENTSO-E as the primary and Energy-Charts as the live tail, is worth deciding once the grid
  selector can use the resolution column.
- 2026 coverage differs by two days between the sources; re-running
  `scripts/fetch_spot_prices.py` would close that if the parity matters.
