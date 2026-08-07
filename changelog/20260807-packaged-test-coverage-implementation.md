# Implementation: closing the unpackaged coverage gaps

## Task Specification

Implements the seven items approved in
[20260807-packaged-test-coverage-proposal.md](20260807-packaged-test-coverage-proposal.md),
which followed the review in
[20260807-packaged-test-gating-review.md](20260807-packaged-test-gating-review.md).

Goal: the properties previously asserted ONLY by the dispatch-only Release workflow now
also run on every push, and the packaged suite keeps only the questions no unpackaged run
can answer.

## What was added

| # | Test | File |
|---|---|---|
| 1 | `test_the_static_mount_serves_its_assets` (×2, parametrized) | `tests/test_static_mount.py` (new) |
| 2 | `test_no_supported_locale_falls_back_to_roots_placeholder_month_names` | `tests/test_i18n.py` |
| 3 | `test_an_inverted_window_is_rejected_over_the_socket` | `tests/test_ingest_ws.py` |
| 4 | `test_load_endpoint_inverted_window_400` | `tests/test_slot_load.py` |
| 5 | `test_an_unknown_workspace_fails_the_websocket_handshake` | `tests/test_ingest_ws.py` |
| 6 | `test_the_chart_month_labels_are_localised_end_to_end` (×2) + `year_client` fixture | `tests/test_i18n.py` |
| 7 | `test_the_cldr_locale_data_is_in_the_bundle` | `tests/test_packaged.py` |

Nine test cases from seven definitions (items 1 and 6 are parametrized).

## Decisions taken during implementation

**Item 4 moved to `tests/test_slot_load.py`.** The proposal put it beside the socket test
for cohesion, on the user's "whatever is easier for maintenance". Implementation showed
that was the wrong file: the HTTP window check lives in `POST /w/{id}/data/slot/{slot}/load`,
whose other error paths (unknown slot, unknown source, browser_fetch rejected) already form
a labelled section in `test_slot_load.py`, and reaching `_parse_window` needs a slot/source
pair that survives the route's earlier validation steps. Putting it there reuses that
file's fixtures and puts it with the tests a reader would compare it against. Cross-
referenced in both directions in the docstrings.

**Item 6 needed no new seeding machinery, but did need a wider window.** Probed first: the
existing `seeded_client` fixture ALREADY renders both month nodes. Its 40-day span yields
only Jan/Feb, though, so a test asserting `Mar`/`mrt` would fail on the data rather than on
the property. Added `year_client`, a 365-day sibling, rather than widening `seeded_client`
— whose 40 days were chosen so figures are four digits and therefore grouped, which the
number-convention tests depend on.

**Item 6 reads the JSON chart node, not visible text.** The month labels only ever appear
inside `<script type="application/json">`, because the charts are drawn client-side. The
neighbouring `test_the_rendered_dutch_pages_use_dutch_number_conventions` STRIPS `<script>`
blocks before asserting, so its helper could not be reused; the two tests deliberately look
at disjoint halves of the same page.

**Item 7 imports the keep-set rather than restating it.** It asserts against
`babel_locale_keep_set()` — the same function `packaging/hooks/hook-babel.py` filters with
— so it checks that what the hook intended to keep actually arrived. A hardcoded
`{"en","nl","root"}` would pass even after a language was added to `SUPPORTED` and the trim
silently failed to follow, which is the regression the trim can introduce. Also asserts
`global.dat`, which lives outside `locale-data/` and would be missing if the filter
over-matched.

## Verification

Every test was run green, then MUTATED to confirm it fails for the right reason. A test
never seen red is not yet evidence.

| Test | Mutation | Result |
|---|---|---|
| 1 | stub floor raised to 10 MB | both fail, naming the real byte counts |
| 2 | `root` injected into the iterated locales | fails, listing all twelve `M01`..`M12` |
| 3 | window inverted back to valid | **hangs** — see below |
| 4 | window inverted back to valid | fails with 200 and the route's success body |
| 5 | pointed at a real workspace | fails (no `WebSocketDenialResponse` raised) |
| 6 | `_MARCH` locale expectations swapped | fails for BOTH locales, so it genuinely distinguishes them |
| 7 | four fake bundle layouts (see below) | correct verdict on all four |

**Item 3's mutation hangs rather than fails, and that is correct behaviour.** A VALID
header draws no reply at all — `app/ingest_ws.py::on_header` records the window and returns
— so `receive_json()` blocks forever. This is the same property
`tests/test_packaged_ingest.py::test_level1_the_server_answers_a_header_frame` documents in
its docstring. The mutation therefore demonstrates the test depends on the inverted window,
just not by failing an assertion. Confirmed by observing the hang and killing the run.

**Item 7 cannot be run here.** There is no bundle in this worktree and building one takes
minutes, so its logic was exercised against four synthetic layouts instead: a correct one
(passes), one with `nl.dat` dropped (reports `['nl']` missing), one with `global.dat`
dropped (reports it), and one with no `locale-data/` at all (reports that). The keep-set
import path was confirmed to work, returning `{'en','nl','root'}`.

**Item 7's bundle path is now CONFIRMED.** It was written as a reasoned inference from
`hook-babel.py`'s `_keep` plus PyInstaller's onedir convention, and flagged here as
unobserved. Release run 31186803969 (dispatch on `worktree-fixes`, 2026-08-07) executed it
against a real AppImage build:

    tests/test_packaged.py::test_the_cldr_locale_data_is_in_the_bundle PASSED [ 62%]

So `_internal/babel/locale-data/*.dat` is the actual layout, and the assertion that the
keep-set locales are present holds on a real artifact. The Linux job's verification step
went from 27 passed to 28.

That run also closes an open item from an earlier commit on this branch: the **Windows job
passed**, which is the first observation that the `tzdata` dependency actually fixes the
Windows build. `changelog/20260806-windows-tzdata.md` lists that as unverified.

## What this does NOT do

- **The packaged suite still runs and still matters.** Items 1–6 assert APPLICATION
  behaviour; none observes whether a bundle carries what that behaviour needs. Adding the
  unpackaged half is not an argument for dropping the packaged half.
- ~~**`test_babel_locale_data_is_bundled` is still failing in the Linux release job.**~~
  **Resolved: the test was removed.** See "Item 8" below.
- The feedback delay (packaging jobs are dispatch-only) is untouched; that is CI policy.

## Item 8: `test_babel_locale_data_is_bundled` removed

Added after release run 31186803969, on the user's decision (option 3 of the three the
analysis listed: narrow it, seed its fixture, or drop it).

**What the run established first.** It failed on exactly that test and nothing else:

    FAILED tests/test_packaged.py::test_babel_locale_data_is_bundled -
    AssertionError: no CLDR English month abbreviation on the en results screen

The predicted message. The fixture's workspace has no simulation, so both guarded month
nodes are absent and the grep for `Mar` finds nothing. Crucially this is a **probe failure,
not missing data** — `test_the_cldr_locale_data_is_in_the_bundle` PASSED in the same run
against the same bundle, so the CLDR files demonstrably arrived.

**Why dropping rather than repairing.** Both properties the test covered now run elsewhere,
each in a place better suited to it:

| Property | Now asserted by |
|---|---|
| the CLDR `.dat` files reached the bundle | `test_the_cldr_locale_data_is_in_the_bundle` (item 7) — reads `_internal`, immune to template changes |
| the labels render correctly per locale, end to end | `test_the_chart_month_labels_are_localised_end_to_end` (item 6) — every push, on a year-long fixture |

Keeping it would have meant either re-creating the template coupling that broke it (seeding
the packaged fixture) or keeping a page-level probe whose most valuable assertion — the
`M0[1-9]` negative catching a silent `root` fallback — is the one that goes vacuous when a
template change empties the page. Nothing is lost that is not now covered twice.

`tests/test_packaged.py` goes from 11 collected to 10. The module docstring was rewritten to
record why the page-rendering probe is gone, so a future reader does not re-add it; the
`_fetch_in` helper and the `re` import both stay, still used by
`test_the_dutch_message_catalog_is_bundled`.

Changelogs referring to the removed test are left as written — they are records of what was
true when they were written, not documentation of the current tree.

## Files Modified

- `tests/test_static_mount.py` — new; the static-mount test.
- `tests/test_i18n.py` — the `root`-fallback unit test, the `year_client` fixture, the
  `_chart_months` helper, and the end-to-end month-label test.
- `tests/test_ingest_ws.py` — the socket inverted-window test and the WS-handshake 404 test.
- `tests/test_slot_load.py` — the HTTP inverted-window test.
- `tests/test_packaged.py` — the direct CLDR bundle probe added; the page-rendering
  `test_babel_locale_data_is_bundled` removed (item 8); module docstring rewritten for both.
- `changelog/20260807-packaged-test-coverage-implementation.md` — this file.

## Current Status

All eight items done. Items 1–7 implemented and mutation-verified as recorded above; item 8
(the removal) followed from what release run 31186803969 showed.

That run closed both of the things this file previously listed as unverified: the in-bundle
CLDR path is confirmed, and the Windows job passed, which is the first observation of the
`tzdata` fix working rather than an argument that it should.

What remains open is not about these tests: the packaging jobs are still dispatch-only, so a
packaging regression still surfaces at release time rather than on the push that causes it.
That is CI policy and was never in scope here — the options the analysis listed (run on
pushes to master, nightly, or leave as-is) are still the options.
