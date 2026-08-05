# Appendix A — Default parameter values

> **Purpose:** every shipped default in one table, with the reason for it.
> **Audience:** everyone. This is also the checklist for `config.toml`
> ([§5.4](08-architecture.md#54-configuration)).

| Parameter | Default | Source / rationale |
|---|---|---|
| `usable_capacity_kwh` | 10.0 | Typical residential |
| `min_soc_pct` | 10 | Common installer setting |
| `max_soc_pct` | 100 | |
| `max_charge_kw` | 5.0 | |
| `max_discharge_kw` | 5.0 | |
| `roundtrip_efficiency` | 0.90 | AC-to-AC; datasheet DC figures are 5–8 pp higher |
| `roundtrip_dc_bonus` | +0.04 | DC-coupled PV path |
| `standby_w` | 30 | ≈ 260 kWh/yr — material, routinely omitted |
| `coupling` | `ac` | |
| `has_pv` | `true` | The common case among likely users; asked explicitly, never inferred — see [§8.16](17-open-questions.md) |
| `simulate_cost` | `false` | Energy-only by default, so a first result needs no contract knowledge — see [§8.18](17-open-questions.md) |
| `initial_soc_pct` | 50 | |
| `phases` | 1 | |
| `fuse_a` | 25 | → 5.75 kW (1×25 A) / 17.3 kW (3×25 A) |
| `max_export_kw` | = import | |
| `energy_tax_excl_vat` | 0.09161 €/kWh | 2026 rate; €0.11085 incl. VAT |
| `vat_rate` | 0.21 | |
| `supplier_markup` | 0.0205 €/kWh | Representative dynamic-supplier inkoopvergoeding |
| `feedin_alpha` | 0.50 | Statutory minimum to 1 Jan 2030 |
| `feedin_beta` | 0.0000 | |
| `feedin_floor_mode` | `monthly` | The law assesses the ≥0 floor over a month, not per interval |
| `feedin_floor_period` | calendar month | The period art. 2.34 lid 7 Energiewet names; whether longer ones are lawful is unresolved — see [§8.14](17-open-questions.md) |
| `tlk_eur_per_kwh` | 0.0400 | Placeholder — 2027 tariffs unpublished |
| `dal_start_hour` | 23 | Varies by grid operator (21:00 in some areas) |
| `dal_end_hour` | 7 | |
| `dal_weekends` | true | |
| `degradation_eur_per_kwh` | 0.0 | Disabled |
| `allow_grid_export` | false | |
| `economic_guard` | false | Policies stay literal by default |
| `pv_coupling` | `dc_hybrid` | Most new installs are hybrid; ask, do not assume. Forced to `null` when `has_pv = false` |
| `battery_phases` | `three_phase` | Only offered when connection is 3-phase |
| `supplier_settlement` | `hourly` | Most NL dynamic suppliers still bill hourly averages |
| `epoch_detection` | on | PV/battery commissioning |
| `pv_capacity_change_detection` | off | Too many false positives — see [§8.13](17-open-questions.md) |
| `epoch_min_segment_days` | 45 | Rejects spurious changepoints |
| `undeclared_battery_check` | on | Heuristic, surfaced as a question |
| `time_offset_max_lag` | 12 intervals | ±12 h hourly, ±1 h at 5-minute |
| `time_offset_autocorrect` | off | Always offered, never applied silently |
| `debounce_ms` | 400 | |
| `dp_soc_levels` | 101 | Shared by both perfect-foresight runs ([§6.9](11-policies-and-battery.md#69-main-simulation-loop), runs D and E) |
| `dp_action_levels` | 41 | Likewise; the two objectives differ only in `transition_cost` |
| `benchmark_divergence_display_threshold` | 0.02 | Capture-ratio gap above which the "…if export allowed" benchmark row is shown ([§2.4](02-ux-wireframes.md#24-panel--results-expanded)). **Provisional** — an untested guess pending [experiment X10](19-prototype-experiments.md#x10--does-the-benchmarks-export-permission-matter) |
| `min_annualisation_days` | 90 | Below this a window is too short to annualise without large seasonal error ([§7.4](15-data-quality-and-limits.md#74-window-anchoring-and-short-window-guard)); check 13 |
| `min_tlk_tiering_days` | 90 | Below this the annualised export driving tiered terugleverkosten is too noisy ([§6.5](10-pricing.md#65-price-curves)); check 13, cost only. Defaults equal to `min_annualisation_days` but a distinct concern |
| `gap_factor` | 1.5 | An interval wider than this × the series' native resolution is a gap ([§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas)); check 3 |
| `pv_yield_max_kwh_per_kwp` | 2000 | Implausible-PV-total warning bound; check 10. A user with an atypical install may raise it |
| `load_max_kwh_per_year` | 30000 | Implausible-load-total warning bound (30 MWh/yr); check 10 |
| `rte_min` | 0.5 | Lower bound on accepted round-trip efficiency; check 11. The 1.0 upper bound is physics, not configurable |
| `pv_capacity_min_rel_step` | 0.20 | Minimum relative step in daily-peak PV for a capacity-change changepoint ([§6.15](13-configuration-epochs.md)) |
| `overlap_warn_pct` | 2 | `overlap_pct` above which the resolution-damage diagnostic warns ([§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly)) |
| `overlap_prominent_pct` | 10 | `overlap_pct` above which that warning is shown prominently |
| `residual_mean_warn_pct` | 5 | Power-vs-energy mean residual warning threshold ([§6.17](14-diagnostics.md#617-timestamp-misalignment-detection)); check 17 |
| `residual_diurnal_warn_pct` | 3 | Power-vs-energy diurnal residual warning threshold; check 17 |
| `tariff_zone_mismatch_pct` | 5 | Tariff-zone-vs-register mismatch above which the configured dal window is flagged wrong ([§6.4](09-ingest-algorithms.md#3-which-zone-applies-to-a-simulated-interval)); check 8b |
| `ha_fine_window_days` | 10 | Trailing window fetched at 5-minute resolution from Home Assistant ([§6.0](06-home-assistant-ingestion.md)); `statistics_short_term` retention |
| `ha_chunk_days` | 90 | Max days per WebSocket fetch call, to avoid oversized frames |
| `sse_poll_fallback_ms` | 750 | Polling interval when SSE is unavailable ([§4.1](04-state-machine.md)) |
| `params_persist_debounce_ms` | 1000 | Debounce before persisting changed params to disk |
| `result_cache_runs` | 5 | Number of recent run results retained in the result cache |

Tax and tariff constants must be editable in the UI and are stamped with the year they
were taken from. They will change on 1 January 2027.

**Which defaults are inert when `simulate_cost = false`.** The following parameters feed
the cost model only, are not asked for in energy-only mode, and are retained at their
stored values so that enabling cost simulation later restores the user's configuration
rather than resetting it: `energy_tax_excl_vat`, `vat_rate`, `supplier_markup`,
`feedin_alpha`, `feedin_beta`, `feedin_floor_mode`, `feedin_floor_period`,
`tlk_eur_per_kwh`, `dal_start_hour`, `dal_end_hour`, `dal_weekends`,
`degradation_eur_per_kwh` and `supplier_settlement`. `economic_guard` is additionally
**forced** off rather than merely hidden, because it reads a cost-model output
([§6.7](11-policies-and-battery.md#67-discharge-policy)).

Everything not in that list applies in both modes. The band parameters in particular
(`band_a` through `band_d`, not tabulated above because they have no fixed default — see
[§2.3](02-ux-wireframes.md#23-panel--parameter-configuration-expanded)) are dispatch
parameters and are asked for in both modes, as is the spot price series itself.

Five of these defaults are themselves open questions: `degradation_eur_per_kwh`
([§8.3](17-open-questions.md)), `pv_capacity_change_detection`
([§8.13](17-open-questions.md)), `feedin_floor_period`
([§8.14](17-open-questions.md)), `has_pv` ([§8.16](17-open-questions.md)) and
`simulate_cost` ([§8.18](17-open-questions.md)).

The 2026 constants above are drawn from
[background E-A](18-dutch-electricity-background.md#appendix-e-a--quick-reference-2026),
which also records what those figures were verified against and when.
