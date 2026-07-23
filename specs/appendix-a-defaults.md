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
| `initial_soc_pct` | 50 | |
| `phases` | 1 | |
| `fuse_a` | 25 | → 5.75 kW (1×25 A) / 17.3 kW (3×25 A) |
| `max_export_kw` | = import | |
| `energy_tax_excl_vat` | 0.09161 €/kWh | 2026 rate; €0.11085 incl. VAT |
| `vat_rate` | 0.21 | |
| `supplier_markup` | 0.0205 €/kWh | Representative dynamic-supplier inkoopvergoeding |
| `feedin_alpha` | 0.50 | Statutory minimum to 1 Jan 2030 |
| `feedin_beta` | 0.0000 | |
| `feedin_floor_mode` | `monthly` | The law assesses the ≥0 floor over ≥1 month, not per interval |
| `feedin_floor_period` | calendar month | Shortest period the law permits, so the most favourable — see [§8.14](17-open-questions.md) |
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
| `dp_soc_levels` | 101 | |
| `dp_action_levels` | 41 | |

Tax and tariff constants must be editable in the UI and are stamped with the year they
were taken from. They will change on 1 January 2027.

Five of these defaults are themselves open questions: `degradation_eur_per_kwh`
([§8.3](17-open-questions.md)), `supplier_settlement` ([§8.12](17-open-questions.md)),
`pv_capacity_change_detection` ([§8.13](17-open-questions.md)), `feedin_floor_period`
([§8.14](17-open-questions.md)) and `has_pv` ([§8.16](17-open-questions.md)).

The 2026 constants above are drawn from
[background E-A](18-dutch-electricity-background.md#appendix-e-a--quick-reference-2026),
which also records what those figures were verified against and when.
