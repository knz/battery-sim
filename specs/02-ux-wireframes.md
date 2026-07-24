# 2. UX wireframes

> **Purpose:** the single-page layout and the three stepper panels.
> **Audience:** frontend.
> **Read with:** [03-topology-selector.md](03-topology-selector.md) for the illustrated
> selectors referenced from panel ②, and [04-state-machine.md](04-state-machine.md) for
> the state transitions these panels drive.

## 2.1 Overall layout

Single page, a **setup band** followed by three stacked panels acting as a stepper.
Completed panels collapse to a one-line summary and can be reopened at any time. Reopening
and editing does **not** discard results — it marks them stale and triggers a
recalculation.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Home Battery Simulator                          [workspace: local]  [⚙]     │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ Before you start ─────────────────────────────────────────────────────┐  │
│  │  Do you have solar PV?      ( • ) Yes    (   ) No                      │  │
│  │  Simulate cost savings?     (   ) Yes    ( • ) No                      │  │
│  │  ⓘ These two answers decide what the app asks you for below.           │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ ① DATA                                            ✓ 412 days  [edit ▾] │  │
│  │    Home Assistant · 5 series · simulated hourly                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Your data at a glance ─────────────────────────────── (see 2.3a) ─────┐  │
│  │  4,129 kWh imported · 31% self-sufficient · … (shown once data loads)  │  │
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

### The setup band

The band carries the two choices that decide the *shape* of everything below it — which
series the data panel asks for, which boxes the parameter panel shows, and which sections
the results panel renders:

- **`has_pv`** — *do you have solar PV?*
- **`simulate_cost`** — *simulate cost savings?* (default off)

It is a **scope selector, not a stepper panel**: it does not collapse to a summary, does
not carry a `[?]` or a CTA, and is not numbered. It sits above panel ① because the natural
order of use is to answer it first — a user cannot sensibly map sensors or upload files
before the app knows whether it should be asking for a solar series or for cost-only
inputs. The band is the **single source of truth** for both choices; they appear nowhere
else as controls.

**The band is editable at any time**, including after data is loaded. Changing either
answer re-derives the panels below in place — showing or hiding rows and boxes against the
new answer — **retains** any values already entered in still-applicable fields, and marks
results stale so they recalculate ([§3.2](04-state-machine.md#32-events)). It never
discards a loaded dataset or resets the configuration; a user who toggles a choice and
toggles it back finds their earlier inputs where they left them. What each answer controls
is set out per panel in §2.2 (data slots), §2.3 (parameter boxes) and §2.4 (result
sections).

The panel ① summary line reports the **simulation grid**, not any one series' native
resolution — one line cannot carry a per-series fact, and the grid is the figure that
applies to every number downstream. The per-series breakdown is in the expanded panel
([§2.2](#granularity-per-series)).

The panel ② summary line ends with the run's cost mode: the contract name
(`dynamic`, `fixed`, `variable`) when cost simulation is on, and `energy only`
when it is off. That word is the fastest way for a user to see, from the collapsed state,
which of the two products they are looking at.

### The four availability states

A control described in this package is not always usable, and it is unusable for four
different reasons. Each renders differently, because each means something different, and
confusing them is the fastest way to make the app feel broken.

| State | Rendering | Why | Clears when |
|---|---|---|---|
| **Available** | Normal | — | — |
| **Inapplicable** | **Absent** | The configuration gives it no meaning | The user changes the configuration |
| **Blocked** | Disabled, greyed | A precondition is unmet | The user satisfies the precondition |
| **Soft-blocked** | Selectable, warns, offers an approximation | The model cannot represent the choice | A later version models it |
| **Pending** | Disabled, greyed, with a `[?]` affordance | Specified, but not built yet | The next increment ships it |

The soft block has one instance, the unsupported battery phase topologies in
[§2.5](03-topology-selector.md); it is listed here so it is not mistaken for either of the
two states it sits between.

**Inapplicable is hidden, never greyed.** With `has_pv` off there is no solar row; with
`simulate_cost` off there is no Pricing box. A greyed control invites the user to work out
how to un-grey it, and here there is nothing to work out that the toggle does not already
say. This rule is applied throughout §2.2, §2.3 and §2.4.

**Blocked is greyed, because the user can clear it.** `[ Load data ]` while a slot is empty,
the annualised figure under `min_annualisation_days`. The greying is the message: this becomes available when
you do something, and the adjacent text says what.

**Pending is different in kind from the other three, and the difference is the point.**
Inapplicable and blocked are properties of the user's *configuration*; the soft block in
[§2.5](03-topology-selector.md) is a property of what the model can *represent*. All three
are permanent facts about a situation. Pending is a property of **build progress**: the
application is built one feature at a time behind a UI that is laid out in full from the
start, so a control can be fully specified here and not yet wired to anything. It is a
temporary condition and is expected to disappear.

This has a direct consequence for the specification: **which controls are pending is not
recorded here.** It changes with every release, and a list in the spec would be wrong within
a week of being written. Any control described in this package may render pending while its
machinery is outstanding; the state is removed as each feature lands, and no other text
changes when it is. A reader encountering a pending control in a running build must not
infer that the feature was cut — the specification is the statement of intent, and the
control's presence in it is the commitment.

### The pending affordance

A pending control renders disabled with a small `[?]` button beside it. The button opens the
dialog below, in which `<control>` stands for whichever control was clicked — the wireframe
is the template, not a statement that any particular control is pending:

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Not built yet                                                       │
  │                                                                      │
  │     <Control> is part of the plan for this simulator, but it is      │
  │     not built yet. The app is being written one feature at a time    │
  │     and this one has not been reached.                               │
  │                                                                      │
  │     If you would use it, say so. It tells us what to build next,     │
  │     and it is the only signal we get.                                │
  │                                                                      │
  │  [ 👍  I want this ]                                        [ close ]│
  └──────────────────────────────────────────────────────────────────────┘
```

The user-facing wording is **"not built yet"**, not "not in v1". The two say different
things: "not in v1" is a release decision, and this is not one — the work simply has not
happened yet. The label the topology selector uses for its unsupported options
([§2.5](03-topology-selector.md)) *is* a release decision and correctly reads `not in v1`.

**Clicking the thumbs-up** increments a per-feature counter and, if an endpoint is
configured, fires an asynchronous POST
([§5.1](08-architecture.md#51-diagram), [§7.5](15-data-quality-and-limits.md#75-operational-notes)).
The dialog acknowledges in place — the button becomes `✓ Noted` and the text below it reads
*"Thanks. We have recorded that you want this."* Reopening the dialog for a feature already
thumbed shows that state rather than a fresh button, and **a second click does not count
twice**.

**No count is ever shown to the user.** On a single-household installation the number is
either 1 or 0, which tells the user nothing, and any figure shown next to a thumbs-up is
read as a global tally that it is not.

**The dialog never reports failure.** The POST is fire-and-forget; a timeout, a refused
connection or an unset endpoint all leave the acknowledgement exactly as described. The
counter write is local and does not depend on the request.

**Feature keys.** Each pending control carries a short stable string key naming it in the
counter table and in the POST body, formed from the box and the control: `battery_rte`,
`spot_source_upload`, `export_csv` are the shape, not a list of pending features. The keys
are a closed vocabulary: they are allocated when a control is first marked
pending and are not reused for anything else afterwards, so a counter row keeps its meaning
after the feature ships and the control stops being pending. Same discipline as the series
names in [§4.1](05-data-formats.md), and for the same reason: a key that quietly changes
meaning makes every historical row a lie.

## 2.2 Panel ① — Data input (expanded)

The panel is **slot-first**: it leads with the roster of data slots
([§4.1](05-data-formats.md#41-the-series-vocabulary)) and lets the user choose, *per slot*,
where that slot's data comes from. This is the inverse of an earlier draft that asked for the
source once and applied it to the whole panel. The reason for the flip is that different slots
have genuinely different sources available: an energy meter can only come from the user's own
records (Home Assistant today, an uploaded CSV later), but the spot price can come from Home
Assistant *or* from a preset historical dataset the app ships. Asking "what is the source"
before the slot is known forces a single answer onto a set of slots that do not share one.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ① DATA                                                            [collapse] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Pick where each series comes from. Choose a source per slot; for Home       │
│  Assistant, connect once from the source drawer (Configure) and that         │
│  connection is reused by every slot that uses it.                            │
│                                                                              │
│  ┌─ Series slots ─────────────────────────────────────────────────────────┐  │
│  │  ROLE              REQ  SOURCE                                          │  │
│  │  ──────────────────────────────────────────────────────────────────    │  │
│  │  Grid import T1     ●  [ Home Assistant · sensor.…import_t1        ▸ ]  │  │
│  │  Grid import T2     ●  [ Home Assistant · sensor.…import_t2        ▸ ]  │  │
│  │  Grid export T1     ●  [ Home Assistant · sensor.…export_t1        ▸ ]  │  │
│  │  Grid export T2     ●  [ Home Assistant · sensor.…export_t2        ▸ ]  │  │
│  │  Solar production   ◐  [ Home Assistant · choose entity…           ▸ ]  │  │
│  │  Battery charge     ○  [ Choose source…                            ▸ ]  │  │
│  │  Battery discharge  ○  [ Choose source…                            ▸ ]  │  │
│  │  Spot price         ●  [ Preset historical (Energy-Charts NL)      ▸ ]  │  │
│  │  Spot price (min)   ◒  [ Choose source…                            ▸ ]  │  │
│  │  Spot price (max)   ◒  [ Choose source…                            ▸ ]  │  │
│  │                                                                        │  │
│  │  Each row's [ … ▸ ] opens the source drawer for that slot; the button  │  │
│  │  shows the chosen source and, for Home Assistant, the bound entity.    │  │
│  │                                                                        │  │
│  │  ● = required.  ○ = optional.                                          │  │
│  │  ◐ = required only if you have solar PV.                               │  │
│  │  ◒ = offered only if you simulate costs (intra-hour price bracketing). │  │
│  │  Both answers come from the setup band above.                          │  │
│  │  Spot price drives the charge and discharge bands, so it is required   │  │
│  │  whether or not you simulate costs.                                    │  │
│  │  Both meter registers should be mapped. See "Tariff registers" below.  │  │
│  │                                                                        │  │
│  │                                              [ Fetch history ]         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Data quality ─────────────────────────────────────────────────────────┐  │
│  │  Coverage        2025-06-01 → 2026-07-21   (416 days)                  │  │
│  │                                                                        │  │
│  │  Simulation grid   hourly  ·  8,760 intervals                          │  │
│  │                                                                        │  │
│  │  SERIES              RECORDED AT                THE RUN USES           │  │
│  │  ────────────────────────────────────────────────────────────────      │  │
│  │  Grid import T1      hourly (full)              hourly                 │  │
│  │                      5-min (last 9 days)                               │  │
│  │  Grid import T2      hourly (full)              hourly                 │  │
│  │                      5-min (last 9 days)                               │  │
│  │  Grid export T1      hourly (full)              hourly                 │  │
│  │                      5-min (last 9 days)                               │  │
│  │  Grid export T2      hourly (full)              hourly                 │  │
│  │                      5-min (last 9 days)                               │  │
│  │  Solar production    hourly (full)              hourly                 │  │
│  │  Spot price          15-min (full)            ⚠ hourly, averaged       │  │
│  │                                                                        │  │
│  │  ⚠  Your prices change every 15 minutes but your meter records hourly, │  │
│  │     so the run sees one averaged price per hour and cannot act on      │  │
│  │     within-hour swings.                           [ what is this? ]    │  │
│  │                                                                        │  │
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

### The per-slot source drawer

The `▸` on a slot row opens a right-side drawer listing the sources available **for that
slot** — different slots offer different sets, decided by each source's `available_for` rule
([§5.1](08-architecture.md#51-diagram)). The user picks one, configures it, and commits with
**Confirm**; the choice is then persisted with the slot and shown back on the row. The drawer is
one shared component: it opens for whichever slot's `▸` was clicked.

```
  ┌─ Source for: Grid import T1 ───────────────────────────────────────────┐
  │                                                                        │
  │  ( • ) Home Assistant                              [ ✓ Connected ]     │
  │        Fetched from your Home Assistant in your browser; the token     │
  │        never reaches this app.                                         │
  │        Entity  [ sensor.electricity_meter_import_t1            ▾ ]     │
  │                                                                        │
  │  (   ) Upload CSV                                              [?]      │
  │        Provide a file yourself.  — not built yet —                    │
  │                                                                        │
  │                                          [ Confirm ]   [ Cancel ]      │
  └────────────────────────────────────────────────────────────────────────┘

  The [ Configure… / ✓ Connected ] button beside Home Assistant opens the
  shared connection modal (one for the whole app, not per slot):

  ┌─ Home Assistant connection ──────────── shared across HA slots ────────┐
  │  Base URL   [ http://homeassistant.local:8123               ]          │
  │  Token      [ ●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●● ]          │
  │             Stays in your browser; sent only to your Home Assistant.   │
  │                                                     [ Test connection ] │
  │  ✓ Connected · HA 2026.6.2 · 1,284 statistic IDs available             │
  │                                                             [ close ]   │
  └────────────────────────────────────────────────────────────────────────┘
```

Each source shows a **label and a one-line blurb** as a radio option
([§5.1](08-architecture.md#51-diagram) `SourceDescriptor`).

**The drawer is transactional: nothing takes effect until Confirm.** Choosing a source or an
entity in the drawer stages the change but does not touch the roster row or the loaded data.
**Confirm** commits it — for Home Assistant it binds the source and entity to the slot; for the
preset spot-price source it runs the backend load. **Cancel** (and closing the drawer with `✕`,
the backdrop, or `Esc`) discards the staged change and leaves the slot exactly as it was. This
keeps a half-made choice from silently altering what the run will use. For a Home Assistant
slot, **Confirm is enabled only once the connection has been tested and an entity is chosen** —
so a committed HA slot is always fetchable; until then Confirm stays disabled.

**The Home Assistant entity is chosen here, in the drawer, not on the row.** When Home
Assistant is the selected source the drawer shows an **Entity** dropdown of the statistic ids
the shared connection listed (energy `sum` ids for an energy slot, `mean` ids for a price
slot), so the one place a slot's HA binding is made is the same place its source is chosen —
there is no separate mapping column on the main roster. The dropdown is populated from the
shared connection; until the connection has been tested it is disabled and shows a prompt to
configure it first. The chosen id is shown back on the roster row beside the source
(`Home Assistant · sensor.…import_t1`). A source with no entity to pick — the preset
Energy-Charts price, a future CSV upload — shows no dropdown, because there is nothing to bind.

Which slots offer which sources:

- **Energy slots** (grid import/export, solar, battery charge/discharge) offer **Home
  Assistant**, and — pending — **Upload CSV**. These are the user's own records, so there is no
  preset dataset to offer.
- **The Spot price slot** additionally offers the **preset Energy-Charts NL** historical
  source. It is the one slot the app can fill from shipped data rather than the user's own,
  because a day-ahead spot price is a public market series, not a household measurement.
- The **Spot price (min)** and **Spot price (max)** bracket slots offer Home Assistant only:
  they carry an HA measurement statistic's own intra-interval min/max, which the price API does
  not provide.

**Home Assistant is a browser fetch; the preset source is a backend load.** The two families
differ in *where the frame is produced*, and the drawer reflects it. Picking Home Assistant
arms the browser fetch (below); picking the preset source triggers a backend load with no
browser round-trip.

**The Home Assistant connection is shared, and lives in a modal.** There is one connection for
the whole app, not one per slot. It is entered in a **connection modal** opened by the
**Configure** button beside the Home Assistant option in the drawer — not a standing card on
the panel, so a user who never touches Home Assistant never sees the connection fields. The
button reflects the shared state: *Configure…* until a test succeeds, *✓ Connected* after. Once
tested, every slot whose source is Home Assistant reuses that connection, and its entity
dropdown is filled from the same statistic-id listing — a user with five HA slots enters the URL
and token once, from whichever slot's drawer they configure first. *Test connection* and *Fetch
history* are performed by the browser against the user's own Home Assistant, not by the backend
([§4.3](06-home-assistant-ingestion.md)). The token entered here stays in the browser and is
sent only to that instance — it is never transmitted to the application backend
([§7.5](15-data-quality-and-limits.md#75-operational-notes)), and the modal says so beneath the
token field. *Test connection* lists the available statistic ids and fills the entity dropdown
of every HA slot; *Fetch history* reifies the whole staged configuration — it fetches the
statistics for the mapped HA slots and streams them to the backend, and in the same step the
backend loads every staged backend-load slot (e.g. the spot price) — after which the panel
re-renders from the one persisted dataset. It is enabled once **any** slot is staged, not only
HA slots (a backend-only configuration is fetchable without a Home Assistant connection).

**The preset spot-price source is loaded by the backend — at fetch time, not on pick.**
Choosing it for the Spot price slot only **stages** the choice, exactly as choosing Home
Assistant for a slot does: nothing is loaded or persisted until **Fetch history**. The drawer is
a pure staging surface (§3.1, §3.5) — picking a source, HA or backend, writes no dataset. On
Fetch, the backend reads the committed on-disk NL day-ahead dataset (2023 → a recent tail) and
bridges any gap to the end of the selected range with a call to the public Energy-Charts API,
with no browser involvement, and folds the result into the **same** dataset as the fetched HA
series. It is the **one source the backend fetches directly**, and the reason it can is that the
price API is a public cloud endpoint the backend can reach — unlike a user's LAN-only Home
Assistant. The mechanics are in [§4.3](06-home-assistant-ingestion.md), and the outbound-request
note in [§7.5](15-data-quality-and-limits.md#75-operational-notes). A backend load has no
per-entity mapping dropdown: the slot identity *is* the mapping, so the row shows a static
indication of the source rather than a `▾` selector.

Because both source kinds only stage until Fetch, a fetch **reifies the whole staged
configuration into one dataset** — the HA slots streamed from the browser and every staged
backend-load slot loaded by the backend, together. This is why configuring a backend source and
then fetching an HA slot no longer discards the backend source: there is no earlier per-source
dataset to orphan. The reify is all-or-nothing — if a staged backend load fails, the whole fetch
fails (`LOAD_FAILED`, §3.2) and nothing is persisted.

**The setup band decides which slots the roster asks for.** The two choices in the band above
panel ① ([§2.1](#the-setup-band)) determine the slot roster here, and this is the reason
they are asked first:

- **`has_pv`** governs the **Solar production** row. It is rendered only when the household
  has declared PV; with PV declared it is required and carries the same `●` as the grid
  registers, and the `◐` in the wireframe marks the row as conditional on that declaration
  rather than as a third level of optionality. With PV not declared the row is hidden
  entirely rather than shown greyed, so there is no invitation to map a sensor the run will
  ignore.
- **`simulate_cost`** governs the two **Spot price (min)** and **Spot price (max)** rows.
  These carry the intra-interval price minimum and maximum that enable the bracketing
  diagnostic ([§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)),
  which quantifies a euro figure and therefore has no meaning in an energy-only run. They
  are offered — as optional (`◒`) slots, never required — only when cost simulation is on,
  and are absent otherwise. They are the one place the cost choice *adds* a data slot rather
  than only hiding downstream boxes.

Editing either answer in the band re-derives this roster in place: a slot that ceases to
apply is removed and any file or mapping in a still-applicable slot is kept
([§2.1](#the-setup-band), [§3.2](04-state-machine.md#32-events)).

The **Spot price** row itself is required in both cost modes, because the charge and
discharge bands compare against it regardless of whether anything is converted to euros
([§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model)). It is the one input a
user might expect the cost choice to remove and it does not — only the min/max companions
above are cost-gated.

### Granularity, per series

The granularity table exists because series arrive at genuinely different resolutions —
hourly meter registers, 15-minute spot prices, 5-minute recent Home Assistant statistics —
and a single "resolution: hourly" line hides which series contributed what. Each series
carries its own native resolution whichever path it came in by: one Home Assistant
statistic per row, one uploaded file per row. Two columns, because two different facts
matter:

- **Recorded at** — the series' *native* resolution, as it came from the source. Where a
  finer copy exists over part of the window, both appear with their coverage; the Home
  Assistant fetch deliberately retrieves 5-minute statistics for the trailing ten days on
  top of the full-window hourly ones ([§4.3](06-home-assistant-ingestion.md)).
- **The run uses** — the simulation grid, plus how this series was reconciled onto it:
  nothing for a series already at the grid, `averaged` for a price averaged down, `held`
  for a price forward-filled from a coarser spacing.

Only `averaged` carries the ⚠ marker, and this is the point of the whole table. Summing
energy deltas into a coarser bucket is exact, and holding a price across a finer grid is
exact for a step function; averaging a price is the one reconciliation that destroys
information the simulator would otherwise have used. Marking the harmless cases as well
would leave the user with five warnings and no way to tell which one costs them anything.
The same finding is check 3b in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order) and reaches
the result object as `diagnostics.price_granularity_lost`. It is shown in both cost modes,
because the spot series steers the battery whether or not euros are computed
([§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model)).

**Why the grid is what it is.** The simulation grid is the *coarsest* native resolution
among the energy series, so no energy series is ever coarser than the grid and every one of
them downsamples exactly. Making it any finer would mean upsampling energy, which the
simulator refuses to do: splitting an hourly total across twelve five-minute buckets means
inventing a within-interval profile, and the invented profile — not the data — would decide
what the battery did. The full rule is
[§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling), and what the
chosen grid costs in accuracy is measured rather than assumed, by
[§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly) and
[§6.13](14-diagnostics.md#613-resolution-bias-diagnostic).

A series whose spacing is irregular is shown as `irregular` in the first column and
`undefined` in the second. What the grid selector should do with such a series is
[open question §8.20](17-open-questions.md); the table reports the fact without implying an
answer.

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

### The CSV source (pending)

**Upload CSV** is one source among those offered in the drawer, not a whole-panel mode. It is
offered for every energy slot and for the spot-price slots, and it is **pending**
([§2.1](#the-four-availability-states)): it renders as a disabled radio with the `[?]`
affordance (feature key `data_source_csv`) until the machinery ships. What follows describes
what the CSV source *will do* when built, so the intent is on record; a reader must not read
its pending state as the feature having been cut.

A user picking CSV does not own their data in the shape the app wants it. They will be
downloading exports from an energy supplier, a grid operator's portal, or a PV installer, and a
first-time user typically does not know which of those files they need before they start.
Choosing CSV for a slot therefore opens an upload flow built around a **checklist of the series
to go and collect** — the same slot roster the panel already shows, but read as "what do I need
to download", with one upload slot per series and a pointer to where each file comes from.

```
  ┌─ Upload CSV — files to collect ────────────────────────────────────────┐
  │                                                                        │
  │  Collect one file per row below. Most of these come from your energy   │
  │  supplier's website; solar production usually comes from your          │
  │  installer's monitoring portal or the inverter app.                    │
  │                                                    [ Where do I get    │
  │                                                      these files? ]    │
  │                                                                        │
  │  SERIES              REQ  FILE                                         │
  │  ───────────────────────────────────────────────────────────────────   │
  │  Grid import T1       ●   import_t1_2025.csv  ✓ 8,760 rows  [ replace ]│
  │  Grid import T2       ●   import_t2_2025.csv  ✓ 8,760 rows  [ replace ]│
  │  Grid export T1       ●   [ choose file… ]                             │
  │  Grid export T2       ●   [ choose file… ]                             │
  │  Solar production     ◐   solar_2025.csv      ✓ 8,760 rows  [ replace ]│
  │  Battery charge       ○   [ choose file… ]                             │
  │  Battery discharge    ○   [ choose file… ]                             │
  │  Spot price           ●   prices.csv          ✗ see below   [ replace ]│
  │  Spot price (min)     ◒   [ choose file… ]                             │
  │  Spot price (max)     ◒   [ choose file… ]                             │
  │                                                                        │
  │  ✗  prices.csv does not match the expected format for Spot price.      │
  │     Expected a timestamp column with a UTC offset and a price column   │
  │     in EUR/kWh. Row 2 reads `2026-01-01 00:00`, which has no offset,   │
  │     so the October clock change cannot be resolved.                    │
  │                                              [ choose another file… ]  │
  │                                                                        │
  │  ● = required.  ○ = optional.                                          │
  │  ◐ = required only if you have solar PV.                               │
  │  ◒ = offered only if you simulate costs (intra-hour price bracketing). │
  │  Both answers come from the setup band above.                          │
  │  Spot price drives the charge and discharge bands, so it is required   │
  │  whether or not you simulate costs.                                    │
  │                                                                        │
  │  [ Download format spec ]  [ Download example file ]  [ Clear all ]    │
  │                                                                        │
  │                                              [ Load data ]             │
  └────────────────────────────────────────────────────────────────────────┘
```

**The slot supplies the series identity.** Nothing inside an uploaded file says which
series it is — not a column header, not a name column, not the filename. The user declares
what they are providing by choosing the slot to drop it into, which is the one thing they
reliably know and the one thing a supplier's export cannot get wrong. The consequence worth
stating plainly: the series names in
[§4.1](05-data-formats.md#41-the-series-vocabulary) are internal identifiers used
downstream and in the result object; a user's file is never required to contain them.

**Which rows appear** follows the same setup-band rules as the roster above
([§2.1](#the-setup-band)): `Solar production` only when `cfg.has_pv` is set, the `Spot price
(min)` / `Spot price (max)` slots only when `cfg.simulate_cost` is on, and `Spot price` itself
required in both cost modes. Neither choice is asked here — the band is the single source of
truth for both.

**Validation is per slot and recoverable.** A file is checked against the expected format
for the series it was dropped into, and a failure is reported on that row alone: what was
expected, what was found, and a fresh file chooser for the same slot. The other slots keep
their contents and the session does not enter an error state — a badly-formatted export is
an ordinary event on this path, not a run-fatal one, and the user's recourse is a different
file rather than a restart. The row is not marked complete until a file passes, and
`[ Load data ]` stays disabled while any required slot is empty or failing.

Uploading into a slot that already holds a file **replaces** it. There is one file per
series, so there is no merging to specify and no collision to resolve.

The expected format for each series is in [05-data-formats.md](05-data-formats.md).

## 2.3a The data summary band — "Your data at a glance"

Between panel ① and panel ② sits an **unnumbered summary band**. It appears once the fetch
succeeds (`LOAD_SUCCEEDED`, [§3.1](04-state-machine.md#31-session-level-states)) and shows the
figures that follow **from the household's own recorded data alone** — before any simulated
battery, policy or pricing is configured. It is an interstitial "here is what we found", read
between loading the data and describing the battery: it lets the user confirm the import looks
right, and see what their year actually was, before they invest effort in parameters.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Your data at a glance                              2025-06-01 → 2026-07-21   │
│                                                     416 days                  │
│                                                                              │
│  ┌─ Grid ─────────────────┐  ┌─ Household ────────────┐  ┌─ Solar ──────────┐ │
│  │  Imported   4,129 kWh  │  │  Consumption 6,540 kWh │  │  Produced        │ │
│  │  Exported   3,180 kWh  │  │  Self-sufficiency 31%  │  │     4,820 kWh    │ │
│  │                        │  │  net of your battery ⓘ │  │  Self-consumption│ │
│  │                        │  │                        │  │     58 %         │ │
│  │                        │  │                        │  │  net of battery  │ │
│  └────────────────────────┘  └────────────────────────┘  └──────────────────┘ │
│                                                                              │
│  ┌─ Your existing battery ────────────────────────────────────────────────┐  │
│  │  Charged      2,510 kWh        Discharged     2,240 kWh                 │  │
│  │  ⓘ These come from the battery you already own (its charge/discharge    │  │
│  │     sensors). The figures above are reconstructed net of it, so they    │  │
│  │     describe the house, not the meter.                                  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Spot price over this period ──────────────────────────────────────────┐  │
│  │  Average 0.142 €/kWh    ·    low −0.021    ·    high 0.487              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### It is a band, not a stepper panel

Like the setup band ([§2.1](#the-setup-band)), it is **not numbered, does not collapse to a
summary, carries no CTA and no `[?]` affordance**, and has no focus state of its own
([§3.4](04-state-machine.md#34-panel-focus-model)). It differs from the setup band in one
respect: the setup band is present from `EMPTY`, whereas this band has nothing to summarise until
data exists, so it is **absent before the first successful fetch** and appears on
`LOAD_SUCCEEDED`. It re-renders whenever the dataset is reloaded ([§3.2](04-state-machine.md#32-events)
`RELOAD_DATA`). Panel ①'s own "Next: parameters →" CTA is unchanged and still drives the step from
① to ②; the band sits between them as context, not as a gate.

### What it shows, and why none of it needs the simulated battery

Every figure here is a function of the ingested series, computed by the metrics in
[§6.11](12-metrics-and-benchmarks.md#611-metrics) (the "Energy" row, minus `efc`, which counts
the simulated battery's cycles) over the reconstructed load of
[§6.3](09-ingest-algorithms.md#63-household-load-reconstruction). None of them depends on the
battery capacity, the policy, or the pricing model, which is exactly why they can be shown before
panel ②. The price context is battery-free for the same reason the charge/discharge bands are:
the spot series is an input, not a cost model ([§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model)).

| Group | Rows | Rendered when |
|---|---|---|
| **Grid** | total imported, total exported (kWh over the window) | always |
| **Household** | reconstructed consumption, self-sufficiency (`1 − import/load`) | always |
| **Solar** | PV production, self-consumption (`1 − export/pv`) | PV series present |
| **Your existing battery** | measured charge-in, discharge-out (kWh) | battery series present |
| **Spot price over this period** | average, min, max (€/kWh) | price series present |

**Omit, never zero.** A group whose inputs are absent is not rendered — no PV series, no Solar
group; no battery series, no battery group. Rendering `0 kWh` or `0%` would assert something the
data cannot support, the same discipline panel ③ uses
([§2.4](#panel--without-pv)). Self-sufficiency is always well defined and always shown; without
PV it measures purely the meter, and (see below) net of any existing battery.

**Self-sufficiency is display-clamped to ≥ 0 %.** The metric `1 − import/load`
([§6.11](12-metrics-and-benchmarks.md#611-metrics)) can go negative when grid import exceeds the
reconstructed load over the window — which happens when an existing battery ends the window more
charged than it started (net SoC drift) or through round-trip losses: some imported energy went
into the battery and was not discharged to the load within the window. The quantity is honest —
that energy *was* imported, not self-supplied — but a negative percentage reads as broken. So the
band clamps the *displayed* value to `max(0, ·)` and, when it clamps, shows a one-line caveat
noting the battery ended more charged than it started and that this evens out over full
charge/discharge cycles. The underlying metric is unchanged; only the presentation is clamped.
This case does not arise for a household without an existing battery (import cannot exceed
`import − export + pv`), so it is specific to the existing-battery variant below.

### Coverage: the grid meter drives the window; each group keeps its own span

The band's window is the **grid meter** coverage, not the intersection of every mapped series. A
household may map a series that covers only part of the meter history — solar panels or a battery
installed part-way through a two-year record. Intersecting all series would collapse the window to
that short span and clip the grid totals to it (a two-year import reading as a few hundred kWh). So
the Grid and Household figures span the meter window, and each optional group (Solar, existing
battery, price) is summed over **its own coverage** within that window and reports that span
("since &lt;date&gt; · N days") when it is materially shorter. Self-consumption compares PV against
export over the **PV's** window, not the whole window — comparing six months of production against
two years of export would be meaningless.

### When an input is empty or the reconstruction is unreliable, say so

Two data problems the band must surface rather than present as clean numbers, in the spirit of
[§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) ("say what happened"):

- **A mapped PV series that reports almost nothing** (total production below a small floor) is
  treated as *empty*, not as zero production: the Solar group is omitted and a note explains the
  sensor may not be wired up correctly. This also avoids `self_consumption = 1 − export/pv` dividing
  by a near-zero PV total, which otherwise produces an absurd percentage.
- **A load reconstruction the negative-load clamp has badly damaged.** When
  [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) clamps a large share of the load
  to zero — export the reconstruction cannot explain from import + PV + battery, typically real PV
  the solar sensor under-reports or an unmapped battery discharging to the grid — the clamp silently
  *inflates* consumption and drives self-sufficiency toward 0. Past a threshold the band treats
  consumption and self-sufficiency as **unreliable**: it hides both and shows a prominent warning
  naming the unexplained export and pointing the user at their solar/battery sensors. The measured
  figures (grid import/export, price) are unaffected and still shown.

### The pre-existing battery, and what "net of your battery" means

The user **may already own a battery**. When they do, its charge/discharge sensors are mapped into
the `battery_charge` / `battery_discharge` slots ([§4.1](05-data-formats.md#41-the-series-vocabulary)),
and [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) reconstructs household load by
*stripping* that battery: `load = import − export + pv + battery_discharge − battery_charge`. The
household consumption and self-consumption figures are therefore **derived from the existing
battery's data too** — they describe the house behind the meter, net of the battery it already has,
not a hypothetical no-battery meter reading.

Two consequences the band makes explicit rather than hiding:

- The existing battery gets **its own group**, reporting the charge-in and discharge-out it
  actually did over the window. This is an observed fact about the household's current setup, and
  it is worth stating on its own before the simulated battery's figures appear in panel ③ — the two
  are easily confused, and separating "the battery you have" from "the battery we simulate" here
  keeps them apart.
- The Household and Solar rows are labelled **"net of your existing battery"** whenever those slots
  are present, with an ⓘ explaining that the reconstruction used the battery's sensors. Without the
  slots the label is absent and the rows read plainly, because there was no battery to net out.

This is the *existing* (measured, an input) versus *simulated* (configured in panel ②, the
counterfactual) battery distinction, and it runs through the whole product: the summary band
reports the household as it was, panels ②/③ report what a simulated battery would change. One
limitation is acknowledged and not solved here: if the existing battery was installed **partway
through the window**, its sensors may not cover the whole span and the reconstructed load is then
inconsistent across the boundary — [open question §8.6](17-open-questions.md), routed to
[§6.15](13-configuration-epochs.md). The band shows the window-wide figures; detecting and
offering to restrict the window is future work.

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
│  │  Contract ⓘ  ( • ) Dynamic     (   ) Fixed     (   ) Variable          │  │
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

The **Fixed** and **Variable** sub-panels replace the Dynamic sub-panel:

```
  ┌ Fixed ────────────────────────────────────────────────────────────────┐
  │  Supply rate normaal (T1)  [ 0.1350 ] €/kWh  excl. tax and VAT        │
  │  Supply rate dal     (T2)  [ 0.1180 ] €/kWh  excl. tax and VAT        │
  │  Contract runs from        [ 2025-01-01 ]  to  [ 2027-01-01 ]         │
  └───────────────────────────────────────────────────────────────────────┘

  ┌ Variable ─────────────────────────────────────────────────────────────┐
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

### The contract-type help affordance

The three contract types are named by the single words the Dutch market uses —
**dynamic**, **fixed**, **variable** — and the package is single-jurisdiction throughout,
so no country qualifier appears on any of them. These are the same three names as the
`DYNAMIC` / `FIXED` / `VARIABLE` values in
[§6.5](10-pricing.md#65-price-curves); label and enum do not diverge.

The bare words do not tell a user which one they hold, and *variable* and *dynamic* are
the pair most easily confused: both describe a rate that moves. The `ⓘ` next to
**Contract** exists for that, and opens a popover naming the one thing that separates each
type from the others:

- **Dynamic** — the price follows the EPEX day-ahead market and changes every hour.
- **Fixed** — one normaal and one dal rate, agreed for the term of the contract.
- **Variable** — the supplier sets the rate and revises it periodically, typically every
  six months. Between revisions it behaves exactly like a fixed contract.

It closes with a link to
[background E3.1](18-dutch-electricity-background.md#e31-the-three-forms), which carries
the full treatment including the Dutch names (*dynamisch*, *vast*, *variabel*) and what
each means for a battery. E3.1 is the single normative definition of the three types: the
popover text above and the glossary entries in
[Appendix B](appendix-b-glossary.md) are deliberately one line each and defer to it, so
that a change to the definitions is made in one place.

The affordance is part of the Pricing box and is therefore absent when cost simulation is
off, along with everything else in that box.

### Without PV

`has_pv` is set in the setup band ([§2.1](#the-setup-band)); this panel reads it and does
not ask again. The `[PV only]` markers above are not rendered; those options are **absent**.
With `has_pv = false` the panel changes as follows, and nothing else changes:

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

`simulate_cost` is set in the setup band ([§2.1](#the-setup-band)); this panel reads it and
does not ask again. With `simulate_cost = false` — the default — the panel loses everything
that exists to turn kWh into euros, and keeps everything that decides which kWh move:

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
│           2025-07-22 → 2026-07-21 · simulated hourly · 8,760 intervals       │
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
│  │  …if export allowed 2,311 kWh  ├──────────────────────────────────●─┤  │  │
│  │                                                                        │  │
│  │  Your policy captures 71% of the grid import a perfectly-informed      │  │
│  │  battery could have avoided. Allowed to export, that ceiling rises to  │  │
│  │  2,311 kWh (a 61% capture) — the extra is arbitrage your export        │  │
│  │  setting currently forbids.                                            │  │
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
│  │  …if export allowed    € 503   ├──────────────────────────────────●─┤  │  │
│  │                                                                        │  │
│  │  Your policy captures 69% of the money a perfectly-informed battery    │  │
│  │  could have saved. A different ceiling from the energy benchmark, and  │  │
│  │  a different dispatch behind it: buying cheaply is not the same as     │  │
│  │  importing little. Allowed to export, the ceiling rises to € 503.      │  │
│  │                                                       [ what is this? ]│  │
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
│  │  ⚠  Spot prices are quarter-hourly but the run is hourly, so the       │  │
│  │     battery acted on an averaged price and could not chase within-     │  │
│  │     hour swings.                                     [ what is this? ] │  │
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
- **The "…if export allowed" row is conditional.** Both benchmark boxes carry a fourth row
  and a trailing gloss for the unconstrained-export bound, drawn from the
  `*_unconstrained` fields
  ([§4.5](07-internal-representation.md#45-result-object)). It renders only when those
  fields are non-null (i.e. `allow_grid_export` is off, so a second DP actually ran) **and**
  the two capture ratios differ by more than `benchmark_divergence_display_threshold`
  ([appendix A](appendix-a-defaults.md), default 0.02) — a provisional cutoff whose value
  [experiment X10](19-prototype-experiments.md#x10--does-the-benchmarks-export-permission-matter)
  is meant to revisit once real runs show how far the two bounds usually sit apart. When
  export is on, or when the bounds are within the threshold, the row is omitted and the box
  reads exactly as before. This keeps a dense box from carrying a near-duplicate line that
  says nothing.
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
  ([§6.13](14-diagnostics.md#613-resolution-bias-diagnostic)). The lost-price-granularity
  caveat is likewise shown in both modes: it says the battery *dispatched* on an averaged
  price, which happened either way
  ([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)). Its
  cost-only companion, the price bracket, quantifies what that averaging did to the euro
  figure and appears beside it only when there is one.

### Panel ③ without cost simulation

The `COST SAVINGS` section and everything in it is absent — the money KPI tile, the money
waterfall, the money benchmark. The `ENERGY SAVINGS` section is **identical**, figure for
figure, to what the same data produces with cost simulation on, and the panel is complete
without the second half rather than looking truncated. Two smaller consequences:

- The `MONEY SAVED` tile is not replaced by a placeholder or a zero. A blank where a
  headline number would go reads as a failed calculation; an absent section reads as a
  choice the user made, which is what it is.
- A short affordance sits at the foot of the energy section: *"Want to know what this is
  worth in euros? [ Enable cost simulation ]"*, linking back to the `simulate_cost` choice
  in the setup band ([§2.1](#the-setup-band)). Since it defaults off, some users will
  otherwise never discover that the app can do this at all.

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
`min_annualisation_days` (see
[§7.4](15-data-quality-and-limits.md#74-window-anchoring-and-short-window-guard)):

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │  ⓘ  Annualised projection is disabled for ranges under 90 days.        │
  │     Battery savings are strongly seasonal; scaling a July week to a    │
  │     year overstates annual savings by a factor of roughly 2–3.         │
  │     Select 6 months or 1 year to see an annual figure.                 │
  └────────────────────────────────────────────────────────────────────────┘
```
