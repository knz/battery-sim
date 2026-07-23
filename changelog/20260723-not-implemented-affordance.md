# 20260723 — "Not implemented yet" affordance with interest counter

## Task specification

User request (verbatim, from `todo.txt`):

> UX wireframes: in various places, we'll want to mark a feature as "not implemented yet":
> UI control disabled / greyed out, but with a small button next to it that pops up a dialog
> that explains "this is not implemented yet, if you are interested please click the button
> below" with a "thumbs up" button. The button increments a corresponding feature counter in
> the database, as well as performs an asynchronous POST request to a configurable URL
> (failures ignored).

Standing guidance at the top of `todo.txt`:

> Whenever possible, it will be preferable to rewrite/simplify existing paragraphs -- we do
> not have users who know the previous version so there is no need to inform them of what
> has changed.

Context: seventh in the 2026-07-23 series of spec changes. Unlike the previous six, this
one implies runtime behaviour — a database write and an outbound network request — not only
prose and wireframes.

## Requirements change — what the item actually is

The investigation asked which features would carry the affordance, having found that no
control in the wireframes is currently marked unimplemented. The user's answer (verbatim)
reframed the item:

> we will proceed to implement the app incrementally, one feature at a time, but set up the
> UI/UX screens early. until the corresponding machinery is implemented, we'll use the 'not
> implemented yet' screen

So the mechanism is not infrastructure awaiting call sites, and it is not a request to add
new controls. The specs describe the complete intended UI; the app is built incrementally
behind it; any control whose machinery is pending wears the state until its feature lands.

Two consequences drive the spec text:

1. **Call sites are transient and set by build order, not by the spec.** The spec must not
   enumerate which controls are currently pending — such a list is stale as soon as the
   first feature ships.
2. **The state is temporary by construction.** This is the root distinction, and the
   vocabulary fix this item is really about. Hidden-inapplicable, disabled-precondition and
   soft-blocked are all permanent properties of a *configuration*. Pending is a property of
   *build progress* and is expected to disappear. Without that stated, a later reader reads
   "not implemented yet" as a product decision rather than a temporary condition.

## Findings

### Deployment and privacy posture

- There is a server component: FastAPI + service layer + SQLite, `08-architecture.md` §5.1.
- Database is SQLite via SQLAlchemy; schema in §5.1 has six tables, every one carrying
  `workspace_id` (§5.5 invariant 1: "Every persisted row carries `workspace_id`. No table is
  implicitly global").
- Outbound network requests today: HA WebSocket/REST (`HaStatsClient`), a future
  `EntsoeClient`. Both are user-configured data sources on the local network or explicitly
  chosen. There is no telemetry, analytics or phone-home anywhere in the package.
- There is **no explicit "your data never leaves your machine" promise**. The nearest
  statement is §7.5 ops note: bind `127.0.0.1` by default, warn on non-loopback bind. The
  motivation given is HA-token protection, not data-egress policy.
- Config lives in a single `config.toml` beside the data directory (§5.4), env-var
  overridable.

### Existing conventions for unavailable features

Three mechanisms already exist and are **distinct**:

1. **Hidden because inapplicable** — `has_pv` / `simulate_cost` off. Wireframes §2.2, §2.3
   ("Absent, not greyed — there is nothing here the user can usefully look at without opting
   in"), §2.4. Explicit rejection of greying.
2. **Disabled because a precondition is unmet** — `[ Load data ]` while a slot is empty;
   annualisation under 90 days; `economic_guard` forced off without a cost model.
3. **Soft block on an unsupported choice** — `03-topology-selector.md` (b): the two
   unsupported phase topologies carry `⚠ not in v1`, remain selectable, and open a dialog
   that explains the limitation and asks the user to **email `setups@<domain>`** because
   "It directly determines whether this lands in version 2". This is the closest existing
   analogue of the requested affordance, and it is an *email* call-to-action rather than a
   counter.

So "hidden because inapplicable" and "disabled because unimplemented" are already
distinguished in spirit; the third state is currently one-off and hand-rolled.

### Candidate call sites

See the report. Only one confirmed call site exists today (the topology soft block, which
is not disabled but soft-blocked). Everything else is deferred *silently* — out-of-scope
items in §1.5 have no UI presence at all.

## Decisions

**D1 — the fourth state, named `pending`.** A control that is specified but whose machinery
is not yet built renders disabled, with an adjacent affordance opening a dialog that
explains the situation and offers a thumbs-up. Defined once in `02-ux-wireframes.md` §2.1
alongside the other three states, glossed in `appendix-b-glossary.md`.

**D2 — naming.** Prose term **pending**; user-facing label **"not built yet"**. The
investigation leaned toward reusing "not in v1", the label already on the topology
selector's unsupported options. Rejected on the Q1 reframing: "not in v1" states a release
decision, which is exactly the wrong reading for a condition that clears when the next
increment ships. "Deferred" was rejected for the same reason — it implies someone decided to
postpone. "Not built yet" says only that the work has not happened, which is the accurate
claim. "Not in v1" stays where it is on the topology selector, where it does describe a
release decision.

**D3 — egress off by default.** The POST URL is unset in `config.toml` and no request ever
fires unless a user or packager sets one. A positive egress statement goes in
`15-data-quality-and-limits.md` §7.5 beside the loopback-bind and token-logging notes: what
is transmitted, when, to whom, that it is off unless configured, and that failures are
ignored and never surface.

**D4 — counter table.** `feature_interest(workspace_id, feature_key, count, last_clicked_at)`
in `08-architecture.md` §5.1. Carries `workspace_id`, so §5.5 invariant 1 ("no table is
implicitly global") is preserved unmodified. Rejected: a global table with a carve-out from
that invariant — it edits a stated architectural rule for no real gain.

**D5 — feature keys.** Short stable strings, a closed vocabulary listed in one place in
§2.1, same discipline as the series-name vocabulary in `05-data-formats.md`. Keys are
allocated as controls are marked pending and retired when the feature lands; counter rows
outlive the key so historical interest is not lost.

**D6 — payload: key, app version, installation id.** *This went against the
investigation's recommendation and was chosen deliberately by the user*, to allow
deduplication of repeat clicks from one installation. The investigation advised key-only or
key-plus-version, on the grounds that a stable id makes the request a persistent
pseudonymous identifier and complicates the privacy statement. The user accepted that trade
for deduplication. Because the recommendation was overruled, the spec specifies the id
carefully rather than minimally: what it is, what it is not derived from, that it is stable
across runs and therefore a persistent pseudonymous identifier, and how to reset it. The
mitigation is D3 — the id only ever leaves a machine whose operator configured a URL.

**D7 — topology dialog keeps its email.** `03-topology-selector.md` gains a sentence saying
why: that dialog asks for structured technical detail needed to build the feature (inverter
model, phase allocation, per-phase sensors), not a vote, and a counter cannot carry it.
Stated so the two mechanisms do not drift together later.

**D8 — acknowledgement, no counts shown.** One-time acknowledgement in the dialog. A second
click does not double-count and the dialog says interest is already registered. No count is
ever displayed — on a single-user install it would read as pointless or be mistaken for a
global figure.

**D9 — no fixture.** Every fixture in `16-validation-harness.md` is pure-domain, arrays in
and numbers out with no I/O. A fixture here would be the first to break that property. The
guarantees are stated as invariants in §5.1 and §7.5 instead: a POST failure or timeout
never changes any user-visible state; the counter increments exactly once per click; an
unset URL disables the request and nothing else.

## Files modified

- `specs/02-ux-wireframes.md` — new §2.1 subsection defining the four availability states
  and the pending affordance, with the dialog wireframe and the feature-key vocabulary rule.
- `specs/08-architecture.md` — §5.1 gains the `feature_interest` table, the
  `routes/feedback.py` entry and the `InterestReporter` adapter, with the invariants stated
  below the diagram; §5.4 gains the config keys.
- `specs/15-data-quality-and-limits.md` — §7.5 gains the egress note.
- `specs/01-product-brief.md` — §1.5 gains a line on the egress posture.
- `specs/appendix-a-defaults.md` — the two new config defaults.
- `specs/03-topology-selector.md` — one paragraph distinguishing the soft block from
  pending.
- `specs/appendix-b-glossary.md` — glossary entry for *pending*.
- `specs/README.md` — §2 file-contents row updated.

`04-state-machine.md` deliberately untouched: the counter write is not session state and
does not belong in the §3.5 persistence list.

## Current status

Complete. All eight spec files edited. `todo.txt` not modified and nothing committed, per
instruction.
