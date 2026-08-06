# CSV import — step 3: the upload HTTP routes

Companion to [20260805-csv-import-implementation-brief.md](20260805-csv-import-implementation-brief.md)
(step 3) and [20260805-csv-import.md](20260805-csv-import.md) (decision record). Steps 1 and 2 —
`app/uploads.py` and `app/domain/csv_wide.py` — were already built, reviewed and clean when this
work started, and are not modified here.

## Task specification

Add the three HTTP routes the upload dialog and the drawer's file selector need, per the brief's
step 3:

- `POST /w/{workspace_id}/data/uploads` — multipart upload; parse via step 2, then write the file
  and the row; return the header plus the coverage summary for the dialog. Enforce a size cap and
  the CSRF convention.
- `GET /w/{workspace_id}/data/uploads` — the list, for the dialog and the file selector.
- `DELETE /w/{workspace_id}/data/uploads/{upload_id}` — remove row + file, and clear any slot
  binding referencing it.

A rejected upload must write nothing. Error statuses follow `app/main.py`'s existing convention
(404 unknown, 400 bad input, 502 load failure).

Out of scope, and deliberately untouched: `app/uploads.py`, `app/domain/csv_wide.py`,
`app/sources/` (step 4, being built concurrently), the binding/reify path (step 5), the JS and
templates (step 6).

## High-level decisions

**D3-1 — parse before any write, in the route, from bytes the route decoded itself.** The store's
`create` cannot reject (it never looks inside a file), so "a rejected upload writes nothing" is
only true if the route parses first. The order in `create_upload` is therefore: size check →
decode → validate the declared zone → `csv_wide.parse_and_summarise` → `uploads.create`. Every
rejection happens strictly above the `create` call.

**D3-2 — the size cap is enforced at the edge, twice, and `UploadFile` is deliberately not used.**
`uploads.MAX_UPLOAD_BYTES` is declared in the store and enforced nowhere there, by design: by the
time `create` runs the content is already in memory. Starlette's `UploadFile` has the same problem
one layer up — declaring a `File(...)` parameter makes FastAPI parse the whole multipart body
*before* the handler's first statement, so a handler-body check is a check after the fact. So this
route takes the raw `Request`, rejects on `Content-Length` when the header is present, and streams
`request.stream()` into a bounded buffer that aborts as soon as the accumulated byte count exceeds
the cap. Both checks answer **413**. Content-Length alone is not enough (it is client-supplied and
absent under chunked transfer encoding); the streaming check alone would accept a large declared
body up to the point of the abort, and answering before reading anything is strictly better when
the client told us the size. The multipart body is then parsed with `request.form()` on the
buffered bytes.

**D3-3 — CSRF: same-site on the two state-changing routes, nothing on the GET.** `app/csrf.py`
draws its line at "can this request destroy or create something", not at "is this a POST" — which
is why `POST /w/{id}/params` is uncovered. `POST …/uploads` creates persistent state and
`DELETE …/uploads/{id}` destroys it irreversibly (and, per step 5, will also clear slot bindings),
so both take `Depends(csrf.require_same_site)`. `GET …/uploads` is a read and takes none.

**D3-4 — `ambiguous_rows` and `timestamp_name` are returned to the client but NOT persisted.**
`WideCsvSummary` carries both; the `uploads` table has columns for neither, and step 1 is closed.
Both are recomputable from the stored file by re-parsing (which is what `CsvSource.load` does
anyway), so persisting them would be a cache, not a fact. They are included in the POST response
JSON, where the dialog wants them: `ambiguous_rows` feeds §7.3's data-quality box wording and
`timestamp_name` lets the dialog echo which column it treated as the timestamp. The `GET` list
therefore does not report them — it reads the row, not the file. Stated here because a step-6
reader looking for `ambiguous_rows` in the list payload will not find it.

**D3-5 — i18n of `CsvFormatError` messages is DEFERRED to step 6.** *(Amended in review round 2 —
the guarantee as first written was overstated; see the amendment at the end of this decision.)* The parser's messages are
English and not wrapped in `_()`, because `app/domain/` is pure and has no i18n plumbing. Mapping
`.code` → a translated string is left to step 6 for two reasons. First, the existing convention
already does exactly this: `drawer_i18n` in `workspace_data.html` holds
`ingest_rejected: _("Ingest rejected: %(reason)s")`, a translated *envelope* around an
untranslated server-supplied reason — so a server reason string crossing to the UI untranslated is
the established shape, not a new leak. Second, the mapping's natural home is the code that renders
it: step 6 owns the dialog and knows which of the twelve codes it wants distinct wording for and
which fold into one message. What this step guarantees is that the mapping is *possible*: every
error response carries the machine-readable `code` and the 1-based `row` alongside the English
`detail`, so step 6 can key on `code` and never has to string-match. No untranslated English
reaches a template from this step — these routes return JSON only.

**Amendment (review round 2).** The original wording — "every error response carries the
machine-readable `code`" — was false for three of the five 400 shapes on these routes, verified:
python-multipart's "Too many fields. Maximum number of fields is 1000.", the malformed-`upload_id`
400, and the unknown-`tz` 400 all answered with a bare `detail` string. Since step 6 was going to
build a `code`-keyed table against that promise, the fix is split rather than papered over:

- **The shapes this module raises itself are now uniform.** Every 4xx `create_upload`,
  `list_uploads` and `delete_upload` raise carries `{"code", "message", "row"}`. Four codes were
  added for rejections that previously had none: `no_file`, `bad_timezone` (the route's own, distinct
  from the parser's identically-named one — same condition, so the same code is correct),
  `bad_upload_id` and `no_such_upload`. `unreadable_csv` was added for D1. *(`no_such_upload` was
  retired the next day when DELETE became idempotent — see the requirements change above. The
  surviving codes are `unreadable_csv`, `bad_encoding`, `no_file`, `bad_timezone`, `bad_upload_id`
  and the parser's own.)*
- **The one genuine exception is written down instead of engineered away.** python-multipart enforces
  its own field and part limits and answers before this handler runs; Starlette owns that response.
  Reshaping it would mean an app-wide exception handler intercepting every route to fix a message on
  one of them — a worse trade than a two-line fallback in the caller. So the contract step 6 gets is
  `detail: dict | str`: key off `detail.code` when it is a dict, generic message when it is not.
  Documented in `create_upload`'s docstring.

Also hardened while in there: the malformed-`upload_id` 400 used to reflect the submitted segment
back (`unsafe upload_id: '\x00abc'`, verified with a `%00` path segment). Not an XSS hole — the body
is JSON and the id never reaches a filesystem path — but the client already knows what it sent, so a
fixed message costs nothing. Step 6 must still use `textContent` and never `innerHTML` on any server
`message`, because the parser's messages legitimately quote column names and cell values that came
out of the user's file; noted in the docstring.

**D3-6 — the delete→binding cascade is a marked TODO naming step 5.** Step 5 has not started and
no binding store exists. Inventing one here would be the wrong module deciding where a binding
lives (the brief's open item 3 is explicitly still open: `params` vs beside `series_sources`). So
`delete_upload` carries a TODO naming step 5 and the route contract it must satisfy, and the
docstring says plainly that the cascade is not yet implemented. The route is otherwise complete.

## Files modified

- `app/main.py` — three new routes plus one shared helper (`_read_capped_body`) and one summary
  serialiser (`_upload_json`). Imports `uploads`, `csv_wide`, `csv` and `ClientDisconnect`. The
  module docstring is updated: the `Routes:` table gained the three routes, and the
  "**The three state-changing routes are same-site only**" paragraph became "five" and names them.
  *(An earlier revision of this changelog claimed "top-of-file comment untouched (it does not
  enumerate routes)". That was simply false — the docstring carries an explicit `Routes:` table and
  a per-route-family narrative, and leaving the CSRF sentence saying "three" made the one place a
  reader learns the CSRF surface actively wrong. Corrected in review round 2.)*
- `tests/test_upload_routes.py` — new; the step-3 half of step 8's route tests.

- `app/csrf.py` — docstring only. Its "Which routes are covered" section enumerated three routes
  and was made stale by this work; two lines added naming the two new covered routes and the
  uncovered GET. No behaviour change.

## Obstacles and solutions

- **`UploadFile` parses before the handler runs**, so a size cap in the handler body is too late →
  take the raw `Request` and bound the stream read (D3-2).
- **Draining `request.stream()` by hand sets `_stream_consumed` but does NOT populate `_body`**, so
  the subsequent `await request.form()` raised `RuntimeError("Stream consumed")` (reproduced across
  24 tests) → `_read_capped_body` assigns the buffered bytes to `request._body`. A private
  attribute, and the docstring says why the public `Request.body()` is not an option: it has no
  limit parameter, so using it would read the whole body unbounded first.
- **A multipart `file` part with no `filename=` arrives as a plain `str`, not an `UploadFile`** —
  Starlette classifies parts by that attribute. So the route's `isinstance(..., str)` branch is the
  branch that shape actually takes, and it answers 400. A first version of the test assumed such a
  part would be stored under a placeholder name; the test now asserts the real behaviour, and the
  placeholder covers only a genuinely absent `filename` attribute. A browser's
  `FormData.append(name, File)` always sets one, so step 6 does not meet this.
- **A malformed `upload_id` raises `ValueError` from `uploads.get`/`delete`**, which would surface
  as a 500 on a hand-typed URL segment → caught and mapped to 400 in both routes.
- **Latin-1 supplier exports** would raise `UnicodeDecodeError` at decode → caught and answered as
  a 400 with its own code (`bad_encoding`), rather than a 500. Deliberately not retried under a
  fallback encoding: guessing would store a file whose column names are silently mojibake, and the
  binding keys on those names.

## Requirements change — DELETE is idempotent (user decision, 2026-08-06)

**Original behaviour:** `DELETE …/uploads/{upload_id}` answered 404 when the workspace had no such
upload, whether because it was already deleted or because the id belonged to another workspace. I
raised this in the round-2 report as an inconsistency worth deciding on purpose, since it contradicted
`deps.get_optional_workspace`'s "already-gone is fine" convention for the two workspace-deletion
routes.

**Decision:** make it idempotent. A second DELETE succeeds, so a double-click on the dialog's
`[ remove ]` link is harmless. **Rationale (the user's):** the file *is* removed, so an error in front
of the user describes a failure that did not happen; and it aligns the route with the convention the
rest of the app already follows.

**New contract.** 200 in both cases, body `{"deleted": "<id>", "existed": true|false}`. `existed` is
`true` when this call removed the row and `false` when there was nothing to remove. The drawer need
not branch on it — the end state is identical, which is the point — but a caller reconciling a stale
list can tell "I just did that" from "my list was out of date", and a body reporting `deleted` for a
no-op with no way to tell would quietly misdescribe what happened. Code `no_such_upload` is retired
(it was added in round 2 and is now unreachable); the code list in `create_upload`'s docstring was
updated with it removed.

**Malformed ids remain 400** (`bad_upload_id`): a syntactically invalid id is a client error, not an
absent resource, and idempotence is not a licence to accept nonsense.

**On preserving 404 for foreign ids — the priority named in the request, and what actually happened.**
The two guarantees turned out to live in different places, which is what let both survive:

- **Cross-OWNER isolation is unchanged and is now pinned directly.** `deps.get_workspace` 404s a
  workspace the requesting principal does not own *before* the handler runs — verified, and the store
  is never consulted. A new test asserts this on all three routes, and mutation-testing confirms it:
  dropping the `_authorize` check in `deps.py` fails that test and only that test. The old blanket 404
  was mistakenly credited with defending this boundary; it never was the mechanism.
- **The same-owner cross-workspace case did change status, from 404 to 200, and that is deliberate.**
  `uploads.delete` still filters on `workspace_id`, so the other workspace's row and file are
  untouched — that assertion is unchanged and is the load-bearing one. What changed is only the status
  reported for the no-op, and only for a requester who owns both workspaces and supplied the id
  themselves. They learn "this workspace has no such upload", which is true and is exactly what a 200
  on a never-existed id tells them. There is no confidentiality boundary between two workspaces of one
  owner for the old 404's leak argument to protect.

**And the ambiguity the reviewer flagged is real and did constrain this** — reported rather than
collapsed quietly, as asked. `uploads.get` returns `None` and `uploads.delete` returns `False` for
*both* "never existed" and "exists in another workspace", deliberately: the store has no function that
answers an unscoped question (`app/uploads.py`, "Owner scoping"). So keeping a 404 for only the foreign
case was **not available** without adding an unscoped read, which would trade the store's central
invariant for a better error message. Both are 200 instead, and neither acts on data outside the
workspace. Verified directly before choosing: an unscoped `SELECT workspace_id FROM uploads WHERE
id = ?` *can* tell them apart, which is precisely why the store declines to offer one.

**One consequence for step 5, recorded at the TODO:** the binding cascade must run **unconditionally,
not only when `existed` is true**. A delete that removed the row but crashed before clearing bindings
leaves a stranded binding, and the retry that would fix it is exactly the call where `existed` is
false — gating on it would make the retry a no-op and strand the binding permanently.

**Files touched:** `app/main.py` (`delete_upload` body and docstring, `create_upload`'s code list),
`tests/test_upload_routes.py` (the renamed `test_delete_is_idempotent`, the reframed
never-existed and same-owner-cross-workspace tests, the new cross-owner test, and one stale
`{"deleted": id}` assertion in the happy path).

## Review round 2 — defects found and fixed

A reviewer confirmed the test counts and the cap's resistance to every constructed attack, and
raised six items. All six addressed.

**D1 — a CSV cell over 128 KB answered 500 (highest priority, fixed).** `create_upload` caught only
`csv_wide.CsvFormatError`, but `csv.reader` raises a bare `_csv.Error("field larger than field limit
(131072)")` — which is not a `CsvFormatError` and **not even a `ValueError`**; it derives straight
from `Exception`. Reproduced: a ~200 KB body, nowhere near the 32 MiB cap, escaped as a 500 with no
`code`. Now caught as `csv.Error` → 400 with code `unreadable_csv` and no `row` (the reader fails
before yielding one, and inventing a line number would point the user at the wrong place). Fixed in
the route rather than in `csv_wide`: the parser is pure and `csv.Error` is a fact about the stdlib
reader it happens to use, not about the wide format, so translating it is the adapter's job. "Writes
nothing" held throughout, before and after.

**D2 — a client disconnecting mid-body answered 500 where the stock stack answers 400 (fixed).**
`request.stream()` raises `starlette.requests.ClientDisconnect` and nothing caught it. Verified side
by side at the ASGI level: a stock `file: UploadFile = File(...)` route answers **400** for the
identical request; the raw-`Request` route **raised**. So taking the raw `Request` — necessary for
D3-2's size check — regressed the stack's own handling of an ordinary network event (the user hits
Escape, wifi drops mid-upload). Now caught → 400. Not a security issue: no response reaches a client
that has already left, so the whole cost was a spurious traceback in the log for a non-event. Worth
recording that the stock route's 400 comes from its multipart parser rejecting the truncated body
rather than from the disconnect as such — the observable behaviour the reviewer described is right,
the mechanism differs slightly.

**M3 — a test that survived mutation (fixed).** Deleting the *entire* `Content-Length` check left all
35 tests passing: `test_oversized_declared_body_is_413_before_anything_is_read` was named for the
header branch, but its input was genuinely oversized so the streaming branch answered identically,
and its docstring's "without reading a body byte" was unasserted. Fixed on both sides — the two
branches now emit deliberately different messages (`"file too large: {declared} bytes, limit is
{limit}"` vs `"file too large: over the limit of {limit} bytes"`), and the test posts a *tiny* body
with a declared `Content-Length: 10^9` so only the header branch can possibly answer, asserting the
exact message including the declared count. A counterpart test pins the streaming branch the same
way. Re-mutation-tested: removing the header check now fails exactly that test.

**Memory amplification — recorded, not fixed.** Measured: a 30.02 MiB body (under the cap), 2618 rows
× 2000 columns, `tz=Europe/Amsterdam` → peak RSS **727 MB**, 2.23 s — roughly **19x**, from the raw
bytes, the decoded `str` and one small Python `str` per cell all live at once (a 5-byte cell costs
~54 bytes of object header). The reviewer is right that the cap does not bound what a docstring
calling it a DoS control invites a reader to think it bounds. Recorded in `_read_capped_body`'s
docstring rather than in `MAX_UPLOAD_BYTES`', because `app/uploads.py` is closed to this step — the
note is at the code that actually does the reading, and it points back at the constant's reasoning.
Not fixed because severity is bounded by the deployment, not by hope: localhost, single user, both
mutating routes same-site checked, so the only reachable principal is the user spending their own RAM.
The cheap lever if it ever matters is a column-count limit at the header, before any cell is
allocated.

**`columns[0]` is not uniquified — documented, not changed.** Verified: header `,A,B` → `["", "A",
"B"]`; header `Tijdstip,Tijdstip` → `["Tijdstip", "Tijdstip"]`, because `csv_wide`'s uniquification
runs over `header[1:]` and the timestamp name never participates. Name-based resolution is
unaffected, so this is a trap for index-based step-6 code rather than a live bug; `_upload_json`'s
docstring now says `columns.indexOf(name)` can return 0 and that step 6 must slice and send names.
Both shapes are pinned by tests.

## Tests added in round 2

Twelve, taking the file from 35 to 47: the oversized CSV field (D1); client disconnect mid-body,
driven at the ASGI level since `TestClient` cannot send one (D2); the discriminating Content-Length
case and its streaming counterpart (M3); a zero-byte file (→ 400 `missing_header`); `tz` absent from
the form entirely, which is a different request shape from `tz=""`; duplicate `file` parts (last wins,
and exactly one row results); a traversal-shaped filename (→ 201, stored verbatim as a display string,
nothing on disk named for it); `resolution_s: null` round-tripping through POST **and** GET for both
an irregular-spacing file and a single-row file; the two `columns[0]` shapes; and the malformed-id
message no longer echoing its input.

Each of the three behaviour fixes was mutation-tested individually — reverting the `csv.Error` catch,
the `ClientDisconnect` catch, or the whole `Content-Length` check each fails the suite.

## Current status

Step 3 complete, review round 2 addressed, and the idempotent-delete requirements change applied.
`tests/test_upload_routes.py` has 48 tests, all passing; run together with the directly-related
existing suites (`test_uploads`, `test_csv_wide`, `test_workspace_routes`, `test_slot_load`,
`test_i18n`, `test_no_english_leakage`, `test_workspace_data`, `test_workspaces`) that is 548 passing.

Not done here, by design:

- **The delete→binding cascade** (D3-6) — a marked TODO in `delete_upload`'s docstring naming step 5
  and the exact contract it must satisfy. Until it lands, a slot bound to a deleted upload fails at
  LOAD time (`uploads.read_text` → `FileNotFoundError` → the 502 convention) rather than at delete
  time, which is loud and recoverable but not what §2.2 promises.
- **The `code` → translated-string table** (D3-5) — step 6's, in `drawer_i18n`.
