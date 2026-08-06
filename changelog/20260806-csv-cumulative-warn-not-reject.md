# CSV wide format: cumulative column becomes a warning, not a rejection

## Task specification

Behaviour change requested by the user, verbatim:

> I'm ok with a warning in small letters that warns the user the data may be
> cumulative, but don't enforce and let the user proceed anyway.

Today `column_frame` raises `CsvFormatError("cumulative_column")` when a selected wide-CSV
column never decreases, so the fetch fails and the binding cannot be used. It must become a
non-blocking warning the user can ignore, surfaced as small print next to the column picker
in the CSV drawer.

## Rationale

`app/domain/csv_wide.py` documents a real false positive in the detector: a monotonically
rising partial-day PV export (morning-only, or a window ending at solar noon) is refused even
though it is valid per-interval data — "That is wrong and it will happen." The user has
decided that a false positive costing a line of small print is a better trade than blocking
valid data. The user was told, and accepted, that proceeding with a genuine meter register
produces a confidently wrong simulation.

`_looks_cumulative` and its thresholds are unchanged. Only the consequence changes.

## High-level decisions

1. **Detector untouched.** Same three-part threshold; only `column_frame`'s reaction changes,
   from `raise` to a `warnings` entry with code `CSV_CUMULATIVE_COLUMN`, following the shape
   of the existing `CSV_GAP_CELLS` / `CSV_DST_AMBIGUOUS_HOUR` entries.
2. **The verdict is persisted, not merely returned by the upload POST.** The drawer's file
   cache is filled from the uploads LIST route, not from the POST response, so a
   POST-only verdict would appear right after upload and vanish on reload.
3. **New nullable `uploads` column** holding a JSON list of the column names that look
   cumulative. NULL means "not computed" (rows written before this change), so no backfill is
   needed. Deliberately *not* stored inside `columns_json`, which has a documented contract
   as a plain `list[str]`.
4. **Small print, never a block.** The picker annotation does not touch
   `updateConfirmEnabled`; Confirm stays enabled for a flagged column.

## Files modified

- `app/domain/csv_wide.py` — `column_frame` warns instead of raising; module docstring and
  `column_frame` docstring rewritten to describe warn-not-reject and record why;
  `CsvFormatError("cumulative_column")` removed.
- `app/uploads.py` — new `cumulative_columns_json` column in the schema, in `_COLUMNS` and
  in `_row_to_upload`; `create()` accepts the verdict list.
- `app/db.py` — migration adding the column to an existing database.
- `app/main.py` — upload POST computes the verdict and stores it; `_upload_json` exposes it
  for both the POST and the LIST payloads.
- `app/templates/workspace_data.html` — two new `drawer_i18n` strings and the small-print
  element next to the column picker.
- `app/static/ha_fetch.js` — shows/hides the small print on column change, file change and
  drawer open.
- `locale/nl/LC_MESSAGES/messages.po` (+ `.mo`) — Dutch translations.
- `tests/test_csv_wide.py`, `tests/test_csv_source.py`, `tests/test_csv_binding_reify.py`,
  `tests/test_uploads.py`, `tests/test_upload_routes.py`, `tests/test_smoke.py` — tests
  updated from "rejects" to "warns and succeeds", plus new coverage.

## Obstacles and solutions

- `csv_source.CsvSource.load` recounts warnings from the SLICE's quality bits and discards
  `column_frame`'s. There is no quality bit for "cumulative" (it is a per-column claim, not a
  per-sample one), so the new warning would have been silently dropped on every fetch. Fixed by
  carrying that one code through explicitly rather than recounting it.
- `_cumulative_columns` in the upload route must not fail the upload on a non-numeric column:
  §4.2a defers the numeric check to selection. It swallows `CsvFormatError` per column and skips
  that column's verdict.
- `pybabel extract` regenerated the catalogs while a parallel agent was editing the same files.
  Their two new msgids ("Clock change", the DST-ambiguous plural) were already translated in the
  working tree and `pybabel update --no-fuzzy-matching` preserved them, so the merged catalogs
  carry both agents' strings.

## New strings

- `csv_cumulative_warning` (new): "This column never decreases, so it may be a meter reading (a
  running total) rather than the amount used in each interval. If it is, the results will be
  wrong. You can continue anyway — a column that only rises across the whole file, such as solar
  in a morning-only export, is flagged here too."
- `csv_err_cumulative_column` (removed): the server can no longer emit code `cumulative_column`,
  so the error-table entry and its msgid are gone. Also removed from `CSV_ERROR_KEYS` and
  `CSV_ERROR_DETAILED` in `ha_fetch.js`.

## Migration

`uploads._ADDED_COLUMNS` + `uploads._migrate`, copying `dataset._migrate`: `PRAGMA table_info`,
then `ALTER TABLE uploads ADD COLUMN cumulative_columns_json TEXT` when absent. Run from
`_connect` after the schema script and outside any `with` block, so the DDL autocommits rather
than taking the write lock on every connect. Verified by
`test_an_older_table_without_the_verdict_column_is_migrated`, which builds the pre-change table by
hand, inserts a row into it, and then reads through the module's own API — this fails with "no
such column" without the migration, and the pre-existing row reads back with
`cumulative_columns is None`.

## Mutation testing

1. `_looks_cumulative` forced to `return False` — 12 tests failed across all four layers
   (`test_csv_wide.py` ×6, `test_csv_source.py` ×2, `test_csv_binding_reify.py` ×1,
   `test_upload_routes.py` ×3).
2. `create`'s `cumulative_json` forced to `None` (verdict never reaches the row) — 5 tests failed
   (`test_uploads.py` ×3, `test_upload_routes.py` ×2), plus the new Playwright test.

Both restored with `cp` from the scratchpad; `grep -rn MUTATION app/ tests/` empty afterwards.

## Test results

- The nine backend suites: 512 passed (505 before the new tests were added).
- `tests/test_smoke.py`: 58 passed (was 57).
- Whole suite minus smoke and the parallel agent's `test_data_summary.py`: 1613 passed, 25 skipped.

## Current status

Complete, not committed. Note for a reviewer: `_looks_cumulative` is called from `app/main.py`
despite the leading underscore, which its docstring now records. If that bothers anyone the fix is
to rename it, not to duplicate the threshold.
