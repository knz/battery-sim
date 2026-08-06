# Pin the undifferenced pass-through of a flagged CSV register end-to-end

## Task specification

Harness fixture 22 (`docs/specs/16-validation-harness.md`, amended in 75bb41f) now requires
asserting that a column flagged `CSV_CUMULATIVE_COLUMN` is carried through the CSV import path
**undifferenced** — the series must hold the register's own readings, because silently
differencing them is the one thing this format never does (decision D-KIND).

Scope: test-only work plus this changelog. No product-code change. A Playwright test was
explicitly not wanted — the property is about values, not UI.

## Assessment of the existing coverage

Read before writing anything:

* `tests/test_csv_wide.py` (the "cumulative-register WARNING" block, ~lines 570-725). The
  domain layer is well pinned: `test_a_rising_register_column_warns_and_still_returns_its_values`
  asserts `np.allclose(frame.values, values)` over all 24 readings, and the section's own header
  comment states the intent (values *and* warning asserted together). No gap here.
* `tests/test_csv_source.py::test_cumulative_column_warns_and_is_neither_rejected_nor_differenced`
  — the source adapter is also pinned over the whole 14-row series.
* `tests/test_csv_binding_reify.py::test_a_cumulative_column_warns_and_the_fetch_still_succeeds`
  — **this is where the gap was.** It goes through the real reify path (WS `backend_load` →
  `_load_backend_frame` → persist → `dataset.load_latest`) but asserts only
  `frame.values[0] == pytest.approx(1000.0)`, i.e. one sample, the first one. Differencing
  implemented with a first-value-preserving convention — `np.concatenate([[v[0]], np.diff(v)])`,
  the most natural spelling — leaves `values[0]` untouched and passes that assertion. The
  property was therefore *stated* end-to-end but not *pinned* end-to-end.

## Decision: add the test at the reify layer

`tests/test_csv_binding_reify.py` was chosen over the alternatives:

* **not `tests/test_csv_wide.py`** — already fully pinned there, and it is the domain layer the
  spec's gap is explicitly *not* about;
* **not `tests/test_csv_source.py`** — also already pinned, and the adapter is one layer short of
  "the reify/load path a real fetch goes through";
* **not a new module** — the reify module already has the WS-driving helpers (`_store_upload`,
  `_send_csv_fetch`) and an isolated data dir, so the fixture cost of adding one test there is a
  handful of lines. A new module would duplicate the reload fixture.
* **not Playwright** — ruled out by the brief, and it could not assert array values anyway.

## Shape of the assertion

`test_a_flagged_register_loads_through_the_reify_path_undifferenced`:

* a 24-row hourly file, one column `Register`, values `5000.0 + 0.7 * i` — a rising register with
  a **constant** step. The constant step is deliberate: it makes every difference equal (0.7), so
  a differenced series is a flat line and cannot coincidentally resemble the readings.
* the window is the full 24 hours (`_WIDE_WINDOW`), not the module's default 6-hour window, so the
  assertion covers the whole column rather than a slice.
* the assertion compares the persisted frame's values against the **complete** expected list with
  `pytest.approx`, and then adds two explicit guards that name the two differencing conventions:
  `values[1]` is 5000.7 (not 0.7) and the last value is 5016.1 (not 0.7). The magnitude of the
  readings is ~7000× the step, so no differencing spelling can pass.
* the fetch is also asserted to succeed and to carry `CSV_CUMULATIVE_COLUMN`, so the test does not
  silently degrade into a values-only check if the warning is dropped.

Also widened `test_a_cumulative_column_warns_and_the_fetch_still_succeeds` from
`values[0]`-only to the full 6-sample window slice, since that was the specific weakness found.

## Verification

`.venv/bin/python -m pytest tests/test_csv_wide.py tests/test_csv_source.py
tests/test_csv_binding_reify.py -q` → all pass (see Current status for counts).

Mutation test: `app/sources/csv_source.py`'s `load_with_warnings` was temporarily changed to
difference the frame values with a first-value-preserving convention
(`np.concatenate([[v[0]], np.diff(v)])`) before slicing. Confirmed the new test fails and the
old `values[0]`-only assertion would have passed that mutation. File restored from a scratchpad
`cp` backup, never from git; `git diff --stat` on it confirms byte-identity.

## Files modified

* `tests/test_csv_binding_reify.py` — one new test, one widened assertion, module comment updated.
* `changelog/20260806-csv-cumulative-passthrough-e2e-test.md` — this file.

## Current status

Done, uncommitted. See the final report for exact test counts and mutation output.
