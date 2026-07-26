# 20260726 — Workspaces restructure: implementation plan

Companion to [20260726-workspaces-ux-restructure.md](20260726-workspaces-ux-restructure.md),
which records the design conversation. This file is the build plan for
[specs/20-workspaces-ux.md](../specs/20-workspaces-ux.md).

**Status: approved 2026-07-26.** Building phase by phase, with a sub-agent review pass between
implementation and commit. Minor review findings are either fixed immediately or filed in
[`followups.md`](../followups.md).

### Build log

| Phase | State |
|---|---|
| 0 — Prepare | done — [changelog](20260726-workspaces-phase0.md) |
| 1 — Workspace-scoped routes | not started |
| 2 — The list screen | not started |
| 3 — Edit workspace | not started |
| 4 — Configure data, and results | not started |
| 5 — The wizard | not started |
| 6 — Finish | not started |

---

## What the survey established

Facts that shape the plan, all verified against the tree rather than assumed:

- **Persistence is already workspace-parameterised.** `simconfig_store.load/save/config_path`,
  `dataset.save_dataset/upsert_series/load_latest`, `db.record_interest/source_generation` all
  take a `workspace_id` and default it to the constant `db.WORKSPACE_ID = "local"`. Path
  helpers already reject traversal. **No storage-layer redesign is needed** — the work is
  giving those parameters real values.
- **There is no `workspaces` table.** §5.1 of `08-architecture.md` specifies one; the code has
  `feature_interest` and `workspace_state` only. The index has to be built.
- **No route is workspace-scoped.** All eight routes in `app/main.py` are flat.
- **There is no htmx.** Panel swapping is hand-rolled `fetch` + `outerHTML` in a ~320-line IIFE
  at the bottom of `index.html`, with delegated listeners (a swapped-in `<script>` re-inserts
  but does not re-execute). Any new screen has to fit that idiom or replace it.
- **`ha_fetch.js` is 1,079 lines** and holds the drawer, the HA connection, the slot state
  machine and the fetch. It keys `localStorage` globally (`ha.slots`, `ha.url`, `ha.token`).
- **i18n is enforced by test.** `tests/test_no_english_leakage.py` renders pages in Dutch and
  fails on English-looking prose. Every new string needs a `.po` entry in both catalogs, via
  the exact `pybabel` invocation in `babel.cfg` (three `-k` flags, `--no-fuzzy-matching`).
- **There is a Playwright smoke test** and a CSS build step (`npm run build:css`).

## The shape of the work

Roughly, in decreasing order of risk:

1. Workspace identity threaded through routes, templates and JS — the structural change.
2. The list screen and its two delete flows — new surface, little existing code to reuse.
3. Splitting panel ② across two screens — the fiddliest, because `params_view.py` (976 lines)
   builds one view-model for one form, and `POST /params` validates the whole config at once.
4. The wizard and the footer modes — mostly new, small.
5. New fields: `title`, postcode, `pricing.configured`.
6. Migration of `local`, and the `feature_interest` key change.

---

## Phase 0 — Prepare (no user-visible change)

**0.1 The workspace index.** New table, per §5.1's shape plus what §2′.2 needs:

```sql
CREATE TABLE workspaces (
    id          TEXT PRIMARY KEY,      -- opaque; "local" is the migrated one
    owner_id    TEXT NOT NULL,         -- "local" from day one (§5.5)
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL          -- config save time; drives ordering + the badge
);
```

`title` lives here, not on the config document — it names the workspace rather than
parameterising a run (§2′.10). `updated_at` is bumped on config save **only**, never on data
load (§2′.10), or loading data would reorder the list.

**0.2 A workspace service.** `app/workspaces.py`: `create`, `list_summaries`, `get`, `rename`,
`touch`, `delete`, `delete_data`. `list_summaries` returns exactly what a card renders — badges
from the config, the five data facts from the dataset metadata — so the list route stays thin
and the card never loads a `SimulationConfig` per workspace if a cheaper read will do.

**0.3 Migration.** On startup, if `workspaces` is empty and a `local` config or dataset exists,
insert `id="local"` with a generated title (§2′.10). Set `pricing.configured = simulate_cost`
so an existing cost-simulating user is not blocked after upgrade (§2′.6). Idempotent.

**0.4 `feature_interest` goes installation-wide** (§2′.10). Drop `workspace_id` from the key,
collapse existing rows by `feature_key` taking the earliest `last_clicked_at` (union, not sum —
interest is boolean per household). `workspace_state.source_generation` stays per-workspace.
Update `tests/test_feature_interest.py`.

> **Also amend `08-architecture.md` §5.5** to record this as a deliberate exception to
> invariant 1, or the two documents contradict each other.

**0.5 The three new config fields.** `title` (workspace row), `postcode` (config document,
stored and read by nothing yet — §2′.4), `pricing.configured` (config document, set on save —
§2′.6). `simconfig_store.from_dict` must default all of them so existing documents load.

*Tests:* migration idempotence; `list_summaries` against a workspace with data, without data,
and with `has_pv=False`; the `feature_interest` collapse.

## Phase 1 — Workspace-scoped routes

Thread the id through without changing any screen yet. `GET /` still renders the current
single-page UI, for `local`.

- `deps.get_workspace(principal, id)` as §5.1 specifies, resolving from the path.
- Re-root the routes: `/w/{id}/params`, `/w/{id}/results`, `/w/{id}/results/benchmark`,
  `/w/{id}/data/slot/{slot}/load`, `/w/{id}/data/ingest/ws`. `/feature-interest/{key}` stays
  flat (now installation-wide) and `/lang/{code}` stays flat.
- 404 on unknown id, and reject traversal at the route rather than relying on the path helpers.
- Every `fetch()` in `index.html` and `ha_fetch.js` takes the workspace id from a
  `data-workspace-id` on `<body>` rather than a literal path.
- **`localStorage` keys become per workspace** (`ha.slots.<id>`) so a mapping staged in one
  analysis does not appear staged in another (§2′.11). URL and token stay global — one
  household, one Home Assistant.

*Risk:* the WS ingest path (`main.py:395–580`) is the longest and least covered by unit tests;
`tests/test_ingest_ws.py` exercises it and must be updated in step with the URL change.

*Tests:* existing route tests re-pointed; a second workspace's params write must not touch the
first's config document.

## Phase 2 — The list screen

- `GET /` becomes the list; the old single page moves to `/w/{id}/results` (phase 4 splits it).
- `_workspace_card.html` renders badges, the info box and the action set, with the no-data
  variant (§2′.2). Card actions are links, not fetches.
- `POST /workspaces` creates and redirects into the wizard; `DELETE`/`POST` for the two
  deletions, each returning to the re-rendered list.
- The two confirmation modals (§2′.3), reusing the existing `<dialog>` idiom — page-level, not
  inside a card, for the same top-layer reason documented in `index.html:54–66`.
- Header loses the `[workspace: local]` badge and the `[⚙]` (§2′.2).

*Tests:* card renders the right badge set from a config; the no-data card omits `[ Results ]`
and `[ Delete data ]`; delete-data leaves `simconfig.json` and the slot mapping; delete-analysis
removes the directory and every keyed row but leaves `feature_interest`.

## Phase 3 — Edit workspace

- `GET /w/{id}/edit` + `POST /w/{id}/edit`, rendering title, postcode, grid connection, contract.
- **The connection dropdown** (§2′.4): ten presets writing `grid.phases`/`grid.fuse_a`, each
  labelled with `connection_capacity_kw_display`. A stored off-list combination must render as
  an extra selected entry rather than snapping — snapping would silently change `max_import_kw`.
- Two advanced collapsibles, preserving contents when collapsed, with an "N overridden" summary.
- `pricing.configured` set on save (§2′.6), never cleared automatically.
- Footer modes (§2′.8) and the dirty-check warning.

*Risk:* `POST /params` currently validates the entire config and returns the whole panel. Two
screens now write disjoint halves. Either reuse the route with a `sections` filter — the hidden
`sections` field already exists for exactly this reason — or split the view-model. Reusing is
less code but keeps a coupling that made panel ② hard to reason about; worth deciding at the
start of this phase rather than during it.

## Phase 4 — Configure data, and results

**4.1 Configure data** — `/w/{id}/data`. Mostly a move: panel ①'s roster, drawer, HA modal,
quality box and glance are unchanged (§2′.5). Adds the "About your household" box for
`has_pv`/`has_battery`, the footer, and the dirty warning keyed on staged-but-unfetched slots
(the existing generation-tagged `localStorage` entry answers this — §2′.11).

**4.2 Results** — `/w/{id}/results`. Battery capacity first, then the three-tab advanced pane
(Battery / Installation / Charge & discharge, §2′.6). The cost toggle moves inside the results
block and is Blocked with an ⓘ dialog until `pricing.configured` (§2′.6).

*Risk:* this is where `params_view.py` is cut. Its `_sections_for` already models "which boxes
were drawn", which is the seam to widen. The illustrated topology selector inside a tab inside
a collapsible needs a real look in the browser — §2′.6 names stacked boxes as the fallback if
tabs do not work.

## Phase 5 — The wizard

Three steps over the same three screens, differing only in footer (§2′.8). `[ Next → ]`
persists, so an interrupted wizard leaves a usable workspace. Step 2's `[ Next → ]` is Blocked
until house load is reconstructable — import + export, PV if `has_pv`, existing-battery series
if `has_battery` — naming the missing series (§2′.8). No minimum duration.

## Phase 6 — Finish

- **i18n**: extract, update both catalogs with `--no-fuzzy-matching`, translate, compile. Then
  `tests/test_no_english_leakage.py` against the new screens — it only covers `/`, `POST
  /results` and `POST /results/benchmark` today, so it needs extending to the new routes or the
  new screens are unguarded.
- **Playwright**: extend `tests/test_smoke.py` — create a workspace, walk the wizard, confirm
  a delete, check the cost toggle is blocked without a contract.
- **Specs**: fold `20-workspaces-ux.md` into `02-ux-wireframes.md` as the §2.1 replacement;
  reword §3.5's startup rule and §3.4's panel-focus model (§2′.9); amend §5.5 (0.4).

---

## Sequencing

Phases 0–1 are prerequisites. 2 → 3 → 4 → 5 is the natural order but 3 and 4.2 both cut
`params_view.py`, so doing them close together avoids reworking the same seam twice.

Each phase leaves the app working. The awkward interval is between phases 1 and 2, where routes
are scoped but the UI still assumes one workspace — worth keeping short.

## What could go wrong

- **`params_view.py`'s split is the main unknown.** 976 lines building one form's view-model,
  now serving two screens with different footers and validation scopes.
- **The hand-rolled swap layer does not obviously survive multiple screens.** It assumes one
  page with three known panel ids. Multi-screen navigation may want real page loads (simplest,
  loses the no-flicker results update) or a small router. §2′.6's requirement that parameters
  and results stay visible together constrains only the results screen — the rest can be plain
  navigation.
- **`ha_fetch.js` is large and central.** The workspace-scoping change touches its storage
  layer, which the drawer's staged-then-confirm behaviour depends on.
- **Translation is not a rounding error.** Three new screens, two modals and the blocked-toggle
  dialog, all needing Dutch, with a test that fails on English prose.

## Open, for the build to settle

- Whether `POST /params` is reused with a section filter or split (phase 3).
- Whether navigation stays hand-rolled or becomes plain page loads (phase 4).
- Postcode format validation, and what eventually reads it (§2′.4) — inert either way.
