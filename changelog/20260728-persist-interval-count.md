# Persist the dataset's interval count (followup I2)

## Task specification

The user asked to "compute and persist the number of intervals", closing followup **I2** in
`followups.md`: the workspace card's interval count is derived from SQLite metadata alone and can
be plainly wrong, not merely approximate.

## Background — what I2 actually is

Two code paths answer "how many simulation intervals does this dataset have", and they disagree:

* **The results screen** — `normalize.grid_report` (`app/domain/normalize.py:124`). It first
  narrows the window with `effective_window` (the intersection of the *energy* series' coverage,
  clipped to the requested bounds), then picks the grid with `choose_grid`, which takes the
  coarsest resolution among energy series that `covers(window)`. Interval count is
  `effective_span // grid_s`.
* **The workspace card** — `workspaces._data_facts` (`app/workspaces.py:265`). It has only
  metadata: the `datasets` row's stored window and the `series_meta` rows. It takes
  `max(resolution_s)` over *all* energy series with no coverage filter, and divides the *stored*
  window span by it.

So the card can differ on two independent counts, not one as `followups.md` states:

1. **No `covers()` filter.** A short auxiliary energy series drags the reported grid coarser.
2. **Stored window, not effective window.** The same short series also shrinks
   `effective_window`, so the real run covers far less than the stored window advertises.

## Measured — I2's stated cause is wrong, and so was my first reading

Both were checked against the running code (scratchpad probes, then pinned as tests). On I2's own
fixture — 900 s grid over two days plus a 3600 s solar series over three hours:

| | resolution | intervals |
|---|---|---|
| `grid_report` (the real run) | 3600 s | **3** |
| `_data_facts` (the card) | 3600 s | **48** |

* **I2's claim that the results screen computes "900 s / 192" is false.** That is
  `choose_grid` against the *raw* window, which nothing calls. `grid_report` clips to
  `effective_window` first, and once the window is the 3 h overlap the solar series *does* cover
  it — so 3600 s is the correct grid and the card's resolution agrees.
* **My own step-1 hypothesis (900 s / 12) was also wrong**, for the same reason: I applied the
  clipped window to the unclipped grid.

So on this fixture the divergence is entirely the **window** (stored fetch bounds vs. the energy
coverage intersection), not the missing `covers()` filter.

The `covers()` filter is not, however, a non-issue. Probing the corners found exactly one shape
where the *resolution* diverges too: an **empty** energy series carrying a coarse `resolution_s`.
`effective_window` skips it (its `coverage()` is None) and `choose_grid` drops it (`covers()`
false), but the card's unfiltered `max()` counts it — 3600 s / 48 against a true 900 s / 192.

Conclusion: two independent causes, both real, neither as described. Persisting *both* the grid
and the count covers both, which is what the plan already did for a different reason (the card
renders count and resolution as one sentence).

## Decisions

* **Persist `grid_s` and `n_intervals` on `datasets`**, computed by the same helper the results
  screen uses, rather than re-deriving from metadata at read time.
* **`upsert_series` reloads its sibling frames and recomputes** (user's choice), so the single-slot
  merge path cannot leave a stale count. Costs an npz read per sibling on an action that already
  does network I/O.
* **Pre-migration rows fall back to today's derived value** (user's choice) — NULL count means the
  old code path runs, so no existing workspace loses its card line; it self-corrects on next load.
* **One helper, `normalize.grid_facts`**, extracted from `grid_report` and shared, so the card and
  the results screen cannot drift apart again. This is the part that actually closes I2, as opposed
  to fixing today's two symptoms.

## Obstacles

* **The stated cause was wrong, and I repeated the mistake.** Both `followups.md`'s numbers and my
  own first correction were arrived at by reading `choose_grid` and `effective_window` separately
  and combining them by hand. Only running the fixture gave the right answer. Solution: probe
  first, then write the test — the two scratchpad probes are what produced the table above.
* **`upsert_series` holds one frame, not the dataset.** Solution: extract the frame-restoring loop
  out of `load_latest` as `_restore_frames(conn, dataset_id)` and call it from the merge path,
  after `_insert_series_meta` so it reads the merged set.
* **The size depends on the window that the same function may widen.** Solution: track
  `final_window` through the merge branch and recompute after the widening UPDATE, not before.
* **`datasets` had no migration list** — only `series_meta` did. Solution: generalise `_migrate`
  to walk a `(table, columns)` list.

## Files modified

* `app/domain/normalize.py` — added `grid_facts(frames, window) -> (grid_s, intervals)`, the
  effective-window/choose-grid/count triple; `grid_report` now calls it instead of inlining it.
* `app/dataset.py` — `grid_s` / `n_intervals` columns on `datasets`, plus `_DATASETS_ADDED_COLUMNS`
  and a `_migrate` generalised over both tables; both save paths compute and store the pair;
  `_restore_frames` and `_store_grid_facts` extracted; module header and `upsert_series` docstring.
* `app/workspaces.py` — `_data_facts` reads the stored pair, with the old derivation kept as the
  documented NULL fallback; module header's I2 caveat replaced; `DataFacts` docstring corrected
  (`intervals` is no longer `window / resolution`, and explicitly is not reconcilable with it).
* `app/workspace_list_view.py`, `app/main.py`, `app/templates/_workspace_card.html` — the three
  cross-references to the old caveat.
* `tests/test_workspace_data.py` — new group of 8: a parametrised card-vs-`grid_report` agreement
  check over four dataset shapes (both measured-divergent ones and two ordinary ones), the naive
  derivation named as the wrong answer, the merge path, the NULL fallback, and the `datasets`
  migration against a hand-built pre-change table.
* `followups.md` — I2 struck through and closed, with the corrected diagnosis recorded.

## Verification

* Full suite: **1218 passed, 2 skipped** (was 1210 + 2; the 2 skips are the known live-HA suite).
* The four defect tests were confirmed to FAIL against the old behaviour, by forcing the fallback
  branch — they report 48 where the run has 3, i.e. they fail with the original symptom rather
  than for an unrelated reason. The fallback and migration tests correctly still pass under that
  forcing, since they test the legacy path.
* Rendered the card through the real route: it reads "3 intervals · hourly" where it previously
  read 48. Plural selection and the nested resolution message both still work.

## Current status

Done. Not committed — the working tree also carries an unrelated untracked changelog
(`20260728-results-stale-dimming.md`) from earlier work, so staging is left to the user.

Deliberately not done, and available if wanted:

* **No backfill for existing rows.** They fall back to the old (wrong) derivation until their next
  load. A startup pass could recompute them at the cost of reading every workspace's frames once.
* **`grid_report` still recomputes rather than reading the stored pair.** It has the frames in
  hand and needs the per-series table anyway, so there is no saving; but it does mean the stored
  value is never read back on the results path, and so a stale one would not be noticed there.
* **The stored pair can go stale if a `.npz` is edited outside the app.** Nothing does this today.
