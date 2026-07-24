# Data summary interstitial panel

## Task Specification

**User's original prompt (verbatim):**

> update for the UX/wireframe specs & app code. After the user validates their data series
> (click fetch button), we'd like an interstitial "summary of your data" panel before they go
> on to enter their battery details.
>
> the summary should display the data results that can be computed without the battery
> information (including, but not limited to, the total energy consumed/produced from the grid,
> self-sufficiency)

Add a "summary of your data" panel that appears after the data fetch (panel ①) and before the
battery-parameter panel (panel ②). It presents figures derivable from the household's data alone
— no battery, no policy, no pricing. Examples named by the user: total grid energy
consumed/produced, self-sufficiency. Scope spans both the specification package (`specs/`) and
the running app (`app/`).

## Current State (pre-change, established by exploration)

- The app is at the **data-import increment**. After a browser Fetch (ha_fetch.js), the page
  reloads and panel ① renders the real persisted dataset via `app/data_view.py` +
  `app/domain/normalize.py` (grid selection + reconciliation metadata). Panels ② and ③ still
  render the *static* sample view-model (`app/sample_data.py`); there is **no simulation domain
  layer yet** (no `simulate_core`, no metrics module).
- The panels are three stacked stepper sections in `templates/index.html`
  (`_setup_band`, `_panel_data`, `_panel_params`, `_panel_results`). Panel ① ends with a
  "Next: parameters →" button.
- Load reconstruction (§6.3: `load = import − export [+ pv]`) and the energy metrics
  (§6.11: `self_sufficiency = 1 − import/load`, `self_consumption`, totals) are **specified but
  not yet implemented**. The frames carry per-interval kWh values already (energy series), so the
  battery-free aggregates ARE computable from the persisted dataset now.
- Spec §2 (`02-ux-wireframes.md`) defines the setup band + three panels; §2.4 documents panel ③.
  §12 (`12-metrics-and-benchmarks.md`) defines the metrics and marks which are battery-free.

## High-Level Decisions

Settled with the user via clarifying questions (2026-07-24):

1. **Placement — unnumbered band below panel ①, above panel ②.** Not a numbered stepper step:
   it is a "here's what we found" interstitial, modelled on the setup band (always-expanded, no
   collapse-to-summary, no `[?]`/pending semantics, no CTA of its own). This avoids renumbering
   Parameters/Results across the specs and templates. It renders **only once a real dataset is
   loaded** — the empty state has nothing to summarise, so before the first fetch the band is
   absent (like the results it foreshadows).
2. **Content — all four figure groups**, all battery-free (§6.11 energy metrics + §6.3 load
   reconstruction):
   - Grid import/export totals (kWh over the window).
   - Self-sufficiency (`1 − import/load`).
   - Solar & consumption: total PV production, reconstructed household load, self-consumption
     ratio (`1 − export/pv`). PV-dependent rows shown only when `has_pv` / when PV data exists.
   - Price/window context: coverage span & days, average / min / max spot price over the window.
   All are figures a real controller/simulator does not need battery inputs to produce; they are
   exactly the §6.11 "Energy" row plus the raw meter/price aggregates behind it.
3. **Implementation — spec + UI shell with a sample view-model.** Matches the scaffold's current
   "shape first" posture (panels ②/③ still render `sample_data.py`). The real battery-free
   computation (a §6.3/§6.11 domain slice over the persisted frames) is deferred to a later
   increment; this task lands the spec text and the panel/template driven by sample numbers, so
   the intended shape is on record and reviewable without pulling the domain layer forward.

## Requirements Changes

**2026-07-24 — pre-existing battery accounted for in the grouping (user follow-up).**

> note that the user may already have a pre-existing battery, such that home load and
> self-consumption are derived from that data too. the grouping should take it into account

The user may already own a battery whose sensors are mapped into the `battery_charge` /
`battery_discharge` slots (§4.1, §5). §6.3 load reconstruction then *strips* that battery
(`load = imp − exp + pv + batt_dis − batt_chg`), so the reconstructed household load and the
self-consumption ratio are **derived from the existing battery's data too** — they are the true
behind-the-meter demand net of that battery, not a no-battery quantity.

Consequences for this task:

- **Framing.** Drop "battery-free" as the organising label. The honest contract is: figures
  computable **from the household's own recorded data — which may include a pre-existing
  battery — before the *simulated* battery is configured.** The distinction that matters is
  *existing/measured* battery (an input) vs. *simulated* battery (what panels ②/③ add), not
  "no battery at all".
- **Grouping.** When `battery_charge` / `battery_discharge` are present, surface the existing
  battery as its own group (observed charge/discharge throughput over the window), and label the
  household-load and self-consumption rows as **net of your existing battery** so the reader
  knows the reconstruction used it. When those slots are absent, that group is omitted and the
  labels carry no such qualifier (the omit-don't-zero rule from §2.4 again).
- Cross-refs: §6.3 (the `batt_chg`/`batt_dis` strip), §4.1 (the optional battery slots),
  §6.15 / open-question §8.6 (existing battery installed mid-window → reconstruction consistency,
  a known limitation to acknowledge but not solve here).

## Confirmations (2026-07-24)

- **(a)** The band is hidden in the empty/pre-fetch state and shown only once a dataset is loaded.
- **(b)** The sample view-model demos the **existing-battery variant**: `battery_charge` /
  `battery_discharge` populated, the "Your existing battery" throughput group rendered, and the
  Household/Solar rows labelled "net of your existing battery". (This diverges from the current
  `sample_data.py`, which leaves those two slots unmapped — the summary sample carries its own
  battery figures rather than re-deriving the mapping sample.)

## Files Modified

Specs:
- `specs/02-ux-wireframes.md` — new **§2.3a "The data summary band — Your data at a glance"**
  (wireframe + prose: band-not-panel, the shown-figures table, the omit-don't-zero rule, and the
  existing-vs-simulated battery distinction with "net of your battery"). §2.1 overall-layout ASCII
  updated to show the band's position between ① and ②.
- `specs/04-state-machine.md` — §3.4 note: the summary band, like the setup band, has no focus
  state; absent until `DATA_READY`, re-renders on `RELOAD_DATA`.
- `specs/12-metrics-and-benchmarks.md` — §6.11 note: the self-sufficiency / self-consumption /
  totals subset of the Energy row needs no simulated battery and is surfaced in the band; `efc`,
  `saved_kwh`, `saved_pct` stay in panel ③. Cross-refs the existing-battery net-of labelling.

App:
- `app/templates/_panel_summary.html` — **new**. The band markup (Grid / Household / Solar /
  existing-battery / price groups), each optional group guarded for omit-don't-zero.
- `app/templates/index.html` — include `_panel_summary.html` between ① and ②, gated on
  `data_summary` being present; header docstring updated.
- `app/sample_data.py` — new `_data_summary()` sample view-model (existing-battery variant);
  exposed in `sample_view()`; module docstring notes main.py drops it in the empty state.
- `app/main.py` — `index()` drops `data_summary` from the context when no dataset is loaded, so
  the band is absent pre-fetch and present once data exists (numbers still sample this increment).
- i18n: `app/locales/messages.pot`, `nl` + `en` `.po`/`.mo` — new band strings extracted and
  translated (Dutch), en filled as identity; catalogs kept fuzzy-free.

Tests:
- `tests/test_data_summary.py` — **new**. Unit tests for the sample view-model shape (always-on
  groups, existing-battery variant, optional-group keys present for the template guards).
- `tests/test_smoke.py` — new assertion that the band is absent in the empty/pre-fetch state.

## Rationales and Alternatives

- **Unnumbered band, not a numbered panel** (user's choice): avoids renumbering
  Parameters/Results across specs + templates, and reads correctly as read-only context rather
  than a stepper step. Modelled on the setup band, differing only in that it is absent until data
  loads.
- **Spec + UI shell with sample numbers** (user's choice): matches the scaffold's posture (panels
  ②/③ still render `sample_data.py`); the real §6.3/§6.11 battery-free computation over the
  persisted frames is a later increment. A code comment in `main.py` flags this so the sample
  numbers over a real dataset are not mistaken for a bug.
- **Existing battery surfaced explicitly** (user's follow-up): §6.3 already strips a mapped
  existing battery when reconstructing load, so household/self-consumption figures are net of it.
  The band gives the existing battery its own throughput group and labels the reconstructed rows,
  keeping "the battery you have" distinct from "the battery we simulate" (panels ②/③).

## Obstacles and Solutions

- **i18n extraction dropped every `_N()` string.** First `pybabel extract` omitted `-k _N` (the
  repo's chrome marker), so `update` obsoleted all `sample_data.py` msgids and fuzzy-matched new
  short msgids onto existing translations (e.g. `Imported` stole `BESPAARDE NETAFNAME`), breaking
  `test_dutch_renders`. Fix: reverted the catalogs to HEAD, re-extracted with the documented
  `pybabel extract -F babel.cfg -k _N … --no-location`, ran `update … --no-fuzzy-matching` to stop
  the donor problem, then filled only the new empty msgstrs (Dutch for nl, identity for en). All
  original translations preserved; catalogs fuzzy-free.

## Current Status

Complete for this increment. Specs updated; band implemented as a spec + UI shell driven by the
sample view-model; hidden pre-fetch, shown once data loads; bilingual. Full test suite passes
(83 passed, HA-live test skipped — needs a real instance).

**Deferred (next increment):** the real battery-free computation — a §6.3 load reconstruction +
§6.11 metrics slice over the persisted frames — feeding real numbers into `data_summary` via
`app/data_view.py`, replacing the sample. `tests/test_data_summary.py` is written to become the
contract that computed view-model must also satisfy.
