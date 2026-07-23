# 2. UX wireframes

> **Purpose:** the single-page layout and the three stepper panels.
> **Audience:** frontend.
> **Read with:** [03-topology-selector.md](03-topology-selector.md) for the illustrated
> selectors referenced from panel ②, and [04-state-machine.md](04-state-machine.md) for
> the state transitions these panels drive.

## 2.1 Overall layout

Single page, three stacked panels acting as a stepper. Completed panels collapse to a
one-line summary and can be reopened at any time. Reopening and editing does **not**
discard results — it marks them stale and triggers a recalculation.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Home Battery Simulator                          [workspace: local]  [⚙]     │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ ① DATA                                            ✓ 412 days  [edit ▾] │  │
│  │    Home Assistant · 5 series · hourly (5-min for last 9 days)          │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ ② PARAMETERS                                      ✓ valid     [edit ▾] │  │
│  │    10.0 kWh · 5.0/5.0 kW · 90% · charge P3 · discharge P1 · dynamic    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ ③ RESULTS                                                    [expanded]│  │
│  │                                                                        │  │
│  │   ... see 2.4 ...                                                      │  │
│  │                                                                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2.2 Panel ① — Data input (expanded)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ① DATA                                                            [collapse] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Source:  ( • ) Home Assistant      (   ) Upload CSV                         │
│                                                                              │
│  ┌─ Home Assistant ───────────────────────────────────────────────────────┐  │
│  │  Base URL   [ http://homeassistant.local:8123               ]          │  │
│  │  Token      [ ●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●● ]          │  │
│  │                                                     [ Test connection ] │  │
│  │  ✓ Connected · HA 2026.6.2 · 1,284 statistic IDs available             │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Series mapping ───────────────────────────────────────────────────────┐  │
│  │                                                                        │  │
│  │  ROLE                REQ  ENTITY / STATISTIC ID                        │  │
│  │  ──────────────────────────────────────────────────────────────────    │  │
│  │  Grid import T1       ●   [ sensor.electricity_meter_import_t1    ▾ ]  │  │
│  │  Grid import T2       ●   [ sensor.electricity_meter_import_t2    ▾ ]  │  │
│  │  Grid export T1       ●   [ sensor.electricity_meter_export_t1    ▾ ]  │  │
│  │  Grid export T2       ●   [ sensor.electricity_meter_export_t2    ▾ ]  │  │
│  │  Solar production     ◐   [ sensor.solar_total_production         ▾ ]  │  │
│  │  Battery charge       ○   [ — none —                              ▾ ]  │  │
│  │  Battery discharge    ○   [ — none —                              ▾ ]  │  │
│  │  Spot price           ○   [ sensor.epex_spot_price                ▾ ]  │  │
│  │                                                                        │  │
│  │  ○ = optional.  Spot price required only for dynamic pricing.          │  │
│  │  ◐ = required only if you have solar PV (set in panel ②).              │  │
│  │  If T1/T2 are not split, map "Grid import T1" and leave T2 empty.      │  │
│  │                                                                        │  │
│  │                                              [ Fetch history ]         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Data quality ─────────────────────────────────────────────────────────┐  │
│  │  Coverage        2025-06-01 → 2026-07-21   (416 days)                  │  │
│  │  Resolution      hourly · 5-min available for last 9 days              │  │
│  │  Gaps            3 gaps totalling 4.2 h  (0.04%)          [ details ]  │  │
│  │  Counter resets  2 detected and corrected                 [ details ]  │  │
│  │                                                                        │  │
│  │  ⚠  Reconstructed load is negative in 41 intervals (0.41%).            │  │
│  │     Usually means the solar sensor does not cover the whole house,     │  │
│  │     or a clock offset between sensors.            [ what to check ]    │  │
│  │                                                                        │  │
│  │  ⚠  T1/T2 register check: 2.1% of intervals disagree with the          │  │
│  │     configured day/night window.                  [ adjust window ]    │  │
│  │                                                                        │  │
│  │  Tariff registers   T1 = normaal (day)   T2 = dal (night)  [ swap ]    │  │
│  │                     auto-detected from increment timing                │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│                                              [ Next: parameters →  ]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

The **Solar production** row is rendered only when the household has declared PV
(`cfg.has_pv`, set by the toggle in panel ② below). With PV declared it is required and
carries the same `●` as the grid registers; the `◐` in the wireframe marks the row as
conditional on that declaration rather than as a third level of optionality. With PV not
declared the row is hidden entirely rather than shown greyed, so there is no invitation to
map a sensor the run will ignore.

Panel ② is therefore the panel that decides what panel ① asks for. Since the natural order
of use is ① then ②, the PV toggle is also mirrored at the head of the series-mapping box
as a one-line question, and changing it in either place changes it in both.

The data-quality box renders the diagnostics computed at ingest time. Their definitions
live in [14-diagnostics.md](14-diagnostics.md); the ordered list of checks and their
failure actions is in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order). Several
of those checks are PV-dependent and are simply not run without PV — the box omits them
rather than reporting them as passed. The epoch timeline strip described in
[§6.15](13-configuration-epochs.md#615-configuration-epochs) is rendered above the
coverage summary.

CSV variant of the source sub-panel:

```
  ┌─ Upload CSV ───────────────────────────────────────────────────────────┐
  │                                                                        │
  │    ┌──────────────────────────────────────────────────────────────┐    │
  │    │            Drop CSV files here, or click to browse           │    │
  │    │                                                              │    │
  │    │        Long format (canonical) or wide format accepted       │    │
  │    └──────────────────────────────────────────────────────────────┘    │
  │                                                                        │
  │    Uploaded:  meter_2025.csv   ✓ 8,412 rows · 4 series                 │
  │               solar_2025.csv   ✓ 8,760 rows · 1 series                 │
  │               prices.csv       ✓ 8,760 rows · 1 series                 │
  │                                                                        │
  │    [ Download format spec ]   [ Download example file ]   [ Clear all ] │
  └────────────────────────────────────────────────────────────────────────┘
```

The two accepted CSV shapes are specified in [05-data-formats.md](05-data-formats.md).

## 2.3 Panel ② — Parameter configuration (expanded)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ② PARAMETERS                                                      [collapse] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ Battery ──────────────────────────────────────────────────────────────┐  │
│  │  Usable capacity        [  10.0 ] kWh    ⓘ not nameplate               │  │
│  │  Min state of charge    [    10 ] %                                    │  │
│  │  Max state of charge    [   100 ] %                                    │  │
│  │  Max charge power       [   5.0 ] kW                                   │  │
│  │  Max discharge power    [   5.0 ] kW                                   │  │
│  │  Round-trip efficiency  [    90 ] %      ⓘ AC-to-AC at the meter       │  │
│  │  Standby draw           [    30 ] W      ⓘ ≈260 kWh/yr — see help      │  │
│  │  Coupling               ( • ) AC-coupled   (   ) DC / hybrid           │  │
│  │  Initial SoC            [    50 ] %                                    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Grid connection ──────────────────────────────────────────────────────┐  │
│  │  Phases      ( • ) 1-phase    (   ) 3-phase                            │  │
│  │  Fuse rating [ 25 ] A     →  max import 5.75 kW   [ override ]         │  │
│  │  Export limit          [ same as import ▾ ]                            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Solar PV ─────────────────────────────────────────────────────────────┐  │
│  │  Do you have solar panels?   ( • ) Yes    (   ) No                     │  │
│  │  ⓘ Answering No hides the solar sensor mapping, the PV coupling        │  │
│  │    choice, and the policies that act on solar surplus.                 │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Installation topology ────────────────────────────── [see §2.5] ─────┐  │
│  │  PV coupling      ( • ) DC-coupled / hybrid   (   ) AC-coupled         │  │
│  │                   (shown only when you have PV)                        │  │
│  │  Battery phases   ( • ) 3-phase inverter      (shown for 3-phase only) │  │
│  │  Both are chosen from illustrated options, not from these labels.      │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Charge policy ────────────────────────────────────────────────────────┐  │
│  │  (   ) P1  Solar surplus only (net zero at the grid)       [PV only]   │  │
│  │  (   ) P2  Grid charge when spot price is in band                      │  │
│  │  ( • ) P3  Both                                            [PV only]   │  │
│  │                                                                        │  │
│  │        Band A (lower) [ -0.050 ] €/kWh   B (upper) [ 0.040 ] €/kWh     │  │
│  │        Charge when  A ≤ spot ≤ B.  Compared against EPEX spot.         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Discharge policy ─────────────────────────────────────────────────────┐  │
│  │  ( • ) D1  Serve house load when consumption exceeds solar             │  │
│  │  (   ) D2  Maximise discharge when spot price is in band               │  │
│  │  (   ) D3  Both                                                        │  │
│  │                                                                        │  │
│  │        Band C (lower) [ 0.180 ] €/kWh   D (upper) [ 9.999 ] €/kWh      │  │
│  │        [ ] Allow export to grid during D2/D3                           │  │
│  │        [ ] Economic guard: never discharge at a loss                    │  │
│  │                                                                        │  │
│  │  ⚠  Charge band [-0.050, 0.040] and discharge band [0.180, 9.999]      │  │
│  │     do not overlap.  ✓                                                 │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Pricing ──────────────────────────────────────────────────────────────┐  │
│  │  Contract   ( • ) Dynamic   (   ) Dutch fixed   (   ) Dutch variable   │  │
│  │                                                                        │  │
│  │  ┌ Dynamic ──────────────────────────────────────────────────────────┐ │  │
│  │  │  Spot source        ( • ) from mapped sensor  (  ) upload CSV     │ │  │
│  │  │  Supplier markup    [ 0.0205 ] €/kWh   excl. VAT                  │ │  │
│  │  └───────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  │  Energy tax          [ 0.09161 ] €/kWh  excl. VAT     (2026 value)     │  │
│  │  VAT                 [ 21 ] %                                          │  │
│  │                                                                        │  │
│  │  ┌ Feed-in ──────────────────────────────────────────────────────────┐ │  │
│  │  │  Preset  [ Legal minimum (50% of bare price)              ▾ ]     │ │  │
│  │  │  compensation = max(0, α × bare + β)                              │ │  │
│  │  │      α [ 0.50 ]      β [ 0.0000 ] €/kWh                           │ │  │
│  │  │  Terugleverkosten  ( • ) flat  [ 0.0400 ] €/kWh                   │ │  │
│  │  │                    (   ) tiered by annual volume   [ edit tiers ] │ │  │
│  │  │  ⓘ 2027 tariffs are not yet published. Presets are estimates.     │ │  │
│  │  └───────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  │  ┌ Advanced ─────────────────────────────────────────────── [expand] ┐ │  │
│  │  │  Degradation cost  [ 0.0000 ] €/kWh throughput   (0 = disabled)   │ │  │
│  │  │  Day/night window  dal from [ 23:00 ] to [ 07:00 ] + weekends     │ │  │
│  │  │  Fixed costs (vastrecht, systeembeheer, vermindering) — these do  │ │  │
│  │  │  not change with a battery and are excluded from savings.         │ │  │
│  │  └───────────────────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│                              [ ← Back ]          [ Calculate →  ]            │
└──────────────────────────────────────────────────────────────────────────────┘
```

The **Dutch fixed** and **Dutch variable** sub-panels replace the Dynamic sub-panel:

```
  ┌ Dutch fixed ──────────────────────────────────────────────────────────┐
  │  Supply rate normaal (T1)  [ 0.1350 ] €/kWh  excl. tax and VAT        │
  │  Supply rate dal     (T2)  [ 0.1180 ] €/kWh  excl. tax and VAT        │
  │  Contract runs from        [ 2025-01-01 ]  to  [ 2027-01-01 ]         │
  └───────────────────────────────────────────────────────────────────────┘

  ┌ Dutch variable ───────────────────────────────────────────────────────┐
  │  Rate schedule — supplier changes these, typically 1 Jan and 1 Jul.   │
  │                                                                       │
  │    FROM          NORMAAL (T1)   DAL (T2)                              │
  │    2025-01-01    [ 0.1420 ]     [ 0.1240 ]                    [ ✕ ]   │
  │    2025-07-01    [ 0.1310 ]     [ 0.1150 ]                    [ ✕ ]   │
  │    2026-01-01    [ 0.1385 ]     [ 0.1205 ]                    [ ✕ ]   │
  │                                                    [ + add period ]   │
  │  Rates excl. energy tax and VAT.                                      │
  └───────────────────────────────────────────────────────────────────────┘
```

### Without PV

The `[PV only]` markers above are not rendered; those options are **absent**. With
`has_pv = false` the panel changes as follows, and nothing else changes:

```
  ┌─ Charge policy ────────────────────────────────────────────────────────┐
  │  ( • ) P2  Grid charge when spot price is in band                      │
  │                                                                        │
  │        Band A (lower) [ -0.050 ] €/kWh   B (upper) [ 0.040 ] €/kWh     │
  │        Charge when  A ≤ spot ≤ B.  Compared against EPEX spot.         │
  │                                                                        │
  │  ⓘ Without solar there is no surplus to capture, so grid charging is   │
  │    the only way to fill the battery.                                   │
  └────────────────────────────────────────────────────────────────────────┘

  ┌─ Discharge policy ─────────────────────────────────────────────────────┐
  │  ( • ) D1  Serve house load                                            │
  │  (   ) D2  Maximise discharge when spot price is in band               │
  │  (   ) D3  Both                                                        │
  └────────────────────────────────────────────────────────────────────────┘
```

- **Charge policy** collapses to P2 alone, preselected and rendered as a single labelled
  option rather than a one-item radio group. P1 and P3 are hidden: with no solar there is
  no surplus, so P1 would charge nothing and P3 would be P2 under a different name. Showing
  a user a policy that provably does nothing is a defect, not a courtesy.
- **D1 is relabelled** from "Serve house load when consumption exceeds solar" to "Serve
  house load". The behaviour is unchanged — the deficit `max(0, load − pv)` is just the
  whole load when `pv = 0` — but the original label refers to a comparison the user has
  told us does not exist. All three discharge policies remain available and meaningfully
  distinct. Whether D1 should instead be merged with D3 here is
  [open question §8.17](17-open-questions.md).
- **The Installation topology box** loses the PV coupling row and shows only the battery
  phase choice, which on a 1-phase connection empties the box entirely — in that case do
  not render it. See [§2.5](03-topology-selector.md), which specifies the illustrated
  grid-only topology shown in its place.

Field semantics and the formulas behind them: policies in
[11-policies-and-battery.md](11-policies-and-battery.md), pricing in
[10-pricing.md](10-pricing.md), every default value in
[appendix-a-defaults.md](appendix-a-defaults.md). Validation rules that block or warn on
these fields are checks 11–13 in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order).

## 2.4 Panel ③ — Results (expanded)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ③ RESULTS                                                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Period:  [ 1 week ] [ 1 month ] [ 3 months ] [ 6 months ] (•1 year•)        │
│           2025-07-22 → 2026-07-21 · hourly · 8,760 intervals                 │
│                                                       ⟳ recalculating…       │
│                                                                              │
│  ┌───────────────────────┬───────────────────────┬──────────────────────────┐│
│  │ GRID IMPORT SAVED     │ MONEY SAVED           │ EQUIVALENT FULL CYCLES   ││
│  │                       │                       │                          ││
│  │      1,412 kWh        │      € 331            │        241               ││
│  │      −34.2 %          │      −28.7 %          │    0.66 / day            ││
│  │                       │                       │    2,410 kWh throughput  ││
│  └───────────────────────┴───────────────────────┴──────────────────────────┘│
│                                                                              │
│  ┌─ Where the money comes from ───────────────────────────────────────────┐  │
│  │  Avoided grid import                              + € 402              │  │
│  │  Avoided terugleverkosten                         +  €  96             │  │
│  │  Lost feed-in compensation                        −  € 141             │  │
│  │  Standby consumption (263 kWh)                    −  €  62             │  │
│  │  Grid arbitrage export revenue                    +  €  36             │  │
│  │  Degradation cost                                     disabled         │  │
│  │  ─────────────────────────────────────────────────────────────         │  │
│  │  Net saving                                       + € 331              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Benchmarks ───────────────────────────────────────────────────────────┐  │
│  │                                                                        │  │
│  │  No battery          €0        ├────────────────────────────────────┤  │  │
│  │  Your policy         €331      ├──────────────────────●─────────────┤  │  │
│  │  Perfect foresight   €478      ├────────────────────────────────●───┤  │  │
│  │                                                                        │  │
│  │  Your policy captures 69% of the theoretical maximum.                  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Charts ───────────────────────────────────────────── [ ⤓ export CSV ] ┐  │
│  │  ( • ) Monthly savings   (   ) SoC + price   (   ) Energy flows        │  │
│  │                                                                        │  │
│  │   €                                                                    │  │
│  │  60│                        ▄▄  ▄▄  ▄▄                                 │  │
│  │  40│              ▄▄  ▄▄  ██  ██  ██  ▄▄                               │  │
│  │  20│      ▄▄  ▄▄  ██  ██  ██  ██  ██  ██  ▄▄  ▄▄                       │  │
│  │   0│  ▄▄  ██  ██  ██  ██  ██  ██  ██  ██  ██  ██  ▄▄                   │  │
│  │     └───────────────────────────────────────────────────────           │  │
│  │      Aug Sep Oct Nov Dec Jan Feb Mar Apr May Jun Jul                   │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Secondary metrics ────────────────────────────────────────────────────┐  │
│  │  Self-consumption ratio     58% → 81%                                  │  │
│  │  Self-sufficiency ratio     31% → 52%                                  │  │
│  │  Grid export               3,180 → 1,742 kWh                           │  │
│  │  Conversion losses          254 kWh                                    │  │
│  │  Intervals battery was full / empty   1,204 / 2,988                    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Caveats for this run ─────────────────────────────────────────────────┐  │
│  │  ⚠  Simulated at hourly resolution. A 5-minute re-run over the last    │  │
│  │     9 days gives 8.4% lower savings — hourly buckets hide within-hour  │  │
│  │     import/export overlap and flatter the battery. Treat the headline  │  │
│  │     figure as an upper bound.                        [ what is this? ] │  │
│  │  ⚠  0.41% of intervals had negative reconstructed load (clamped to 0). │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

The panel renders the result object in
[§4.5](07-internal-representation.md#45-result-object) field for field; the waterfall box
is `cost.waterfall`, the benchmark bar is `benchmarks`, the caveats box is `warnings`.
The **⤓ export CSV** link serves
[§4.6](07-internal-representation.md#46-per-interval-csv-export).

**Without PV**, three of the rendered figures have no meaning and are omitted rather than
shown as zero:

- **Self-consumption ratio** is `1 − export/pv` and has PV in its denominator. It arrives
  as `null` ([§6.11](12-metrics-and-benchmarks.md#611-metrics)); omit the row. Rendering
  `0%` or `100%` would state something the data cannot support.
- **Grid export** and **Lost feed-in compensation** are structurally zero — a household
  with no generator exports nothing, unless `allow_grid_export` is on and D2/D3 are
  arbitraging, in which case both rows are meaningful and are shown. Test the value, not
  `has_pv`.
- **Avoided terugleverkosten** likewise: zero unless there was export to avoid.

Self-sufficiency (`1 − import/load`) remains well defined and is always shown; without PV
it measures purely what the battery time-shifted. The waterfall stays exact in every case —
lines that evaluate to zero are dropped from the display, never from `cost.waterfall` in
the result JSON, which must continue to close against `cost(A) − cost(C)`.

Short-window guard, shown instead of an annualised figure when the range is under
90 days (see
[§7.4](15-data-quality-and-limits.md#74-window-anchoring-and-short-window-guard)):

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │  ⓘ  Annualised projection is disabled for ranges under 90 days.        │
  │     Battery savings are strongly seasonal; scaling a July week to a    │
  │     year overstates annual savings by a factor of roughly 2–3.         │
  │     Select 6 months or 1 year to see an annual figure.                 │
  └────────────────────────────────────────────────────────────────────────┘
```
