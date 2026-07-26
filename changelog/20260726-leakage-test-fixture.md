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

## Phase 2 — DONE

Implemented. The leakage tests no longer read the developer's `data/` at all.

### Scope decision

The user chose the eight-scenario option after an exploration pass found more mutually-exclusive
branches than the first estimate of three allowed for. Seven are dataset/config scenarios; the
eighth is the validation-message surface, which needs a different mechanism (see below).

### What was built

`rendered` — a module-scoped fixture that, for each scenario, redirects `BATTERY_SIM_DATA_DIR` to
a fresh temp dir, reloads the config/db/dataset/simconfig_store chain, seeds a synthetic dataset
and a stored `SimulationConfig`, and renders `/`, `/results` and `/results/benchmark` in Dutch.
Returns `{scenario: {page: visible_text}}`. One pass for the whole module, for the same reason
phase 1 gave.

Series are built in-process from numpy arrays (the `SeriesFrame` shape `test_results_route.py`
already uses) rather than committed as fixture files — chosen for maintenance, per the user's
"whatever is easier later": no binary `.npz` in git, nothing to regenerate when the schema moves,
and it reuses helpers that are already maintained. Windows are 40 days hourly (10 for the short
scenario), and the DP grids are cut to 21x21 since nothing here asserts on the bound's tightness.

The seven scenarios and the branch each exists to reach:

| scenario | reaches |
|---|---|
| `full` | euro section, pricing box, 4 euro caveats, accepted 3-phase approximation, 15-min prices vs hourly grid (price-granularity caveat), existing-battery box |
| `bare` | cost-OFF affordance, cost-OFF negative-saving wording, no-PV policy labels and greyed P1/P3 |
| `unreliable_nopv` | `load_unreliable` "no solar data supplied" variant |
| `unreliable_pv` | `load_unreliable` "sensor did not report" variant |
| `solar_empty` | `solar_empty` note (PV mapped, ~zero production) |
| `short_window` | `annualisation_disabled` |
| `phase_unsupported` | check 18's warning (unsupported topology NOT accepted) |

The eighth surface, `params_view.ISSUE_MESSAGES`, is driven through `POST /params` with one
deliberately-invalid submission per code, because none of those 14 messages renders from a stored
config. `test_every_issue_message_has_a_trigger` asserts the trigger table covers the live
`ISSUE_MESSAGES` dict, so a message added later is not silently skipped.

### Coverage guards

Per the user's choice, the scan is backed by floors rather than trusted:

- `test_each_scenario_still_surfaces_its_boxes` — each scenario must still render its marker.
- `test_the_cost_branches_are_both_reached` — presence AND absence, since "cost-OFF" is defined
  by the euro section *not* rendering, which a marker table cannot express.
- `test_the_scenarios_between_them_render_a_lot_of_prose` — a word floor per page.
- `test_the_marker_table_covers_every_scenario` / `test_every_issue_message_has_a_trigger` —
  completeness of the two tables.

### Two things measurement corrected

**A marker that did not test what it claimed.** `"Kostenbesparing"` looked like the natural
cost-section marker and was wrong: it is a substring of the setup band's `"Kostenbesparing
simuleren?"`, which renders in both branches. A mutation run (disabling `simulate_cost` on the
`full` scenario) passed 62/62 with it. Replaced with the waterfall heading `"Waar het geld
vandaan komt"`, which appears only inside the euro section; the same mutation now fails two
tests. The guard was only trustworthy after being made to fail on purpose.

**A word floor set above a legitimate state.** The benchmark box's shortest honest form — "even
perfect foresight could not have avoided any import", which `unreliable_pv` reaches — is 33
words. The floor was 40, so a correct page failed. Lowered to 25: the guard is against the box
collapsing, not against it being terse.

### Verification

- `tests/test_no_english_leakage.py`: **62 passed in ~4.0s**.
- **Identical with and without the live `data/` copied in** — which is the phase's point. H13's
  per-machine variance is gone; the 7 failures that used to appear only in a bare checkout no
  longer exist in either state.
- Three mutations, each caught: cost simulation silently disabled (2 tests fail), the clamp
  scenario no longer clamping (1 fails), an English string injected into a template (14 fail).
- Full suite: **877 passed, 2 skipped, 1 failed** in 33.2s. The one failure,
  `test_i18n.py::test_the_rendered_dutch_pages_use_dutch_number_conventions`, is PRE-EXISTING —
  confirmed by stashing this change and seeing it fail identically. It is the same H13 pattern in
  a file this work did not touch.

### Known coverage loss, deliberate

`data.quality.load_warning` is set only in `app/sample_data.py:269` and never by `data_view.py`.
It rendered on the developer's machine solely through the sample-view fallback, so replacing the
live data means it is no longer scanned. It is dead in the real path, so this is judged correct
rather than a regression — but it is a string that was covered before and is not now.

### Follow-up: the last failing test — DONE

`test_i18n.py::test_the_rendered_dutch_pages_use_dutch_number_conventions` was the same H13
pattern, confirmed by measurement rather than assumed: it PASSED on the developer's checkout and
FAILED in a bare worktree, with `POST /results` answering 409 for want of a dataset. It predates
this work (last touched in `de6f3ab`), and its own docstring recorded the dependency — "the
persisted dataset's numbers change between runs".

Fixed the same way: a `seeded_client` fixture over a synthetic dataset. It is the only test in
that file hitting `POST /results`; the others use `GET /`, which renders the sample fallback and
does not 409.

The seeded figures are chosen, not arbitrary. The assertions come in pairs — "Dutch must group
with a point" AND "Dutch must not group with a comma" — and the second half passes trivially on a
page with no grouped figure at all. So the dataset is sized to put a FOUR-DIGIT figure on the
page (1.5 kWh/h over 40 days ≈ 1,440 kWh) and a price series to produce a three-decimal €/kWh
line. Verified by rendering: `1,440 kWh` / `1.440 kWh` and `0.164` / `0,164 €/kWh`.

Mutation-checked both ways: shrinking the import to 0.05 kWh/h — figures too small to group —
makes the test FAIL rather than pass vacuously, and breaking `i18n.num` fails it too.

Full suite in a bare worktree: **878 passed, 2 skipped, 0 failed**, 33.0s. `test_i18n.py` and
`test_no_english_leakage.py` give identical results with and without the developer's `data/`.

## Phase 2, as originally specified

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
