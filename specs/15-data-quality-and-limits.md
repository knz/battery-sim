# 7.2–7.5 Modelling limits, quality checks, anchoring and operations

> **Purpose:** what the model knowingly gets wrong, the ordered list of validation checks,
> how time windows are anchored, and how the app is meant to be run.
> **Audience:** everyone. §7.2 in particular is worth reading before implementing the
> domain layer rather than after.
> **Read with:** [14-diagnostics.md](14-diagnostics.md) for the measurements several of
> these checks consume.

## 7.2 Known modelling limitations — state these in the UI, not just here

1. **Baseline curtailment must match.** If an export limit is configured, run A must apply
   it too. Curtailing PV only in the battery scenario would credit the battery with
   avoiding a constraint the baseline never faced. Easy to get wrong; assert in tests.
   See [§6.8](11-policies-and-battery.md#68-battery-step-function) step 6.
2. **DC-side battery sensors break reconstruction.**
   [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) assumes AC-side
   measurements. DC-side figures put conversion losses on the wrong side of the balance
   and silently bias the reconstructed load. Ask the user which they mapped; if unknown,
   check whether `Σcharge > Σdischarge` by roughly the expected round-trip loss (AC-side)
   or by substantially less (DC-side).
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
8. **The load profile is held fixed across the regime change.** The input data was
   recorded by a household living under salderen, which gave it no financial reason to
   shift consumption toward its own solar. A household facing 2027 prices would gradually
   change that behaviour. The simulator changes the prices and adds the battery but leaves
   the occupants' habits exactly as recorded, which credits the battery with all of the
   load-shifting and the household with none of it. The direction is *conservative* —
   savings are understated relative to what a 2027 household would achieve — but the
   magnitude is unknown and unmeasurable from the data.
   See [§1.3](01-product-brief.md#13-regulatory-regime--fixed-decision) and
   [background E4.2](18-dutch-electricity-background.md#e42-why-this-matters-for-battery-analysis).

9. **Without PV, the result rests entirely on the price series.** A PV household's saving
   comes largely from storing surplus, which is measured; a no-PV household's saving comes
   entirely from the spread between charge and discharge prices, so every modelling choice
   about prices — the markup, the settlement convention
   ([§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)),
   the tariff-zone rule — lands on the headline figure undiluted. Under a fixed contract
   with a single tariff register there is no spread at all and the honest answer is that
   the battery saves nothing but its own standby draw, which the simulator will duly
   report as a negative saving. That is correct output, not a fault.

   This is sharpest in the narrowest configuration — no PV and no cost simulation — where
   the result is driven entirely by the user's own charge and discharge bands acting on the
   spot series. The kWh figure is genuine, but it measures the band configuration at least
   as much as it measures the battery, and the UI should not let it read as a
   property of the hardware alone.

10. **An energy-only run cannot tell the user whether the battery is worth buying.** It
    reports kWh of grid import avoided, which is a real and correctly-measured quantity,
    but grid import avoided at 3 a.m. and grid import avoided at 6 p.m. are worth very
    different amounts and the energy figure weights them identically. Cost simulation is
    what distinguishes them. Since it defaults off, the energy-only results panel must not
    frame its output as an investment answer, and the affordance offering cost simulation
    ([§2.4](02-ux-wireframes.md#panel--without-cost-simulation)) exists partly for this reason.

A further known gap — a 1-phase battery on a 3-phase connection, where the per-phase power
ceiling cannot be modelled without per-phase data — is handled as a soft block in
[§2.5](03-topology-selector.md) and raised as
[open questions §8.7 and §8.9](17-open-questions.md).

## 7.3 Data quality checks, in execution order

| # | Check | Action on failure |
|---|---|---|
| 1 | Timestamps carry a UTC offset | Reject the file, explain DST ambiguity. On the CSV path this is per slot and recoverable — see below |
| 2 | Series monotonic where `kind=cumulative` | [§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas) reset handling, count and flag |
| 3 | Gap detection at > `gap_factor`× native resolution | Flag; exclude from sums; report hours |
| 3b | Price series downsampled onto a coarser grid by a factor ≥ 2 ([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)) | Warn; set `diagnostics.price_granularity_lost`. Do not block |
| 4 | Required series present: grid registers, spot price, **and solar per the declared PV state** | Block run, name the missing series |
| 5 | Windows of the mapped series overlap | Restrict to intersection, report |
| 6 | Reconstructed load ≥ 0 | Clamp, flag, warn with likely causes ([§6.3](09-ingest-algorithms.md#63-household-load-reconstruction)) |
| 6b | *No PV declared:* sustained daytime export ([§6.15](13-configuration-epochs.md#undeclared-pv)) | Ask the user whether they have PV; do not change `has_pv` automatically |
| 7 | `overlap_pct` ([§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly)) | Warn per the table there — *PV households only*; without PV route a nonzero value to 6b |
| 8a | Both meter registers present and accruing ([§6.4](09-ingest-algorithms.md#1-register-availability)) | Warn: probable incomplete mapping or installation. Do not block |
| 8b | *Cost only:* tariff zone rule vs registers ([§6.4](09-ingest-algorithms.md#3-which-zone-applies-to-a-simulated-interval)) | Warn above `tariff_zone_mismatch_pct` mismatch |
| 9 | *PV only:* implausible PV: `pv > 0` at local solar midnight | Warn — likely a mismapped sensor |
| 10 | Implausible totals: PV > `pv_yield_max_kwh_per_kwp`, load > `load_max_kwh_per_year` | Warn, do not block |
| 11 | Config: `soc_min < soc_max`, powers > 0, `rte_min < RTE ≤ 1.0` | Block with field errors |
| 12 | Config: charge band ∩ discharge band = ∅ | Warn, allow (netting handles it — [§6.7](11-policies-and-battery.md#67-discharge-policy)) |
| 13 | Window ≥ `min_annualisation_days` for annualisation; *cost only:* ≥ `min_tlk_tiering_days` for tiered TLK | Disable those features, explain |
| 14 | Configuration epoch boundaries ([§6.15](13-configuration-epochs.md)) | Offer to restrict window; block annualisation if spanning |
| 15 | Undeclared battery heuristics ([§6.15](13-configuration-epochs.md#undeclared-batteries)) | Ask the user; do not assert |
| 16 | *PV only:* cross-correlation lag between PV and meter ([§6.17](14-diagnostics.md#617-timestamp-misalignment-detection)) | Offer a shift; never apply silently |
| 17 | Power-vs-energy residual, where both mapped ([§6.17](14-diagnostics.md#617-timestamp-misalignment-detection)) | Warn above `residual_mean_warn_pct` mean or `residual_diurnal_warn_pct` diurnal |
| 18 | Unsupported phase topology selected ([§2.5](03-topology-selector.md)) | Soft block; set `topology.approximated` |

**Where these checks run on the CSV path.** Checks 1 and 2 are per-file format checks and
run as each upload arrives, against the format expected for the slot it was dropped into
([§4.2](05-data-formats.md#42-the-per-series-file-format)). A failure is reported on that
slot and the user supplies another file for it; the other slots keep their contents, the
session does not enter an error state, and the run is not attempted. Everything from
check 3 onward runs once against the assembled dataset, so those checks see a complete set
of validated files whichever source path produced them.

Checks marked *PV only* are **skipped** when `has_pv = false`, and those marked *cost only*
are skipped when `simulate_cost = false`. In both cases they are reported as **skipped
rather than as passed**. A quality panel that shows a green tick beside "solar sensor
plausibility" for a household with no solar sensor, or beside "tariff zone rule" for a run
that priced nothing, is telling the user something false about how much the data was
checked.

Check 4 is two-sided on PV. It blocks when `has_pv = true` and no `solar_production`
series was mapped, and equally when a `solar_production` series was supplied while
`has_pv = false` — the latter is a contradiction, not a harmless extra, since one of the
two answers is wrong and the app cannot tell which. Name the conflict and let the user
resolve it. It is **not** two-sided on cost: `price_spot` is required in both cost modes
because the charge and discharge bands consume it
([§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model)), so there is no cost mode
in which its presence is a contradiction.

Check 3b is deliberately narrow and deliberately not cost-gated. Narrow: only *price*
series can be finer than the grid, since the grid is the coarsest energy series, and only
averaging a price loses information — energy summed into a coarser bucket is exact and a
price held across a finer one is exact for a step function
([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)). The
factor-of-2 threshold keeps it attached to the case that costs the user something, chiefly
quarter-hourly prices against an hourly meter, rather than firing on a spacing that differs
by rounding. Not cost-gated: the averaging happened before dispatch, and the charge and
discharge bands compare against the spot series in both cost modes
([§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model)), so an energy-only run
carries exactly the same error. What *is* cost-gated is
[§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch), which
bounds what the averaging did to the euro figure — a different question, asked only when
there is a euro figure.

Check 8 is split because its two halves ask different questions. **8a** asks whether the
meter's two registers are both present and accruing — a fact about the installation and the
mapping, independent of any contract, and therefore checked in both cost modes. **8b** asks
whether the *configured day/night window* agrees with when those registers actually
accrued, which matters only to a bill and is skipped without cost simulation. Running 8b
without 8a passing is meaningless and it is skipped in that case too.

## 7.4 Window anchoring and short-window guard

Predefined ranges anchor to the **last timestamp present in the data**, not to `now()`.
If the HA instance stopped recording three days ago, "last week" means the final seven
days of data, and the UI states the actual dates. Anchoring to wall-clock time silently
produces a window that is partly empty and a savings figure that is quietly too low.

If the requested range exceeds available coverage, clamp to coverage and say so; never
pad with zeros.

Annualised projections are disabled below `min_annualisation_days` (default 90). Battery
savings are strongly seasonal — a summer week has abundant surplus and a battery that
saturates by noon, a winter week has almost no surplus and value comes only from price
arbitrage. Scaling either to a year is wrong by a factor of roughly 2–3 in opposite
directions.

A separate floor, `min_tlk_tiering_days`, gates tiered terugleverkosten, which must be
resolved from annualised export — see [§6.5](10-pricing.md#65-price-curves). That half of
the check applies only when cost simulation is on. It defaults to the same 90 days but is a
distinct concern — one bounds seasonal projection error, the other the noise in an
annualised export total — so the two are separate constants that happen to share a default,
not one value reused. Annualisation itself applies in both modes: an
annualised kWh saving is projected from a short window with exactly the same seasonal error
as an annualised euro saving, so the guard is not a cost feature. Annualisation is also
disabled when the window spans a configuration-epoch boundary
([§6.15](13-configuration-epochs.md#effects-on-the-rest-of-the-application)).

**Partial assessment periods for the feed-in floor.** Applies to cost simulation only.
The statutory floor on feed-in
compensation is assessed over a calendar month by default, so an arbitrary window leaves a
partial month at each end. Assess the floor over the partial period as it stands and
record the count in `diagnostics.feedin_floor_partial_periods`; do not drop the partial
period, and do not extrapolate it to a full month. A window shorter than one assessment
period is assessed over the whole window, which is a weaker constraint than the law
imposes — set `diagnostics.feedin_floor_shorter_than_period` so the result carries the
fact. The effect is small in every ordinary case, but it means two runs over slightly
different windows can differ by more than the difference in their data.

## 7.5 Operational notes

- **Bind to `127.0.0.1` by default.** If the user wants LAN access, make them change the
  bind address deliberately and show a warning when the bind address is not loopback.
- **The Home Assistant token stays in the browser.** The fetch runs in the browser
  ([§4.3](06-home-assistant-ingestion.md)), so the long-lived access token — a full-privilege
  credential — is held in the browser's local storage and sent only to the Home Assistant
  instance the user entered. It **never reaches the application backend**, is never written to
  the database, and there is no server-side token store to encrypt. Clearing the browser's
  storage removes it. The UI should say plainly that the token lives in the browser and goes
  only to the user's own Home Assistant.
- **Never log the token.** It is not present server-side to log; the browser fetch code must
  likewise keep it out of any console/debug output.
- **What the app sends out, and when.** From the browser: Home Assistant requests, to the URL
  the user entered. From the backend: spot-price fetches to `api.energy-charts.info`, and
  feature-interest reports (below). The rows the browser forwards to the backend over
  `WS /data/ingest/ws` are energy/price statistics the user asked to import — they stay on the
  backend and are never onward-transmitted; the HA token is not among them. Parameters, results
  and the contents of the database are never transmitted anywhere. The two backend egress cases
  are named next.
- **Backend spot-price fetch, only when the preset source is selected.** When the user picks the
  preset Energy-Charts NL source for the spot-price slot
  ([§2.2](02-ux-wireframes.md#22-panel--data-input-expanded),
  [§4.3](06-home-assistant-ingestion.md)), the backend fetches NL day-ahead prices from
  `api.energy-charts.info` to bridge the committed on-disk data to the end of the requested
  range. This is one of the two things the backend sends out. What is sent is a **bidding zone
  (`NL`) and a date range, and nothing else** — no user data, no energy data, no parameters, no
  identifier. It fires **only** when the user selects that source, and not at all if the
  spot-price slot is filled from Home Assistant instead. The endpoint is a fixed public URL that
  needs no key ([§5.4](08-architecture.md#54-configuration)).
- **Feature-interest reports are off unless an endpoint is configured.** Clicking the
  thumbs-up on a not-built-yet control ([§2.1](02-ux-wireframes.md#the-pending-affordance))
  always increments a local counter. It additionally POSTs to `feature_interest_url`, which
  is **empty in a stock configuration**, so on an installation nobody has configured, nothing
  is ever transmitted. Where it is set, the body is three fields and no more: the feature key
  (a short string such as `battery_rte`), the application version, and the installation id.
  No energy data, no parameters, no results, no hostname, no IP beyond what any HTTP request
  discloses. The request is asynchronous and fire-and-forget: failures are ignored, nothing
  is retried or queued, and the user is never told either way.
- **The installation id is a persistent pseudonymous identifier, and should be described as
  one.** It is a random value generated on first run and stored in `config.toml`. It is not
  derived from the hardware, the MAC address, the hostname, the user account, the household
  or anything about the data — it carries no information about who or where the installation
  is, what it consumes or how it is configured. But it is deliberately **stable across
  runs**, because its purpose is to let ten clicks from one household be counted as one
  household rather than ten. That stability is exactly what makes it an identifier: an
  endpoint operator can tell that two reports came from the same installation. This is a real
  property and the UI should not describe it as anonymous. Deleting the `installation_id`
  line from `config.toml` generates a new one at the next start, which breaks the link to
  everything sent before. The id only ever leaves a machine whose operator set an endpoint;
  with the endpoint unset it is a local value that is never used.
- Target performance: hourly year (8,760 intervals) end-to-end under 3 s including the DP;
  5-minute month (8,640 intervals) comparable. 5-minute year (105k intervals) is the case
  that may need Numba — see [§5.3](08-architecture.md#53-compute).
- Language: English UI in v1. Dutch is likely wanted later given the audience — keep user
  strings in a single catalogue module rather than inline in templates.
