# CSV import — step 6: the drawer UI

Implements step 6 of `changelog/20260805-csv-import-implementation-brief.md`. Steps 1–5 (uploads
storage, the pure parser, the upload routes, `CsvSource`, the binding and its reify path) are done
and reviewed; this step builds the user-facing half — the upload dialog, the per-slot file/column/
unit controls, the Confirm gate, the row label, and the client-side delete cascade.

## Task specification

From the brief's step 6 and `docs/specs/02-ux-wireframes.md` §"The CSV source" / §"The upload
dialog":

- Replace `csvPendingOption()` (the disabled placeholder radio) with a **real** `csv_upload` radio
  carrying an `[ Upload… ]` button that mirrors Home Assistant's `[ Configure… ]`, and remove the
  `PENDING_SOURCE_KEYS` filter that hid the live radio.
- Build the **upload dialog** as a new `<dialog>` beside `#ha-config-dialog`: intro text, the format
  bullets, the Amsterdam-local-time | UTC radio (Amsterdam default), a file chooser, and the list of
  uploaded files with `[ remove ]` and a `rows · resolution · columns` summary. Upload errors are
  shown in the dialog and are recoverable.
- Build the **per-slot controls** under the CSV radio, shown only while it is selected: **File**
  (from the LIST route), **Column** (from the chosen file's `columns.slice(1)`), **Unit**
  (kWh default | Wh). They write `draft.uploadId` / `draft.column` / `draft.unit`.
- **Confirm enabled once file+column are chosen.** Uploads survive Cancel; the binding does not.
- Row label reads `Upload CSV · <file> · <column>`.
- **Delete-cascade, client-side**: removing a file clears any slot bound to it and says which.
- Every new user-facing string goes through `_()` / `drawer_i18n` + `t()`/`ti()`, translated into
  Dutch and recompiled.
- Own the upload-error `code` → translated-string table (deferred here by step 3).

Out of scope, and deliberately untouched: `app/features.py` (step 7 retires `data_source_csv`, so
the key is briefly an orphan — expected and consistent with the planned sequencing); any server-side
binding storage (contradicts D-BIND); any new route.

## High-level decisions

1. **One completeness predicate, three callers.** `csvBindingComplete(o)` — "a file AND a column;
   `unit` has a documented default and is not part of it" — now backs all three gates: the drawer's
   Confirm (is this committable?), `saveSlotStore` (should this be written?) and `usableStoreEntry`
   (should this be restored?). Step 5's review had already established that the rule must exist on
   both store sides; adding a third hand-written copy in the Confirm gate was the alternative and was
   rejected. The three answers are the same question asked at three moments of one lifecycle, and
   they have to agree: what Confirm permits must be exactly what the store persists, which must be
   exactly what a reload restores. It takes the whole object rather than two arguments so a caller
   cannot pass the fields in the wrong order, and so a fourth required field would be one edit.
   `usableStoreEntry`'s scoping is unchanged — it still gates only `csv_upload`, because
   `tests/test_smoke.py::_make_slot_pristine` writes `{source:'', statId:''}` to clear a slot and
   that is a meaningful state to restore.

2. **The delete cascade runs in the client, because that is where the binding lives.** §2.2 says
   removing a file that a slot uses clears that slot's binding "reported when the removal is
   confirmed", and under D-BIND the server cannot do it — the binding is browser-local and the
   server has no table for it. `pruneStaleCsvBindings()` clears any slot whose `uploadId` is not in
   the current list, saves the store, re-labels the affected rows and returns their names;
   `removeCsvUpload` reports them in the dialog's status line via one msgid,
   `"✓ Removed %(name)s. These series went back to “Choose source…”: %(slots)s"`. Slots are named by
   the roster's own `data-slot-role` label ("Grid import T1"), never by the internal series name
   (§4.1). The clear is **whole** — source included — so the row returns to "Choose source…" as the
   spec requires, rather than sitting as a CSV slot with no file, which is a state the fetch rejects
   and the label cannot describe.

3. **The cascade runs on any 2xx, not only when the server reports `existed: true`.** The DELETE is
   idempotent by design, so `existed: false` is exactly what a retry after a partial failure looks
   like — and the retry is the call that must still clear a binding stranded by the first attempt.
   This is the same "unconditionally, not gated on `existed`" rule the brief recorded for a
   server-side cascade, applied where the cascade actually ended up.

4. **`pruneStaleCsvBindings` also runs whenever the uploads are listed**, which discharges the
   obligation D-BIND left to this step: a binding whose file was removed in another tab, or in a
   workspace whose data was cleared, surfaces in the drawer rather than only at fetch time. To make
   that true on a plain page load, the module lists the uploads eagerly **if and only if** some slot
   arrived CSV-bound. Gating it that way keeps an ordinary page load at zero extra requests: with
   nothing bound, nothing on screen names a file.

5. **`detail` is handled as `dict | str`, keyed off `detail.code`.** `csvErrorText(status, detail)`
   checks the status first (413 has no envelope of ours — `_read_capped_body` raises a plain string),
   then requires `detail` to be an object, then looks its `code` up in `CSV_ERROR_KEYS`. Anything
   that is not an object, and any code the table does not know, falls back to one generic sentence.
   Both fallbacks are real: python-multipart enforces its own part limits before our handler runs and
   Starlette owns that response, and a newly-added parser code is what an un-updated catalog sees.
   The server's English `message` is **not** shown in place of the translated wording, but it **is**
   appended for the codes in `CSV_ERROR_DETAILED` — the ones whose message names the specific
   offender (which row, which column, what was found), since re-deriving that would mean parsing
   English prose. The 1-based `row` is appended separately, so it survives a code whose message is
   not shown. Every write is `textContent`; nothing from the server is ever `innerHTML`d, because
   parser messages legitimately quote the user's own column names and cell values.

6. **The binding block toggles on the source KEY, not the kind.** `csv_upload` is `backend_load`,
   exactly like `energy_charts`, so a kind-based toggle would show File/Column/Unit for
   `energy_charts` too. `#drawer-backend-action` still toggles on the kind and therefore shows for a
   CSV slot as well — harmless, since it is only a status line.

7. **A default FILE is staged; a default COLUMN is not.** The file selector stages the newest upload
   (the list is newest-first) when the draft names none, which makes the common path — upload, pick a
   column, Confirm — need no extra click. The column selector leads with "— choose a column —" and
   stages nothing, because nothing about a column says which series it is (§4.1): a pre-picked column
   would present an arbitrary guess as an answer. This asymmetry is deliberate and is why the state
   immediately after selecting the radio is exactly the one the Confirm gate has to catch.

8. **The row label needs an id→filename map, so the LIST response is cached.** `slotState` holds the
   upload id and never the filename — the id is what the binding means and what the server validates,
   and a filename is not an identity (two exports may share one). `csvUploads` is therefore not only
   a fetch cache; it is what `updateSlotButton` reads. A binding whose id is not in it renders
   "(file no longer available)" rather than a blank, which is a fact about the binding rather than
   something that looks like a rendering bug. That placeholder is visible only in the window before
   the workspace's uploads are known: once a list arrives, surviving rows are re-labelled and stale
   ones are cleared outright.

9. **`pending_hint` was removed from `drawer_i18n`, not merely left unused.** Its only reader was the
   stub. The msgid "Not built yet" survives in `_pending_dialog.html`, so nothing was lost from the
   catalogs and the pending affordance elsewhere on the page is unaffected.

10. **Two msgids use typographic quotes (`“ ”`) rather than escaped ASCII ones.** The delete-cascade
    messages quote "Choose source…". Written with `\"`, they extract into the `.pot` as escaped
    quotes, which `tests/test_i18n.py::test_all_msgids_in_the_block_are_extractable` reads as absent
    (its regex does not handle escapes). Typographic quotes are also simply better typography here,
    so the msgid was reworded rather than the test's regex widened.

## Requirements changes

None from the user mid-task. Two things in the brief turned out to be slightly different from what
the code does, and were followed rather than the brief:

- The brief's suggested test of a rejected upload was a **cumulative column**. That rejection lives
  in `column_frame`, i.e. on column SELECTION, not in `parse_and_summarise` — a monotone file uploads
  successfully (verified). The rejection test therefore drives a **12-hour clock in the timestamp
  column**, which is a genuine upload-time rejection and is the mistake the dialog's own bullet warns
  about. The dialog's fourth format bullet still states the per-interval rule, so the user is warned
  before they hit it at bind time.
- The brief said `#drawer-backend-action` "is only a status line, so that is harmless". Confirmed and
  kept: it shows for a CSV slot and carries nothing.

## Files modified

- `app/static/ha_fetch.js` — deleted `csvPendingOption()`, its call, the `csvPending` computation
  and `PENDING_SOURCE_KEYS`. Added `csvBindingComplete` and rewired `saveSlotStore` /
  `usableStoreEntry` onto it. Added the whole uploaded-CSV block: `uploadsPath`, `csvUploadById`,
  `csvResolutionLabel`, `csvShortDate`, `csvNumber`, `CSV_ERROR_KEYS` / `CSV_ERROR_DETAILED` /
  `csvErrorText` / `csvErrorFromResponse`, `showCsvError` / `clearCsvError`, `refreshCsvUploads`,
  `pruneStaleCsvBindings`, `renderCsvUploadList`, `removeCsvUpload`, `slotRoleLabel`,
  `uploadCsvFile`, `openCsvUpload`, `fillCsvFileSelect`, `fillCsvColumnSelect`, `csvFileSummary`,
  `syncCsvUnitRadios`, `applyCsvChoice`, and the control listeners. Extended `renderSourceList`
  (the `[ Upload… ]` button), `openDrawer` / `closeDrawer` (hide the block), `onSelectSource` (show
  it, on the key), `updateConfirmEnabled` (the CSV branch), `updateSlotButton` (the row label), and
  the wiring block (the eager list). Corrected the file header and five now-stale comments.
- `app/templates/workspace_data.html` — new `#csv-upload-dialog`; new `#drawer-csv-binding` block in
  the drawer; `drawer_i18n` gained 60 keys and lost `pending_hint`. A long note above the `set`
  records why no Jinja comment may appear inside it.
- `app/static/app.css` — rebuilt (`npm run build:css`) for the new utility classes.
- `app/locales/messages.pot`, `app/locales/{nl,en}/LC_MESSAGES/messages.{po,mo}` — 60 new msgids,
  all translated into Dutch and compiled. (Counted from `git diff` on the `.pot`: 60 added `msgid`
  lines, 0 removed. An earlier revision of this file and of the brief both said 59.)
- `tests/test_smoke.py` — removed the pending-stub assertion from
  `test_new_pending_controls_marked` (the rest of that test stands); added `_WIDE_CSV`,
  `_upload_csv`, `_open_csv_drawer` and seven step-6 tests; `_seed_csv_binding` documents that a test
  needing the entry RESTORED must now pass a real upload id, and the round-trip test was switched to
  one. **The review added two more tests (54 total)** and switched the two partial-binding store tests
  to a real upload id as well — see "Review, 2026-08-06".
- `tests/test_i18n.py` — two structurally-identical msgids added to the EN==NL allowlist, with the
  reason.
- `changelog/20260805-csv-import-implementation-brief.md` — step 6's status line.

## Rationales and alternatives

- **The Confirm gate replaces the filter, rather than the filter being kept.** Keeping
  `PENDING_SOURCE_KEYS` and adding the gate was possible, but the filter's own comment said step 6
  removes it "together with building that control plus a Confirm gate", and a filter that hides a
  built control is a lie to the user. The guard moved from "you may not choose this" to "you may not
  confirm this half-done", which is what the wireframe asks for. `defaultSourceFor` can now stage
  `csv_upload` on a slot offering nothing else; that opens the drawer on the CSV radio with its
  controls showing and Confirm greyed out, which is the correct thing to show.
- **A per-slot unit radio rather than a per-file one.** §4.2a's format carries no unit, and one
  file's columns need not share one — a Wh PV export beside a kWh grid register is ordinary. The
  values are `csv_wide.UNIT_FACTORS`' keys verbatim and are not translated; only the visible text is.
- **`syncCsvUnitRadios` exists because the radios are page-level markup shared by every slot.** They
  hold the last slot's answer until the draft is reflected onto them; without the sync, opening a kWh
  slot after a Wh one would show Wh while the draft said kWh — the same show/draft mismatch
  `defaultSourceFor` was added upstream to prevent.
- **The upload starts on the file input's `change`, with the native input hidden behind a styled
  button.** A bare file input cannot be restyled and reads as a foreign control beside daisyUI's, and
  a separate "upload" press after choosing a file is a step with nothing in it. The input's value is
  cleared after every attempt so re-picking the same (now fixed) file still fires.
- **`window.confirm` for the removal, not a custom dialog.** The upload dialog is already a modal,
  and nesting a second `<dialog>` inside an open one to confirm a row action is more machinery than
  the decision warrants. The trade is that the confirmation is not styled with the rest of the app;
  if that matters later, the message is already one msgid and can move.
- **Rejected: resolving the filename server-side into the binding.** It would have removed the
  id→filename map, but a filename is display-only (`uploads.Upload.filename` says so) and storing one
  in the binding would make two exports of the same name indistinguishable — which is the reason the
  id exists.

## Obstacles and solutions

- **A Jinja comment inside the `{%- set drawer_i18n = {…} %}` literal is a syntax error that
  `pybabel extract` does not report.** It logged the file, extracted nothing from it, and the run
  "succeeded" with a catalog missing every `workspace_data.html` string — which then silently
  emptied both `.po` files on the next `update`. Found by parsing the template directly with Jinja.
  Fixed by moving all the notes above the `set`; the `.po` files were restored from `git show HEAD:`
  into a scratch copy and re-updated from a good `.pot`. A warning about this now sits at the top of
  that comment.
- **`write_po` reflowed the whole Dutch catalog** (2380 changed lines) because its default width
  differs from `pybabel`'s. Solved by patching the msgstrs textually using `babel.messages.pofile.
  normalize` at pybabel's own width, which left the diff at 255 lines — all of them new entries.
- **The step-5 round-trip smoke test broke**, because it seeds a synthetic 32-hex upload id and the
  new prune clears a binding the server does not list. That is the prune working, not a regression:
  the test now uploads a real file through the route (`_upload_csv`) and binds to its id. The two
  tests that only need an entry REJECTED still use the synthetic id, which is still right for them.
- **`test_the_column_selector_skips_the_timestamp_and_offers_names` was order-dependent** — it read
  the option list before the LIST fetch resolved, passing alone and failing in a full run. Fixed with
  an `expect(...).to_contain_text(...)` on the file select first, so the assertion waits for the
  fetch rather than assuming it landed.
- **The first rejection test asserted on a phrase the server's English message also carries**
  ("24-hour clock"), so it survived a mutation that bypassed the whole `code` table. Retargeted at
  the table's own distinct opening ("A timestamp could not be read") plus the appended cell value.

## Verification

Exact commands and results:

```
timeout 900 uv run pytest tests/test_csv_binding_reify.py tests/test_ingest_ws.py \
  tests/test_slot_load.py tests/test_csv_source.py tests/test_upload_routes.py \
  tests/test_uploads.py tests/test_csv_wide.py tests/test_no_english_leakage.py -q
    → 422 passed (baseline 422)

timeout 1200 uv run pytest tests/test_smoke.py -q
    → 52 passed (baseline 45, +7 new), and green on three consecutive runs

timeout 300 uv run pytest tests/test_i18n.py tests/test_no_english_leakage.py -q
    → 205 passed
```

Seven mutations, each reverted by hand with the editor afterwards:

| # | Mutation | Caught by |
|---|---|---|
| 1 | Drop the `csv_upload` branch from `updateConfirmEnabled` | `test_confirm_is_blocked_until_a_file_and_a_column_are_chosen` |
| 2 | Populate the column selector from `columns` instead of `columns.slice(1)` | `test_the_column_selector_skips_the_timestamp_and_offers_names` |
| 3 | Replace `pruneStaleCsvBindings()` in `removeCsvUpload` with `[]` | `test_removing_a_file_clears_the_slots_bound_to_it_and_says_which` |
| 4 | Show `#drawer-csv-binding` unconditionally | `test_the_csv_radio_is_selectable_and_reveals_its_controls_only_when_selected` |
| 5 | Label the row with the upload id instead of the filename | `test_confirm_stages_the_binding_into_localstorage_and_labels_the_row` |
| 6 | Bypass `CSV_ERROR_KEYS` so every code falls back to the generic sentence | `test_a_rejected_upload_is_reported_in_the_dialog_and_is_recoverable` (only after the assertion was retargeted — see Obstacles) |
| 7 | Weaken `csvBindingComplete` to require only a file | `test_confirm_is_blocked_until_a_file_and_a_column_are_chosen` |

Mutation 7 is worth reading carefully: it is caught by the Confirm gate but NOT by the two store
tests, because those seed a synthetic upload id that the prune clears before the gate is consulted.
The store side of the predicate is therefore covered only indirectly. That is a known gap, not a
claim of coverage.

## Current status

Step 6 is complete, **reviewed** (see "Review, 2026-08-06" at the end of this file) and its tests pass:
`tests/test_smoke.py` is 45 → 54. Not committed, per instructions.

Deliberately not done, with reasons:

- **`app/features.py` is untouched.** `data_source_csv` is now an orphan key — nothing renders a `[?]`
  for it — which is exactly what step 7 exists to clean up. Retiring it here would have pulled step
  7's scope forward and would have touched `docs/specs/implementation-progress.md` too.
- **No harness fixtures 22 / 22a.** Step 8 owns them and they need a `docs/specs/16` harness run,
  not a smoke test.
- **The cumulative-column rejection has no in-drawer surface.** D-KIND refuses such a column in
  `column_frame`, i.e. at fetch time, so a user can bind to a monotone column and only learn at the
  fetch. The dialog warns about it in a format bullet, which is the cheap half. Making it a
  bind-time check would need a new route (the client cannot see the values), and the brief forbids
  new routes here. Worth considering for a later increment — as would be the register-heuristic
  false positive on monotone partial-day PV that step 2 recorded, which the same surface would carry
  an override for.
- **No styling of the `window.confirm` used for `[ remove ]`** — see Rationales.

## Review, 2026-08-06

An independent review of step 6 found **no correctness defects**: the shipped behaviour is what the
spec and the decisions above describe. What it found instead was five places where **correct code was
unpinned** — a future edit would break them silently — plus three documentation errors. The follow-up
work below closed three of the five, corrected the docs, and left two gaps to step 8 with reasons.
No working behaviour was changed.

### Closed here

1. **A failed uploads LIST must not wipe every binding.** `refreshCsvUploads`' `.catch` correctly never
   assigns `csvUploads` and never prunes, so a network error leaves the cache UNKNOWN rather than
   empty. Nothing held that in place: adding `csvUploads = []; pruneStaleCsvBindings();` to the
   `.catch` — two lines, and a plausible-looking "the cache is stale, clear it" edit — passed all 52
   tests. Its symptom is the worst one the drawer has: every CSV binding in the workspace silently
   disappears on a page load that lost the request, with nothing on screen to say why. Now pinned by
   `test_a_failed_uploads_list_leaves_every_binding_alone`, which aborts the LIST route with
   `page.route(...).abort("connectionfailed")` (the first use of route interception in this suite) after
   committing a real binding, and asserts the row is still CSV-bound to its column and the store is
   byte-for-byte unchanged.

   One thing the test had to get right, and it is worth recording: after the failed list the row reads
   `Upload CSV · (file no longer available) · Verbruik_T1`, which is **correct** per decision 8 — the
   filename comes from the cache, so with no cache the placeholder is the honest rendering. The
   assertion therefore pins the SOURCE and the COLUMN and rejects "Choose source…", not the filename;
   pinning the filename would have pinned the cache the failure emptied by design. (A first draft did
   pin it and failed against correct code, which is how this got noticed.)

2. **`syncCsvUnitRadios`.** Deleting its call from `applyCsvChoice` also passed all 52 tests, because
   every existing CSV test drives one slot per page and the radios happen to start on the template's
   `checked` default. It is nonetheless a real user-visible bug on the SECOND slot of a session: the
   radios are page-level markup shared by every slot, so a slot with no committed binding shows the
   PREVIOUS slot's unit while `openDrawer` has seeded `draft.unit = DEFAULT_CSV_UNIT`. Confirming
   without touching them stores kWh from a drawer that read Wh, which scales the series by 1000. Now
   pinned by `test_the_unit_radios_show_the_drafts_unit_and_not_the_previous_slots`, which commits `Wh`
   on `grid_import_t1`, opens `solar_production` in the same page, and asserts the RENDERED radio state
   (not the draft, which the user cannot see) plus what Confirm then writes.

3. **Two store tests were passing for the wrong reason** — this is the mutation-7 gap the Verification
   section above already flagged, now actually closed. `_seed_csv_binding`'s default `upload_id` is a
   synthetic 32-hex id absent from the workspace's list, so **two independent mechanisms** could remove
   a partial entry: the completeness predicate (the intended subject) and `pruneStaleCsvBindings` on the
   eager list-on-load. Asserting only that the entry was GONE could not distinguish them.
   `test_a_partial_csv_binding_is_not_persisted_by_confirm` and
   `test_a_partial_csv_binding_already_in_the_store_is_not_restored` now bind to a REAL id from
   `_upload_csv`, which disarms the prune and leaves `csvBindingComplete` as the only thing that can
   reject the entry. `_seed_csv_binding`'s docstring now states this as a rule about which tests may use
   the synthetic default, rather than only about tests needing an entry restored.

   Verified in both directions: weakening `csvBindingComplete` to `!!(o && o.uploadId)` fails both
   tests with the real id, and **passes both with the old synthetic id** — so the fixture change is
   what makes them test the predicate, and the previous coverage claim was correctly described as
   indirect.

### Documentation corrections

- **"59 new msgids" was wrong; it is 60.** `git diff` on `app/locales/messages.pot` shows 60 added
  `msgid` lines and 0 removed. Corrected in the brief's step-6 status line and in this file's
  Files-modified list (which already said "60 keys" one line earlier — the two disagreed).
- **The brief's pre-step-6 line anchors into `ha_fetch.js` are ~500 lines stale.** The load-bearing one
  is re-anchored **by name**: the brief cites the file header's "two things carry a source choice
  across a reload" list twice as the *reason* candidate E was chosen, and it is now cited by that phrase
  rather than by `:64-84`, so it cannot rot again. The others (`stagedBackendSlots`, the
  staged-then-confirm contract, `csvPendingOption`, HA's `[ Configure… ]`) are likewise named rather
  than renumbered, with a note that the section's numbers predate step 6. `csvPendingOption` is called
  out as **deleted**, since a reader searching for it would otherwise find nothing.
- **The `defaultSourceFor` comment overstated a hypothetical.** It framed `csv_upload` becoming
  `sources[0]` — and thus the staged default — as a live possibility. Enumerating `sources_for` over all
  ten slots shows every slot offering `csv_upload` also offers `home_assistant`, which sorts first in
  the registry, so it is **not reachable today**. Softened to say so while keeping the guard and its
  reasoning, in the same shape as the pre-existing no-op-guard note about the CSV filter ordering. The
  Confirm gate makes it safe either way; nothing needs changing if a CSV-only slot is ever added.

### Recorded, not implemented

- **The cumulative-column gap now has its own subsection in the brief** ("Known gap — a cumulative
  column is refused at FETCH time, not at bind time"). D-KIND's "rejected on selection" reads as
  bind-time and is not: the refusal is in `column_frame`, at load time, and the drawer has no route to
  ask. The subsection records the gap, why step 6 could not close it, three options with their
  trade-offs, and the **intended shape if it is taken up** — a per-column `cumulative` flag on
  `_upload_json` annotating the column selector, since that adds a field to an existing response rather
  than a new route. It also records the precondition: step 2's register false positive on monotone
  partial-day PV must be settled first, because greying out a column the user is entitled to bind is a
  worse failure than a late rejection.

### Deferred to step 8, with reasons

Both are listed in the brief's step-8 section so step 8 inherits them, and neither is a defect:

- **`usableStoreEntry`'s scoping is untested.** Pinning it needs a slot with a **committed** source
  cleared to pristine and reloaded — i.e. a fetched slot and a real dataset, which is harness fixture
  work rather than a smoke test.
- **The 413 branch of `csvErrorText` is untested.** It is the one status with no error envelope of ours,
  so it is a genuinely separate path, but driving it means pushing a multi-megabyte buffer through a
  file input.

Also recorded in the brief's step-8 section, as a follow-up rather than a gap: the real cost of
`window.confirm` for `[ remove ]` is not styling but **untranslated** browser OK/Cancel labels, in an
app where every other string goes through `_()`. Not changed here.

### Out of scope, unchanged

`app/features.py` — `data_source_csv` stays active; step 7 retires it. No server-side binding storage,
no new route, no behaviour change beyond the two mutation-reverts and the test-fixture change above.

### Mutations verified in this round

Each was applied, run, and reverted with the editor (never with git — the step-6 work is uncommitted).

| # | Mutation | Result |
|---|---|---|
| 8 | `csvUploads = []; pruneStaleCsvBindings();` in `refreshCsvUploads`' `.catch` | **caught** — `test_a_failed_uploads_list_leaves_every_binding_alone` fails: the row reads "Choose source…" |
| 9 | Delete the `syncCsvUnitRadios()` call from `applyCsvChoice` | **caught** — `test_the_unit_radios_show_the_drafts_unit_and_not_the_previous_slots` fails: the kWh radio is not checked on the second slot |
| 10 | Weaken `csvBindingComplete` to `!!(o && o.uploadId)` | **caught** — both partial-binding store tests fail with the real upload id, and both PASS with the old synthetic id, which is the point of the fixture change |
