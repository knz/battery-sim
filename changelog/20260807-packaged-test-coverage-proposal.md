# Proposal: close the unpackaged coverage gaps

## Task Specification

Following the review in
[20260807-packaged-test-gating-review.md](20260807-packaged-test-gating-review.md), the
user asked for a proposal to improve test coverage.

**Status: proposal only, awaiting approval. Nothing implemented.**

Scope: the four properties currently asserted ONLY in the dispatch-only release run, plus
the i18n strengthening identified in the review. Out of scope: the fragile-probe decision
for `test_babel_locale_data_is_bundled` and the CI-cadence question — both are choices for
the user, and both are addressed separately at the end.

## Feasibility checks run before writing this

Each proposed test was probed against the tree first, so none of what follows is assumed:

- **`TestClient` serves the static mount.** `GET /static/app.css` → 200, 100,534 bytes;
  `/static/ha_fetch.js` → 200, 125,840 bytes. No uvicorn subprocess is needed, which moves
  this test out of the slow Playwright module.
- **`TestClient` DOES observe the WS handshake rejection.** It raises
  `WebSocketDenialResponse` carrying `.status_code == 404`. This is the one claim I
  expected might not transfer; it does, and gives a cleaner assertion than the packaged
  test's substring match on `"404"`.
- **The `root`-fallback assertion is non-vacuous and passes today.** `i18n.SUPPORTED` is
  `('en','nl')`; neither yields an `M\d\d` abbreviation for any of the 12 months, while
  `Locale.parse("root")` yields `M01`/`M03`/`M10`.
- **`app/main.py:2407`** raises the same window-ordering message on an HTTP path, alongside
  `app/ingest_ws.py:199`.

## The proposal: five tests, four files

Ordered by value per unit of effort. Each is small and runs on every push.

### 1. The static mount serves real assets — `tests/test_static_mount.py` (new)

The largest real gap: nothing unpackaged fetches `/static/*` at all, so the mount could
break and only a release build would notice.

Two assertions per asset, mirroring the packaged test: status 200, and a size floor. The
size floor is what distinguishes "the route works" from "the route serves a stub", and it
is the half that would catch a Tailwind build writing an empty file.

A new file rather than an addition to an existing one, because it belongs to neither the
workspace-route suite nor the Playwright suite, and `TestClient(main.app)` needs no
fixture from either. Roughly 25 lines including the header comment AGENTS.md requires.

**Deliberately NOT proposed:** asserting on `app.css` CONTENT (e.g. that a given class is
present). The css-freshness CI job already owns that property, and duplicating it here
would give two tests that fail together for one cause.

### 2. The `root`-fallback negative — `tests/test_i18n.py` (addition)

The strengthening the review identified. One test asserting that no locale in
`i18n.SUPPORTED` yields a `M\d\d` placeholder abbreviation for any month.

This is the load-bearing item, and worth stating precisely why. The packaged test's

    assert not re.search(r"\bM0[1-9]\b", page)

is *vacuously true whenever the page renders no months* — exactly the state the template
guards now produce. It only has teeth when the positive assertions above it already
passed, so the check guarding the subtle failure is the one an unrelated template change
most easily silences. Asserting on `month_abbr` directly cannot go vacuous: it calls the
function rather than grepping a page that may contain nothing.

It also loops over `SUPPORTED` rather than hardcoding `en`/`nl`, so adding a language
extends the check automatically — which is the case the CLDR trim in
`packaging/battery_sim_babel_locales.py` is most likely to get wrong.

Placed next to `test_month_abbreviations_come_from_the_catalog_of_each_locale`
(`tests/test_i18n.py:573`), which asserts the positive values and is its natural sibling.

### 3. The inverted-window rejection, WS path — `tests/test_ingest_ws.py` (addition)

Sits directly alongside the existing neighbours `test_done_before_header_is_rejected`
(`:208`), `test_rows_before_series_is_rejected` and `test_unknown_series_is_rejected`.
Sends a header whose `end` precedes its `start`; asserts the error frame and its message.

Same shape as its neighbours, ~8 lines.

### 4. The inverted-window rejection, HTTP path — `tests/test_ingest_ws.py` or the route suite

`app/main.py:2407` raises the identical text from `HTTPException(400)`. This site was not
in the original analysis; I found it while checking gap 2.

Proposed as a **separate, smaller** item because it is a different code path with a
different failure mode (a 400 response, not an error frame), and because its natural home
may be the route-level suite rather than the ingest one. I would put it with the WS test
for cohesion — the two assert the same rule at the app's two entry points, and keeping
them adjacent makes the pair legible — but this is the one placement decision I would take
direction on.

### 5. Unknown workspace → 404 at the WS handshake — `tests/test_ingest_ws.py` (addition)

Asserts `WebSocketDenialResponse` with `.status_code == 404`, using the mechanism verified
above.

Worth having unpackaged for a reason beyond coverage: the packaged suite's own docstrings
record that this behaviour once caused a misdiagnosis — a rejected handshake looks exactly
like "this bundle has no WebSocket support" to a reader who has not seen the route. Pinning
it where it runs on every push keeps that documented in executable form for the source
tree too, not only in the release run.

## What this does and does not achieve

**Closes:** all four properties previously checked only in the release run, plus the
vacuous-negative weakness.

**Does NOT close, and should not be read as closing:**

- The packaged tests still need to run. Every one of these asserts APPLICATION behaviour;
  none observes whether the bundle carries what that behaviour needs. Per the review's
  bucket 2, this is the point — the two runs ascertain different things, and adding the
  unpackaged half is not an argument for dropping the packaged half.
- **`test_babel_locale_data_is_bundled` remains broken in the Linux release job.** Nothing
  proposed here fixes it. Item 2 makes the CLDR trim's failure mode catchable on every
  push, which reduces what that test is the sole guard of — but the test itself still
  fails until its probe is chosen. Deliberately left out: that decision is the user's.
- The feedback delay (packaging jobs are dispatch-only) is untouched. That is CI policy.

## Verification plan

Each new test run against the current tree to confirm it passes, then **mutation-checked**
— the assertion inverted or its subject broken, to confirm it fails for the right reason.
A test that has never been seen red is not yet evidence of anything. Concretely:

- static: point the mount at an empty directory; expect 404 and a size-floor failure.
- `root` negative: temporarily add a bogus locale to the iteration; expect the placeholder
  match.
- the three ingest tests: each already has a passing sibling, so inverting the asserted
  condition is enough.

Then the full suite once, to confirm nothing regressed. Not targeted runs only — five new
tests across three files touch enough shared fixture surface to be worth one full pass,
and the suite is ~180s.

## Cost

Five tests, ~90 lines including the file-header comments AGENTS.md requires. All run
in-process under `TestClient`; none spawns a subprocess or a browser. Expected addition to
suite runtime: under a second — the static test is the only one touching a large file, and
it reads two already-built assets.

## User decisions (answers to the open questions)

1. **Item 4's placement** — "whatever is easier for maintenance": keep it beside the WS
   test in `tests/test_ingest_ws.py`. The two assert the same rule at the app's two entry
   points, so a change to the rule is one file to edit.
2. **Scope** — all five.
3. **The babel probe** — do BOTH halves, split by environment (see below). This is a third
   shape, better than either single option originally offered.

## Items 6 and 7: the babel probe, split by environment

The user's framing: a standalone unpackaged test that seeds enough months and asserts the
end-to-end rendering, plus a direct bundle test in the packaged suite.

This is a better split than "seed the packaged fixture" or "replace the packaged probe",
because it puts each question where it can be answered cheaply: the end-to-end property
runs on every push where seeding is a fixture away, and the packaged suite keeps only the
question no unpackaged run can answer.

### 6. End-to-end month labels — `tests/test_i18n.py` (addition)

**Verified by probe before proposing.** The existing `seeded_client` fixture
(`tests/test_i18n.py:594`) ALREADY renders both month nodes — `#saved-eur-data` and
`#flows-data` are present, carrying `"Jan","Feb"` in English and `"jan","feb"` in Dutch.
So no new seeding machinery is needed; the guards
(`_panel_results.html:776`, `:851`) are satisfied by that fixture's data.

Two findings that shape the test:

- Its 40-day span yields only Jan/Feb, so asserting on `Mar`/`mrt` as the packaged test
  does would fail. A probe with a **365-day** span returns all twelve months, correctly
  localized in both locales (`Jan..Dec` / `jan..dec`, including `mrt`, `mei`, `okt`), with
  no `M0[1-9]` placeholders. A wider fixture is the right call: a test pinned to exactly
  two months is fragile in the same way the packaged one was.
- The month labels live INSIDE a `<script type="application/json">` node, so this test
  cannot reuse `test_the_rendered_dutch_pages_use_dutch_number_conventions`'s `visible()`
  helper — that helper strips `<script>` blocks. It must read the JSON node directly.

The test asserts, per locale: the node exists, its `months` array is non-empty, the
expected localized abbreviations appear, and no entry matches `M\d\d`. Unlike the packaged
grep, the negative here is NOT vacuous — the assertion that the array is non-empty runs
first, so an empty page fails loudly rather than passing silently.

A separate year-long fixture rather than widening `seeded_client`, so the existing
number-convention tests keep their current data and are not perturbed by this change.

### 7. CLDR data files in the bundle — `tests/test_packaged.py` (addition)

Asserts Babel's locale data reached `_internal`, without rendering anything. Decoupled
from every template and view-model, so a chart change cannot break it.

**Caveat, stated because it is the one thing not verified:** the exact on-disk layout of
Babel's data inside a built bundle has not been confirmed — there is no bundle in this
worktree and building one takes minutes. The test will be written defensively (locate
Babel's data directory under `_internal`, then assert the `.dat` files for
`i18n.SUPPORTED` plus `root` are present) rather than hardcoding a guessed path, and the
path assumption must be confirmed against a real build before this is relied on. It is
also the one proposed test that cannot be verified locally by running it.

This does NOT by itself fix the currently-failing `test_babel_locale_data_is_bundled`.
That test's fate is now a smaller decision — with items 6 and 7 in place, its end-to-end
property runs unpackaged and its bundle property is asserted directly, so it could be
narrowed to the number-separator check or dropped. Left for the user.

## Current Status

Approved: all seven items. Feasibility of items 1–6 verified against the tree by direct
probe; item 7's bundle path is the one open assumption, flagged above.
