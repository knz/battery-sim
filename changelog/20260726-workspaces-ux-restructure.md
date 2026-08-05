# 20260726 — Workspaces UX restructure (spec/wireframe phase)

## Task Specification

Rearrange the overall screen UX of the app **without changing computations or the data
model**. Replace the current single-simulation, 3-panel layout (with a "simulate cost
savings" toggle above panel 1) with a multi-workspace structure.

User's stated requirements (verbatim scope):

- Support multiple **workspaces** (config + data + results), each with a user-customizable
  title.
- **Main screen**: list of workspace cards, most recent first, with a "create new
  workspace" button at the top.
- **Card contents**:
  - Title = workspace title.
  - Badges: number of phases / capacity per phase (`1x25A`, `3x25A`, …); contract type
    (DYNAMIC / VARIABLE / FIXED); last date/time config was saved.
  - Info box: (1) grid consumption data loaded? (2) grid production data loaded? (3) PV
    production data loaded? (4) start/end date-time of the series (5) total interval count.
  - Action buttons: "configure data", "delete data", "update", "results",
    "delete analysis".
- **Actions**:
  - "delete analysis" → modal confirming deletion of the entire workspace; warn it cannot
    be undone.
  - "delete data" → modal confirming deletion of the data series only, keeping config.
  - "update" → "edit workspace" screen: (1) workspace title (2) zip code, explained as
    used for sunrise/sunset (3) grid connection (dropdown 1x10A, 1x25, 1x35, 1x50, 3x25,
    3x35, 3x40, 3x50, 3x63, 3x80) with an "advanced" collapsible for import/export limit
    overrides (4) contract type with an "advanced" collapsible for pricing parameters and
    day/night windows. VARIABLE/FIXED remain unimplemented as before.
  - "configure data" → screen holding current panel 1 contents plus its side-panel
    behaviour.
  - "results" → screen holding current panels 2 and 3, with panel 2 reduced to only the
    battery-related parameters.
- **Wizard flow** from "create new workspace": edit workspace → configure data → results.
- Footer buttons on "edit workspace" / "configure data" depend on entry point: wizard →
  "previous" / "next"; from a card → "cancel" / "save".

**Deliverable for this round: UX spec / wireframes only. No implementation.**

## Findings from the survey (before any decision)

**The `workspace` concept already exists backend-side, unused by the UI.** Every persisted
row carries `workspace_id`; `db.WORKSPACE_ID = "local"` is a module constant; every path
helper (`simconfig_store._workspace_dir`, `dataset.*`) takes a `workspace_id` and rejects
traversal. §5.5 of `08-architecture.md` states this is deliberate forward-compatibility
scaffolding. The header already renders a static `[workspace: local]` badge. So the
restructure is largely a UI and routing change over persistence that was designed for it —
though there is no workspace *index* (no `workspaces` table exists in code yet) and no route
resolves a workspace id.

**No zip code / geolocation exists anywhere** — not in the code, not in `specs/`. A
case-insensitive search of the whole spec tree for zip/postcode/latitude/sunrise returns
nothing. The zip-code field is genuinely new surface, and nothing consumes sunrise/sunset
today.

**`GridConfig(phases, fuse_a)` maps cleanly onto the requested `1x25A`-style dropdown**;
`connection_capacity_kw_display` already produces the derived kW figure. The dropdown is a
presentation change over the existing two fields, not a model change.

**Coupling to watch:** panel ②'s battery *Coupling* display is set by the topology selector,
and topology's battery-phases options are offered only when `grid.phases == 3`. Grid phases
moving to "edit workspace" while topology stays on "results" splits a dependency across two
screens.

## High-Level Decisions

Answers given by the user when asked (2026-07-26):

1. **Scope answers split by what they shape.** `has_pv` / `has_battery` stay on the
   "configure data" screen (they decide the slot roster); `simulate_cost` moves to the
   "results" screen (it decides which result sections exist). Neither goes to "edit
   workspace". Consequence: the setup band disappears as a construct — its one remaining
   question relocates.
2. **Panel ② reduces to a progressive-disclosure battery box**, not a flat subset: battery
   **usable capacity first**, then a collapsible **"advanced"** pane holding installation
   topology, charge/discharge policy, and the remaining battery parameters. Grid connection
   and Pricing move to "edit workspace" as the user specified.
3. **Spec scope this round: UX only, with data implications noted.** Wireframes and screen
   flows are normative; a short section flags what the backend must gain (workspace index,
   workspace-scoped routes, migration of the existing `local` workspace) without designing
   it. No implementation.

## Requirements Changes

- Panel ②'s reduction was initially stated as "only the battery-related parameters"; on
  clarification it became the capacity-first + advanced-collapsible arrangement in decision 2
  above, which keeps topology and the policies on the results screen rather than moving them.

## Files Modified

- `changelog/20260726-workspaces-ux-restructure.md` (created)
- `specs/20-workspaces-ux.md` (created) — the new UX spec, written as a new file rather than
  a rewrite of `02-ux-wireframes.md` so the current design stays readable side by side while
  we iterate. It references §2.2–§2.4's box contents rather than restating them.
- `specs/02-ux-wireframes.md` (header note only) — flags §2.1 as under revision and points
  at the new file. No content changed.
- `specs/README.md` (one row added to the file table)

## Original user prompt (verbatim, per specs/CLAUDE.md)

> we want to rearrange the overall screen UX of the app, without changing anything about
> computations or the data model.
>
> Currently we have 3 panels with a "do you want to simulate cost savings" toggle before the
> first panel.
>
> We'd like instead to have the following structure:
>
> - support for multiple "workspaces" (config+data+results). Workspaces have
>   user-customizable title.
> - main screen is a list of workspaces. one card per workspace. most recent first. With a
>   "create new workspace" button at the top.
>
> Inside the main screen, inside each card:
> - Card title is workspace title
> - below the title, small badges with main characteristics defined in the config: number of
>   phases / capacity per phase (e.g. "1x25A" or "3x25A" etc); type of pricing contract
>   (DYNAMIC vs VARIABLE vs FIXED), last date/time the config was saved/updated.
> - below the badges, an info box stating: 1) whether the grid consumption data is loaded 2)
>   whether the grid production data is loaded 3) whether the PV production data is loaded 4)
>   start/end date/time of the data series 5) total number of intervals in the data
> - below the info box, a set of action buttons: "configure data"; "delete data"; "update",
>   "results", "delete analysis"
>
> Actions:
> - button "delete analysis" pops a modal dialog to ask the user to confirm deletion of the
>   entire workspace (and remind them it cannot be canceled)
> - button "delete data" pops a modal dialog to ask the user to confirm deletion of the data
>   series but keep the workspace config
> - button "update" leads to a "edit workspace" screen which allows the user to customize: 1)
>   workspace title 2) zip code, with explanation this is used to determine sunrise and sunset
>   times 3) the grid connection properties (dropdown: 1x10A, 1x25, 1x35, 1x50, 3x25, 3x35,
>   3x40, 3x50, 3x63, 3x80) with "advanced" collapsible pane for the import/export limits
>   config overrides   4) type of contract (DYNAMIC vs VARIABLE vs FIXED) with "advanced"
>   collapsible pane for the pricing parameters and day/night window config.  (For now,
>   VARIABLE/FIXED remain unimplemented as before).
> - button "configure data" leads to a "configure data" screen with the current contents of
>   panel 1 (and the side panel behavior)
> - button "results" leads to a "results" screen with the current panels 2 and 3, but panel 2
>   reduced to only the battery-related parameters
>
> UX flows when using the "create new workspace" button ("wizard"):  "edit workspace" ->
> "configure data" -> "results".
>
> At the bottom of "edit workspace" and "configure data", the buttons available should depend
> on whether the screen was opened from the new workspace wizard, or from the workspace card
> in the overview. In the wizard it should be "previous" / "next" and from the workspace card
> "cancel" / "save".
>
> we'd like you to help capture this new design first as overall UX spec / wireframes so we
> can iterate on that before you implement anything

Answers to the three clarifying questions (paraphrased from the user's selections):

1. Scope answers — "Split: PV/battery on data screen, cost on results".
2. Panel ② reduction — "battery usable capacity first, then collapsible 'advanced' panel with
   topology + charge/discharge policy + other battery parameters".
3. Spec scope — "UX spec only, note data implications".

## Rationales and Alternatives

- **Scope answers**: the alternative of moving all three into "edit workspace" would have
  made the card badges richer and let the wizard ask every shape question up front. The user
  chose proximity instead — each answer sits next to the surface it shapes, which keeps
  "edit workspace" about the household's fixed facts (location, connection, contract) and
  avoids asking about PV before the user has seen the data screen.

## Obstacles and Solutions

- Grid phases (moving to "edit workspace") gates battery-phase topology (staying on
  results) — flagged as an open question in the spec rather than resolved unilaterally.

## Round 2 — inline answers to the eleven open questions

The user answered the draft's open questions inline in `specs/20-workspaces-ux.md`, prefixed
`> [knz] A:`. All were integrated and the markers removed. Verbatim answers, in file order:

1. Contract badge when cost is off — *"yes show it, don't disable."*
2. Header badge / gear — *"remove the workspace ID and gear icon from the top right."*
3. Delete data and the source mapping — *"keep the source mapping"*
4. Off-list connection — *"preset only. these are the options available in the netherlands."*
5. Contract box when cost is off — *"show always."*
6. Zip code — *"show/enable the field and persist it in conf. we'll wire it later."*
7. Advanced-pane nesting — *"i'm open to alternate designs as long as we keep the progressive
   disclosure of usable capacity shown first. use best judgement."*
8. Cost toggle placement — *"inside panel 3; greyed out if the contract information was not
   set up in the "edit workspace" screen. If it is greyed out, do include an info button with
   a popup that informs the user they should set up their contract type first."*
9. §2.4's invitation box — *"keep it there for now, we'll iterate later."*
10. Cancel and unsaved changes — *"yes preferably cancel should warn about unsaved changes."*
11. Wizard step 2 gate — *"block "next" until enough data is loaded to estimate house load."*

Question 10 of the original list (do `feature_interest` rows survive workspace deletion?) was
not answered and remains open.

### Judgement calls made where the answer delegated one

- **Advanced pane → tabs** (answer 7 said "use best judgement"). Four tabs — Battery,
  Installation, Charge, Discharge — inside one collapsible, with usable capacity still outside
  it. Rationale: stacking the four boxes would put the illustrated topology selector three
  frames deep, and that selector needs width. Recorded with stacked boxes named as a fallback
  if the band-overlap warning proves awkward to place.
- **Cost-toggle precondition needs a field that does not exist.** Answer 8 requires knowing
  whether "the contract information was set up", but `PricingConfig` is always fully populated
  from appendix A — there is no unset state, so any test against the current fields would pass
  for every workspace and the toggle would never block. The spec proposes an explicit
  `pricing.configured` flag and flags it as the one thing blocking implementation of this
  answer, rather than inventing a heuristic (diffing against defaults is fragile in both
  directions).
- **"Enough data to estimate house load"** (answer 11) was made concrete as §6.3's
  reconstruction being computable: import + export present, PV present if `has_pv`, existing
  battery series present if `has_battery`. Noted that this is a *lower* bar than a full run —
  the spot price is needed for dispatch but not for load — and argued that is the right line
  for the wizard.
- **Off-list connections** (answer 4, "preset only"): the preset list is authoritative, but the
  spec adds that a *stored* off-list value must still render as itself rather than snapping to
  a neighbour, since snapping would silently change `max_import_kw` and therefore the answer.

## Round 3 — the five remaining questions answered

Answered inline again, this time as `A:` lines under each item in §2′.11. Verbatim:

12. Contract-configured definition — *"introduce a flag"*
13. Band-overlap warning placement — *"combine charge/discharge into one tab."*
14. "Changed" on configure data — *"data source changed but "fetch" was not clicked yet"*
15. Minimum data duration — *"no minimum duration"*
10. `feature_interest` and workspace deletion — *"let's elevate feature interest to be
    install-wide instead of per-workspace."*

### Consequences worth noting

- **The advanced pane is now three tabs, not four** (Battery / Installation / Charge &
  discharge). Merging the two policy boxes resolves the overlap-warning problem by removing it:
  the warning sits below both boxes, where it already sits today. It also matches the argument
  that the two policies are halves of one decision — the bands must not overlap.
- **`pricing.configured` is now a specified field**, not a suggestion. Recorded with two rules
  that keep it honest: migration sets it true where `simulate_cost` is already on (so an
  existing user does not lose cost results on upgrade), and it is never cleared automatically,
  matching the existing `economic_guard` retention behaviour.
- **`feature_interest` going install-wide contradicts §5.5 invariant 1** ("Every persisted row
  carries `workspace_id`. No table is implicitly global"). Recorded in §2′.10 as a *deliberate,
  first* exception with the reasoning — interest counters are outbound product telemetry
  already reported under the pseudonymous `installation_id`, not per-household user data, so
  the invariant's purpose (no data leaking between workspaces or, later, accounts) is not
  weakened. Flagged that `08-architecture.md` should record the exception rather than leave the
  two documents in conflict. Migration collapses existing rows by `feature_key`, taking the
  earliest `last_clicked_at`, preserving the thumbed-once-per-household semantics (union, not
  sum). `workspace_state.source_generation` correctly stays per-workspace.
- **The dirty-check on configure data** is now defined as "a slot's source changed but Fetch
  was not pressed", with its own wording ("You have not loaded your data yet") rather than the
  generic discard prompt — what is at risk there is not typing but a change that never took
  effect. Left open whether the mapping carries a marker making "since the last fetch"
  answerable with what exists today.

## Round 4 — last design question answered

Question 16, what sets `pricing.configured`: *"saving the screen"*. Integrated — an abandoned
edit leaves the flag false, matching `[ Cancel ]`'s "what is not saved did not happen"
semantics; `[ Next → ]` sets it on the same terms as `[ Save ]` since it persists.

The design is now fully specified. One implementation question remains (whether "changed
since the last fetch" is answerable from the current slot mapping, or whether the mapping
needs a per-slot generation marker) — for the build to establish, not a design decision.

## Current Status

**Spec complete, three review rounds integrated. Implementation plan drafted. No code changed.**

The build plan is a separate document:
[20260726-workspaces-implementation-plan.md](20260726-workspaces-implementation-plan.md).
Seven phases, phases 0–1 (workspace index, migration, scoped routes) being prerequisites for
everything else. It is proposed, not approved.

`specs/20-workspaces-ux.md` covers: the workspace concept and what it owns (§2′.1); the list
screen with card badges, info box and actions (§2′.2); the two confirmation modals (§2′.3);
the edit-workspace screen with the connection dropdown and the two advanced panes (§2′.4);
configure-data (§2′.5); results with the capacity-first battery box (§2′.6); where the setup
band's three questions went (§2′.7); the footer/entry-point rules and the wizard (§2′.8);
the state-machine implications (§2′.9); the backend implications, noted not designed
(§2′.10); and eleven collected open questions (§2′.11).

§2′.11 records all sixteen resolved decisions across two tables (first round: 11; second
round: 5). Two minor questions remain open, both settleable during the build:

1. Does editing the contract set `pricing.configured`, or does saving the screen?
2. Is "changed since the last fetch" trackable with what the mapping stores today?

No blockers remain in the UX design itself.

Next steps, in no fixed order and for the user to choose between: another review pass;
folding the draft into `02-ux-wireframes.md` as a proper §2.1 replacement now that it has
stopped moving; designing the backend pass (workspace index, route scoping, migration, the
three new persisted fields, the `feature_interest` key change) that §2′.10 only flags; or
starting implementation from the spec as it stands.

Note for whoever does the backend pass: `08-architecture.md` §5.5 needs amending to record
the `feature_interest` exception to invariant 1, or the two documents will disagree.
