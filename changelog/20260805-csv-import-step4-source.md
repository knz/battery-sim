# CSV import — step 4: `CsvSource`

Implements step 4 of `changelog/20260805-csv-import-implementation-brief.md`. Steps 1 (uploads
storage) and 2 (the pure parser) were already built and reviewed; this step is the adapter that
joins them to the slot-first source registry.

## Task specification

From the brief, step 4, plus its cited specs (`08-architecture.md` §5.1 `CsvSource` bullet,
`05-data-formats.md` §4.2a, `15-data-quality-and-limits.md` §7.3 and §7.4):

- New `app/sources/csv_source.py` with `kind="backend_load"`, registered in `ALL_SOURCES`.
- `available_for(slot)` → energy slots only, never `price_spot` (D-PRICE).
- `load(slot, window)` reads the slot's `(upload_id, column, unit)` binding, following
  `EnergyChartsSource`'s keyword-only-extras precedent. The `DataSource` protocol signature is
  not widened.
- Mirror `label`/`blurb` into `app/sample_data.py` `_SOURCE_STRINGS` with `_N(...)`.
- Tests mirroring `tests/test_sources.py` / `tests/test_slot_load.py`.

Out of scope, and untouched: `app/uploads.py`, `app/domain/csv_wide.py`, the upload routes
(step 3, being built concurrently by another agent), the binding store and reify path (step 5),
the drawer JS and templates (step 6). `app/main.py` was deliberately not modified.

## High-level decisions

1. **Windowing is done by the source, not the parser.** `csv_wide.column_frame` returns a frame
   covering the whole file — that is by design, since the parse is per-file and the window is
   per-load. So `CsvSource.load` slices the frame to the half-open `[start, end)` window itself,
   with `np.searchsorted` on the already-ascending index. Half-open matches the rest of the
   pipeline (`EnergyChartsSource` filters bridge points with `start <= p.start < end`).
2. **A window outside the file's coverage yields an empty frame, not an error and not zeros.**
   §7.4 says "clamp to coverage and say so; never pad with zeros". Clamping is what the slice
   does; the "say so" belongs to the assembled-dataset checks (§7.3 check 5, window overlap),
   which see the frame's actual coverage. Raising instead would be wrong: a partly-covered window
   is a normal thing to ask for and the intersection is the answer.
3. **`resolution_s` is re-inferred on the slice, not inherited from the file.** The file-level
   value is the modal spacing of the whole file; a window can select a stretch with different
   spacing (or too few rows for a modal answer). `infer_resolution_s` is reused, per the brief.
4. **The binding is a keyword-only extra with an explicit, named error when absent.** Step 5 has
   not landed, so nothing threads a binding yet. `load` therefore raises a
   `CsvBindingError` naming step 5 when called without one, rather than returning an empty frame
   or guessing a column. The two existing call sites (`app/main.py` `_load_backend_frame` and
   `load_slot`) call `source.load(slot, win)` with no extras, so this is the error a caller hits
   today; a TODO in the module comment names them.
5. **The gate is `slot.kind == "energy"` AND `slot.name not in _EXCLUDED_SLOTS`**, where the
   exclusion holds `power_grid`. The kind half is read off `series_vocab.SlotSpec`, not a name match
   against `price_spot`. The exclusion was added after review asked about `power_grid`:
   `docs/specs/05-data-formats.md` §4.1 gives that slot kind **power** ("Signed W, import
   positive"), but `SeriesKind` is only `"energy" | "price"`, so `series_vocab.py:109` records it as
   `"energy"` with a `# signed W` comment — a lossy encoding my gate inherited. §6.17's
   `power_energy_consistency` (`docs/specs/14-diagnostics.md:283`) computes
   `power_mean_w / 1000 * dt_h`, confirming the slot means **mean watts**, while `column_frame`
   hardcodes kWh-per-interval and `UNIT_FACTORS` has no watt member. A column of `1500 / -800` would
   therefore have been persisted as a kWh series with its numbers unchanged. §6.17 is not implemented
   yet, so nothing reads the slot today — the exclusion prevents storing a wrongly-scaled series in
   the meantime. Supporting it properly needs a watt unit (whose `W → kWh` factor needs the interval
   length, i.e. `resolution_s`, which is `None` for an irregular file) plus a drawer radio; that is a
   feature, not a fix.

   The earlier rationale — "a future energy slot is offered CSV automatically" — is **withdrawn**: it
   is precisely what produced this defect. A new slot now needs a deliberate answer.
6. **Warnings are returned, not dropped.** `column_frame` yields `CSV_GAP_CELLS` and
   `CSV_DST_AMBIGUOUS_HOUR`. The `DataSource.load` contract returns only a frame, so `load`
   discards them and a second entry point, `load_with_warnings`, returns both. Gap counts are
   recomputed on the *slice* (a gap outside the window is not this load's gap); the DST warning's
   day list is likewise filtered to the window. Step 5 should call `load_with_warnings` so §7.3's
   quality box can name the October day.

## Files modified

- **`app/sources/csv_source.py`** (new) — `CsvBinding`, `CsvBindingError`, `CsvSource`,
  `slice_to_window`.
- **`app/sources/registry.py`** — `CsvSource()` appended to `ALL_SOURCES`, with a comment on why
  it goes last.
- **`app/sources/__init__.py`** — re-export, matching the other sources.
- **`app/sample_data.py`** — label/blurb mirrored into `_SOURCE_STRINGS` for pybabel.
- **`app/locales/{nl,en}/LC_MESSAGES/messages.{po,mo}`** — the blurb's msgid added and translated
  (the label `"Upload CSV"` was already in both catalogs from the pending placeholder), then
  recompiled. Done here rather than left to step 6 because the roster template already serialises
  every source's translated label and blurb into the drawer's `data-slot-sources` JSON, so the new
  strings reach a Dutch page as soon as the source is registered — not only once step 6 builds the
  drawer controls.
- **`tests/test_sources.py`** — `test_energy_slot_offers_ha_only` became
  `test_energy_slot_offers_ha_then_csv`; an energy slot now lists two sources.
- **`app/static/ha_fetch.js`** — `renderSourceList` filters `csv_upload` out of the live radio list
  (`PENDING_SOURCE_KEYS`) and renders the pending stub only for the slots that actually offer CSV.
- **`tests/test_smoke.py`** — the backend-source selector in
  `test_ha_fetch_scopes_its_slot_store_per_workspace` retargeted at `price_spot` by name; a note on
  `test_new_pending_controls_marked` for steps 6/7.

### Correction to an earlier version of this file

An earlier revision claimed `tests/test_sources.py` was the only test needing an update. **That was
false and was found by review, not by me.** Registering the source changed the roster that two other
consumers read indirectly:

- `tests/test_smoke.py:583` selected a backend source with
  `.slot-source-btn[data-slot-sources*='backend_load']").first`, which meant "the first slot with
  any backend source". That was `price_spot` only while `price_spot` was the only backend-source
  slot; with CSV registered for the energy slots, `.first` became `grid_import_t1`, whose drawer has
  no `energy_charts` radio, and the Playwright test failed on a 30 s timeout. The Playwright smoke
  tests **do** run in this repo (only the live-HA suite is skipped), so this was a live failure, not
  a dormant one. `tests/test_smoke.py` is now in the targeted set for this work.
- `app/static/ha_fetch.js:945` appended the disabled `csvPendingOption()` stub unconditionally, so
  every energy slot rendered "Upload CSV" **twice** (a live enabled radio from the registry plus the
  pending stub), while `price_spot` rendered only the stub — which misrepresents D-PRICE, where CSV
  is deliberately unavailable rather than pending.

The lesson, recorded because it generalises: adding a row to `ALL_SOURCES` changes a
**server-rendered attribute** (`data-slot-sources` in `_data_roster.html`) that both JS and
Playwright selectors read by substring. Grepping for the registry function found neither consumer;
grepping for the attribute would have found both.
- **`tests/test_csv_source.py`** (new) — registry membership per slot kind, descriptor, windowing
  matrix (fully inside, partial both ends, wholly before/after, exact bounds), unit conversion,
  warning filtering, and the error paths (no binding, unknown upload, missing file, unknown
  column, cumulative column, bad unit, price slot).

## Review findings and what changed

A review of the first revision confirmed the core windowing, D-TZ round-tripping, D-PRICE gating and
`.mo` currency, and found the following. All are fixed unless marked otherwise.

- **Broke a live Playwright smoke test, and two indirect roster consumers went unchecked.** See the
  correction section under "Files modified".
- **Every energy slot rendered "Upload CSV" twice**; `price_spot` rendered only the pending stub.
  Fixed in `ha_fetch.js` by filtering the live radio and making the stub per-slot.
- **A selected CSV radio would have killed an entire fetch.** `ha_fetch.js` stages `backend_load`
  slots by kind, so a bindingless CSV slot → `CsvBindingError` → `IngestError` → the whole
  all-or-nothing fetch fails, HA slots included. The JS filter above is what makes this unreachable;
  it is documented at the TODO in `csv_source.py` as a guard that must not be lifted before step 5.
- **Sub-second window bounds truncated inconsistently, and my docstring's justification was false.**
  Both bounds floored, so `[00:00:00.5, 01:00)` returned a sample outside the window and
  `[00:00, 00:00:00.5)` dropped one inside it — while the docstring claimed a fractional bound
  "cannot select a different set of samples". Reachable via `_parse_window`'s
  `datetime.fromisoformat`. Fixed by rounding **both bounds up**, derived rather than guessed: for
  integer-second samples, `s >= start` ⟺ `s >= ceil(start)` and `s < end` ⟺ `s < ceil(end)`. My
  first attempt (floor the start, ceil the end, by analogy with §7.4's clamping) was wrong at the
  start and caught by the new test.
- **My D-DST premise was too broad, in two places.** I wrote that "a full-day October Amsterdam file
  yields a duplicate index entry". Checked directly: a chronological 24-row hourly file yields **no**
  duplicate — its single `02:00` local row resolves to `00:00Z` and `01:00Z` is simply absent, a
  missing hour rather than a doubled one (1 row flagged ambiguous). A duplicate needs a genuine
  25-row export that writes the repeated hour twice (2 flagged). The tie-handling is therefore
  load-bearing only for the 25-row case. Corrected in `csv_source.py`; **the same overstatement is in
  `app/domain/csv_wide.py`'s module docstring and in `20260805-csv-import-step2-parser.md`, and I did
  not fix it there** — step 2 is outside this step's scope and another agent's territory. Flagged for
  whoever owns it, since the false premise will otherwise propagate.
- **Two surviving mutants.** `if binding.unit not in UNIT_FACTORS:` → `if False:` survived, because
  `column_frame` also raises `bad_unit`; now pinned by deleting the file and asking for `MWh`, which
  distinguishes the early check (`bad_unit`) from the late one (`FileNotFoundError`). The second,
  `hi = max(hi, lo)`, survived because it was **dead code**: `searchsorted` is monotonic in its
  target, so `end < start` already gives `hi <= lo`, and both negative- and zero-width numpy slices
  are empty. No test could kill it, so it was **removed** rather than pinned, with the reasoning kept
  as a comment. The end-`==`-start case is now parametrized anyway.
- **`CsvBindingError`'s docstring claimed "both surface as a 4xx".** It does not — `load_slot`'s bare
  `except Exception` maps it to **502**, "bad gateway" for an unconfigured slot. Docstring corrected;
  the 400 mapping is recorded as step 5's job, since `app/main.py` is not this step's file.
- **Count discrepancy:** the brief said 33 tests, the file had 32. Now 43, stated consistently.
- Left as-is by the reviewer's own judgement: `slice_to_window` on a non-ascending index is silently
  wrong, but the sorted-input precondition is documented (`parse_wide_csv` sorts), so it is a
  documented contract rather than a defect.

## Obstacles and solutions

- `column_frame` returns whole-file frames, so a naive `load` would ignore the window entirely and
  merge a year of data into a one-week dataset. Solved by slicing in the source (decision 1) and
  pinning it with the windowing matrix in the tests.
- The October DST fold makes the index non-strictly-increasing (a duplicate entry, documented in
  `csv_wide`'s module docstring). `np.searchsorted` with `side="left"`/`"right"` handles ties
  correctly — both duplicate rows fall inside a window containing that instant — so no
  deduplication is needed and none is done.

## Current status

Done, reviewed, review defects fixed. `app/sources/csv_source.py` + `tests/test_csv_source.py`
(43 tests); `tests/test_sources.py`, `tests/test_smoke.py` and `app/static/ha_fetch.js` updated for
the roster change.

Test command and result:

```
uv run pytest tests/test_csv_source.py tests/test_sources.py tests/test_slot_load.py \
  tests/test_uploads.py tests/test_csv_wide.py tests/test_upload_routes.py \
  tests/test_no_english_leakage.py tests/test_i18n.py tests/test_workspace_data.py \
  tests/test_ingest_ws.py tests/test_ingest.py tests/test_smoke.py -q
→ 641 passed, 1 warning in 65.79s
```

**For step 5:** `load` takes `binding=CsvBinding(upload_id, column, unit)` and
`workspace_id=...` as keyword-only extras. Neither `_load_backend_frame` nor `load_slot` in
`app/main.py` passes them today, so step 5 must thread both through — that is the one change
outside this step that the source needs to become reachable. Use `load_with_warnings` there if
the quality box is to report §7.3's flags.
