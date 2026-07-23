# 1. Product brief

> **Purpose:** what the application is for, who it serves, which regulatory regime it
> models, and what is deliberately left out.
> **Audience:** everyone.
> **Read with:** [17-open-questions.md](17-open-questions.md) for what is still undecided.

## 1.1 Purpose

A locally-run web application that answers one question with the household's own
historical data:

> *If I had owned a home battery over this period, operated under this policy, how much
> grid electricity and how much money would I have saved?*

It is a **retrospective counterfactual simulator**, not a forecaster and not a controller.

## 1.2 Target user

A technically literate Dutch homeowner who runs Home Assistant and is evaluating a battery
purchase (or evaluating operating strategies for one they own). They can obtain an HA
long-lived access token or export CSVs. They are assumed to be comfortable entering numeric
parameters but **not** assumed to know Dutch energy tax structure.

**Solar PV is optional.** The household may have it or not, and the simulator supports
both. Where PV is present, the battery's value comes mainly from storing surplus that would
otherwise be exported at a poor rate. Where it is absent, the value comes entirely from
price arbitrage — charging at cheap hours and discharging at expensive ones — plus avoided
peak-tariff import. That is a smaller and more volatile saving under most parameter
choices, but it is not zero, and whether it clears the cost of a battery is exactly the
question this tool exists to answer. The app must therefore never treat a missing PV series
as an error.

## 1.3 Regulatory regime — fixed decision

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
must not structurally preclude it — see the extension-point note in
[§6.5](10-pricing.md#65-price-curves).

**The app therefore answers a counterfactual, and must say so.** Any data a user brings
today was recorded in 2025 or 2026, by a household living under salderen — a regime in
which the grid acted as a free, lossless, unlimited battery and there was correspondingly
little reason to shift load toward one's own solar
([background E4.2](18-dutch-electricity-background.md#e42-why-this-matters-for-battery-analysis)).
Running that data under 2027 rules is the right question to ask and is what this tool is
for. But two things follow:

- **Regimes must never be mixed within one calculation.** Not per interval, not per epoch,
  not as a blend. The pre-2027 extension point in
  [§6.5](10-pricing.md#65-price-curves) is specified as a separate netting *stage* for
  exactly this reason.
- **The load profile is held fixed, and that is an assumption, not a measurement.** A
  household facing 2027 prices would over time shift consumption toward its own
  generation, which this simulator does not model and cannot infer. The effect biases
  results toward *understating* what a 2027 household would achieve, since it credits the
  battery with all of the shifting and the occupants with none of it. This is a
  counterfactual over prices and hardware, not a forecast of behaviour.

## 1.4 In scope (v1)

- Two data ingestion paths: direct Home Assistant access, and standardised CSV upload.
- **Households with and without solar PV.** PV series are optional; the household declares
  which case applies, and the requirements, policies, topology choices, metrics and
  diagnostics that depend on PV are adjusted accordingly.
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

## 1.5 Explicitly out of scope (v1)

- Gas. Electricity only.
- Real-time or forward-looking optimisation; no scheduling output.
- Battery control or write-back to Home Assistant.
- Multi-site / multi-connection households.
- Investment appraisal (payback period, NPV, IRR). The app reports annualised savings;
  capital cost modelling is deferred.
- Authentication and multi-tenancy. See
  [§5.5](08-architecture.md#55-multi-user-readiness-designed-for-not-implemented) — the
  architecture must *permit* it, v1 does not *implement* it.

## 1.6 Success criteria

1. A user with a working HA instance can go from cold start to a result in under five
   minutes without reading documentation.
2. Changing any parameter updates results automatically without a page reload.
3. Restarting the server preserves all user state.
4. The application refuses to produce misleading numbers: it surfaces data quality
   problems prominently and blocks annualised extrapolation from short windows
   ([§7.4](15-data-quality-and-limits.md#74-window-anchoring-and-short-window-guard)).
5. Every headline figure can be traced to its inputs via an exportable per-interval CSV.

## 1.7 Design principles

- **Honest over impressive.** Where a modelling choice flatters the battery, the app says
  so. The resolution-bias diagnostic
  ([§6.13](14-diagnostics.md#613-resolution-bias-diagnostic)) exists for exactly this
  reason.
- **Literal policies.** Policies do what the user configured, even when uneconomic. The
  simulator reports the outcome rather than quietly overriding the configuration. An
  optional economic guard exists but defaults **off**.
- **No invented data.** Energy series are never upsampled to a finer resolution than they
  were recorded at.
- **Everything overridable.** Defaults are sensible; nothing is hard-coded beyond override.
  See [appendix-a-defaults.md](appendix-a-defaults.md).
