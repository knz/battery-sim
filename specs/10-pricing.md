# 6.5, 6.10 Pricing and cost accounting

> **Purpose:** turning contract configuration into the two price arrays every run is
> costed against, and turning flows into a cost and an exact savings decomposition.
> **Audience:** backend, domain layer.
> **Read with:** [09-ingest-algorithms.md](09-ingest-algorithms.md) §6.4 (supplies
> `tariff_zone`), [11-policies-and-battery.md](11-policies-and-battery.md) (supplies the
> flows), [appendix-b-glossary.md](appendix-b-glossary.md) for the Dutch terms.

§6.5 and §6.10 are kept together because they are two halves of one calculation: the
waterfall consumes the price arrays directly.

## 6.5 Price curves

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

      compensation = alpha * bare + beta       # per interval, NOT clamped here
      net          = compensation - terugleverkosten

    The statutory "compensation may not be negative" floor is NOT applied per
    interval -- see the feed-in floor note below. Both the per-interval
    compensation and the net after charges may be negative.

    No energy tax and no VAT on feed-in for private consumers.
    """
    compensation = cfg.feedin_alpha * bare + cfg.feedin_beta
    if cfg.tlk_mode == FLAT:
        tlk = cfg.tlk_eur_per_kwh
    else:
        tlk = tiered_tlk_rate(cfg.tlk_tiers, annual_export_kwh)   # see note
    return compensation - tlk


def feedin_floor_topup(export_kwh, compensation, index, cfg):
    """
    The statutory floor on feed-in compensation, applied over the assessment
    period rather than per interval. Returns EUR to be credited over the
    window -- zero in all but exceptional periods.

    Wet beeindiging salderingsregeling: the compensation may not be a negative
    amount, and an amendment fixed that this is assessed over a period of AT
    LEAST ONE MONTH, not instant by instant. Individual negative-price
    intervals therefore do not breach the floor as long as the period
    aggregate is non-negative.
    """
    if cfg.feedin_floor_mode == PER_INTERVAL:
        # v1.1 behaviour, retained for reproducibility. Stricter than the law.
        return (export_kwh * maximum(0.0, -compensation)).sum()

    topup = 0.0
    for period in calendar_periods(index, cfg.feedin_floor_period):   # default: month
        earned = (export_kwh[period] * compensation[period]).sum()
        topup += max(0.0, -earned)
    return topup
```

### The feed-in floor is a period aggregate, not a per-interval clamp

This is the one place where the specification cannot be expressed as a per-interval price
array, and it is worth being precise about why and about which direction it moves the
answer.

Writing `c(t) = α·bare(t) + β` for the unclamped compensation, the two readings are:

| Reading | Compensation revenue over a period |
|---|---|
| Per-interval clamp (v1.1) | `Σ export(t)·max(0, c(t))` |
| Period floor (the law) | `max(0, Σ export(t)·c(t))` |

The first is **always greater than or equal to** the second, because clamping discards
every negative term individually while the aggregate lets them offset positive ones. So
moving to the legally correct rule **reduces** modelled feed-in revenue; it does not
increase it. The floor itself — the `max(0, …)` on the outside — only ever binds in a
period whose export earned a net negative amount overall, which is rare.

The second-order effect runs the other way. Feed-in revenue accrues mostly to the
*baseline*, since a battery's job is to export less. Reducing modelled feed-in revenue
therefore reduces the baseline's earnings more than the battery scenario's, which slightly
**increases** modelled battery savings. The magnitude is small — it is bounded by the
export-weighted negative part of `c(t)`, which is nonzero only during negative-price hours
— but it is not zero on a dynamic contract in a windy spring.

Three consequences for the implementation:

1. **`p_export_net` is no longer the whole story.** `compute_costs` below takes the
   per-interval array *plus* the period top-up. Do not fold the top-up into the array;
   there is no correct per-interval allocation of it, only conventions.
2. **The window edges are partial periods.** A window that starts mid-month leaves a
   partial month at each end. Assess the floor over the partial period and flag it, rather
   than dropping the partial period or extrapolating it. For windows shorter than one
   assessment period the floor is assessed over the whole window, which is a weaker
   constraint than the law imposes — record it in `diagnostics`.
3. **The assessment period is configurable.** The law says "at least one month", so a
   supplier may legally use a longer one. `feedin_floor_period` defaults to a calendar
   month; see [open question §8.14](17-open-questions.md).

`feedin_floor_mode = PER_INTERVAL` is retained so v1.1 numbers remain reproducible, and
because a supplier may in practice choose to guarantee a non-negative compensation in every
interval — a stricter offer than the law requires, which some may market as a feature.

Presets for `(alpha, beta)`:

| Preset | α | β | Meaning |
|---|---|---|---|
| Legal minimum | 0.50 | 0.0000 | Statutory floor, valid to 1 Jan 2030 |
| Spot minus fee | 1.00 | −0.0200 | Typical dynamic supplier offer |
| Spot | 1.00 | 0.0000 | Optimistic |
| Fixed amount | 0.00 | *user* | Fixed/variable contracts with a flat feed-in rate |

What counts as the "bare supply price" for a *dynamic* contract's feed-in reference is
[open question §8.1](17-open-questions.md) — it moves feed-in revenue by roughly 1 ct/kWh.

> **Tiered terugleverkosten.** From 2027 these must be expressed per fed-in kWh, so
> `FLAT` is the default and the expected shape. Tiered support is retained because some
> suppliers may keep annual-volume staffels, and a staffel makes savings a **step
> function** of annual export — reducing export by 200 kWh can be worth €0 or €40
> depending on which side of a tier boundary you land. When `tlk_mode == TIERED` the tier
> must be resolved from **annualised** export, so it is unavailable for windows under
> 90 days; fall back to `FLAT` with a visible notice. See
> [§7.4](15-data-quality-and-limits.md#74-window-anchoring-and-short-window-guard).

> **What shapes terugleverkosten may legally take.** The 2027 law restricts feed-in
> charges in two ways that bound the plausible preset space
> ([background E5.2](18-dutch-electricity-background.md#e52-the-rules-on-compensation)
> provision 4). They may be levied only on **active customers** — those who actually feed
> in — rather than spread across the whole customer base; and charges that are
> discriminatory, or not directly or indirectly related to feed-in, are prohibited for
> households and micro-enterprises. Two implications for this app: a preset shaped as a
> fixed standing charge borne by all customers is not a legal shape and should not ship;
> and a per-fed-in-kWh charge is not merely the expected shape but close to the only
> clearly compliant one. Annual-volume staffels remain arguable, since volume is plainly
> related to feed-in, which is why `TIERED` is retained rather than removed. This bears on
> [open question §8.5](17-open-questions.md).

> **Pre-2027 extension point.** Reintroducing salderen means adding an annual netting
> stage between the flow simulation and the cost accounting, not changing these
> functions. Keep `compute_costs` (§6.10 below) operating on flow arrays so that stage can
> be inserted.

## 6.10 Cost accounting

```python
def compute_costs(flows, p_import, p_export_net, compensation, index, cfg):
    """EUR over the window. Vectorised apart from the period floor."""
    per_interval = ((flows.imp * p_import).sum()
                    - (flows.exp * p_export_net).sum())     # [vectorisable]
    return per_interval - feedin_floor_topup(flows.exp, compensation, index, cfg)
```

Note the export term is *subtracted* and `p_export_net` may itself be negative — in which
case exporting increases the bill. That is the intended behaviour under the 2027 regime
during negative-price hours, and it is one of the more important things this tool can
show a user.

The top-up is subtracted as well, because it is money received: it reduces the bill. It is
zero in almost every window — see the feed-in floor note in §6.5 above — but it is carried
through here rather than dropped, so that the waterfall below closes exactly.

**Waterfall decomposition** (exact, because per interval
`Δcost = Δimp·p_imp − Δexp·p_exp_net` and splitting by sign is lossless). `A`, `B` and `C`
are the first three of the four runs defined in
[§6.9](11-policies-and-battery.md#69-main-simulation-loop):

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
      ("feedin_floor_topup",          topup(C) - topup(A)),
      ("degradation",                -cfg.degradation_eur_per_kwh * C.withdrawn.sum()),
    ]
    # invariant, assert in tests:
    #   sum(waterfall) == cost(A) - cost(C) - degradation
```

That invariant is fixture 4 in [16-validation-harness.md](16-validation-harness.md).

**Why the top-up needs its own line.** The other terms are per-interval quantities split
by sign, which is why the decomposition is exact rather than approximate. The floor top-up
is a period-level scalar with no per-interval decomposition (§6.5), so folding it into
`lost_feedin_compensation` would silently turn an exact identity into an allocation
convention. As its own term it stays exact: it is the *difference* between the top-up the
baseline would have received and the top-up the battery scenario receives, which is what
the battery actually changed. Because the battery exports less, it is usually zero on both
sides and therefore zero in the waterfall; it becomes visible only in a period whose export
earned a net negative amount in one scenario and not the other.

Fixed costs — vastrecht, netbeheerkosten, vermindering energiebelasting — are
**excluded**. They do not change with a battery, so including them would only dilute the
percentage. Show them, greyed out, in an informational strip if total-bill context is
wanted later.

The test for inclusion is whether a component responds to consumption at all, and the
authority is the table in
[background E2.5](18-dutch-electricity-background.md#e25-which-components-respond-to-behaviour).
The two exclusions worth understanding rather than memorising:

- **Netbeheerkosten** are a *capaciteitstarief* — a fixed annual amount set by the size of
  the connection, not by the energy flowing through it. A 1×25 A connection pays the same
  whether it draws 500 or 5,000 kWh a year, so no battery, no solar array and no
  behavioural change reduces it. Only physically downgrading the connection does.
- **Vermindering energiebelasting** is a flat annual credit per connection, €519.80 excl.
  VAT in 2026. It does not scale with consumption and cancels exactly out of any
  before-and-after comparison.
