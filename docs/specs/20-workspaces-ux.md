# 2′. Workspaces — screen structure and flows

> **Purpose:** the multi-workspace restructure of the UI: the workspace list, the three
> per-workspace screens, and the flows between them.
> **Audience:** frontend, with a backend note at the end.
> **Status:** **specification.** This section supersedes
> [§2.1](02-ux-wireframes.md#21-overall-layout)'s single-page stepper and its setup band,
> which §2.1 now defers to rather than describing. Everything §2.2–§2.4 says about the
> *contents* of the data, parameter and results surfaces still holds and is referenced
> rather than restated; what changes is how those surfaces are reached, and which of them a
> given control lives on.
> **Read with:** [02-ux-wireframes.md](02-ux-wireframes.md) for the box-level detail of each
> surface, [04-state-machine.md](04-state-machine.md) for the session states this reorganises.

This document was written as a proposal and adopted as written. The §2′.N numbering is kept
rather than folded into §2's sequence because it is cited by section number from 35 places in
`app/` and `tests/`, which a renumber would all have to follow. A secondary consideration: the
prime is stripped from generated anchors, so a merged file would carry two families of sections
sharing `22-`/`24-` prefixes and differing only by title. That is a readability cost, not a
collision — checked against the real headings, every anchor stays distinct.

**Nothing in this document changes any computation or the data model.** The simulation core,
the pricing package, the metrics and the persisted `SimulationConfig` are untouched. The
change is which screen a control appears on and how many independent configurations the app
holds at once.

---

## 2′.1 What a workspace is

A **workspace** is one household-and-question: a configuration, a dataset, and the results
that follow from them. Today the app has exactly one, implicit and unnamed. This document
makes it plural, named, and listed.

The term is not new. [§5.1](08-architecture.md#51-diagram) has carried `workspace_id` on
every persisted row since the first increment, and [§5.5](08-architecture.md) states that
this was deliberate scaffolding for exactly this change. The header already renders a static
`[workspace: local]` badge. What is new is that the user can see the plural, create members
of it, and choose between them.

A workspace owns:

| Part | Where it lives today | Screen that edits it |
|---|---|---|
| Title | *(does not exist)* | Edit workspace |
| Location (zip code) | *(does not exist)* | Edit workspace |
| Grid connection (`grid.*`) | §2.3 panel ② box 2 | Edit workspace |
| Contract and rates (`pricing.*`) | §2.3 panel ② box 6 | Edit workspace |
| Data source mapping + dataset | §2.2 panel ① | Configure data |
| `has_pv` / `has_battery` | §2.2 panel ① | Configure data |
| Battery, topology, policies | §2.3 panel ② boxes 1, 3, 4, 5 | Results |
| `simulate_cost` | §2.1 setup band | Results |
| Results | §2.4 panel ③ | Results (read-only) |

**The setup band ceases to exist as a construct.** Its three scope answers are distributed to
the screens they shape: `has_pv` and `has_battery` decide panel ①'s slot roster and stay with
it; `simulate_cost` decides which result sections exist and moves to the results screen. The
rule is proximity — each shape question sits on the surface it reshapes, where the user can
see the effect of flipping it. See [§2′.7](#27-where-the-setup-bands-questions-went).

---

## 2′.2 The workspace list — the app's home screen

The list replaces the single page as the entry point. Cards are ordered **most recently
updated first**.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Home Battery Simulator                                            [NL|EN]   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Your analyses                              [ + New analysis ]              │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  Our house, dynamic contract                                           │  │
│  │  ( 1×25 A )  ( DYNAMIC )  ( saved 2026-07-24 16:20 )                   │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │  Grid consumption   ✓ loaded          Grid production  ✓ loaded  │  │  │
│  │  │  Solar production   ✓ loaded                                     │  │  │
│  │  │                                                                  │  │  │
│  │  │  2025-06-01 09:00 → 2026-07-21 23:00                             │  │  │
│  │  │  9,983 intervals · hourly                                        │  │  │
│  │  └──────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │  [ Results ]  [ Configure data ]  [ Configure analysis ]               │  │
│  │                                  [ Delete data ]  [ Delete analysis ]  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  Rental flat — no PV                                                   │  │
│  │  ( 1×35 A )  ( DYNAMIC )  ( saved 2026-07-19 11:04 )                   │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │  Grid consumption   ✓ loaded          Grid production  ✓ loaded  │  │  │
│  │  │  Solar production   — not applicable (no PV)                     │  │  │
│  │  │                                                                  │  │  │
│  │  │  2025-01-01 00:00 → 2026-01-01 00:00                             │  │  │
│  │  │  8,760 intervals · hourly                                        │  │  │
│  │  └──────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │  [ Results ]  [ Configure data ]  [ Configure analysis ]               │  │
│  │                                  [ Delete data ]  [ Delete analysis ]  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  Three-phase, 3×25                                                     │  │
│  │  ( 3×25 A )  ( DYNAMIC )  ( saved 2026-07-26 09:12 )                   │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │  No data loaded yet.                                             │  │  │
│  │  │  Choose your data sources to get a result.                       │  │  │
│  │  └──────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │  [ Configure data ]  [ Configure analysis ]                            │  │
│  │                                                   [ Delete analysis ]  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### The badges

Three, in fixed order, derived from the config — never typed:

- **Connection** — `phases × fuse_a` rendered `1×25 A`, `3×63 A`. From `GridConfig`; the same
  two fields the dropdown in [§2′.4](#24-edit-workspace) sets.
- **Contract** — `DYNAMIC`, `VARIABLE` or `FIXED`, the enum value verbatim. §2.3's rule that
  "label and enum do not diverge" applies here too.
- **Last saved** — the config document's `updated_at`, in Europe/Amsterdam.

The badges deliberately describe the **configuration only**, not the data or the result. A
badge that sometimes reflects a dataset and sometimes a config would be unreadable at a
glance, which is the only thing a badge is for.

**The contract badge is always shown, at full strength.** It is not hidden, greyed or
qualified when `simulate_cost` is off. The badge reports a fact about the household's
contract, which is true whether or not the current run prices anything with it — the same
reasoning that keeps the Contract box permanently on the edit-workspace screen
([§2′.4](#what-is-not-on-this-screen)). Consistent badge geometry across cards is worth more
here than annotating a distinction the card has no room to explain.

### The info box

Five facts about the *dataset*, in a visually distinct block so they are not confused with the
config badges above them:

1. **Grid consumption** loaded / not loaded
2. **Grid production** loaded / not loaded
3. **PV production** loaded / not loaded / not applicable
4. **Coverage** — start and end date-time of the series
5. **Size** — total interval count, and the simulation grid resolution

"Grid consumption" and "grid production" each stand for the T1+T2 register pair
([§4.1](05-data-formats.md#41-the-series-vocabulary)): the card reports the *role* as loaded
when the slots that role needs are filled, and does not expose the register split. That detail
belongs on the configure-data screen, which has room to explain it.

**When no data is loaded the box collapses to a one-line invitation** and the buttons that
need a dataset are absent, as the third card above shows. This is the Inapplicable rule from
[§2.1](02-ux-wireframes.md#the-four-availability-states): a `[ Results ]` button on a
workspace with no data has nothing to lead to, and greying it invites the user to work out
how to un-grey it when the adjacent line already says.

**PV production reads "not applicable" when `has_pv` is off** — not "not loaded". The two are
different facts and the card should not report a deliberate configuration as a missing input.

### The actions

| Button | Leads to | Present when |
|---|---|---|
| `[ Results ]` | [§2′.6](#26-results) | data is loaded |
| `[ Configure data ]` | [§2′.5](#25-configure-data) | always |
| `[ Configure analysis ]` | [§2′.4](#24-edit-workspace) | always |
| `[ Delete data ]` | modal, then stays on the list | data is loaded |
| `[ Delete analysis ]` | modal, then stays on the list | always |

`[ Results ]` is first and visually primary: on a workspace that has data, it is what the user
came for. The two destructive actions are separated from the three navigational ones by a gap,
and the workspace-deleting one is at the far end — the furthest thing on the card from where the
pointer usually lands.

**Both destructive actions are named in words, not drawn as an icon.** The workspace-deleting one
was once a bare `🗑`. The two deletions on this card destroy very different amounts of work —
one throws away a dataset that can be loaded again, the other throws away the analysis itself —
and a glyph leaves that difference to be inferred from position. Position still carries the
ordering (the gap, and the far end), but the label carries the meaning. Distance from the pointer
is what keeps the heavier action from being hit by accident; it stays `btn-ghost` so that
spelling it out does not also make it the loudest thing in the row.

### The header

**Both the `[workspace: local]` badge and the `[⚙]` button are removed.** The badge named the
single implicit workspace and has nothing left to say once the list exists; the gear was never
wired to anything. The header keeps the title and the language toggle only:

```
│  Home Battery Simulator                                            [NL|EN]   │
```

---

## 2′.3 The two confirmation modals

Both follow the same shape, and both state what survives as well as what goes — a deletion
dialog that says only what it destroys makes the user guess at the rest.

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Delete this analysis?                                               │
  │                                                                      │
  │     "Our house, dynamic contract" and everything in it — the         │
  │     configuration, the loaded data and the results — will be         │
  │     deleted.                                                         │
  │                                                                      │
  │     This cannot be undone.                                           │
  │                                                                      │
  │                                    [ Cancel ]   [ Delete analysis ]  │
  └──────────────────────────────────────────────────────────────────────┘
```

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Delete the loaded data?                                             │
  │                                                                      │
  │     The measurements loaded into "Our house, dynamic contract"       │
  │     will be deleted, along with the results computed from them.      │
  │                                                                      │
  │     Your connection, contract and battery settings are kept.         │
  │     You will need to choose your data sources again.                 │
  │                                                                      │
  │     This cannot be undone.                                           │
  │                                                                      │
  │                                        [ Cancel ]   [ Delete data ]  │
  └──────────────────────────────────────────────────────────────────────┘
```

Rules for both:

- **The workspace title is quoted in the body.** With several cards on screen, a dialog that
  says "this analysis" relies on the user remembering which button they pressed.
- **The confirming button carries the verb, not "OK".** `[ Delete analysis ]` /
  `[ Delete data ]`, styled as destructive; `[ Cancel ]` is the default focus.
- **No "don't ask again".** Both are irreversible and neither is frequent enough for the
  prompt to become friction.
- After confirming, the user stays on the list, which re-renders. Deleting data leaves the
  card in the no-data state shown as the third card in [§2′.2](#22-the-workspace-list--the-apps-home-screen).

**"Delete data" keeps the configuration, and does NOT keep a fetched slot's source mapping.**
The two halves of that sentence are the honest statement of what the operation does, and the
dialog copy above says both.

The configuration is genuinely separable from the dataset: `simconfig.json` is a different
document, so the connection, contract and battery settings come through a data deletion
untouched, and the workspace is still the same analysis afterwards.

The source mapping is not separable, because for a slot that has been **fetched** it is not
held apart from the data — it is part of it. When a fetch persists a series, the source key and
the Home Assistant statistic id are stored in `series_meta` alongside that series, and the slot
roster renders the slot's source from the dataset on every reload; this is branch 1 of "Two
things carry a source choice across a reload" in
[`app/static/ha_fetch.js`](../../app/static/ha_fetch.js)'s header, which describes the split
accurately. Deleting the measurements deletes those rows, so the slot returns to being
unassigned.

What does survive is branch 2: a **pre-fetch staged choice**, one the user made in the drawer
but has not fetched yet, which lives in `localStorage` keyed by workspace and is reconciled
against `source_generation`. A data deletion deliberately leaves `source_generation` alone, so a
staged choice is not invalidated by it.

The practical consequence, and the reason the copy had to change: a user who deletes data in
order to re-fetch a longer window does **not** simply press `[ Fetch history ]` again — they
choose their sources first. Making that untrue would mean preserving `series_meta`'s source
columns across a deletion, i.e. keeping rows that describe series that no longer exist; the
mapping is worth less than the confusion that would cause, so the behaviour stands and the
sentence changed.

---

## 2′.4 Edit workspace

The household's fixed facts: what and where it is, what it is connected to, and what it pays.
Reached by `[ Configure analysis ]` from a card, or as step 1 of the new-workspace wizard.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Your analyses                                                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Edit analysis                                                              │
│                                                                              │
│  ┌─ Name ─────────────────────────────────────────────────────────────────┐  │
│  │  Title  [ Our house, dynamic contract                              ]   │  │
│  │  ⓘ Only a label, so you can tell your analyses apart.                  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Location ─────────────────────────────────────────────────────────────┐  │
│  │  Postcode  [ 1012 AB ]                                                 │  │
│  │  ⓘ Used to work out sunrise and sunset at your address. Nothing is     │  │
│  │    sent anywhere — the calculation is local.                           │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Grid connection ──────────────────────────────────────────────────────┐  │
│  │  Connection  [ 1 × 25 A  (5.75 kW)                              ▾ ]    │  │
│  │              ⓘ On your meter cabinet, or on your grid operator bill.   │  │
│  │                                                                        │  │
│  │  ┌ Advanced ───────────────────────────────────────────── [ expand ] ┐ │  │
│  │  │  Max import  [ 5.75 ] kW   ⓘ blank = derived from the connection  │ │  │
│  │  │  Max export  [ same as import ▾ ]                                 │ │  │
│  │  │  Override these only if your operator has set a different limit.  │ │  │
│  │  └───────────────────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Contract ─────────────────────────────────────────────────────────────┐  │
│  │  Type ⓘ  ( • ) Dynamic    (   ) Variable [?]    (   ) Fixed [?]        │  │
│  │                                                                        │  │
│  │  ┌ Advanced ───────────────────────────────────────────── [ expand ] ┐ │  │
│  │  │  Supplier markup   [ 0.0205 ] €/kWh  excl. VAT                    │ │  │
│  │  │  Energy tax        [ 0.09161 ] €/kWh excl. VAT      (2026 value)  │ │  │
│  │  │  VAT               [ 21 ] %                                       │ │  │
│  │  │                                                                   │ │  │
│  │  │  ┌ Feed-in ─────────────────────────────────────────────────────┐ │ │  │
│  │  │  │  Preset [ Legal minimum (50% of bare price)            ▾ ]   │ │ │  │
│  │  │  │  compensation = max(0, α × bare + β)                         │ │ │  │
│  │  │  │      α [ 0.50 ]      β [ 0.0000 ] €/kWh                      │ │ │  │
│  │  │  │  Terugleverkosten ( • ) flat [ 0.0400 ] €/kWh                │ │ │  │
│  │  │  │                   (   ) tiered by annual volume [?]          │ │ │  │
│  │  │  │  ⓘ 2027 tariffs are not published. Presets are estimates.    │ │ │  │
│  │  │  └──────────────────────────────────────────────────────────────┘ │ │  │
│  │  │                                                                   │ │  │
│  │  │  ┌ Settlement ──────────────────────────────────────────────────┐ │ │  │
│  │  │  │  Your supplier bills  ( • ) Hourly average                   │ │ │  │
│  │  │  │                       (   ) Every 15 minutes                 │ │ │  │
│  │  │  │  ⓘ How your SUPPLIER bills you, not how the market settles.  │ │ │  │
│  │  │  └──────────────────────────────────────────────────────────────┘ │ │  │
│  │  │                                                                   │ │  │
│  │  │  Day/night window   dal from [ 23:00 ] to [ 07:00 ] + weekends    │ │  │
│  │  │  Degradation cost   [ 0.0000 ] €/kWh throughput  (0 = disabled)   │ │  │
│  │  └───────────────────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│                                      [ Cancel ]            [ Save ]          │
└──────────────────────────────────────────────────────────────────────────────┘
```

### The connection dropdown

Ten options, replacing §2.3's separate phases radio + fuse field:

```
   1 × 10 A  (2.30 kW)      3 × 25 A  (17.25 kW)     3 × 50 A  (34.50 kW)
   1 × 25 A  (5.75 kW)      3 × 35 A  (24.15 kW)     3 × 63 A  (43.47 kW)
   1 × 35 A  (8.05 kW)      3 × 40 A  (27.60 kW)     3 × 80 A  (55.20 kW)
   1 × 50 A  (11.50 kW)
```

Each option shows its derived capacity, from `connection_capacity_kw_display` — the rounded
display figure, never the exact one used in dispatch
([§6.8](11-policies-and-battery.md) step 6 reads the exact value).

This is a **presentation change only**: the dropdown writes the same `grid.phases` and
`grid.fuse_a` the two controls wrote before. The list covers the standard Dutch domestic
connections; a household outside it uses the advanced override.

**The ten options are the whole list — there is no "other…" and no free-text fuse field.**
These are the connections a Dutch household can actually have, so a value outside them is a
mistake rather than an unusual case, and the free-text field it replaces mostly invited typos.
A household whose operator has set a limit that does not follow from the connection expresses
that through the **advanced import/export override**, which is precisely what it is for.

One consequence to handle rather than ignore: **a stored config holding an off-list
combination must still render as itself.** The old free-text field could have produced
`1×20 A`, and the dropdown must show that value (as an extra, marked entry) rather than
silently snapping to `1×25 A` — a snap would change `max_import_kw` and therefore the answer,
without telling anyone. Selecting any listed option replaces it, and the off-list entry
disappears once it is no longer selected.

### The advanced panes

Both are **collapsed by default and preserve their contents when collapsed** — collapsing is a
display state, never a reset. A pane whose contents differ from the defaults should say so on
its collapsed summary line, so a user cannot leave a non-default override hidden and forgotten:

```
  ┌ Advanced ─────────────────── 2 values overridden ───────── [ expand ] ┐
```

### The settlement question

The Contract box's Advanced pane carries a radio pair for `supplier_settlement` — hourly
average, or every 15 minutes. It resolves [§8.12](17-open-questions.md), which asked whether
the hourly default should be silent. It is the sole gate on whether
[§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)'s
pricing-uncertainty caveat can appear at all, since a supplier billing the hourly average
charges exactly the price the simulation used and there is nothing to bracket.

The wording asks about the **invoice**, not the market. EPEX has settled quarter-hourly since
2025-10-01, so a user who has read about that change and is asked "how is your electricity
settled?" answers for the market and gets the wrong branch. Both options are real — neither
is pending — and hourly is pre-checked, matching appendix A.

### What is *not* on this screen

`simulate_cost` is not here, even though the Contract box exists only to produce euros. The
toggle lives on the results screen ([§2′.7](#27-where-the-setup-bands-questions-went)). The
consequence is deliberate but worth stating: **the Contract box is always shown here**, even
for a workspace currently reporting energy only, because this screen describes the household's
contract as a fact about the household, not as an input to the current run.

**This is settled: always shown, never greyed or hidden.** Two reasons beyond the one above.
A screen whose shape changed according to a toggle on a *different* screen would be hard to
explain — the user would find boxes missing with nothing visible to blame. And under
[§2′.6](#the-cost-toggle-and-its-precondition) this box is the thing that *unlocks* the cost
toggle: greying it when cost simulation is off would make the two controls mutually blocking,
each waiting for the other.

Note this is a deliberate exception to §2.3's "Inapplicable is hidden, never greyed" rule.
The rule governs controls made meaningless by the *current* configuration; the contract is a
standing fact about the household that outlives any one run, and filling it in is how the
user turns cost simulation on in the first place.

### The zip code

New surface, and **nothing consumes it yet** — no sunrise/sunset calculation exists in the
code or in any other spec file. The field is nonetheless **live, not pending**: enabled,
editable, and persisted to the config document. It is deliberately *not* rendered as a
[pending control](02-ux-wireframes.md#the-pending-affordance), because pending means "specified
but not built" and offers a `[?]` to register interest — neither fits a field that works
exactly as it appears and simply has no reader yet. A disabled box with a "not built yet"
dialog would misdescribe it.

The consequence to accept openly: for now this collects a value nothing reads. That is the
point of collecting it — the datum is cheap to gather while the user is on the screen and
expensive to ask for later.

**What it should do in this increment:** accept and store a Dutch postcode, and nothing else.
The ⓘ text names sunrise/sunset as the purpose, which is honest about the intent without
claiming the app currently does it.

> **Open — validation, and what eventually reads it.** Whether to enforce the `1234 AB`
> format (and whether to accept the PC4 digits alone) is unspecified; storing the string
> as typed is the safe default until a consumer needs a parsed form. The eventual reader is
> also unchosen — candidates are PV-coverage diagnostics
> ([§7.3](15-data-quality-and-limits.md)), epoch detection
> ([§6.15](13-configuration-epochs.md)), or daily-chart presentation. That choice decides the
> precision needed and whether a postcode→coordinate table ships with the app; a PC4 centroid
> is ±~2 km, worth well under a minute of sunrise error at NL latitudes, so the bar is likely
> low.

---

## 2′.5 Configure data

Panel ① of [§2.2](02-ux-wireframes.md#22-panel--data-input-expanded), unchanged in content,
promoted to a screen of its own. The slot roster, the source drawer and its staged-then-confirm
behaviour, the HA connection modal, the data-quality box and "Your data at a glance" all keep
their specified behaviour.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Your analyses                        Our house, dynamic contract          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Configure data                                                             │
│                                                                              │
│  ┌─ About your household ─────────────────────────────────────────────────┐  │
│  │  Do you have solar PV?          ( • ) Yes    (   ) No                  │  │
│  │  Do you already have a battery? (   ) Yes    ( • ) No                  │  │
│  │  ⓘ These decide which measurements the app asks you for below.         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Series slots ─────────────────────────────────────────────────────────┐  │
│  │  … §2.2's roster, unchanged: ROLE / REQ / SOURCE, the [ … ▸ ] drawer   │  │
│  │    opener per row, the ● ○ ◐ legend, [ Fetch history ]                │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Data quality ─────────────────────────────────────────────────────────┐  │
│  │  … §2.2, unchanged. Present once data has loaded.                      │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌─ Your data at a glance ────────────────────────────────────────────────┐  │
│  │  … §2.3a, unchanged. Present once data has loaded.                     │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│                                      [ Cancel ]            [ Save ]          │
└──────────────────────────────────────────────────────────────────────────────┘
```

Two changes from §2.2:

- **`has_pv` / `has_battery` get a titled box.** They sit loose under the panel title today.
  As a screen rather than a panel, an untitled pair of questions above a table reads as
  chrome; the box names what they are for. Their behaviour is unchanged — they still re-derive
  the roster in place ([§3.2](04-state-machine.md)) and are still committed with the fetch.
- **The `[ Next: parameters → ]` CTA is replaced** by the footer described in
  [§2′.8](#28-the-footer-and-the-two-entry-points).

The source drawer stays a right-side overlay over this screen, with its transactional
Confirm/Cancel semantics untouched.

---

## 2′.6 Results

Panels ② and ③ combined, with ② reduced to a capacity-first battery box.

The controls sit in a fixed column on the left; the results scroll beside them. (The layout is
specified below under ["The controls are a fixed
column"](#the-controls-are-a-fixed-column-not-the-top-of-a-long-page); this wireframe shows
what is *in* each region.)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Your analyses                        Our house, dynamic contract          │
├──────────────────────────────┬───────────────────────────────────────────────┤
│ ┌─ Battery ─────────────────┐│  … §2.4 unchanged: the energy-use section, ▲  │
│ │ Usable capacity           ││    ENERGY SAVINGS with its KPI tiles,      │  │
│ │  [  10.0 ] kWh            ││    breakdown, benchmark and secondary      │  │
│ │  ⓘ not the nameplate      ││    metrics, COST SAVINGS when the toggle   │  │
│ │                           ││    below is on, charts, caveats.           │  │
│ │ ┌ More settings ────────┐ ││                                            │  │
│ │ │ 2 changed  [ expand ] │ ││  Simulate cost savings?  (   ) Yes  ( • ) No│ │
│ │ │ (Battery)(Installation)│││                                            │  │
│ │ │ (Charge & discharge)  │ ││                                            │  │
│ │ │ ───────────────────── │ ││                                            │  │
│ │ │ Min / Max SoC         │ ││                                            │  │
│ │ │   [ 10 ] % / [ 100 ] %│ ││                                            │  │
│ │ │ Max charge   [ 5.0 ] kW│││                                            │  │
│ │ │ Max discharge[ 5.0 ] kW│││                                            │  │
│ │ │ Round-trip   [ 90 ] % │ ││                                            │  │
│ │ │ Standby draw [ 30 ] W │ ││                                            │  │
│ │ │ Initial SoC  [ 50 ] % │ ││                                            │  │
│ │ │ Coupling: AC-coupled  │ ││                                            │  │
│ │ │                       │ ││                                            │  │
│ │ │ (Installation holds   │ ││                                            │  │
│ │ │  §2.3 box 3, the      │ ││                                            │  │
│ │ │  illustrated topology │ ││                                            │  │
│ │ │  selectors; Charge &  │ ││                                            │  │
│ │ │  discharge holds boxes│ ││                                            │  │
│ │ │  4 and 5 stacked —    │ ││                                            │  │
│ │ │  P1/P2/P3 w. bands A/B│ ││                                            │  │
│ │ │  D1/D2/D3 w. bands C/D│ ││                                            │  │
│ │ │  export toggle, econ. │ ││                                            │  │
│ │ │  guard — overlap      │ ││                                            │  │
│ │ │  warning below both)  │ ││                                            │  │
│ │ └───────────────────────┘ ││                                            │  │
│ │            [ Calculate → ]││                                            │  │
│ └───────────────────────────┘│                                            │  │
│ ┌─ Period ──────────────────┐│                                            │  │
│ │ [1 week] [1 month]        ││                                            │  │
│ │ [3 months] [6 months]     ││                                            │  │
│ │ (•1 year•)  [ custom ]    ││                                            │  │
│ │ 2025-07-22 → 2026-07-21   ││                                            │  │
│ │ · 365 days · 8,760 interv.││                                            │  │
│ │        ⟳ recalculating…   ││                                            │  │
│ └───────────────────────────┘│                                            ▼  │
│        ↕ own scroll          │  ↕ own scroll                                 │
└──────────────────────────────┴───────────────────────────────────────────────┘
```

When the workspace has no contract configured, the toggle is blocked:

```
│  │  Simulate cost savings?   (   ) Yes   ( • ) No   ⓘ                     │  │
│  │                           ↑ greyed                                     │  │
```

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Set up your contract first                                          │
  │                                                                      │
  │     To put a euro figure on your savings, the app needs to know      │
  │     what you pay for electricity — your contract type and its        │
  │     rates.                                                           │
  │                                                                      │
  │     You have not set those up for this analysis yet.                 │
  │                                                                      │
  │  [ Set up my contract → ]                                   [ close ]│
  └──────────────────────────────────────────────────────────────────────┘
```

### Why capacity comes first and alone

Usable capacity is the parameter a user actually shops for and the one whose effect on the
answer is largest and most legible: it is the number on the product page. Everything else in
§2.3's battery box is either an installer detail (efficiency, standby, coupling), a
constraint the hardware fixes (charge/discharge power), or a modelling choice (initial SoC,
policies, bands). Putting one field in front of a collapsed pane means the common path —
"what would a 10 kWh battery have done for me?" — is a single input away from a result, while
nothing is removed from the user who wants it.

**The advanced pane preserves state and does not reset on collapse**, exactly as in
[§2′.4](#24-edit-workspace). Its collapsed summary should name how many values differ from
the defaults.

### The advanced pane is tabbed, not nested

§2.3's four remaining boxes sit behind **three tabs inside one pane**, rather than as four
stacked boxes inside it. Stacking them would put the illustrated topology selector three
frames deep (pane → box → selector), and that selector is itself a visual chooser with SVG
options ([§2.5](03-topology-selector.md)) — it needs width and does not survive being nested
that far. Tabs keep every group one click from the others and give each the full width of the
pane.

```
   ( Battery )  ( Installation )  ( Charge & discharge )
```

**Charge and discharge share one tab.** They are two halves of one decision: the bands must
not overlap, and §2.3's overlap warning compares band A/B against band C/D. Splitting them
would put that warning on one tab while the values it indicts sat on the other, and would ask
the user to configure a dispatch strategy while seeing half of it. The tab holds §2.3's boxes
4 and 5 stacked, with the warning below both — which is where it already sits today.

The tab order runs from the settings most users might touch to the ones almost nobody will.
**Battery is the default tab**, since a user who opens the pane at all most likely came for a
power or SoC limit.

This is a presentation choice and nothing depends on it: the four groups keep their §2.3
contents, their validation and their gating (the PV-blocked charge policies, the cost-gated
economic guard, the soft block on unsupported battery phases) exactly as specified. If tabs
prove awkward in practice, stacked boxes remain a valid fallback.

### This screen has no footer buttons

There is nothing to cancel or save: parameter edits are committed by the parameter box's own
`[ Calculate → ]`, which recomputes and persists, as they were before this restructure. The
screen is left through the back link.

([§3.5](04-state-machine.md#35-persistence-points) specifies a debounced auto-persist on
`PARAMS_CHANGED` in addition to that button. It is **not built** — see the note there — so
today `[ Calculate → ]` is the only thing that commits a parameter edit.) This is the one screen where the wizard's `[ Previous ] /
[ Next ]` and the card's `[ Cancel ] / [ Save ]` do not apply, because it is the end of both
paths.

### What is unchanged

`RESULTS_STALE` still renders the previous results dimmed rather than blanking them
([§3.1](04-state-machine.md#31-session-level-states)), and editing a parameter still does not
navigate away from the figures.
[§3.4](04-state-machine.md#34-screen-structure-and-what-must-stay-visible-together) calls
"the parameters and the results must be visible at the same time" the single most important
interaction detail in the app. Here that is met structurally: **the controls and the results
are on one screen**, so a capacity change and its effect are visible at once. That is why
parameters were not given a screen of their own.

### The controls are a fixed column, not the top of a long page

Above the `lg` breakpoint the screen is exactly one viewport tall and the page itself does not
scroll. The header is pinned; below it the width divides in two, each side owning its own
scrollbar:

```
┌─ ← Your analyses ─────────── Our house, dynamic contract ──── [NL][EN] ─┐
├──────────────────────┬───────────────────────────────────────────────────┤
│ ┌ Battery ─────────┐ │  RESULTS                                       ▲  │
│ │ Usable capacity  │ │  … the energy and cost sections                │  │
│ │ [ 10.0 ] kWh     │ │  … KPI tiles, benchmark, charts, caveats       │  │
│ │ ┌ More settings ┐│ │                                                │  │
│ │ │(Bat)(Ins)(Chg)││ │                                                │  │
│ │ └───────────────┘│ │                                                │  │
│ │      [Calculate →]│ │                                                │  │
│ └──────────────────┘ │                                                │  │
│ ┌ Period ──────────┐ │                                                ▼  │
│ │ (1 week)(30 days)│ ├───────────────────────────────────────────────────┤
│ │ From […] To […]  │ │  the site footer — pinned, never scrolls          │
│ └──────────────────┘ │                                                   │
│      ↕ own scroll    │  ↕ own scroll (figures only)                      │
└──────────────────────┴───────────────────────────────────────────────────┘
```

**Inputs on the left, answers on the right.** The battery box and the period card are the two
questions — "what battery" and "over what window" — and everything in the right column is a
function of both.

This *replaces* the earlier mechanism, in which the battery box and the results sat on one long
page and **scrolled together**. That met §3.4's requirement only near the top of the page:
scrolling down to the charts took the capacity field off screen, and changing it meant
scrolling back up and then back down to see what changed — on the very screen whose stated
purpose is seeing both at once. A fixed control column meets the same requirement
unconditionally, at every scroll position. **The requirement did not change; the mechanism
that was failing it did.**

The control column **scrolls internally** when its own content outgrows the viewport — the
advanced pane opens a tab of fields, and a control the user cannot reach would be a worse
failure than a second scrollbar.

**The site footer is a pinned band at the bottom of the results column, not the end of its
scroll.** It carries the privacy statement, the attribution, the licence and the NO WARRANTY
control — a notice whose whole purpose is that a reader can find it. Because the page itself does
not scroll above `lg`, the footer has to live inside one of the two columns; putting it at the
bottom of the figures' scroll made it reachable only from the very end of them, behind some
3400px of charts on a typical window. Pinning it splits the results column into a scrolling half
and a fixed half, so the notice is on screen at every scroll position and the figures scroll
beneath it. Below `lg` it returns to normal flow at the end of the stacked page, as on the other
three screens.

**Below `lg` the screen falls back to the vertical stack**: the page scrolls, the columns
become blocks, and the controls sit above the results as before. The two-column form needs
width a phone does not have, and a fixed panel on a short viewport would leave the results a
few lines tall. On that viewport the parameters and the figures are once again visible only by
scrolling between them — the constraint is real and the fallback is the honest response to it.

### The cost toggle and its precondition

**The toggle sits inside the results block**, under the period selector and above the result
sections — not in the battery box, and not floating between the two. It reshapes the results,
so it belongs to them.

**It is Blocked — greyed — until the workspace has a contract configured**, with an ⓘ beside
it opening the dialog shown above. This is the Blocked state from
[§2.1](02-ux-wireframes.md#the-four-availability-states), used exactly as specified: a
precondition is unmet, the user can clear it, and the adjacent affordance says how. The
dialog's `[ Set up my contract → ]` navigates to the workspace's edit screen with the Contract
box in view; returning finds the toggle live.

Blocked is right here and Inapplicable would not be. Cost simulation is not meaningless for
this household — it is one screen away from working, and hiding the toggle would leave a user
who wants euro figures with nothing to click and nothing to read.

### "A contract configured" is an explicit flag

The precondition cannot be derived from the current model. `PricingConfig` is always fully
populated from [appendix A](appendix-a-defaults.md) — there is no null contract and no unset
state — so any test written against its fields would pass for every workspace and the toggle
would never actually block.

**A new persisted boolean therefore carries it: `pricing.configured`.** False on a new
workspace; set true when the user saves the edit-workspace screen having touched the Contract
box. It is the only field whose meaning is "the user has told us what they pay", and it is
read by exactly one thing — whether the cost toggle is Blocked.

The alternative, testing whether the pricing config differs from the defaults, was rejected as
fragile in both directions: a household whose real supplier markup happens to equal the
default would be told it has no contract, and any stray edit — including one the user
reverted — would silently unlock the toggle. A flag says what it means.

**Two rules keep the flag honest:**

- **Migration must not regress an existing user.** The workspace migrated from `local`
  ([§2′.10](#210-what-the-backend-needs-noted-not-designed)) is set `configured = true` if
  `simulate_cost` is already on — someone with cost results on screen today must not find them
  switched off and the toggle blocked after an upgrade. A workspace with cost simulation off
  migrates as `false`, which costs nothing: the toggle they were not using becomes one that
  asks for a contract first.
- **It is never cleared automatically.** Turning cost simulation off does not unset it, for the
  same reason `economic_guard` is retained rather than erased
  ([`simconfig_store`](08-architecture.md#51-diagram)): a user who toggles off and back on
  should find their contract where they left it.

- **Saving the screen sets it, not editing a field.** The flag means the user committed to a
  contract, so an abandoned edit — typed into and then cancelled — leaves it false. This
  follows the `[ Cancel ]` semantics in
  [§2′.8](#28-the-footer-and-the-two-entry-points): what is not saved did not happen. In the
  wizard, `[ Next → ]` persists and therefore sets it on the same terms as `[ Save ]`.

---

## 2′.7 Where the setup band's questions went

The band held three scope answers. It is dissolved, and each answer moves to the surface it
shapes rather than to a single settings screen:

| Answer | New home | Shapes |
|---|---|---|
| `has_pv` | Configure data | Which slots the roster asks for; the PV-requiring charge policies |
| `has_battery` | Configure data | Whether the existing-battery slots appear |
| `simulate_cost` | Results | The Pricing-derived result sections, the economic guard, the euro chart tab |

**The rationale is proximity.** A shape question is easiest to answer correctly when its
effect is visible: flipping `has_pv` visibly adds or removes a row from the roster the user is
looking at, and flipping `simulate_cost` visibly adds or removes the cost section below it.
The alternative — collecting all three on the edit-workspace screen — would have made the
wizard ask every shape question before the user has seen anything, and would have put
`has_pv` two screens away from the roster it governs.

**Consequences to keep:**

- Everything [§3.2](04-state-machine.md) says about setup-band edits still applies unchanged:
  they emit an ordinary `PARAMS_CHANGED`, validation runs against the new field set, the
  roster is re-derived in place with mappings kept, and values are retained rather than
  discarded so toggling back restores the previous answer.
- `simulate_cost` gates no data slot. It once offered two `◒` bracket slots on the
  *configure data* screen, from a control on a *different* screen, which would have needed a
  legend that did not assume the toggle was visible; those slots are gone
  ([§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)
  derives the bracket from the spot series instead), and with them the cross-screen
  dependency. The roster's remaining gates — `has_pv` and `has_battery` — are both answered
  on this same screen.
- The `economic_guard` retention behaviour in `simconfig_store` is untouched.

**§2.4's invitation box stays as it is.** "Want to know what this is worth in euros?" keeps
its current place and behaviour alongside the toggle; the two coexist without either being
rewritten for the other. This is explicitly a hold rather than a conclusion — the pair is
worth revisiting once the restructured screen exists and the redundancy can be judged on
something real.

One thing to watch when it is revisited: the invitation currently anchors to
`#setup-simulate-cost`, an id in the setup band that this restructure removes. It needs to
point at the toggle's new location, and — under
[§2′.6](#the-cost-toggle-and-its-precondition) — to say something useful when the toggle it
points at is blocked.

---

## 2′.8 The footer, and the two entry points

**Edit workspace** and **configure data** are each reachable two ways, and the footer states
which path the user is on.

```
   From a card:          [ Cancel ]                              [ Save ]

   In the wizard:        [ ← Previous ]                          [ Next → ]
```

| | From a card | In the wizard |
|---|---|---|
| Left button | `[ Cancel ]` — discard, return to the list | `[ ← Previous ]` — back a step, keeping entries |
| Right button | `[ Save ]` — persist, return to the list | `[ Next → ]` — persist, advance a step |
| On step 1 | — | `[ ← Previous ]` returns to the list |

Rules:

- **`[ Next → ]` persists.** The wizard is not a transaction held in memory to be committed at
  the end: a workspace exists from the moment step 1 is completed, so an interrupted wizard
  leaves a usable workspace rather than nothing. This is what lets the third card in
  [§2′.2](#22-the-workspace-list--the-apps-home-screen) — configured, no data — exist as a
  legitimate state.
- **`[ Cancel ]` discards this screen's edits only**, and never deletes the workspace. A user
  who wants the workspace gone uses `[ Delete analysis ]` on the card.
- **`[ ← Previous ]` keeps what was entered**, consistent with the retention rule everywhere
  else in the app.
- The back link (`← Your analyses`) is present on every screen in both modes. In the wizard it
  behaves as `[ Cancel ]` on the current screen: entries on *this* screen are discarded, steps
  already completed stay saved.

**`[ Cancel ]` warns when there are unsaved changes.** Silently discarding a screenful of
typed contract parameters is a real loss, and the screens this footer appears on are exactly
the ones where a user does careful typing. With no changes made, `[ Cancel ]` leaves
immediately — an unconditional prompt would be noise on the common case of opening a screen
to look at it.

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Discard your changes?                                               │
  │                                                                      │
  │     You have changes on this screen that have not been saved.        │
  │     Leaving now discards them.                                       │
  │                                                                      │
  │                          [ Keep editing ]      [ Discard changes ]   │
  └──────────────────────────────────────────────────────────────────────┘
```

`[ Keep editing ]` is the default focus. The same check guards the **back link** in both
modes, and the wizard's `[ ← Previous ]` — anything that leaves a screen with unsaved edits.
It does not guard `[ Save ]` or `[ Next → ]`, which persist.

**On configure data, "changed" means a source was chosen but not yet fetched.** The dirty test
there is not a form-dirty check — the source drawer already commits its choices on Confirm,
and `[ Fetch history ]` writes the dataset, so most of that screen's work is persisted before
`[ Cancel ]` is ever reachable. What is genuinely unfinished is a **slot mapping that has
changed since the last fetch**: the roster says one thing and the loaded data reflects another,
and leaving now means the change never took effect.

The warning is therefore worded for what is actually at stake:

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  You have not loaded your data yet                                   │
  │                                                                      │
  │     You changed where some of your data comes from, but have not     │
  │     fetched it. Your results will still be based on the data         │
  │     loaded earlier.                                                  │
  │                                                                      │
  │                        [ Keep editing ]       [ Leave anyway ]       │
  └──────────────────────────────────────────────────────────────────────┘
```

The `has_pv` / `has_battery` answers do not trigger it on their own: they are committed with
the fetch today ([§2.2](02-ux-wireframes.md#22-panel--data-input-expanded)), and a user who
flips one without touching a source has changed which slots are *asked for*, not which data is
loaded.

> **Open — is "since the last fetch" tracked today?** The source generation counter in
> `db.workspace_state` marks when a fetch happened, but whether the mapping carries a
> comparable marker — enough to answer "has this slot changed since then" — is an
> implementation question this document does not settle.

### The wizard

`[ + New analysis ]` creates a workspace with default parameters
([appendix A](appendix-a-defaults.md)) and an editable placeholder title, then runs:

```
   [ + New analysis ]
          │
          ▼
   ┌──────────────────┐  Next →   ┌──────────────────┐  Next →   ┌──────────┐
   │ 1. Edit analysis │──────────►│ 2. Configure data│──────────►│ 3. Results│
   └──────────────────┘◄──────────└──────────────────┘◄──────────└──────────┘
          │            ← Previous          │           ← Previous
          │ ← Previous                     │
          ▼                                ▼
     Your analyses                    (back link at any point)
```

The three steps are the same three screens reachable from a card; only the footer differs. A
step indicator (`Step 2 of 3`) beside the screen title is suggested, not specified.

### `[ Next → ]` on step 2 is blocked until house load can be reconstructed

Advancing to the results step requires enough data to compute the household's load, since
that is what every figure on step 3 rests on. Until then `[ Next → ]` is **Blocked** rather
than leading to an empty results screen.

**It is Blocked without being disabled**, which is [§2.1](02-ux-wireframes.md#the-four-availability-states)'s
self-clearing exception rather than a departure from it. This button is the only submitter of
the form the `has_pv` / `has_battery` radios sit in, so disabling it also disables the answer
that clears the block: a household whose stored answers say "I have solar" but whose dataset
has none could see the reason "Add Solar production to continue", answer "no solar", and have
no way to submit that answer — `[ Fetch history ]` is disabled with nothing staged, and
`[ ← Previous ]` discards the radio. So the button stays live, the reason beside it carries
the Blocked meaning at full strength, and **the server-side check is the enforcement**: the
POST persists the two household answers first and only then re-checks the gate, re-rendering
step 2 with an accurate message if it is still unmet. A click from a genuinely blocked state
therefore records the answer and redraws; it never advances.

The condition is [§6.3](09-ingest-algorithms.md)'s load reconstruction,
`load = imp − exp + pv + batt_dis − batt_chg`, being computable. Concretely, a loaded dataset
in which:

- **grid import and grid export** are present. Each is a T1/T2 register pair in §2.2's
  roster, and the gate requires **the T1 register of each pair only**: T1 is §4.1's required
  slot, T2 is "expected" rather than required (note 4), and the reconciliation folds the pair
  so an absent T2 contributes zero. A single-tariff household has no T2 register to map, and
  requiring one would block those users behind a message naming a series they cannot supply;
- **solar production** is present *if* `has_pv` is on — without it the reconstruction silently
  attributes PV output to the house not existing, which is check 7's negative-load symptom
  ([§7.3](15-data-quality-and-limits.md));
- the **existing battery's** charge/discharge series are present if `has_battery` is on, for
  the same reason.

Note this is a *lower* bar than a full run: the spot price is required for dispatch but not
for load, so a workspace can pass this gate and still be unable to simulate. That is the right
place to draw the line for the wizard — step 3 can render the battery-free "Your data at a
glance" figures from load alone, and a missing spot price is a problem the results screen can
state in context.

The blocked button states which series are missing, naming them, rather than saying only "load
data first". The user is looking at the roster that would fix it.

**The back link remains available throughout**, so a user who cannot complete the fetch is
never trapped: leaving keeps the workspace with whatever was configured, which is exactly the
no-data card in [§2′.2](#22-the-workspace-list--the-apps-home-screen).

**There is no minimum duration.** The gate is about which series exist, not how long they run:
a user with three days of data may advance and see a result for three days. §2.4 already
guards the figures that a short window would distort — the annualised savings are replaced by
the short-window box under `min_annualisation_days` ([§7.4](15-data-quality-and-limits.md)) —
so a brief window yields a caveated result rather than a wrong one, and the wizard needs no
duration rule of its own.

This is the better division of labour: the wizard blocks on what makes results *impossible*
(no load), and the results screen explains what makes them *weak* (too short a window). A
duration gate in the wizard would duplicate that judgement in a place with less context, and
would turn away a user legitimately checking a week of data.


---

## 2′.9 State machine, revisited

[§3](04-state-machine.md)'s session states describe **one workspace's** lifecycle. Under this
restructure they become per-workspace and are entered when a workspace is opened, which has
three consequences:

- **The list screen is outside the state machine.** It is not a state of a session; it renders
  from stored config and dataset metadata for every workspace and drives no transition. The
  states in §3.1 apply from the moment a workspace is opened.
- **`run_id` was already specified as per-workspace** ([§3.3](04-state-machine.md#33-concurrency-and-run-identity)),
  so nothing changes there. If two workspaces can be open in two browser tabs, the SSE channel
  and the `JobRunner`'s keying by `workspace_id` ([§5.1](08-architecture.md#51-diagram))
  already carry the distinction.
- **§3.5's startup rule is rewritten to match.** It previously read "on startup the server
  restores the most recent workspace and lands the user in `RESULTS_STALE`", which was
  written for a single implicit workspace. With a list screen the user lands on the list, and
  no workspace is restored or recalculated until one is opened.

[§3.4](04-state-machine.md#34-screen-structure-and-what-must-stay-visible-together)'s panel
focus model is gone: with data and results on separate screens there is no collapse/expand
stepper to model. What survives is the rule underneath it — parameters and results must be
visible together — which [§2′.6](#the-controls-are-a-fixed-column-not-the-top-of-a-long-page)
keeps by putting the controls in a fixed column beside the scrolling results, and which §3.4
now states as the requirement rather than as a property of the mechanism.

---

## 2′.10 What the backend needs (noted, not designed)

This document is a UX specification. The following are the implications a later design pass
must cover; none of them are settled here.

- **A workspace index.** `08-architecture.md` §5.1 already lists
  `workspaces(id, owner_id, name, created_at)`, but no such table exists in code —
  `db.WORKSPACE_ID` is the module constant `"local"`. The list screen needs this table plus
  an `updated_at` for card ordering and the "last saved" badge, and a title column.
- **Workspace-scoped routes.** Every route in `app/main.py` is currently unscoped
  (`/params`, `/results`, `/data/slot/{slot}/load`, the ingest WebSocket). Each needs to
  resolve a workspace. §5.1 already specifies the seam:
  `deps.get_workspace(principal, id)`.
- **Migration of the existing workspace.** The `"local"` workspace has a config on disk and
  possibly a dataset. It must become a listed workspace with a generated title rather than
  being orphaned or silently deleted.
- **New persisted fields.** `title` and the postcode are both new — `SimulationConfig` has
  neither today. Whether the title belongs on the config document or on the workspace row is a
  design question; the workspace row is the more natural home, since the title names the
  workspace rather than parameterising a run. The postcode is stored but read by nothing this
  increment ([§2′.4](#the-zip-code)). A third is `pricing.configured`, the boolean that gates
  the cost toggle ([§2′.6](#a-contract-configured-is-an-explicit-flag)) — it must be set true
  for a migrated workspace that already has `simulate_cost` on, or an existing user loses
  their cost results on upgrade.
- **`updated_at` must move with the config, not the dataset.** The card's "last saved" badge
  and the list's ordering both read it, and §2′.2 defines it as the *configuration's* save
  time — so loading data must not reorder the list or advance the badge.
- **Cascade semantics for the two deletes.** "Delete data" must clear the dataset rows, the
  `.npz` files and any cached results while leaving `simconfig.json`
  ([§2′.3](#23-the-two-confirmation-modals)). It does *not* leave a fetched slot's source
  mapping, which lives in `series_meta` and goes with the data — §2′.3 sets out the split and
  the dialog copy states it; "delete analysis" must remove the workspace
  directory and every row keyed by its id — with one exception, below.
- **`feature_interest` becomes installation-wide**, dropping `workspace_id` from its key.
  **— SUPERSEDED. The table no longer exists.** A feature request is filed as a GitHub issue
  ([§2.1](02-ux-wireframes.md#the-pending-affordance)) and nothing is recorded locally, so the
  exception this decision introduced is gone and §5.5's invariant 1 holds without carve-outs.
  The reasoning is kept below because it is the test any future candidate for an exception has
  to pass, not because the table it describes is still there.

  It
  records that *this household* wants a feature, which is a fact about the person using the
  app rather than about any one analysis: a user who thumbs up "upload CSV" from one workspace
  has not said something narrower by having done it there. Keying it per workspace also makes
  the counter answer the wrong question — the same person could register the same wish three
  times from three analyses, and a workspace deletion would silently retract a signal the user
  never withdrew.

  This is a **deliberate exception to §5.5's invariant 1** ("Every persisted row carries
  `workspace_id`. No table is implicitly global"), and the first one. It should be recorded as
  such in [08-architecture.md](08-architecture.md) rather than left as an inconsistency for a
  later reader to trip over. The invariant's purpose is that user *data* never leaks between
  workspaces or, later, between accounts; interest counters are not user data in that sense —
  they are outbound product telemetry, already reported under the pseudonymous
  `installation_id` from `config.toml` rather than under any workspace identity.

  Consequences: the primary key becomes `feature_key` alone; existing rows collapse by key,
  taking the earliest `last_clicked_at` and preserving the thumbed-once semantics (interest
  stays boolean per household, so the merge is a union, not a sum); and the rows survive
  deletion of every workspace, including the last.

  Note this leaves `workspace_state.source_generation` correctly per-workspace — it tracks one
  workspace's fetches and must not be shared.
- **Nothing in the domain layer changes.** No spec file from
  [09-ingest-algorithms.md](09-ingest-algorithms.md) through
  [16-validation-harness.md](16-validation-harness.md) is affected by this document.

---

## 2′.11 Decisions and remaining questions

### Resolved — first round (2026-07-26)

| # | Question | Decision | § |
|---|---|---|---|
| 1 | Contract badge when cost is off | Always shown, full strength | [§2′.2](#the-badges) |
| 2 | Does "delete data" clear the source mapping | No — mapping is kept | [§2′.3](#23-the-two-confirmation-modals) |
| 3 | Off-list connection (`1×20 A`) | Preset list only; overrides cover the rest | [§2′.4](#the-connection-dropdown) |
| 4 | Contract box when cost is off | Always shown | [§2′.4](#what-is-not-on-this-screen) |
| 5 | Zip code | Live and persisted now, wired later | [§2′.4](#the-zip-code) |
| 6 | Nesting of the advanced pane | Tabbed, capacity still first | [§2′.6](#the-advanced-pane-is-tabbed-not-nested) |
| 7 | Cost toggle placement | Inside the results block; Blocked until a contract exists | [§2′.6](#the-cost-toggle-and-its-precondition) |
| 7b | §2.4's invitation box | Kept as is, revisit later | [§2′.7](#27-where-the-setup-bands-questions-went) |
| 8 | `[ Cancel ]` and unsaved changes | Warns when dirty | [§2′.8](#28-the-footer-and-the-two-entry-points) |
| 9 | `[ Next → ]` with no data | Blocked until house load is reconstructable | [§2′.8](#-next---on-step-2-is-blocked-until-house-load-can-be-reconstructed) |
| 11 | Header badge and ⚙ | Both removed | [§2′.2](#the-header) |

### Resolved — second round (2026-07-26)

The five that the first round's answers left open:

| # | Question | Decision | § |
|---|---|---|---|
| 12 | What counts as "a contract configured" | A new persisted `pricing.configured` flag | [§2′.6](#a-contract-configured-is-an-explicit-flag) |
| 13 | Where the band-overlap warning lives | Charge and discharge merge into one tab; warning below both | [§2′.6](#the-advanced-pane-is-tabbed-not-nested) |
| 14 | "Changed" on configure data | A slot's source changed but `[ Fetch history ]` not yet pressed | [§2′.8](#28-the-footer-and-the-two-entry-points) |
| 15 | Minimum data duration for the wizard | None — §7.4's short-window guard covers it | [§2′.8](#-next---on-step-2-is-blocked-until-house-load-can-be-reconstructed) |
| 10 | `feature_interest` and workspace deletion | Elevated to installation-wide; `workspace_id` dropped — **superseded, table removed** | [§2′.10](#210-what-the-backend-needs-noted-not-designed) |
| 16 | What sets `pricing.configured` | Saving the screen, not editing a field | [§2′.6](#a-contract-configured-is-an-explicit-flag) |

### Resolved — third round (2026-08-09)

| # | Question | Decision | § |
|---|---|---|---|
| 17 | How "parameters and results visible together" is met | A fixed control column beside a scrolling results column, replacing the single scrolling page | [§2′.6](#the-controls-are-a-fixed-column-not-the-top-of-a-long-page) |
| 18 | What goes in the fixed column | Both control cards — battery box and period card. The cost toggle stays in the results block per decision 7 | [§2′.6](#the-controls-are-a-fixed-column-not-the-top-of-a-long-page) |
| 19 | The column outgrowing a short viewport | It scrolls internally rather than clipping | [§2′.6](#the-controls-are-a-fixed-column-not-the-top-of-a-long-page) |
| 20 | Narrow viewports | Fall back to the stacked, single-scroll layout below `lg` | [§2′.6](#the-controls-are-a-fixed-column-not-the-top-of-a-long-page) |

Decision 17 revises the mechanism decisions 6 and 7 were written against, and
[§3.4](04-state-machine.md#34-screen-structure-and-what-must-stay-visible-together) with it.
The requirement those sections protect is unchanged — it is the reason for the revision, since
scrolling-together met it only near the top of the page.

Decision 10 had reach beyond this document: it made `feature_interest` the first deliberate
exception to §5.5's "no table is implicitly global" invariant. It has since been superseded —
the table was removed when feature requests moved to GitHub issues — so the invariant holds
without exceptions again, and [08-architecture.md](08-architecture.md) records that rather than
the carve-out.

### Still open

None. The last one — whether "changed since the last fetch" is trackable — is answered by
what already exists: `ha_fetch.js` keeps pre-fetch slot customizations in `localStorage`
under `ha.slots`, tagged with the `source_generation` they were saved at, precisely so a
customization made before a fetch survives a reload and is discarded once a newer fetch
supersedes it. A non-empty entry at the current generation *is* the "changed but not fetched"
state the warning in [§2′.8](#28-the-footer-and-the-two-entry-points) describes.

One consequence for the build: that store is a single browser-global key today. It must
become **per workspace**, or a mapping staged in one analysis will appear staged in another.
The same applies to the HA base URL and token, though sharing those across workspaces is
arguably correct — one household, one Home Assistant.

Lower-priority, noted where they arise: postcode format validation and what eventually reads
it ([§2′.4](#the-zip-code)).
