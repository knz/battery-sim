# CSV import, step 8 — test the CSV import path

## Task specification

Step 8 of the CSV-import plan: cover the CSV import path, specified as validation-harness
fixtures **22** and **22a** (`docs/specs/16-validation-harness.md:182-219`), plus two coverage
gaps inherited from step 6's review and a check that the i18n suites still pass.

Steps 2, 3, 4 and 6 each shipped with their own tests, so this step is not "write the tests" from
scratch — it is closing what those tests do not reach. The first action was therefore a coverage
audit against the two fixtures, claim by claim, rather than writing anything.

## Findings before writing tests

### Open item 2 (register-detection threshold) is settled, and it settles the cumulative gap

The implementation brief left "the monotonicity threshold for register rejection" to the
implementer, and step 6 recorded a related gap: D-KIND says a cumulative column is "rejected on
selection", but the refusal happens in `column_frame` when the column is *loaded*, so a user
learns at fetch time. The brief said this wanted the false-positive question settled first.

It is settled, in `app/domain/csv_wide.py:140-196`. The threshold is a conjunction of three
conditions (≥12 finite samples, no decrease beyond 1e-9, total rise above 1e-6), and the residual
risk is documented as **measured, not assumed**: partial-day PV columns *are* refused — 5-minute
dawn-to-noon (72 samples), 15-minute dawn-to-solar-noon (28), even a 13-sample dawn ramp. A full
day passes only because the afternoon decline breaks monotonicity, "so the shape of the window,
not the shape of the data, decides. ... That is wrong and it will happen."

**This makes annotating the column selector the wrong fix.** Greying out, or marking as a
register, a column that the detector merely *suspects* would put a known-wrong verdict in front of
the user at the moment they are choosing — and for partial-day PV it would be wrong. The current
behaviour is the better of the two: rejection is loud, panel-local, recoverable, names the column,
and never produces a number. `csv_wide.py:182-187` reaches the same conclusion and names the two
better mitigations (compare the column's total against the window length; ask the user to confirm
on rejection) as deliberately not built.

Recommendation: **close the step-6 gap as "will not fix as specified"**, and treat D-KIND's
"rejected on selection" as satisfied in substance (the user is told, before any number exists) but
not literally. Fixture 22's *At column selection* part asserts rejection "in the drawer", which
today happens on Confirm→fetch rather than on picking the column in the select.

### A pre-existing feature gap: `DST_AMBIGUOUS` reaches the database and stops

Fixture 22a requires that the October ambiguous hour "carries the ambiguity flag" **and** that
"the flag is reported in the data-quality box naming the day". The first half holds and is tested
(`tests/test_csv_source.py:498-503`). The second half does not hold.

The chain is intact up to persistence: `CsvSource.load_with_warnings` sets `DST_AMBIGUOUS` per
sample and emits a `CSV_DST_AMBIGUOUS_HOUR` warning (`app/sources/csv_source.py:341-368`);
`app/main.py:1384-1390` stamps each warning with its series name specifically so "the box can name
the slot"; `app/dataset.py` persists them in `warnings_json` and reads them back into
`LoadedDataset.warnings`.

Then it stops. Nothing reads `LoadedDataset.warnings` — the only `.warnings` consumer in `app/` is
`app/params_view.py:552`, which is a different object (a validation result). And the box's own
flag counting covers two bits only:

    app/data_view.py:272  gaps   = _count_flag(frames, QualityFlags.GAP_FILLED)
    app/data_view.py:273  resets = _count_flag(frames, QualityFlags.RESET_CORRECTED)

`_count_flag` is generic, so adding a third is mechanically small, and `quality["gaps"]` /
`quality["resets"]` (`data_view.py:298-308`) show the exact `_msg_n` pattern a new field would
follow.

**This is pre-existing and not caused by the CSV work.** `git show 4a4fa10:app/data_view.py` has
the same two call sites, and `data_view.py`'s last commit is a docs reorganisation. It was simply
unreachable before: the wide-CSV path is the only producer of `DST_AMBIGUOUS`
(`app/domain/frames.py:41` says so). So the CSV work is what makes the gap observable, without
having introduced it.

This is a **feature** change, not a test change, and it is outside step 8's stated scope. Flagged
for a decision rather than silently absorbed.

### The state machine is spec-only, so several fixture-22 claims are unassertable as written

Fixture 22 asserts that `LOAD_FAILED` is not emitted, that `SOURCE_CONFIGURED` has not fired, and
that failures do not escalate into `DATA_ERROR`. `docs/specs/04-state-machine.md` specifies those
events, but **nothing implements them**: every occurrence in `app/` is a prose comment
(`app/ingest_ws.py:55,96,172`; `app/main.py:1331,1365,1506,1586,1715`), with zero occurrences in
`ha_fetch.js` or any template.

So these claims cannot be asserted as events. They can only be asserted through their observable
consequences — an error surfaced panel-locally, and nothing persisted — which is what
`tests/test_ingest_ws.py:386` already does for the all-or-nothing case. Step 8 will assert the
consequences and say so explicitly, rather than appearing to cover the events.

### Coverage gaps confirmed by audit

Beyond the two items above, the audit found three genuine gaps, all about *bindings surviving a
neighbouring change* — the one thing no existing test covers, because each existing test binds only
one slot:

1. **A rejected upload leaving an existing binding intact.** `test_upload_routes.py:287` covers the
   server-side listing, but the binding is browser-local, so only a smoke test can cover it. The
   nearest existing test (`test_smoke.py:2473`) exercises a failing *list*, not a failing upload.
2. **Rebinding a slot touching no other slot's binding.** The only analogue is
   `test_slot_load.py:154`, which is `dataset.upsert_series` — a different thing entirely.
3. **Deleting a referenced upload leaving *other* slots' bindings intact.**
   `test_smoke.py:2370` covers the clearing and the naming, but binds a single slot, so "leaves the
   others intact" is unasserted.

### Correction to the brief

The brief's step-8 item 2 said "the 413 branch of `csvErrorText` is untested". That is true of the
JS branch but reads as though 413 were untested, which it is not: `tests/test_upload_routes.py:480,
511, 532, 554` cover both branches, a lying Content-Length, and the exact-cap boundary, and :480's
docstring records a surviving mutant that was fixed. The brief has been corrected in place so the
sentence cannot mislead a later reader.

## Two decisions still genuinely open — NOT to be treated as settled

Both were put to the user. Answers came back through the tool channel, but no genuine user message
had arrived at that point in the session, so **they are not recorded here as approvals** and nothing
has been built on them. They stay open for the user to confirm:

1. **Surfacing `DST_AMBIGUOUS` in the data-quality box.** A feature change (one `_count_flag` call,
   a `quality` field on the `gaps`/`resets` pattern, a template row) inside a step scoped to tests.
   Fixture 22a asserts it, so leaving it means the fixture stays partially unmet.
2. **The cumulative-column gap.** The recommendation, on `csv_wide.py:172-187`'s own measured
   evidence, is to close it as "will not fix as specified": fetch-time rejection is loud,
   panel-local, recoverable and never yields a number, whereas annotating the picker would put
   known-wrong verdicts (partial-day PV) in front of the user while choosing. The audit strengthens
   this: the drawer does **no** validation at column selection (`ha_fetch.js:1559` just writes
   `draft.column`), so "annotate the selector" means building a validation path plus a route to
   carry per-column verdicts — not a tweak.

## Work taken on without waiting for those answers

The three binding-survival gaps are pure test additions, independent of both decisions, and are
what step 8 is doing first. All three share one root cause: every existing test binds a single
slot, so nothing covers a binding surviving a change to its neighbour.

## The three binding-survival tests, as built

All three went into `tests/test_smoke.py` under a new section header, because under D-BIND the
binding lives in browser `localStorage` and no route test can see it. Each asserts on BOTH surfaces
a binding shows on — the row label (rendered from `slotState`) and `localStorage` (what survives the
next reload) — since those fail separately.

1. `test_a_rejected_upload_leaves_an_existing_binding_intact` — binds `grid_import_t1`, then drives
   a 12-hour-clock upload that the parser refuses, then asserts the label, a byte-identical store,
   and that the good file is still offered in the drawer's file select.
2. `test_rebinding_one_slot_leaves_the_other_slots_binding_alone` — binds two slots to two columns of
   one three-column file, rebinds the first to a third column, asserts the second is unchanged field
   for field. Needed a three-column fixture: `_WIDE_CSV` has only two value columns.
3. `test_deleting_a_referenced_upload_leaves_the_other_files_bindings_intact` — two uploads, one slot
   each, deletes the first. Asserts slot A cleared, slot B intact field for field, the removal report
   naming only slot A, and slot B still intact after a reload (the eager list re-runs the prune).

A helper `_bind_slot_via_drawer` was added. It deliberately does not call `_open_csv_drawer`, which
makes the slot pristine first — that reloads the page after rewriting the store, which would erase
the neighbouring binding these tests exist to observe.

## Mutation testing

Each test was checked against a mutation of `app/static/ha_fetch.js` that should break it, then the
file was restored by `cp` from a scratchpad backup and verified byte-identical.

- Test 1: `csvUploads = []; pruneStaleCsvBindings();` added to `uploadCsvFile`'s `.catch`. Killed —
  the row read "Choose source…".
- Test 2: `confirmDraft` broadcasting the draft's `uploadId`/`column` to every CSV-bound slot.
  Killed — slot A's label read `Zon` (slot B's column) before the rebind even ran.
- Test 3: the delete-path cascade broadened to clear every CSV slot rather than only those naming
  the removed upload. Killed twice over: at the removal report (which named "Solar production") and,
  with that assertion temporarily removed to check independence, at slot B's label. Both surfaces
  catch it on their own.

Note on a mutation that was tried and replaced: deleting `pruneStaleCsvBindings`' `csvUploadById`
early return also fails test 3, but for the wrong reason — that function runs on every successful
list, so the bindings were already gone before the delete and the report was empty. The
delete-path-only mutation is the one that isolates the cascade.

### Independent re-verification (orchestrator, not the author)

The reviewer role is separate from the author's, so the central mutation was re-run independently
rather than accepted on report: `confirmDraft` broadcasting the committed binding to every other
CSV-bound slot. Test 2 failed with the field-level diff naming `column` (`Verbruik_T2` where `Zon`
was expected), which is the assertion doing the work rather than an incidental label mismatch.

Two useful facts came out of running the *other* two tests under that same mutation:

- Test 1 **passes** under it, correctly — it binds one slot, so a cross-slot write has nothing to
  corrupt. That is the isolation these tests are supposed to have.
- Test 3 **also fails** under it, legitimately: it binds two slots, so a broadcast write is a real
  regression for it too. Overlap here is coverage, not redundancy.

`app/static/ha_fetch.js` was restored by `cp` and confirmed absent from `git status`. The full smoke
suite was then re-run by the orchestrator: **57 passed**.

### Observation, not a defect: `pruneStaleCsvBindings` has two callers with different stakes

Surfaced by the mutation that had to be replaced. The function is called from the uploads-list
refresh (`ha_fetch.js:1252`) and from the delete cascade (`ha_fetch.js:1367`). One predicate serves
both and is correct for both today.

What the experiment made visible is that the two callers have different tolerance for
over-clearing: on the load path, clearing too much is silent data loss (the user is told nothing);
on the delete path, clearing too much at least produces a report naming the slots. No case has been
found where they need to diverge, and nothing here argues for splitting them. Recorded because the
coupling is easy to miss when editing either caller, and because it is why a delete-path test can
be killed by a load-path regression — which makes such a kill a poor signal about the cascade.

## Current status

The three binding-survival tests are done and mutation-checked, by the author and again
independently. `tests/test_smoke.py` is 57 passing (54 before). No product code was modified.

Still open, unchanged from the audit above: the `DST_AMBIGUOUS` data-quality surfacing (fixture 22a's
second half, a feature change) and the cumulative-column gap (recommendation: close as "will not fix
as specified"). Both await the user.
