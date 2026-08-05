# Default `simulate_cost` to on, and reconcile the spec with the wizard

## Task specification (as given)

The user's prompts, verbatim and in order (`docs/specs/AGENTS.md` requires recording them when
spec files change):

1. > the "simulate cost savings" toggle in the results screens. pros/cons of keeping it?
2. > i believe we've changed the implementation (the spec diverges) since the user is invited to
   > enter their contract details when setting up their workspace, before displaying the results
   > screen.
   > this leads me to think we should default to yes - welcoming feedback
3. > do the first. agree spec needs update

   ("the first" = keep `pricing_configured` as-is, rather than tightening it to mean "the user
   actually edited a pricing field".)
4. > regarding §8.18 - it was already incorrect, we've split "has_pv" to a different screen already
5. > beware that the full test suite takes a long time to run (it contains benchmarks). prefer
   > running targeted tests for the bulk of the work. we have CI targets for the full suite anyway
6. > panel 2 asks has_pv, and that's ok - they should be separate

Outcome: **keep the toggle, flip its default from `false` to `true`.**

Decisions taken:

1. **Flip the default.** Chosen over keeping `false` and over leaving it unset and requiring an
   answer.
2. **Keep `pricing_configured` as-is** — do not tighten it to a diff against defaults; that is
   the approach §2′.6 rejected as fragile.
3. **Update the spec**, not just the default.
4. **Decouple §8.16 from §8.18.** §8.16 stays open as its own question — panel ② still asks
   `has_pv` and that placement is correct; only the "decide together" pairing is removed.

## Why the old default no longer holds

§8.18 justified `false` as protecting the five-minute cold-start criterion (§1.6): a first-time
user should reach an energy-only result "without entering a single euro figure". That premise is
no longer true of the implementation:

- `[ + New analysis ]` redirects to `/w/{id}/edit?mode=wizard` — step 1 of the three-step wizard,
  the screen carrying the Contract box (`app/main.py:307`).
- Every successful save of that screen passes `pricing_configured=True` unconditionally
  (`app/main.py:512`), which is what unblocks the results-screen toggle.
- The wizard's step 1 → step 2 → results ordering means a user arriving at results via
  `[ + New analysis ]` has already passed the contract question.

So the default now produces the worst of both: the user answers the contract question, and the
results screen then ignores that answer until they find a toggle. That is §8.18's stated cost
("cost simulation is the more compelling half … some users will never find the toggle") with
none of the cold-start benefit it was bought for.

## Known cost of the decision, accepted

`pricing_configured=True` fires on *any* successful save of the edit screen, including one where
the user left every pricing field at its appendix-A default — the flag records that the user
**passed a point in the UI**, not that they answered (`app/simconfig_store.py:114`). With the
default on, a user who tabs past the Contract box sees euro figures derived from placeholder
rates they never looked at.

Accepted rather than fixed, because the alternative (deriving the flag from whether pricing
differs from defaults) is the exact approach §2′.6 rejected as fragile in both directions, and
because the failure mode here is visible and editable on screen rather than silent.

## Scope boundaries

- **New workspaces only.** Existing workspaces carry their stored `simulate_cost` forward;
  `app/workspaces.py:599` sets `pricing_configured=True` on migration only when cost simulation
  was already on. A user who deliberately turned cost off must not find it back on.
- **No behavioural change to the toggle itself** — Blocked state, retention across toggling,
  `economic_guard` forcing, and the §4.5 additive-layer guarantee are all untouched.

## Files modified

**Application (2 files)**

| File | Change |
|---|---|
| `app/domain/simconfig.py` | `simulate_cost: bool = False` → `True` — the single source of the default; plus the field's docstring rationale |
| `app/sample_data.py` | module comment's stated app default |

**Specification (5 files)**

| File | Change |
|---|---|
| `docs/specs/17-open-questions.md` | §8.18 rewritten as **decided** (`true`), recording the wizard as the reason, the accepted placeholder-rates cost, and what was not adopted; §8.16 keeps its own question but loses the "decide together with §8.18" clause |
| `docs/specs/appendix-a-defaults.md` | defaults-table row and rationale; the closing open-questions list drops `simulate_cost` (five → four) |
| `docs/specs/01-product-brief.md` | §1.4 reframed from "opt-in" to "on by default and switchable off" |
| `docs/specs/02-ux-wireframes.md` | the §2.4 affordance's justification (it now addresses a user who turned cost *off*); §2.3's "with `simulate_cost = false` — the default" and an "opting in" phrase |
| `docs/specs/appendix-b-glossary.md` | "Off by default" → "On by default, switchable off" |

**Tests (5 files)** — see the next section for why each changed.

## What the test failures revealed

The flip surfaced a class of tests that expressed "cost off" by *saying nothing* — relying on
the dataclass default rather than naming the state. Every fix names it explicitly, which is a
durable improvement independent of this change's direction.

| File | Change |
|---|---|
| `tests/test_simconfig.py` | the appendix-A defaults table (`_APPENDIX_A_DEFAULTS`) — the one test that legitimately asserts the default itself |
| `tests/test_params_route.py` | `_form()` omitted the `setup` section entirely, so `parse_form` **inherited** `simulate_cost` from the stored config — it read as "cost off" only while the default was off. Now posts `setup.simulate_cost=no` explicitly. Added `_energy_only_cfg()` and used it at six `store.save(SimulationConfig(), …)` sites; two more tests now store cost-off rather than leaning on the fixture |
| `tests/test_results_view.py` | `_energy_cfg()` — the helper whose whole purpose is "the cost-off half" — returned a bare `SimulationConfig()` and so silently became the cost-*on* half. Now sets the flag. Three inline sites likewise |
| `tests/test_workspace_results.py` | two tests seeded a workspace and relied on the default being off; both now store the state they assert |
| `tests/test_params_view.py` | the two summary-line tests hardcoded `energy only` as the trailing clause. One now tracks the new default (and additionally pins the off case); the other pins cost off, since it is about the battery fields it names |

## Verification

Targeted suites, per the user's instruction to avoid the full run (it contains benchmarks; CI
covers it):

- `test_simconfig.py`, `test_params_view.py`, `test_params_route.py` — 315 passed
- `test_results_route.py`, `test_results_view.py`, `test_workspace_{results,edit,list,data,routes}.py`,
  `test_workspaces.py` — 461 passed
- `test_costs.py`, `test_pricing.py`, `test_metrics.py`, `test_simulate.py`, `test_simframe.py`,
  `test_data_summary.py`, `test_footer.py`, `test_i18n.py`, `test_sources.py`, `test_slot_load.py`
  — 307 passed

**Not run:** `test_benchmark.py` (the slow DP fixtures), and the packaging/desktop/HA-live
suites. `test_benchmark.py` was inspected rather than executed: it contains no bare
`SimulationConfig()`, and every one of its `simulate_cost` sites passes the value explicitly
(`_cfg(simulate_cost=True/False, …)`, including both halves of the fixture-18 bit-identity
test), so the default cannot reach it. Execution is left to CI.

## Obstacles

- `grep --include=*.ts` and a `2>/dev/null` redirect were both refused by the shell/worktree
  guard — reran as plain commands.
- §8.18's premise turned out to be stale in a second way the user flagged: it said to decide
  jointly with §8.16, but §2′.7 had already moved the two toggles to different screens, so the
  shared-friction argument that justified the pairing no longer applied.

## Current status

**Complete.** Default flipped, five spec files reconciled, five test files updated, targeted
suites green. `test_benchmark.py` and the packaging suites are left to CI.

Not changed, deliberately: §2′.6's `pricing.configured` semantics, the migration rule, the
Blocked state, parameter retention across toggling, `economic_guard` forcing, and §4.5's
additive-layer guarantee.

Open for the plan step: whether §8.18 is rewritten as a settled decision or retained as an open
question with its premise corrected, given that §8.18 says to decide it together with §8.16
(`has_pv`), which remains open.
