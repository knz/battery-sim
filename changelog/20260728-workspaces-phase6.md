# Phase 6 — Finish

Final phase of the workspaces restructure (`changelog/20260726-workspaces-implementation-plan.md`).
Phases 0–5 are committed; the app works. What remains is the finishing work the plan deferred to
the end, plus the divergences and coverage gaps the earlier phases filed as they went.

## Task specification

The plan's Phase 6 in full:

> - **i18n**: extract, update both catalogs with `--no-fuzzy-matching`, translate, compile. Then
>   `tests/test_no_english_leakage.py` against the new screens — it only covers `/`, `POST
>   /results` and `POST /results/benchmark` today, so it needs extending to the new routes or the
>   new screens are unguarded.
> - **Playwright**: extend `tests/test_smoke.py` — create a workspace, walk the wizard, confirm
>   a delete, check the cost toggle is blocked without a contract.
> - **Specs**: fold `20-workspaces-ux.md` into `02-ux-wireframes.md` as the §2.1 replacement;
>   reword §3.5's startup rule and §3.4's panel-focus model (§2′.9); amend §5.5 (0.4).

## What the earlier phases already did

Surveyed before planning, because two of the three bullets are partly stale:

**i18n is in a good state, and the leakage scan is already extended.** `PAGES` in
`tests/test_no_english_leakage.py` covers `/`, `/w/{id}/results`, `/w/{id}/edit`, `/w/{id}/data`,
`POST /results` and `POST /results/benchmark` — phase 4 extended it as the screens landed. Both
catalogs stand at 449 msgids, `nl` at 0 untranslated / 0 fuzzy, verified after phase 5. So the
bullet's stated worry ("the new screens are unguarded") no longer applies. What remains is J3:
the scan sees only each screen's DEFAULT render.

**Playwright covers more than the bullet assumes.** The suite runs 38+ browser tests including
the wizard walk (`test_the_wizard_footer_walks_edit_to_data_to_results`), the blocked step-2 gate
and its escape (phase 5), and the blocking-error visibility test (phase 4.2). The delete
confirmation and the blocked cost toggle need checking against what exists.

**The spec fold is untouched and is the bulk of the phase.** `specs/20-workspaces-ux.md` is 974
lines still marked *"Status: draft for iteration"*, proposing a replacement for
`02-ux-wireframes.md` §2.1 (1264 lines). Nothing has been folded.

## The work, grouped

### 1. Specs — the fold and the consequential rewordings

`20-workspaces-ux.md` is a proposal document that the implementation has now settled. Folding it
is what promotes it from "draft for iteration" to specification, and it is the largest single
piece of Phase 6.

Consequential edits the plan names:

- `04-state-machine.md` §3.4 (panel focus model) — describes a three-panel stepper with a setup
  band that no longer exists (§2′.7 dissolved it, phase 4.2).
- `04-state-machine.md` §3.5 (persistence points) — its startup rule ("the server restores the
  most recent workspace and lands the user in `RESULTS_STALE`") contradicts §2′.2's list-first
  home screen.
- `08-architecture.md` §5.5 invariant 1 — already amended in phase 0 for the `feature_interest`
  exception; needs re-reading against the final state rather than assumed done.

### 2. Divergences where the code is right and the spec is wrong

Both were filed deliberately, with the code's reasoning recorded at the time. The fold is where
they get settled in the spec rather than carried as notes:

- **§2′.8's "both T1/T2 register pairs"** reads as requiring four registers for the wizard's
  step-2 gate. Three code sites treat T2 as optional, and a single-tariff household has no T2
  meter at all. (Phase 5, D2.)
- **§2′.8's "greyed" / §2.1's Blocked = "disabled, greyed"** for step 2's `[ Next → ]`. Phase 5's
  R1 found that disabling it made the gate self-locking, because that button is the only submitter
  of the form holding the answers that clear the block. §2.1 arguably needs a variant for a
  control whose own submission is what clears its precondition — that is the open question, not
  just a wording fix.

### 3. Coverage and test-hygiene items filed by earlier phases

- **J3** — the leakage scan sees only default renders, so the edit screen's off-list connection
  label, page-level `other_errors` alert, save-error banner and inline field errors are never
  scanned. All four were hand-checked in Dutch during phase 3 and are translated, so this is a
  coverage gap rather than a live leak.
- **The tautological `>=` idiom**, at `tests/test_workspace_edit.py:643` and
  `tests/test_workspaces.py:291`. Both assert `updated_at >= before` where `before` was captured
  from the same row, so the assertion holds even if the write never happened. It is a real
  weakness in the two tests that exist to prove `touch()` fires.

### 4. Not in scope — the five open product decisions

`followups.md` K1, K2, L1, L2, L3 are decisions for the user, not work items, and are deliberately
left for them. L2 and L3 acquired a concrete consequence in phase 5: a user can now walk all three
wizard steps without ever opening the Contract box and arrive at results with the cost toggle live
over appendix-A default rates. That strengthens the case for deciding them but does not make the
decision mine.

## Sequencing

The three groups are close to independent. Specs touch no code; the test items touch no specs.
Doing the spec fold first means the divergences are settled text before the test work cites them.

## Group 1 — the fold: structure chosen, and why

### The user's original prompts

Per `specs/CLAUDE.md`, the human user's own words, verbatim. The whole restructure ran from one
standing instruction given at the start of the work:

> please work on changelog/20260726-workspaces-implementation-plan.md — work on each phase in
> turn; use sub-agents for implementation and review and iterate between them until review is
> clean (if there are minor issues either address them immediately, or file a followup in
> `followups.md`). you can proceed on your own unless there's a question that needs my input.
> you may commit your work between phases.

Every later message was a continuation of it: "continue with phase 3", "proceed", "continue"
(×3), and "pause after committing this phase". Two questions were put to the user during phase
1 and answered "Change the copy and the spec instead" and "Origin check on state-changing
POSTs". **No prompt in this session named the spec work specifically** — Phase 6's content
comes from the plan document the standing instruction points at, quoted at the top of this file.

The task scope for this group, derived from that plan and settled by me rather than by the user:
fold `20-workspaces-ux.md` into `02-ux-wireframes.md` as the §2.1 replacement; reword §3.5's
startup rule and §3.4's panel-focus model; amend §5.5 (0.4); settle the two divergences (the
T1/T2 gate, and the "greyed" `[ Next → ]` against §2.1's Blocked state) in the spec, the code
being right in both. Three fold structures were offered — (a) merge into §2.1 in place and
delete document 20, (b) keep 20 as a document and promote it from draft to specification with
§2.1 deferring to it, (c) a hybrid. The choice, with justification, was left to that pass.

### Chosen: (b), with a hybrid touch on §2.1

`20-workspaces-ux.md` stays a document. It is promoted from *"draft for iteration"* to
specification, `02-ux-wireframes.md` §2.1 is rewritten to describe the shipped structure in
short and defer to it, and §2.1's material that survived (the availability states, the pending
affordance) stays where every other document already points at it.

Three findings decided this, all measured rather than assumed:

1. **43 citation sites outside `specs/` name the file.** 35 in `app/` and `tests/`, 4 in other
   spec files, plus the document's own. They cite `specs/20-workspaces-ux.md §2′.N` as a path
   and a prose section number, not as a markdown anchor. Deleting or renumbering the document
   breaks all of them at once, for a tidiness gain.

2. **Merging the §2′.N numbering into `02-ux-wireframes.md` would make the anchors
   confusable, though not identical.** The prime `′` (U+2032) is punctuation and GitHub's
   slugger drops it, so `## 2′.4 Edit workspace` generates `24-edit-workspace` while §2.4
   generates `24-panel-③-results-expanded`. **Checked against the real headings: no pair
   collides** — the circled digits survive slugging and the titles differ, so all sixteen
   anchors stay distinct. What a merge would produce is two families of sections sharing
   `22-`/`24-` prefixes and differing only by title, in one file, which is a readability cost
   rather than a breakage. On its own this finding would not decide the structure; finding 1
   does. Recorded because an earlier draft of this note claimed the anchors "collide
   outright", which measurement did not support.

3. **The prime notation is what already breaks the document's own links.** All 21 of its
   intra-document `](#2′N-…)` links are broken today, for exactly the reason in finding 2 —
   the link keeps the prime, the generated anchor does not. This is pre-existing breakage,
   independent of the fold, and it is repairable in place by dropping the prime from the link
   targets only. Doing that is cheap and touches no referrer, because no external citation
   uses these anchors.

So the prime notation becomes permanent, which is the honest reading of what happened: the
document stopped being a parallel proposal when phases 0–5 shipped it, but its section numbers
had by then been written into 43 places, and stability there is worth more than the tidiness of
a single §2 sequence. The header's own constraint — that §2.2–§2.4 still hold and are
referenced rather than restated — is what makes two documents the natural shape rather than a
compromise.

### What changed in each file

- **`specs/20-workspaces-ux.md`** — status promoted from draft to specification; header
  rewritten to say it supersedes §2.1 rather than proposes to. The 21 broken intra-document
  anchors fixed by dropping the prime from the link targets. The two divergences settled (see
  below). §2′.6's "no footer buttons" paragraph no longer claims parameter edits persist
  debounced without a `[ Calculate → ]`, which is not what the app does.
- **`specs/02-ux-wireframes.md`** — §2.1 rewritten: the stepper wireframe and the setup-band
  subsection are replaced by a short statement of the shipped structure (a list of workspaces,
  three per-workspace screens) that defers to 20 for it. The availability states and the
  pending affordance stay in §2.1 unchanged in substance, because 9 documents point at them.
  §2.2/§2.3a/§2.3/§2.4 keep their box-level contents; the statements the restructure
  invalidated — setup band, panel CTAs, panel collapse — are reworded in place.
- **`specs/04-state-machine.md`** — §3.4 and §3.5 reworded (below).
- **`specs/08-architecture.md`** — re-read; see below.
- **`specs/README.md`** — the catalogue row for 20 no longer calls it a draft.

### §3.4 and §3.5

**§3.4** described `COLLAPSED_INCOMPLETE` / `EXPANDED` / `COLLAPSED_COMPLETE`, a CTA in panel
*n* collapsing *n* and expanding *n+1*, and a setup band with no focus state. None of that
mechanism exists. What survives is the requirement the old text stated as an aside, and it is
kept as the section's substance: **parameters and results must be visible together**, so that a
user can watch results change while editing parameters. §2′.6 delivers it by putting the
battery box and the results on one scrolling screen. The section now describes screens rather
than panel focus states, and the data summary's "hides when panel ① collapses" consequence is
dropped, because there is no collapse.

**§3.5**'s startup rule ("the server restores the most recent workspace and lands the user in
`RESULTS_STALE`, then immediately recalculates") is replaced by the list-first rule: startup
renders the workspace list, which is outside the state machine (§2′.9), and no workspace is
restored or recalculated until one is opened.

§3.5 also specifies `PARAMS_CHANGED` as a persistence point, debounced by
`params_persist_debounce_ms` (default 1000). **That debounced auto-persist was never built** —
a parameter edit still requires `[ Calculate → ]`. This is flagged in the spec as specified and
not built rather than silently rewritten to match the code, because which of the two is wrong
is a product decision, not a documentation one. `20-workspaces-ux.md` §2′.6 cited the debounce
as settled fact ("recompute and persist as they always have"); that sentence is corrected,
since it was describing behaviour that does not exist.

### §5.5

Re-read against the final state. **Invariant 1 is already correct** and needs no edit: phase 0
added the `feature_interest` exception, and it states the exception's scope (`feature_interest`
and nothing else), its reasoning, and the explicit carve-out that
`workspace_state.source_generation` stays per-workspace. §5.1's Feature-interest subsection
agrees with it. The only thing amended in `08-architecture.md` is the two anchor links into
document 20, which carried the prime and were therefore broken.

## Group 2 — the two divergences, settled

### D2 — the wizard gate and the T2 registers

§2′.8 read "both T1/T2 register pairs", which taken literally requires four series. Three code
sites disagree and are right: `app/domain/series_vocab.py` marks `grid_import_t2` /
`grid_export_t2` `"optional"` citing §4.1 note 4's "expected"; `app/domain/reconcile.py` folds
each pair with `_combined`, so an absent T2 contributes zero and the reconstruction succeeds on
T1 alone; `app/workspaces.py` gates the card badge on T1. A single-tariff Dutch household has
no T2 register at all, so a literal gate would lock those users out of the wizard behind a
message naming a series they cannot supply.

**Settled in the spec:** the gate requires the T1 register of each pair. T2 is folded in when
present and contributes zero when absent. The reasoning is kept to two sentences in §2′.8.

### R1 — the Blocked `[ Next → ]`, and what §2.1's Blocked state means

Phase 5 found that disabling step 2's `[ Next → ]` made the gate self-locking. That button is
the only submitter of `#data-form`, and the `has_pv` / `has_battery` radios live inside that
form, so a household whose stored answers say "I have solar" but whose dataset has none could
not submit the answer that would clear the block. `[ Fetch history ]` is also disabled in that
state, and `[ ← Previous ]` discards the radio answer, so the round trip returns to the same
trap. Reproduced twice in Chromium. The fix keeps the button live and makes the server-side
check the sole enforcement — it persists the answers first, then re-checks the gate.

**Settled as a caveat on Blocked's definition, not a sixth state.** This is a judgement call
and is flagged as one in the spec; the alternatives were a sixth availability state and a
documented sub-case of Blocked.

The reasoning for preferring a caveat: the five states answer *why is this control not usable*,
and the answer here is unchanged — a precondition is unmet, and the user can clear it. That is
Blocked, and nothing about the meaning changed. What R1 found is a defect in Blocked's
prescribed *rendering*, and it applies wherever the same shape occurs, so writing it as a
sixth state would split one meaning across two rows of the table on a rendering difference. The
rule added to Blocked is: **greying is the default rendering, and it is wrong when the control's
own submission is what clears the precondition** — in that case the control stays live, the
reason beside it carries the Blocked meaning at full strength, and the server-side check is the
enforcement. A disabled button was never the enforcement anyway; it is a rendering.

The confound worth naming: only one instance of this shape is known, so the rule is generalised
from a single case. If a second turns up and does not fit, the sixth-state reading gets
stronger.

## Anchors — measured before and after

Checked mechanically with a GitHub-compatible slugger (letters, marks and **all** number
categories retained; other punctuation dropped; whitespace to `-`), over every
`](file.md#anchor)` and `](#anchor)` link in `specs/`.

- **Before: 29 broken. After: 19. Ten repaired, none introduced** — re-measured
  independently with GitHub's own slug rule (lowercase, drop characters outside
  `[\w\s-]`, then spaces to hyphens). An earlier count in this file said "50 → 27,
  twenty-three fixed"; that used a stricter slugger which also stripped the spaces
  flanking a dropped em-dash and so scored correct `--` anchors as broken. The
  direction and the "none introduced" conclusion survive re-measurement; the
  absolute numbers did not.
- **One genuine new break was found and fixed in this pass**: a link added to
  `02-ux-wireframes.md` spelled §2.4's anchor `#24-panel--results-expanded`, dropping
  the circled ③ that GitHub keeps. Corrected to `#24-panel-③--results-expanded`. It
  belonged to the pre-existing class below, but it was newly written, so it is written
  correctly rather than added to the backlog.
- The 23 fixed are the prime-in-link class: 21 intra-document `](#2′N-…)` links in
  `20-workspaces-ux.md` and the 2 links into it from `08-architecture.md`. All were fixed by
  dropping the prime from the *link target* only; the headings and the §2′.N notation are
  unchanged, so no citation elsewhere moved.
- The remaining 27 are pre-existing and untouched. They are almost entirely one class: the
  circled digits in `## 2.2 Panel ① …`, `## 2.3 Panel ② …` and `## 2.4 Panel ③ …` are
  category `No` and GitHub **keeps** them, so the true anchors are
  `22-panel-①--data-input-expanded` and so on, while all 17 referrers spell them without.
  Fixing that class means editing 10 files and is out of this task's scope; it matches
  followup F1's record of spec anchors already broken at an earlier HEAD.
- Removing the `### The setup band` heading from §2.1 would have broken 6 external links to
  `#the-setup-band` (in `01-product-brief.md`, `05-data-formats.md`,
  `06-home-assistant-ingestion.md`). All 6 were repointed — three to `#21-overall-layout`,
  three to §2′.7, whichever now carries the statement they were citing. This is counted in
  "none introduced" above.

## A third divergence, found and not fixed

**`04-state-machine.md` §3.5's `params_persist_debounce_ms` debounce is specified and not
implemented.** Verified by grep: the constant appears in `specs/04-state-machine.md`,
`specs/appendix-a-defaults.md` and two spec-citing comments, and in no executable code.
`[ Calculate → ]` in `_panel_params.html` is the only committer of a parameter edit. This is
distinct from the two known divergences in that neither side has been argued: it is not
"the code is right and the spec is wrong", it is a specified feature that was never built.
Flagged in §3.5 as such rather than resolved either way, and the false claim it had produced
in §2′.6 ("recompute and persist as they always have … debounced") is corrected.

## Left undone, and what was not verified

- **The circled-digit anchor class** (27 links, 10 files) — pre-existing, out of scope.
- **Behaviour claims in §2.2–§2.4 were not re-verified against the code.** Only the statements
  the restructure invalidated were touched: the setup band, the inter-panel CTAs, panel
  collapse, and the data summary's placement. Everything else in those sections is left as
  written, including claims that may have drifted for reasons unrelated to this restructure.
  The verified ones are: the data summary renders on the configure-data screen below the
  data-quality box (`workspace_data.html`); `[ Calculate → ]` is the parameter commit; the
  `has_pv`/`has_battery` footer save exists alongside the fetch commit (`data_screen_view.py`).
- **Group 3** (J3's leakage-scan coverage gap, the two tautological `>=` assertions) not
  started.
- The suite passes: **1210 passed, 2 skipped**. That is above the 1179 baseline because the
  working tree already carried uncommitted changes to four test files from earlier work; this
  task touched no test and no code.

## Current status

Group 1 and group 2 complete. Group 3 (the coverage and test-hygiene items) not started.

---

# Group 3 — coverage and test hygiene (tests/ only)

Written by the agent that owned group 3. Touches `tests/` only; no `app/` change, no spec change.

## J3 — the leakage scan sees only default renders

**What was already covered.** `tests/test_no_english_leakage.py` already scanned six surfaces
across seven dataset scenarios, and already had one non-default-render idiom in it:
`test_validation_messages_are_dutch` drives `POST /params` through fourteen invalid submissions.
So the machinery for "a POST that returns a validation error" existed; what was missing was that
nothing applied it to the screens J3 names.

**What was genuinely missing.** Seven error/edge surfaces, none of them scanned:

| render | surface |
|---|---|
| `edit_off_list_connection` | §2′.4's extra `<select>` entry for a stored pair matching no preset |
| `edit_inline_field_error` | `field()`'s inline `errors`, beside the input |
| `edit_other_errors` | the page-level alert for a blocking issue outside `EDITED_FIELDS` |
| `edit_save_error` | the edit screen's write-failed banner |
| `data_save_error` | the configure-data screen's write-failed banner |
| `results_hidden_errors` | phase 4.2's alert above the advanced pane |
| `data_blocked_next` | phase 5's blocked step-2 reason, with its joined role labels |

The last three are beyond J3's four; all three were checked to exist before being covered.

**Structural decision: a second axis, not more entries in `_PAGES`.** What these renders say
depends on the SUBMISSION and on a small forced config, not on which dataset is stored. Adding
them to `_PAGES` would have multiplied them across all seven scenarios for the same strings, at
seven times the cost. They live in their own module-scoped `error_renders` fixture instead, and
reuse the same two scanners through a new `_english_offenders` helper extracted from the existing
prose test — one threshold, three callers, so a surface cannot end up scanned under a looser rule
than its neighbours.

`_ERROR_MARKERS` mirrors `_SCENARIO_MARKERS`: each render must still contain a short Dutch marker,
so a route that starts taking the success path fails loudly instead of leaving the scan passing
against an ordinary render. The fixture also asserts `status_code == 200` per render, which
catches the redirect case (a route that stopped refusing).

`save_error` is reached by making `simconfig_store.save` raise `OSError` — the real trigger, since
the routes catch nothing else. Faking the view-model flag would assert on the view rather than on
the route that sets it.

**Result.** 21 new tests. All seven surfaces were found already translated, as J3 predicted — no
live leak. Verified non-inert by flipping the fixture's cookie to `lang=en`: 18 of the 21 fail.

## The tautological `>=` idiom

**Scope.** Grepped `tests/` for `>= before`, `>= created`, `>= earlier`, `>= start`, `>= t0`,
`>= prev`, `>= ts` and `> before`. Exactly three sites, and one of them is not a defect:
`tests/test_workspace_data.py:593` had already found this shape in its own copy, replaced it with
an ORDERING assertion over two workspaces, and recorded the measurement — "deleting
`workspaces.touch` from the route left the whole non-browser suite green". So the pattern does not
repeat beyond the two named sites.

**The fix, at both sites: back-date the row, then assert `>`.** The stored `updated_at` is set to
a fixed instant in the past that the route's own clock cannot produce, which makes the comparison
a real constraint instead of a restatement of the fact that time moves forward. Chosen over
freezing the clock (which would couple the tests to the private `workspaces._now`) and over the
ordering idiom (which fits a route test with two workspaces better than it fits a unit test of
`touch()` itself). A back-dated row also lets the failed-submission half assert exact EQUALITY
against a known value rather than "unchanged".

`tests/test_workspace_edit.py` gains a `_backdate` helper; `tests/test_workspaces.py` does the
same UPDATE inline, since it is the only site there.

**Mutation testing.** With `touch()` made a no-op (`return` inserted before its UPDATE, file
backed up and restored by copy, not `git checkout`):

- before the fix: both tests passed with `touch()` disabled — neither constrained it.
- after the fix, `touch()` disabled: **2 failed**.
- after the fix, `touch()` restored: **2 passed**, and `tests/test_workspaces.py` +
  `tests/test_workspace_edit.py` together at 68 passed.

## Playwright audit against the plan's bullet

Audited all four; three were already covered end to end and were left alone.

| bullet | verdict | test |
|---|---|---|
| create a workspace | covered | `test_the_list_creates_a_workspace_and_starts_the_wizard` — clicks the real button, asserts the redirect lands on `/edit?mode=wizard` with a live indicator and footer, and that the list grew by one |
| walk the wizard | covered | `test_the_wizard_footer_walks_edit_to_data_to_results` — the full three-step path including `Step 1 of 3` / `Step 2 of 3`, the backward step, and step 3 having no indicator. Phase 5's blocked-gate and escape tests cover the gated branch |
| confirm a delete | covered | `test_the_delete_dialog_names_the_workspace_and_deletes_it` — opens the dialog, checks it quotes the title, cancels (card survives), confirms, and asserts the card is gone from the re-rendered list. Suspected to be the gap; it is not |
| cost toggle blocked | **partly** — gap filled | `test_the_cost_tint_actually_renders_and_is_not_merely_a_class_name` drives Blocked→live, but asserts the blocked half through `is_disabled()` alone |

**The gap, and why it counted as one.** §2.1's Blocked is "greyed, with an adjacent affordance
saying how to clear the precondition". Neither half is an attribute. The greying is
`.blocked-control { opacity: .55 }` — the same kind of rule that, twenty lines below it in
`app.tailwind.css`, parsed and shipped and rendered nothing because daisyUI restated the property
in a later cascade layer, while every class-name assertion passed. And the affordance is a link:
the existing test asserts it is visible, which is not the same as it working. A dialog whose only
action is a dead link leaves the user able to see what blocks them and unable to reach what clears
it.

Added `test_the_blocked_cost_toggle_reads_as_blocked_and_its_way_out_resolves`, on its OWN
workspace and context (the module-scoped one has `pricing_configured` set by the time the tint
test has run, so sharing it would make the result order-dependent). It measures computed opacity
rather than the class, and follows `[ Set up my contract → ]` to assert it reaches
`/w/{id}/edit#contract` AND that a real `#contract` element is there to land on.

**Mutation testing.** Two mutations, each restored by copy afterwards:

- `.blocked-control{opacity:.55}` → `opacity:1` in the compiled CSS: **1 failed**, on the dim
  assertion, with the message naming the cascade-layer hypothesis.
- the dialog link's `#contract` fragment removed from `workspace_results.html`: **1 failed**, on
  the destination assertion.

## Suite

Baseline 1179 passed / 2 skipped → **1210 passed / 2 skipped** (+31: 21 leakage, 1 smoke, and 9
from the parametrized error-render marker test). No regressions; `tests/test_ha_live.py` is the
only skip, as before.

## Gaps deliberately left

- **The scenario × error-render cross product is not covered.** The error renders run once each,
  on one small forced config, not against all seven dataset scenarios. That is the cost trade
  described above and it is a real narrowing: a string that only appears when a save fails ON a
  workspace with a particular dataset would not be scanned. No such string is known to exist.
- **The two leave-guard dialogs were not separately added.** They are in the DEFAULT DOM of the
  edit and configure-data screens (`workspace_edit.html`'s discard dialog, `workspace_data.html`'s
  staged-but-unfetched warning), so the existing `/w/{id}/edit` and `/w/{id}/data` page entries
  already scan their copy. Checked, not assumed.
- **`app.css` is a build artifact and was mutated directly** for the CSS probe rather than
  rebuilt from `app.tailwind.css`. Restored from a backup copy; `git status` is clean on it.
