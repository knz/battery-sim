# Home Battery Simulator — Specification Package

**Version:** 1.1 (draft for implementation)
**Date:** 2026-07-22
**Status:** Ready for implementer hand-off. Open questions are collected in §8.

**Changes in 1.1:** configuration epochs for mid-window PV/battery installation (§6.15);
installation topology selector with diagrams (§2.5); use of HA statistics
min/max/mean for price bracketing (§6.16) and timestamp-misalignment detection (§6.17);
corrected conversion-loss formula (§6.11); overlap diagnostic reinterpreted in light of
smart-meter phase netting (§7.1).

---

## 0. Reading guide

| § | Section | Primary audience |
|---|---------|------------------|
| 1 | Product brief | Everyone |
| 2 | UX wireframes | Frontend |
| 3 | Application state machine | Frontend + backend |
| 4 | Input / output formats | Backend, integrators |
| 5 | Software architecture | Backend |
| 6 | Algorithms and formulas | Backend (domain layer) |
| 7 | Data quality, validation, red-team notes | Everyone |
| 8 | Open questions | Product owner |

Conventions used throughout:

- All energy in **kWh**, all power in **kW**, all money in **EUR**.
- All timestamps stored and computed in **UTC**; displayed in **Europe/Amsterdam**.
- `dt` = interval duration in hours (0.0833 for 5 min, 0.25 for 15 min, 1.0 for hourly).
- Sign convention: energy flows are **non-negative magnitudes** in named directions
  (`import`, `export`, `charge`, `discharge`). No signed net flows in the domain model —
  this has repeatedly been a source of bugs in comparable tools.

---

## 1. Product brief

### 1.1 Purpose

A locally-run web application that answers one question with the household's own
historical data:

> *If I had owned a home battery over this period, operated under this policy, how much
> grid electricity and how much money would I have saved?*

It is a **retrospective counterfactual simulator**, not a forecaster and not a controller.

### 1.2 Target user

A technically literate Dutch homeowner who runs Home Assistant, has solar PV, and is
evaluating a battery purchase (or evaluating operating strategies for one they own).
They can obtain an HA long-lived access token or export CSVs. They are assumed to be
comfortable entering numeric parameters but **not** assumed to know Dutch energy tax
structure.

### 1.3 Regulatory regime — fixed decision

The simulator models the **post-1-January-2027 Dutch regime**:

- The salderingsregeling (net metering) is abolished for all contract types.
- Every imported kWh is charged at the full import price; every exported kWh earns a
  feed-in compensation. **There is no netting**, for dynamic, fixed or variable contracts.
- Feed-in compensation must be at least 50% of the bare supply price (excl. VAT and
  energy tax) until 1 January 2030, and may not be negative.
- Feed-in *charges* (terugleverkosten) may be levied on top and, from 2027, must be
  expressed as a flat amount per fed-in kWh. The net of compensation minus charges
  **can** be negative.

The pre-2027 salderen regime is explicitly **out of scope for v1** but the pricing engine
must not structurally preclude it (see §6.7 note).

### 1.4 In scope (v1)

- Two data ingestion paths: direct Home Assistant access, and standardised CSV upload.
- Reconstruction of the battery-free household load, including stripping out an
  already-installed battery if its sensors are provided.
- Mixed-resolution input data, normalised onto a single uniform simulation grid.
- Three charge policies, three discharge policies, freely combinable.
- Three pricing models: dynamic (spot-based), Dutch fixed, Dutch variable.
- Predefined time ranges: last week / month / 3 months / 6 months / year.
- Results: energy saved (kWh and %), money saved (EUR), equivalent full cycles,
  self-consumption and self-sufficiency ratios, plus time-series and monthly breakdowns.
- Two reference baselines so the headline number is interpretable:
  **no battery** (the counterfactual floor) and **perfect foresight** (the ceiling).
- Server-side persistence of raw data, parameters and selected range, restored on restart.
- **Configuration epochs**: detection of PV or battery commissioning part-way through the
  window, with the analysis made aware of it rather than silently averaging across it.
- **Installation topology** selection (PV coupling, battery phase configuration) via
  illustrated choices, since users reliably recognise a picture of their meter cupboard
  and reliably mis-answer the same question asked in words.
- **Price uncertainty bracketing** where the supplier settles per 15 minutes but the
  available energy data is hourly.

### 1.5 Explicitly out of scope (v1)

- Gas. Electricity only.
- Real-time or forward-looking optimisation; no scheduling output.
- Battery control or write-back to Home Assistant.
- Multi-site / multi-connection households.
- Investment appraisal (payback period, NPV, IRR). The app reports annualised savings;
  capital cost modelling is deferred.
- Authentication and multi-tenancy. See §5.5 — the architecture must *permit* it, v1 does
  not *implement* it.

### 1.6 Success criteria

1. A user with a working HA instance can go from cold start to a result in under five
   minutes without reading documentation.
2. Changing any parameter updates results automatically without a page reload.
3. Restarting the server preserves all user state.
4. The application refuses to produce misleading numbers: it surfaces data quality
   problems prominently and blocks annualised extrapolation from short windows (§7.4).
5. Every headline figure can be traced to its inputs via an exportable per-interval CSV.

### 1.7 Design principles

- **Honest over impressive.** Where a modelling choice flatters the battery, the app says
  so. The resolution-bias diagnostic (§6.11) exists for exactly this reason.
- **Literal policies.** Policies do what the user configured, even when uneconomic. The
  simulator reports the outcome rather than quietly overriding the configuration. An
  optional economic guard exists but defaults **off**.
- **No invented data.** Energy series are never upsampled to a finer resolution than they
  were recorded at.
- **Everything overridable.** Defaults are sensible; nothing is hard-coded beyond override.

---

## 2. UX wireframes

### 2.1 Overall layout

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

### 2.2 Panel ① — Data input (expanded)

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
│  │  Solar production     ●   [ sensor.solar_total_production         ▾ ]  │  │
│  │  Battery charge       ○   [ — none —                              ▾ ]  │  │
│  │  Battery discharge    ○   [ — none —                              ▾ ]  │  │
│  │  Spot price           ○   [ sensor.epex_spot_price                ▾ ]  │  │
│  │                                                                        │  │
│  │  ○ = optional.  Spot price required only for dynamic pricing.          │  │
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

### 2.3 Panel ② — Parameter configuration (expanded)

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
│  ┌─ Installation topology ────────────────────────────── [see §2.5] ─────┐  │
│  │  PV coupling      ( • ) DC-coupled / hybrid   (   ) AC-coupled         │  │
│  │  Battery phases   ( • ) 3-phase inverter      (shown for 3-phase only) │  │
│  │  Both are chosen from illustrated options, not from these labels.      │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Charge policy ────────────────────────────────────────────────────────┐  │
│  │  (   ) P1  Solar surplus only (net zero at the grid)                   │  │
│  │  (   ) P2  Grid charge when spot price is in band                      │  │
│  │  ( • ) P3  Both                                                        │  │
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

### 2.4 Panel ③ — Results (expanded)

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

Short-window guard, shown instead of an annualised figure when the range is under
90 days:

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │  ⓘ  Annualised projection is disabled for ranges under 90 days.        │
  │     Battery savings are strongly seasonal; scaling a July week to a    │
  │     year overstates annual savings by a factor of roughly 2–3.         │
  │     Select 6 months or 1 year to see an annual figure.                 │
  └────────────────────────────────────────────────────────────────────────┘
```

### 2.5 Topology selector detail

Both selectors are **illustrated radio groups**, not dropdowns. Users recognise a picture
of their own meter cupboard far more reliably than they answer the equivalent question in
words, and both of these settings materially change the numbers.

**(a) PV coupling** — always shown.

```
  How is your PV connected to the battery?

  ┌───────────────────────────────┐   ┌───────────────────────────────┐
  │ ( • ) DC-coupled / hybrid     │   │ (   ) AC-coupled              │
  │                               │   │                               │
  │   ┌────┐   DC   ┌──────────┐  │   │  ┌────┐    ┌─────┐            │
  │   │ PV │───────►│ hybrid   │  │   │  │ PV │───►│ PV  │───┐        │
  │   └────┘        │ inverter │  │   │  └────┘    │ inv │   │        │
  │                 │  ┌─────┐ │  │   │            └─────┘   ▼        │
  │                 │  │ BAT │ │  │   │                    ══╪══ AC   │
  │                 │  └─────┘ │  │   │  ┌────┐    ┌─────┐   │        │
  │                 └────┬─────┘  │   │  │ BAT│───►│batt │───┘        │
  │                   AC │        │   │  └────┘    │ inv │   │        │
  │                   ═══╪═══     │   │            └─────┘   │        │
  │                grid ─┴─ load  │   │        grid ─────────┴─ load  │
  │                               │   │                               │
  │  One conversion PV→battery    │   │  Two conversions PV→battery   │
  └───────────────────────────────┘   └───────────────────────────────┘

  DC-coupled skips an inversion on the solar charging path — typically
  +3 to +5 percentage points on that path only. Grid charging is
  unaffected. Set the bonus under Advanced if your installer gave you
  separate figures.
```

**(b) Battery phase configuration** — rendered only when *Grid connection → 3-phase* is
selected. On a 1-phase connection there is nothing to choose.

```
  How is your battery connected across the phases?

  ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
  │ (   ) 1-phase      │ │ ( • ) 3-phase      │ │ (   ) 3 × 1-phase  │
  │       battery      │ │       inverter     │ │       batteries    │
  │                    │ │                    │ │                    │
  │  L1 ══╤══──[ BAT ] │ │  L1 ══╤══──┐       │ │  L1 ══╤══──[ BAT ] │
  │  L2 ══╪══          │ │  L2 ══╪══──┼─[BAT] │ │  L2 ══╪══──[ BAT ] │
  │  L3 ══╪══          │ │  L3 ══╪══──┘       │ │  L3 ══╪══──[ BAT ] │
  │                    │ │                    │ │                    │
  │   ⚠ not in v1      │ │   ✓ supported      │ │   ⚠ not in v1      │
  └────────────────────┘ └────────────────────┘ └────────────────────┘
```

Selecting either unsupported option reveals:

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  ⚠  This topology is not fully supported in version 1.               │
  │                                                                      │
  │     Your smart meter nets across phases, so the *financial* result   │
  │     would be close to the 3-phase case. What we cannot model without │
  │     per-phase data is the per-phase power limit — a 1-phase battery  │
  │     cannot exceed one phase's fuse rating no matter how the load is  │
  │     distributed.                                                     │
  │                                                                      │
  │     Please email setups@<domain> describing your setup — inverter    │
  │     model, phase allocation, and whether you have per-phase sensors. │
  │     It directly determines whether this lands in version 2.          │
  │                                                                      │
  │  [ Continue with a 3-phase approximation ]        [ Email us ]       │
  └──────────────────────────────────────────────────────────────────────┘
```

**Soft, not hard, block.** Given phase netting, refusing to compute anything would deny
the user a number that is probably accurate to within a few percent. Continuing sets
`topology_approximated = true`, which propagates into the result JSON and pins a
persistent caveat to the results panel. See open question §8.9.

Asset requirements for the implementer: four inline SVGs, 240 × 160 viewBox, single
`currentColor` stroke at 2 px, no fills, no external fonts or dependencies. Selected
state indicated by border and background, never by colour alone. Each `<svg>` carries a
`role="img"` and an `aria-label` repeating the full text description, and each option
keeps a visible text label — the diagram supplements the label, it does not replace it.

---

## 3. Application state machine

### 3.1 Session-level states

```
                         ┌──────────────┐
        app start ──────►│    EMPTY     │  no data, no params
                         └──────┬───────┘
                                │ SOURCE_CONFIGURED
                                ▼
                         ┌──────────────┐
              ┌─────────►│ DATA_LOADING │◄────── RELOAD_DATA
              │          └──────┬───────┘
              │                 │
              │        ┌────────┴────────┐
              │        │                 │
              │  LOAD_FAILED        LOAD_SUCCEEDED
              │        │                 │
              │        ▼                 ▼
              │  ┌───────────┐    ┌─────────────┐
              └──┤ DATA_ERROR│    │ DATA_READY  │
                 └───────────┘    └──────┬──────┘
                                         │ PARAMS_VALID
                                         ▼
                                  ┌─────────────┐
                                  │PARAMS_READY │
                                  └──────┬──────┘
                                         │ RUN_REQUESTED
                                         ▼
                         ┌───────────────────────────┐
             ┌──────────►│        SIMULATING         │
             │           └─────────────┬─────────────┘
             │                         │
             │              ┌──────────┴──────────┐
             │         RUN_FAILED            RUN_COMPLETED
             │              │                     │
             │              ▼                     ▼
             │        ┌───────────┐        ┌─────────────┐
             │        │ RUN_ERROR │        │RESULTS_FRESH│
             │        └─────┬─────┘        └──────┬──────┘
             │              │                     │
             │              │              INPUT_CHANGED
             │              │                     ▼
             │              │              ┌─────────────┐
             └──────────────┴──────────────┤RESULTS_STALE│
                        DEBOUNCE_ELAPSED   └─────────────┘
                                            (old results still
                                             displayed, dimmed)
```

**Key behaviour:** `RESULTS_STALE` continues to render the previous results, visually
dimmed, with a spinner. It never blanks the panel. This is what makes continuous
re-parameterisation feel responsive.

### 3.2 Events

| Event | Trigger | Effect |
|---|---|---|
| `SOURCE_CONFIGURED` | HA credentials tested OK, or ≥1 CSV parsed | → `DATA_LOADING` |
| `LOAD_SUCCEEDED` | Ingest + normalise + QA complete | → `DATA_READY`, persist dataset |
| `LOAD_FAILED` | Network, auth, parse or validation error | → `DATA_ERROR` with actionable message |
| `PARAMS_CHANGED` | Any field in panel ② | Validate; persist; if valid → `INPUT_CHANGED` |
| `RANGE_CHANGED` | Period selector in panel ③ | Persist; → `INPUT_CHANGED` |
| `INPUT_CHANGED` | From `PARAMS_CHANGED` / `RANGE_CHANGED` / `LOAD_SUCCEEDED` | → `RESULTS_STALE`, start debounce timer |
| `DEBOUNCE_ELAPSED` | 400 ms after last `INPUT_CHANGED` | → `SIMULATING`, enqueue run |
| `RUN_REQUESTED` | Explicit **Calculate** button | Bypass debounce → `SIMULATING` |
| `RUN_COMPLETED` | Worker finishes, `run_id` is current | → `RESULTS_FRESH` |
| `RUN_SUPERSEDED` | Worker finishes, `run_id` is stale | Discard result silently, no state change |
| `RUN_FAILED` | Exception in domain layer | → `RUN_ERROR`, previous results retained |
| `RELOAD_DATA` | User edits panel ① | → `DATA_LOADING` |

### 3.3 Concurrency and run identity

A monotonically increasing `run_id` per workspace guards against out-of-order results:

```
on INPUT_CHANGED:
    session.run_id += 1
    cancel_pending_debounce()
    schedule_debounce(400ms, run_id=session.run_id)

on DEBOUNCE_ELAPSED(run_id):
    if run_id != session.run_id: return          # superseded during debounce
    request_cancel(in_flight_run)                # cooperative, checked per chunk
    enqueue_simulation(run_id)

on worker finishes(run_id, result):
    if run_id != session.run_id:
        emit RUN_SUPERSEDED
    else:
        cache[run_id] = result
        emit RUN_COMPLETED
```

Results are pushed to the browser over **SSE** on `/api/stream`. HTMX swaps the results
fragment. Polling every 750 ms is an acceptable fallback if SSE proves troublesome behind
a reverse proxy.

### 3.4 Panel focus model

Panels are independent of session state; they have their own UI state:
`COLLAPSED_INCOMPLETE`, `EXPANDED`, `COLLAPSED_COMPLETE`. The CTA in panel *n* collapses
panel *n* and expands panel *n+1*. Panel ③ auto-expands on first `RUN_COMPLETED`.
Reopening panel ① or ② does **not** collapse panel ③ — the user must be able to watch
results change while editing parameters. This is the single most important interaction
detail in the app.

### 3.5 Persistence points

State is written to disk on: `LOAD_SUCCEEDED` (dataset), `PARAMS_CHANGED` (debounced
1 s), `RANGE_CHANGED`, and `RUN_COMPLETED` (result cache, last N=5 runs). On startup the
server restores the most recent workspace and lands the user in `RESULTS_STALE`, then
immediately recalculates.

---

## 4. Input and output formats

### 4.1 Canonical CSV — long format (preferred)

Long format is canonical because series legitimately arrive at **different resolutions**
(hourly meter data, 15-minute prices, 5-minute recent HA data). A wide format would force
a common grid at ingestion time, which is precisely the wrong place to make that decision.

```csv
timestamp,series,value,unit,kind
2026-01-01T00:00:00+01:00,grid_import_t1,14203.412,kWh,cumulative
2026-01-01T00:00:00+01:00,grid_import_t2,9821.005,kWh,cumulative
2026-01-01T00:00:00+01:00,solar_production,7734.220,kWh,cumulative
2026-01-01T00:00:00+01:00,price_spot,0.0412,EUR/kWh,price
2026-01-01T01:00:00+01:00,grid_import_t1,14203.911,kWh,cumulative
```

**Column rules**

| Column | Type | Rules |
|---|---|---|
| `timestamp` | ISO 8601 | **Offset or `Z` is mandatory.** Naive timestamps are rejected — during the October DST transition a naive local timestamp is genuinely ambiguous and silently corrupts an hour of data every year. |
| `series` | enum | See below. Unknown values rejected with the list of valid names. |
| `value` | float | `.` decimal separator. Empty or `NaN` treated as a gap, not as zero. |
| `unit` | enum | `kWh`, `Wh`, `MWh`, `EUR/kWh`, `EURcent/kWh`, `EUR/MWh`. Converted on ingest. |
| `kind` | enum | `cumulative`, `delta`, `price`. |

**Series names**

| Series | Required | Kind | Notes |
|---|---|---|---|
| `grid_import_t1` | yes¹ | cumulative/delta | Normaal or dal — see §6.4 |
| `grid_import_t2` | no | cumulative/delta | Omit if the meter has a single register |
| `grid_export_t1` | yes¹ | cumulative/delta | |
| `grid_export_t2` | no | cumulative/delta | |
| `solar_production` | yes | cumulative/delta | AC output of the PV inverter |
| `battery_charge` | no | cumulative/delta | **AC-side.** See §7.2 |
| `battery_discharge` | no | cumulative/delta | **AC-side.** |
| `price_spot` | conditional | price | Required for dynamic pricing. Bare EPEX, excl. markup, tax and VAT |
| `price_spot_min` | no | price | Intra-interval minimum. Enables §6.16 bracketing |
| `price_spot_max` | no | price | Intra-interval maximum. Enables §6.16 bracketing |
| `power_grid` | no | power | Signed W, import positive. Enables §6.17 checks |
| `house_load` | no | cumulative/delta | If supplied, overrides reconstruction (§6.3) and enables a consistency check |

¹ `grid_import`/`grid_export` are accepted as aliases for the `_t1` variants when the
meter is not split.

**Semantics of `kind`**

- `cumulative` — monotonically increasing meter register. The value at time *t* is the
  reading *at* *t*. Deltas are derived by differencing (§6.1).
- `delta` — energy consumed **during the interval starting at** `timestamp`. The interval
  length is inferred from the spacing to the next row of the same series.
- `price` — the price **valid from** `timestamp` until the next row of that series.

Mixing `cumulative` and `delta` across different series is allowed. Mixing them *within*
one series is rejected.

### 4.2 Wide format (convenience)

Accepted when every column shares one timestamp grid. Column headers are series names;
a `kind` is inferred per column (monotonic non-decreasing → `cumulative`, else `delta`)
with the inference reported back to the user for confirmation.

```csv
timestamp,grid_import_t1,grid_export_t1,solar_production,price_spot
2026-01-01T00:00:00+01:00,14203.412,2201.100,7734.220,0.0412
```

### 4.3 Home Assistant ingestion

Use the **WebSocket API**, endpoint `recorder/statistics_during_period`, not the REST
history endpoint. Rationale:

- It returns the `sum` column of long-term statistics, which is already **corrected for
  meter resets** by HA's own `total_increasing` handling. Re-deriving this from raw states
  is a well-known source of spurious multi-thousand-kWh spikes.
- Long-term statistics are hourly and **never purged**; `states` and
  `statistics_short_term` default to ~10 days retention. For any window beyond ~10 days
  the REST history endpoint has nothing to offer and is dramatically heavier.

```
GET  /api/                              → connectivity + version check
WS   /api/websocket                     → auth with long-lived access token
     {type: "recorder/list_statistic_ids", statistic_type: "sum"}
     {type: "recorder/statistics_during_period",
      start_time, end_time, statistic_ids: [...],
      period: "5minute" | "hour" | "day"}
```

Fetch strategy: request `period: "hour"` for the full window, then additionally request
`period: "5minute"` for the trailing 10 days. Store both; the simulation grid selector
(§6.2) decides which gets used. The 5-minute copy exists to power the resolution-bias
diagnostic even when the main run is hourly.

Chunk requests to ≤ 90 days per call to avoid oversized WebSocket frames on large
instances.

**Which statistics columns actually exist — this is not uniform.** HA computes different
aggregates depending on the sensor's `state_class`:

| `state_class` | Columns stored | Typical sensors |
|---|---|---|
| `total` / `total_increasing` | `sum`, `state`, `last_reset` | Grid import/export, solar production, battery charge/discharge |
| `measurement` | `mean`, `min`, `max` | Spot price, power (W), voltage, SoC (%) |

The consequence is important and slightly counter-intuitive: **the energy meters have no
min/max/mean.** An hourly row for `sensor.grid_import` carries only the hourly total.
There is no intra-hour information to recover from it.

Where min/max/mean *are* available and useful:

- **Spot price sensors** are `measurement`, so an hourly row retains the min, max and mean
  of the underlying 15-minute prices. This supports the bracketing in §6.16.
- **Power sensors**, if the user has them, retain hourly min/max/mean power. These enable
  the consistency and misalignment checks in §6.17 and reveal inverter clipping.
- **Battery SoC sensors** (%) retain min/max/mean, which gives a cheap sanity check
  against a simulated SoC trace when the user already owns a battery.

Request `price_spot` and any power sensors with all of `mean`, `min`, `max`; request
energy sensors with `sum` only.

### 4.4 Internal normalised representation

After ingest, every series becomes a `SeriesFrame`:

```python
SeriesFrame:
    name:            str
    kind:            Literal["energy", "price"]
    resolution_s:    int | None       # None if irregular
    index:           DatetimeIndex    # UTC, interval START, left-closed
    values:          np.ndarray       # energy: kWh in interval; price: EUR/kWh valid from
    quality:         QualityFlags     # per-interval bitfield
```

`QualityFlags` bits: `OK`, `GAP_FILLED`, `RESET_CORRECTED`, `INTERPOLATED`,
`RESAMPLED_DOWN`, `CLAMPED_NEGATIVE`.

The simulation consumes a single `SimulationFrame` — all series on one uniform grid:

```python
SimulationFrame:
    index:      DatetimeIndex      # UTC, uniform, interval start
    dt_hours:   float
    pv:         ndarray            # kWh
    load:       ndarray            # kWh, battery-free, standby-free
    spot:       ndarray            # EUR/kWh, bare (mean within interval)
    spot_min:   ndarray | None     # EUR/kWh, intra-interval min (§6.16)
    spot_max:   ndarray | None     # EUR/kWh, intra-interval max (§6.16)
    epoch_id:   ndarray[uint8]     # configuration epoch index (§6.15)
    import_obs: ndarray            # kWh, as measured (for validation only)
    export_obs: ndarray            # kWh, as measured (for validation only)
    tariff_zone: ndarray[uint8]    # 0 = normaal, 1 = dal
    quality:    ndarray[uint16]
```

### 4.5 Result object

```jsonc
{
  "run_id": 47,
  "generated_at": "2026-07-22T09:14:02Z",
  "window": { "start": "2025-07-22T00:00:00Z", "end": "2026-07-21T23:00:00Z",
              "intervals": 8760, "dt_hours": 1.0, "resolution": "hour" },
  "config_hash": "sha256:9f2c…",

  "energy": {
    "baseline":  { "import_kwh": 4129.4, "export_kwh": 3180.2 },
    "battery":   { "import_kwh": 2717.1, "export_kwh": 1742.0 },
    "saved_kwh": 1412.3, "saved_pct": 34.2,
    "pv_kwh": 5210.0, "load_kwh": 6120.4,
    "charge_ac_kwh": 2664.0, "discharge_ac_kwh": 2410.0,
    "conversion_loss_kwh": 254.0, "standby_kwh": 262.8,
    "curtailed_kwh": 0.0
  },

  "cost": {
    "currency": "EUR",
    "baseline_eur": 1153.20,
    "battery_eur":  822.10,
    "saved_eur":    331.10,
    "saved_pct":    28.7,
    "waterfall": [
      { "label": "avoided_grid_import",       "eur":  402.10 },
      { "label": "added_grid_import_charging","eur":  -62.00 },
      { "label": "avoided_terugleverkosten",  "eur":   96.40 },
      { "label": "lost_feedin_compensation",  "eur": -141.30 },
      { "label": "arbitrage_export_revenue",  "eur":   36.00 },
      { "label": "standby_consumption",       "eur":  -62.00 },
      { "label": "degradation",               "eur":    0.00, "enabled": false }
    ]
  },

  "battery": {
    "equivalent_full_cycles": 241.0,
    "cycles_per_day": 0.66,
    "throughput_kwh": 2410.0,
    "soc_start_kwh": 5.0, "soc_end_kwh": 4.2,
    "soc_delta_value_eur": -0.19,
    "intervals_at_max_soc": 1204, "intervals_at_min_soc": 2988
  },

  "ratios": {
    "self_consumption_baseline": 0.58, "self_consumption_battery": 0.81,
    "self_sufficiency_baseline": 0.31, "self_sufficiency_battery": 0.52
  },

  "benchmarks": {
    "no_battery_eur": 0.0,
    "policy_eur": 331.10,
    "perfect_foresight_eur": 478.30,
    "capture_ratio": 0.692
  },

  "epochs": [
    { "id": 0, "start": "2025-07-22", "end": "2025-09-14",
      "has_pv": false, "has_battery": false, "detected": true, "confirmed_by_user": true },
    { "id": 1, "start": "2025-09-15", "end": "2026-07-21",
      "has_pv": true,  "has_battery": false, "detected": true, "confirmed_by_user": true }
  ],
  "epoch_used": 1,
  "spans_epoch_boundary": false,

  "price_bracket": {
    "applicable": true,
    "settlement": "quarter_hourly",
    "saved_eur_low": 298.40, "saved_eur_central": 331.10, "saved_eur_high": 366.80,
    "intra_hour_spread_mean_eur_kwh": 0.021
  },

  "topology": {
    "pv_coupling": "dc_hybrid",
    "battery_phases": "three_phase",
    "approximated": false
  },

  "diagnostics": {
    "overlap_kwh": 61.2, "overlap_pct": 1.5,
    "time_offset_s": 0, "time_offset_confidence": 0.94,
    "power_energy_residual_pct": 0.8,
    "resolution_bias_pct": 8.4,
    "resolution_bias_basis": "9 days at 5-minute vs hourly",
    "negative_load_intervals": 41, "negative_load_pct": 0.41,
    "gaps_filled_hours": 4.2,
    "counter_resets": 2,
    "tariff_zone_mismatch_pct": 2.1,
    "annualisation_allowed": true
  },

  "monthly": [ { "month": "2025-08", "saved_kwh": 88.2, "saved_eur": 21.4,
                 "cycles": 18.1 } ],

  "warnings": [
    { "code": "RESOLUTION_BIAS_HIGH", "severity": "warn",
      "message": "Hourly simulation overstates savings by ~8.4%." }
  ]
}
```

### 4.6 Per-interval CSV export

Every headline figure must be traceable. The export contains one row per simulation
interval:

```csv
timestamp_utc,timestamp_local,dt_h,pv_kwh,load_kwh,spot_eur_kwh,
p_import_eur_kwh,p_export_net_eur_kwh,tariff_zone,
base_import_kwh,base_export_kwh,
charge_ac_kwh,charge_from_pv_kwh,charge_from_grid_kwh,
discharge_ac_kwh,discharge_to_home_kwh,discharge_to_grid_kwh,
soc_kwh,batt_import_kwh,batt_export_kwh,
base_cost_eur,batt_cost_eur,quality_flags
```

---

## 5. Software architecture

### 5.1 Diagram

```
┌───────────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                                  │
│  Jinja2-rendered HTML · HTMX (fragment swaps) · Plotly (chart JSON)       │
│  No build step, no SPA framework, no client-side computation.             │
└───────────────────────────┬───────────────────────────────────────────────┘
                            │  HTTP (fragments + JSON) · SSE /api/stream
┌───────────────────────────▼───────────────────────────────────────────────┐
│  WEB LAYER — FastAPI                                                      │
│    routes/data.py     POST /data/source  /data/mapping  /data/fetch       │
│    routes/params.py   PATCH /params                                       │
│    routes/results.py  GET  /results  /results/export.csv                  │
│    routes/stream.py   GET  /api/stream           (SSE)                    │
│                                                                           │
│    deps.py:  get_principal() -> Principal        ← v1 returns "local"      │
│              get_workspace(principal, id) -> Workspace                    │
└───────────────────────────┬───────────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────────┐
│  SERVICE LAYER  (orchestration, state machine, no numerics)               │
│    IngestService       source config → SeriesFrames → persist             │
│    WorkspaceService    params CRUD, validation, dirty tracking            │
│    SimulationService   run_id, debounce, cancellation, LRU result cache   │
│    JobRunner           ProcessPoolExecutor keyed by workspace_id          │
└──────┬──────────────────────────────────────┬─────────────────────────────┘
       │                                      │
┌──────▼──────────────────────┐   ┌───────────▼────────────────────────────┐
│  ADAPTERS  (all I/O)        │   │  DOMAIN  (pure functions, no I/O)      │
│    HaStatsClient            │   │    ingest/     cumulative→delta        │
│    CsvLoader                │   │    normalize/  grid selection, resample│
│    PriceLoader              │   │    quality/    checks, flags           │
│    (future) EntsoeClient    │   │    pricing/    import/export curves    │
└──────┬──────────────────────┘   │    policies/   charge + discharge      │
       │                          │    battery/    step function, limits   │
       │                          │    simulate/   main loop               │
       │                          │    metrics/    KPIs, waterfall         │
       │                          │    benchmark/  perfect-foresight DP    │
       │                          └────────────────────────────────────────┘
┌──────▼────────────────────────────────────────────────────────────────────┐
│  PERSISTENCE                                                              │
│    SQLite  (SQLAlchemy)                                                   │
│      workspaces(id, owner_id, name, created_at)                           │
│      datasets(id, workspace_id, source_type, fetched_at, coverage, qa)    │
│      series_meta(id, dataset_id, name, kind, resolution_s, path)          │
│      params(workspace_id, json, updated_at)          -- current config    │
│      runs(id, workspace_id, run_id, config_hash, result_json, created_at) │
│      credentials(workspace_id, ha_url, ha_token_enc)                      │
│                                                                           │
│    Filesystem                                                             │
│      <data_dir>/<workspace_id>/series/<name>_<res>.parquet                │
│      <data_dir>/<workspace_id>/uploads/<original_filename>                │
└───────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Why this split

The **domain layer is pure** — it takes arrays and a config object and returns arrays and
a result object. No database, no HTTP, no clock. This is what makes the simulator testable
against hand-computed fixtures, and it is what allows the resolution-bias diagnostic and
the perfect-foresight benchmark to be implemented as *additional calls* rather than
special cases threaded through the application.

### 5.3 Compute

`ProcessPoolExecutor` with one worker per workspace. A year of hourly data is 8,760
intervals; the vectorisable parts (pricing, metrics) run in numpy, and the sequential
battery loop is the only genuine bottleneck. Expect ~50 ms for the policy run and ~1–3 s
for the perfect-foresight DP at 100 SoC levels. If the sequential loop proves too slow at
5-minute resolution over a year (105k intervals), the fallback is Numba `@njit` on
`simulate_core` — keep that function free of Python objects so the option stays open.

Cancellation is cooperative: `simulate_core` checks a shared `multiprocessing.Event`
every 1,024 intervals.

### 5.4 Configuration

Single `config.toml` next to the data directory: bind host/port, data dir, log level,
default parameter values, encryption key for stored HA tokens. Environment variables
override. HA tokens are encrypted at rest with a key derived from a local secret file
(0600); this is deterrence against casual disclosure, not a security boundary.

### 5.5 Multi-user readiness (designed for, not implemented)

The following are v1 requirements *because* they make multi-tenancy a later additive
change rather than a rewrite:

1. **Every persisted row carries `workspace_id`.** No table is implicitly global.
2. **`Workspace` is resolved via a FastAPI dependency**, never read from a global.
   In v1 `get_principal()` returns a hard-coded `Principal(id="local")` and
   `get_workspace()` returns the single workspace. Adding auth means replacing exactly
   these two functions.
3. **No module-level mutable state.** Session state, run ids, debounce timers and caches
   live inside `SimulationService`, instantiated per workspace and held in a registry
   keyed by `workspace_id`.
4. **Filesystem paths derive from `workspace_id`**, with path traversal rejected.
5. **The job runner is keyed by `workspace_id`** with a per-workspace concurrency limit
   of 1, so one user's year-long run cannot starve another's.
6. **SSE streams are per-workspace channels.** The stream endpoint takes the workspace
   from the dependency, not from a query parameter.
7. **`owner_id` exists on `workspaces` from day one**, populated with `"local"`.

Deliberately deferred: authentication, authorisation policy, quotas, per-user encryption
keys, workspace sharing, migration of the v1 single workspace into a user account
(a one-row `UPDATE` when the time comes).

---

## 6. Algorithms and formulas

Pseudocode is Python-flavoured. Functions marked **[vectorisable]** should be implemented
with numpy over the whole array; the rest are genuinely sequential.

### 6.1 Cumulative meter register → interval deltas

```python
def cumulative_to_delta(ts, values):
    """
    Meter registers are total_increasing. They reset on meter replacement,
    integration reload, or sensor unavailability. A naive diff() turns a reset
    into a large negative spike; a naive clip(0) turns it into a lost interval
    but a *rollover* into a spurious huge positive one. Both are wrong.
    """
    d = diff(values)                       # length n-1, aligned to interval start
    flags = zeros_like(d, dtype=uint16)

    for i where d[i] < 0:
        drop = -d[i]
        if drop < RESET_TOLERANCE_KWH:     # 0.01 — float noise / rounding
            d[i] = 0
        elif values[i+1] < RESET_FLOOR_KWH:  # 1.0 — register restarted near zero
            # Genuine reset: energy consumed since the reset is the new reading.
            d[i] = values[i+1]
            flags[i] |= RESET_CORRECTED
        else:
            # Ambiguous: register went backwards but not to zero. Do not guess.
            d[i] = 0
            flags[i] |= RESET_CORRECTED
            record_warning(AMBIGUOUS_REGISTER_DECREASE, ts[i], drop)

    return d, flags

# NOTE: when ingesting from HA's `statistics_during_period`, prefer the `sum`
# column, which HA has already reset-corrected. Apply this function only to
# CSV input and to raw `state` series.
```

Gap handling: if `ts[i+1] - ts[i]` exceeds 1.5× the nominal resolution, the interval is a
**gap**. Gaps are *not* interpolated for energy; they are emitted as `NaN` and excluded
from all sums, with their duration reported. Interpolating a 6-hour outage invents a load
profile and quietly changes the answer. Prices, by contrast, are forward-filled (a price
is a step function that genuinely persists).

### 6.2 Simulation grid selection and resampling

```python
def choose_grid(series_frames, window):
    energy_series = [s for s in series_frames if s.kind == "energy"]
    resolutions = [s.resolution_s for s in energy_series
                   if s.covers(window)]

    # Coarsest wins. Downsampling energy (summing deltas) is exact.
    # Upsampling would require assuming a within-interval profile: forbidden.
    return max(resolutions)

def resample_energy(frame, target_s):
    assert target_s >= frame.resolution_s, "never upsample energy"
    if target_s == frame.resolution_s:
        return frame
    return frame.resample(target_s).sum()        # exact  [vectorisable]

def resample_price(frame, target_s):
    if target_s >= frame.resolution_s:
        return frame.resample(target_s).mean()   # energy-unweighted; see note
    return frame.reindex(target_index).ffill()   # step function: safe to upsample
```

> **Note on price downsampling.** Averaging 4×15-minute prices into an hourly price is
> only exact if consumption within the hour is uniform. It is not. Where 15-minute prices
> exist but energy is hourly, the correct move is to keep the *hourly* grid but flag that
> price granularity has been lost — the simulator cannot exploit intra-hour spreads it
> cannot observe in the energy data. Record this in `diagnostics`.

One grid is chosen for the **whole window**. Mixing 5-minute and hourly within a single
run would make the battery's behaviour resolution-dependent mid-run and the results
internally incomparable.

### 6.3 Household load reconstruction

Energy balance at the AC bus over one interval:

```
pv + import + battery_discharge  =  load + export + battery_charge
```

therefore

```python
def reconstruct_load(pv, imp, exp, batt_chg=None, batt_dis=None):
    """[vectorisable] Returns the battery-free, standby-free household load."""
    load = pv + imp - exp
    if batt_chg is not None:                 # strip an existing battery
        load = load + batt_dis - batt_chg

    negative = load < 0
    if negative.any():
        record_warning(NEGATIVE_LOAD, count=negative.sum(),
                       pct=100 * negative.mean())
        load = maximum(load, 0)              # clamp, flag, do not silently absorb
        flags[negative] |= CLAMPED_NEGATIVE

    return load, flags
```

Negative reconstructed load is always a data problem, never physics. Likely causes, in
order of frequency: the PV sensor measures only part of the array or sits behind a
sub-meter; a clock offset between the P1 meter and the inverter integration; sign
convention inverted on an export sensor; or an existing battery whose sensors were not
mapped. The UI must say this rather than presenting a clamped series as clean.

If `house_load` is supplied directly, use it, and report
`max|load_supplied − load_reconstructed|` as a consistency check.

### 6.4 Tariff register identification and zone assignment

Two related but distinct problems.

**(a) Which register is dal?** Installations disagree about whether T1 or T2 is the
night register. Detect it from the data:

```python
def detect_dal_register(import_t1, import_t2, index_local):
    """Whichever register accrues predominantly at night is the dal register."""
    night = (index_local.hour >= 23) | (index_local.hour < 7)
    share_t1 = import_t1[night].sum() / max(import_t1.sum(), EPS)
    share_t2 = import_t2[night].sum() / max(import_t2.sum(), EPS)
    if abs(share_t1 - share_t2) < 0.2:
        return UNCERTAIN            # ask the user
    return T2 if share_t2 > share_t1 else T1
```

**(b) Which zone applies to a *simulated* interval?** The baseline can be priced from the
registers directly — that is what the supplier actually bills. But once a battery changes
the flows, simulated import must be assigned to a zone by clock rule:

```python
def tariff_zone(index_local, cfg):
    dal = ((index_local.hour >= cfg.dal_start_hour) |
           (index_local.hour <  cfg.dal_end_hour)  |
           (index_local.dayofweek >= 5))            # Sat/Sun
    return where(dal, DAL, NORMAAL)
```

Default window: dal from 23:00 to 07:00 plus weekends. **This varies by grid operator**
(21:00 in some areas), so it is user-configurable, and the app validates the rule against
the observed registers:

```python
mismatch = sum(import_t2[zone == NORMAAL]) + sum(import_t1[zone == DAL])
mismatch_pct = 100 * mismatch / total_import
# > 5% means the configured window is wrong — surface it in panel ①.
```

This check costs almost nothing and catches a whole class of silent mispricing under
fixed/variable contracts.

### 6.5 Price curves

All three contract types produce the same two arrays. This is deliberately a single code
path with three rate sources, not three pricing engines.

```python
def bare_supply_price(cfg, index, tariff_zone, spot):
    """[vectorisable] EUR/kWh, excl. energy tax and VAT."""
    if cfg.contract == DYNAMIC:
        return spot + cfg.supplier_markup
    elif cfg.contract == FIXED:
        return where(tariff_zone == DAL, cfg.rate_dal, cfg.rate_normaal)
    elif cfg.contract == VARIABLE:
        # piecewise-constant schedule, changes typically 1 Jan / 1 Jul
        rates = lookup_schedule(cfg.rate_schedule, index)   # searchsorted on 'from'
        return where(tariff_zone == DAL, rates.dal, rates.normaal)


def import_price(cfg, bare):
    """[vectorisable] EUR/kWh, all-in, what you actually pay."""
    return (bare + cfg.energy_tax_excl_vat) * (1 + cfg.vat_rate)


def export_price_net(cfg, bare):
    """
    [vectorisable] EUR/kWh net received per exported kWh, 2027+ regime.

      compensation = max(0, alpha * bare + beta)     # may not be negative
      net          = compensation - terugleverkosten # net MAY be negative

    No energy tax and no VAT on feed-in for private consumers.
    """
    compensation = maximum(0.0, cfg.feedin_alpha * bare + cfg.feedin_beta)
    if cfg.tlk_mode == FLAT:
        tlk = cfg.tlk_eur_per_kwh
    else:
        tlk = tiered_tlk_rate(cfg.tlk_tiers, annual_export_kwh)   # see note
    return compensation - tlk
```

Presets for `(alpha, beta)`:

| Preset | α | β | Meaning |
|---|---|---|---|
| Legal minimum | 0.50 | 0.0000 | Statutory floor, valid to 1 Jan 2030 |
| Spot minus fee | 1.00 | −0.0200 | Typical dynamic supplier offer |
| Spot | 1.00 | 0.0000 | Optimistic |
| Fixed amount | 0.00 | *user* | Fixed/variable contracts with a flat feed-in rate |

> **Tiered terugleverkosten.** From 2027 these must be expressed per fed-in kWh, so
> `FLAT` is the default and the expected shape. Tiered support is retained because some
> suppliers may keep annual-volume staffels, and a staffel makes savings a **step
> function** of annual export — reducing export by 200 kWh can be worth €0 or €40
> depending on which side of a tier boundary you land. When `tlk_mode == TIERED` the tier
> must be resolved from **annualised** export, so it is unavailable for windows under
> 90 days; fall back to `FLAT` with a visible notice.

> **Pre-2027 extension point.** Reintroducing salderen means adding an annual netting
> stage between the flow simulation and the cost accounting, not changing these
> functions. Keep `compute_costs` (§6.10) operating on flow arrays so that stage can be
> inserted.

### 6.6 Charge policy

```python
def charge_request(policy, i, st, cfg):
    """
    Returns (kwh_from_pv_surplus, kwh_from_grid) requested this interval,
    before any physical limit is applied.
    """
    solar_surplus = max(0.0, st.pv[i] - st.load[i])

    req_pv = solar_surplus if policy in (P1, P3) else 0.0

    in_band = cfg.band_a <= st.spot[i] <= cfg.band_b
    req_grid = cfg.max_charge_kw * st.dt if (policy in (P2, P3) and in_band) else 0.0

    return req_pv, req_grid
```

- **P1** — solar surplus only. Net zero at the grid on the export side.
- **P2** — grid charging only, while `A ≤ spot ≤ B`. "Maximise" means charge at full
  rated power. Surplus solar is *not* captured under P2 alone.
- **P3** — both. PV surplus is always taken; grid charging adds on top inside the band,
  with the combined request clamped to rated power in §6.8. PV takes priority in that
  clamp because it is free and, on a DC-coupled system, more efficient.

The band is compared against the **bare EPEX spot price**, per product decision.
Note that `A` is a lower bound and exists mainly to let the user *exclude* deeply negative
prices (unusual) or, more typically, to be left at a large negative value so only `B`
binds.

### 6.7 Discharge policy

```python
def discharge_request(policy, i, st, cfg):
    """Returns (kwh_to_home, kwh_to_grid) requested, before physical limits."""
    deficit = max(0.0, st.load[i] - st.pv[i])

    req_home = deficit if policy in (D1, D3) else 0.0
    req_grid = 0.0

    in_band = cfg.band_c <= st.spot[i] <= cfg.band_d
    if policy in (D2, D3) and in_band:
        full = cfg.max_discharge_kw * st.dt
        req_home = min(full, deficit)               # serve the house first
        if cfg.allow_grid_export:
            req_grid = full - req_home

    if cfg.economic_guard and st.p_export_net[i] <= 0:
        req_grid = 0.0        # never pay to export

    return req_home, req_grid
```

- **D1** — serve household deficit only. Never exports.
- **D2** — discharge only while `C ≤ spot ≤ D`, at full rated power. Outside the band the
  battery does nothing, even if the house is importing. This is intentional and literal.
- **D3** — both.

`allow_grid_export` defaults **off**. Under the 2027 regime, a kWh discharged to the house
displaces `p_import` (≈ €0.25 at €0.08 spot) while a kWh exported earns `p_export_net`
(≈ €0.04–0.09 minus terugleverkosten). Home discharge is worth roughly three times as
much, and grid arbitrage generally only clears when charging happened at negative prices.
The simulator should demonstrate this rather than assume it.

**Band overlap.** If `[A,B]` and `[C,D]` intersect, charge and discharge can both fire.
Validate at config time and warn. At runtime, net the requests:

```python
net = (req_pv + req_grid_chg) - (req_home + req_grid_dis)
charge_total, discharge_total = (net, 0) if net > 0 else (0, -net)
```

P1/D1 can never conflict, since `max(0, pv−load)` and `max(0, load−pv)` are never both
positive.

### 6.8 Battery step function

```python
def battery_step(soc, req_pv, req_grid_chg, req_home_dis, req_grid_dis, st, i, cfg):
    dt = st.dt

    # ---- 1. resolve simultaneous charge/discharge ------------------------
    chg_req = req_pv + req_grid_chg
    dis_req = req_home_dis + req_grid_dis
    if chg_req > 0 and dis_req > 0:
        net = chg_req - dis_req
        if net >= 0:
            scale = net / chg_req; req_pv *= scale; req_grid_chg *= scale
            dis_req = 0; req_home_dis = req_grid_dis = 0
        else:
            scale = -net / dis_req; req_home_dis *= scale; req_grid_dis *= scale
            chg_req = 0; req_pv = req_grid_chg = 0

    # ---- 2. clamp charge to rated power, PV first -----------------------
    chg_ac = min(req_pv + req_grid_chg, cfg.max_charge_kw * dt)
    chg_pv   = min(req_pv, chg_ac)
    chg_grid = chg_ac - chg_pv

    # ---- 3. clamp charge to SoC headroom --------------------------------
    #   DC-coupled systems skip one inversion on the PV path.
    eta_c_pv = cfg.eta_c_dc if cfg.coupling == DC_HYBRID else cfg.eta_c
    stored   = chg_pv * eta_c_pv + chg_grid * cfg.eta_c
    headroom = cfg.soc_max_kwh - soc
    if stored > headroom:
        scale = headroom / stored
        chg_pv *= scale; chg_grid *= scale; stored = headroom

    # ---- 4. clamp discharge to rated power and available energy ---------
    dis_ac = min(req_home_dis + req_grid_dis,
                 cfg.max_discharge_kw * dt,
                 (soc - cfg.soc_min_kwh) * cfg.eta_d)
    dis_home = min(req_home_dis, dis_ac)
    dis_grid = dis_ac - dis_home
    withdrawn = dis_ac / cfg.eta_d

    # ---- 5. resulting grid flows ----------------------------------------
    #   load here already includes standby draw (added in the caller).
    net_flow = st.load[i] + chg_pv + chg_grid - st.pv[i] - dis_ac
    imp = max(0.0,  net_flow)
    exp = max(0.0, -net_flow)

    # ---- 6. connection limits -------------------------------------------
    imp_cap = cfg.max_import_kw * dt
    if imp > imp_cap:                       # shed grid charging first
        excess   = imp - imp_cap
        cut      = min(chg_grid, excess)
        chg_grid -= cut
        stored   -= cut * cfg.eta_c
        imp      -= cut
        if imp > imp_cap:
            record_warning(IMPORT_LIMIT_EXCEEDED, i)   # household load alone exceeds it

    exp_cap = cfg.max_export_kw * dt
    if exp > exp_cap:                       # shed arbitrage export, then curtail PV
        excess = exp - exp_cap
        cut    = min(dis_grid, excess)
        dis_grid -= cut; dis_ac -= cut; withdrawn -= cut / cfg.eta_d; exp -= cut
        if exp > exp_cap:
            curtailed = exp - exp_cap
            exp = exp_cap
            record_curtailment(i, curtailed)

    # ---- 7. integrate ----------------------------------------------------
    soc_new = soc + stored - withdrawn
    assert cfg.soc_min_kwh - EPS <= soc_new <= cfg.soc_max_kwh + EPS

    return soc_new, Flows(imp, exp, chg_pv, chg_grid, dis_home, dis_grid, stored,
                          withdrawn, curtailed)
```

Efficiency split convention: `eta_c = eta_d = sqrt(roundtrip_efficiency)`. The user enters
a single **AC-to-AC** round-trip figure. `eta_c_dc = sqrt(roundtrip_dc)` where
`roundtrip_dc` defaults to `roundtrip + 0.04` for DC-coupled systems, overridable.

SoC bounds: `soc_min_kwh = usable_capacity * min_soc_pct/100`,
`soc_max_kwh = usable_capacity * max_soc_pct/100`. "Usable capacity" is the full 0–100%
window the battery reports; min/max SoC are additional user-imposed operating limits
inside it.

### 6.9 Main simulation loop

```python
def simulate(frame, cfg, include_standby=True):
    n   = len(frame.index)
    soc = cfg.initial_soc_kwh
    out = Flows.empty(n)

    standby_kwh = (cfg.standby_w / 1000.0) * frame.dt if include_standby else 0.0

    st = frame.view()
    st.load = frame.load + standby_kwh       # standby exists only with a battery

    for i in range(n):
        if i % 1024 == 0 and cancel_event.is_set():
            raise Cancelled

        if isnan(st.load[i]) or isnan(st.pv[i]):
            out.mark_gap(i); continue        # gaps excluded, SoC carried forward

        rp, rg  = charge_request(cfg.charge_policy, i, st, cfg)
        dh, dg  = discharge_request(cfg.discharge_policy, i, st, cfg)
        soc, f  = battery_step(soc, rp, rg, dh, dg, st, i, cfg)
        out[i]  = f
        out.soc[i] = soc

    return out


def simulate_baseline(frame):
    """[vectorisable] No battery, no standby."""
    net = frame.load - frame.pv
    return Flows(imp=maximum(net, 0), exp=maximum(-net, 0), ...)
```

**Four runs per request**, which together make the cost waterfall exact rather than
approximate:

| Run | Battery | Standby | Purpose |
|---|---|---|---|
| A | no | no | Baseline |
| B | yes | no | Isolates flow effects |
| C | yes | yes | The headline result |
| D | perfect foresight | yes | Upper bound |

`standby_cost ≡ cost(C) − cost(B)` exactly. Run A is vectorised, B and C are the
sequential loop, D is the DP in §6.12. Total ≈ 1–3 s at hourly resolution.

### 6.10 Cost accounting

```python
def compute_costs(flows, p_import, p_export_net):
    """[vectorisable] EUR over the window."""
    return (flows.imp * p_import).sum() - (flows.exp * p_export_net).sum()
```

Note the export term is *subtracted* and `p_export_net` may itself be negative — in which
case exporting increases the bill. That is the intended behaviour under the 2027 regime
during negative-price hours, and it is one of the more important things this tool can
show a user.

**Waterfall decomposition** (exact, because per interval
`Δcost = Δimp·p_imp − Δexp·p_exp_net` and splitting by sign is lossless):

```python
def waterfall(A, B, C, p_import, compensation, tlk, cfg):
    d_imp = B.imp - A.imp
    d_exp = B.exp - A.exp

    return [
      ("avoided_grid_import",        (maximum(-d_imp, 0) * p_import).sum()),
      ("added_grid_import_charging", -(maximum(d_imp, 0) * p_import).sum()),
      ("avoided_terugleverkosten",    (maximum(-d_exp, 0) * tlk).sum()),
      ("lost_feedin_compensation",   -(maximum(-d_exp, 0) * compensation).sum()),
      ("arbitrage_export_revenue",    (maximum(d_exp, 0) *
                                       (compensation - tlk)).sum()),
      ("standby_consumption",         cost(B) - cost(C)),
      ("degradation",                -cfg.degradation_eur_per_kwh * C.withdrawn.sum()),
    ]
    # invariant, assert in tests:
    #   sum(waterfall) == cost(A) - cost(C) - degradation
```

Fixed costs — vastrecht, systeembeheerkosten, vermindering energiebelasting — are
**excluded**. They do not change with a battery, so including them would only dilute the
percentage. Show them, greyed out, in an informational strip if total-bill context is
wanted later.

### 6.11 Metrics

```python
saved_kwh  = A.imp.sum() - C.imp.sum()
saved_pct  = 100 * saved_kwh / A.imp.sum()

# Equivalent full cycles, counted on the storage side.
# Convention matters: AC-side throughput gives a figure ~5% lower.
efc = C.withdrawn.sum() / cfg.usable_capacity_kwh

self_consumption = 1 - export.sum() / pv.sum()          # per scenario
self_sufficiency = 1 - import.sum() / load.sum()        # per scenario

# Conversion loss = AC in - AC out - energy still sitting in the battery.
# Equivalently (charge_ac - stored) + (withdrawn - discharge_ac).
charge_ac        = (C.chg_pv + C.chg_grid).sum()
discharge_ac     = (C.dis_home + C.dis_grid).sum()
conversion_loss  = charge_ac - discharge_ac - (soc_end - soc_start)
```

**SoC drift correction.** The battery does not end the window at its starting SoC. Report
`soc_end − soc_start` and value it at the median import price; if it exceeds 2% of the
headline saving, surface it. Without this, a policy that simply ends the year empty looks
better than it is.

### 6.12 Perfect-foresight benchmark

An upper bound obtained by dynamic programming over discretised SoC. Its only purpose is
to make the headline number interpretable: "€331" means little; "€331 of a theoretical
€478" means a great deal.

```python
def perfect_foresight(frame, cfg, n_soc=101, n_actions=41):
    soc_levels = linspace(cfg.soc_min_kwh, cfg.soc_max_kwh, n_soc)
    V          = zeros(n_soc)

    # Terminal constraint: must finish at or above the starting SoC.
    # Without it the DP simply liquidates the battery and inflates the bound.
    V[soc_levels < cfg.initial_soc_kwh - EPS] = +INF

    policy = zeros((len(frame), n_soc), dtype=int8)

    for i in reversed(range(len(frame))):
        # action = signed AC power, negative = charge, positive = discharge
        actions = linspace(-cfg.max_charge_kw, cfg.max_discharge_kw, n_actions) * frame.dt
        # [vectorisable] over (n_soc x n_actions)
        soc_next, cost = transition_cost(soc_levels[:, None], actions[None, :],
                                         frame, i, cfg)
        Vn   = interp(soc_next, soc_levels, V)      # linear interpolation
        tot  = cost + Vn
        tot[~feasible(soc_next, cfg)] = +INF
        V         = tot.min(axis=1)
        policy[i] = tot.argmin(axis=1)

    return roll_forward(policy, frame, cfg)
```

Complexity `O(T · n_soc · n_actions)` ≈ 8,760 × 101 × 41 ≈ 36M vectorised operations —
a few seconds in numpy. Interpolation of `V` rather than snapping to the nearest SoC level
avoids a systematic pessimism bias of several percent.

The DP obeys the same power, SoC and connection limits, and the same standby draw, so the
comparison is like-for-like. It does **not** obey the user's price bands — that is the
point.

### 6.13 Resolution-bias diagnostic

Complements the overlap diagnostic in §7.1. Overlap measures how much information
the recording resolution destroyed; this measures how much that changes the answer.
Report both — §7.1 covers the whole window and is always available, §6.13 is more
direct but only available where 5-minute data exists.

Hourly buckets cannot represent a house that imports at 12:05 and exports at 12:40. They
show only the net, which makes the household look more self-balancing than it was and
**systematically overstates** what a battery would have added. The magnitude is household-
specific (5–20% is typical), so it must be measured, not assumed.

```python
def resolution_bias(dataset, cfg):
    fine_window = dataset.window_with_resolution(300)     # trailing ~10 days
    if fine_window is None or fine_window.days < 3:
        return None

    r_fine   = run_all(dataset.frame(fine_window, grid_s=300),  cfg)
    r_coarse = run_all(dataset.frame(fine_window, grid_s=3600), cfg)

    if abs(r_fine.saved_eur) < 1.0:
        return None                                      # too small to be meaningful

    return {
      "bias_pct": 100 * (r_coarse.saved_eur - r_fine.saved_eur) / r_fine.saved_eur,
      "basis":    f"{fine_window.days} days at 5-minute vs hourly",
    }
```

It measures *dispatch* error (the battery makes different decisions at different
resolutions). The price bracket in §6.16 measures *pricing* error. They are independent
and both should be reported.

Reported as an advisory, **never applied as an automatic correction**: the trailing ten
days are not a representative sample of the year, and silently scaling the headline number
by a factor derived from one seasonal window would be worse than showing both.

### 6.15 Configuration epochs

PV and batteries get installed mid-window. Averaging across a commissioning date produces
a figure that describes a household that never existed.

```python
EPOCH_EVENTS = ["pv_commissioned", "pv_capacity_changed",
                "battery_commissioned", "battery_removed"]

def detect_epochs(series, index_local):
    """Segment the window into intervals of constant physical configuration."""
    events = []

    # --- PV commissioning ------------------------------------------------
    # A sensor can exist and read zero for months before the panels go live,
    # so "first non-null" is the wrong test. Use sustained daily production.
    daily = series.solar.resample("1D").sum()
    ref   = daily.quantile(0.95)
    if ref > 0.1:
        live = daily.rolling(7, min_periods=4).mean() > 0.10 * ref
        if not live.iloc[0] and live.any():
            events.append(("pv_commissioned", live.idxmax()))

    # --- PV capacity change (panels added) --------------------------------
    # Compare rolling 30-day peak hourly output. A sustained step > 20% that
    # is not explained by season indicates added capacity.
    peak = series.solar.resample("1D").max().rolling(30).median()
    for d in changepoints(peak, min_rel_step=0.20, min_segment_days=45):
        events.append(("pv_capacity_changed", d))

    # --- Battery commissioning / removal ---------------------------------
    if series.batt_charge is not None:
        thr = (series.batt_charge + series.batt_discharge).resample("1D").sum()
        active = thr > 0.05 * max(thr.quantile(0.95), EPS)
        events += transitions(active, "battery_commissioned", "battery_removed")

    return build_epochs(events, index_local)
```

**The dangerous case is an undeclared battery**: the unit was installed but its sensors
were never added to Home Assistant, or were added weeks later. The reconstruction in §6.3
then silently attributes the battery's charging to household load, and every downstream
number is wrong with no error raised. Heuristic detection:

```python
def detect_undeclared_battery(frame, epochs):
    """Flag unexplained step changes consistent with hidden storage."""
    sc    = rolling_self_consumption(frame, window="14D")
    night = rolling_night_import(frame, window="14D")

    for d in changepoints(sc, min_abs_step=0.15):
        if not epoch_boundary_near(d, epochs, tol="7D"):
            warn(POSSIBLE_UNDECLARED_BATTERY, date=d,
                 detail="self-consumption rose sharply with no PV or battery event")

    # Grid-charging storage shows as flat-topped night import at constant power.
    if flat_top_fraction(night) > 0.3:
        warn(POSSIBLE_UNDECLARED_BATTERY, detail="constant-power night import blocks")
```

Both are heuristics and both are presented as questions to the user, never as findings.
Detected boundaries are **always user-confirmable and overridable** — the household knows
when the installer came, and a date entered by hand beats any changepoint algorithm.

Effects on the rest of the application:

1. Panel ① renders an **epoch timeline strip** above the coverage summary.
2. The range selector marks any predefined range that crosses a boundary, and offers a
   one-click *"restrict to current configuration"*.
3. If a run spans a boundary it proceeds, but: annualisation is disabled, the result
   carries `spans_epoch_boundary: true`, and per-epoch sub-totals are reported alongside
   the aggregate so the user can see the discontinuity rather than infer it.
4. `SimulationFrame.epoch_id` lets metrics be grouped without re-running.
5. The battery state is **not** reset at a boundary. It is one continuous simulation; only
   the reporting is segmented.

### 6.16 Price bracketing under settlement/resolution mismatch

Since 1 October 2025 EPEX settles per 15 minutes. Where the supplier passes that through
but the available energy data is hourly, the simulator sees an hourly average price and
cannot know how the household's consumption was distributed within the hour.

HA's hourly statistics retain `min`, `max` and `mean` for price sensors (§4.3). That is
enough to *bound* the pricing error rather than ignore it:

```python
def price_bracket_runs(frame, cfg):
    if cfg.supplier_settlement == HOURLY:
        return None            # supplier bills the hourly average: min/max irrelevant
    if frame.spot_min is None:
        return None            # no sub-hourly information available

    central     = run(frame, cfg, charge_px=frame.spot,     discharge_px=frame.spot)
    optimistic  = run(frame, cfg, charge_px=frame.spot_min, discharge_px=frame.spot_max)
    pessimistic = run(frame, cfg, charge_px=frame.spot_max, discharge_px=frame.spot_min)
    return Bracket(low=pessimistic, central=central, high=optimistic)
```

**Be precise about what this brackets.** Every kWh charged within the hour was bought at
some price ≥ the hourly minimum, and every kWh discharged displaced a price ≤ the hourly
maximum. So the optimistic run is a genuine upper bound *on the cost of this dispatch* and
the pessimistic run a genuine lower bound. It is **not** a bound on what a 15-minute-aware
controller could achieve — such a controller would also dispatch differently, and could
exceed the optimistic bound. Pricing error and dispatch error are separate; §6.13 covers
the second.

The first check is `cfg.supplier_settlement`. Many Dutch dynamic suppliers still average
the four quarter-hour prices to an hourly price and bill on that. For those customers the
hourly mean is not an approximation — it is exactly what they pay, and applying a bracket
would manufacture uncertainty that does not exist. Ask the user; default to hourly.

Also report the intra-hour spread as a standalone indicator:

```python
intra_hour_spread = (frame.spot_max - frame.spot_min).mean()
```

A large spread with hourly settlement is an argument for switching supplier, not a
modelling problem — worth surfacing as an insight.

### 6.17 Timestamp misalignment detection

A clock offset between the P1 meter integration and the solar inverter integration is
common (minutes to a full hour, the latter usually a timezone bug) and corrupts the
reconstruction in §6.3 in a way that looks like noise rather than an error.

**Min/max alone cannot detect an offset** — shifting a series in time does not change its
hourly extrema in any recoverable way. Two things do work:

```python
def detect_time_offset(pv, export_obs, max_lag_intervals=12):
    """
    Primary method: normalised cross-correlation. PV production and grid export
    are strongly coupled in a PV household; the lag maximising correlation is
    the offset between the two sensors' clocks.
    """
    a = zscore(detrend_daily(pv))
    b = zscore(detrend_daily(export_obs))
    scores = [pearson(a, shift(b, lag)) for lag in range(-max_lag, max_lag + 1)]
    best   = argmax(scores)
    confidence = (scores[best] - median(scores)) / (std(scores) + EPS)
    return lag_at(best), confidence


def power_energy_consistency(power_mean_w, energy_sum_kwh, dt_h):
    """
    Corroborating method, available when the user mapped BOTH a power sensor
    (state_class measurement -> has mean) and an energy meter for the same
    quantity. Over one interval these must agree:

        mean_power_W / 1000 * dt_h  ==  energy_sum_kWh

    A constant proportional error means a unit or scaling mistake. An error
    that oscillates with the daily cycle means a time offset — the mean power
    is being attributed to the wrong hour.
    """
    implied  = power_mean_w / 1000.0 * dt_h
    residual = (implied - energy_sum_kwh) / maximum(energy_sum_kwh, EPS)
    return dict(mean_pct=100 * residual.mean(),
                diurnal_amplitude_pct=100 * daily_fourier_amplitude(residual))
```

A detected offset is **reported and offered as a correction**, never applied silently:
"Solar production appears to lag the meter by 1 hour (confidence 0.94). Shift it?"
Applying it automatically would make a data problem invisible, and the user may have a
better explanation than the algorithm does.

The third signal is already in the spec: `overlap_pct` (§7.1) inflates under misalignment,
because a shifted PV series creates apparent import and export in the same interval. If
overlap is high *and* cross-correlation finds a confident non-zero lag, misalignment is
the likely cause rather than genuine sub-interval variation.

### 6.14 Validation harness

Fixtures the implementation must reproduce exactly:

1. **Trivial** — flat 1 kW load, no PV, flat price, P2/D2 with disjoint bands. Cycles,
   throughput and cost are analytically computable.
2. **Efficiency** — one charge and one discharge of a 10 kWh battery at 90% RTE returns
   9.0 kWh AC. Round-trip loss is 1.0 kWh, not 0.9 or 1.11.
3. **Conservation** — for every run, `Σ(pv + imp + dis) == Σ(load + exp + chg) ± 1e-6`.
4. **Waterfall closure** — `Σ(waterfall) == cost(A) − cost(C) − degradation ± 1e-6`.
5. **Monotonicity** — larger capacity never reduces savings, all else equal. Violation
   indicates a clamping bug.
6. **Bound** — perfect-foresight saving ≥ every policy saving, for every configuration.
   This is a strong invariant and catches most policy and pricing errors.
7. **DST** — a window spanning both the March and October transitions has 8,760 ± 1 hourly
   intervals with no duplicated or dropped index entries.
8. **Reset** — a synthetic register that resets to 0 mid-window yields the correct total.
9. **Epoch** — a synthetic window with PV switched on at the midpoint yields exactly two
   epochs with the correct boundary date, and per-epoch savings that sum to the aggregate.
10. **Bracket ordering** — `saved_low ≤ saved_central ≤ saved_high` for every configuration
    where a bracket applies. Violation means charge and discharge price arrays were
    swapped.
11. **Offset recovery** — a series shifted by a known lag is recovered by
    `detect_time_offset` to within one interval, with confidence above 3.0.
12. **Phase approximation** — selecting an unsupported phase topology and continuing sets
    `topology.approximated = true` and produces results identical to the 3-phase case
    (the approximation is the 3-phase model).

---

## 7. Data quality, validation and red-team notes

### 7.1 The overlap diagnostic — measure resolution damage directly

There is a much better resolution diagnostic than §6.13, available on the **full window**
without needing any 5-minute data:

```python
overlap_kwh = minimum(import_obs, export_obs).sum()
overlap_pct = 100 * overlap_kwh / import_obs.sum()
```

In any interval where the meter recorded **both** import and export, the flow direction
reversed *within* the interval. That energy is invisible to the simulator: the
reconstructed load nets it out, so the simulated baseline shows less import than actually
occurred, and no battery in the simulation can recover it.

**This measure is clean, and the reason matters.** Dutch smart meters net internally
across phases: they never register import and export at the same instant, only one or the
other, and this behaviour is unchanged by the end of salderen in 2027. So overlap within
an interval can only have arisen from the flow reversing *in time*, never from one phase
exporting while another imports. `overlap_kwh` is therefore an uncontaminated measure of
temporal resolution loss. On a meter without phase netting the same statistic would
conflate two effects and would not be usable this way.

`overlap_kwh` is therefore a direct, exact measure of how much information the recording
resolution destroyed. Use it as the primary gate:

| `overlap_pct` | Treatment |
|---|---|
| < 2% | Fine. Report quietly. |
| 2–10% | Warn. Headline savings are an upper bound. |
| > 10% | Prominent warning. Recommend re-running over the 5-minute window instead. |

Consequently `SimulationFrame` must retain `import_obs`/`export_obs` — they are not used
in the simulation itself, only in validation. Keep both.

**Which baseline for the savings percentage?** Use the *simulated* baseline (run A), so
that both scenarios see identical information. Report the observed import alongside it,
with the difference labelled as resolution loss. Using observed import as the denominator
while computing the battery case from reconstructed data would mix two information sets
and produce a number that is wrong in a direction nobody can reason about.

### 7.2 Known modelling limitations — state these in the UI, not just here

1. **Baseline curtailment must match.** If an export limit is configured, run A must apply
   it too. Curtailing PV only in the battery scenario would credit the battery with
   avoiding a constraint the baseline never faced. Easy to get wrong; assert in tests.
2. **DC-side battery sensors break reconstruction.** §6.3 assumes AC-side measurements.
   DC-side figures put conversion losses on the wrong side of the balance and silently
   bias the reconstructed load. Ask the user which they mapped; if unknown, check whether
   `Σcharge > Σdischarge` by roughly the expected round-trip loss (AC-side) or by
   substantially less (DC-side).
3. **Standby is modelled as a constant.** Real inverters draw more when cycling and less
   when deeply idle. A constant is defensible and conservative-ish; a load-dependent model
   is not worth the parameter burden.
4. **`chg_grid` is a request label, not a measurement.** Under P2/P3 during a sunny hour,
   energy requested "from grid" may in fact be served by PV. This only affects the
   efficiency assignment on DC-coupled systems, by a fraction of a percent. Documented,
   not fixed.
5. **No inverter power derating** at high SoC, low temperature, or high grid voltage.
   Real systems taper. This flatters the battery slightly on the highest-value intervals.
6. **Perfect foresight is genuinely perfect** — it knows every future price exactly. No
   real controller reaches it. Treat the capture ratio as a floor on achievable
   improvement, not a target.
7. **Prices are treated as exogenous.** Fine for one household; invalid if you imagine
   scaling the strategy to a population.

### 7.3 Data quality checks, in execution order

| # | Check | Action on failure |
|---|---|---|
| 1 | Timestamps carry a UTC offset | Reject file, explain DST ambiguity |
| 2 | Series monotonic where `kind=cumulative` | §6.1 reset handling, count and flag |
| 3 | Gap detection at > 1.5× nominal resolution | Flag; exclude from sums; report hours |
| 4 | Required series present for chosen pricing | Block run, name the missing series |
| 5 | Windows of the mapped series overlap | Restrict to intersection, report |
| 6 | Reconstructed load ≥ 0 | Clamp, flag, warn with likely causes (§6.3) |
| 7 | `overlap_pct` (§7.1) | Warn per table above |
| 8 | Tariff zone rule vs registers (§6.4) | Warn above 5% mismatch |
| 9 | Implausible PV: `pv > 0` at local solar midnight | Warn — likely a mismapped sensor |
| 10 | Implausible totals: PV > 2000 kWh/kWp/yr, load > 30 MWh/yr | Warn, do not block |
| 11 | Config: `soc_min < soc_max`, powers > 0, `0.5 < RTE ≤ 1.0` | Block with field errors |
| 12 | Config: charge band ∩ discharge band = ∅ | Warn, allow (netting handles it) |
| 13 | Window ≥ 90 days for annualisation, tiered TLK | Disable those features, explain |
| 14 | Configuration epoch boundaries (§6.15) | Offer to restrict window; block annualisation if spanning |
| 15 | Undeclared battery heuristics (§6.15) | Ask the user; do not assert |
| 16 | Cross-correlation lag between PV and meter (§6.17) | Offer a shift; never apply silently |
| 17 | Power-vs-energy residual, where both mapped (§6.17) | Warn above 5% mean or 3% diurnal |
| 18 | Unsupported phase topology selected | Soft block; set `topology.approximated` |

### 7.4 Window anchoring and short-window guard

Predefined ranges anchor to the **last timestamp present in the data**, not to `now()`.
If the HA instance stopped recording three days ago, "last week" means the final seven
days of data, and the UI states the actual dates. Anchoring to wall-clock time silently
produces a window that is partly empty and a savings figure that is quietly too low.

If the requested range exceeds available coverage, clamp to coverage and say so; never
pad with zeros.

Annualised projections are disabled below 90 days. Battery savings are strongly seasonal —
a summer week has abundant surplus and a battery that saturates by noon, a winter week has
almost no surplus and value comes only from price arbitrage. Scaling either to a year is
wrong by a factor of roughly 2–3 in opposite directions.

### 7.5 Operational notes

- **Bind to `127.0.0.1` by default.** The app stores a Home Assistant long-lived access
  token, which is a full-privilege credential. If the user wants LAN access, make them
  change the bind address deliberately and show a warning when the bind address is not
  loopback.
- **Token storage** is encrypted at rest with a key in a `0600` file beside the database.
  This is deterrence, not a security boundary; say so in the UI.
- **Never log the token**, including in HTTP client debug output.
- Target performance: hourly year (8,760 intervals) end-to-end under 3 s including the DP;
  5-minute month (8,640 intervals) comparable. 5-minute year (105k intervals) is the case
  that may need Numba.
- Language: English UI in v1. Dutch is likely wanted later given the audience — keep user
  strings in a single catalogue module rather than inline in templates.

---

## 8. Open questions for the product owner

Ordered by how much rework the answer causes if deferred.

1. **Feed-in reference for dynamic contracts.** The statutory floor is 50% of the "bare
   supply price". For a fixed contract that is unambiguous. For a dynamic contract, is the
   bare price the hourly spot, or the spot plus the supplier's markup? The spec currently
   assumes `bare = spot + markup` for import but applies α to the same `bare` for export,
   which is a choice, not a fact. It moves feed-in revenue by roughly 1 ct/kWh.

2. **Should the perfect-foresight benchmark be allowed to export?** Currently it inherits
   `allow_grid_export`. Inheriting makes the capture ratio a fair comparison of *policy
   quality*; not inheriting makes it a comparison against the true physical maximum. Both
   are defensible and they differ materially. Recommendation: inherit, and offer the
   unconstrained bound as a secondary figure.

3. **Cycle-life cost.** Currently reported as cycles only, with an optional
   €/kWh-throughput term defaulting to 0. Confirm that a policy doing 700 cycles/yr
   ranking above one doing 300 with similar savings is acceptable output, or set a
   non-zero default (a €5,000 / 10 kWh / 6,000-cycle system implies ≈ €0.08/kWh
   throughput, which is large enough to reverse most arbitrage conclusions).

4. **Multiple policy comparison in one run.** The current UI evaluates one configuration
   at a time. Since a full run costs seconds, evaluating all nine charge×discharge
   combinations and presenting a matrix would be far more useful than sequential manual
   exploration. This is a significant UX addition — worth deciding before build rather
   than retrofitting panel ③.

5. **Terugleverkosten presets.** 2027 tariffs are not published. Shipping presets named
   after real suppliers implies a precision that does not exist. Recommendation: ship
   generic presets ("low / mid / high: 2, 4, 7 ct/kWh") plus a dated note, and let users
   enter their own. Confirm.

6. **Battery-free periods.** If the user already owns a battery, its sensors are stripped
   in §6.3 — but if the battery was installed partway through the window, the reconstructed
   load will be inconsistent across the boundary unless the sensors cover the whole period.
   Should the app detect this and offer to restrict the window?

7. **1-phase vs 3-phase asymmetry.** A 1-phase battery on a 3-phase connection can only
   charge and discharge on its own phase, while the meter nets across phases. This is
   common in the Netherlands and the current model ignores it (it assumes the battery sees
   the net). Is per-phase modelling in scope later? If so, the data model needs per-phase
   series and the decision affects §4 now.

8. **DST-boundary intervals.** The October transition produces a 25-hour local day. The
   spec computes in UTC throughout, which is correct, but hourly *prices* published per
   local hour need care at the boundary. Confirm the spot price source's convention.

9. **Is a soft block on 1-phase / 3×1-phase batteries the right call?** The spec
   implements your instruction, but with an escape hatch, because Dutch smart meters net
   internally across phases and that behaviour survives 2027. The financial result for a
   1-phase battery on a 3-phase connection is therefore close to the 3-phase case; what is
   genuinely unmodellable without per-phase data is the per-phase power ceiling. A hard
   block denies users a number that is probably good to a few percent. Confirm soft block,
   or overrule to hard block.

10. **Should `max_charge_kw` / `max_discharge_kw` be auto-derived from the phase
    topology?** For a 1-phase battery on a 3-phase connection the ceiling is one phase's
    fuse rating, which the user may not think to enter. Proposal: derive a suggested cap
    and warn when the entered value exceeds it, rather than enforcing.

11. **Epoch semantics for battery state.** §6.15 keeps one continuous SoC trace across
    epoch boundaries and segments only the reporting. The alternative — reset SoC at each
    boundary — is arguably cleaner when the boundary is a PV commissioning date. Confirm.

12. **Default for `supplier_settlement`.** Set to hourly, since most Dutch dynamic
    suppliers still bill on the hourly average despite 15-minute EPEX settlement. This
    default silently disables the price bracket for most users. Is that right, or should
    the app ask explicitly during setup rather than defaulting?

13. **PV capacity-change detection** is the weakest of the epoch heuristics — seasonal
    variation, soiling and shading all produce similar signatures, and a false positive
    fragments the window unhelpfully. Consider shipping it disabled, surfacing it only as
    a note in the data-quality panel.

---

## Appendix A — Default parameter values

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
| `initial_soc_pct` | 50 | |
| `phases` | 1 | |
| `fuse_a` | 25 | → 5.75 kW (1×25 A) / 17.3 kW (3×25 A) |
| `max_export_kw` | = import | |
| `energy_tax_excl_vat` | 0.09161 €/kWh | 2026 rate; €0.11085 incl. VAT |
| `vat_rate` | 0.21 | |
| `supplier_markup` | 0.0205 €/kWh | Representative dynamic-supplier inkoopvergoeding |
| `feedin_alpha` | 0.50 | Statutory minimum to 1 Jan 2030 |
| `feedin_beta` | 0.0000 | |
| `tlk_eur_per_kwh` | 0.0400 | Placeholder — 2027 tariffs unpublished |
| `dal_start_hour` | 23 | Varies by grid operator (21:00 in some areas) |
| `dal_end_hour` | 7 | |
| `dal_weekends` | true | |
| `degradation_eur_per_kwh` | 0.0 | Disabled |
| `allow_grid_export` | false | |
| `economic_guard` | false | Policies stay literal by default |
| `pv_coupling` | `dc_hybrid` | Most new installs are hybrid; ask, do not assume |
| `battery_phases` | `three_phase` | Only offered when connection is 3-phase |
| `supplier_settlement` | `hourly` | Most NL dynamic suppliers still bill hourly averages |
| `epoch_detection` | on | PV/battery commissioning |
| `pv_capacity_change_detection` | off | Too many false positives — see §8.13 |
| `epoch_min_segment_days` | 45 | Rejects spurious changepoints |
| `undeclared_battery_check` | on | Heuristic, surfaced as a question |
| `time_offset_max_lag` | 12 intervals | ±12 h hourly, ±1 h at 5-minute |
| `time_offset_autocorrect` | off | Always offered, never applied silently |
| `debounce_ms` | 400 | |
| `dp_soc_levels` | 101 | |
| `dp_action_levels` | 41 | |

Tax and tariff constants must be editable in the UI and are stamped with the year they
were taken from. They will change on 1 January 2027.

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| Salderingsregeling | Dutch net metering. Abolished 1 Jan 2027; out of scope. |
| Terugleververgoeding | Feed-in compensation paid per exported kWh. |
| Terugleverkosten | Feed-in *charge* levied by the supplier per exported kWh. |
| Energiebelasting | Energy tax, per kWh imported. Not levied on export. |
| Vermindering energiebelasting | Fixed annual tax rebate per connection. Battery-invariant. |
| Kale leveringsprijs | Bare supply price, excl. energy tax and VAT. |
| Normaal / dal | Day / night tariff registers (T1 / T2, assignment varies). |
| Vastrecht | Fixed standing charge. Battery-invariant. |
| EFC | Equivalent full cycles: storage-side throughput ÷ usable capacity. |
| RTE | Round-trip efficiency, AC-to-AC at the meter unless stated. |
| Intern salderen | Internal netting across phases by the smart meter. Survives 2027. |
| Configuration epoch | A span of the window with unchanged physical installation. |
| MTU15 | 15-minute market time unit; EPEX settlement since 1 October 2025. |
