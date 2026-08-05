# 20260726 — Workspaces restructure, phase 1 (workspace-scoped routes)

Implements phase 1 of
[20260726-workspaces-implementation-plan.md](20260726-workspaces-implementation-plan.md),
against [specs/20-workspaces-ux.md](../specs/20-workspaces-ux.md) §2′.10, §2′.11 and
[specs/08-architecture.md](../specs/08-architecture.md) §5.1, §5.5.

## Task specification

Thread the workspace id through routes, templates and JS without changing any screen. `GET /`
still renders the current single-page UI, for `local`. No new screens, no template
restructuring. The phase is deliberately awkward: routes become scoped while the UI is still
single-workspace.

1. `app/deps.py` with `get_workspace(...)` per §5.1, resolving the id from the path, 404 on an
   unknown id, traversal rejected at the route rather than by the storage helpers downstream.
2. Re-root five routes under `/w/{workspace_id}/…`. `GET /`, `POST /feature-interest/{key}` and
   `GET /lang/{code}` stay flat.
3. Every browser `fetch()` and the ingest WebSocket URL take the id from `data-workspace-id` on
   `<body>` rather than a literal path.
4. `localStorage`'s `ha.slots` becomes per-workspace (§2′.11); URL and token stay global.

No computations and no persistence signatures changed. Every storage call already took a
`workspace_id`; this phase gives those parameters real values.

## Requirements changes

None from the user. One requirement was *discovered* during the build and is recorded under
obstacles: a fresh installation had no workspace row at all, which scoping turned from harmless
into a page whose every control 404s.

## High-level decisions

**`deps.py` is a FastAPI dependency, not a helper the routes call.** §5.5 invariant 2 asks for
exactly this, and it buys two things beyond compliance: the 404 for an unknown workspace is
uniform because no route body runs before it, and adding authentication is a replacement of
`get_principal` plus `_authorize` rather than an edit to seven routes. `Principal` and
`Workspace` are typed and thin — `Workspace` deliberately carries identity and the two
timestamps and NOT the config or the dataset, so resolving one stays a single indexed read on
paths (the ingest socket, `/results/benchmark`) that never look at the config.

**Traversal is checked at the edge, and the check is a 404.** The three `_workspace_dir` helpers
already reject a separator-bearing id (§5.5 invariant 4) and remain the real guarantee. What they
do about it is *raise `ValueError`*, which an unguarded route turns into a 500 with a stack trace
— and a path segment is client input, so that is the wrong shape. The edge check makes it the
same 404 an unknown-but-well-formed id gets, which also leaks least. Worth noting that Starlette's
router already resolves a literal `/w/../params` before matching, so what actually reaches the
dependency is the percent-encoded and multi-segment spellings; the check is written against the id
VALUE rather than any URL spelling, so it does not depend on which of those the router normalises.

**404 rather than 403 for a workspace the principal may not use.** `_authorize` exists (and is
always true in v1), but a workspace you may not use should not be distinguishable from one that
does not exist.

**The id reaches the JS through `data-workspace-id` on `<body>`, and the WebSocket path does not
go through it.** Two different mechanisms, for a reason:

  * `index.html` reads the attribute once into a `WORKSPACE_ID` and builds every fetch with
    `wsPath('/results')`. Once, at load, rather than per call — the attribute is on a node no
    fragment swap replaces, and a page that had somehow lost it should fail visibly on the first
    request rather than silently address a different workspace.
  * The ingest socket keeps reading the roster's `data-ingest-ws`, which now carries the WHOLE
    scoped path, rendered server-side in `_panel_data.html`. The attribute already had that shape;
    keeping it means `ha_fetch.js` still reads one attribute and knows nothing about URL layout.
    It reads `data-workspace-id` only to key `localStorage`.

The alternative — one JS helper shared by both files — was rejected because the two files have no
shared module scope (no build step, no framework, per §5.1) and creating one for a path
concatenation would be the largest structural change in a phase whose point is that it makes none.

**`ha.slots` is per workspace; the connection is not.** §2′.11 asks for the first. The second is
the deliberate other half: URL and token answer "where is this household's Home Assistant", which
every analysis of that household shares. The slot store answers "which entity feeds which role in
THIS analysis". Stated in the file because the asymmetry looks arbitrary otherwise.

Worth being precise about why the existing staleness rule cannot substitute for the split: it
compares the store's `gen` against this workspace's `source_generation`. Another workspace's
counter is a different integer that can coincide — the mechanism reconciles across TIME, not
across workspaces. The generation rule itself is untouched; only the key changed.

**A pre-existing global `ha.slots` is DISCARDED, not migrated to `ha.slots.local`.** Both reasons
are in the code; the load-bearing one is the second. What the key holds is a pre-fetch staging
convenience — a source, and for HA an entity, chosen but not yet fetched — so losing it costs one
re-selection in a drawer the user is already standing in, and nothing fetched is in there (that
lives in `series_meta` and renders from the dataset). Adopting it would be a silent write into a
named workspace on the user's behalf, and the generation tag would carry over intact and MATCH, so
a mapping staged before the upgrade would come back looking deliberately staged in `local` —
exactly the confusion §2′.11 asks us to prevent, arriving from the time axis instead of the
workspace axis. It is `removeItem`'d rather than left to sit, so it does not linger as a key
nothing reads.

**`touch()` is still not called.** §2′.10 makes a config save the one event that advances
`updated_at`, and `POST /w/{id}/params` is that save — but nothing reads the field until phase 2's
ordering and badge exist, and this phase is meant to change no behaviour. Wiring it belongs with
the screen that shows it. Filed as followup I6 and noted in the route's docstring so it is not
forgotten.

**Test URLs go through one helper, not ~90 literals.** `tests/conftest.py` grows `w(suffix)` and
`seed_workspace()`. Plain module functions rather than fixtures, because most call sites are
inside `_form(...)`-style helpers and parametrize lists where a fixture argument does not reach.
The alternative — rewriting each literal — would have to be redone the next time the layout moves.

## Files modified

- `app/deps.py` — **new.** `Principal`, `Workspace`, `get_principal`, `resolve_workspace_id`,
  `_authorize`, `get_workspace`.
- `app/main.py` — five routes re-rooted under `/w/{workspace_id}/…` with a `deps.get_workspace`
  dependency; every `simconfig_store` / `dataset` / `db` call inside them given the resolved id;
  `_resolve_results_window` and `_persist_setup_answers` take a `workspace_id`; `index()` names
  `db.WORKSPACE_ID` once, deliberately, and puts it in the template context; the lifespan now
  ensures `local` exists (see obstacles); module docstring rewritten around the new URL table and
  the three routes that stay flat.
- `app/templates/index.html` — `data-workspace-id` on `<body>`; `wsPath()` in the panel-③ IIFE and
  the three `fetch()` call sites built through it; file-header comment extended.
- `app/templates/_panel_data.html` — `data-ingest-ws` now renders the scoped path.
- `app/static/ha_fetch.js` — `LS_SLOTS` keyed per workspace; `WORKSPACE_ID` read from `<body>`; the
  legacy global `ha.slots` removed at load; file header given a workspace-scoping section and three
  stale claims corrected (see obstacles).
- `tests/conftest.py` — `W`, `w()`, `seed_workspace()`, and a docstring explaining why the lifespan
  does not run for these clients.
- `app/templates/_panel_params.html` — the `params-form` `action` scoped (review finding 1).
- `tests/test_workspace_routes.py` — **new.** Isolation, unknown ids, traversal, the flat routes,
  and the form-action regression test added by the review.
- `tests/test_results_route.py`, `tests/test_params_route.py`, `tests/test_slot_load.py`,
  `tests/test_ingest_ws.py`, `tests/test_i18n.py`, `tests/test_no_english_leakage.py` — re-pointed
  at the scoped URLs; fixtures seed the workspace row.
- `tests/test_smoke.py` — one new browser test for the `localStorage` scoping and the legacy-key
  discard; header updated.
- `followups.md` — I6 (`touch` unwired), I7 (the lifespan's temporary `local` create), I8
  (`ha_fetch.js`'s drifted header).

## Rationales and alternatives

**Resolving the workspace inside the WS handler instead of via `Depends`.** Considered, because
the ingest route reports everything else as an `error` frame on an accepted socket, and a
dependency raises before `accept()`. Verified what FastAPI actually does: it answers a rejected
WebSocket dependency with an ordinary HTTP 404 and never upgrades. That is the better shape — a
bad workspace id is a bad *address*, not a bad message, and the browser's existing "could not
reach the app's ingest endpoint" path already covers a failed handshake. Using `Depends`
uniformly also means no route can forget the check. Pinned by its own test, because a future
change that moved the resolution inside the handler would still "404" in some sense while
silently changing what the browser observes.

**`GET /` writing the workspace row on demand.** Rejected in favour of the lifespan. A GET that
writes to the database is a worse shape than a startup step that does, and the lifespan already
existed for the phase-0 migration.

**Rewriting the swap layer, or introducing a router.** Out of scope by instruction, and there was
no pressure toward it: the change is one helper and three call sites.

## Obstacles and solutions

**A fresh installation had no workspace at all, so every control on the page 404'd.** Phase 0
deliberately leaves the index empty when `local` has no config and no dataset — §2′.2 wants the
list to show its empty state and the wizard, not a phantom analysis. That was harmless while every
route was flat. Scoping made it a broken page. Caught by `tests/test_smoke.py`'s cost-tint test,
which drives the real setup-band radio through a real browser against an empty data dir — the
only test in the suite that exercises a genuinely fresh installation end to end.

Fixed by having the lifespan create `local` after `migrate_local()` when it is still absent, with
the migration's own `DEFAULT_TITLE` so an adopted installation and a fresh one are
indistinguishable afterwards. Recorded in the docstring and in followup I7 as **temporary**: once
`GET /` is the list, this becomes the phantom workspace §2′.2 does not want.

Worth stating plainly, because it bears on the remaining phases: this was invisible to every
non-browser test. The route tests seed their own workspace, so they never exercise the fresh path.

**`TestClient(app)` outside a `with` block does not run the lifespan.** Every route-test fixture
in the repo is written that way, so the workspace row those tests now need was never created.
Solved with an explicit `seed_workspace()` in each fixture rather than by converting them to
`with` blocks — creating the row is what the test wants to be explicit about, and the migration's
adoption rules are phase 0's business, not something every route test should depend on.

**Two test fixtures `importlib.reload` the app modules.** `app.workspaces` captures the `db`
module object at import, so a reloaded `db` would have left the workspace row in whichever
database the older module still pointed at. Both fixtures now reload `workspaces` and `deps` too.

**A read-back helper that overwrote what it was reading.** The isolation test's
`_capacity_on_panel` originally posted a full valid form to get the panel back, which persisted
the form's own defaults and destroyed the value under test. Changed to post a deliberately INVALID
submission (min SoC above max, §7.3 check 11) naming only the `battery` section: `POST /params`
then re-renders from the candidate — which is built on top of the STORED config — and skips the
save. The assertion that `X-Params-Valid` is `0` is part of the helper, so a future change that
made that submission valid fails loudly instead of silently reintroducing the overwrite.

**`ha_fetch.js`'s file header was already wrong about the route this phase re-rooted.** It said a
backend_load Confirm POSTs `/data/slot/{slot}/load` and reloads. Neither is true: reify moved into
Fetch history, Confirm only stages, and the browser does not call that route at all — only tests
do. The two lines naming the path were corrected here (the route does still exist), along with the
"surviving the reload" paragraph that named the wrong trigger. The rest of that header still needs
a pass against the current code; filed as I8 rather than done here, since it is pre-existing drift
and not what this phase changed.

## Verification

**Suite: 842 passed, 2 skipped.** Both skips are `tests/test_ha_live.py` (needs a live Home
Assistant). The baseline before this phase was 823 passed, 2 skipped — but with `test_smoke.py`
RUNNING rather than skipped: Playwright's Chromium is installed on this machine, so the brief's
"2 skipped, including smoke" did not hold locally. That is what let the fresh-install defect above
be caught at all. The 19 added tests are 18 in `tests/test_workspace_routes.py` plus one in
`tests/test_smoke.py`.

**`GET /` before and after, against the developer's real `data/` directory.** The page renders, and
the diff is **all intended** — six hunks as first written, plus a seventh from the review fix
(`_panel_params.html`'s form `action`, finding 1):

  1. `<body>` gains `data-workspace-id="local"` (and the line break that splits the attributes).
  2. `data-ingest-ws`: `/data/ingest/ws` → `/w/local/data/ingest/ws`.
  3. A comment reflow in the panel-③ IIFE header (`POST /results` → `POST /w/{id}/results`).
  4. The `WORKSPACE_ID` / `wsPath` helper, inserted at the top of that IIFE.
  5. `fetch('/results/benchmark', …)` → `fetch(wsPath('/results/benchmark'), …)`.
  6. `fetch('/results', …)` and `fetch('/params', …)` likewise (adjacent enough to land in one
     hunk each; three call sites across hunks 5 and 6).

  7. `_panel_params.html`'s `<form id="params-form">` action: `/params` →
     `/w/local/params`. Added by the review fix, not present in the first version of this phase.

Checked positively rather than by reading the diff: stripping `<script>`, `<style>` and all tags
from both renders leaves **byte-identical visible text**. Phase 0 could claim a byte-for-byte
identical page; this phase legitimately changes embedded URLs, so the equivalent claim is that
everything a reader sees is unchanged, and that is measured.

**What this check cannot do, learned from finding 1.** A before/after diff shows what changed. It
is silent on an attribute that should have changed and did not — which is exactly what a re-rooting
phase risks, and exactly what shipped. The diff was read as evidence of completeness and it is only
evidence of intent. What actually catches that class of defect is asserting the property directly
(the new form-action test), or grepping for what should no longer exist. Both are cheap; neither
was done here until the review.

**CSS** was not touched, so no `npm run build:css` was needed.

## Review findings and fixes

An adversarial review of the working tree raised four findings, none blocking. All fixed in place.

**1 (should-fix) — `_panel_params.html`'s form `action` was left flat, at a now-dead route.**
`action="/params"` rendered on every page load while `POST /params` had become a 404 (both
verified). Inert while the script runs — `index.html`'s delegated handler `preventDefault()`s and
refetches through `wsPath` — but it is the no-JS fallback, so a JS error earlier in that IIFE, or a
blocked script, made the "Calculate →" button and the setup-band radios navigate to a 404 document.
That fallback worked before this phase, so it is a silent regression rather than a pre-existing gap.

Scoped at both render sites: `index.html`'s include takes `workspace_id` from `index()`'s context,
and `POST /w/{id}/params`'s standalone panel-swap render needed it added. Pinned by
`test_the_params_form_posts_to_its_own_workspace`, confirmed to fail with the flat action restored.

Two claims in this changelog were wrong because of it and are corrected above: "Files modified" did
not list `_panel_params.html`, and the Verification section's before/after render diff was
described as covering the page. It cannot — comparing two renders shows what *changed*, never an
attribute that should have changed and did not. That is a real limit of that check, worth
remembering rather than working around.

**2 (minor) — `ha_fetch.js`'s header still named `/data/ingest/ws`.** A third line naming a
re-rooted path, missed by the correction pass this changelog described as covering "the two lines
directly touching the re-rooted path". Corrected, and it now also records that the file never
builds the scoped path itself — the roster carries it whole in `data-ingest-ws`.

**3 (minor) — the lifespan's create is check-then-act, and mislabelled its own failure.**
`workspaces.create` is a plain `INSERT` on a primary key, so two workers starting together both see
no row and both insert; measured, 2 of 12 concurrent starts raise `IntegrityError`. The outer
handler caught it and logged "workspace migration failed (ignored)" — a message about a step that
succeeded, describing the opposite of what happened, since the row it wanted now exists. The state
was always correct; only the log lied. Now caught narrowly around that one statement. Verified: 12
concurrent starts, no escaped exception, exactly one row.

**4 (minor) — an overstated claim in the isolation test.** Its docstring called the mtime assertion
"the strongest form". It is the weaker companion: `save` goes through `mkstemp` + `os.replace` so a
rewrite does get a fresh inode, but timestamp resolution is finite — over 200 back-to-back rewrites,
14 (7%) left `st_mtime_ns` identical. It can only false-pass, never false-fail, and the byte
comparison beside it catches every mis-scoped write unconditionally. Docstring corrected; both
assertions kept.

## Current status

Phase 1 complete, with the four review findings above fixed. Phase 2 not started.

Two things phase 2 must pick up, both already filed: the lifespan's temporary `local` create (I7)
becomes wrong the moment `GET /` is the list, and `workspaces.touch()` (I6) needs a caller before
the list's ordering means anything.

One observation to carry forward, consistent with phase 0's: the phase's only real defect was
invisible to 823 green non-browser tests and surfaced from the one test that drives a fresh
installation in a real browser. The route tests seed their own preconditions, which is correct for
what they assert and precisely why they cannot see a missing precondition.
