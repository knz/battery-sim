# Default the spot price source to the energy-charts historical preset

## Task Specification

User request: "for the spot price source, default to the energy-charts
historical preset".

Scope as implemented: when the `price_spot` slot has no committed
source, the source-picker drawer stages the Energy-Charts preset
(`energy_charts`) instead of Home Assistant. This is the drawer's
preselection only — the user still confirms, and already-configured
workspaces are untouched.

## Findings — where the default actually lived

There is no server-side default anywhere. `data_view.py` renders only
the *committed* source (`None` for an unfilled slot), the registry
answers "which sources" and never "which one by default", and the DB
stores per-series provenance of what was loaded, not a preference.

The one and only default rule was `defaultSourceFor` in
`app/static/ha_fetch.js`: prefer the first `browser_fetch` source, else
the first source offered at all. That rule is slot-agnostic, and since
Home Assistant leads every slot's list, `price_spot` staged
`home_assistant`.

Two things surfaced during the investigation that are worth recording:

- `price_spot` offers **three** sources, not two: `home_assistant`,
  `energy_charts` ("Preset historical (Energy-Charts NL)"), and
  `entsoe_nl` ("Preset historical (ENTSO-E NL)"). "The historical
  preset" was therefore ambiguous between two presets; the user named
  energy-charts, so that is the one chosen.
- `registry.py`'s ordering comment already argued Energy-Charts is "the
  better default for a window reaching the present" (it bridges live to
  `now`, while ENTSO-E stops at the last extracted dump), and
  `sample_data.py` shows `price_spot` with `source: "energy_charts"` in
  the demo roster. Both pointed at this default; neither made it real.

## High-Level Decisions

**D1 — put the rule in the JS, not in `SourceDescriptor`.** The
alternative was a server-side `default: true` flag on the descriptor,
passed through `data_view.py`. That is more principled and testable in
Python, but it changes the descriptor shape and touches three source
files to express a preference that currently has exactly one consumer.
Kept the change where the existing default already lives. If a second
slot ever needs a non-HA default, moving it server-side becomes the
better trade.

**D2 — match on the source key, not on kind or position.** `price_spot`
has two `backend_load` presets, so "the first backend_load option" or
"the second source" would pick Energy-Charts today and silently pick
ENTSO-E if the registration order changed. The rule names
`energy_charts` explicitly, and the test pins the key for the same
reason.

**D3 — the fallback is preserved.** If `energy_charts` is not among the
offered sources, `defaultSourceFor` falls through to the old rule
(first `browser_fetch`, then first offered). Nothing regresses for the
other slots, and `price_spot` still stages *something* rather than
leaving every radio unchecked — the bug the function was written to fix.

**D4 — staging only, no reification.** Confirming a backend source
stages it; the load happens on the next Fetch history. The default
inherits that model unchanged, so nothing is contacted at drawer-open
time.

## Files Modified

- `app/static/ha_fetch.js` — `defaultSourceFor` takes the slot name and
  prefers `energy_charts` for `price_spot`; the preference is a named
  constant (`PRESET_DEFAULT_SOURCE`) with the rationale beside it. Its
  one call site passes `draft.slot`. Updated the two file-header
  comments that stated the old rule.
- `tests/test_smoke.py` — added
  `test_the_spot_price_slot_defaults_to_the_energy_charts_preset`: opens
  a pristine `price_spot` slot, asserts the Energy-Charts radio is
  checked and Home Assistant is not, then confirms without an entity to
  show the staged default is a real draft choice rather than a checked
  radio the draft disagrees with.

## Obstacles and Solutions

- No test covered the spot-price default in either direction, so there
  was nothing to regress against — added one. The existing
  `defaultSourceFor` coverage
  (`test_a_successful_connection_preselects_the_slots_entity`) uses
  `grid_import_t1`, so it exercises the fallback path and was unaffected.

## Current Status

Done. Full suite green: 1422 passed, 25 skipped (the skips are the
live-HA suite, skipped by design). Not committed — left in the working
tree for review.

Not done, and deliberately out of scope: the default is still the
drawer's preselection, so a user who never opens the spot-price slot
never gets a source committed for it. Making the slot arrive pre-filled
without opening the drawer is a separate change, and a larger one — it
would need a real committed default somewhere in the server-side state
rather than a staging rule.
