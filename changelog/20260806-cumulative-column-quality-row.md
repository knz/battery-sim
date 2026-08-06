# Report the suspected-cumulative columns in the data-quality box

## Task specification

`LoadedDataset.warnings` is a persisted `list[dict]` written on every fetch and read nowhere in
`app/` — dead data. One warning code, `CSV_CUMULATIVE_COLUMN`, has no per-interval `QualityFlags`
bit (it is a claim about a whole COLUMN, not about a sample), so it cannot be recomputed from the
flags the data-quality box otherwise derives everything from. Spec §4.2a (05-data-formats) and
§7.3 check 2 (15-data-quality-and-limits) both require the flagged column to be named in the
data-quality box "so the reason survives the run".

Scope: make `app/data_view.panel_data_from` read `dataset.warnings`, filter for
`CSV_CUMULATIVE_COLUMN`, and emit a data-quality row naming the affected column(s). Dutch
translations, sample-data shape parity, tests, and a mutation check are in scope.

## High-level decisions

1. **Only `CSV_CUMULATIVE_COLUMN` is routed through the warnings path.** The other two codes
   (`CSV_GAP_CELLS`, `CSV_DST_AMBIGUOUS_HOUR`) already have flag-derived rows in the box (Gaps,
   Clock change). Routing them here too would double-report the same facts, and the flag-derived
   form is strictly better for them: `_flagged_days`/`_count_flag` are recomputed against the
   RUN's window, whereas a persisted warning describes whatever window was fetched. The minimal
   change that makes `warnings` live is the one code that has no other route.

2. **The row is GATED on presence** (rendered only when at least one column is flagged), unlike
   Gaps / Counter resets / Clock change which always render. Rationale: those three are checks
   that run on EVERY dataset, so "none detected" is a fact about the data. Check 2 only runs on
   the wide-CSV path — a Home Assistant dataset is never examined for a cumulative column at all,
   so "none detected" on an HA dataset would assert a check that never ran. The template already
   has this pattern for `price_warning` and `load_warning` (computations that may not have run).

3. **Rendered as a warning alert, not a plain row.** §4.2a is explicit that the accepted cost of
   flagging-not-refusing is that a user who proceeds with a genuine register "gets a confidently
   wrong simulation, and the warning is the only signal they will get". A ⚠ alert matches that
   weight; a quiet grid row does not.

4. **Column names travel as literal data, not as a msgid.** They are user data (an uploaded
   file's header row). The sentence is a `(msgid, params)` pair; the joined, de-duplicated,
   sorted column list is a param, following the same convention `coverage`'s `dates` and `dst`'s
   `days` already use (see `_fmt_date`'s docstring). Jinja autoescaping in `_msg.html` is what
   makes them safe to render.

5. **Robustness:** the filter tolerates non-dict entries, unknown codes, and a missing/blank
   `column` key. A persisted list can carry shapes this code did not write, and one bad row must
   not take down the whole panel.

## Files modified

- `app/data_view.py` — new `_cumulative_columns(warnings)` helper; `quality["cumulative"]`
  emitted only when non-empty; module docstring and `Main items` updated.
- `app/templates/_data_quality.html` — new conditional ⚠ alert block; header comment updated.
- `app/sample_data.py` — sample `quality` gains the same key (omitted/None, matching the HA
  sample it demos) so the shape stays compatible.
- `tests/test_data_summary.py` — new tests: named column, multiple columns, de-duplication,
  clean case (key absent), unrecognised code ignored, malformed entry (missing `column`).
- `app/locales/messages.pot`, `app/locales/{nl,en}/LC_MESSAGES/messages.po`/`.mo` — new msgids
  and Dutch.

## Rationales and alternatives rejected

- **Route all three CSV warning codes through `warnings`.** Rejected: `CSV_GAP_CELLS` and
  `CSV_DST_AMBIGUOUS_HOUR` already have flag-derived rows, so this would double-report. It would
  also be a regression in accuracy — `_count_flag` / `_flagged_days` recompute against the run's
  window, a persisted warning describes the fetch's.
- **Reuse the existing `none detected` msgid for a clean branch.** Rejected on meaning, not on
  wording: see decision 2. The msgid would have been correct English for a check that ran and
  found nothing; the problem is that on an HA dataset the check never ran.
- **A plain grid row beside Gaps / Counter resets.** Rejected: an alert matches the weight §4.2a
  assigns this ("the only signal they will get"), and a conditional grid row would leave a gap in
  the two-column layout when absent.
- **Escape the column name in `data_view`.** Rejected: escaping belongs at render time, and
  `_msg.html` already does it — the translated msgid becomes `Markup`, whose `__mod__` escapes
  each substituted raw value exactly once. Pre-escaping here would double-escape.

## Obstacles and solutions

- A `-k cumulative` pytest selector silently deselected the two robustness tests, because their
  names lacked the word — two mutation runs reported "5 passed" against a mutant that was in fact
  fatal. Renamed both to `test_panel_cumulative_row_*` and re-ran; both then failed as intended.
  (The near-miss is itself the argument for the rename: a selector-shaped coverage gap.)
- `pybabel update` re-wrapped one pre-existing Dutch msgstr (the drawer's small print) at its own
  line width. Text-identical; verified by reading the diff rather than assumed.

## Verification

- `pytest tests/test_data_summary.py tests/test_workspace_data.py tests/test_i18n.py
  tests/test_no_english_leakage.py -q` → **354 passed**.
- Whole suite (minus `test_smoke.py`) → **1665 passed, 25 skipped**.
- Re-extract after the update is byte-identical modulo `POT-Creation-Date` (verified by diff).
- `nl` catalog: 0 untranslated, 0 fuzzy. Dutch verified by RENDERING both plural forms through the
  real `_msg.html` macro, not by reading the `.po`.
- Escaping verified by rendering the whole `_data_quality.html` macro with a column named
  `<Verbruik & co>`: comes out `&lt;Verbruik &amp; co&gt;` — escaped once, in both locales.

### Mutation testing

Five mutations, each restored with `cp` from the scratchpad backup (never git):

| Mutation | Tests that died |
|---|---|
| warning `code` compared against `"MUTATION_MATCHES_NOTHING"` | 4: names_the_flagged_column, lists_several_columns, lists_each_column_once, renders_through_the_real_template |
| `columns="MUTATION"` (names dropped, sentence kept) | the same 4 |
| presence gate replaced with `if True:` | 1: is_omitted_when_nothing_is_flagged |
| column filter removed (`code` accepted unconditionally) | 1: ignores_warning_codes_it_does_not_recognise |
| `out.add(str(w.get("column")))` — no validation of the value | 1: survives_a_malformed_persisted_warning |

`grep -rn MUTATION app/ tests/` is empty after restoration.

## Current status

Complete and uncommitted. Not done, and out of scope: the other two warning codes stay unread
(they have flag-derived rows); nothing reads `warnings` outside `data_view`; and the CSV path's
end-to-end "upload a monotonic column, then see it named in the box" flow is not covered by a
route-level test here — the concurrent agent owns `tests/test_upload_routes.py` and
`tests/test_csv_binding_reify.py`, and the latter already pins that the warning reaches
`loaded.warnings`, which is where this row picks it up.
