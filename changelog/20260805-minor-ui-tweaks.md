# Minor UI tweaks

## Task Specification

User request: "create a workspace, we're going to do minor UI tweaks".

Scope arrives tweak by tweak. First item: the user saw an info box reading
"Annualised projection is disabled for ranges under 90 days…" and asked when it
displays and what it means. After the investigation below, they decided: **drop
it until annualised figures are implemented.**

## High-Level Decisions

- Work happens in a git worktree at `.claude/worktrees/ui-tweaks` on branch
  `worktree-ui-tweaks`.

### Tweak 1 — drop the short-window annualisation notice

**What the box was.** `results_view.py` set `annualisation_disabled` plus a
message whenever the *effective* window (post-clamping to coverage, not the
requested range) spanned fewer than `min_annualisation_days` = 90 days.
`_panel_results.html` rendered it as an `alert-info` box at the top of the
results panel. Spec basis: §7.4 (`15-data-quality-and-limits.md`) and the §2.4
wireframe.

**Why it was dropped.** No annualised figure is computed or rendered anywhere in
the app — confirmed by grepping the templates and the domain layer; the
view-model's own header comment already said "nothing is annualised here
anyway". So the box announced that a projection had been withheld when none
existed, and its closing instruction ("Select 6 months or 1 year to see an
annual figure") pointed at a selection that produced no such figure either. The
guard shipped ahead of the feature it guards.

**What was kept.** `min_annualisation_days = 90` stays as a module constant —
the threshold is the spec's, not a decision to remake later. The Dutch
translation survives as an obsolete (`#~`) entry in the catalogs, so restoring
the box does not mean re-translating it.

**Noted, not fixed.** §7.4 and §6.15 specify a *second* trigger for the same
guard — a window spanning a configuration-epoch boundary. It was never
implemented; `annualisation_disabled` only ever had the day-count trigger. When
the guard returns it should carry both. Recorded in
`docs/specs/implementation-progress.md`, not acted on here.

## Requirements Changes

None. The drop was the user's decision on the first tweak, taken after the
investigation rather than as a change to a prior instruction.

## Files Modified

- `changelog/20260805-minor-ui-tweaks.md` (new) — this file.
- `app/results_view.py` — removed the short-window guard block that set
  `annualisation_disabled` / `annualisation_message`; rewrote the module header's
  "not emitted this increment" entry and the `min_annualisation_days` comment to
  say why the constant is now unread.
- `app/templates/_panel_results.html` — removed the info-box block, leaving a
  comment recording why it is absent; dropped the notice from the header
  comment's list of `msg()` consumers.
- `tests/test_results_view.py` — `test_results_short_window_disables_annualisation`
  became `test_results_short_window_emits_no_annualisation_guard`, asserting both
  keys stay absent on a window that would have tripped the old guard.
- `tests/test_no_english_leakage.py` — dropped the English marker for the removed
  string; repointed the `short_window` scenario's coverage markers at the euro
  section it still renders; updated the two comments describing why that scenario
  exists.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.{po,mo}` —
  regenerated via the `babel.cfg` workflow (extract → update `--no-fuzzy-matching`
  → compile). The removed msgid demoted to `#~` in the .po files.
- `docs/specs/implementation-progress.md` — added the guard to the "Known gaps"
  prose section, including the unimplemented epoch-boundary trigger.

## Rationales and Alternatives

- **Drop vs. reword vs. gate on cost simulation.** Rewording would still describe
  a feature that does not exist; gating on cost simulation is wrong on the spec's
  own reasoning (§7.4 is explicit that annualisation is not a cost feature — an
  annualised kWh saving carries the same seasonal error as an annualised euro
  one). The user chose to drop.
- **`short_window` leakage scenario kept, not deleted.** It existed only to reach
  this box, so deleting it was on the table. Kept because it is the sweep's only
  *short* cost-on render, which is independently worth scanning; its markers were
  repointed at the euro prose it does render.
- **Markers verified, not guessed.** The replacement markers were confirmed
  against the actual render with a throwaway probe test (since removed) rather
  than assumed from the scenario's config.

## Obstacles and Solutions

- The leakage suite asserts every scenario has a coverage marker, so removing the
  only marker for `short_window` would have failed that check — repointed rather
  than removed.
- `_msg_n` looked unused after the removal; it is still used by `period_run`, so
  the import stays.

## Current Status

Tweak 1 complete. Full suite green: 1381 passed, 25 skipped (the skips are the
live-HA suite, which does not run here). Nothing committed yet.

Waiting for the next tweak.
