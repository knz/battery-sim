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

## Independent verification (orchestrator, not the author)

Reviewer ≠ author, so the central claim was re-mutated rather than taken from the report above.
The mutation chosen was sharper than the author's: instead of stopping the verdict from reaching
the row, `_upload_json` was made to emit `cumulative_columns` **only when `summary is not None`**
— i.e. POST-only, which is precisely the failure mode decision 2 exists to prevent. Exactly one
test failed, `test_the_list_route_reports_the_verdict_too`, with `[None] == [['Meterstand']]`.
That is the LIST-route assertion doing its job. Restored with `cp`; no `MUTATION` markers remain.

Also checked, because the two agents ran `pybabel` concurrently over each other's edits: a fresh
`pybabel extract` reproduces `messages.pot` byte-for-byte apart from the `POT-Creation-Date`
header, so the shared-catalog merge is clean rather than one run having clobbered the other. Both
new msgids are present with non-fuzzy Dutch, and the obsolete rejection message moved to a `#~`
block as expected.

Combined-tree results after both changes landed: 631 targeted backend tests pass (ten suites) and
58 Playwright smoke tests pass. The `test_i18n.py` failure the DST agent reported as a possible
flake passes here — it was reading the tree while the other agent was mid-edit on the drawer
strings, which is the likely explanation, though that was not proven.

Committed as `a844c46` together with the DST data-quality note
([20260806-dst-ambiguous-quality-note.md](20260806-dst-ambiguous-quality-note.md)).

## Specification amended (follow-up, 2026-08-06)

The user's prompt, verbatim:

> amend the spec

Raised as an open item after the code landed: "rejected on selection" no longer described the
intended behaviour, so the specs contradicted the shipped code. Four sites in `docs/specs/`
carried the stale claim, and all four were corrected. Per `docs/specs/AGENTS.md`, the user's
original prompts are recorded here.

1. **`05-data-formats.md` §4.2a** — the normative statement. "Cumulative meter registers are
   rejected, not differenced" → "warned about, not differenced and not refused". Records why the
   refusal was wrong (monotonicity is a property of the *window*, not of the data's kind, so
   partial-day data trips it), states the accepted cost, and notes that the P1-register shape
   still cannot be used *correctly* — the flag is what says so. Also names the better
   discriminator that remains unbuilt: total-against-window-length.
2. **`02-ux-wireframes.md`** — the user-facing description. "**rejected** on selection" →
   "**flagged**", plus what the user actually sees (small print, Confirm stays enabled) and that
   the warning explains its own false-alarm case so a user with valid monotonic data knows to
   ignore it.
3. **`15-data-quality-and-limits.md` §7.3 check 2** — "it is rejected in the drawer" → flagged,
   not rejected, and reported in the box afterwards. Describes the check as a *suspicion rather
   than a verdict*.
4. **`15-data-quality-and-limits.md`, the paragraph after the checks** — a second-order
   correction found while editing check 2, not in the original list. It said "A failure in either
   place … the run is not attempted", which check 2 no longer satisfies. Now distinguishes the
   blocking failures (unreadable file, non-numeric column) from the two non-blocking outcomes
   (October ambiguous hour, suspected cumulative column), with the reason they differ: neither is
   a defect the user can fix by picking something else.
5. **`16-validation-harness.md` fixture 22** — the most consequential, since its assertions are
   what a future test encodes. Was: assert the column "is rejected in the drawer" and
   `SOURCE_CONFIGURED` has not fired. Now: assert the warning shows, Confirm stays enabled, the
   binding is accepted, the run completes, and the flagged column is named in the data-quality
   box. Two assertions were **added** rather than merely inverted: that the values pass through
   **undifferenced** (silently differencing them is the one thing this format must never do, and
   nothing else in the harness pins that down), and that the non-numeric column *still is*
   rejected — so relaxing one check cannot quietly relax the other.

§7.3 check 1's existing claim that the October flag "is reported here, in this box, naming the
affected day" needed no edit: it was aspirational when written and is now accurate, which is what
the DST note in the same commit implemented.

## Current status

Code and specs complete and committed. Note for a reviewer: `_looks_cumulative` is called from
`app/main.py` despite the leading underscore, which its docstring now records. If that bothers
anyone the fix is to rename it, not to duplicate the threshold.

Not scheduled, and worth a decision rather than a default: fixture 22's new undifferenced-values
assertion is specified but no test implements it yet. The existing Playwright test covers the
warning appearing and Confirm staying enabled; the pass-through-undifferenced claim is currently
pinned only at the domain layer (`test_csv_wide.py`), not end-to-end.
