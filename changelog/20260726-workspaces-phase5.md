# Phase 5 — The wizard

Part of the workspaces restructure (`changelog/20260726-workspaces-implementation-plan.md`).
Specification: `specs/20-workspaces-ux.md` §2′.8.

## Task specification

The plan's Phase 5 in full:

> Three steps over the same three screens, differing only in footer (§2′.8). `[ Next → ]`
> persists, so an interrupted wizard leaves a usable workspace. Step 2's `[ Next → ]` is Blocked
> until house load is reconstructable — import + export, PV if `has_pv`, existing-battery series
> if `has_battery` — naming the missing series (§2′.8). No minimum duration.

## What phases 3 and 4 already built

Most of the wizard is in place, because §2′.8's own framing — "the same three screens; only the
footer differs" — meant each screen built its own wizard mode as it landed. Confirmed present
before starting:

- `?mode=wizard` on `GET`/`POST /w/{id}/edit` and `/w/{id}/data`, threaded through
  `workspace_edit_view.wizard` / `data_screen_view.wizard` into both templates.
- Both footers, in both modes, with §2′.8's exact button labels and destinations: step 1's
  `[ ← Previous ]` → `/`, step 2's → `/w/{id}/edit?mode=wizard`, and `[ Next → ]` persisting via
  the same POST as `[ Save ]` and redirecting one step on.
- Both dialogs — the edit screen's "Discard your changes?" and the data screen's differently
  worded "You have not loaded your data yet" — with `[ Keep editing ]` holding default focus, and
  `data-leave` on every control that leaves a screen in either mode.
- The results screen deliberately has no footer and no mode, per §2′.6.

So Phase 5 is three remaining pieces, not a build from scratch.

## The three gaps

1. **`[ + New analysis ]` does not start the wizard.** `POST /workspaces` redirects to
   `/w/{id}/results`, which `app/main.py:274-280` documents as an explicit placeholder ("Where it
   redirects, and why that is temporary") standing in until phases 3 and 4 existed. They now do.
   Destination becomes `/w/{id}/edit?mode=wizard`.
2. **No step indicator.** §2′.8: "A step indicator (`Step 2 of 3`) beside the screen title is
   suggested, not specified." Suggested, so this is a judgement call — see below.
3. **Step 2's Blocked `[ Next → ]` gate is entirely unbuilt.** Nothing in `data_screen_view.py`
   or `main.py` computes reconstructability. This is the substantive work of the phase.

## High-level decisions

### D1 — The gate reads the loaded dataset, not `workspaces.DataFacts`

`workspaces._data_facts` already computes a near-identical predicate for the §2′.2 card badges
(`grid_consumption`, `grid_production`, `pv_production`), with the same "T1 answers the role"
reasoning the gate needs. Reuse was considered and rejected on two grounds:

- It does not cover the existing-battery slots, which §2′.8's gate requires when `has_battery`.
  Adding them would put fields on a dataclass whose one consumer, the card, does not want them.
- It reads `series_meta` from the database, while the data screen already holds a
  `LoadedDataset` from `dataset.load_latest`. Reusing it would mean a second query for facts
  already in hand.

The gate therefore derives from the loaded frames. **The two must not disagree**, so a test
asserts they answer the three shared roles identically for the same workspace — the cheap guard
against the duplication silently drifting.

### D2 — T2 registers are NOT required, diverging from a literal reading of §2′.8

§2′.8 says the gate wants "grid import and grid export ... (both T1/T2 register pairs, per §2.2's
roster)". Read literally that requires four series. The code disagrees, in three places:

- `series_vocab.SERIES_SLOTS` marks `grid_import_t2` / `grid_export_t2` `"optional"`, with a
  comment pointing at §4.1 note 4 ("expected").
- `reconcile.py:189-195` folds the two registers with `_combined`, so an absent T2 contributes
  zero and reconstruction succeeds on T1 alone.
- `workspaces.py:308-311` gates the card badge on T1 only, with the comment "T1 is §4.1's
  required slot of each pair, so its presence answers 'is this role filled'".

A single-tariff household has no T2 register at all. Requiring it would block those users out of
the wizard permanently, with a message naming a series they cannot supply — the opposite of the
gate's purpose. The parenthetical reads as describing the roster's shape rather than setting the
condition, and §2′.8's own stated condition is "§6.3's load reconstruction being computable",
which T1-only satisfies.

**Gating on T1 only.** Filed as a spec-wording correction for Phase 6.

### D3 — Blocked, not hidden, and the button names what is missing

§2.1's Blocked state: greyed, still present, reason beside it. §2′.8 is explicit that the message
names the missing series rather than saying "load data first", because "the user is looking at the
roster that would fix it". The missing slots are named with the same `ROLE_LABEL` strings the
roster rows use, so the message and the table agree word for word.

The gate is enforced server-side as well as rendered greyed: a disabled button is a rendering, not
a guarantee, and phase 4's L3 followup is a live example of what happens when a control's
`disabled` attribute is the only thing standing between a POST and an incoherent state. `POST
/w/{id}/data?mode=wizard` re-renders step 2 rather than redirecting when the gate is unmet.

### D4 — The step indicator is built (taking up the suggestion)

§2′.8 leaves it optional. Building it, because the wizard is otherwise indistinguishable from the
card path except by the footer buttons — a user who arrives at step 2 has no way to know a step 3
follows. Rendered beside the screen title, wizard mode only.

Deliberately a plain text label rather than a clickable stepper: steps are not freely navigable
(step 3 is gated), and a stepper that renders steps a user cannot click would be four new
affordance states to specify for a feature the spec calls "suggested".

## Files to modify

- `app/main.py` — `[ + New analysis ]` destination; the step-2 gate on `POST /w/{id}/data`.
- `app/data_screen_view.py` — the gate's view-model (blocked flag + named missing series).
- `app/templates/workspace_data.html` — Blocked `[ Next → ]` with its reason.
- `app/templates/workspace_edit.html`, `workspace_data.html` — step indicator.
- `tests/` — new coverage for the gate, the redirect, and the DataFacts cross-check.

## Implementation notes

### D5 — The gate's condition lives in `data_screen_view`, its inputs are supplied by the route

`data_screen_view.load_gate(series_names, has_pv=…, has_battery=…)` is the whole condition, as a
pure function over a set of series names. The route hands it the names off the `LoadedDataset` it
already loaded (D1), so the view module keeps the no-I/O rule every `*_view.py` follows and the
condition is unit-testable without a database.

The function is exported separately from `data_screen_view()` rather than being folded into it,
because the POST route needs the same answer with nothing rendered — the server-side half of D3
must not have to build a page in order to decide whether to refuse.

### D6 — What the blocked button says, and how the missing names travel

The view-model emits `blocked` plus `missing`, a list of `ROLE_LABEL` msgids in roster order. The
labels are the untranslated English msgids `data_view.ROLE_LABEL` holds, and the template
translates each with `_()` — the same treatment the roster rows give them, so the message and the
table cannot word the same slot differently. The joining is done in the template with a
placeholder-bearing msgid (`Add %(series)s to continue.`) rather than by concatenating fragments in
Python, per the project's msgid rule.

Naming is unconditional on why a slot is missing: with no dataset at all, EVERY applicable slot is
named. That is the same sentence as "you loaded some of it", which is deliberate — the roster
beside it already distinguishes the two, and a second empty-state wording would be a second string
saying the same thing.

### D7 — The step indicator is one msgid with two holes

`Step %(n)s of %(total)s`, not two literals. Two literals would put "Step 1 of 3" and "Step 2 of 3"
in the catalog as unrelated entries, so a translator could word them differently, and a fourth step
would need a catalog change rather than a template change. The total is a parameter for the same
reason. The numbers are plain integers rather than `i18n.num()` pairs: single digits carry no
grouping separator, so there is nothing for a locale convention to disagree about.

### D8 — Flipping the household radios does not lift the block until the next render

**Superseded by review finding R1 below. Its first bullet was wrong, and the conclusion it
supported produced a defect. Left standing here rather than edited away, because the shape of the
error is worth keeping.**

The original reasoning, verbatim:

> The gate is evaluated server-side at render, so a user on step 2 who answers "no, I have no
> solar" still sees the greyed `[ Next → ]` naming the solar series until something re-renders the
> screen. The roster DOES re-gate live (`applySetupGating` in `ha_fetch.js`), so for a moment the
> roster and the footer disagree.
>
> Left as it is, deliberately:
>
> - The user's next action from that state is `[ Fetch history ]`, which reloads the screen and
>   clears the disagreement anyway.
> - Making the footer re-gate in the browser means duplicating the condition in JavaScript, which
>   is the shape of duplication D1 already rejected once — and this copy could not be tested
>   against the Python one the way `DataFacts` is.
> - The alternative, re-rendering the screen on a radio change, is a round trip on every toggle for
>   a control whose whole point (§2′.5) is that it re-gates instantly.

What was wrong with it:

- **The first bullet's escape hatch does not exist.** `[ Fetch history ]` is itself `disabled`
  whenever nothing is staged (`mappedSlots()` filters on staged HA sources), which is precisely
  the state a user is in immediately after a completed fetch. Verified in Chromium.
- **The analysis only considered the benign direction.** "Unblocked but should block" is harmless
  — the server catches it. "Blocked but should unblock" is not, and it is the direction that
  matters here, because `[ Next → ]` is the only submitter of the form the radios live in. That
  asymmetry is what turns a cosmetic disagreement into a trap.

The second and third bullets still hold, and the fix keeps both: no JavaScript copy of the gate,
and no round trip per toggle. What changed is which side enforces.

**Revised decision: the client explains, the server enforces.** The rendered `[ Next → ]` is never
`disabled` on step 2. It states the block — the reason naming the missing series stays, per §2.1 —
and clicking it POSTs, which persists the household answers and then re-checks the gate,
re-rendering step 2 with a freshly computed message when it is still unmet. The client-side
disagreement D8 described is now harmless in both directions, because nothing about it decides
anything.

## Mutation testing

Each behaviour was reverted and the suite re-run, to check the tests fail rather than merely pass.
Fourteen mutations; twelve were caught immediately, two were not, and both gaps were closed:

| Mutation | Caught by |
|---|---|
| Create redirect back to `/w/{id}/results` | the route test and the browser test |
| Gate requires the T2 registers (the D2 regression) — **`LOAD_GATE_ROLES` and `required` both mutated** | 11 route tests, incl. the dedicated T2 one |
| Solar/battery required unconditionally | 11 route tests |
| Solar/battery never required | 12 route tests, incl. the `DataFacts` cross-check |
| Server-side POST guard deleted | 3 route tests |
| POST guard moved BEFORE the persist | 2 route tests |
| POST guard applied on the card path too | 3 route tests |
| Step indicator numbered 3 instead of 2 | the data and the edit tests |
| Blocked `[ Next → ]` hidden instead of greyed | **only** the browser test |
| Reason element sized to zero height | **only** the browser test |
| `load_gate` returns `[]` unconditionally | 18 route tests + the browser test |
| Route feeds the gate every series regardless of the dataset | 6 route tests |

**The T2 row's mutation has to touch both sides, and this is not a detail.** `load_gate` ends
`[role for role in LOAD_GATE_ROLES if role in required and role not in names]` — `LOAD_GATE_ROLES`
filters the result, so adding `grid_import_t2` / `grid_export_t2` to `required` alone is **inert**:
they are not in `LOAD_GATE_ROLES`, the comprehension drops them, and no test can fail. Verified
during review. A future reader writing the obvious one-line mutation and seeing the suite stay
green would wrongly conclude the T2 guard is worthless. The mutation that means anything adds the
two roles to `LOAD_GATE_ROLES` **and** to `required`.

The two that initially escaped:

- **`next_blocked` without `and wizard` left every test green.** The rendered assertion was
  satisfied twice over — the template's Blocked branch is nested inside its wizard branch — so the
  flag itself was unconstrained. `test_the_card_footer_is_never_blocked` now also asserts the
  view-model directly, and fails against that mutation.
- **The `DataFacts` cross-check does NOT catch the T2 regression**, contrary to what its docstring
  first claimed: T2 is not one of the three shared roles, so requiring it changes no answer the
  test compares. The docstring now records the limit, and the dedicated T2 test is the only guard
  there. Kept rather than widened — extending `DataFacts` to know about T2 would be the reuse D1
  rejected.

The two browser-only catches are the concrete argument for that test earning its place: both
mutations leave markup that every source-level assertion accepts.

## Obstacles

- **The wizard smoke test walked to results with no data**
  (`test_the_wizard_footer_walks_edit_to_data_to_results`). With the gate in place its second
  `[ Next → ]` is correctly refused, so the test now fetches nothing and asserts the BLOCK instead;
  the walk-through-to-results half is covered by a new browser test that seeds a dataset first.
- **`_workspace_url` in the smoke suite returned the create redirect's destination** and roughly
  thirty tests treat that as the results page. Changing the redirect would have moved all of them
  into the wizard's step 1, so the helper now derives `/w/<id>/results` from the created id rather
  than trusting the redirect. The redirect itself is asserted by its own test.

## Files modified

- `app/main.py` — create redirect to step 1; `_data_page` collects the loaded series names and
  passes the gate's answer to the view-model; `POST /w/{id}/data` re-checks the gate in wizard mode
  before advancing. Module header updated with a wizard paragraph.
- `app/data_screen_view.py` — `LOAD_GATE_ROLES` and `load_gate`; two new view-model keys.
- `app/templates/workspace_data.html` — step indicator; the Blocked `[ Next → ]` and its reason.
- `app/templates/workspace_edit.html` — step indicator.
- `app/locales/` — two new msgids, `Step %(n)s of %(total)s` and `Add %(series)s to continue.`,
  with Dutch translations. `nl` is back to 0 untranslated / 0 fuzzy.
- `tests/test_workspace_data.py` — 24 new tests: the gate in both directions for every conditional
  role, the T2 and spot-price non-conditions, the duration non-condition, the server-side guard,
  the card path's exemption, the Dutch rendering, the roster-wording agreement, and the `DataFacts`
  cross-check.
- `tests/test_workspace_edit.py` — 4 tests for the step indicator, including that both screens use
  one msgid.
- `tests/test_workspace_list.py` — the create-redirect test now asserts the wizard destination.
- `tests/test_smoke.py` — `_workspace_url` derives the results URL rather than reading the redirect;
  the create test asserts the wizard starts; the wizard walk seeds a dataset; two browser tests for
  the Blocked state — that it reads as blocked and does not advance, and (R1) that the user can
  escape it by answering "no PV". `_seed_reconstructable_dataset` takes `has_pv`, so it can seed a
  dataset that does NOT satisfy the gate under the stored answers.

No CSS change: the block reuses `.blocked-control`, and every layout class was already in the built
sheet (`npm run build:css` produced no diff).

## Review findings, and their fixes

Found by review of the uncommitted work, before commit.

### R1 (blocking) — the Blocked `[ Next → ]` was a trap with no in-page exit

Reproduced twice in a real browser. The path:

1. New workspace; appendix A defaults `has_pv = True`.
2. The user fetches grid data. They have no array, so the dataset is import + export T1.
3. Step 2 renders Blocked: "Add Solar production to continue." Correct so far.
4. The user does the obvious thing and answers **"Do you have solar PV? → No"**.
5. `applySetupGating` hides the solar roster row. The page has stopped asking for solar.
6. The footer still says "Add Solar production to continue." and `[ Next → ]` is still `disabled`.

Measured at step 6: `next_disabled=True`, solar row hidden, `fetch_disabled=True`.

`[ Next → ]` is the **only** submitter of `#data-form`, which it reaches from outside via `form=`,
and the `has_pv` / `has_battery` radios are inside that form. So disabling it disabled the only
way to submit the answer that clears the block. There was no in-page recovery: `[ Fetch history ]`
is disabled with nothing staged (which is why D8's stated escape hatch does not exist), and
`[ ← Previous ]` is a plain link that discards the radio answer, so the round trip returns to the
identical trap. Only a reload or leaving the wizard got out, and neither saved the answer.

**Fixed by keeping the button live and letting the server-side guard be the sole enforcement.**
That guard already existed, was already tested, and already does the right thing: it persists the
household answers first and only then re-checks the gate, re-rendering step 2 when unmet. So a
click from a genuinely-blocked state records the answers and redraws the screen with an accurate
message — correct in both directions, and exactly what springs the trap. The guard needed no code
change; its comments did, since they described a `disabled` button as the first line of defence.

Rejected: making `applySetupGating` re-evaluate the footer. That is a second implementation of
`load_gate` in JavaScript — the duplication D1 rejected — and unlike the `DataFacts` overlap it
could not be cross-tested against the Python one, so it could drift silently.

Everything else about the Blocked presentation stays, per §2.1: the button is present, not hidden,
and the reason naming the missing series is still beside it. Two presentation changes follow from
the button being clickable:

- **`.blocked-control` is dropped from it.** That class is an opacity dim, and a
  dimmed-but-clickable control is a contradiction — §2.1's dim means "you cannot use this yet",
  which is now false of the button. Review note M3 separately found that stacking it on daisyUI's
  `btn:disabled` made the label quite faint. §2.1 treats the greying as the signal that adjacent
  text explains; here the adjacent text is doing that work on its own.
- **The reason is drawn at full strength** (`text-base-content` rather than `/70`), since it is now
  the whole of the Blocked rendering rather than a note beside a greyed control.

The `data-next-blocked` wrapper and `data-next-blocked-reason` marker stay: the state is real, and
tests key on them.

### M1 — the T2 mutation-testing row understated what was mutated

Corrected in the table above. Mutating `required` alone is inert, because `LOAD_GATE_ROLES` filters
the comprehension's result; only mutating both sides tests anything.

### Mutation testing of the fix

| Mutation | Caught by |
|---|---|
| `disabled` + `.blocked-control` restored on the blocked `[ Next → ]` | both browser tests — the escape test on the assertion that the answer is submittable |
| POST guard gates on the answers as stored BEFORE this request | the escape test (the user never reaches step 3) |
| Seed helper hardcodes `has_pv=False` again (both the helper and the call site) | the escape test's precondition — it fails rather than passing vacuously on a workspace that was never in the trap |

The third is the inert-mutation check the review asked for: the helper's `has_pv` parameter is new,
so mutating only the call site would have been silently absorbed by a hardcoded body.

## Current status

Implemented, reviewed, and tested — **1179 passed, 2 skipped**, including the Playwright suite
(1177 before, plus the two tests R1 added). `npm run build:css` produces no diff. Not committed.

Open, and left for phase 6 or later:

- §2′.8's "both T1/T2 register pairs" parenthetical still reads as requiring four registers. D2
  diverges from it deliberately; the spec wording is the thing that should change.
- §2′.8 words step 2's `[ Next → ]` as "**Blocked** — greyed, with the reason beside it". Since R1
  the button is not greyed and not disabled; the reason carries the state and the server enforces
  it. That is a deliberate divergence for the reason R1 records, and a second spec-wording item for
  phase 6 — §2.1's Blocked state may want a variant for "a control whose own submission is what
  clears the block".
