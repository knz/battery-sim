# CSV field delimiter and per-cell decimal separator

## Task specification

The user asked what it would take to auto-detect the CSV delimiter and decimal
separator, then — after seeing the current state — specified the design directly.

### Original prompts, verbatim

> what would it take to auto-detect the csv delimiter and decimal separator?

Then, after a scoping report:

> i'd like the format to be handled as follows:
> - ask for the separator using a radio select alongisde the timestamp radio during upload (choices: ',' ';' 'spaces' 'tabs')
> - during parsing, properly handle double quotes (don't detect separators inside double quotes)
> - after column splitting (taking into account double quotes), auto-detect the decimal separator (can be either '.' or ',' -- reject when both are present)

Then, in answer to two clarifying questions (how "spaces" should be defined,
and at what scope "both are present" applies):

> regarding point 2: let's drop the "spaces" option for now, keep just comma semicolon and tab
> regarding point 3: "reject when both are present" is within the scope of 1 cell.
>
> See the file ~/voorbeeld.csv -- it mixes both periods and commas as decimal separators. we want to support that. the decimal separator is not a property of an entire file or entire column.

### Resulting scope

1. A field-delimiter radio group in the upload dialog, beside the existing
   timezone radio. Three choices: comma, semicolon, tab. ("Spaces" was
   considered and explicitly dropped — see below.)
2. Double quotes honoured during tokenization: a delimiter inside a quoted
   cell does not split it.
3. Decimal separator detected **per cell**, either `.` or `,`, rejecting a
   cell that contains both. Explicitly *not* a per-file or per-column
   property.

## Findings from the current state

Established by reading the code before any design work:

- The sole tokenizer for wide CSV is `csv.reader` at `app/domain/csv_wide.py:390`,
  with no `delimiter=` argument, so the stdlib comma default applies. There is
  no `csv.Sniffer` anywhere in the repo, and the delimiter is not stored on the
  `Upload` row, in the binding, or in config.
- Requirement 2 is **already satisfied**. `csv.reader` is an RFC4180
  tokenizer and honours double quotes today; it will continue to when passed a
  `delimiter=`. The work is to confirm and pin this under each delimiter, not
  to build anything.
- Value cells are kept as strings by `parse_wide_csv`. They become floats only
  in `parse_column_values` (`csv_wide.py:562`), through a bare `float(text)` at
  `:608`. That is the single point the decimal rule has to change.
- The file is parsed twice — once at upload (`app/main.py:2158`) and again on
  every fetch (`app/sources/csv_source.py:505-509`). The two parses must agree,
  so the chosen delimiter has to be persisted on the `Upload` row.
- The delimiter is **never stated normatively** in the specs. `docs/specs/05-data-formats.md:156`
  mandates the `.` decimal separator, and the example block is comma-separated,
  but no sentence says "comma-separated". So the delimiter work adds a rule
  where none was written; the decimal work contradicts one that was.

## The example file

`~/voorbeeld.csv`, 96 lines, header `DatumTijd,Import,Export,Opwek`,
comma-delimited, timestamps like `25-08-2024 0:00:00` (single-digit hour, which
`%H` via `strptime` accepts).

It mixes conventions row by row, and the pattern is not arbitrary: every
dot-decimal cell is unquoted (`0.56`, `0.13`), and every comma-decimal cell is
quoted (`"1,9"`, `"1,72"`, `"0,55"` — twelve distinct values). No cell contains
both separators. Every row has exactly four fields under comma tokenization,
because the exporter quoted precisely those cells that would otherwise split.

Two consequences shaped the design:

- The file needs no delimiter selection, and tokenizes correctly today. The
  only thing blocking it is the `float()` call. So the decimal half alone
  unblocks the file in front of us; the delimiter half is independent.
- Because comma decimals arrive quoted, per-cell detection only ever has to
  help cells that arrived as a single field.

## Decisions

### D-DELIM-SCOPE: the decimal separator is a per-cell property

The user was explicit. This is cheaper than it sounds *because* of the
reject-if-both rule: each cell is independently unambiguous, so there is no
file-wide or column-wide state, no thousands-separator inference, and no
ordering dependency. It is a local transformation inside the existing
conversion loop.

The cost is that `1.234,56` (European thousands + decimal) is rejected rather
than interpreted. That is the conservative reading and it forecloses the silent
1000x error; it was accepted deliberately, not overlooked.

### D-DELIM-SPACES: whitespace-delimited files are out of scope for now

Raised because "spaces" is underdetermined — a single space, or a run? Space-
aligned exports nearly always use runs, and `csv.reader` cannot collapse runs
(its delimiter is one character), so supporting it would mean a second
tokenizer with hand-written quote handling. The user dropped the option rather
than pay for that now.

### D-DELIM-GUARD: the row-length guard must survive intact

`csv_wide.py:443-455` rejects rows whose field count differs from the header.
Its comment records that the *long* direction is deliberate: an unquoted
decimal-comma file splits `0,412` into two cells, making every row one cell too
long, and reading it would be wrong by a factor of a thousand.

Per-cell detection helps only quoted comma cells, which arrive as one field.
Unquoted comma decimals must still be rejected by the row-length guard.
Accepting `"1,9"` must never license accepting bare `1,9`, and a regression
test has to pin that.

## Files modified

### `app/uploads.py` — preparatory refactor of the column list (no behaviour change)

Done ahead of adding the `delimiter` column, to remove one way that addition
could go wrong silently.

Before, three things had to be hand-kept in step: `_COLUMNS`, a single
comma-separated SQL string used as both the SELECT list and the INSERT column
list; `_row_to_upload`, which reads the row positionally as `row[0]..row[10]`;
and the INSERT's `VALUES (?, ?, …)`, a hand-counted literal of eleven
placeholders with a matching hand-ordered value tuple.

Of those, the placeholder *count* fails loudly — a miscount raises
`sqlite3.ProgrammingError` on the first insert. The *order* fails silently: a
value tuple out of step with the column list writes one field's value into
another field's column, and nothing reports it. That asymmetry is why the count
was worth designing away even though it was the less dangerous of the two.

`_COLUMNS` is now a `tuple[str, ...]` of column names — the canonical
definition — with `_COLUMNS_SQL = ", ".join(_COLUMNS)` and
`_PLACEHOLDERS = ", ".join("?" * len(_COLUMNS))` derived from it. The INSERT is
built from both, so its placeholder count is a consequence of the tuple rather
than a literal that can disagree with it.

What this does **not** fix, and the docstrings say so explicitly: the positional
indices in `_row_to_upload` and the order of the value tuple in `create` are
still hand-synced with the tuple, and nothing checks either. The refactor
narrows the hand-maintained set from three items to two; it does not make the
remaining two safe.

The generated SQL was verified byte-identical before and after — all three
statements (`INSERT`, `get`'s SELECT, `list_for`'s SELECT) printed from the
module and diffed, empty diff. `tests/test_uploads.py` and
`tests/test_upload_routes.py` pass (104), as does `tests/test_csv_source.py`
(44).

Considered and declined: a module-level assertion tying `len(_COLUMNS)` to the
number of fields `_row_to_upload` reads. There is no honest way to count the
latter without inspecting source or calling the function with a probe row, and
`len(_COLUMNS) == len(dataclasses.fields(Upload))` is a coincidence of the
current schema rather than an invariant — it would break the moment a stored
column has no `Upload` field or vice versa, and a false invariant is worse than
none. The order hazard is left to the docstring, where it is now stated plainly.

### The per-cell decimal separator — implemented (requirement 3)

The decimal half of the task, landed independently of the delimiter half.

- `app/domain/csv_wide.py` — new module-level `_decimal_normalised(text,
  column, row)` beside `GAP_TOKENS`, which decides one cell's separator and
  raises the new `mixed_decimal_separator` code itself, so the conversion loop
  stays straight-line. `parse_column_values` calls it between the gap check and
  `float()`. That position is load-bearing in both directions: after the gap
  check so `-` (a gap token) is never reinterpreted, and before `np.isinf` —
  which is unaffected, since a substitution can neither create nor remove an
  infinity. Two messages amended because they had become false:
  `row_length_mismatch` no longer claims the format "needs a dot" (it now
  points at the missing quoting), and `non_numeric_value` now says a dot *or* a
  comma, but not both. The module docstring gains a section on why detection is
  per cell, quoting the `voorbeeld.csv` rows that force it, and
  `parse_column_values`'s docstring records that the timestamp column needs no
  exemption because it never reaches that function — `record[0]` goes to
  `_parse_timestamp` and only `record[1:]` becomes cells. Verified, and written
  down so nobody adds redundant dead code later.
- `app/templates/workspace_data.html` — new `csv_err_mixed_decimal_separator`
  string; `csv_err_non_numeric_value` amended to match the server.
- `app/static/ha_fetch.js` — `mixed_decimal_separator` added to
  `CSV_ERROR_KEYS` and to `CSV_ERROR_DETAILED` (its server message names the
  cell and the column, which is that list's stated criterion).
- `app/locales/messages.pot`, `nl/…/messages.po`, `en/…/messages.po` and the
  compiled `.mo`s — extract/update/compile. Dutch hand-written for both the new
  string and the re-worded one, whose old translation was dropped with its
  msgid.
- `docs/specs/05-data-formats.md` — §4.2a's values row rewritten: `.` or `,`
  detected per cell, both-in-one-cell rejected, no thousands separator, and why
  the separator is not a property of the file or of a column. The column-level
  rejection list gains the both-separators cell. §4.2's narrow format is a
  different, unimplemented path and was left alone.
- `docs/specs/16-validation-harness.md` — new fixture **22b**, added rather than
  folded into 22 because 22's subject is recoverability and this is a format
  claim.
- `tests/test_csv_wide.py` — a per-cell section: quoted `"1,9"`, bare `0.56`,
  alternating cells within one column, a variant no per-column rule could
  satisfy, both-separator rejection with `.row` naming the file line,
  `1,234,567` falling through to `non_numeric_value`, the edge spellings, gaps
  and infinities unaffected, a comma in the timestamp column, the paired
  row-length regression, and an end-to-end test over the real file. The
  obsolete `test_decimal_comma_is_rejected_with_the_dot_rule_named` was
  replaced by it — its input is now the positive case.
- `tests/fixtures/wide_mixed_decimal_separators.csv` — **new**, along with a new
  `tests/fixtures/` directory (there was none). A verbatim copy of the user's
  `~/voorbeeld.csv`: rewriting it by hand would lose the property under test,
  which is precisely *which cells the exporter chose to quote*.
- `tests/test_csv_source.py` — one case, because the adapter is the only place
  the bytes go to disk and come back, and the quoting is what carries the
  comma cells.

#### Obstacles

- An existing test asserted the old behaviour by name
  (`test_decimal_comma_is_rejected_with_the_dot_rule_named`) — replaced.
- `test_a_row_with_too_many_cells_is_rejected_not_silently_truncated` asserts
  the phrase `"decimal separator"` appears, so the reworded
  `row_length_mismatch` message had to keep it.
- `pybabel update` rewrapped one unrelated Dutch plural string; content
  unchanged. The rest of the `.pot` diff is the two intended strings plus
  `POT-Creation-Date`.

## Current status

Requirement 3 (the per-cell decimal separator) is implemented and tested.
Requirements 1 and 2 (the delimiter radio and its persistence) are still to do;
`app/uploads.py` has had its preparatory refactor.

Verification for the decimal half: `tests/test_csv_wide.py
tests/test_csv_source.py tests/test_upload_routes.py tests/test_i18n.py
tests/test_no_english_leakage.py` → 398 passed. Changes are in the working
tree, uncommitted.

Open, not yet ruled on:

- Whether the delimiter and decimal halves ship as one commit or two.
- Whether existing upload rows with a NULL delimiter are read as comma or
  re-derived.
- The March spring-forward gap (carried over from earlier work, unrelated to
  this task, still never ruled on).
