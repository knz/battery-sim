# Owner-scoping without authentication (multi-user readiness, option C)

> **Status:** planned, not yet implemented. This file is the agreed plan; it is updated as the
> work lands.

## 1. Task specification

The user asked where to start in making the app multi-user. Investigation of the current code
against [specs/08-architecture.md §5.5](../specs/08-architecture.md) produced three candidate
scopes; the user selected the third.

### The user's prompts, verbatim

Recorded per `specs/AGENTS.md`, since this work amends `specs/`.

1. *"i'd like to make my app multi-user. where should i start?"*
2. *"let's do (C) for now, make a plan for it"*
3. *"we can include phase 3 now."* / *"no bother on list_summaries"*
4. *"can you write the plan to a file"* → *"write the plan"*

### The three scopes considered

- **(A) Several accounts on one locally-run instance.** Housemates, or one person separating
  work. Auth is a local password or a reverse-proxy header. Close to what §5.5 anticipated.
- **(B) A hosted multi-tenant service.** Substantially larger, and blocked on more than code:
  the design has the *browser* connect straight to the household's Home Assistant over `wss://`
  so the token never reaches the backend (§7.5, and why there is no credentials table). That
  works today because browser and HA share a LAN. Hosted, it depends on the user's HA being
  reachable from wherever they open the app, and the "we never see your token" claim needs
  restating against a server the operator runs. Beyond that: transport security, quotas,
  per-tenant backup, GDPR posture on household consumption data, and `installation_id` telemetry
  ceasing to mean one household.
- **(C) Scoping only — no authentication.** Close the places that assume a single owner, leave
  `get_principal()` hard-coded. Selected.

### Scope of this task

Option (C). Explicitly **out of scope**: CSRF tokens and coverage of `POST /w/{id}/params`
(belongs with sessions), any users table or login, §5.3's missing per-workspace
`ProcessPoolExecutor`, and quotas.

## 2. High-level decisions

### D1 — Do the scoping work before choosing (A) or (B)

The scoping gaps are real bugs under either destination and are independently useful. Doing them
first means that whenever authentication is added, the remaining work genuinely is the
two-function replacement §5.5 invariant 2 promises.

### D2 — `get_principal()` stays hard-coded, and that is the safety property

`get_principal()` keeps returning `Principal(id="local")` and `workspaces.OWNER_ID` stays
`"local"`, so every existing row remains owned by the only principal there is. No workspace
becomes invisible and no data migration runs. The change is that ownership is *carried and
checked* rather than assumed.

### D3 — `list_summaries(owner_id)` takes a required argument

Considered and rejected: `owner_id: str | None = None` meaning "all owners", which would have
spared the test fixtures. An optional filter is exactly how the missing-filter bug gets
reintroduced. Confirmed with the user.

### D4 — Defaulted `workspace_id` arguments are removed now, not deferred

Removing them buys a call-time guarantee that no code path silently operates on `"local"` — the
failure mode that would make a future owner-scoping bug invisible. The cost is a large mechanical
diff. It could reasonably have waited until authentication lands, since the risk only bites once
`get_principal` stops being constant; the user chose to include it now, while the call sites are
fresh.

### D5 — Two signatures become keyword-only rather than being reordered

`dataset.save_dataset` and `dataset.upsert_series` both have a defaulted parameter *before*
`workspace_id` (`sources=None` and `window=None` respectively), so simply dropping the default is
a syntax error. `workspace_id` becomes keyword-only and required (`*, workspace_id: str`) rather
than being moved ahead in the positional list: reordering would silently rebind any caller
passing `sources`/`window` positionally, and keyword-only cannot.

### D6 — Three commits, splitting semantics from mechanics

Phase 3 touches ~76 test call sites with no behaviour change. Kept in its own commit so phase 1's
semantic change is reviewable without that churn alongside.

### D7 — `create`/`_insert` take a *defaulted* owner in phase 1, unlike `list_summaries`

Decided during implementation; the plan had not said whether the new argument should be required.
D3 makes the *read* filter required, and the asymmetry here is deliberate: the two paths fail in
opposite directions. An omitted filter on `list_summaries` returns other owners' rows — a silent
wrong answer no caller can detect. An omitted owner on `create` writes the row as `"local"`, so it
becomes invisible to its intended owner: under-permissioning, which surfaces immediately rather
than leaking. That makes the default tolerable for one phase, not correct indefinitely.

`_insert`'s default is load-bearing — `migrate_local` adopts the pre-index workspace and has no
principal to name. `create`'s is not: `app/main.py` passes the owner explicitly, so the default
exists only to spare test fixtures, which is precisely D4's objection. It is therefore added to
phase 3's scope rather than left implicit.

## 3. Findings — the state of the code before this work

The architecture was designed for this and largely honours §5.5. `app/deps.py` is the intended
seam: `get_principal()` (deps.py:93) returns the hard-coded local principal and `_authorize()`
(deps.py:126) is a single `owner_id` equality that every workspace-scoped route already passes
through via `Depends(deps.get_workspace)`. Routes are re-rooted under `/w/{workspace_id}/…`, path
traversal is rejected both at the edge and in storage, `owner_id` is on `workspaces` from day one,
and filesystem paths derive from `workspace_id`.

The gaps found:

1. **The workspace list is unfiltered.** `workspaces.list_summaries()` (workspaces.py:343) selects
   every row with no owner predicate, and `GET /` (main.py:243) takes no principal. `_authorize`
   protects individual workspaces; the list would expose every owner's titles, contract badges and
   data coverage. The largest correctness gap.
2. **`create` hardcodes the owner.** `_insert` writes the module constant `OWNER_ID`
   (workspaces.py:205) rather than a passed-in principal; `POST /workspaces` (main.py:274) takes no
   principal either.
3. **Defaulted workspace ids hide mistakes.** Ten functions across `db.py`, `dataset.py` and
   `simconfig_store.py` default `workspace_id` to `"local"`, so a caller that forgets one gets
   working-but-wrong behaviour instead of an error.
4. **No session mechanism exists** — no cookie beyond `lang`, no users table, no credential
   storage. That is the new construction (A) or (B) would need.
5. **CSRF would have to change.** `app/csrf.py` is a deliberate header-only same-site check chosen
   to avoid session state; its own docstring says so and names itself as the first thing to change
   if the app stops being local-only. It also deliberately leaves `POST /w/{id}/params` uncovered,
   on reasoning that stops holding once other users exist.
6. **No per-workspace compute isolation.** §5.3 specifies a `ProcessPoolExecutor` keyed by
   workspace; no executor was found in the code, so simulation appears to run inline on the
   request. Fine for one user; under several, one long run blocks everyone.

Items 4–6 are out of scope here and are recorded so the next reader does not have to rediscover
them.

### Measured blast radius of phase 3

Verified by grep rather than estimated: **no `app/` call site** relies on a defaulted
`workspace_id` (the single grep hit in `app/` is inside a docstring). All **76** zero-argument
call sites are in tests, across five files — `test_params_route.py` (29), `test_workspaces.py`
(19), `test_slot_load.py` (15), `test_ingest_ws.py` (10), `test_results_route.py` (3).

`.claude/worktrees/runtime-2/` holds near-duplicate copies of these files. It is a separate
worktree and is left alone.

## 4. The plan

### Phase 0 — this changelog

Written before any code, per the repository rules.

### Phase 1 — owner-scope the two unscoped routes

- `app/workspaces.py` — `list_summaries(owner_id: str)` gains `WHERE owner_id = ?` (the SQL at
  line 358), required argument per D3. `_insert` and `create` take the owner instead of reading
  the `OWNER_ID` constant (line 205); the constant remains for `get_principal` and
  `migrate_local`. Docstrings and the module header's "Main items" block updated.
- `app/main.py` — `GET /` (243) and `POST /workspaces` (274) declare
  `principal: Annotated[deps.Principal, Depends(deps.get_principal)]` and pass `principal.id`.
  The module docstring's flat-route table (~line 101) is updated: those two flat routes now take
  a principal.
- `app/deps.py` — docstring only. `_authorize`'s docstring claims to be the whole authorization
  surface; after this phase that is true for *access* but the list filter is a second site, so it
  gains a pointer to `list_summaries`.

### Phase 2 — cross-owner invisibility tests

These are the real deliverable: the regressions that make a later `get_principal` replacement
safe.

- `tests/conftest.py` — `seed_workspace` gains `owner_id="local"`, leaving existing callers
  untouched.
- New tests, in `tests/test_workspaces.py`'s existing style:
  1. A workspace seeded with `owner_id="other"` is absent from `list_summaries("local")` and
     present in `list_summaries("other")`.
  2. It is absent from the rendered `GET /` HTML.
  3. Every workspace-scoped route 404s on it — `GET /w/{id}/results`, `/edit`, `/data`,
     `POST /w/{id}/params`. This pins `_authorize`'s existing behaviour rather than adding any.
  4. `POST /w/{id}/delete` on another owner's workspace redirects to the list and **leaves the row
     intact**. This is the one place where `get_optional_workspace`'s deliberate 404-softening
     meets ownership, and it is untested today.
  5. `create` writes the principal's id, not the constant.

### Phase 3 — remove the defaulted workspace ids

- Drop the default on `db.source_generation`, `db.bump_source_generation`, `dataset.load_latest`,
  `simconfig_store.config_path`, `.load`, `.is_document_readable`, `.is_pricing_configured` and
  `.save`.
- Keyword-only required on `dataset.save_dataset` and `dataset.upsert_series`, per D5.
- Fix the 76 test call sites across the five files named above.
- `db.WORKSPACE_ID` itself is kept — `migrate_local` and the test fixtures legitimately name the
  migrated workspace.
- **Added during phase 1** (see D7): drop the `owner_id` default on `workspaces.create`. Its only
  production caller passes the owner explicitly, so the default exists solely to spare test
  fixtures — the shape D4 objects to. `_insert` keeps its default, which is load-bearing for
  `migrate_local`.

### Phase 4 — documentation

- `specs/implementation-progress.md` — record that owner-scoping is built and that
  `get_principal` remains hard-coded, so the next reader knows precisely what is left.
- `specs/08-architecture.md` §5.5 — one sentence on invariant 1 noting that *queries* must be
  owner-filtered, not merely rows owner-tagged. Invariant 2's text already describes the end state
  and needs no change.

### Commits

Three, in the repository's three-section format, each referencing this file:

1. Phases 0+1+2 — the semantic change together with its tests.
2. Phase 3 — mechanical, reviewable without the semantics alongside.
3. Phase 4 — documentation.

The test suite is run after phases 2 and 3, with results reported as they come out.

## 5. Files to be modified

| File | Phase | Change |
|---|---|---|
| `changelog/20260804-owner-scoping.md` | 0 | new — this file |
| `app/workspaces.py` | 1 | `list_summaries` owner filter; `create`/`_insert` take an owner |
| `app/main.py` | 1 | `GET /` and `POST /workspaces` take a principal; docstring route table |
| `app/deps.py` | 1 | docstring pointer to the second authorization site |
| `app/workspace_list_view.py` | 1 | prose only — `list_summaries()` → `list_summaries(owner_id)` |
| `app/templates/workspaces.html` | 1 | prose only — same reference fix |
| `tests/test_workspaces.py` | 1 | 14 `list_summaries` call sites (unplanned, see §6) |
| `tests/test_workspace_data.py` | 1 | 8 call sites (unplanned) |
| `tests/test_workspace_list.py` | 1 | 8 call sites (unplanned) |
| `tests/conftest.py` | 2 | `seed_workspace(owner_id=...)` |
| `tests/test_workspaces.py` | 2 | five cross-owner tests |
| `app/db.py` | 3 | drop two `workspace_id` defaults |
| `app/dataset.py` | 3 | drop one default; two signatures keyword-only |
| `app/simconfig_store.py` | 3 | drop five defaults |
| `tests/test_params_route.py` | 3 | 29 call sites |
| `tests/test_workspaces.py` | 3 | 19 call sites |
| `tests/test_slot_load.py` | 3 | 15 call sites |
| `tests/test_ingest_ws.py` | 3 | 10 call sites |
| `tests/test_results_route.py` | 3 | 3 call sites |
| `specs/implementation-progress.md` | 4 | record what is built and what remains |
| `specs/08-architecture.md` | 4 | §5.5 invariant 1: queries, not just rows |

## 6. Obstacles and solutions

- *Two signatures cannot simply drop their default* (non-default argument after default) —
  made keyword-only required instead of reordered, per D5.
- *Phase 1 could not avoid touching tests.* The plan listed no test files for phase 1, but making
  `list_summaries`'s argument required breaks 30 existing call sites across three files. They are
  pure call-site updates passing `workspaces.OWNER_ID`, the same value `get_principal` returns.
- *Review noted the filter could be satisfied vacuously.* Checked: the negative assertions
  (`== []`) sit alongside positive-count assertions on the same rows in the same files, so the
  filter is pinned from both directions and no test now passes because a row went missing.

## 7. Current status

**Phase 1 complete.** Phases 2–4 pending.

- **Phase 0** — this file. Complete.
- **Phase 1** — complete. `list_summaries` is owner-filtered with a required argument, `create`
  and `_insert` carry an owner, and both flat routes take a principal. Reviewed: no blocking
  findings. Suite green at 1271 passed / 2 skipped (the 2 are the known live-HA skips).
- **Phases 2–4** — pending, as specified in §4.

Deferred, not blocking:

- Drop `create`'s `owner_id` default in phase 3 (D7), now listed in that phase's scope.
- Seven test lines in `test_workspace_data.py` and `test_workspace_list.py` now exceed 100
  characters from inlining `mod["workspaces"].OWNER_ID`. No linter enforces a limit and the files
  already had two such lines; a local `ws = mod["workspaces"]` binding would shorten them.

### Deviation from §4's commit plan

§4 groups phases 0+1+2 into one commit. The user asked instead for a commit per phase, so phase 1
lands on its own and phase 2 follows separately — four commits rather than three. The rationale
behind D6 (keeping phase 3's mechanical churn away from the semantic change) is unaffected.
