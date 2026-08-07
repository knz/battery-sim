# Review of the packaged-test gating analysis

## Task Specification

The user asked for three things, against
[20260807-packaged-test-gating-analysis.md](20260807-packaged-test-gating-analysis.md):

1. Double-check that analysis's findings.
2. Classify the 23 gated tests into three buckets:
   - only meaningful against the packaged artifacts;
   - worth running in BOTH environments, because each run ascertains something different;
   - sufficient to run in regular CI alone.
3. Follow up on the suggestion that the i18n tests are brittle and something related
   could be strengthened.

Note the classification asked for here is NOT the one the analysis produced. The analysis
asked "could this move?"; the user asks "where should this RUN?", which admits a
both-environments answer the analysis's A/B/C scheme has no bucket for.

**Status: review and classification only. No code or test changes made.**

## Verification method

Every claim was re-checked against the tree rather than accepted. Checks run:

- `pytest --collect-only` on the three gated files → 23 collected, matching the analysis.
- `grep` for `/static/` outside the packaged tests → only the two `href`-string
  assertions the analysis names; no unpackaged fetch of the route.
- `grep` for `"must be after start"` → three raise sites in `app/`, one assertion in
  `tests/test_packaged_ingest.py`, none elsewhere in `tests/`.
- `grep` for a WS-handshake 404 in `tests/test_ingest_ws.py` → nothing.
- `tests/test_desktop.py:1186-1187` read directly → does assert `desktop.lock` exists and
  records the port, unpackaged.
- `tests/test_ingest_ws.py:83-109` and `:278-295` read directly → the level-2 assertions
  are present, several verbatim.
- Babel's `root` locale queried directly → `['M01','M03','M10']`, confirming the
  placeholder shape the negative assertion greps for is real.
- `grep monthname app/templates/` → two call sites, both now behind guards.

## Findings on the analysis itself

The analysis holds up. Every factual claim checked reproduced. Two refinements:

**1. The `f42690f` diagnosis is correct but incomplete.** The analysis attributes the
break to `monthly_saved_eur` guarding the month node (`_panel_results.html:776`). There is
a SECOND `monthname` site at `:852`, guarded by `results.energy_flows`. Both guards are
simulation-dependent, so the fixture that produced the failure renders NEITHER. This
strengthens rather than weakens the analysis's point: there is no longer any unconditional
month label on the page, so the probe depends entirely on the fixture having a simulation.

**2. `app/main.py:2407` raises the same "window end must be after start" text on an HTTP
path.** The analysis names only `app/ingest_ws.py:199`. Neither is asserted unpackaged, so
gap 2 is if anything slightly wider than stated.

Neither refinement changes any conclusion.

## The classification asked for

### Bucket 1 — packaged-only (14)

Read files inside the bundle or observe `sys.frozen`; no unpackaged meaning at all.

`tests/test_appimage.py` (7): the typelib, PyGObject, optparse, WebKit-helper,
WebKit/GTK-library, library-closure and AppRun tests.

`tests/test_packaged.py` (3): `_build_info` as a file, no dev directories, per-user data
directory.

`tests/test_packaged_ingest.py` (4): both `test_level1_a_raw_websocket_upgrade_completes`
and `test_level1_the_server_answers_a_header_frame` — `TestClient` speaks ASGI and never
performs an HTTP upgrade, so there is no unpackaged equivalent even in principle — plus
`test_the_websocket_route_works` in `test_packaged.py`, and
`test_level1_an_unknown_workspace_fails_the_handshake` (see bucket 2 for its unpackaged
half).

### Bucket 2 — worth running in BOTH (6)

These ascertain genuinely different things in each environment: unpackaged they pin
application behaviour on every push; packaged they show the bundle carries what that
behaviour needs. This is the bucket the analysis's scheme could not express — it classed
most of these as "already covered, only distinct value is bundle presence", which is
precisely the case for running them in both places rather than moving them.

| Test | Unpackaged it would ascertain | Packaged it ascertains |
|---|---|---|
| `test_babel_locale_data_is_bundled` | CLDR month/separator behaviour on the real routes | `collect_data_files("babel")` and the SUPPORTED trim reached the bundle |
| `test_the_dutch_message_catalog_is_bundled` | catalogs load and are consulted | `app/locales/nl` survived packaging |
| `test_static_files_are_bundled` | the StaticFiles mount serves 200 (**currently untested anywhere unpackaged**) | the real asset came along, not a stub (`len>1000`) |
| `test_the_single_instance_lock_records_the_live_port` | the lock records the port (already at `test_desktop.py:1186`) | the frozen `sys.frozen` path writes it to the per-user dir |
| `test_level2_a_recorded_ha_batch_replays_and_persists` | the result frame's shape (already at `test_ingest_ws.py:83`) | the same answer through a real socket to a frozen process; `grid_s==3600` exercises bundled numpy |
| `test_level2_the_replayed_rows_are_queryable_afterwards` | the read-back through HTML (already at `test_ingest_ws.py:278`) | persistence reached disk in the frozen per-user dir |

The last three are already covered unpackaged, so "both" is satisfied today and the
packaged copy should simply stay. The first three are the ones where the unpackaged half
does not fully exist yet.

### Bucket 3 — regular CI would suffice (3)

- `test_it_serves_the_workspace_list` — `GET /` → 200 with `<html`. Trivially covered by
  any unpackaged server test. Keeping it packaged costs nothing (it shares the fixture)
  but it carries no bundle-specific information.
- `test_templates_and_the_shipped_data_render_a_results_screen` — covered by
  `tests/test_results_route.py` and `tests/test_smoke.py:198`. Its bundle value is real but
  entirely subsumed by the two locale tests above, which fetch the SAME page and would fail
  first if templates or data were missing.
- `test_the_appimage_serves_over_http` — the `GET /` half. Its stray-`desktop.lock` check
  is bundle-only and belongs in bucket 1; the two are in one test.

Bucket 3 is a statement about information content, not a recommendation to delete. All
three ride on fixtures that already exist, so removing them saves no meaningful time.

### The four uncovered properties

Independently confirmed. These are checked ONLY in the release run today:

1. `/static/app.css` and `/static/ha_fetch.js` returning 200 — no unpackaged test fetches
   `/static/*`.
2. The inverted-window rejection message (three raise sites, one assertion, packaged).
3. Unknown workspace → 404 at the WS handshake.
4. The absence of `M0[1-9]` placeholder labels.

## On the i18n brittleness

The user's reading is right, and the mechanism is worth stating precisely because the
brittleness and the strengthening are two different things.

**The brittleness.** `test_babel_locale_data_is_bundled` wants to know whether Babel's
CLDR `.dat` files reached the bundle. Its probe is to render a results page and grep for
month names. Both `monthname` call sites are now behind simulation guards, so on a
workspace with no simulation the page contains no month label at all — and the test's
positive assertions (`\bMar\b`, `\bmrt\b`) fail. That is what `f42690f` triggered. A
packaging assertion is coupled to every template and view-model change.

**The related weakness, which is the strengthening opportunity.** The negative assertion

    assert not re.search(r"\bM0[1-9]\b", page)

is *vacuously true* whenever the page renders no months — which is exactly the state the
guards now produce. It only has teeth when the positive assertions above it already
passed. So the check that catches the subtle failure (an over-aggressive CLDR trim
dropping `en.dat` while keeping `root`, which formats numbers identically) is the one most
easily silenced by an unrelated template change. Confirmed that `root` really does yield
`M01`/`M03`/`M10`, so the failure it guards against is real.

`tests/test_i18n.py` asserts the positive values (`month_abbr(3,"en")=="Mar"`, `"nl"=="mrt"`)
but never the `root`-fallback negative, in any environment.

**What could be strengthened** (options, not a decision):

- Add the `root`-fallback negative to `tests/test_i18n.py` as a direct assertion on
  `month_abbr` — e.g. that no supported locale yields an `M0\d` abbreviation. Cheap, runs
  on every push, and unlike the packaged grep it cannot go vacuous, because it calls the
  function rather than searching a page that may contain nothing.
- Probe the bundle directly in the packaged test — call `month_abbr` inside the packaged
  interpreter, or assert the `.dat` files exist under `_internal`. Decouples the packaging
  assertion from templates; loses the end-to-end property.
- Seed the packaged fixture with enough data that a simulation exists, so the guarded nodes
  render. Truest to what a reader sees; makes a packaging smoke test depend on the
  simulation pipeline.

The first is orthogonal to the other two and could be done regardless of which probe the
packaged test ends up using.

## Current Status

Review complete; classification delivered. Nothing implemented. The decisions still open
are the same three the analysis left open (which probe to use, whether to add the four
uncovered properties as unpackaged tests, and whether packaging jobs should run more often
than on dispatch), plus the i18n strengthening above.
