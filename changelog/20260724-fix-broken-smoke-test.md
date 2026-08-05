# Fix broken smoke test — stale cost-control assertion

## Task Specification
Investigate and fix the broken test(s) in the suite.

## Investigation
Ran the full pytest suite: **1 failed, 42 passed, 2 skipped**.

Failing test: `tests/test_smoke.py::test_new_pending_controls_marked` (line 136).

The test asserted the page contains the text `"Also simulate cost savings"` — the
label of the *old* cost checkbox. Commit `c8f3254` ("Move has_pv/simulate_cost into
an upfront setup band") replaced that checkbox with a radio pair in the new
`app/templates/_setup_band.html`, relabeled **"Simulate cost savings?"**, with a
pending `[?]` affordance on the disabled "Yes" answer
(`data-feature-key="simulate_cost"`, `name="setup_cost"`).

The test was last modified in `d14d0cd`, which *precedes* `c8f3254` in the linear
history, so its assertion string was never updated. This is a stale test, not a UI
regression: the pending control still exists and is still correctly marked pending.

## High-Level Decisions
Chose a **structural** assertion over a text-match: verify the disabled `setup_cost`
radio plus the `data-feature-key="simulate_cost"` `[?]` button. This matches the
test's stated intent ("renders disabled with a [?] affordance") and is robust to
future wording changes. (User selected this option.)

## Files Modified
- `tests/test_smoke.py` — updated `test_new_pending_controls_marked` to assert on the
  setup-band cost control's structural markers instead of the removed label text.

## Current Status
Fix applied; re-running the suite to confirm green.
