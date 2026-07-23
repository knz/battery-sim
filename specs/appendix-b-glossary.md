# Appendix B — Glossary

> **Purpose:** the Dutch energy terminology and abbreviations used throughout this
> package.
> **Audience:** everyone, and non-Dutch implementers in particular.
> **See also:** [background E-C](18-dutch-electricity-background.md#appendix-e-c--glossary),
> a longer Dutch/English glossary that adds the metering and regulatory vocabulary
> (netbeheerkosten, capaciteitstarief, telwerk, actieve afnemer, DSMR). This table keeps
> the terms the specification itself uses, including the simulator-specific ones.

| Term | Meaning |
|---|---|
| Dynamic (dynamisch) | Contract whose bare price follows the hourly EPEX day-ahead market. |
| Fixed (vast) | Contract with one normaal and one dal rate, agreed for the term. |
| Variable (variabel) | Contract whose rate the supplier sets and revises periodically, typically every six months. |
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
| Cost simulation | The optional half of a run that converts kWh to euros: contract, tax, VAT, feed-in. Off by default (`cfg.simulate_cost`). |
| Dispatch signal | The spot price in its role of deciding *when* the battery charges and discharges, as opposed to its role as a cost input. Present in both cost modes. |
| MTU15 | 15-minute market time unit; EPEX settlement since 1 October 2025. |

Where these terms carry a modelling consequence:

- **Dynamic / fixed / variable** — the one-line entries above are summaries. The three
  types are defined in full in
  [background E3.1](18-dutch-electricity-background.md#e31-the-three-forms), which is the
  single place to change if a definition needs revising; the
  [§2.3 contract help popover](02-ux-wireframes.md#the-contract-type-help-affordance)
  defers to it as well. These same three words are the user-facing labels and the
  `DYNAMIC` / `FIXED` / `VARIABLE` values of `cfg.contract`
  ([§6.5](10-pricing.md#65-price-curves)) — the package carries no country qualifier on
  them, being single-jurisdiction throughout.
- **Salderingsregeling** — the pre-2027 regime is out of scope, but the pricing engine
  keeps an extension point for it ([§6.5](10-pricing.md#65-price-curves)). The regime binds
  the cost path only; energy flows and the kWh metrics derived from them are
  regime-independent ([§1.3](01-product-brief.md#13-regulatory-regime--fixed-decision)).
- **Terugleververgoeding / terugleverkosten** — the two halves of `export_price_net`,
  whose difference may be negative ([§6.5](10-pricing.md#65-price-curves)).
- **Vastrecht** and **vermindering energiebelasting** — battery-invariant, therefore
  excluded from savings ([§6.10](10-pricing.md#610-cost-accounting)).
- **Normaal / dal** — which register is which is detected from when each accrues, not
  assumed from its label, and only when a bill is being computed
  ([§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use)).
  Whether both registers are present at all is a separate question, about the meter
  installation rather than the contract, and is checked in both cost modes.
- **Intern salderen** — the reason the overlap diagnostic is a clean measure of temporal
  resolution loss ([§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly)).
- **MTU15** — the reason a price bracket is needed when energy data is hourly
  ([§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)).
