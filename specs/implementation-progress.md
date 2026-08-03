# Implementation progress — pending controls and feature keys

> **Purpose:** track which specified controls are built, which are still *pending*
> ([§2.1](02-ux-wireframes.md#the-four-availability-states)), and the feature keys the
> pending affordance uses. This is a living implementation record, not a specification — the
> specs state intent; this states how far the build has got.
> **Audience:** implementers.
> **Read with:** [02-ux-wireframes.md §2.1](02-ux-wireframes.md) (the pending affordance),
> [08-architecture.md §5.1](08-architecture.md) (the counter table and reporter).

## The app is built behind a complete UI

The UI is laid out in full from the wireframes; features are implemented one at a time behind
it. A control that is specified but whose machinery is not yet built renders **pending**:
disabled, greyed, with a `[?]` button that opens the "Not built yet" dialog and offers a
thumbs-up. Interest is recorded locally and, if an endpoint is configured, reported outward.

**As you build a feature, remove its control's pending markup** (the `disabled` attribute and
the `[?]` button in the template). Do **not** delete the control's feature key — retire it
(see below), so its counter row keeps its meaning.

## What is built, as of 2026-07-25

**Both the energy and the cost paths are complete end to end**: panel ② configures a battery and
(behind the `simulate_cost` answer) a contract, panel ③ simulates against the household's own
persisted data and reports what it would have saved in kWh and in euros, each bounded by its own
§6.12 perfect-foresight benchmark.

The cost path carries one contract type. Only DYNAMIC has a rate source behind it; FIXED and
VARIABLE are pending controls, blocked on §6.4's `tariff_zone` — a wall-clock dal window this
UTC-naive pipeline cannot yet express.

| Area | State |
|---|---|
| §6.2/§6.3 reconciliation, load reconstruction | built (`app/domain/reconcile.py`) |
| §4.4 `SimulationFrame`, spot on the simulation grid | built (`app/domain/simframe.py`) |
| Battery/policy config, appendix-A defaults, §7.3 checks 11/12/18 | built (`app/domain/simconfig.py`) |
| §6.6–§6.9 policies, battery step, runs A/B/C | built (`app/domain/simulate.py`) |
| §6.11 energy metrics | built (`app/domain/metrics.py`) |
| §6.12 perfect-foresight DP — both objectives (runs D and E) | built (`app/domain/benchmark.py`) |
| §6.5 price curves — **DYNAMIC contract only**, FLAT terugleverkosten | built (`app/domain/pricing.py`) |
| §6.5 feed-in floor, monthly and per-interval assessment | built (`app/domain/pricing.py`) |
| §6.10 cost accounting and the waterfall | built (`app/domain/costs.py`) |
| Panel ② form, validation, persistence | built (`app/params_view.py`, `app/simconfig_store.py`) |
| Panel ③ results, both benchmark boxes, cost savings section | built (`app/results_view.py`) |
| §6.16 price bracket — derived min/max, width, and the results caveat | built (`app/domain/simframe.py`, `app/results_view.py`) |
| `supplier_settlement` question in the Contract box | built (`app/workspace_edit_view.py`) |

`simulate_cost` is no longer a pending control: the setup band's radios POST, and panel ② draws
§2.3's Pricing box behind the answer. Within that box the two unbuilt contract types (FIXED,
VARIABLE) and tiered terugleverkosten are themselves pending — only DYNAMIC and FLAT have a rate
source behind them (§6.5).

**Not built** — the FIXED and VARIABLE contracts and tiered terugleverkosten (see above); §6.15
configuration epochs; §6.13's resolution-bias diagnostic (both bases); §6.17's
timestamp-misalignment detection; §4.6's per-interval CSV export; and CSV ingestion. §6.14 fixtures
1, 2, 3, 4, 5, 6, 7, 12, 13, 14, 16, 17, 18, 19, 20 and 21 are implemented; the rest belong to those
unbuilt areas. Fixture 10's ordering invariant is asserted by a named test in
`tests/test_results_view.py` but is not registered under the fixture number, so it is not counted
above.

Two findings from building the cost path are corrections to the specification rather than deferred
work, and are applied there: §6.10's waterfall pseudocode did not close (the standby line must be
taken on the pre-top-up bills — `top(C)` entered twice otherwise), and §2.3's Pricing wireframe drew
a "Spot source" control that duplicates panel ①'s slot-first data configuration. Both are recorded
in `changelog/20260725-cost-simulation.md`.

Known gaps in what *is* built, carried as follow-ups rather than silently. The DC-bonus validation
warning is unreachable, since panel ② renders no input for `roundtrip_dc_bonus`. `followups.md`
carries the rest; the ones a reader of this file should know about are that FIXED/VARIABLE inherit
an unbuilt local-time axis whose DST trap would misprice silently (H1), that §6.12's drift
correction has no sound euro analogue so the cost capture ratio is unavailable for a liquidating
policy (H10), and that run E's bound is on the pre-top-up bill in windows where the feed-in floor
binds (H11).

The runtime-f-string gap this file used to record is **closed**: `app/results_view.py` and
`app/data_view.py` now emit user-facing sentences as `(msgid, params)` pairs through `_msg`/`_msg_n`
rather than as f-strings, so they carry stable msgids and are translated.

## Feature keys — the closed vocabulary

Feature keys are short, stable strings naming pending controls in the counter table and the
POST body. They are allocated when a control is first marked pending and never reused. The
authoritative list is `app/features.py` (`FEATURE_KEYS`); the templates carry the same key in
`data-feature-key="..."`; the route `POST /feature-interest/{key}` rejects unknown keys.

### Currently pending

| Key | Control | Template | Blocked on |
|---|---|---|---|
| `data_source_csv` | "Upload CSV" data source | `_panel_data.html` | CSV ingestion |
| `pricing_contract_fixed` | "Fixed" contract radio in the Pricing box | `_panel_params.html` | §6.4's `tariff_zone` axis and the FIXED rate source |
| `pricing_contract_variable` | "Variable" contract radio in the Pricing box | `_panel_params.html` | a dated `rate_schedule` on `PricingConfig`, plus its editor |
| `pricing_tlk_tiered` | "tiered by annual volume" terugleverkosten | `_panel_params.html` | a tier table, annualisation, `min_tlk_tiering_days` |
| `export_csv` | "Export CSV" of results | `_panel_results.html` | results export |
| `chart_soc_price` | "SoC + price" chart tab | `_panel_results.html` | that chart's series |
| `chart_energy_flows` | "Energy flows" chart tab | `_panel_results.html` | that chart's series |

### Retired (feature shipped, key kept)

| Key | Control | Shipped in |
|---|---|---|
| `discharge_allow_export` | "Allow export to grid during D2/D3" | panel ② wiring — now a real checkbox bound to `policy.allow_grid_export` |
| `simulate_cost` | "Simulate cost savings?" choice in the setup band | the cost-simulation increment — the band's radios now POST to `/params` and panel ② draws the whole Pricing box behind the answer |

## How to add a pending control

1. Choose a `<box>_<control>`-shaped key (e.g. `battery_rte`). Add it to `FEATURE_KEYS` in
   `app/features.py` and to the table above.
2. In the template, render the control disabled and add a `[?]` button carrying
   `data-pending-name="<human label>"` and `data-feature-key="<key>"`. The shared dialog and
   its script (in `index.html`) do the rest.
3. Record the allocation in the changelog.

## How to retire a key (feature shipped)

1. Remove the control's `disabled` and its `[?]` button from the template.
2. Move the key's row from *Currently pending* to *Retired* above, and in `app/features.py`
   move it from `FEATURE_KEYS` to `RETIRED_KEYS`. The counter row in the database is left
   untouched — the key must never be reused or repointed, or historical counts become a lie.

## Backend status

Built ([changelog 20260723-pending-affordance-impl](../changelog/20260723-pending-affordance-impl.md)):

- `feature_interest(feature_key, count, last_clicked_at)` in a local SQLite file under the
  data dir (`app/db.py`), upsert-once per `feature_key`. This table is installation-wide, not
  per-workspace — the deliberate and only exception to [§5.5](08-architecture.md)'s invariant 1,
  argued there. It was originally keyed `(workspace_id, feature_key)`; the workspaces restructure
  re-keyed it, collapsing existing rows by `feature_key` and keeping the earliest
  `last_clicked_at`.
- `InterestReporter` outbound POST (`app/interest.py`): fire-and-forget, off unless
  `feature_interest_url` is set; body is `{feature_key, app_version, installation_id}`.
- `config.toml` loading and first-run `installation_id` generation (`app/config.py`).
- `POST /feature-interest/{key}` (`app/main.py`) and the dialog's acknowledge-in-place script.

Storage note: this uses the standard-library `sqlite3` for the single counter table. The full
six-table schema of [§5.1](08-architecture.md) is expected to move to SQLAlchemy when it lands;
`feature_interest` migrates with it.
