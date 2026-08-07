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

**Still unverified for item 7:** the real on-disk layout inside a built bundle. The path
`_internal/babel/locale-data/*.dat` is derived from `hook-babel.py`'s `_keep`, which
matches destinations ending `babel/locale-data`, plus PyInstaller's onedir convention of
rooting datas at `_internal`. That is a reasoned inference from the hook source, NOT an
observation of a bundle — the same class of claim
`changelog/20260806-windows-tzdata.md` flags about its own hook reasoning. It needs one
Release run to confirm. If the path is wrong the test fails loudly with the path it looked
at, so the failure mode is a red build rather than a silent pass.

## What this does NOT do

- **The packaged suite still runs and still matters.** Items 1–6 assert APPLICATION
  behaviour; none observes whether a bundle carries what that behaviour needs. Adding the
  unpackaged half is not an argument for dropping the packaged half.
- **`test_babel_locale_data_is_bundled` is still failing in the Linux release job.** Nothing
  here fixes it. Its fate is now a smaller decision than before: its end-to-end property
  runs unpackaged (item 6) and its bundle property is asserted directly (item 7), so it
  could be narrowed to the number-separator check or dropped outright. Left for the user
  deliberately — it was out of the approved scope.
- The feedback delay (packaging jobs are dispatch-only) is untouched; that is CI policy.

## Files Modified

- `tests/test_static_mount.py` — new; the static-mount test.
- `tests/test_i18n.py` — the `root`-fallback unit test, the `year_client` fixture, the
  `_chart_months` helper, and the end-to-end month-label test.
- `tests/test_ingest_ws.py` — the socket inverted-window test and the WS-handshake 404 test.
- `tests/test_slot_load.py` — the HTTP inverted-window test.
- `tests/test_packaged.py` — the direct CLDR bundle probe.
- `changelog/20260807-packaged-test-coverage-implementation.md` — this file.

## Current Status

All seven items implemented and mutation-verified as recorded above. Full suite run to
confirm nothing regressed. Item 7's bundle path is the one open assumption, and it can only
be closed by a Release run.
