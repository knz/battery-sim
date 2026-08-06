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

### The field delimiter — implemented (requirements 1 and 2)

The delimiter half, landed after the decimal half. Requirement 2 (quoting) needed
no new code — `csv.reader` is an RFC 4180 tokenizer and honours double quotes
under whichever delimiter it is given — so the work there was to pin it under
each of the three, and to state it normatively in the spec where it had never
been written down.

#### Decisions taken during implementation

**D-DELIM-VOCAB: the wire and DB vocabulary is names, not characters.**
`comma` / `semicolon` / `tab`, with `csv_wide.DELIMITER_CHARS` the single place a
name becomes a character. Two reasons. A literal tab in an HTML `value=`
attribute, in a multipart field and in a source file survives no reformatter, no
linter and no careless editor, and is invisible in a diff. And `tz` set the
precedent one field over: it carries `Europe/Amsterdam`, an identifier the parser
resolves, not the offset it stands for.

**D-DELIM-NULL: a NULL `delimiter` column reads as `comma`, with no backfill.**
This is the open question from the previous section, now ruled on. It
deliberately differs from `cumulative_columns_json`, where NULL is a meaningful
third state ("not computed") that no reader may collapse. Here NULL is not
unknown at all: `csv.reader`'s comma default was the only tokenizer this app ever
used, so every pre-existing row was parsed as comma *and accepted under it*. The
value is known; it simply predates the column that would have recorded it.
Reading it back as comma states a fact rather than guessing a default, so
`Upload.delimiter` is `str` and never None and no downstream caller holds a third
state that does not exist. A backfill `UPDATE` was declined: it would write the
same value into every row and change nothing about what any of them means. The
argument is written into `app/uploads.py`'s `_SCHEMA` docstring, because reading
the file cold it looks like an inconsistency with the field directly above it.

**D-DELIM-ABSENT: an upload request with no `delimiter` field defaults to comma
rather than being rejected.** Again unlike `tz`, which rejects when absent. There
is no defensible default zone — a file read in the wrong one produces plausible
timestamps silently shifted by an hour or two — whereas comma is the same
known-correct historical answer as above. Defaulting keeps an older client, a
script, and every pre-existing test posting two fields working unchanged, and
stores exactly the value those requests were already getting.

**D-DELIM-NOSNIFF: the app does not sniff, and the spec now says why.** A file
whose cells may themselves contain commas is genuinely ambiguous to a sniffer: a
semicolon export full of decimal commas has more commas than semicolons, so
character-counting reads it under the commoner character and splits every value
into two integers — the same factor-of-a-thousand error the row-length guard
(D-DELIM-GUARD) exists to prevent. Where an ambiguity yields a plausible wrong
answer rather than a visible failure, this app asks.

**The sticky radios were matched, not fixed.** `openCsvUpload` does not reset the
tz radio between two uploads in one dialog session, so the second file inherits
the first's answer; the delimiter radio now behaves identically. Deliberate —
files uploaded back to back nearly always come from one exporter — and recorded
in a comment there rather than fixed, because fixing it should cover both radios
at once and is a separate change.

#### Files modified

- `app/domain/csv_wide.py` — `COMMA_DELIMITER` / `SEMICOLON_DELIMITER` /
  `TAB_DELIMITER`, `DELIMITER_KEYS`, `DELIMITER_CHARS`, `DEFAULT_DELIMITER`
  beside `TZ_KEYS`, with D-DELIM-VOCAB in a comment.
  `parse_wide_csv(text, tz, delimiter=DEFAULT_DELIMITER)` and
  `parse_and_summarise` likewise — keyword-with-default, so every existing call
  site and test keeps working. Validation mirrors the `tz not in TZ_KEYS` block
  and raises the new `bad_delimiter` code. `WideCsv` and `WideCsvSummary` each
  gain a `delimiter` field, for the same reason `tz` is on them: a record of how
  the file was read.
- `app/uploads.py` — a `delimiter TEXT` column appended last (so a fresh table
  matches a migrated one), an `_ADDED_COLUMNS` entry, the `Upload` field, the
  `_COLUMNS` entry, the positional read, and `create`'s parameter / coercion /
  INSERT value / returned object. The coercion sits in the up-front block above
  `path.write_text`, per that function's own rule that no argument-shape error
  may fire once the file exists. The module still imports nothing from
  `app.domain`: the `"comma"` literal is spelled out with a comment pointing at
  `csv_wide.DEFAULT_DELIMITER`, matching how the file already refers to
  `csv_wide` in prose only.
- `app/main.py` — the form read (absent → default, commented against the `tz`
  case), the validation block after the tz one and above the decode, the parse
  call, `delimiter=summary.delimiter` on the `uploads.create` call (from the
  summary, so the row cannot record an answer the file was not read with), and
  `"delimiter": upload.delimiter` in `_upload_json`, off the row like `tz` so it
  appears on the LIST route too. Route docstring amended: two fields → three,
  and the check ordering sentence now reads "size, then the declared zone and
  separator, then the decode, then the full parse".
- `app/sources/csv_source.py` — the fetch-path re-parse passes
  `upload.delimiter or csv_wide.DEFAULT_DELIMITER`. This is the invariant that
  makes the stored value load-bearing: both parses must agree.
- `app/templates/workspace_data.html` — a second `<fieldset>` after the tz one,
  `name="csv-upload-delimiter"`, values `comma` (pre-checked) / `semicolon` /
  `tab` (the wire vocabulary, NOT translated; only the labels are). The layout
  bullet on fractional values now names the dot/comma choice and the quoting rule
  — that clause forecloses the likeliest user failure. New
  `csv_err_bad_delimiter` string.
- `app/static/ha_fetch.js` — `uploadCsvFile` reads the radio and appends the
  third multipart field; header comment "two fields" → three.
  `bad_delimiter` added to `CSV_ERROR_KEYS` but deliberately NOT to
  `CSV_ERROR_DETAILED`, matching `bad_timezone`: its server message merely
  restates the translated one, which is that list's stated criterion. A comment
  in `openCsvUpload` records the sticky-radio decision.
- `app/locales/*` — extract/update/compile, Dutch hand-written for all five new
  strings.
- `docs/specs/05-data-formats.md` — §4.2a's layout table gains a **Fields** row
  stating the delimiter normatively for the first time, including that a
  delimiter inside a double-quoted cell does not split the cell (requirement 2,
  previously unstated even though it needs no code). New subsection "The field
  separator is answered once, at upload — and never sniffed", paralleling the
  timezone one. The file-level rejection list gains an unknown separator, with a
  note that a wrong-separator file usually surfaces as `too_few_columns`.
- `docs/specs/02-ux-wireframes.md` — the dialog ASCII art gains the radio group
  and the amended values bullet; a rationale paragraph after the timezone one
  covers D-DELIM-NOSNIFF and the sticky radios.
- `docs/specs/08-architecture.md` — §5.1's `uploads` row gains `delimiter` (and
  `cumulative_columns_json`, which had never been added to that list), with the
  NULL-means-comma rule stated inline.
- `docs/specs/16-validation-harness.md` — fixture 22's *At upload* paragraph
  gains the unknown separator, plus a positive/negative pair: a semicolon file
  with the semicolon radio parses, and THE SAME BYTES with the comma radio are
  rejected as `too_few_columns`. That pair is what proves the answer is used
  rather than sniffed — a sniffer would accept both halves.
- `tests/test_csv_wide.py` — a delimiter section (each separator parses its own
  file; omitted == explicit comma; each of the two cross-readings rejected as
  `too_few_columns`; `"pipe"` and a raw `";"` both `bad_delimiter`; the echo on
  `WideCsv` and `WideCsvSummary`) and a quoting section (one quoted-delimiter
  case per separator, plus a semicolon file with bare `1,9` and `0,412` reading
  as 1.9 and 0.412 — the commonest European shape and the practical point of the
  whole option).
- `tests/test_upload_routes.py` — `_post` gains an optional `delimiter` that
  OMITS the part when None, so every pre-existing test in the file exercises the
  absent-field default. New: semicolon accepted and echoed and stored, the same
  bytes as comma rejected, four unknown spellings rejected (including `";"` and
  `"COMMA"`, pinning that the vocabulary is names and is not case-folded),
  absent and empty both defaulting to comma, and the LIST route carrying it.
- `tests/test_uploads.py` — round-trip through `get` and `list_for`, the default,
  and a legacy row with an explicitly NULL delimiter reading back as comma. The
  NULL row is fabricated with raw SQL through the module's own `connect`, and the
  existing migration test now also asserts the migrated legacy row reads comma.
  `test_create_round_trips_every_field` extended.
- `tests/test_csv_source.py` — `_upload` gains a delimiter parameter; a semicolon
  upload re-parses with the stored value and yields 1.9 / 0.56 / 0.412, and a row
  whose `delimiter` is NULL re-parses as comma.
- `tests/test_smoke.py` — `_upload_csv` gains an optional `delimiter` part, kept
  OPTIONAL so the route's absent-field default is exercised end to end over real
  HTTP by every existing caller. One new Playwright case: three radios exist with
  comma pre-checked, picking semicolon and uploading a semicolon file succeeds,
  and the listed summary shows 2 value columns (read as comma the file would have
  been refused outright).

#### Obstacles

- No positional `Upload(...)` or `WideCsv(...)` construction exists outside the
  owning modules — grepped for; the new fields broke nothing.
- The smoke list renders VALUE columns (header length minus the timestamp), so
  the new Playwright assertion is "2 columns" for a three-field header.

## Current status

All three requirements are implemented and tested. Changes are in the working
tree, uncommitted.

Verification: `tests/test_csv_wide.py tests/test_csv_source.py
tests/test_upload_routes.py tests/test_uploads.py tests/test_csv_binding_reify.py
tests/test_ingest_ws.py tests/test_i18n.py tests/test_no_english_leakage.py` →
529 passed. `tests/test_slot_load.py` → 28 passed (it calls
`parse_and_summarise` and was checked for the new argument).
`tests/test_smoke.py` → 59 passed, including the new Playwright case. The full
suite was not run — CI covers it.

The `.pot` diff is the five intended new strings, the one re-worded bullet, and
`POT-Creation-Date`; nothing else. Two unrelated Dutch strings were rewrapped by
`pybabel update` with their content unchanged. Zero fuzzy.

Open, not yet ruled on:

- Whether the delimiter and decimal halves ship as one commit or two.
- Whether the sticky radios should reset between uploads in one dialog session.
  Matched for the new radio and recorded in a comment rather than fixed; fixing
  it should cover both radios at once.
- The March spring-forward gap (carried over from earlier work, unrelated to
  this task, still never ruled on).
