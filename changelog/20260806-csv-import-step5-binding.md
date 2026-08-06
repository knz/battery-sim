# CSV import — step 5: persist the binding, and reify it on fetch

Implements step 5 of `changelog/20260805-csv-import-implementation-brief.md`. Steps 1–4 (uploads
storage, the pure parser, the upload routes, `CsvSource`) are done and reviewed; this step makes a
CSV-bound slot actually loadable — it stores the binding, carries it to the server, validates it
there, and threads it through both backend-load call sites.

## Task specification

From the brief's step 5, and in particular from **D-BIND**, whose Decision 1 was *retracted and
re-decided* before this work started:

- Storage is **candidate E: `localStorage`**. The per-slot entry in `ha.slots.<workspace_id>` grows
  from `{source, statId}` to `{source, statId, uploadId, column, unit}`. There is **no** server-side
  binding store — no new table, no `series_meta` column, no `simconfig.json` key. An earlier
  revision of the brief said "extend `series_meta`"; that was retracted (a `series_meta` row exists
  only for a series that already has data, and each fetch orphans the previous fetch's rows), and
  this step deliberately does not implement it.
- Transport is the ingest WS `backend_load` message, which gains an optional
  `binding: {upload_id, column, unit}`.
- Because the binding arrives from the client, **server-side validation of `upload_id` is
  load-bearing**, not defence in depth.
- Thread `workspace_id=` and `binding=` through both `app/main.py` `_load_backend_frame` (WS reify)
  and `POST /w/{id}/data/slot/{slot}/load`, calling `load_with_warnings` rather than `load`.
- Map `CsvBindingError` → 400, not the bare-`except`-driven 502.
- Honour **D-SEQ**: never nest an `uploads.*` call inside an open `dataset.connect()` transaction.
- Do **not** lift `ha_fetch.js`'s `PENDING_SOURCE_KEYS` filter on `csv_upload` — that is step 6.
  This step makes the plumbing ready behind the guard.

Out of scope: the drawer controls (file/column/unit selectors, the upload dialog) — step 6.

## High-level decisions

1. **The binding is stored in the existing slot store, not a new one.** `ha_fetch.js:64-84` already
   documents exactly two carriers of a source choice across a reload: fetched slots (server-side
   provenance) and pre-fetch customizations (`localStorage`, reconciled by `source_generation`). A
   CSV binding is category 2 verbatim, so it extends the per-slot object rather than inventing a
   third mechanism. The generation reconciliation is untouched: `loadSlotStore` returns whatever the
   per-slot object holds and the seed loop copies the three new fields across, so a stale store is
   dropped by the same comparison as before.
2. **`saveSlotStore` gates a CSV slot on a complete binding**, mirroring the existing rule that an
   HA slot is stored only once it has a `statId`. A partial binding is not fetchable, and storing one
   would restore a slot that fails the next fetch. The gate is `uploadId && column`; `unit` falls
   back to `kWh`, which is the drawer's default and `CsvBinding`'s.
3. **The WS message carries the binding; the server does not look it up.** Confirm stays a pure
   client action (the drawer's staging contract, `ha_fetch.js:40-52`), which is what makes step 6's
   "uploads survive Cancel, the binding does not" rule work without a server write.
4. **Validation lives in `ingest_ws.on_backend_load` for SHAPE and in `main._load_backend_frame`
   for EXISTENCE.** The session stays pure and data-dir-free (its module comment says so), so it can
   check that a binding is a dict with a 32-hex `upload_id`, a non-empty `column` and a known unit,
   but it cannot ask whether that upload exists. The existence check therefore runs where the load
   runs, via `uploads.get(workspace_id, upload_id)` — the one call that is workspace-scoped, so a
   foreign id resolves to None and fails rather than loading another workspace's file.
5. **A generic `binding` parameter, not a CSV-specific one.** `_load_backend_frame` and `load_slot`
   pass `workspace_id=`/`binding=` only to a source that declares it wants them, decided by
   `inspect`-free means: the extras are passed only when the resolved source key is `csv_upload`'s.
   Rejected alternative — passing them unconditionally — breaks `EnergyChartsSource.load`, whose
   keyword-only extras are `opener`/`now` and which would raise `TypeError` on an unexpected
   keyword.
6. **`CsvBindingError` → 400 on both paths.** On the endpoint it is caught before the bare
   `except Exception`; on the WS path it still becomes an `IngestError` (the WS protocol has one
   error shape), but with a message that names the configuration gap.
7. **No delete cascade, and the `TODO (step 5)` marker is replaced by the reason.** Under E the
   binding is browser-local, so `delete_upload` has nothing to clear: a deleted upload leaves a
   stale local entry which fails `uploads.get` at the next fetch. The brief's
   "clear bindings unconditionally, not gated on `existed`" requirement is moot; the reasoning is
   kept on record in the brief in case the binding ever moves server-side.

## Files modified

- **`app/static/ha_fetch.js`** — the module comment's carrier-2 paragraph now describes the extended
  per-slot shape; `draft` carries `uploadId`/`column`/`unit`; `openDrawer`/`closeDrawer`/
  `onSelectSource`/`confirmDraft` carry them through the staging cycle; `saveSlotStore` persists a
  complete CSV binding and the seed loop restores it; `stagedBackendSlots` emits
  `binding: {upload_id, column, unit}` for a slot whose committed source is `csv_upload`; the fetch
  loop forwards it on the `backend_load` message. `PENDING_SOURCE_KEYS` is **unchanged** — the
  radio is still filtered out, so none of this is reachable from the UI until step 6.
- **`app/ingest_ws.py`** — protocol docstring gains the `binding` field; `BackendLoadRequest` gains
  `binding: dict | None`; `on_backend_load` validates the binding's shape and rejects a malformed
  one.
- **`app/main.py`** — `_load_backend_frame` takes `workspace_id` and `binding`, builds a
  `CsvBinding`, calls `load_with_warnings`, and returns `(frame, warnings)`; the WS `done` handler
  passes `workspace.id` and `req.binding` and folds the CSV warnings into the dataset's warnings;
  `load_slot` accepts a `binding` in its body, threads it, and maps `CsvBindingError` to 400;
  `delete_upload`'s `TODO (step 5)` is replaced by a note recording why no cascade exists.
- **`tests/test_ingest_ws.py`** — binding-shape rejection cases.
- **`tests/test_slot_load.py`** — the endpoint cases: a CSV-bound load, a foreign/absent upload id
  (400, nothing persisted), `CsvBindingError` → 400 for a missing binding, bad unit/column.
- **`tests/test_csv_binding_reify.py`** (new) — the WS reify path end to end: a CSV-bound slot lands
  in the dataset with `csv_upload` provenance and its §7.3 warnings; a foreign upload id fails the
  fetch and persists nothing; a mixed HA+CSV fetch is all-or-nothing.
- **`tests/test_smoke.py`** — the localStorage round-trip: a CSV binding written into
  `ha.slots.<ws>` at the current generation is restored into `slotState` and reaches
  `stagedBackendSlots`; a stale generation drops it.

## Obstacles and solutions

- Passing `workspace_id=`/`binding=` to every backend source breaks `EnergyChartsSource.load`
  (`TypeError: unexpected keyword`). Solved by passing the extras only for the CSV source key.
- `_load_backend_frame` returned a bare frame, but §7.3 wants the CSV warnings. Solved by returning
  `(frame, warnings)` and having the WS handler extend the dataset's warning list.
- D-SEQ: `uploads.get` must not run inside `dataset.connect()`. The load (and therefore the
  `uploads.get` inside it) happens strictly before `save_dataset` opens its transaction, so the two
  are already sequenced; no code change was needed, only the ordering preserved.

## Review, 2026-08-06 — findings and fixes

An independent review of the step-5 work raised six defects (one behavioural, one cosmetic, four
documentation) plus one it asked to be left alone. All but that one were fixed; nothing about D-BIND
candidate E was reopened, `PENDING_SOURCE_KEYS` was not lifted, and no server-side binding storage
was added.

### D1 — a partial stored binding was restored, staged, and failed the whole fetch

**The defect.** `saveSlotStore`'s completeness gate for a `csv_upload` entry (a file AND a column)
was a WRITE-side gate only. The seed loop copied `uploadId`/`column` out of `localStorage`
verbatim, and `stagedBackendSlots` filters only on the source being a `backend_load` key — so an
entry already in the store with, say, an empty `column` was restored into `slotState`, left
`[ Fetch history ]` enabled, and sent `binding: {upload_id: …, column: "", unit: "kWh"}`. The
server's shape check rejects it, and under the all-or-nothing reify contract that failure takes the
whole fetch down, HA slots included. Not reachable from the UI today (the CSV radio is still
filtered out), but reachable from a hand-edited store or an older build — and step 6 lifts that
filter.

**The fix, and the decision inside it.** A new `usableStoreEntry(entry)` predicate runs in the seed
loop, and an entry it rejects is dropped **whole** — the slot falls back to the server's committed
source, exactly as if there were no local entry. The alternative considered was keeping
`source: "csv_upload"` and discarding only the binding fields. Rejected: that leaves the row reading
as CSV-configured while nothing can load it, and the user has no way to correct it, since the
`csv_upload` radio does not exist in the drawer until step 6. Falling back to the server's choice
leaves the slot in a state the drawer already renders and the user already knows how to change.

The gate is scoped to `csv_upload` alone, though `saveSlotStore` also requires a `statId` before
writing a `home_assistant` entry. Two reasons: an HA entry without an entity, or an entry with an
empty source, stages nothing and so cannot fail a fetch; and an empty-source entry is a
**meaningful** state — it is how a user clears a slot the server committed, which
`tests/test_smoke.py`'s `_make_slot_pristine` depends on. A blanket gate silently re-applied the
server's choice over the user's deletion and broke the two preselect tests, which is how this was
caught.

`unit` is deliberately not part of completeness: it has a documented default (kWh).

### D6 / S1 — malformed binding input answered 502

`uploads._check_upload_id` is the traversal guard and raises a plain `ValueError`. Both callers
classify by exception TYPE (`CsvBindingError` → 400, everything else → 502), so a traversal-shaped
`upload_id` — the most obviously client-supplied bad input on the path — answered 502 on the
endpoint and read as a load failure on the WS path. Separately, `_csv_binding` called `.get` on an
unvalidated body, so `"binding": "a string"` produced a 502 quoting
`'str' object has no attribute 'get'`.

Fixed at the two boundaries where the binding is interpreted, not by weakening the guard: the guard
and its 32-lowercase-hex whitelist are untouched. `CsvSource.load_with_warnings` wraps its
`uploads.get` call and translates `ValueError` → `CsvBindingError`; `_csv_binding` rejects a
non-dict binding with the same error type. Both therefore reach 400 on the endpoint and the
"slot … is not fully configured" wording on the WS path, which is the same answer a missing binding
already got. Translating in `CsvSource` rather than at each caller keeps the rule "a `ValueError`
out of the uploads store means the binding was malformed, not that the store broke" in the one place
that interprets bindings.

The rejected id is not echoed back, following `delete_upload`'s reasoning.

### D2/D3/D4/D5 — comments that contradicted D-BIND or the code

- **`app/uploads.py` `delete`** said a slot binding referencing the upload is cleared by "step 3's
  route". Under candidate E there is no server-side binding and no route can do it; this directly
  contradicted `app/main.py`'s `delete_upload`, which had been rewritten correctly. Rewritten to say
  what actually happens, keeping the paragraph's stated purpose (the place a cascade is NOT
  implemented is the place a reader looks first) and recording that the old wording predated D-BIND.
- **`app/uploads.py` module comment, "What is NOT here"** said the binding "lives with the slot's
  stored source choice", which is still true but reads as server-side. Clarified: the stored source
  choice is itself browser-local, so there is no table, column or document key holding a binding
  anywhere.
- **`app/uploads.py` module comment, "A note for step 5"** framed the `database is locked`
  cross-connection fact around a step-5 path writing a binding and an upload as one operation. No
  such path exists under E. The heading and scenario were dropped; the D-SEQ fact itself is real and
  was kept, generalised to any caller, with a note that the CSV load path avoids it by construction.
- **`app/static/ha_fetch.js`** still documented `slotState[name] = {source, statId, kind}` while the
  file header described the extended shape — the two disagreed about the same object. The comment
  now lists all six fields and states that the CSV three are empty strings on every non-CSV slot, so
  no reader has to test for their presence.

Two further comments were updated as a consequence of D1: the seed loop's "carried across verbatim"
note now says why verbatim is safe, and `stagedBackendSlots`' "an incomplete binding is sent as-is"
paragraph now names both gates and says why a third filter there would be wrong (it would drop the
SLOT silently, leaving a fetch quietly missing a series).

### Left alone, deliberately

S2, a pre-existing generation-reconciliation doc/code mismatch, was out of scope and is untouched.

### Tests added or tightened, all mutation-verified

- `tests/test_smoke.py::test_a_partial_csv_binding_already_in_the_store_is_not_restored` (new) — the
  READ path the existing `…_is_not_persisted_by_confirm` misses, which only covers what a save
  writes. Mutation: commenting out the `usableStoreEntry` call in the seed loop fails it.
- `tests/test_slot_load.py::test_load_endpoint_malformed_upload_id_is_400` — was
  `…_is_not_a_500` asserting `status_code in (400, 502)`, a disjunction that passed under either
  behaviour and pinned neither. Now one status, plus an assertion that the id is not reflected.
- `tests/test_slot_load.py::test_load_endpoint_non_dict_binding_is_400` (new) — S1's case.
- `tests/test_csv_binding_reify.py::test_malformed_upload_id_is_rejected_as_a_configuration_error` —
  was only "an error, nothing persisted"; now pins the "not fully configured" wording, i.e. that the
  WS path treats it as an unconfigured slot rather than a load failure.

Mutations run and confirmed failing: the seed-loop gate removed (D1 smoke test), the
`except ValueError` in `CsvSource.load_with_warnings` narrowed to `RuntimeError` (both malformed-id
tests), and the `isinstance` check in `_csv_binding` disabled (the non-dict test).

### Test results after the review fixes

```
uv run pytest tests/test_csv_binding_reify.py tests/test_ingest_ws.py tests/test_slot_load.py \
              tests/test_csv_source.py tests/test_upload_routes.py tests/test_uploads.py -q
220 passed

uv run pytest tests/test_smoke.py -q
45 passed
```

## Current status

Implemented and reviewed. Six review defects fixed (see above); step 6 is unblocked and inherits the
obligations already listed — lift `PENDING_SOURCE_KEYS`, build the drawer controls, gate Confirm on a
complete binding (now the third copy of the same completeness rule, beside `saveSlotStore` and
`usableStoreEntry`), and drop local entries whose upload no longer exists.
