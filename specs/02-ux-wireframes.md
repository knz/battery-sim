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
│  │    10.0 kWh · 5.0/5.0 kW · 90% · charge P3 · discharge P1 · energy only│  │
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

The panel ② summary line ends with the run's cost mode: the contract name
(`dynamic`, `Dutch fixed`, `Dutch variable`) when cost simulation is on, and `energy only`
when it is off. That word is the fastest way for a user to see, from the collapsed state,
which of the two products they are looking at.

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
│  │  Do you have solar PV?      ( • ) Yes    (   ) No                      │  │
│  │  Simulate cost savings?     (   ) Yes    ( • ) No                      │  │
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
│  │  Spot price           ●   [ sensor.epex_spot_price                ▾ ]  │  │
│  │                                                                        │  │
│  │  ● = required.  ○ = optional.                                          │  │
│  │  ◐ = required only if you have solar PV (set in panel ②).              │  │
│  │  Spot price drives the charge and discharge bands, so it is required   │  │
│  │  whether or not you simulate costs.                                    │  │
│  │  Both meter registers should be mapped. See "Tariff registers" below.  │  │
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
│  │  Meter registers    T1 ✓ mapped    T2 ✓ mapped, active                 │  │
│  │                                                                        │  │
│  │  ⚠  T1/T2 register check: 2.1% of intervals disagree with the          │  │
│  │     configured day/night window.                  [ adjust window ]    │  │
│  │                                                                        │  │
│  │  Tariff registers   T1 = normaal (day)   T2 = dal (night)  [ swap ]    │  │
│  │                     auto-detected from when each register increments   │  │
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
of use is ① then ②, both toggles — *do you have solar PV* and *simulate cost savings* — are
mirrored at the head of the series-mapping box as one-line questions, and changing either
in one place changes it in both.

The **Spot price** row is required in both cost modes, because the charge and discharge
bands compare against it regardless of whether anything is converted to euros
([§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model)). It is the one input a
user might expect the cost toggle to remove and it does not.

The data-quality box renders the diagnostics computed at ingest time. Their definitions
live in [14-diagnostics.md](14-diagnostics.md); the ordered list of checks and their
failure actions is in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order). Some of
those checks depend on PV and some on cost simulation; the ones that do not apply are
simply not run, and the box omits them rather than reporting them as passed. The epoch
timeline strip described in
[§6.15](13-configuration-epochs.md#615-configuration-epochs) is rendered above the
coverage summary.

Two rows in that box behave differently under the cost toggle, and the split follows
[§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use):

- **Meter registers** — whether T1 and T2 are both mapped and both accruing — is a
  statement about the meter installation, not about a contract. It is shown always. A
  register that is absent or permanently flat points at an incomplete mapping or an
  incorrect installation and is worth telling the user about whatever they asked to
  simulate.
- **Tariff registers** — which register is dal and which is normaal — and the day/night
  window check below it are shown **only when cost simulation is on**. Which register
  carries which *tariff* matters only to a bill.

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
│  ┌─ What to simulate ─────────────────────────────────────────────────────┐  │
│  │  Energy savings          ✓ always                                      │  │
│  │  [ ] Also simulate cost savings                                        │  │
│  │      ⓘ Needs your contract type, supply rates, energy tax, VAT and     │  │
│  │        feed-in terms. Leave this off to see kWh saved only.            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
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
│  ┌─ Pricing ───────────────────────── [only when simulating costs] ──────┐  │
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
│  ⓘ The whole Pricing box above, Advanced included, is hidden when cost       │
│    simulation is off. Every field in it — contract, rates, tax, VAT,         │
│    feed-in, degradation cost, day/night window — feeds a euro figure only.   │
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

### Without cost simulation

With `simulate_cost = false` — the default — the panel loses everything that exists to
turn kWh into euros, and keeps everything that decides which kWh move:

- **The entire Pricing box is absent**: contract type, all three contract sub-panels, the
  supplier markup, energy tax, VAT, the Feed-in box, and the Advanced box with its
  degradation cost and day/night window. Absent, not greyed — there is nothing here the
  user can usefully look at without opting in.
- **The charge and discharge price bands stay.** `Band A/B` and `Band C/D` are dispatch
  parameters: they decide when the battery charges and discharges, which changes the kWh
  answer. They keep their €/kWh units and stay compared against the bare EPEX spot, because
  that is the signal a real controller would use. See
  [§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model), which sets out why the
  price series and the cost model are separable.
- **The band-overlap warning stays**, for the same reason: overlapping bands make the
  battery fight itself, which is an energy problem before it is a money problem.
- **`Economic guard` is absent.** "Never discharge at a loss" is a statement about
  `p_export_net`, which does not exist without a cost model. It is forced off.
- **The Battery, Grid connection, Solar PV and Installation topology boxes are unchanged.**
  All four describe physical hardware.

Everything else about the panel — validation, the Calculate button, the collapsed summary —
behaves identically; only the summary's final clause reads `energy only`.

Field semantics and the formulas behind them: policies in
[11-policies-and-battery.md](11-policies-and-battery.md), pricing in
[10-pricing.md](10-pricing.md), every default value in
[appendix-a-defaults.md](appendix-a-defaults.md). Validation rules that block or warn on
these fields are checks 11–13 in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order).

## 2.4 Panel ③ — Results (expanded)

The panel is organised into two clearly separated result sections. **Energy savings** are
always present. **Cost savings** are a distinct section below them, rendered only when
`simulate_cost` is on. The separation is structural, not cosmetic: the two rest on
different inputs and carry different confidence, and interleaving kWh and euro figures — as
an earlier draft of this panel did — invited users to read a euro figure as being as
well-grounded as the kWh figure beside it. It is not: the kWh figure comes from measured
data, the euro figure from that data plus a contract model assembled from unpublished 2027
tariffs.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ③ RESULTS                                                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Period:  [ 1 week ] [ 1 month ] [ 3 months ] [ 6 months ] (•1 year•)        │
│           2025-07-22 → 2026-07-21 · hourly · 8,760 intervals                 │
│                                                       ⟳ recalculating…       │
│                                                                              │
│  ═══ ENERGY SAVINGS ═════════════════════════════════════════════════════    │
│                                                                              │
│  ┌───────────────────────┬───────────────────────┬──────────────────────────┐│
│  │ GRID IMPORT SAVED     │ SELF-SUFFICIENCY      │ EQUIVALENT FULL CYCLES   ││
│  │                       │                       │                          ││
│  │      1,412 kWh        │    31% → 52%          │        241               ││
│  │      −34.2 %          │      +21 pp           │    0.66 / day            ││
│  │                       │                       │    2,410 kWh throughput  ││
│  └───────────────────────┴───────────────────────┴──────────────────────────┘│
│                                                                              │
│  ┌─ Where the energy comes from ──────────────────────────────────────────┐  │
│  │  Grid import, no battery                        4,129 kWh              │  │
│  │  Grid import, with battery                      2,717 kWh              │  │
│  │  ─────────────────────────────────────────────────────────────         │  │
│  │  Grid import avoided                            1,412 kWh              │  │
│  │                                                                        │  │
│  │  Charged into the battery                       2,664 kWh              │  │
│  │  Discharged from the battery                    2,410 kWh              │  │
│  │  Conversion losses                                254 kWh              │  │
│  │  Standby consumption                              263 kWh              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Benchmark: grid import avoided ───────────────────────────────────────┐  │
│  │                                                                        │  │
│  │  No battery            0 kWh   ├────────────────────────────────────┤  │  │
│  │  Your policy       1,412 kWh   ├──────────────────────●─────────────┤  │  │
│  │  Perfect foresight 1,988 kWh   ├────────────────────────────────●───┤  │  │
│  │                                                                        │  │
│  │  Your policy captures 71% of the grid import a perfectly-informed      │  │
│  │  battery could have avoided.                                           │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Secondary metrics ────────────────────────────────────────────────────┐  │
│  │  Self-consumption ratio     58% → 81%                                  │  │
│  │  Grid export               3,180 → 1,742 kWh                           │  │
│  │  Intervals battery was full / empty   1,204 / 2,988                    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ═══ COST SAVINGS ═══════════════════ [only when simulating costs] ══════    │
│                                                                              │
│  ┌───────────────────────┬──────────────────────────────────────────────────┐│
│  │ MONEY SAVED           │  € 1,153 without a battery → € 822 with one      ││
│  │                       │                                                  ││
│  │      € 331            │  Priced under the 2027 regime from the contract  ││
│  │      −28.7 %          │  you entered. See the caveats below.             ││
│  └───────────────────────┴──────────────────────────────────────────────────┘│
│                                                                              │
│  ┌─ Benchmark: money saved ───────────────────────────────────────────────┐  │
│  │                                                                        │  │
│  │  No battery            € 0     ├────────────────────────────────────┤  │  │
│  │  Your policy           € 331   ├─────────────────────●──────────────┤  │  │
│  │  Perfect foresight     € 478   ├────────────────────────────────●───┤  │  │
│  │                                                                        │  │
│  │  Your policy captures 69% of the money a perfectly-informed battery    │  │
│  │  could have saved. A different ceiling from the energy benchmark, and  │  │
│  │  a different dispatch behind it: buying cheaply is not the same as     │  │
│  │  importing little.                                    [ what is this? ]│  │
│  └────────────────────────────────────────────────────────────────────────┘  │
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
│  ┌─ Charts ───────────────────────────────────────────── [ ⤓ export CSV ] ┐  │
│  │  ( • ) Monthly savings   (   ) SoC + price   (   ) Energy flows        │  │
│  │                                                                        │  │
│  │   kWh                                                                  │  │
│  │ 200│                        ▄▄  ▄▄  ▄▄                                 │  │
│  │ 150│              ▄▄  ▄▄  ██  ██  ██  ▄▄                               │  │
│  │ 100│      ▄▄  ▄▄  ██  ██  ██  ██  ██  ██  ▄▄  ▄▄                       │  │
│  │   0│  ▄▄  ██  ██  ██  ██  ██  ██  ██  ██  ██  ██  ▄▄                   │  │
│  │     └───────────────────────────────────────────────────────           │  │
│  │      Aug Sep Oct Nov Dec Jan Feb Mar Apr May Jun Jul                   │  │
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
[§4.5](07-internal-representation.md#45-result-object) field for field; the energy
breakdown box is `energy`, the money waterfall is `cost.waterfall`, the two benchmark boxes
are `benchmarks.energy` and `benchmarks.cost`, the caveats box is `warnings`. The
**⤓ export CSV** link serves
[§4.6](07-internal-representation.md#46-per-interval-csv-export).

Notes on the two sections:

- **Enabling cost simulation adds the second section and changes nothing in the first.**
  Every figure above the `COST SAVINGS` divider — the three KPI tiles, the energy breakdown,
  the energy benchmark and its capture ratio, the secondary metrics, the kWh caveats — is
  identical to what an energy-only run shows over the same data. A user who ticks the box
  should see their kWh numbers stay exactly where they were, because a question about money
  is not a question about kilowatt-hours.
- **Each benchmark is optimised for its own quantity.** The energy box is bounded by a
  perfect-foresight run that minimises grid import; the money box by one that minimises
  euros ([§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)). The two
  ceilings come from genuinely different dispatches and the two capture ratios will differ,
  usually by a few points. That is information, not an inconsistency, and the money box says
  so in one line: a battery that buys cheaply imports more, not less.
- **The Charts box gains options rather than swapping them.** *Monthly savings* always
  offers kWh and shows it by default; with cost simulation on it gains a *Monthly savings
  (€)* option beside it. The two are separate views, not a dual axis — a euro series moves
  with tariff structure as well as with kWh, and overlaying them invites exactly the
  reading this panel's two-section split exists to prevent. *SoC + price* keeps the bare
  spot price on its secondary axis in both modes, since the spot series is present either
  way. *Energy flows* is unaffected.
- **Caveats are shown in both modes**, with the kWh ones identical across the toggle. The
  caveats that qualify a euro figure — price bracketing, the feed-in floor, tiered
  terugleverkosten — appear only with cost simulation on, because there is no euro figure to
  qualify. The resolution-bias caveat is stated in kWh in both modes and gains its euro
  percentage as a second sentence when costs are modelled
  ([§6.13](14-diagnostics.md#613-resolution-bias-diagnostic)).

### Panel ③ without cost simulation

The `COST SAVINGS` section and everything in it is absent — the money KPI tile, the money
waterfall, the money benchmark. The `ENERGY SAVINGS` section is **identical**, figure for
figure, to what the same data produces with cost simulation on, and the panel is complete
without the second half rather than looking truncated. Two smaller consequences:

- The `MONEY SAVED` tile is not replaced by a placeholder or a zero. A blank where a
  headline number would go reads as a failed calculation; an absent section reads as a
  choice the user made, which is what it is.
- A short affordance sits at the foot of the energy section: *"Want to know what this is
  worth in euros? [ Enable cost simulation ]"*, linking back to the panel ② toggle. Since
  the toggle defaults off, some users will otherwise never discover that the app can do
  this at all.

### Panel ③ without PV

Three of the rendered figures have no meaning and are omitted rather than shown as zero:

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
