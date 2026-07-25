# 20260725 — Collated follow-up work from the 23–25 July changelogs

## Task specification

User request (verbatim):

> the changelog files from the last few days have each captured some amount of follow-up work.
> please collate it.

Scope: read the changelog files dated 2026-07-23 through 2026-07-25 and gather every item they
recorded as deferred, filed-as-follow-up, noted-but-not-fixed, or left as an open question, into
one list. This is a collation pass only — no code, spec or catalog changes, and no re-triage of
whether each item is still valid. Where a changelog states the reason a thing was deferred, that
reason is carried over rather than re-argued.

## Method and caveats

- Sources: the 30 changelog files dated `20260723-*`, `20260724-*`, `20260725-*`, plus the two
  memory notes for the slot-first data work (`data-source-followups`, `data-source-architecture`),
  which already collated three items from 2026-07-24.
- Items are grouped by the area they touch, not by the changelog they came from, because several
  recur across files (the runtime-f-string i18n gap appears in four).
- Each entry cites its origin changelog. Where two files describe the same thing at different
  depths, both are cited.
- **Not verified against the current tree.** Some of these may have been fixed in passing by later
  phases; the collation reports what the changelogs say, and any item acted on should be re-checked
  against the code first.
- Severity labels below are the changelogs' own framing ("latent bug", "cosmetic", "open question"),
  not a new assessment.

## A. i18n and the message catalogs  - DONE

**A1. Runtime f-strings have no stable msgid, so they render in English under NL.** The largest
single item, recorded four times with growing scope. Sites named: `app/results_view.py` — the
benchmark gloss (`:551-627`), the annualisation notice (`:1025-1030`), the range label's
"simulated hourly · N intervals" (`:698`), the KPI deltas "0.38 / day" and "1,311 kWh throughput"
(`:811-813`); the panel-③ caveats; and — pre-existing, untouched by the panel-③ work — the whole
panel-① data-quality box in `app/data_view.py`. The fix is to restructure these as `_()`/`_N`
templates with `%(name)s` placeholders, which touches every call site and both catalogs; it was
deliberately declined three times as its own task.
*Origin:* `20260724-panel3-prototype-zero-battery.md`, `20260724-panel3-battery-simulation.md`
(Phase 2 cross-phase note and Phase 7), `20260725-panel2-parameters-phase6.md`.

**A2. `newstyle=True` makes a literal `%` in any dynamic translated string a live trap.**
`app/i18n.py:90` %-formats the result of `_()`: a `%` is silently eaten before a letter and raises
`ValueError` before a non-ASCII character — a 500 on a page the user is looking at. Not currently
triggered (KPI values bypass `_()`, and the Phase 4 caveats and the NL DC-bonus string were worded
around it), but the next dynamic string carrying a percentage hits it. Root fix: escape `%` → `%%`
before translation, or `newstyle=False`. Touches i18n and every catalog. Same root cause as A1 —
both come from passing runtime-built strings through `_()` at all.
*Origin:* `20260724-panel3-battery-simulation.md` (found in Phase 4),
`20260725-phase6-remaining-translations.md`.

**A3. Shared-Jinja-env locale race (pre-existing, app-wide).** `index()`, `POST /results` and now
`POST /params` install the request's gettext catalog onto the *module-level shared* `templates.env`
before rendering. Install-then-render is not atomic and sync routes run in a threadpool, so under
concurrent mixed-locale load a render can pick up another request's catalog. Predates the panel-③
work; each subsequent phase mirrored it rather than worsening it. Fix app-wide — a per-render env
overlay, or pass translations explicitly instead of mutating the shared env.
*Origin:* `20260724-panel3-prototype-zero-battery.md`, `20260725-panel2-parameters-phase6.md`.

**A4. Hardcoded English fetch-status strings in `ha_fetch.js`** (`Connecting…`, `Fetching…`, error
messages). Predates the drawer work; the drawer's own strings do go through `t()`/`#drawer-i18n`,
so the mechanism exists. A full JS i18n pass is a separate cleanup.
*Origin:* `20260724-slot-first-data-panel-ui.md`, memory `data-source-followups`.

**A5. `pybabel update` needs two flags, undocumented.** `--no-location` (the committed catalogs
carry no `#:` comments) and `--no-fuzzy-matching` (fuzzy matching mistranslated "Extra grid import"
as "Netafname T2"). Worth writing into `babel.cfg`'s workflow notes.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 4 follow-ups).

**A6. Locale-aware number and date formatting is not done.** Dutch decimal comma, in particular.
Explicitly a follow-up from the bilingual pass.
*Origin:* `20260723-i18n-bilingual.md`.

**A7. Sample-data strings left in English on purpose** — the two panel summary lines, granularity
cell values ("hourly (full)"), KPI deltas, coverage/period detail strings. The stated reason was
that these would arrive formatted from the domain layer; now that they partly do (A1), it is worth
re-checking whether the exemption still holds.
*Origin:* `20260723-i18n-bilingual.md`.

## B. Panel ② parameters, config and persistence

**B1. The DC-bonus warning is unreachable — no control for `battery.roundtrip_dc_bonus`.** The
check fires in `validate()` (rte 0.99 + bonus 0.05 → `eta_c_dc` 1.0198 → warning), the msgid is
extracted and the NL string is translated, but `_panel_params.html` renders no input keyed
`battery.roundtrip_dc_bonus`, so the warning has no slot to appear in. Flagged as an open question
in two files, and it is the one item both call out explicitly as unresolved.
*Origin:* `20260725-phase6-remaining-translations.md`, `20260724-panel3-battery-simulation.md`
(Phase 6 follow-ups).

**B2. The setup band's radios do not POST anywhere.** — **DONE** (cost-simulation increment,
Phase 5). `simulate_cost`'s radios now carry `form="params-form"` (explicit HTML form association)
so they submit with panel ②'s form: one POST, one validation, one panel swap. `parse_form` reads
them behind a `setup` section marker, so a partial POST cannot silently answer "no". `has_pv` is
parsed but deliberately NOT re-added to the band — it moved to panel ①'s scope questions in an
earlier commit, and two controls for one answer is the thing §2.1 forbids; the parse path is ready
if panel ① is ever pointed at it.
*Origin:* `20260725-panel2-parameters-phase6.md`.

**B3. `simulate_cost` pending ⇒ the Pricing box, the `economic_guard` control and run E are all
unreachable by design.** — **DONE** (cost-simulation increment, Phases 2–5). §6.5's contract model
exists, the Pricing box renders behind the answer, `economic_guard` is a real control, and run E is
built and on screen (H12). The summary line now ends in the contract name.
*Origin:* `20260725-panel2-parameters-phase6.md`.

**B4. The `retained` slot is deliberately single-purpose, and worth a second reading.** It holds
`economic_guard` only — the spec forces that field off rather than merely hiding it, whereas the
twelve cost-only parameters are merely inert and retain themselves through `parse_form`'s
inherit-if-absent rule. The mechanism works and is tested both directions, but it puts one field's
authoritative value in the persistence document rather than on the config object. The cleaner
alternative (a raw-value companion field on `SimulationConfig` that `_force_invariants` does not
touch) was declined because it modifies a domain module Phase 6 was told not to touch. Revisit if a
second forced-off field appears — "a list of two is still not a pattern".
*Origin:* `20260725-phase6-review-defects.md` (FLAG 1), `20260725-panel2-parameters-phase6.md`.

**B5. The collapsed summary line reads `charge P3` even when `has_pv = false`,** where P3
degenerates to P2. That is the stored policy and §6.6 is explicit it should be left alone (rewriting
it would discard the user's answer if they re-enable PV), but it reads oddly next to a panel that
only offers P2. Wants a presentation decision.
*Origin:* `20260725-panel2-parameters-phase6.md`.

**B6. CSRF is absent on `POST /params`, as a recorded decision.** Local-only app, `workspace_id` is
the hardcoded `"local"` and never user-influenced, no exfiltration path (the response is
same-origin-read-blocked), worst outcome is a rewritten local parameter set; a token would add a
session/secret surface the app does not otherwise have. Listed here because it is a standing
decision to revisit if the app ever stops being local-only, not because it is pending work.
*Origin:* `20260725-phase6-review-defects.md`, `20260724-panel3-battery-simulation.md`.

**B7. `_finite()` rejects `str`, so `GridConfig(phases="3")` blocks rather than coercing.**
Defensible (coercion belongs to the form layer) but the opposite choice is equally defensible; the
note said to revisit once Phase 6's form binding existed and showed which is less friction. Phase 6
now exists, so this is answerable.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 2 follow-ups), `20260724-sim-config-phase2.md`.

**B8. The display-precision rule and 230 V are inferred, not specified.** "2 dp below 10 kW, 1 dp
at/above" and the 230 V mains figure are each pinned by the same two published figures and appear
nowhere in `specs/`.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 2 follow-ups).

## C. Simulation, benchmark and metrics

**C1. A real per-month savings series remains unbuilt.** §2.4's wireframe asks for a
monthly-savings chart. What ships is `results_view._monthly_import()` — measured grid import per
calendar month — now honestly relabelled "Monthly grid import". Building the real series means
running the A/B/C simulation and bucketing `saved_kwh` per month.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 7).

**C2. Two chart tabs are pending affordances, not implementations.** "SoC + price" and "Energy
flows" now carry the §2.1 pending affordance with keys `chart_soc_price` and `chart_energy_flows`
in `app/features.py`. Named as newly pending in `specs/implementation-progress.md`.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 7),
`20260725-spec-corrections-from-implementation.md`.

**C3. Run E / the cost DP, and any euro figure, are not built.** — **DONE** (cost-simulation
increment, Phases 2–4). §6.5's price curves, §6.10's cost accounting and waterfall, and run E with
`benchmarks.cost` are all built; §6.12's DP is now parameterised by its objective rather than
duplicated, so runs D and E share one state space, action set and terminal constraint. Two spec
gaps surfaced doing it and are carried as H10 (no sound euro drift correction) and H11 (the feed-in
floor is not separable inside the DP). The remaining unbuilt items this entry lists — epochs, the
price bracket, the resolution-bias and misalignment diagnostics, CSV — stay out of scope (H3).
*Origin:* `20260725-perfect-foresight-benchmark-phase5.md`,
`20260725-spec-corrections-from-implementation.md`.

**C4. The unconstrained-export DP being redundant is an argument, not a proof.** With export off,
both DPs are bit-identical on this dataset (import 3261.476807 either way) and the feasibility masks
genuinely differ (180 infeasible cells vs 0), so the second DP optimises over a superset and cannot
improve an import-minimising objective. Experiment **X10** exists to settle it.
*Origin:* `20260725-perfect-foresight-benchmark-phase5.md`,
`20260724-panel3-battery-simulation.md` (Phase 5 follow-ups).

**C5. Whether `dp_soc_levels = 101` is wastefully high is now the open question.** The
implementation measurements showed the SoC grid converged well before 101 under interpolation, with
the action-grid residual at 0.025 kWh at 41 levels. **X13** was rewritten to sweep downward as well
as up; the DP's measured ~2.3 s cost means a coarsening finding has a directly felt payoff.
*Origin:* `20260725-spec-corrections-from-implementation.md`.

**C6. The band's derived ratios stay measured while the tiles are simulated** (household
self-sufficiency 21% vs 23%, solar self-consumption 34% vs 36%). Intended per §2.3a, and the caveat
says so; moving the band to simulated figures would be a further product decision, not taken.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 4 follow-ups).

**C7. Two thresholds are judgement calls, not spec-derived** — the resolution-loss caveat firing
when the gap rounds to ≥ 1 kWh, and the `1e-6` tolerance on the capture ratio's range test (a policy
exactly at the bound corrects to `1.0000000000000024` and would otherwise be reported as a fault;
real breaches are orders of magnitude larger, −4.93 and 28.59).
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 4 and Phase 5 follow-ups).

**C8. `_period_selected_for` maps a *clamped* window's span to the nearest preset,** so a "1 year"
request over less than a year of coverage highlights a shorter button. Inherent to passing a
resolved window rather than the origin preset.
*Origin:* `20260724-panel3-prototype-zero-battery.md`.

**C9. `_monthly_import` repeats month labels across a multi-year window** (two "Jan" bars). Values
are correct; wants year disambiguation if multi-year ranges become common.
*Origin:* `20260724-panel3-prototype-zero-battery.md`.

**C10. The sample tile keeps a secondary row the view-model does not emit.** "Intervals battery was
full / empty" is in §2.4's wireframe but not in `results_from`; both sides document the divergence
rather than hiding it. Recorded as a deliberate choice to revisit, not a defect.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 7).

## D. Data ingest, frames and sources

**D1. `.replace(tzinfo=None)` is unsafe for non-UTC-aware windows.** Three sites:
`reconcile._resample_sum`, `summary_view._price_stats_in_window`, and now `simframe`. Latent — every
current caller passes UTC. The safe general form is
`.astimezone(timezone.utc).replace(tzinfo=None)`. Fix app-wide in `reconcile.py` rather than
diverging one module.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 1 follow-ups).

**D2. The frame's arrays alias `reconcile_grid`'s.** `load`, `pv`, `import_obs`, `export_obs` are
the same objects, not copies. Harmless today because §6.9 rebinds (`st.load = frame.load +
standby_kwh`) rather than mutating, but an in-place variant would silently corrupt the data-summary
band through the shared object. Carried into Phase 3 as an explicit constraint; the aliasing itself
is unchanged.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 1 follow-ups).

**D3. Mixed-resolution spot-price frames get one modal `resolution_s`.** A window straddling the
hourly→15-min transition (real NL data transitions at 2025-09-30T22:00Z) is not per-interval
authoritative. No downstream consumer of that resolution exists yet; the real fix belongs in the
§6.2 grid selector, treating it like the HA hourly/5-min pair. Documented in
`EnergyChartsSource.load`.
*Origin:* `20260724-slot-first-data-sources.md`, memory `data-source-followups`.

**D4. The energy_charts → HA switch in the drawer is inert without a reload.** When a slot's
persisted source is `energy_charts`, its row renders a static `<span>` not an `.ha-map-select`, and
`selects` is captured once at load, so the drawer finds no select to activate. Narrow (only
`price_spot`, only after an energy_charts load) and recoverable by a page reload. A proper fix
injects a select dynamically.
*Origin:* `20260724-slot-first-data-panel-ui.md`, memory `data-source-followups`.

**D5. Drawer focus is not trapped.** Escape / backdrop / ✕ all close it and focus returns to the
opening button, but focus can leave the drawer while open. Judged acceptable for a non-modal picker;
noted for a later a11y pass.
*Origin:* `20260724-slot-first-data-panel-ui.md`.

**D6. Coverage-line pluralisation** — "1 intervals". Cosmetic.
*Origin:* `20260724-panel3-prototype-zero-battery.md`.

## E. Tests

**E1. Fixture 21's `series`-block assertions are not tested.** The spec also asks that the price
series' `reconciliation` read `"averaged"` and the energy series' `"exact"`.
`normalize.reconciliation` implements this, but fixture 21's test does not tie them together. Called
a real gap in two files.
*Origin:* `20260724-simulation-frame-phase1.md`, `20260724-panel3-battery-simulation.md`.

**E2. The DST test (fixture 7) is a regression guard, not a DST repair test.** Its input index is
already a clean UTC `arange`, so it verifies the pipeline does not corrupt a uniform axis rather
than that it repairs a DST-shaped input. That is the right scope for this layer — ingest owns
local→UTC conversion — but the test's framing should say so.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 1 follow-ups).

**E3. `| e` on `data-benchmark-body` is load-bearing and fragile.** Without it the raw `"`
terminates the attribute early and the fetcher reads `{`. Verified escaped in the live page, but
correctness rests on a filter that is easy to drop — worth a test that would catch its removal.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 5 follow-ups).

**E4. `test_smoke.py::test_new_pending_controls_marked` failed on the base commit** — it looked for
setup-band copy ("Also simulate cost savings") that a prior commit reworded. Fixed later the same
day in `20260724-fix-pending-controls-test.md`; listed for completeness, believed closed.
*Origin:* `20260723-ha-data-import.md`, `20260724-ha-connection-in-drawer.md`,
`20260724-ha-source-reset-on-price-pick.md`.

**E5. No live browser exercise of pick-entity-then-fetch.** The entity-picker-in-drawer change had
no browser automation available that session; a manual pick-then-fetch check was called for. Later
sessions did drive Playwright over adjacent flows, so this may be covered incidentally.
*Origin:* `20260724-entity-picker-in-drawer.md`.

## F. Specs and documentation

**F1. 23 spec anchors were already broken at HEAD** before the correction pass (25 after, the two
added following the same established pattern). They point into `02-ux-wireframes.md` headings
containing circled numerals (`Panel ①`) and similar symbols, where the anchor GitHub generates
differs from what the links assume. Out of scope for a correctness pass; wants a separate mechanical
sweep.
*Origin:* `20260725-spec-corrections-from-implementation.md`.

**F2. §6.12's terminal-constraint asymmetry is a genuine spec gap, now documented rather than
resolved.** The DP must finish at or above its starting SoC; nothing imposes that on run C, and
§6.11 deliberately reports SoC drift rather than netting it out. The spec is silent on the policy
run's endpoint. The implementation resolved the visible symptom by drift-correcting the ratio for
display; whether the *spec* should constrain run C's endpoint is still open.
*Origin:* `20260725-spec-corrections-from-implementation.md`,
`20260725-perfect-foresight-benchmark-phase5.md`.

**F3. Open question §8.6** — an existing battery added mid-window must not truncate the grid
totals — is the stated reason the summary band uses a mixed coverage policy (grid series reconciled
onto the effective window; price aggregates over their own coverage). Still open.
*Origin:* `20260724-data-summary-interstitial.md`.

## G. Process notes worth keeping

**G1. A per-module review cannot catch a defect whose two halves are each internally consistent.**
Six phases were adversarially reviewed in isolation, four returned DEFECT FOUND, and all six missed
the chart labelled "Monthly savings" plotting measured grid import — wrong by more than 11× against
the KPI tile beside it (3,923 kWh of bars beside a 341 kWh tile). It survived because the
function's docstring said "measured grid import" and the test asserted import values: code and test
agreed with each other. Only reading the chart next to the tile exposed it. The cross-seam audit is
what found it.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 7).

**G2. A changelog claiming catalogs were regenerated is not evidence they were.**
`20260725-panel2-parameters-phase6.md` recorded the catalogs as extracted, translated and
recompiled. They were not — `pybabel extract` picked up 31 new msgids on the first run of the next
task, i.e. a Dutch user would have seen the whole parameter panel in English. Verify catalog state
by extracting, not by reading the record.
*Origin:* `20260725-phase6-review-defects.md`.

**G3. A stale git-status snapshot cost a `.po` round-trip.** A `git checkout` of the two catalogs
restored the *committed* versions, which predated Phase 6, because the Phase 6 catalogs were
uncommitted working-tree state and the status snapshot in context was stale. Recovered by rebuilding
both `.po` from `messages.pot` plus the compiled `.mo`. Check freshness before checking out.
*Origin:* `20260725-phase6-remaining-translations.md`.

**G4. Two corrections to figures that circulated in briefs.** (i) "20 kWh/8 kW → 1,582 kWh saved"
was wrong; the real figures are 10 kWh/5 kW → 341 kWh and 20 kWh/8 kW → 317 kWh — the saving
*decreases* with a bigger battery, because grid-charge round-trip loss plus standby outgrow the
gain. This is why `test_a_parameter_change_moves_panel_3s_figures` asserts movement, not direction.
(ii) The hourly→15-min price transition is 2025-09-30T22:00Z, not the 2025-10-23 a review brief
guessed. Neither number was in the repo, so nothing needed correcting; recorded so they do not
resurface.
*Origin:* `20260725-phase6-review-defects.md`, `20260724-slot-first-data-sources.md`.

## H. Deferred by the cost-simulation increment (2026-07-25)

Items this increment deliberately left out of scope. Unlike A–G above, these were **not** inherited
from earlier changelogs — they are decisions taken while building the cost path, recorded here at
the moment of deferral rather than reconstructed afterwards.

**H1. `tariff_zone` and the local-time axis are not built, and the DST trap is live for whoever
builds FIXED/VARIABLE.** §6.4's dal mask is defined over `index_local` — "dal from 23:00 to 07:00
plus weekends" is a wall-clock rule. The entire pipeline is UTC-naive by design (`SimulationFrame.index`
is UTC; `reconcile.py:81` and `simframe.py:93` drop the tz deliberately, and `simframe.py` lists
`tariff_zone` as explicitly out of scope). Nothing in the codebase has ever needed
`Europe/Amsterdam`.

Only FIXED and VARIABLE read `tariff_zone`; DYNAMIC prices off spot and never touches it. Since this
increment builds DYNAMIC only, the whole question was deferred on the user's instruction.

**The trap:** applying §6.4's hour mask directly to the UTC index shifts the dal window one hour in
winter and two in summer, silently mispricing every fixed/variable run. There is no test that would
catch it and no figure that would look wrong. Whoever builds FIXED must convert UTC →
`Europe/Amsterdam` per interval (via `zoneinfo`) before applying the mask. §6.4 also specifies check
8b (`tariff_zone_mismatch_pct`) to validate the configured window against the observed T1/T2
registers — that needs register data this increment does not wire up.
*Origin:* cost-simulation increment, Phase 2 scoping.

**H2. Public holidays are not modelled in the dal mask.** On Dutch dubbeltarief meters the low
tariff also applies on nationally recognised public holidays (≈ 8–10 days/year); §6.4's mask prices
them as `NORMAAL` and the spec records this as a known watch item rather than a defect. Inherited by
H1's implementer, not created by it.
*Origin:* `specs/09-ingest-algorithms.md` §6.4, carried forward.

**H3. Deferred cost-adjacent features, each unbuilt and each spec'd.** §6.16 price bracket
(`price_bracket` stays null), §6.13's euro-basis resolution bias (`resolution_bias_pct_eur` stays
null), tiered terugleverkosten (`TlkMode.TIERED` is in the vocabulary but only `FLAT` is built),
§6.15 configuration epochs, and §4.6's per-interval CSV export including its cost columns. Scoped
out at the user's direction; the enum values and null result fields exist so the shapes are right
when they land.
*Origin:* cost-simulation increment, Phase 0 scoping.

**H4. FIXED and VARIABLE contracts ship as pending controls.** Only DYNAMIC is built. The two radios
render disabled with `[?]` affordances and new feature keys; `Contract` carries all three values so
the vocabulary does not change when they ship. VARIABLE additionally needs the repeating
rate-schedule editor from §2.3's wireframe, which is a sizeable form in its own right.
*Origin:* cost-simulation increment, Phase 0 scoping.

**H5. The older enum-typed config fields are unvalidated.** `charge_policy`, `discharge_policy`,
`coupling`, `pv_coupling` and `battery_phases` accept `None`, a bare string, or any object without
`validate()` saying anything — so a mistyped value reaches the dispatch chain in §6.6–§6.8 and takes
a silent branch. Phase 1 added a `not_a_choice` check for the three *pricing* enums (`contract`,
`feedin_floor_mode`, `tlk_mode`) because §6.5 dispatches on them and a wrong branch there is a
confident wrong euro figure. The same argument applies to the older five; they were left alone
because widening the check is a behaviour change to already-shipped validation, not because they
are safe. Extending it is mechanical — the pricing check at `app/domain/simconfig.py` is the
template.
*Origin:* cost-simulation increment, Phase 1 review (finding 11).

**H6. A stored `contract = VARIABLE` is a config §6.5 cannot price, and nothing says so.** `FIXED`
reads `rate_normaal`/`rate_dal`; `VARIABLE` reads a dated `rate_schedule` that does not exist on
`PricingConfig` at all. Both are in the enum vocabulary but only DYNAMIC is built (H4), and
`validate()` raises no issue for either. Once panel ② renders the two as pending controls the UI
cannot produce the state, but a hand-edited or migrated document can. Whoever builds VARIABLE
should decide whether validation should reject it in the interim.
*Origin:* cost-simulation increment, Phase 1 review (finding 12).

**H7. `to_dict` writes raw numerics, so a user-typed `nan` reaches `json.dumps` as bare `NaN`.**
Valid for Python's own `json` on read-back, not valid JSON for any other reader. Pre-existing and
identical across `battery`/`grid`/`policy` — pricing merely joins them — so this is a whole-store
issue rather than a cost-path one. A non-JSON-serialisable object in a field would likewise make
`save()` raise, same scope.
*Origin:* cost-simulation increment, Phase 1b (persistence).

**H8. `dal_start_hour` / `dal_end_hour` are `float` while the wireframe shows integer hours.**
§2.3's control is `dal from [ 23:00 ] to [ 07:00 ]` and appendix A gives bare ints, but the fields
are typed `float` and validated only to `[0, 24)`, so `23.5` is storable. Defensible as
permissive-here-validate-later, and harmless until §6.4's zone assignment reads them — which is
H1's work. Flagged so that implementer decides deliberately rather than discovering a half-hour
boundary.
*Origin:* cost-simulation increment, Phase 1 review (finding 14).

**H9. The feed-in floor buckets on UTC calendar months, not Amsterdam ones.** `feedin_floor_topup`
uses `astype("datetime64[M]")`, so an assessment period starts 1–2 h after the Dutch calendar month
does. Measured, not theoretical: an interval at 2026-03-31T23:00Z is 1 April CEST, and in a
constructed case moving it across the boundary changes the month's top-up from €0.30 to €0.60. It
only bites when the floor actually binds *and* the binding period's sign turns on those one or two
hours, which is rare — but the statute's period is a Dutch calendar month, so this is a real if
small correctness gap rather than a modelling choice. Belongs with H1: whoever adds the UTC →
`Europe/Amsterdam` conversion should re-bucket the floor in the same pass.
*Origin:* cost-simulation increment, Phase 2.

**H10. §6.12 states its drift correction only in kWh, and there is no sound euro analogue.** The
spec corrects both sides by `saved_kwh + soc_delta_kwh × eta_d` before asserting fixture 6, because
the DP's terminal constraint binds it and nothing binds the policy run. In kWh that correction is
exact: a residual kWh is worth exactly one avoided kWh whenever it is used. **In euros the
residual's worth depends on *when* it is used, and the two sides use it at different times by
construction** — the DP's terminal constraint forces it to hold charge through (or repurchase at)
the expensive hours, while a liquidating policy dumps it into the cheap ones and never buys back.
No single scalar price can value both correctly.

Measured, not assumed: valuing at §6.11's median import price leaves fixture-6 violations up to
€0.91; valuing at the window maximum nearly restores the ordering, which is itself evidence that
the *basis* is wrong rather than the DP. So `cost_benchmark` reports
`median_import_price_eur_kwh` as an input and applies no correction, and the euro fixture 6 is
asserted over non-liquidating configurations — the form §6.14 itself names. A defensible euro
correction would value each side's residual at that side's own marginal continuation value, which
the DP has (`V`'s slope at the terminal SoC) and the policy run does not. Pinned by
`test_the_euro_drift_correction_does_not_restore_the_bound_for_a_liquidating_policy` so nobody
re-derives the median-price form as an improvement.
*Origin:* cost-simulation increment, Phase 4.

**H11. The feed-in floor top-up is not separable, so run E's bound is on the pre-top-up bill.** The
top-up is `max(0, −Σ_period export × compensation)` — a function of a whole assessment period's
dispatch, so pricing it inside `transition_cost` would need the period's running export revenue as
a second DP state dimension. Run E therefore minimises the per-interval bill and the top-up is
applied afterwards. In a window where the floor binds, the two bases diverge and a policy could in
principle beat the full-bill bound by stumbling into a larger top-up than the DP's dispatch earns.
`CostBenchmark.floor_binds` flags those windows so the figure is not read as unqualified, but **how
large such a violation could get has not been measured**. §6.12 does not discuss the interaction at
all.
*Origin:* cost-simulation increment, Phase 4.

**H12. `benchmarks.cost` and the euro figures are computed but not yet rendered.** — **DONE**
(cost-simulation increment, Phase 6). Panel ③ now renders the COST SAVINGS section: the MONEY SAVED
tile, the money benchmark box, the waterfall, monthly savings in euros and the euro caveats. The
money box rides the same lazy fetch as the energy one — `POST /results/benchmark` returns both
boxes wrapped by slot id, since both DPs run on that request anyway and returning one would spend
~2.3 s on a result nobody sees.
*Origin:* cost-simulation increment, Phase 4.

**H13. `test_no_english_leakage.py` scans whatever the developer's `data/` directory happens to
hold, so its coverage varies per machine.** Which panels and boxes the Dutch page renders — and
therefore which strings the test can catch — depends on the stored dataset and the stored config.
On a machine with `simulate_cost = true` it scans the Pricing box; on one with it false, it does
not. Pointing it at a temp data dir makes it *worse*, not better: with no dataset the page falls
back to the sample view-model, which carries its own untranslated strings (A7), producing six
failures. A real fix needs the fixture to seed both a known dataset and a known config, which is
test-infrastructure work rather than part of any feature increment. Until then, a green leakage
suite on one machine does not prove the catalogs are complete.
*Origin:* cost-simulation increment, Phase 5.

**H14. Four places still document gettext as `newstyle=True` when `app/i18n.py` sets it False.**
`params_view.py`'s module docstring, `tests/test_params_view.py`, and two comments state that a
literal `%` in a translated string is a live trap that eats the character or raises `ValueError`.
That was true and is not any more. The rule they impose (avoid literal `%`, use the word "percent"
or a `%(name)s` placeholder) is harmless to keep following and was followed in Phase 5, but the
stated *reason* is stale, and A2 in this same register describes the old behaviour as current. Worth
one sweep so the two do not contradict each other.
*Origin:* cost-simulation increment, Phase 5.

**H15. Two cost-only §4.5 fields remain unbuilt and are not faked.** `price_bracket` (§6.16's
intra-hour bracketing) and `diagnostics.resolution_bias_pct_eur` (§6.13's euro-basis bias) have no
domain-layer implementation, so panel ③ emits neither rather than emitting a zero or a placeholder.
Both were scoped out at the start of the cost-simulation increment (H3) and both are cost-only, so
they became visible as gaps only once the section existed to hold them. The kWh-basis
`resolution_bias_pct` beside the second is likewise unbuilt — that one predates this increment.
*Origin:* cost-simulation increment, Phase 6.

**H16. The waterfall's whole-euro rows do not visibly add up over short windows.** The rows render
with pattern `#,##0`, so on a window whose figures are single-digit euros a reader sees "+ € 4",
"− € 3", "€ 0" above a "Net saving + € 2" (actual net €1.54) and cannot check the column. The Net
saving row is correct — it is `saved_eur` from the two bills, never a sum of displayed rows, which
is what §2.4 requires — and the underlying `cost.waterfall` closes exactly (fixture 4). §2.4's
wireframe shows figures in the hundreds, where whole-euro rounding is invisible; it does not say
what to do over a week. Options: give the rows cents on short windows (and move
`WATERFALL_DISPLAY_EPS_EUR` with them — the two are deliberately tied), or state the rounding under
the box. Not decided here because it is a presentation choice the wireframe does not settle.
*Origin:* cost-simulation increment, Phase 6 review (finding 3).

**H17. `_cost_benchmark_block`'s `median_import_price_eur_kwh is None` fallback is written as safe
rather than as unreachable.** It substitutes 0.0, which makes the residual worth nothing, so a
materially-liquidating policy with a ratio above 1 would take the "genuine fault" wording instead of
the drift explanation. Not reachable in practice — a window with no priced interval has ~zero euro
figures throughout, so `capture_ratio` is None and shape 3 fires first — but the code does not say
so, and a future change that made a euro figure survive an unpriced window would silently
mis-explain it. A comment or an explicit guard would settle it.
*Origin:* cost-simulation increment, Phase 6 review (finding 5).

**H18. The dark theme is declared but unreachable, so every dark-mode rule in the stylesheet is
dormant and unverified.** `index.html` hard-codes `data-theme="light"` on `<html>`, while daisyUI's
dark rules are scoped to `:root:not([data-theme])` and `[data-theme='dark']` — neither of which can
match. The `@plugin 'daisyui'` block declares `dark --prefersdark`, so the intent is clearly that
dark mode exist.

This surfaced building the cost tint (Phase 7), which needs a per-theme split: daisyUI's `accent` is
the same bright teal in both themes and gives only **1.91:1** on light `base-100` — against WCAG
AA's 4.5:1 floor for small text — so light mode uses `accent-content` (9.70:1) and dark mode uses
`accent`. The dark branch is written and compiles, but nobody can see it and its contrast was
checked arithmetically rather than observed. The same is true of every other dark rule daisyUI
ships here.

Either wire a theme toggle (or drop the hard-coded attribute so `prefersdark` works) and verify the
dark palette in a live render, or decide the app is light-only and say so — at which point the dark
rules are dead weight rather than dormant. Not decided here: it is a product question about whether
the app supports dark mode at all, which predates this increment.
*Origin:* cost-simulation increment, Phase 7.

## Cross-cutting observations

Three clusters account for most of the list, and each has a single root:

- **A1 + A2 + A6 are one task.** All three are consequences of building display strings at runtime
  and then passing them through `_()`. The `%(name)s` restructuring fixes A1, removes A2's trap
  surface, and is the natural place to introduce locale-aware formatting (A6). Doing them separately
  means touching the same call sites and both catalogs three times.
- **B2 gates B3 and B5.** Until the setup band's radios POST, `simulate_cost` and `has_pv` cannot
  change through the UI, so the Pricing box, `economic_guard`, run E and the `charge P3`-without-PV
  reading all stay unreachable or untestable in the real app.
- **C1 + C2 are the remaining gap between panel ③ and §2.4's wireframe.** One real series and two
  real charts; everything else in that panel now plots real data.

Two items are decisions rather than work (B6 CSRF, C6 measured-vs-simulated band ratios) and should
not be re-litigated without a product reason. Two more (B4, B7) were explicitly parked pending
information that now exists — Phase 6's form layer shipped, so both are answerable rather than open.

## Files modified

- `changelog/20260725-collated-followups.md` — this file (new). Nothing else touched; no code, spec
  or catalog changes, nothing committed.

## Current status

Collation complete: 38 items across six areas, plus four process notes. Not triaged into a
priority order and not verified against the current tree — both are the user's call. If a next step
is wanted, the three clusters above are where the leverage is; which one to take first is open.
