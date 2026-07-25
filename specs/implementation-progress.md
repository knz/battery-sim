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

The **energy path is complete end to end**: panel ② configures a battery, panel ③ simulates it
against the household's own persisted data and reports what it would have saved, bounded by the
§6.12 perfect-foresight benchmark.

| Area | State |
|---|---|
| §6.2/§6.3 reconciliation, load reconstruction | built (`app/domain/reconcile.py`) |
| §4.4 `SimulationFrame`, spot on the simulation grid | built (`app/domain/simframe.py`) |
| Battery/policy config, appendix-A defaults, §7.3 checks 11/12/18 | built (`app/domain/simconfig.py`) |
| §6.6–§6.9 policies, battery step, runs A/B/C | built (`app/domain/simulate.py`) |
| §6.11 energy metrics | built (`app/domain/metrics.py`) |
| §6.12 perfect-foresight DP — **energy objective (run D) only** | built (`app/domain/benchmark.py`) |
| Panel ② form, validation, persistence | built (`app/params_view.py`, `app/simconfig_store.py`) |
| Panel ③ results, benchmark box | built (`app/results_view.py`) |

`simulate_cost` is no longer a pending control: the setup band's radios POST, and panel ② draws
§2.3's Pricing box behind the answer. Within that box the two unbuilt contract types (FIXED,
VARIABLE) and tiered terugleverkosten are themselves pending — only DYNAMIC and FLAT have a rate
source behind them (§6.5).

**Not built** — the §6.15
configuration epochs; §6.16's price bracket; §6.13's resolution-bias diagnostic; §6.17's
timestamp-misalignment detection; §4.6's per-interval CSV export; and CSV ingestion. §6.14 fixtures
1, 2, 3, 5, 6, 7, 12, 16, 17 and 21 are implemented; the rest belong to those unbuilt areas.

Known gaps in what *is* built, carried as follow-ups rather than silently: runtime-assembled strings
(caveats, the benchmark gloss, panel ①'s data-quality box) are not translatable, because an
f-string has no fixed msgid — they need restructuring around `%(name)s` placeholders; and the
DC-bonus validation warning is unreachable, since panel ② renders no input for
`roundtrip_dc_bonus`.

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

- `feature_interest(workspace_id, feature_key, count, last_clicked_at)` in a local SQLite
  file under the data dir (`app/db.py`), upsert-once per `(workspace_id, feature_key)`.
- `InterestReporter` outbound POST (`app/interest.py`): fire-and-forget, off unless
  `feature_interest_url` is set; body is `{feature_key, app_version, installation_id}`.
- `config.toml` loading and first-run `installation_id` generation (`app/config.py`).
- `POST /feature-interest/{key}` (`app/main.py`) and the dialog's acknowledge-in-place script.

Storage note: this uses the standard-library `sqlite3` for the single counter table. The full
six-table schema of [§5.1](08-architecture.md) is expected to move to SQLAlchemy when it lands;
`feature_interest` migrates with it.
