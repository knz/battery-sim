# 20260726 — Workspaces restructure, phase 2 (the list screen)

Implements phase 2 of
[20260726-workspaces-implementation-plan.md](20260726-workspaces-implementation-plan.md),
against [specs/20-workspaces-ux.md](../specs/20-workspaces-ux.md) §2′.2, §2′.3 and §2′.10, and
[specs/02-ux-wireframes.md](../specs/02-ux-wireframes.md) §2.1's Inapplicable rule.

## Task specification

Turn `GET /` into the workspace list and give the old single page a scoped home, with the two
deletion flows and their confirmation modals. No new computation, no data-model change, and
nothing from phases 3–5 (no edit screen, no configure-data screen, no wizard).

1. `GET /` renders the list; the three-panel page moves to `GET /w/{id}/results`.
2. Remove phase 1's temporary lifespan `workspaces.create(local)` (followup I7). `migrate_local()`
   stays — adopting a genuine pre-index installation is correct.
3. `_workspace_card.html`: the three badges, the info box, the action set, the no-data variant.
4. `POST /workspaces` creates and redirects; two deletion routes, each returning to the list.
5. The two confirmation modals (§2′.3), page-level, reusing the `<dialog>` idiom.
6. The header loses the `[workspace: local]` badge and the `[⚙]`.
7. Wire `workspaces.touch()` from `POST /w/{id}/params` (followup I6).

Every new user-visible string marked with `_()`; no `.po`/`.mo` edits and no `pybabel` run — a
separate translation pass follows.

## Requirements changes

None from the user. One thing the brief left open was settled during the build and is recorded
under decisions: where `POST /workspaces` redirects to, given that its specified destination
(phase 5's wizard) does not exist yet.

## High-level decisions

**`POST /workspaces` redirects to `/w/{id}/results`, and says so.** §2′.2 sends `[ + New analysis ]`
into the three-step wizard, which phase 5 builds. Of the three destinations available today, this
is the only one that renders: `/w/{id}/edit` and `/w/{id}/data` are phases 3 and 4 and would 404,
and staying on the list would make the button look like it had done nothing but add a card. The
new workspace therefore lands on the page that shows its appendix-A default configuration and
invites a data load. The shape — POST, then 303 — is not temporary and is the part worth fixing
now: a reload of the destination must not create a second workspace.

**A view-model module rather than formatting in Jinja.** `app/workspace_list_view.py` sits between
`workspaces.list_summaries()` (which already returns exactly a card's facts) and the template. It
exists for one specific reason rather than symmetry: the card carries figures and a timestamp, and
both are locale-dependent — Dutch groups thousands with a point, and §2′.2 asks for
Europe/Amsterdam while everything stored is UTC. Neither can be decided in the template without
duplicating machinery, and neither can be decided in `workspaces.py` without formatting before the
request's locale is known (`app/i18n.py`'s A6 note). So the module emits `i18n.num()` pairs and
`_msg()` pairs and formats nothing; `templates/_msg.html` does it at render time, exactly as panel
① and panel ③ already do.

**The card's actions are `<a href>`, and only the two deletions are not.** The plan is explicit and
the reasoning holds up: they are navigations, so the browser already does them well, they keep
working without JavaScript, and reaching for index.html's hand-rolled `fetch` + `outerHTML` layer
would couple the list to machinery that exists to keep panels ② and ③ on screen together — a
problem this screen does not have. The two deletions are `<button>`s that open a page-level
`<dialog>` whose body holds an ordinary form POST.

**POST + redirect for both deletions, not `DELETE`.** An HTML form can only issue GET or POST, and
these are submitted by forms inside the dialogs. A `DELETE` would need a `fetch`, which would make
the two destructive actions on the screen the only things that stop working when a script fails to
load. Redirect-after-POST is also what §2′.3 asks for in so many words — "the user stays on the
list, which re-renders".

**One dialog per KIND, filled from the clicked card.** Page-level for the top-layer reason
index.html documents at its own `#slot-info-dialog`; cards are not collapsibles today so that exact
trigger does not exist here, but the second reason does: a dialog per card would mean N copies of
the same copy in the DOM and N form actions to keep in step. The script that fills them is ~30
lines and does nothing else.

**The two dialog body sentences live in a `<template>`, not in the script.** They carry the
workspace title, so they have to be substituted client-side — and a string literal inside a
`<script>` block is invisible to `pybabel extract` (babel.cfg extracts Jinja through the i18n
extension, which does not descend into script bodies). A msgid the extractor cannot see is a msgid
that renders in English on a Dutch page, which is followups A1's exact failure mode. Rendering them
server-side through `_()` into a `<template>` and reading them back keeps the msgid extractable and
the two-step order (translate, then interpolate) intact. Substituted with `textContent`, never
`innerHTML`, so an interpolated title cannot be markup.

**`updated_at` moves on a save that HAPPENED, and on nothing else.** `touch()` is called inside the
`try` that saves, after `simconfig_store.save` returns — so an invalid submission (which never
reaches the save) and a save that raised `OSError` both leave the badge alone. Deleting data does
not advance it either: §2′.10's rule is about the configuration's save time, and a list that
reordered behind a deletion would be the same surprise as one that reordered behind a fetch.

**The relocated page gets a "← Your analyses" link.** Not in the phase-2 brief, but the page stopped
being the entry point, and without it the only route back to the other analyses is the browser's
Back button. §2′.4's screens carry the same breadcrumb, so this is that pattern applied to the one
screen this phase moved rather than a new invention.

**Two structural changes to `tests/test_no_english_leakage.py`, both deliberate.** Its `_PAGES` now
has four entries — the list is a new surface with its own prose and is the app's entry point, so
leaving it unscanned would leave the newest screen the only unguarded one. And `/`'s word floor is
60 rather than 200: that floor guards against a screen collapsing to nothing, and the list is one
card and two dialogs, not three panels of caveats. Keeping 200 would have made the test assert that
the list is as verbose as the results page, which is not a property anyone wants.

## Files modified

- `app/workspace_list_view.py` — **new.** `card`, `cards`, `_data`, `_fmt_instant`, `_fmt_fuse`,
  `DISPLAY_TZ`, `CONNECTION_BADGE`.
- `app/templates/workspaces.html` — **new.** The list page: header, heading + `[ + New analysis ]`,
  the card loop, the empty state, the two dialogs and the ~30-line dialog script.
- `app/templates/_workspace_card.html` — **new.** One card: badges, info box, action row, the
  no-data variant.
- `app/main.py` — `GET /` is now `workspace_list`; `POST /workspaces`, `POST /w/{id}/delete` and
  `POST /w/{id}/data/delete` added; the old `index` moved to `GET /w/{id}/results` and takes its id
  from the resolved `Workspace` rather than `db.WORKSPACE_ID`; the lifespan's `create` removed
  (I7); `POST /w/{id}/params` calls `workspaces.touch` after a successful save (I6); module
  docstring rewritten around the new URL table; `sqlite3` import dropped with the `create` it
  guarded.
- `app/templates/index.html` — header loses the `[workspace: local]` badge and the `[⚙]`, gains the
  back-link; file-header comment rewritten around the relocation.
- `tests/conftest.py` — `page(id)` helper, and the docstring note on why it exists.
- `tests/test_workspace_list.py` — **new**, 28 tests.
- `tests/test_smoke.py` — `_workspace_url()` and a `workspace_url` fixture (a throwaway data dir now
  starts with no workspaces, so the page has to be reached); five new browser tests on the list.
- `tests/test_i18n.py`, `tests/test_params_route.py`, `tests/test_results_route.py`,
  `tests/test_ingest_ws.py`, `tests/test_workspace_routes.py` — re-pointed at `page()`; two
  fixtures seed the workspace row they now need.
- `tests/test_no_english_leakage.py` — the list added to `_PAGES` as a fourth surface, `/`'s word
  floor lowered, `test_the_english_page_is_unaffected` seeds the row the scoped page needs.
- `followups.md` — I6 and I7 marked done.
- `app/static/app.css` — regenerated (`npm run build:css`); no new CSS was written by hand.

## Rationales and alternatives

**Denormalising the badge fields onto the `workspaces` row.** Rejected, and phase 0 had already
rejected it: `list_summaries` reads one small JSON config per workspace with no arrays in it, and a
second copy of `phases`/`fuse_a`/`contract` would be a copy that can drift.

**Formatting the connection badge as an `i18n.num()` pair.** Rejected. A fuse rating is an
identifier of a connection type, not a quantity: "1×25 A" is written the same way in both
languages, and a 1600 A rating localised into "1.600 A" on a Dutch page is a different-looking
number. An integral rating loses its `.0` (the field is a float); anything else keeps its own
precision rather than being rounded into a rating the household does not have.

**Localised dates.** Rejected, following `data_view._fmt_date`'s existing reasoning: babel's short
date is `24-07-2026` for nl and `7/24/26` for en, and a reader who is unsure which convention a
page follows cannot tell 07-24 from 24-07. ISO is unambiguous and is what a Dutch reader sees on a
meter readout. What IS localised is the timezone — §2′.2 asks for Europe/Amsterdam, and that
conversion happens in `_fmt_instant` and nowhere else on this screen.

**Hiding `[ Configure data ]` and `[ Update ]` while phases 3 and 4 are outstanding.** Rejected.
§2′.2's action table marks both "always", and hiding them would encode the opposite of what the
spec says about them. They currently lead to a 404, which is a build-progress fact rather than a
specified state — the same distinction §2.1 draws between Pending and Inapplicable.

## Obstacles and solutions

**`_card_html`'s first version sliced to the end of the document.** Bounded at the NEXT `<article>`,
which does not exist for the last card — so the slice swallowed the two page-level dialogs and the
assertion that a no-data card omits `[ Delete data ]` failed against the dialog it opens. Bounded
at `</article>` instead, with the trap written into the docstring.

**A regex rename of `.get("/")` → `.get(page())` shadowed three local variables.** Three tests in
`test_params_route.py` bind `page = client.get(...)`, so the helper became unreachable inside them.
Renamed those locals to `rendered_page`.

**Two test modules build a bare `TestClient(app)` with no seeded workspace.** They passed while the
page was at `/`; scoped, they 404. Seeded explicitly, as `tests/conftest.py`'s docstring already
prescribes. Worth noting for the remaining phases: in
`test_no_english_leakage.test_the_english_page_is_unaffected` the 404 rendered as zero English
markers, i.e. as "`_visible_text` is broken" — the exact failure that test claims to distinguish
from a real one.

**The card's size line is absent when the only series is a price series.** Not a defect:
`workspaces._data_facts` derives the interval count from the coarsest ENERGY resolution and returns
None when there is none, and the template omits the line rather than guessing. Found while
screenshotting, because the only dataset an out-of-process server can be given today is the preset
spot-price load. Verified against a real energy dataset in-process: "48 intervals · hourly".

## Verification

**Suite: 931 passed, 2 skipped, 14 failed.** Baseline was 843 passed, 2 skipped. The two skips are
`tests/test_ha_live.py` as before. (This originally read "930 passed"; the run was 931. Corrected
during the review pass.)

**The 14 failures are all `tests/test_no_english_leakage.py` on `/`**, and all are the expected
untranslated new strings — seven scenarios × two checks, every one of them the same three sentences
plus the word "intervals". They are listed in "New translatable strings" below. Nothing was
allowlisted, no fragment was removed from `FORBIDDEN_FRAGMENTS`, and no assertion was weakened to
make them pass: the translation pass closes them.

**Playwright: 25 passed** (20 before). `test_smoke.py` runs here — Chromium is installed. The five
new ones drive the real screen: creating through the button and landing on the destination, the
no-data card's two absent actions asserted with `is_visible()` rather than on markup, the
delete-analysis dialog quoting the title and both cancelling and confirming, the delete-data dialog
stating what it keeps, and — on its own server against its own untouched data directory — the
empty state of a genuinely fresh installation.

**Browser check, by screenshot.** The list, the empty state and both dialogs were rendered at
1100×900 and read against §2′.2's and §2′.3's wireframes. They match: badge order and content, the
info box as a distinct block, `[ Results ]` primary and first, the two destructive actions
separated by a gap with the 🗑 at the far end, and the no-data card showing only three actions. The
delete dialog matches §2′.3's copy line for line, with `[ Cancel ]` before the destructive button.

**Both locales rendered and read as text.** English is complete. Dutch shows the new strings in
English (expected) while the strings the card reuses from existing msgids — "Zonopwekking",
"uurlijks", "Annuleren" — do translate, which is the evidence that the new msgids are wired into
the same machinery and not merely absent.

**Extraction was verified without writing any catalog.** `pybabel extract` to a scratch `.pot`, and
every new string appears as a stable compile-time msgid, including the two `%(title)s` sentences in
the `<template>` and the `msgid_plural` pair for the size line. Nothing was extracted as a runtime
f-string. The committed `.po`/`.mo` files were not touched.

**CSS** was rebuilt (`npm run build:css`) although no hand-written CSS was added — the new templates
use daisyUI classes not previously present in any template, and Tailwind's generated stylesheet is
content-scanned.

## New translatable strings

Nineteen msgids, all in the two new templates except the last two, which are in
`app/workspace_list_view.py`:

*`_workspace_card.html`:* `saved %(when)s` · `Grid consumption` · `Grid production` ·
`Solar production` · `loaded` · `not loaded` · `not applicable (no PV)` · `No data loaded yet.` ·
`Choose your data sources to get a result.` · `Results` · `Configure data` · `Update` ·
`Delete data` · `Delete analysis`

*`workspaces.html`:* `Your analyses` · `+ New analysis` · `You have no analyses yet.` ·
`An analysis is one household and one question: your data, your contract, and the battery you are
considering.` · `Delete this analysis?` · `This cannot be undone.` · `Cancel` ·
`"%(title)s" and everything in it — the configuration, the loaded data and the results — will be
deleted.` · `Delete the loaded data?` · `The measurements loaded into "%(title)s" will be deleted,
along with the results computed from them.` · ~~`The configuration is kept — your connection,
contract and battery settings stay as they are, your data sources stay chosen, and you can load
data again.`~~ → replaced during the review by `Your connection, contract and battery settings are
kept. You will need to choose your data sources again.`, because the struck sentence was false for
any slot the user had fetched (blocking 2).

*`index.html`:* `← Your analyses` (new); `workspace: local` and `Settings` are now unused.

*`app/workspace_list_view.py`:* `%(phases)s×%(fuse)s A` (badge) and the plural pair
`%(count)s interval · %(res)s` / `%(count)s intervals · %(res)s`.

Three of these already exist in the catalogs and need no work: `Solar production`, `Cancel`
(rendered as "Annuleren" in the check above) and the resolution labels the size line embeds.

Four notes for the translator: `Grid consumption` / `Grid production` are the ROLE names §2′.2 uses
on this screen and are deliberately not the register labels panel ① uses (`Grid import T1` etc.);
the `%(title)s` sentences keep their straight double quotes, which is what the wireframe writes;
`%(phases)s×%(fuse)s A` uses U+00D7, not the letter x; and the contract badge is NOT translatable —
it is the enum value.

## What the spec and the plan got wrong, or left open

**§2′.2's info box is numbered 1–5 but called "four facts".** The prose says "Four facts about the
*dataset*" and then lists five. Five is what the wireframe draws and what was built.

**The plan says "`DELETE`/`POST` for the two deletions".** Both are POST, for the reasons above; the
brief had already settled this and the plan text is the older wording.

**§2′.2's action table does not say where `[ Configure data ]` and `[ Update ]` lead before phases 3
and 4 exist.** Not a defect in the spec — it describes the finished product — but it is the one
place this phase ships a control that 404s, and it is recorded here rather than silently resolved.

**"Nothing was found wrong with §2′.3" — this was wrong, and the review found it.** The claim rested
on reading §2′.3's "source mapping survives" promise as being about `source_generation` alone. It
is not: for a slot that has been FETCHED the mapping lives in `series_meta`, which `delete_data`
clears, so the promise was false for the common case. §2′.3, the dialog copy, `main.py`'s docstring
and the test that asserted it have all been corrected — see "Review findings and fixes", blocking 2.
The one part that does hold is the `source_generation` reasoning, which protects a PRE-FETCH staged
choice and is why that counter is still deliberately untouched.

## Review findings and fixes

A review of the phase-2 working tree raised eight findings — two blocking, four should-fix or
minor, two record-only. The two design questions the blocking findings raised were decided **by the
user**, not here, and are followed rather than re-argued.

### Blocking 1 — a cross-site POST could delete an installation. *User decision: an Origin check.*

**Reproduced.** A single `POST /w/local/delete` carrying `Origin: https://evil.example` was
accepted and removed `simconfig.json`, the workspace row and the whole `data/local/` directory —
`status: 303`, `config exists after: False`, `workspace row after: None`. The `local` id is a
constant every migrated installation shares, so the target needed no guessing. After the fix the
same script reports `status: 403`, `config exists after: True`, and the row intact.

**The user chose a same-site header check over a token**, explicitly to preserve the property
followups B6 declined tokens for: no session, no secret, no new state. `app/csrf.py` is a FastAPI
dependency (`require_same_site`) declared by the three state-changing routes — `POST /workspaces`,
`POST /w/{id}/delete`, `POST /w/{id}/data/delete` — one place rather than three copies, beside
`deps.get_workspace` in the same seam.

**What it does with a missing header, and why.** `Sec-Fetch-Site` is trusted first when present:
it is set by the browser, cannot be set by page script, and distinguishes `same-origin` from
`cross-site` directly. When it is absent, `Origin` is compared against the request's own host. When
BOTH are absent the request is ALLOWED, and that is a deliberate, documented gap: every browser
that can run this app's `<dialog>` and `fetch` sends at least one of the two on a form POST, so the
allow-branch is not reachable from a browser attack — it exists for `curl`, for a scripted local
client, and for any proxy that strips headers. Closing it would need a token, which is the thing
the decision excluded. Written down in `app/csrf.py` and in followups B6 rather than left implicit.

`POST /w/{id}/params` is deliberately NOT covered. It is an idempotent overwrite of one local
parameter set with values the attacker chose blind — which is what B6's original reasoning actually
covered, and it stays covered by it. The asymmetry is a comment in `csrf.py` and in the route, so
it reads as a decision rather than an omission.

**followups B6 rewritten.** Both its premises had become false: the worst outcome is no longer "a
rewritten local parameter set" (it is irreversible deletion), and `workspace_id` is no longer the
hardcoded `local` (phase 1 put it in the path). The entry now records what was reproduced, what is
protected, what is not, and the missing-header gap.

### Blocking 2 — the delete-data dialog promised something false. *User decision: change the copy.*

**Reproduced.** `workspaces.delete_data` deletes every `series_meta` row, and for a FETCHED slot
that row is where the source key and the HA statistic id live (`app/static/ha_fetch.js`'s header,
branch 1 of "Two things carry a source choice across a reload"). Before a delete,
`dataset.load_latest("w1").series_sources` reads `{'grid_import_t1': 'home_assistant', …}`; after
it, `load_latest` returns `None`. Only a PRE-FETCH staged choice in `localStorage` (branch 2)
survives, and that is the branch the dialog copy was written from.

**The user decided the deletion behaviour is right and the statements about it are wrong.** So
nothing about `delete_data` changed; four statements did:

- `specs/20-workspaces-ux.md` §2′.3 — the "keeps the per-slot source mapping" paragraph rewritten
  around the fetched/staged split, citing `ha_fetch.js`'s header, which already draws it correctly.
- The dialog copy in `app/templates/workspaces.html` — the user's replacement sentence, adapted to
  the existing structure. A new msgid.
- `app/main.py`'s `delete_workspace_data` docstring — the claim that the mapping "lives in the
  browser's `localStorage` and is not touched by any backend delete" corrected.
- `tests/test_workspace_list.py` — the test that asserted the `localStorage` property now asserts
  what actually happens, `series_meta` cleared included. It was green while the property it named
  was broken.

### Should-fix 3 — the `IntegrityError` race, now in `migrate_local()`

Phase 1 had a narrow handler around a lifespan `create`; phase 2 removed both, but
`migrate_local()` has the same check-then-act shape — `SELECT COUNT(*)`, connection released,
`create()`. **Reproduced**: 16 threads against a genuine pre-index directory, `IntegrityError` in 2
of 6 runs. The suite never sees it because it needs a real pre-index installation.

It was swallowed by the lifespan's broad `except`, but logged as `workspace migration failed
(ignored)` — and the lifespan docstring tells the reader that message means an installation may be
left unadopted. A misleading scary log during exactly the operation where one matters.

**Fixed by making the count and the insert one transaction.** `migrate_local` now holds the
`dataset.connect()` block across both and inserts the row itself; `_Connection`'s `BEGIN IMMEDIATE`
takes the write lock before the count, so a second thread waits and then sees a non-empty table.
`create()` keeps its own connection for every other caller — the INSERT is factored into
`_insert(conn, …)` so both spellings share one statement. The same 16-thread script reports 0
errors in 6 of 6 runs afterwards. A concurrency test in `tests/test_workspaces.py` drives 16
threads against a genuine pre-index directory and asserts no exception, exactly one caller
reporting an insert, and exactly one row — the second and third being what would catch a "fix"
that merely swallowed the error.

### Should-fix 4 — `delete()`'s atomicity docstring was false, and the ordering failed badly

`delete_data` opens `dataset.connect()` and `delete` opens `db.connect()` — two distinct connection
objects, so `_Connection._depth` (per-connection) never nests them. They were two sequential
independent transactions, and the docstring said otherwise.

**Ordering reversed, docstring corrected.** The workspace row now goes FIRST, then the data. A
crash between the steps used to leave the row present with its measurements destroyed — a surviving
analysis whose data silently vanished, which reads as corruption. It now leaves data rows and files
behind a workspace that is gone from the index: unreachable residue, the same shape the file
`rmtree` already accepts, and the user sees what they asked for. Genuine atomicity was considered
and not attempted: the two tables live in the same file but are reached through two modules'
connections, and threading one through `delete_data` would give it a connection parameter for one
caller's benefit. An honest docstring plus the ordering that fails better is the answer here.

### Should-fix 5 — a replayed deletion dropped the user onto raw JSON

A second POST to an already-deleted workspace 404'd with a JSON body. Reachable by an ordinary
double-click: the form is in a `<dialog>` with no submit-disable. §2′.3 requires the user stays on
the list. Both deletion routes now resolve their workspace through `deps.get_optional_workspace`
and 303 to `/` when it is already gone — a second delete has already achieved the requested end
state. `GET /w/{id}/results` keeps its 404: an unknown id there is a bad address, not a completed
request.

### Minor 6 — `$`-sequences in a title corrupted the dialog

`template.replace(/%\(title\)s/g, title)` in `workspaces.html`: JS treats `$&`, `` $` ``, `$'` and
`$$` specially in the REPLACEMENT string, so a title `My $& Analysis` rendered as
`"My %(title)s Analysis"`. Not a security issue — the value is assigned with `textContent` — but
the dialog then named the workspace differently from the card that opened it, which is what §2′.3
quotes the title for. Replaced with `split('%(title)s').join(title)`, which has no escape syntax.

### Minor 7 — two tests that did not test what they claimed

- `test_the_card_actions_are_links_not_fetches` asserted `'<a class="btn' in card` inside the loop,
  which is loop-invariant and never tied an `href` to an anchor: markup with one `<a>` and two
  `<button data-fetch-target>`s passed. It now matches the anchor and its href together, per target.
- `test_pv_reads_not_applicable_rather_than_not_loaded_without_pv` asserted `"not loaded" not in
  card` over the WHOLE card, which passed only because the fixture loads both grid slots. Scoped to
  the PV row.

### Minor 8 — recorded, not fixed

- **A price-only dataset sets `loaded=True`**, so the card offers `[ Results ]` and reads "not
  loaded" three times. A phase-0 `_data_facts` property the card merely surfaces; the size line is
  correctly omitted and no literal `None` renders. Filed as followup **I9** (I8 was taken) — the
  `loaded` flag arguably wants to mean "has at least one ENERGY series". Seen live while
  screenshotting: the only dataset an out-of-process server can load is the preset spot price, so
  the review screenshots show exactly this card.
- **`_persist_setup_answers` does not `touch()`.** Correct per §2′.10 — a data load must not
  reorder the list — but the badge is documented as "when the configuration was last stored", and
  after a fetch the document is newer than the badge says. One clarifying sentence added where the
  badge is documented (`workspaces.touch`) so nobody closes the gap by adding a `touch`.
- **§2′.2 said "Four facts" over a list of five.** Corrected to five.
- **This changelog reported "930 passed" where the run was 931.** Corrected below.

### i18n

The full `babel.cfg` workflow was run — all three `-k` flags, `--no-fuzzy-matching` on update,
recompile — for the one new msgid and the one removed. The new sentence, "Your connection, contract
and battery settings are kept. You will need to choose your data sources again.", is Dutch as
"Je aansluiting, contract en batterij-instellingen blijven bewaard. Je moet je gegevensbronnen
opnieuw kiezen." — informal "Je" and "gegevens", consistent with the rest of the catalog. No
`#, fuzzy` markers ship.

### Files modified by the review pass

- `app/csrf.py` — **new.** `require_same_site`, `is_same_site`, `_ALLOWED_FETCH_SITES`, and the
  decision record for the missing-header branch and the `params` exclusion.
- `app/deps.py` — `get_optional_workspace` added beside `get_workspace`, for the deletion routes
  only; its docstring says why it must not spread.
- `app/main.py` — the three state-changing routes declare `csrf.require_same_site`; both deletions
  take `get_optional_workspace` and no-op when it is None; `delete_workspace_data`'s source-mapping
  claim corrected; `params` gains the comment recording why it is not covered; module docstring
  gains the same-site paragraph.
- `app/workspaces.py` — `_insert` factored out of `create`; `migrate_local` holds one transaction
  across the count and the insert; `delete`'s ordering reversed and its atomicity docstring
  rewritten; `delete_data`'s docstring rewritten around the fetched/staged split; `touch` gains the
  "last user-initiated save" clarification; module docstring corrected on both points.
- `app/templates/workspaces.html` — the dialog sentence replaced (new msgid), the surrounding
  comment rewritten around the real behaviour, `fill()` switched from `replace` to `split`/`join`.
- `specs/20-workspaces-ux.md` — §2′.3's mapping paragraph and its wireframe copy rewritten; §2′.2's
  "Four facts" → "Five facts"; §2′.10's cascade bullet corrected.
- `followups.md` — B6 rewritten; I3 updated with the ordering change; I9 added.
- `tests/test_workspace_list.py` — the mapping test rewritten to assert what happens; the
  link-vs-fetch and PV assertions scoped (`_role_row` helper added); the two deletion-404 tests
  rewritten for the redirect; replay and traversal tests added; 12 same-site tests added.
- `tests/test_workspaces.py` — the partway-crash test rewritten for the new ordering and the false
  premise it rested on; the 16-thread migration concurrency test added.
- `tests/test_smoke.py` — the delete-data dialog assertion updated to both halves of the new copy;
  a `$`-sequence title test added.
- `app/locales/*` — full `babel.cfg` workflow (extract, update ×2 with `--no-fuzzy-matching`,
  compile). `app/static/app.css` regenerated.

### Verification

**Suite: 967 passed, 2 skipped, 0 failed** (baseline 945 / 2). The two skips are `test_ha_live.py`,
unchanged. Of the 22 added, 12 are the same-site group, 4 the deletion-replay and traversal group,
and the rest are the migration race, the mapping assertion, the crash ordering and the `$` title.

**Playwright: 26 passed** (25 before). The real-browser delete flow — open the dialog, confirm,
land back on the re-rendered list — passes under the new same-site check, which is the check that
would break it if the header logic were wrong. `test_the_delete_data_dialog_says_what_it_keeps`
now asserts both halves of the new copy and that the struck promise is absent.

**Both reproductions re-run after the fix.** Cross-site delete: `403`, config and row intact.
Migration race at 16 threads: 0 errors in 6 of 6 runs, against 2 failures in 6 before.

**Both dialogs screenshotted at 1100×900 in both locales** and read as text. English and Dutch both
carry the corrected sentence; the Dutch reads "Je aansluiting, contract en batterij-instellingen
blijven bewaard. Je moet je gegevensbronnen opnieuw kiezen." No `#, fuzzy` markers in either
catalog.

## Current status

Phase 2 complete, review findings addressed. Followups I6 and I7 closed; I9 opened; B6 rewritten
and I3 updated. Phase 3 not started.

Two things a next pass may want to weigh, neither decided here:

- **Followup I9 (the price-only card) is a product call**, not a cleanup. Tightening `loaded` to
  mean "has an energy series" would withdraw `[ Results ]` from a workspace holding a real dataset
  the user did load; a third "prices only" state is the other candidate.
- **`app/csrf.py`'s missing-header branch** is the residual gap. It is not reachable from a
  browser, so closing it buys nothing against the threat that motivated the check — but it is the
  line that has to change first if the app is ever served anywhere but locally.

Two things carried forward for the next phase:

- **The 14 leakage failures are real and open.** They are the translation pass's work, not a test
  defect, and they should not be closed by editing the test.
- **Three routes the list links to do not exist yet** — `/w/{id}/data` and `/w/{id}/edit` (phases 4
  and 3), and phase 5's wizard, which `POST /workspaces` will redirect to instead of
  `/w/{id}/results`. All three are recorded in the code where the link or the redirect is written.
