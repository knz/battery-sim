# Dutch-leakage test: cache the renders in a module fixture

Phase 1 of two. Phase 2 (a predefined dataset, separate from the live instance) is specified at
the end and not yet started.

## Task specification

Follow-on from `20260726-test-suite-runtime-investigation.md`. After the benchmark-sweep caching
landed, the remaining runtime outlier was `tests/test_no_english_leakage.py`, but only on a
machine with a real `data/` directory — which is why the first investigation, run in a bare
worktree, did not see it.

The user then asked for a second phase: have the test work off a predefined dataset rather than
the developer's live instance.

## What was measured

The file's cost is the three page renders, not the string scanning. With a real `data/` present,
`POST /results` runs a simulation over the stored dataset and the three renders together cost
~5.7s.

`_dutch_pages()` was a plain function, not a fixture, and both test functions are parametrized
over the same three pages. So the three renders ran **six times** — ~34s — and each call
discarded two of the three pages it had just built. `_visible_text` likewise ran six times over
the same markup.

Confirmed causally rather than inferred: copying the user's `data/` into a bare worktree
reproduced both the runtime (~6.3s to ~42.5s for the affected files) and the disappearance of the
7 pre-existing leakage failures.

A framing correction worth recording, since the first investigation got it wrong: the test does
not recurse into subdirectories, and `external_data/` (429M) is not walked. `data/` is 2.4M. The
cost is the application loading the dataset during rendering.

## Change

`_dutch_pages(client)` became a module-scoped `dutch_text` fixture returning the three pages
already stripped to visible text — which is what both tests actually consume, so caching the raw
HTML would have left `_visible_text` running six times. The two parametrized tests take
`dutch_text` instead of `client`.

`test_the_english_page_is_unaffected` still takes `client` directly; it renders a different page
and is not part of the Dutch triple.

## Behaviour change to be aware of

On a machine **without** a usable `data/`, the six tests now report as **errors** (fixture setup
failed) rather than **failures**. Same root cause (the H13 409), same count, but pytest
categorises a raised assertion differently once it lives in a fixture. This is arguably the
clearer signal — the pages could not be built at all, which is not the same thing as the pages
containing English — but it is a real change in how a red run looks, and CI filters keying on
"failed" specifically would need to account for it.

## Verification

- With `data/` present: `test_no_english_leakage.py` 34s to **6.6s**, 7 passed. One 5.91s setup;
  the other five tests ~0.00s each.
- Full suite with `data/`: **823 passed, 2 skipped**, 36.3s.
- The fixture returns real content, not empty strings — 13629 / 4039 / 898 visible characters for
  `/`, `/results`, `/results/benchmark` respectively. Checked because a fixture that silently
  returned blanks would also make these tests pass.
- A single parametrized case passes in isolation, so no test depends on another warming the
  fixture.

## Files modified

- `tests/test_no_english_leakage.py` — `_dutch_pages` to a module-scoped `dutch_text` fixture
- `changelog/20260726-leakage-test-fixture.md` (this file, created)

## Current status

Phase 1 complete. Runtime addressed; **coverage is not** — `followups.md` H13 still stands, and
this change does not touch it. Which boxes these pages render still depends on the developer's
stored dataset and config, so a green leakage run on one machine still does not prove the
catalogs are complete.

## Phase 2, as requested and not yet started

Point the leakage tests at a predefined dataset held separately from the live instance, so
coverage is identical on every machine and in CI.

H13 records the trap: pointing the test at an empty temp data dir makes things *worse*, because
with no dataset the page falls back to the sample view-model, which carries its own untranslated
strings (followup A7) and produces six failures. So the fixture has to seed both a known dataset
and a known config, not merely redirect the path.

Open questions for that phase, not yet decided:

- Where the fixture dataset lives and in what format — committed CSV, a generator, or a small
  synthetic frame built in-process.
- Whether it replaces the live-instance run or runs alongside it (a committed dataset guarantees
  identical coverage; the live one exercises whatever real data happens to expose).
- How much of the panel surface it must populate to keep the current assertions meaningful, since
  a dataset that renders fewer boxes silently narrows the test.
