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

**B6. Cross-site POSTs: the three destructive routes are checked, `POST /params` is not.**
Rewritten 2026-07-26 (workspaces phase 2 review) — the previous entry's two premises had both
become false and are recorded here so the change of position is legible.

*What the old entry said, and why it stopped holding.* It declined CSRF protection outright on the
grounds that `workspace_id` was "the hardcoded `local` and never user-influenced" and that the
"worst outcome is a rewritten local parameter set". Phase 1 put the workspace id in the path, so
the first is no longer true. Phase 2 added `POST /w/{id}/delete` and `POST /w/{id}/data/delete`, so
the second is no longer true either: the worst outcome is irreversible deletion of a workspace's
rows, its `simconfig.json` and its whole directory.

*Reproduced.* A single `POST /w/local/delete` carrying `Origin: https://evil.example` was accepted
and destroyed the workspace. No guessing was involved — a migrated pre-index installation always
has the id `local`, so every such installation was equally targetable by a fixed URL.

*What is protected now.* `app/csrf.py` provides `require_same_site`, a FastAPI dependency declared
by `POST /workspaces`, `POST /w/{id}/delete` and `POST /w/{id}/data/delete`; a cross-site request
gets 403. It trusts `Sec-Fetch-Site` when present and falls back to comparing `Origin` against the
request's own host. **This deliberately keeps the property the old entry declined tokens for**: no
session, no secret, no server-side state — the browser already supplies headers page script cannot
forge, so no token is needed for these three.

*What is NOT protected, and why that is a decision.* `POST /w/{id}/params` is left open. It is an
idempotent overwrite of one local parameter set with values a forging page chooses blind and cannot
read back (the response is same-origin-read-blocked), which is exactly the threat the original
entry weighed and accepted — that reasoning survives intact for this route, because what changed in
phase 2 was the arrival of irreversible deletion, not anything about `params`. The line is drawn at
"can this request destroy something the user cannot recreate".

*The remaining hole in the check.* When BOTH `Sec-Fetch-Site` and `Origin` are absent the request
is allowed. No browser produces a cross-origin POST without one of them, so this is not reachable
from a browser attack; it is reachable by `curl`, a scripted local client, or a proxy that strips
headers. Closing it needs a token, which is the option excluded above. First thing to revisit if
the app ever stops being local-only — at which point it would need a session anyway.
*Origin:* `20260725-phase6-review-defects.md`, `20260724-panel3-battery-simulation.md`,
`20260726-workspaces-phase2.md` (review).

**B7. `_finite()` rejects `str`, so `GridConfig(phases="3")` blocks rather than coercing.**
Defensible (coercion belongs to the form layer) but the opposite choice is equally defensible; the
note said to revisit once Phase 6's form binding existed and showed which is less friction. Phase 6
now exists, so this is answerable.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 2 follow-ups), `20260724-sim-config-phase2.md`.

**B8. The display-precision rule and 230 V are inferred, not specified.** "2 dp below 10 kW, 1 dp
at/above" and the 230 V mains figure are each pinned by the same two published figures and appear
nowhere in `docs/specs/`.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 2 follow-ups).

## C. Simulation, benchmark and metrics

**C1. A real per-month savings series remains unbuilt.** §2.4's wireframe asks for a
monthly-savings chart. What ships is `results_view._monthly_import()` — measured grid import per
calendar month — now honestly relabelled "Monthly grid import". Building the real series means
running the A/B/C simulation and bucketing `saved_kwh` per month.
*Origin:* `20260724-panel3-battery-simulation.md` (Phase 7).

**C2. Two chart tabs are pending affordances, not implementations.** "SoC + price" and "Energy
flows" now carry the §2.1 pending affordance with keys `chart_soc_price` and `chart_energy_flows`
in `app/features.py`. Named as newly pending in `docs/specs/implementation-progress.md`.
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
*Origin:* `docs/specs/09-ingest-algorithms.md` §6.4, carried forward.

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

---

# Added 2026-07-26 — workspaces restructure, phase 0

## I. Deferred by the workspaces restructure (phase 0)

**I1. `upsert_series`' rollback covers the rows, not the `.npz` file.** `_save_frame` runs before
the transaction and `_frame_path` is deterministic by name, so a failed replacement restores the
`series_meta` row but leaves the *new* array on disk. The honest post-condition is "the series is
still there, still listed, still readable with its original metadata", not "its values are
unchanged". Strictly smaller damage than the regression it replaced (which removed the series
outright), and the same rows-versus-files split that findings 6 and 8 of that phase already accept.
Closing it properly means writing the frame to a temp path and renaming it inside the transaction,
or accepting a two-phase write. Documented in `upsert_series`' docstring and pinned by an assertion
in `tests/test_slot_load.py`.
*Origin:* `20260726-workspaces-phase0.md` finding 9.

**I2. The card's interval count is derived, and can be plainly wrong rather than approximate.**
~~`workspaces._data_facts` computes `window / resolution` from `series_meta`, using
`max(resolutions)` without `choose_grid`'s `covers(window)` filter — so a short auxiliary series
drags the reported grid coarser. Measured: a 900 s grid series over a two-day window plus a
three-hour 3600 s solar series reports 3600 s / 48 intervals instead of 900 s / 192.~~ **DONE.**

The symptom was real and the fixture reproduces, but **the diagnosis above was wrong** — recorded
because it was quoted forward twice before anyone re-ran it. On that fixture the results screen
resolves **3600 s / 3**, not 900 s / 192: `grid_report` clips to `effective_window` (the energy
coverage intersection) BEFORE selecting the grid, and once the window is the three-hour overlap the
solar series does cover it, so 3600 s is correct and the card's *resolution* was right all along.
The divergence there is entirely the window — stored fetch bounds vs. effective — and the count
alone (48 vs 3).

The `covers()` filter named above does cause a divergence, but only in one shape found by probing:
an **empty** energy series carrying a coarse `resolution_s`, which `effective_window` skips and
`choose_grid` drops but an unfiltered `max()` keeps — 3600 s / 48 against a true 900 s / 192.

Closed as the entry suggested, with `grid_s` and `n_intervals` columns on `datasets` written at
save time and no npz read per card. Both save paths write them; `upsert_series` reads its sibling
frames back to recompute, since merging one series can change the size of the whole dataset. The
part that actually closes it is `normalize.grid_facts`, extracted from `grid_report` so both the
card and the results screen call one implementation rather than agreeing by inspection. Rows
predating the columns fall back to the old derivation, so no existing workspace loses its card line.
*Origin:* `20260726-workspaces-phase0.md` finding 5.
*Closed by:* `20260728-persist-interval-count.md`.

**I3. `delete` is not atomic across SQLite and the filesystem.** Rows are deleted, then the
directory is removed with `ignore_errors=True`. A crash between the two, or an unwritable directory,
leaves unreferenced `.npz` files with no route to reclaim them, and a failed `rmtree` is silent.
Accepted for a local single-user app — the failure mode is wasted disk, not a wrong result, since
every read goes through `series_meta`. Closing it needs a startup sweep for directories with no
workspace row. Stated in the docstrings rather than fixed.

*Updated 2026-07-26 (phase 2 review).* The same non-atomicity turned out to hold between `delete`'s
two SQL steps as well, not just between rows and files: `delete_data` opens `dataset.connect()` and
`delete` opens `db.connect()`, and `_Connection._depth` is per-connection, so the docstring's claim
that the blocks nested into one transaction was false. The steps were REORDERED so the workspace
row goes first — a crash then leaves unreachable data rows behind a workspace that is gone, instead
of a live card whose measurements had silently vanished. Still not atomic; the reasoning for
accepting that rather than threading one connection through both is in `workspaces.delete`.
*Origin:* `20260726-workspaces-phase0.md` finding 8, `20260726-workspaces-phase2.md` (review).

**I4. `monkeypatch.undo()` is a trap in the workspace test modules.** It also reverts the fixture's
`BATTERY_SIM_DATA_DIR` setenv, silently redirecting any later assertion at the developer's real
`./data`. Worked around with manual patch/restore in `tests/test_slot_load.py`; worth a fixture that
makes the data-dir override non-revertible so the next test author does not rediscover it.
*Origin:* `20260726-workspaces-phase0.md` finding 9.

**I5. `feature_interest`'s collapse orders timestamps lexicographically.** `MIN(last_clicked_at)`
over TEXT equals the earliest instant only because `record_interest` writes
`datetime.now(timezone.utc).isoformat()` — fixed width, always `+00:00`. A row written by a
differently-built version with another offset would break it. Left as a documented assumption rather
than re-engineered: the field is telemetry no user reads, and an instant-based ordering costs a
parse per row.
*Origin:* `20260726-workspaces-phase0.md` finding 4.

**I6. `workspaces.touch()` still has no production caller. — DONE (phase 2).**
`POST /w/{id}/params` now calls it, after a save that actually happened. Pinned by
`tests/test_workspace_list.py`'s ordering test and by the invalid-submission companion.
 §2′.10 makes a config save the one
event that advances `updated_at`, and `POST /w/{id}/params` is that save — but it does not call
`touch`, because nothing reads the field until phase 2's list ordering and "last saved" badge
exist, and phase 1 was scoped to change no behaviour. Wire it with the screen that shows it, or the
first list will order every workspace by its creation time.
*Origin:* `20260726-workspaces-phase1.md`.

**I7. The lifespan now CREATES `local` when it is missing, which phase 2 must remove. — DONE
(phase 2).** Removed; `migrate_local()` stays. A fresh installation shows §2′.2's empty list, pinned
in a real browser against a genuinely fresh data directory (`tests/test_smoke.py`).
 Phase 0
deliberately left a fresh installation with an empty index so §2′.2's list can show its empty state
and the wizard. Scoping the routes made that a broken page — `GET /` renders the single-page UI for
`local` and every control on it 404s without the row — so `app/main.py`'s lifespan creates it. Once
`GET /` is the list, this line becomes the phantom workspace §2′.2 does not want.
*Origin:* `20260726-workspaces-phase1.md`.

**I8. `ha_fetch.js`'s file header had drifted from the code, independently of the workspace work.
— DONE (2026-07-28).** The owed full pass was made. What the drift actually was, beyond the
phase-1 lines: the header named `_panel_data.html` (deleted; the roster is `_data_roster.html`)
and `_setup_band.html` (deleted; the answers are in `_data_household.html`), still called panel ①
a panel after it became the configure-data screen, and headed its last block "User actions on the
connection card" after that card became the `#ha-config-dialog` modal. Two paragraphs explaining
what an earlier version of the comment had said were dropped as changelog content — but the note
that `POST /w/{id}/data/slot/{slot}/load` exists and the browser deliberately never calls it was
kept, since that is a fact about the code. Also fixed while in there: `mappedSlots`'s docstring had
been orphaned from its function by the setup-band block spliced between them. The load-bearing
parts — the generation-reconcile rule, the global-connection vs per-workspace-store split, the
transactional draft model — were checked and were correct.
*Origin:* `20260726-workspaces-phase1.md`. *Closed by:* `20260728-i8-ha-fetch-header.md`.

**I9. `DataFacts.loaded` means "has a dataset", not "has energy data", and the card shows it.**
A workspace whose only series is a PRICE series (the preset spot-price load, which is the one
dataset a backend_load can produce on its own) gets `loaded=True`, so §2′.2's info box opens in its
full form and reads "not loaded" three times — once per energy role — while the card still offers
`[ Results ]`. Nothing renders wrongly in the narrow sense: the size line is correctly omitted
(`_data_facts` derives the interval count from energy resolutions only and returns None) and no
literal `None` reaches the page. But the card invites the user to a results screen that has no
grid to simulate.

This is a phase-0 `_data_facts` property that the phase-2 card merely surfaces, not a defect
introduced by the card, which is why it is recorded rather than fixed here. The plausible change is
for `loaded` to mean "has at least one ENERGY series", which would put such a workspace in the
no-data variant and withdraw `[ Results ]` — consistent with §2.1's Inapplicable rule. Not made
unilaterally: it changes what a card says about a real dataset the user did load, and a
price-only workspace is a legitimate intermediate state during setup, so whether the right answer
is the stricter flag or a third "prices only" state is a product call.
*Origin:* `20260726-workspaces-phase2.md` (review, finding 8).

**J1. `POST /w/{id}/edit`'s save-error banner overstates a partial write.**
`simconfig_store.save` and `workspaces.rename` are two writes inside one `try`. If the config write
succeeds and the rename raises `OSError`, the banner says the settings could not be saved — but the
config, the connection and `pricing_configured` were all persisted, and only the title was not. The
re-rendered page then shows the typed title beside a banner claiming nothing was stored. Reproduced
with `rename` monkeypatched to raise; the outcome is a misleading message rather than lost data, and
the condition (a data dir that fails between two writes) is rare. The fix is either two try blocks
with two messages, or a banner worded as "some settings".
*Origin:* `20260726-workspaces-phase3.md` (review, finding 4).

**J2. The route documents a `mode` form field the template never emits.**
`POST /w/{id}/edit` reads `form.get("mode")` and both the route docstring and the phase-3 changelog
explain it as the mechanism by which wizard mode survives a validation re-render "without depending
on the form's action URL being rebuilt". The template emits no such hidden field; the mode in fact
survives via `action="…?mode=wizard"`, which is the mechanism the comment says it avoids depending
on. The behaviour is correct and the branch is harmless, but the code and its explanation disagree,
so one of them should go — either emit the hidden field or drop the fallback and the paragraph.
*Origin:* `20260726-workspaces-phase3.md` (review, finding 5).

**J3. The leakage scan sees only the edit screen's default render.**
`tests/test_no_english_leakage.py` renders `GET /w/{id}/edit` on a default config, so the off-list
connection label, the page-level `other_errors` alert, the save-error banner and the inline field
errors are never scanned. All four were checked by hand in Dutch during the phase-3 review and are
translated, so this is a coverage gap rather than a leak — but it is the kind of gap that lets a
later edit to those paths ship English unnoticed. Worth folding into phase 6, which already owns
extending that scan.
*Origin:* `20260726-workspaces-phase3.md` (review, finding 6).

**K1. No config-writing route checks `is_document_readable`, so an unreadable document is
silently replaced by appendix-A defaults.**
`simconfig_store.is_document_readable` exists for exactly this and its docstring states the rule:
"`load()` never raises… That makes it the right function for RENDERING a page and the wrong basis
for a REWRITE, because the defaults it invents would then replace the values it could not read.
Anything that saves back a config it did not obtain from the user needs this distinction." No write
path calls it. `workspaces.migrate_local` is the only guarded caller anywhere.

Reproduced against a document with `version` bumped to 2 (a future build, or a hand edit), and
again with a JSON syntax error. Both `POST /w/{id}/data` and `POST /w/{id}/edit` return 303 while a
17.5 kWh battery and a 63 A fuse become 10.0 and 25.0 and the version is silently downgraded to 1:

    POST /data   status=303 cap=10.0 fuse=25.0 version=1
    POST /edit   status=303 cap=10.0 fuse=25.0 version=1

`POST /params` has the same shape (it writes the submitted values over invented ones), as does the
fetch path via `_persist_setup_answers`. So this is class-wide and pre-dates the workspaces work —
phase 4.1 did not introduce it. What phase 4.1 changed is exposure: it puts a `[ Save ]` button on
the behaviour that a user clicks deliberately.

Deliberately not fixed on one route: a check on `POST /w/{id}/data` alone would leave the other
three clobbering, which is the drift the same-site standing note (B6, and phase 3's changelog)
warns against. The four config-writing routes should gain it together, along with a decision about
what the user is shown when the document is unreadable — a 409-style "this analysis was written by
a newer version" screen is the obvious shape, and it is a product call, not a mechanical one. Worth
weighing against a version-downgrade being arguably worse than the CSRF exposure B6 covers.
*Origin:* `20260726-workspaces-phase4.md` (review, finding 2).

**K2. `[ Save ]` on the configure-data screen leaves a staged-but-unfetched mapping without a
warning.**
§2′.8 says the dirty check "does not guard `[ Save ]` or `[ Next → ]`, which persist", and the
screen follows that literally. But on the edit screen `[ Save ]` persists the thing the check is
about, whereas here it persists two booleans while the staged slot mapping stays unfetched. So the
rule is honoured and its rationale is not: a user who stages a source and clicks `[ Save ]` is told
nothing and lands on a list whose results still describe the old data.

Reproduced in Chromium: after `[ Save ]` with a current-generation store entry, the dialog does not
appear, the page navigates to `/`, and the entry survives in `localStorage` (so `ha_fetch.js`
restores it on return — nothing is lost). This is a missing signal, not data loss, which is why it
is filed rather than fixed. The plausible answers are to guard `[ Save ]` here too, or to have
`[ Save ]` also commit the staged mapping; the second changes what `[ Save ]` means on this screen
and is a product call.
*Origin:* `20260726-workspaces-phase4.md` (review, finding 5).

**L1. `RESULTS_STALE` does not dim the previous results; the app has never implemented it.**
§2′.6 says "`RESULTS_STALE` still renders the previous results dimmed rather than blanking them"
([§3.1](04-state-machine.md)), and the word "still" is doing work the code does not back: the
pre-restructure `index.html` did not dim either, so nothing regressed — the spec point has simply
never been built. What IS implemented is the other half: `#results-recalculating` is un-hidden for
the duration of a recompute, the previous panel stays in the DOM, and a refused recompute leaves the
last good figures alone. Grepping `_panel_results.html` and `workspace_results.html` for
`opacity-`/`dim`/`stale` finds only the pending-chart buttons and the blocked cost toggle.

Filed rather than fixed because it is a visual-design decision (how much dimming, on which elements,
and whether it applies to a partial swap) and because §2′.6 lists it under "what is unchanged",
where it is describing existing behaviour rather than requesting new work. `tests/test_workspace_
results.py`'s test was renamed from `test_results_stale_dims_…` to
`test_a_refused_recompute_keeps_…`: a green test named for the dimming read as coverage of a thing
that does not exist.
*Origin:* `20260726-workspaces-phase4.md` (4.2 review, finding 3).

**L2. `POST /w/{id}/edit` sets `pricing_configured=True` on every successful save, not only when
the Contract box was touched.**
§2′.6 specifies the flag is "set true when the user saves the edit-workspace screen **having
touched the Contract box**", and argues for a flag precisely so that "any stray edit — including one
the user reverted — would silently unlock the toggle" cannot happen. The phase-3 implementation sets
it unconditionally on a successful save, which is documented at `app/main.py:449-453` and was a
deliberate simplification, but it is not what the spec says.

Out of scope for 4.2, which only made the consequence visible: a user who renames their analysis, or
who walks the wizard without ever opening the Contract box, arrives at results with the cost toggle
live and appendix-A default rates presented as their contract. Worth deciding together with the
Blocked-toggle question below (L3), since both turn on what "the user has told us what they pay"
should mean.
*Origin:* `20260726-workspaces-phase4.md` (4.2 review, noted item).

**L3. A hand-crafted POST can turn cost simulation on while `pricing_configured` is false.**
The results screen then renders a checked-but-Blocked toggle beside a fully drawn Pricing box:
internally coherent, contradictory to read. Reproduced with a direct `POST /w/{id}/params` carrying
`setup.simulate_cost=yes`; `simulate_cost` is stored True while `is_pricing_configured` stays False.

Confirmed LATENT, not live: the rendered radios carry `disabled`, so no browser path submits them
while blocked, and §2′.10's migration sets the flag true for anyone who already had cost simulation
on. It is reachable by a hand-edited document or a crafted request only. The review looked for other
entrances and found none — `parse_form`'s `setup`-gated branch is the sole writer of `simulate_cost`.

Not fixed because the resolution is a product choice between three defensible answers: force cost
off while the precondition is unmet (the config always matches the affordance, but a stored user
answer gets overwritten by a rule); unblock the toggle whenever cost is already on (the state
becomes self-consistent, but the precondition stops meaning anything); or hide the Pricing box while
blocked (honest, but the box is where the user would go to satisfy the precondition). The first is
the most defensive and the third the most confusing; L2 above probably wants deciding first.
*Origin:* `20260726-workspaces-phase4.md` (4.2, flagged by the implementer, confirmed by review).

**L4. The feed-in (α, β) preset select has no home after the Pricing box moved.**
§6.5 tabulates three (α, β) rows — "Legal minimum — 50 percent of the bare price", "Spot minus
fee", "Spot" — and panel ② offered them as a `<select>` that WROTE the two fields. It was
client-side only: never a stored value, only a way of typing the pair. §2′.1 moved the Pricing box
to the edit-workspace screen, which renders α and β as plain numeric fields and has no equivalent
select, so the shortcut is currently absent from the app rather than relocated.

Nothing persisted is affected and neither value lost any capability — both still coerce, store and
render back (pinned by `test_the_feedin_pair_round_trips_without_the_preset_shortcut`). What is
lost is discoverability: a user who recognises "Legal minimum" by name now has to know it means
α = 0.50, β = 0.0000. Rebuilding it is an edit-screen design question — where it sits relative to
the two fields, and whether the "Custom" row still reads correctly inside that screen's Advanced
pane — which is why it was not done as part of undoing the duplication.
*Origin:* `20260728-results-screen-leftover-boxes.md`.

**Note on L3:** its third option — "hide the Pricing box while blocked" — is now moot. The box no
longer renders on the results screen at all (§2′.1), so the contradictory state L3 describes is
narrower than when it was written: a hand-crafted POST can still leave `simulate_cost` true with
`pricing_configured` false, but what the reader then sees is a checked-but-Blocked toggle beside
COST SAVINGS figures, not beside an editable Pricing box. The first two options are unaffected.
