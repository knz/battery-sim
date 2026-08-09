# Demo dataset: freeze a 3-month period into the source tree

## Task specification

Original request (verbatim intent):

- Take note of the data directory used by the server when run from this repo / cwd.
- Create a "demo" dataset for the app by freezing / embedding a 3-month period taken
  from the data already loaded in the local data dir, into the source code.
- The same frozen dataset could plausibly serve as a seed for existing smoke /
  integration tests.
- Do the exploration in a new git worktree, which nonetheless needs access to the data
  directory of the main project checkout.

Status of scope: exploratory. No implementation approach has been approved yet; this
changelog is being written before any code changes, per AGENTS.md.

## Environment notes

### Data directory

- Resolution lives in `app/config.py`: `BATTERY_SIM_DATA_DIR` if set, otherwise `./data/`
  beside the checkout. `app/desktop.py::resolve_data_dir()` sets the env var to a per-user
  directory for the packaged desktop launcher; `tests/conftest.py::_isolate_data_dir` does
  the same for tests.
- For the server run from the main checkout, that resolves to
  `/home/kena/src/battery-sim/data/` (~2.5 MB total).

Contents observed in the main checkout:

```
data/config.toml                     installation_id only
data/feature_interest.db             64 KB sqlite
data/local/simconfig.json            workspace "local" sim configuration
data/local/series/*.npz              per-series arrays (see below)
```

Series present under `data/local/series/`:
`grid_import_t1`, `grid_import_t2`, `grid_export_t1`, `grid_export_t2`,
`solar_production`, `price_spot`, `price_spot_min`, `price_spot_max`.

Storage layout is documented in `app/dataset.py` — one `.npz` per series under
`<data_dir>/<workspace>/series/<name>.npz` — and `app/simconfig_store.py` for
`<data_dir>/<workspace>/simconfig.json`.

### Worktree

- Worktree: `.claude/worktrees/demo-dataset`, branch `worktree-demo-dataset`.
- A worktree has its own (empty) `data/`. Rather than copying the data dir, the worktree
  will read the main checkout's data by exporting
  `BATTERY_SIM_DATA_DIR=/home/kena/src/battery-sim/data`. Any run that could write to it
  should use a copy instead, to avoid mutating the user's real workspace.

## Investigation findings

### The `.npz` files are not self-sufficient

The arrays carry no metadata at all: each `.npz` holds exactly `index_s` (int64 epoch
seconds, interval start, UTC), `values` (float64) and `quality` (uint16). The slot length
(`resolution_s`), the series `kind`, the coverage window and the fetch provenance all live
in SQLite (`datasets`, `series_meta` in `app/dataset.py`), alongside the `workspaces` index
row (`app/db.py`) and `workspace_state.source_generation`.

Critically, `series_meta.path` is stored as an **absolute** string (`app/dataset.py:277`),
so the SQLite half is not relocatable — committing a `data/` tree verbatim would leave the
rows pointing at the original machine's paths. `_restore_frames` skips rows whose file is
missing *silently*, so that failure mode presents as a mysteriously empty dataset rather
than an error. This rules out "commit the data dir as-is" and forces a loader that
regenerates metadata via `dataset.save_dataset()` at whatever data dir is active.

`app/sample_data.py` is unrelated to this work: it is a static view-model of placeholder
numbers from the UX wireframes, not a dataset. The demo dataset is a new thing beside it.

The closest existing precedent is `tests/test_smoke.py:1692`
`_seed_reconstructable_dataset()`, which hand-builds two synthetic 48-hour frames because
"there is no browser path that produces a grid meter". A demo dataset generalises exactly
that helper to a real, committed, multi-month set.

`docs/specs/followups.md:611` already asks for this: "A real fix needs the fixture to seed
both a known dataset and a known config".

### Window selection

Series coverage differs. Meters (`grid_import_t1/t2`, `grid_export_t1/t2`) run 2024-08-05
→ 2026-08-05 hourly; `solar_production` only starts 2026-02-12; `price_spot` switches from
hourly to 15-minute on 2025-09-30. A 3-month window with every series present must sit
inside 2026-02-12 → 2026-08-05.

Chosen window: **2026-04-01 → 2026-06-30**. Measured properties: 2184 hourly slots per
energy series, prices at 15-minute resolution throughout, and zero gaps, zero NaNs and
zero quality flags across all six live series. Totals over the window — PV 2093.2 kWh,
grid import 511.8 kWh (T1 380.1 / T2 131.7), grid export 1433.8 kWh (T1 431.7 / T2 1002.1).

`price_spot_min.npz` / `price_spot_max.npz` are dead files: their names fail
`is_known_series`, so `_restore_frames` already drops them on load. They are excluded.

### Privacy exposure of the raw window

Measured before deciding on anonymisation:

- **Daily rhythm** is plainly legible — import is near zero 07:00–17:00 (PV covers the
  house) and peaks at 22:00, over an overnight baseload of ~0.4 kWh/h that is itself a
  fingerprint of always-on equipment.
- **Absence inference** is the significant exposure. Low-import days cluster into runs —
  2026-04-23 → 04-26 (4 days), plus 04-17 → 04-18 and 04-29 → 04-30 — and PV on those days
  is high (29–30 kWh), so weather does not explain them. That reads as a travel calendar
  tied to real dates. It survives date-shifting and rescaling; only smoothing removes it.
- **Scale**: ~5.6 kWh/day mean import, 2093 kWh PV over the quarter (implying roughly a
  6–8 kWp array), 3-phase 25 A. Narrows household type, not address.
- **Not exposed**: postcode is empty in `simconfig.json`; the `.npz` carry no entity IDs
  or names.

## High-level decisions

Answers given by the user, with the reasoning recorded:

1. **Window: 2026-04-01 → 2026-06-30.** Complete coverage of all six live series, clean
   quality, and 15-minute prices throughout.
2. **Anonymisation: smooth away the absence runs only.** Values stay exact everywhere
   except the identified low-import runs, which are filled with a typical-day profile.
   This removes the travel calendar — the exposure that mattered — while keeping rhythm,
   scale and price realism, and keeping the demo close enough to real data to be useful as
   a regression baseline. Rejected: embed-as-is (publishes the absence runs permanently);
   rescale+jitter (blurs scale but leaves the dips visible); maximum scrub (loses the
   check against real results and would need the 15-min price transition re-anchored).
3. **Storage: CSV + JSON manifest, materialized by a loader.** Text diffs and reviews in
   git; the loader converts to `SeriesFrame`s and calls `dataset.save_dataset()`, which is
   what regenerates the non-relocatable SQLite metadata correctly. Rejected: committing
   `.npz` (opaque in review) and shipping a pre-built SQLite file (absolute paths, and it
   would conflict on every schema migration).
4. **Prices: reuse the spot-price data already committed** under `app/data/spot_prices/`
   rather than duplicating ~8736 rows. The loader slices the window at materialization
   time. Keeps one source of truth, and leaves prices genuinely real even though the
   household series are partly smoothed.
5. **Surface: test seed *and* an explicit "load demo workspace" action in the UI.** No
   auto-creation on first run — declined so a user cannot mistake demo numbers for their
   own.

## Open questions

None blocking. Deferred detail: the exact smoothing method for the absence runs (see plan).

## Obstacles and solutions

**Branch base was not a descendant of master.** The worktree branched from `6aa4b65` (merge
of PR #16), which is a sibling of `master`/`origin/master` at `d84e898`, and `git fetch`
fails in this environment (no SSH to github). The user reported CI failures at the branch
root. Resolved by resetting the worktree to local `master` on the user's instruction; the
only work in progress was the untracked changelog, so nothing was lost.

**Export rebalancing was wrong and was removed.** The first anonymisation attempt adjusted
grid export to hold `consumption = pv + import - export` fixed after changing import.
Measurement killed it twice over: 130 of the 288 selected slots have *zero* export (they
are night hours, exactly where the import correction is largest), so the correction had
nowhere to go and silently vanished; and the identity does not hold in the source data
anyway — the raw window has 10 slots of negative implied consumption (min −2.26 kWh),
consistent with the meter and inverter not being clock-aligned. Export and PV are now left
byte-exact, and consumption is simply re-derived by the app.

**The median-of-medians profile was too low to be typical.** Summing 24 independently-taken
hourly medians gave 3.67 kWh/day against an all-days median of 5.05 — close enough to the
selected days' own 3.33 that the "smoothed" days stayed in the bottom of the distribution
and the detector re-flagged every day it had just replaced. Fixed by rescaling the profile
shape to the median daily total of the retained days.

**Identical replacement days were their own artifact.** With a single shared profile every
replaced day had exactly the same total (5.34 kWh), which advertises precisely which days
were scrubbed. Fixed with deterministic per-day scale factors sampled from the retained
days' interquartile band (fixed seed, so the committed CSVs are reproducible).

**The absence detector was measuring the wrong thing.** The original rule (low daily import
AND high PV) selects on sunshine as much as on occupancy, and left a sustained mid-April
low-import stretch untouched because those days were dull. Measuring the overnight baseload
(23:00–05:00 UTC, PV zero, weather factored out) showed why no sharper rule works: the
distribution is *continuous* — median 1.83 kWh, p10 1.02, min 0.90, no gap anywhere. There
is no away/home boundary to detect. Replaced with a deliberately blunt, uniform rule: the
quietest quarter of nights is resampled regardless of cause.

## Anonymisation: what it achieves, and what it does not

Stated plainly because it is easy to overclaim. After resampling:

- The multi-day low-import runs that read as travel (notably 2026-04-23 → 04-26) are gone.
- The overnight low tail lifts: min 0.90 → 1.18 kWh, min/median ratio 0.49 → 0.58.
- Replaced days spread across percentiles 21–75 with no two identical.

But the underlying distribution is continuous, so resampling a quantile *moves* the
boundary rather than eliminating it — a new bottom quartile always exists. This makes
occupancy inference harder and less confident; it does not make the data non-inferential.
The demo should be described as representative real data, not as anonymised data. Daily
rhythm and household scale remain visible by design.

## Verification performed

- **Prices**: the bundled `app/data/spot_prices/NL-2026.csv` covers the window at 15-minute
  resolution, all 8736 slots, and matches the source workspace's `price_spot.npz` to a max
  absolute difference of 0.0. Reusing them rather than duplicating is safe.
- **Reproducibility**: re-running the builder reproduces all five CSVs byte-identically
  (md5 verified).
- **Loader round-trip**: `demo.materialize()` into an isolated data dir yields six frames
  with correct names, kinds, resolutions (3600 s energy, 900 s price) and windows; totals
  match the builder's output.
- **Workspace card**: `list_summaries` reports `loaded=True`, grid consumption/production
  and PV all present, window 2026-04-01 → 2026-07-01, 2184 intervals at 3600 s.
- **Full pipeline**: `POST /w/{id}/results` over the window returns 200 and a rendered
  view-model — 91 days, 2184 intervals, self-sufficiency 57% → 89%, 374 kWh grid import
  avoided, 47 equivalent full cycles. The demo drives the real simulation end to end.

## Requirements changes

**The demo's battery and policies are overridden, not inherited** (user request, after the
first working version). The source workspace's config is carried into the manifest, but the
builder now replaces four fields:

- `charge_policy` P3 → **P1**, `discharge_policy` D3 → **D1**. Charge from solar surplus only,
  discharge to serve household deficit only — the appendix-A defaults, what a new workspace
  starts on, and per §6.6/§6.7 the pair that cannot conflict. The demo's flows therefore read
  as self-consumption rather than as price arbitrage.
- `usable_capacity_kwh` 15 → **6**, `max_charge_kw` / `max_discharge_kw` 7.0 → **5.0**. A
  commonly-sold domestic size, so the demo answers "what would a typical battery have done for
  this household" rather than showcasing an unusually large one.

Only the manifest changed; the five committed CSVs are byte-identical across all three
rebuilds (md5 verified), since the override touches config alone.

Effect on the headline figures over the window, all with the same series:

| config | self-sufficiency | grid import avoided | full cycles |
| --- | --- | --- | --- |
| P3/D3, 15 kWh / 7 kW (source) | 57% → 89% | 374 kWh | 47 |
| P1/D1, 15 kWh / 7 kW | 57% → 99% | 505 kWh | 37 |
| **P1/D1, 6 kWh / 5 kW (shipped)** | **57% → 92%** | **409 kWh** | **76** |

The shipped combination is the most representative of the three: a realistic battery working
hard (0.83 cycles/day) for a large but not implausible gain.

`test_the_demo_ships_the_intended_battery_and_policies` asserts all four values, since a
regeneration that dropped the override would otherwise change the demo's story silently with
every other test still passing.

## The demo title, translated at render time

**Request:** show the demo workspace's title in the active language.

The obvious implementation — translate at creation time, in `demo.materialize()` — was
rejected, and `app/workspaces.py:512` already explains why for `DEFAULT_TITLE`: a string
written to the database once cannot follow the user's later language toggle, so translating
it at write time gives a title that is wrong half the time rather than neutral all of it.
A user who loads the demo in Dutch and switches to English would keep a Dutch card.

**Chosen instead: translate at RENDER time.** The stored title stays the stable English
`demo.DEMO_TITLE`; `workspace_list_view.display_title()` returns a msgid in its place when the
stored title still matches, and the templates translate it in the request's locale. The title
therefore follows the language toggle in both directions, which write-time translation cannot
do. This reuses the `_msg.html` mechanism the role labels and figures already use rather than
inventing anything.

Three consequences worth stating:

- **The substitution stops once the user renames the workspace**, which is the behaviour you
  want — a name the user chose is theirs, not a label to translate.
- **The edit screen deliberately does NOT translate.** Its title is a rename field's `value`,
  posted back and saved; a translated value there would write the Dutch string into the
  database, which is precisely the write-time translation being avoided. Asserted by
  `test_the_edit_field_keeps_the_stored_title`.
- **Two constants hold the same string** (`demo.DEMO_TITLE` and
  `workspace_list_view.DEMO_TITLE_MSGID`), because the msgid must be a literal `_N(...)` call
  for `pybabel extract` to see it and `app.demo` must not depend on the view layer. If they
  drift the substitution silently stops firing, so a test pins them equal.

Accepted trade-off: a user who renames some *other* workspace to exactly "Demo household" gets
that one translated too. Harmless, and the alternative is a flag column on the `workspaces`
table to disambiguate a case with no consequence.

## UI surface

`POST /workspaces/demo` (same-site only, like every other creating route) materializes the demo
and redirects to `/w/{id}/results` — not the wizard, which is where `POST /workspaces` goes,
because a new empty workspace has nothing in it while the demo arrives with config and data
already present. The results screen is what the user pressed the button to see.

Each press creates an independent workspace rather than reusing or overwriting one, so the
action can never clobber a workspace the user has since edited.

The control appears twice on the workspace list: as a ghost button beside `[ + New analysis ]`
in the header, and — with a one-line explanation — in the empty state, which is where it
matters most, since a first-time user has no other way to see the app working without first
connecting Home Assistant or finding a CSV.

Auto-creating the demo on first run was declined by the user, so a user cannot mistake demo
numbers for their own.

## Files modified

- `changelog/20260807-demo-dataset.md` (new, this file).
- `scripts/build_demo_dataset.py` (new) — the committed generator: window slicing, quiet-night
  selection, resampling, CSV + manifest emission, and a before/after report.
- `app/data/demo/*.csv` (new, 5 files) — the committed energy series, 2184 hourly rows each.
- `app/data/demo/manifest.json` (new) — window, series roster, simconfig, provenance.
- `app/demo.py` (new) — the loader: manifest validation, CSV → `SeriesFrame`, price slicing
  from the bundled spot-price store, and workspace materialization.
- `app/main.py` — added the `demo` import and the `POST /workspaces/demo` route.
- `app/templates/workspaces.html` — the demo control in the header and the empty state.
- `app/locales/messages.pot`, `app/locales/{nl,en}/LC_MESSAGES/messages.{po,mo}` — two new
  msgids, with Dutch translations, extracted and compiled per `docs/maintainers/i18n.md`.
- `tests/test_demo.py` (new, 29 tests) — committed-artifact properties, loader round-trip,
  failure modes, the four route tests, and six for the render-time title translation.
- `app/workspace_list_view.py` — `DEMO_TITLE_MSGID` and `display_title()`; the card's title
  now goes through the latter.
- `app/results_screen_view.py` — the header title goes through `display_title()` too.
- `app/templates/_workspace_card.html` — title rendered through the `msg()` macro (heading and
  both delete-dialog `data-workspace-title` attributes).
- `app/templates/workspace_results.html` — header title rendered through `_()`.
- `tests/test_smoke.py` — one browser test for the demo button, added ALONGSIDE
  `_seed_reconstructable_dataset` rather than replacing it (that fixture asserts the §2′.8
  gate's lower bound with two flat series, which a three-month demo does not exercise).

## Test results

- `tests/` excluding the packaged/AppImage suites: **1792 passed, 2 skipped** (the skips are
  the live-HA suite, which needs a real Home Assistant).
- `tests/test_smoke.py` (Playwright): **69 passed**, including the new demo test.
- Screenshots of the empty state and the resulting populated results screen were taken and
  inspected; both render as intended in English, and the Dutch strings render with no English
  leakage.

## Current status

Complete and verified. All planned work is done: builder, committed artifacts, loader, UI
action with translations, and tests at three levels.

Deferred, not done — each is a judgement call worth making deliberately rather than silently:

1. **The window is fixed at 2026-04-01 → 2026-06-30 (a summer quarter).** It exercises PV
   surplus and export well, but never winter import-heavy behaviour, because
   `solar_production` in the source only begins 2026-02-12. A second demo covering a winter
   period would need either a different source workspace or accepting no PV series.
2. **The anonymisation attenuates rather than removes** — see the section above. If the demo
   is ever published more widely than this repository, that trade-off is worth revisiting
   with fresh eyes rather than inheriting this decision.
3. **No spec entry.** `docs/specs/` has nothing about a bundled demo dataset; the closest is
   `followups.md:611`, which asks for a fixture seeding "both a known dataset and a known
   config". Whether this warrants a spec section is the user's call.
4. **The builder's `--source` default is an absolute path** to the author's own checkout
   (`/home/kena/src/battery-sim/data/local`), which is right for a one-off regeneration tool
   but means the script is not runnable as-is by anyone else.
