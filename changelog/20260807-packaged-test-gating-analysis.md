# Analysis: which packaged-only tests could also run unpackaged

**Status: analysis only. No code or test changes were made for this.** Written to be picked up on
a separate branch. Nothing here has been implemented.

## Task Specification

While investigating a Linux failure in the Release workflow (see Background), the user asked two
questions:

1. Why did PR #16's CI pass while the release workflow failed — what runs in one and not the
   other?
2. Review the skipped tests and report which of them could also run in a non-packaged
   environment.

This file answers both and lists the options that follow. It does not choose between them.

## Background: how this came up

Three separate regressions surfaced on the `worktree-network-troubleshooting` branch, all
traceable to PR #16 (merged as `6aa4b65`), none caused by that branch's own commits:

- `app/static/app.css` stale — first introduced by `d212314`, compounded by `9bb3f4d`/`2effe3f`.
  Fixed in `735371c` (see `changelog/20260806-backend-tls-system-trust.md`).
- The Windows build failing on a missing `tzdata` — introduced by `bf562f5`. Fixed in `90cd91c`
  (see `changelog/20260806-windows-tzdata.md`).
- `tests/test_packaged.py::test_babel_locale_data_is_bundled` failing in the Linux job of Release
  run 31157183603 — introduced by `f42690f`. **Not fixed; it is the subject of this analysis.**

That third failure is the one worth generalising from, because the *reason it went unnoticed* is
structural rather than a one-off mistake.

## Why PR #16 was green and the release build was not

**It is not a different set of tests. It is the same tests, skipped.**

`.github/workflows/test.yml` runs a bare `uv run pytest` with no exclusions, so it COLLECTS
`tests/test_packaged.py`, `tests/test_appimage.py` and `tests/test_packaged_ingest.py`. All three
carry a module-level gate:

    pytestmark = pytest.mark.skipif(
        BINARY is None,
        reason=f"set {_ENV_BINARY} to the built bundle's executable to run the packaged checks",
    )

`BATTERY_SIM_PACKAGED_BINARY` and `BATTERY_SIM_APPIMAGE` are set only by the Release workflow's
Linux job, after it has built the artifacts:

    BATTERY_SIM_APPIMAGE: dist/Home-Battery-Simulator-x86_64.AppImage
    BATTERY_SIM_PACKAGED_BINARY: dist/battery-sim/battery-sim

In ordinary CI neither exists, so all 23 skip. Verified by running the suite with `-rs`: the skip
reasons are 8 × `test_appimage.py`, 10 × `test_packaged.py`, and 5 × `test_packaged_ingest.py`
(the last as one parametrised entry reported as `[5]`).

The Linux job runs 28 rather than 23 because `test_packaged_ingest.py`'s five tests are
parametrised over BOTH artifacts once both env vars are set (`onedir` and `appimage`).

**Correction to earlier statements in this session.** The "23 skipped" reported after every local
suite run was repeatedly attributed to the live-HA suite. That was wrong, and self-contradictory
besides: `tests/test_ha_live.py` is excluded by `--ignore`, so it is not collected and cannot be
among the skips. The 23 are these packaging tests.
`changelog/20260806-backend-tls-system-trust.md` has been corrected in place.

**The same mis-attribution appears more widely and predates this session** — e.g.
`20260805-cost-toggle-changes-coupling.md` ("24 skipped … the live-HA suite, as always"),
`20260806-default-spot-price-source.md`, `20260805-minor-ui-tweaks.md`. Older entries reporting
**2** skips are plausibly accurate (the live-HA suite is 2 tests when collected); the recent
entries reporting 23-24 are not. Also relevant:
`memory/battery-sim-test-suite-facts.md` records "only the live-HA suite is skipped", which is
wrong on the same point. Left uncorrected here — auditing past changelogs was outside what was
asked, and is listed as a possible follow-up rather than done silently.

So PR #16 was green because the single test its change broke never executed. `f42690f` removed an
unconditional month-label node; the assertion depending on it runs only against a built bundle,
and nothing built one between that merge and the user's dispatch a day later.

## The classification

23 gated tests. Classified by whether the property asserted is meaningless without a bundle (A),
is application behaviour a source checkout exhibits identically (B), or is a mix (C).

Method: each test's assertions were read mechanically rather than inferred from its name, and
every claim of "already covered" was checked by locating the covering test. A subagent produced
the first pass; the four claimed gaps and the `desktop.lock` classification were then re-verified
directly, which corrected two of its conclusions (noted below).

### Class A — intrinsically packaging-only (14 tests)

Nothing to move. These read files inside the bundle, or observe the `sys.frozen` branch.

`tests/test_appimage.py` (7): `test_the_typelibs_are_bundled`,
`test_pygobject_is_inside_the_frozen_bundle`, `test_optparse_is_bundled`,
`test_the_webkit_helper_processes_are_bundled`, `test_the_webkit_and_gtk_libraries_are_bundled`,
`test_the_library_closure_is_self_contained`, `test_apprun_exports_the_lookup_variables`.

`tests/test_packaged.py` (3): `test_the_build_info_module_is_readable_as_a_FILE_in_the_bundle`,
`test_the_bundle_carries_no_development_directories`,
`test_the_data_directory_is_per_user_and_not_inside_the_bundle`.

### Class B — the property is already covered unpackaged (5 tests)

These assert application behaviour that ordinary CI already verifies. Their only distinct value
is showing the bundle carries what is needed.

| Packaged test | Already covered by |
|---|---|
| `test_babel_locale_data_is_bundled` | `tests/test_i18n.py:576` (`month_abbr(3,"en")=="Mar"`, `"nl"=="mrt"`), `:586` (`test_the_number_filters_are_bound_to_their_own_locale_on_every_environment`, whose line 594 asserts the `monthname` filter per locale), `:650` (`test_the_rendered_dutch_pages_use_dutch_number_conventions`, the IDENTICAL grouping regexes end-to-end on the real routes) |
| `test_the_dutch_message_catalog_is_bundled` | `tests/test_no_english_leakage.py` (renders `/w/{id}/results` under `Cookie: lang=nl`, asserts English absent) |
| `test_templates_and_the_shipped_data_render_a_results_screen` | `tests/test_results_route.py`, `tests/test_smoke.py:198` |
| `test_level2_a_recorded_ha_batch_replays_and_persists` | `tests/test_ingest_ws.py` — the packaged test's own docstring says it mirrors `test_valid_ingest_persists_and_reports` |
| `test_level2_the_replayed_rows_are_queryable_afterwards` | `tests/test_ingest_ws.py:287-295` — the three assertions are verbatim identical |

`test_it_serves_the_workspace_list` is also class B (`GET /` → 200, body contains `<html`), and is
trivially covered by any unpackaged server test; it is cheap enough that moving it buys nothing.

### Class C — mixed; do not move wholesale (3 tests)

- `test_static_files_are_bundled` — the 200 is app-level; the `len(body) > 1000` guard is a
  bundle check ("the real asset came along, not a stub").
- `test_the_appimage_serves_over_http` — `GET /` → 200 is app-level; the stray-`desktop.lock`
  check is bundle-only.
- `test_level1_a_raw_websocket_upgrade_completes` — **worth respecting.** `TestClient` speaks
  ASGI directly and never performs an HTTP upgrade, so there is no unpackaged equivalent even in
  principle without spawning real uvicorn. `tests/test_packaged_ingest.py`'s module docstring
  argues this itself, and the argument holds.
- `test_the_single_instance_lock_records_the_live_port` — **reclassified from A during
  verification.** `tests/test_desktop.py:1186-1187` already asserts, unpackaged, that
  `desktop.lock` exists in the launcher's data dir and records the right port. Only the exact
  `set(state) == {"port", "pid"}` key set is unique to the packaged run.

## Properties checked ONLY in the packaged run

Four, each verified by grep rather than assumed:

1. **`GET /static/app.css` and `/static/ha_fetch.js` returning 200.** No unpackaged test fetches
   `/static/*` at all. The two hits elsewhere (`tests/test_workspace_data.py:382`,
   `tests/test_workspace_results.py:824`) assert the `href` STRING appears in HTML, not that the
   route serves anything. A real gap: the StaticFiles mount could break and only a release build
   would notice.
2. **Inverted-window header → `"window end must be after start"`.** Raised at
   `app/ingest_ws.py:199`; asserted only at `tests/test_packaged_ingest.py:259`.
   `tests/test_ingest_ws.py` has neighbouring rejection tests (`test_done_before_header_is_rejected`,
   `test_rows_before_series_is_rejected`, `test_unknown_series_is_rejected`) but not this one.
3. **Unknown workspace → 404 at the WS handshake.** `deps.get_workspace` rejecting before
   `ws.accept()`. Not asserted unpackaged.
4. **Absence of root's `M0[1-9]` placeholder month labels.** `tests/test_i18n.py` asserts the
   positive values (`Mar`, `mrt`) but not this negative, which is the specific way an
   over-aggressive CLDR trim can look right and be wrong.

## The structural problem, stated separately from the fix

Two distinct issues, worth not conflating:

**(a) Some packaged tests probe BUNDLE properties through APPLICATION surfaces.**
`test_babel_locale_data_is_bundled` wants to know whether Babel's CLDR `.dat` files reached the
bundle. Its chosen probe is to render a results page and grep for month names. That couples a
packaging assertion to every template and view-model change — which is exactly how `f42690f`
broke it, by putting the month node behind `{% if results.monthly_saved_eur %}` for a workspace
with no simulation. Its docstring's reasoning about `root` vs `en` fallback remains correct; only
the probe is fragile.

**(b) The packaged suite runs only in a dispatch-only workflow.** Nothing built Windows or Linux
artifacts between PR #16 merging and the user's dispatch, so three regressions accumulated and
surfaced together, each attributed on first sight to whichever branch happened to trigger the
build. This is also why the tzdata break hid.

These have different remedies and need not be solved together.

## Options (not decided)

On (a) — the fragile probe:

- Probe the bundle directly instead: call `month_abbr` inside the packaged interpreter, or assert
  the CLDR `.dat` files exist under `_internal`. Decouples it from templates; loses the
  end-to-end property.
- Keep the page-rendering probe but seed the fixture with enough data that a simulation exists,
  so the guarded node renders. Truest to "what a reader sees"; makes a packaging smoke test
  depend on the simulation pipeline.
- Drop the month assertions and rely on `tests/test_i18n.py`, keeping only the number-separator
  check. Cheapest; gives up the `root`-fallback detection the docstring argues for.

On the four uncovered properties: add them as unpackaged tests. Small, and each catches its
regression on every push instead of days later. `tests/test_smoke.py::base_url` already spawns a
real uvicorn subprocess with en/nl page fixtures — structurally identical to `packaged_server`,
differing only in what it launches — so a static-mount test has an obvious home. The two ingest
gaps belong in `tests/test_ingest_ws.py`; the `M0[1-9]` negative in `tests/test_i18n.py`.

On (b) — the feedback delay. This is CI policy and the user's call, not a code fix:

- Run the packaging jobs on pushes to master. Fastest feedback; four runners per push.
- Run them nightly, or weekly. Cheaper; bounded delay.
- Leave dispatch-only and accept that packaging regressions surface at release time.

## Note on scope

None of this is implemented. The one thing that IS currently broken —
`test_babel_locale_data_is_bundled` failing in the Linux job — is left failing deliberately, since
fixing it means choosing among the options above. The Release run 31157183603 was otherwise
green: the version gate, Windows, macOS arm64 and macOS x86_64 all succeeded, and 27 of the
Linux job's 28 verification tests passed.
