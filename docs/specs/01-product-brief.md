# 1. Product brief

> **Purpose:** what the application is for, who it serves, which regulatory regime it
> models, and what is deliberately left out.
> **Audience:** everyone.
> **Read with:** [17-open-questions.md](17-open-questions.md) for what is still undecided.

## 1.1 Purpose

A locally-run web application that answers one question with the household's own
historical data:

> *If I had owned a home battery over this period, operated under this policy, how much
> grid electricity — and, if I ask for it, how much money — would I have saved?*

It is a **retrospective counterfactual simulator**, not a forecaster and not a controller.

The two halves of that question are answered separately and the second is optional.
**Energy savings** — how many kWh of grid import the battery displaced — depend only on
the load, the generation and the policy. **Cost savings** depend on all of that plus a
model of the household's electricity contract: supply rates, energy tax, VAT, feed-in
compensation and feed-in charges. That model is a substantial amount of configuration and
much of it rests on 2027 tariffs nobody has published yet, so the app does not require it.
A user who wants only the kWh answer gets it without entering a single euro figure.

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

**Cost simulation is optional.** Users are not assumed to know their contract terms, and
2027 tariffs are not published, so the app does not demand them. It defaults to reporting
energy alone and asks for contract details only when the user opts in.

## 1.3 Regulatory regime — fixed decision

**This section applies only when cost simulation is enabled** (`cfg.simulate_cost`, §1.4).
A regulatory regime is a statement about how kWh are billed; an energy-only run bills
nothing and is regime-free. Everything below therefore describes the cost path.

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

- **Regimes must never be mixed within one cost calculation.** A cost figure is computed
  under a single regime — not blended per interval, not blended per configuration epoch.
  The pre-2027 extension point in [§6.5](10-pricing.md#65-price-curves) is specified as a
  separate netting *stage*, sitting after the flow simulation, for exactly this reason.

  The constraint is confined to money. **Energy-flow simulation is regime-independent:**
  which kWh the battery stores, shifts and returns depends on the load, the generation and
  the policy, not on how the resulting kWh are billed. A window may therefore span
  1 January 2027 freely; it yields one energy result for the whole window, and one cost
  result computed under the one selected regime. Metrics divide along the same line —
  see [§6.11](12-metrics-and-benchmarks.md#611-metrics). This is the same line the
  `simulate_cost` toggle cuts along: an energy-only run computes exactly the regime-free
  half.
- **The load profile is held fixed, and that is an assumption, not a measurement.** A
  household facing 2027 prices would over time shift consumption toward its own
  generation, which this simulator does not model and cannot infer. The effect biases
  results toward *understating* what a 2027 household would achieve, since it credits the
  battery with all of the shifting and the occupants with none of it. This is a
  counterfactual over prices and hardware, not a forecast of behaviour.

## 1.4 In scope (v1)

- Two data ingestion paths: direct Home Assistant access, and CSV upload of one file per
  data series, which the user collects from their energy supplier or PV installer.
- **Households with and without solar PV.** PV series are optional; the household declares
  which case applies, and the requirements, policies, topology choices, metrics and
  diagnostics that depend on PV are adjusted accordingly.
- **Cost simulation as an opt-in.** The household declares whether it wants money figures
  as well as energy figures (`cfg.simulate_cost`, answered on the results screen above the
  sections it adds, [§2′.7](20-workspaces-ux.md#27-where-the-setup-bands-questions-went),
  default **off**). With it off, the contract, tax, VAT and feed-in configuration is not asked
  for, the money results are not produced, and the app is usable end to end without any
  euro figure. See the note on what the toggle does and does not remove, below.
- Reconstruction of the battery-free household load, including stripping out an
  already-installed battery if its sensors are provided.
- Mixed-resolution input data, normalised onto a single uniform simulation grid.
- Three charge policies, three discharge policies, freely combinable.
- Three pricing models, named as the Dutch market names them: **dynamic** (follows the
  hourly EPEX spot price), **fixed** (one rate for the contract term) and **variable**
  (supplier-set, revised periodically) — used when cost simulation is on. Defined in
  [background E3.1](18-dutch-electricity-background.md#e31-the-three-forms).
- Predefined time ranges: last week / month / 3 months / 6 months / year.
- Results: energy saved (kWh and %), equivalent full cycles, self-consumption and
  self-sufficiency ratios, plus time-series and monthly breakdowns; and, with cost
  simulation on, money saved (EUR) and its exact decomposition.
- Two reference baselines so the headline number is interpretable:
  **no battery** (the counterfactual floor) and **perfect foresight** (the ceiling). The
  ceiling is computed against whichever quantity is being reported — euros saved, or kWh
  of grid import avoided ([§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)).
- Server-side persistence of raw data, parameters and selected range, restored on restart.
- **Configuration epochs**: detection of PV or battery commissioning part-way through the
  window, with the analysis made aware of it rather than silently averaging across it.
- **Installation topology** selection (PV coupling, battery phase configuration) via
  illustrated choices, since users reliably recognise a picture of their meter cupboard
  and reliably mis-answer the same question asked in words.
- **Price uncertainty bracketing** where the supplier bills per 15 minutes but the
  available energy data is hourly: how far the stated saving could shift, derived from the
  spot series' own finer spacing rather than asked of the user. Requires cost simulation.

### A price series is not a cost model

The `simulate_cost` toggle removes the **cost model** — the contract type, supply rates,
energy tax, VAT, feed-in compensation and terugleverkosten, and every euro figure derived
from them. It does **not** remove the **spot price series**, which stays a required input
in both modes.

The distinction matters because the spot price does two unrelated jobs. As a *dispatch
signal* it tells the battery when to charge and when to discharge: policies P2, D2 and D3
compare it against user-set bands, and that is a decision about which kWh move, not about
what they cost. As a *cost input* it feeds the supply price. Only the second job depends on
the cost model.

Keeping the series in both modes is what makes an energy-only run worth running. Charging
from the grid at cheap hours and discharging at expensive ones displaces grid import
whether or not anyone converts the result to euros — and for a household without solar it
is the *only* thing a battery does. Dropping the price series would leave such a household
with no usable charge policy at all.

### The two toggles together

`has_pv` and `simulate_cost` are independent, so there are four configurations. The rest of
this package describes each toggle's effect on its own; this table is the only place they
are combined.

| | **Cost simulation off** | **Cost simulation on** |
|---|---|---|
| **With PV** | kWh saved by storing surplus and by price-band arbitrage. No contract configuration. | The full product: kWh plus euros, waterfall, feed-in economics. |
| **Without PV** | kWh of grid import shifted by arbitrage alone. The narrowest configuration, and still meaningful. | Whether arbitrage clears the round-trip loss in euros — the question a no-PV buyer actually has. |

No combination is blocked. The narrowest cell — no PV, no cost — still produces a real
answer: how many kWh of grid import a price-band-driven battery would have displaced.

Moving right along a row **adds** results without changing any of them. Every kWh figure in
the left column reappears unaltered in the right: the same saving, the same cycles, the same
benchmark ceiling, the same kWh diagnostics. Cost simulation prices the flows; it does not
decide them, and it does not change what they are measured against. That guarantee is what
makes the toggle safe to switch on mid-session, and it is stated precisely in
[§4.5](07-internal-representation.md#shape-of-the-object-without-cost-simulation) and
enforced by fixture 18 in [16-validation-harness.md](16-validation-harness.md).

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
- Usage analytics, crash reporting and telemetry of any kind. The app runs on the user's own
  machine and keeps their data there, and it makes **no outbound report at all**. Asking for a
  feature that is not built yet is a GitHub issue the user files themselves
  ([§7.5](15-data-quality-and-limits.md#75-operational-notes)); the app composes a link and
  transmits nothing.

## Built incrementally behind a complete UI

The application is written one feature at a time, but the screens are laid out in full from
the start, so a control specified here may exist on screen before the machinery behind it
does. Such a control renders disabled with an affordance that says it is not built yet and
lets the user register that they want it
([§2.1](02-ux-wireframes.md#the-four-availability-states)).

Which controls are in that state at any moment is a fact about the build, not about the
product, and is deliberately not recorded in this package: it changes with every release.
Everything specified here is intended to exist. A control the user finds disabled today is
pending, not cut.

## 1.6 Success criteria

1. A user with a working HA instance can go from cold start to a result in under five
   minutes without reading documentation. Cost simulation defaults off precisely to protect
   this: reaching a first result must not require the user to know their supply rate, their
   feed-in terms or the current energy tax.
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
