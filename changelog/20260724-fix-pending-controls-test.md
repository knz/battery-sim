# Fix stale test after slot-first panel ① reshape

## Task Specification

Investigate a test failure introduced by a recent change and fix it.

## Investigation

`tests/test_smoke.py::test_new_pending_controls_marked` failed:

```
assert page.locator("input[name=source][disabled]").count() >= 1  # Upload CSV radio
AssertionError: assert 0 >= 1
```

Root cause: the failure is a stale test, not an app regression. The slot-first
reshape of panel ① (commit 0594e34 and followers) intentionally moved the pending
"Upload CSV" source radio:

- Renamed `name=source` → `name="drawer-source"` (app/static/ha_fetch.js `csvPendingOption()`).
- Relocated it out of always-rendered static HTML: it is now created by JS only when a
  slot's "Choose source…" button opens the source-picker drawer.

The test asserted on the initial page (drawer closed), where that radio no longer exists.
The other two assertions in the same test (`setup_cost`, `simulate_cost`) still pass —
they render on first paint in the setup band.

## Files Modified

- `tests/test_smoke.py` — `test_new_pending_controls_marked` now opens a slot's drawer
  (`.slot-source-btn` first click), asserts `input[name=drawer-source][disabled]`, then
  presses Escape (the drawer's discard-and-close path) before the setup-band assertions.

## Rationale / Alternatives

Fixed the test to follow the intentional UI change rather than restoring an
always-visible Upload-CSV affordance. The commit history frames the slot-first drawer as
deliberate, so the app behaviour is correct and the test's expectation was out of date.

## Current Status

Done. Full suite: 74 passed, 2 skipped (pre-existing). No app code changed.
