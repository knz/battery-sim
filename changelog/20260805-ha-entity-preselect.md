# HA entity pre-selection does not happen on a fresh slot

## Task Specification

The user reported that after configuring Home Assistant connection parameters and a
successful "check connection", the per-slot entity `<select>` in the source drawer stays
empty — where they remembered it pre-selecting a suitable HA sensor for the slot. Question
put to the assistant: did something change, or was the remembered mechanism never there?

Scope, as it settled over the conversation:

1. Determine whether the auto-selection mechanism exists (it does).
2. Determine why it does not fire in the user's flow.
3. Fix it via "option 2" (below), with the added requirement — stated by the user — that a
   **manually customized entity selection must not be lost**.

## Investigation findings

The mechanism exists and is implemented entirely client-side in `app/static/ha_fetch.js`:

- `guessId(series, ids)` (~:497) is a case-insensitive substring scan over the sorted
  statistic ids, driven by a per-slot hint table (`grid_import_t1` →
  `consumed_tariff_1` / `import_t1` / `import_1`, etc.).
- `fillDrawerEntitySelect` (~:461) applies it: `draft.statId || guessId(...) || ""`.

It is **implemented but unspecified** — neither `docs/specs/06-home-assistant-ingestion.md`
(§ "the user binds each series slot ... to one statistic id") nor
`docs/specs/20-workspaces-ux.md` describes auto-mapping. The code comment calls it "a
convenience default only ... Not a mapping authority."

### The heuristic itself is good — verified against the user's live HA

Queried the user's instance (81 `sum` ids, 519 `mean` ids) and replayed `guessId` verbatim:

| slot | guess |
|---|---|
| `grid_import_t1` | `sensor.energy_consumed_tariff_1` ✓ (matches user's expectation) |
| `grid_import_t2` | `sensor.energy_consumed_tariff_2` ✓ |
| `grid_export_t1` | `sensor.energy_produced_tariff_1` ✓ |
| `grid_export_t2` | `sensor.energy_produced_tariff_2` ✓ |
| `price_spot` | `sensor.epex_spot_data2_average_price` ✓ |
| `solar_production` | `""` — **no match** (separate gap, see below) |

So the hint table is not the cause.

### Root cause

User's repro: fresh setup → New analysis → parameters → Next → "Source" on grid import T1 →
drawer opens with Home Assistant *appearing* pre-selected → Configure → check connection
succeeds → card says "✓ Connected" but the entity select is still empty.

The chain:

1. Fresh workspace ⇒ `series_sources` empty ⇒ `row.source is None`
   (`app/data_view.py:219`) ⇒ `data-slot-source=""` (`_data_roster.html:123`).
2. `openDrawer` sets `draft.source = null` (`ha_fetch.js:858`).
3. `renderSourceList`: `radio.checked = (s.key === draft.source)` (~:912) is **false for
   every radio**, so the `if (radio.checked) onSelectSource(s)` at ~:939 never fires.
4. `testConnection`'s refill is gated on `draft.slot && draft.source === "home_assistant"`
   (~:436) — false — so `fillDrawerEntitySelect` never runs and `guessId` never executes.

`updateHaConfigButton()` is called unconditionally (~:439), which is why the button
correctly reads "✓ Connected" while the select stays empty — the misleading combination the
user observed.

The underlying defect: **the drawer can show a source as chosen while `draft.source` says
nothing is chosen.** The empty select is one symptom of that mismatch.

Not fully verified: *why* Home Assistant looks pre-selected to the user. No radio is
programmatically checked; HA is the first `browser_fetch` source and the only enabled option
(CSV is disabled/pending). Hypothesis — a visual artifact of first-radio rendering or the HA
card's distinct styling from its Configure button. Flagged as a hypothesis, not confirmed in
a browser.

## High-Level Decisions

**Chosen: option 2 — fix the root, not the gate.** Two options were put to the user:

1. Narrow: in `testConnection`, refill based on the currently *checked* radio rather than
   `draft.source`.
2. Root: when `draft.source` is null on drawer open, stage a default source (check the sole
   enabled / first `browser_fetch` radio and run `onSelectSource`), making the visible radio
   state and `draft.source` agree.

User chose option 2, with the explicit constraint: **do not lose the select value if the
user manually customized it.**

Rationale for 2 over 1: option 1 patches the one observed symptom while leaving the
UI/state mismatch in place to produce further symptoms. Trade-off accepted: option 2 changes
what a freshly-opened drawer *stages*, which touches the staged-then-confirm invariant the
file documents at length (~:41-53) — mitigated by staging only, never committing to
`slotState` before Confirm.

## Requirements Changes

- Mid-conversation addition by the user: preserve a manually customized entity selection
  (i.e. a re-run of the preselect logic must not clobber a user-chosen `statId`).

## Implementation

Two changes in `app/static/ha_fetch.js`, each verified to be independently load-bearing by
reverting it alone and watching the new tests fail:

1. **`defaultSourceFor(sources)` + staging in `renderSourceList`.** When `draft.source` is
   falsy, stage the first `browser_fetch` source (else the first offered) *before* the radios
   are built. The existing `radio.checked` / `if (radio.checked) onSelectSource(s)` path then
   fires on its own — reusing the established flow rather than adding a second one — which
   reveals the entity picker, calls `fillDrawerEntitySelect`, and makes `testConnection`'s
   existing refill gate pass. Staging only; `slotState` and the row label are untouched until
   Confirm.
2. **Stop the silent clobber in `fillDrawerEntitySelect`.** Was `draft.statId = sel.value`
   unconditionally; assigning an id absent from the option list leaves a `<select>` at `""`,
   so a hand-picked id was overwritten with `""` on any repopulate that could not show it.
   Now `if (sel.value === pick) draft.statId = pick` — the staged choice outlives an option
   list that cannot display it. This is what satisfies the user's "don't lose a manual
   customization" requirement.

Comments updated: the file-header staged-then-confirm section, and the stale note in
`openDrawer` that claimed the radio was only re-checked for an already-committed source.

## Testing — option (b), Playwright

The user chose (b) over shipping untested (a) or adding a JS unit runner (c); (c) was argued
against on the grounds that the bug was in the wiring, not in `guessId`, so a unit test of
the heuristic would not have caught it.

Two tests in `tests/test_smoke.py`, driven through the real drawer in a real browser:

- `test_a_successful_connection_preselects_the_slots_entity` — the reported repro.
- `test_a_manually_chosen_entity_survives_a_repopulate` — both loss paths: repopulating while
  the chosen id IS in the list, and while it is NOT.

`window.WebSocket` is stubbed via `add_init_script` (`_HA_WS_STUB`) rather than contacting a
real Home Assistant: `HaClient` resolves the global at call time and speaks four messages, so
the stub exercises the real client, the real `testConnection`, and the real preselect path.
Stubbing at any higher level would stop testing the code that broke. The stub's ids mirror a
Dutch DSMR install including the `_cost` siblings that sort adjacent to the energy sensors —
that adjacency is why `guessId`'s first-match rule is worth asserting.

## Obstacles and Solutions

- Initial hypothesis (refill gate missed because the drawer was closed at test time) was
  **wrong** — the user's repro has the drawer open. Traced `draft.source`'s actual value on a
  fresh slot, which located the real cause at `renderSourceList` ~:912/:939.
- The new test first failed with the select *populated but empty-valued*. Cause: the
  empty-state screen renders `app/sample_data.py`, which ships `grid_import_t1` already bound
  to `sensor.electricity_meter_import_t1` — so the slot was not fresh, `draft.statId` was
  pre-seeded, and there was nothing for the guess to decide. The test premise was wrong, not
  the fix.
- Making the slot genuinely pristine by rewriting its `data-slot-*` attributes lost the race:
  `ha_fetch.js` is a `defer` script that seeds `slotState` during parse, and neither a
  `DOMContentLoaded` listener nor a `MutationObserver` reliably got in front of it. Solution:
  seed a current-generation `localStorage` entry instead — the documented override path.
- `_connect_ha` initially matched the config button by its "Configure" label, which breaks on
  the second call because the label becomes "✓ Connected". Matched by position instead.

## Files Modified

- `changelog/20260805-ha-entity-preselect.md` — this file (new).
- `app/static/ha_fetch.js` — default-source staging on drawer open; preserve a manually
  chosen entity id; three comment blocks refreshed.
- `tests/test_smoke.py` — two new tests, the `_HA_WS_STUB` WebSocket stand-in, the
  `_connect_ha` / `_make_slot_pristine` helpers, and `expect` added to the playwright import.
- `app/main.py` (round 2) — clear the sample's per-slot provenance in the empty state.
- `tests/test_workspace_data.py` (round 2) — the empty-workspace binding assertion.

## Round 2 — the empty state fabricates entity bindings (the user's ACTUAL cause)

The user tested the deployed fix against their live server and the select was still empty.
Checked rather than assumed: the server was serving the fixed JS (`defaultSourceFor` present,
guard present), so the fix was live and this was a second, distinct cause.

Inspecting the rendered page for a **brand-new** workspace showed the roster already bound:

    data-slot-source="home_assistant"
    data-slot-stat-id="sensor.electricity_meter_import_t1"

Those are `app/sample_data.py`'s fictional ids, and none of the five
(`sensor.electricity_meter_{import,export}_t{1,2}`, `sensor.solar_total_production`) exist on
the user's Home Assistant — verified against the id list pulled from their instance.

Root cause: `app/main.py:573` seeds `ctx = sample_view()` and only replaces `ctx["data"]` when
a real dataset loads (`main.py:610-613`). With no dataset, the roster renders `data.mapping`
straight from the sample, so every new workspace ships the sample's entity bindings. The
chain on the client is then correct-but-useless: `openDrawer` seeds `draft.statId` from the
bogus id, `guessId` is skipped (`draft.statId ||` short-circuits, right for a real committed
choice), and `sel.value` matches no option → empty select.

The comment at `main.py:599-601` already names this hazard — "letting a sample value survive
is how the empty state would come to show figures for data the user never supplied" — and
handles `has_dataset` / `data_summary` that way. `ctx["data"]`'s mapping was missed.

This also explains the ORIGINAL report: the mechanism never regressed. New workspaces have
been arriving pre-bound to sample entities, which suppresses the guess. Round 1's
`defaultSourceFor` fix remains correct for the genuinely-unconfigured case — which is what the
empty state should have been producing all along — but the user's setup never reached it.

### Decisions (both approved by the user)

1. **Server fix.** In the empty state the roster must render slots with no source and no
   stat_id — the sample's bindings are a demo artifact and must not reach a real workspace.
   Care needed: the sample view also feeds the static demo, so blanking unconditionally could
   empty that too; `data.mapping`'s other consumers get checked before picking the seam.
2. **Client fallback.** When a stored id is not offered by the connected instance, fall back
   to `guessId` rather than preselecting an id the select cannot show. This revises round 2's
   clobber-guard: preserving an unshowable id is right for a real-but-absent entity and wrong
   for a bogus one, and the user chose the guess.

### Round 2 implementation

**Server** (`app/main.py`, in `_data_page` beside the sibling replaced-or-dropped keys): when
`has_dataset` is false, rebuild `ctx["data"]["mapping"]` with `source`, `stat_id` and `entity`
cleared. Only the provenance is cleared, not the rows — the roster still renders every slot's
role, requirement marker and offered sources. `has_dataset` is the gate rather than `summary`
because a price-only dataset is real data and must keep whatever it mapped. Checked first that
`data.mapping` has exactly one consumer (`_data_roster.html`) and that the roster renders on
only one screen, so the seam is contained; the other `sample_view()` caller is the results
route, which renders no roster.

**Client** (`app/static/ha_fetch.js`): `fillDrawerEntitySelect` now prefers the chosen id only
when the connected instance offers it —

    var offered = draft.statId && statIds[kind].indexOf(draft.statId) !== -1;
    var pick = (offered ? draft.statId : guessId(slotName, statIds[kind])) || "";

An id the instance does not have can be neither shown nor fetched, so the guess beats an empty
picker. This SUPERSEDES round 1's clobber-guard (`if (sel.value === pick)`), which preserved
such an id; that was right for a real-but-absent entity and wrong for a stale or bogus one, and
the user chose the guess. The manual-override case is unchanged: an offered id still wins.

### Round 2 tests

- `tests/test_workspace_data.py::test_an_empty_workspace_claims_no_entity_bindings` — a fresh
  workspace's roster carries no `data-slot-source` / `data-slot-stat-id`, and none of the three
  sample ids appear. Verified to fail with the server fix disabled.
- `tests/test_smoke.py::test_a_manually_chosen_entity_survives_a_repopulate` — rewritten for the
  new rule: an offered id still beats the guess; an unoffered one now falls back to it.

## Current Status

Complete. Full suite green: **1397 passed, 25 skipped**.

Verified against the user's live server that the fixed JS was being served (the round-1 fix was
live and correct — it simply never engaged, because the sample bindings made the slots look
committed). The user's workspace has since been fetched successfully and now carries their real
ids (`sensor.energy_consumed_tariff_1` and peers), so it no longer exercises the empty state.

Not verified: *why* Home Assistant appeared pre-selected to the user before the round-1 fix. No
radio was programmatically checked, so the hypothesis remains a rendering artifact of the first
radio in the group or the HA card's Configure button. The fix makes the appearance correct
either way, so this was not chased further.

Not verified: *why* Home Assistant appeared pre-selected to the user before the fix. No radio
was programmatically checked, so the hypothesis remains a rendering artifact of the first
radio in the group or the HA card's Configure button. The fix makes the appearance correct
either way, so this was not chased further.

### Known separate gap (not in scope — user said "ok for now")

`solar_production` gets no guess against the user's instance — its hints (`solar`,
`pv_production`, `inverter`) match none of the 81 `sum` ids. Their solar sensor turns out to be
`sensor.bg_mk_zp_3p_produced_energy` (seen on their fetched workspace), which no substring in
the table would match. Fixing it means broadening the hints; deferred by the user.
