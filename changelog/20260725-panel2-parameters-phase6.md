# Phase 6 — Panel ② (Parameters) wired for real

## Task specification

Wire panel ② (specs §2.3, §2.5) end-to-end: a working form, persistence of the
`SimulationConfig` alongside the persisted dataset, per-field validation surfacing
(§7.3 checks 11/12/18), and re-simulation of panel ③ from the persisted config.

Deliverables handed down:

1. Persistence in the data dir; survives restart; corrupt/absent → appendix-A defaults, never
   a 500; cost-only params retained at their stored values (appendix A).
2. A real form + a POST route: parse, coerce strings to numbers (the form layer's job —
   `simconfig._finite` deliberately rejects `str`), build `SimulationConfig`, validate,
   persist ONLY when valid, re-render the panel. On failure re-render with the submitted
   values still in the fields and errors bound inline per field.
3. Surface validation: check 11 blocks (field-keyed by dotted path), check 12 warns and
   allows, check 18 is a SOFT block setting `topology.approximated`.
4. Panel ③ driven from the persisted config (`results_from` currently builds
   `SimulationConfig()` internally). `POST /results` and `POST /results/benchmark` use the
   same config. Benchmark stays lazy.
5. The collapsed summary line computed from the config.
6. UI gating from the config's own offerability queries.

Out of scope / forbidden: modifying `simulate.py`, `simframe.py`, `benchmark.py`,
`metrics.py`; euro figures / the Pricing box / run E; literal `%` inside `_()` strings.

## Context established from prior phases

- `SimulationConfig` (commit 6a8707c) was built for this phase: non-raising construction,
  field-keyed `validate()`, forced invariants on read, derived values as properties,
  `offerable_charge_policies()` / `offerable_discharge_policies()` / `battery_phases_offered`,
  `max_import_kw_display`.
- The established route pattern (changelog 20260724-panel3-prototype-zero-battery) is
  `POST` → render the fragment standalone → the browser swaps by `outerHTML`, with all
  listeners delegated from `document` in `index.html` (never swapped). Followed here.

## High-level decisions

### Persistence: one JSON document per workspace, not a SQLite table

`<data_dir>/<workspace>/simconfig.json`, written atomically (temp file + `os.replace`),
versioned, read whole. The dataset splits itself between SQLite metadata and `.npz` arrays
because it is a growing collection of rows with a history; a parameter set is not — there is
exactly one current config per workspace, it is a handful of scalars, and nothing queries
across configs. A single document read whole makes the corrupt-file fallback a two-line `try`,
which is what deliverable 1 asks for. It sits in the same `<data_dir>/<workspace>/` directory
the series live under, through the same traversal-rejecting rule, so a workspace stays one
directory on disk.

`load()` never raises for any reason: absent file, unreadable file, invalid JSON, a JSON value
that is not an object, an out-of-vocabulary enum, a wrong-typed field. Every one degrades to
the appendix-A default for the affected field or for the whole config. `save()` DOES propagate
an I/O error — a save that silently did nothing would tell the user their parameters were
stored when they were not.

### The cost-only retention needed a slot the config object cannot reach — see "Obstacles"

### Form shape: a real HTML form POSTing to `/params`, returning the re-rendered panel

Rejected: JSON + client-side re-render. Panel ② is ~20 inputs whose re-render has to place
per-field errors next to the inputs that caused them; doing that client-side would mean a
second, JS-side copy of the label/gating/translation logic `params_view` already owns. Returning
the rendered panel keeps ONE renderer, and matches the panel-③ pattern already in the codebase,
so the browser side is a delegated `submit` listener and an `outerHTML` swap.

The route sequence is §3.2's `PARAMS_CHANGED` verbatim ("Validate; persist; if valid →
`INPUT_CHANGED`"): coerce → build on top of the STORED config → validate → persist only when
nothing blocks → re-render from the CANDIDATE either way. Re-rendering the stored config on
failure would silently discard what the user typed, which deliverable 2 forbids.

`X-Params-Valid: 1|0` on the response so the browser knows whether to refresh panel ③ without
parsing HTML. A valid submission triggers `recompute()` over the window panel ③ is currently
showing, whose success path already re-fires the lazy benchmark — so a params change re-FETCHES
the benchmark rather than computing it inline (deliverable 4). An invalid submission leaves
panel ③ alone: nothing was persisted, so it still describes the last good config.

### Coercion lives in the form layer — the resolved Phase-2 question

`simconfig._finite()` rejects `str` on purpose and says parsing "is the form layer's job".
`params_view.coerce_number` is that layer, with three outcomes:

    ""/None    → None          the user cleared it; renders back empty, blocks as not_a_number
    "3"/" 5.0" → 3 / 5.0       int stays int, so `phases not in (1, 3)` still means what it says
    "abc"      → "abc"         RAW, so validate() reports it and the re-render shows it back

The third is what makes the error path work at all. A decimal comma (`1,5`) is deliberately NOT
parsed: it is equally a Dutch decimal separator and a thousands separator, and guessing is worse
than a field error naming the value.

Two fields are percent-typed (`roundtrip_efficiency` 90↔0.90, `roundtrip_dc_bonus` 4↔0.04); the
SoC percentages are stored as percentages already. The conversion lives in one place per
direction and the render direction is derived from the parse direction so they cannot drift.

### Validation surfacing

`ConfigIssue.field` is a dotted path; the rendered `name=` attribute is the SAME string. That
one convention is what lets an inline error find its input with no second mapping. Messages are
looked up by `ConfigIssue.code` (a stable machine id) rather than by the developer-facing
English `message`, which `ConfigIssue`'s own docstring says is free to be reworded. An issue
keyed to a field the form does not draw (e.g. `dp_soc_levels`) is surfaced at panel level rather
than dropped.

Check 12 (band overlap) warns and still persists — §6.7 nets the requests at runtime, so an
overlapping configuration is fully simulatable. The template's existing alert now reflects
reality: the success sentence when the bands do not overlap, a warning one when they do.

### check 18: the soft block

`topology.approximated` is set by a checkbox inside the warning dialog, never derived from the
selection — §2.5b makes it the record of a deliberate choice, and deriving it would also set it
for a user who never saw the dialog. It is cleared when the selection returns to the supported
3-phase inverter, so nobody carries a caveat they no longer earn. The question only arises where
the selector is SHOWN (3-phase connections): a stored `one_phase` on a 1-phase connection is
inert per `TopologyConfig` and must not pin a caveat.

The caveat is emitted by `results_view` on every result computed under it, since §2.5b requires
it PINNED to the results panel rather than shown once in the dialog.

### Gating comes from the config's own queries

`offerable_charge_policies()`, `offerable_discharge_policies()`, `battery_phases_offered`,
`cfg.economic_guard`, `cfg.pv_coupling`. No rule is re-derived in the view layer, which would be
a second place for it to drift. Without PV: P2 alone as a single labelled option (§2.3's exact
wording), D1 relabelled to "Serve house load", `pv_coupling` null, and the topology box not
rendered at all when the phase selector is also absent (§2.3: "on a 1-phase connection [it]
empties the box entirely — in that case do not render it"). Without cost simulation: the whole
Pricing box absent, not greyed, and `economic_guard` with it.

### The collapsed summary line is deliberately NOT translated

It is built at runtime from the user's own numbers and carries a literal `%`. `app/i18n.py`
installs gettext with `newstyle=True`, which %-formats the result of `_()`: a bare `%` is eaten
before a letter and RAISES before a non-ASCII character. Passing a runtime-assembled string
through `_()` is exactly the trap the Phase-4 follow-up documented. The words in it ("charge",
"discharge", "energy only") are short and it reads as a technical readout, consistent with the
panel-① summary beside it. A guard test asserts no `ISSUE_MESSAGES` entry carries a literal `%`
either; the `%(a)s` placeholders in the band-overlap alerts are STATIC msgids, which is what
newstyle exists for.

## Requirements changes

None from the user mid-task. One deliverable had to be met differently than its wording
implied — see the retention obstacle below.

## Obstacles and solutions

- **Appendix A's retention requirement cannot be met by `SimulationConfig` alone.**
  `_force_invariants` normalises the STORED `policy.economic_guard` to False (in `__post_init__`
  AND in `validate()`), so the user's raw True is destroyed the moment any config is built with
  cost simulation off — which is every load, parse and clone. That normalisation is deliberate
  and well-argued in `simconfig.py`; it is not a defect, but it means the retained value must
  live where the forcing cannot reach. Solved in the store: a `retained` block beside the four
  groups, carried forward on save and restored into `policy.economic_guard` on load when cost
  simulation is on. `save(..., guard_submitted=True)` is how the route reports that a submission
  actually drew the checkbox, which is the only way to tell "the user unticked it" from "this
  form never showed it" — an HTML checkbox is simply absent in both cases. **No domain module
  was modified.**
- **Starlette requires `python-multipart` for any form parsing**, including urlencoded. Added
  as a runtime dependency (`python-multipart>=0.0.20`). The alternative — hand-parsing the body
  — would be re-implementing a well-specified format badly.
- **A JSON body that is not a form does not raise in Starlette**; it reads as an empty form, so
  the route sees a submission with no fields and correctly inherits everything. The observable
  contract is "no 5xx, nothing changed" rather than a specific 4xx; asserting an invented 400
  for a request the framework parsed would test our plumbing, not behaviour.
- **The fuse figure was being re-padded.** `connection_capacity_kw_display` already decides its
  own precision (2 dp below 10 kW, 1 dp at or above, so both published figures come out exactly
  — 5.75 and 17.3). Formatting its output to a fixed width turned 17.3 back into 17.30 and
  contradicted appendix A. Rendered with `:g` instead.
- **A "bigger battery saves more" assertion does not hold on every dataset.** On the synthetic
  route-test seed the daytime surplus is already exported in the baseline, so a larger battery
  under P3 mostly grid-charges in cheap hours and loses more to round-trip and standby. That is
  correct output (§7.2 item 9) and is exercised properly in `test_results_view.py`. The route
  test asserts what it actually owes — that the config REACHES the run — via inequality plus
  reproducibility (returning to the first parameter set reproduces the first figure exactly),
  rather than tuning the fixture until the sign came out agreeable.
- **The first i18n fill script corrupted multiline PO entries** (it rewrote them as single lines
  and orphaned the continuation lines). Reverted and redone through Babel's own
  `read_po`/`write_po`, which keeps the canonical formatting.

## Files created

- `app/simconfig_store.py` — persistence: `load` / `save` / `to_dict` / `from_dict` / `clone` /
  `config_path`, plus the `retained` block described above.
- `app/params_view.py` — the form layer: coercion primitives, the `FIELDS` table (form name →
  dotted path → coercion), `parse_form`, `phase_topology_unsupported`, `ISSUE_MESSAGES` /
  `issue_message` / `field_messages`, `summary_line`, `params_view`.
- `app/templates/topology/phase-1.svg`, `phase-3.svg`, `phase-3x1.svg` — the three §2.5(b)
  illustrations (240×160, single `currentColor` stroke, `role="img"` + `aria-label`).
- `app/templates/topology/battery-ac-only.svg` — §2.5(a′)'s grid-only battery, shown in place of
  the PV-coupling pair when there is no PV.
- `tests/test_params_view.py` — 35 tests: coercion, percent scaling both ways, the empty and
  unparseable paths, every check-11 condition against its own field, check 12, the summary line,
  the gating rules, check 18's offered-only rule and its deliberate-choice semantics,
  persistence round-trip, absent/corrupt/forward-compatible documents, and the retention pair.
- `tests/test_params_route.py` — 15 tests through the app: valid/invalid submissions, the
  soft-block flow, **spec fixture 12** (both halves), the config driving `/results` and
  `/results/benchmark`, and the never-500 error paths.

## Files modified

- `app/main.py` — imports `params_view` / `simconfig_store`; `index()` loads the persisted config
  and renders panel ② and the setup band from it (replacing `sample_view()`'s static `cfg`), and
  threads it into `results_from`; new `POST /params`; `POST /results` and `POST /results/benchmark`
  both pass `cfg=simconfig_store.load()`. Module docstring and Routes list updated.
- `app/results_view.py` — `results_from` gains `cfg: SimulationConfig | None = None` and no
  longer constructs one internally (`None` → appendix-A defaults, so un-updated callers and
  existing tests keep their behaviour). The "parameters panel is not wired up yet" caveat is
  replaced by one naming the actual configured battery, plus the check-18 approximation caveat.
  Added `_g` / `_policy_key` defensive formatters — a config is constructible from anything, and
  an f-string `:g` on a `None` would raise on a page the user is looking at.
- `app/templates/_panel_params.html` — rewritten as a real form. Every input carries its dotted
  path as `name`; two macros (`field_messages`, `num_field`) render inline errors/warnings; the
  root is `id="panel-params"` (the swap target); a hidden `sections` field echoes which boxes
  were drawn; §2.5(a) / (a′) / (b) selectors; the check-18 dialog; the reality-reflecting
  band-overlap alert; the Pricing box and `economic_guard` absent under `simulate_cost = false`.
- `app/templates/index.html` — a delegated `submit` listener for `#params-form`: POSTs, swaps
  `#panel-params` by `outerHTML`, and on a valid submission re-runs `recompute()` over panel ③'s
  current window (which re-fires the lazy benchmark). Lives outside both swappable panels, so it
  survives every swap with no re-binding.
- `tests/test_results_view.py` — one test renamed and re-pointed: it asserted the now-removed
  "not wired up yet" caveat; it now asserts the replacement still names capacity, powers,
  efficiency and policies (the fact that must stay visible).
- `tests/test_smoke.py` — the thumbs-up test used the "Allow export" pending affordance, which is
  a real dispatch control now; re-pointed at the setup band's `simulate_cost` control, which is
  genuinely still unbuilt and lives in a region no other test mutates.
- `pyproject.toml` / `uv.lock` — `python-multipart` added.
- `app/static/app.css` — regenerated (`npm run build:css`) so Tailwind picks up the new classes.
- `app/locales/{en,nl}/LC_MESSAGES/messages.{po,mo}`, `app/locales/messages.pot` — 39 new msgids
  extracted, translated to NL, EN source catalog filled, both `.mo`s recompiled. No fuzzy
  entries, no `#:` location comments (`--no-location` on extract; `--no-fuzzy-matching` on
  update, per the Phase-4 note).

## Verification

**Test suite: 434 passed, 2 skipped** (was 384/2 — +50 new). Two pre-existing tests changed, both
because the behaviour they asserted was deliberately replaced; both listed above.

**Driven live** against a copy of the real persisted dataset (`uv run uvicorn app.main:app
--port 8093`, a throwaway data dir):

| step | observation |
|---|---|
| GET / baseline (10 kWh, 5/5 kW) | summary `10.0 kWh · 5.0/5.0 kW · 90% · charge P3 · discharge D1 · energy only`; **341 kWh** saved, 138 EFC |
| submit 20 kWh / 8 kW | `200`, `x-params-valid: 1`, summary now `20.0 kWh · 8.0/8.0 kW · …` |
| panel ③ after the change | **322 kWh** saved, EFC 138 → **83** — the figures moved |
| benchmark re-fetch | `Your policy` row reads **322 kWh**, matching the KPI — same config in both routes |
| submit `min_soc = 100` (blocks) | `200`, `x-params-valid: 0`; `value="100"` still in the input; error `battery.min_soc_pct` → "Minimum state of charge must be below the maximum."; panel header reads "needs attention"; panel ③ unchanged |
| submit `rte = 40` | error on `battery.roundtrip_efficiency` → "Round-trip efficiency must be above 50 and at most 100." |
| submit `max_discharge = 0` | error on `battery.max_discharge_kw` → "Must be greater than zero." |
| submit `max_charge = "eight"` | `value="eight"` preserved, error on that field, no crash |
| overlapping bands (B 0.500, C 0.100) | `x-params-valid: 1` — saved — with the overlap alert shown |
| restart the process, GET / | summary reads `20.0 kWh · 8.0/8.0 kW · …`; inputs restored (20.0, 8.0, 0.040, 25); charge P3, DC-hybrid and 1-phase all checked correctly |
| switch to 3-phase | phase selector appears; fuse figure reads **17.3 kW** (appendix A's published figure, not 17.25 or 17.2) |
| select `one_phase` on 3-phase | soft-block dialog shown, `x-params-valid: 1` (soft, not hard); `approximated` still false; no caveat on panel ③ |
| tick "Continue with a 3-phase approximation" | `approximated = true`; saving **312 kWh** — **identical** to the 3-phase case; the approximation caveat now pinned to panel ③ |
| `has_pv = false` | P1/P3 absent, P2 a single labelled option with the no-surplus note, topology box absent (1-phase), D1 relabelled "Serve house load" |
| corrupt the stored file | GET / renders `200` with appendix-A defaults |
| NL locale | panel and soft-block dialog render translated |

Screenshots of the expanded panel and of the §2.5(b) selector with the soft block were captured
and reviewed; both match the wireframes.

## Current status

Complete. All six deliverables met, spec fixture 12 asserted on both halves (the flag is set AND
the run is numerically identical), and the whole suite green at 434/2.

### Notes and open items

- **The retention mechanism is the part I would most want a second reading of.** It works and is
  tested in both directions (retained across a toggle; genuinely cleared when unticked under cost
  simulation), but it puts one field's authoritative value in the persistence document rather
  than on the config object, which is a split worth being deliberate about before the other
  twelve cost-only parameters land. The alternative — giving `SimulationConfig` a raw-value
  companion field that `_force_invariants` does not touch — is cleaner but modifies a domain
  module this phase was told not to touch.
- The collapsed summary line reads `charge P3` even with `has_pv = false`, where P3 degenerates
  to P2. That is the stored policy, and §6.6 is explicit that it should be left alone (rewriting
  it would discard the user's answer if they turn PV back on). It may still read oddly next to a
  panel that only offers P2; worth a decision.
- `simulate_cost` is still pending in the setup band, so the Pricing box, the `economic_guard`
  control and run E remain unreachable by design. The summary line's cost-on clause renders
  `cost` rather than a contract name, since §6.5's contract model does not exist yet.
- The setup band's radios still do not POST anywhere — `has_pv` / `simulate_cost` are read from
  the persisted config but not yet editable through the UI. Out of scope here (the band is §2.1,
  not panel ②), but it is now the only thing standing between the config and a fully editable
  parameter set.
- The pre-existing shared-Jinja-env locale race applies to `POST /params` exactly as it does to
  the other render paths; not worsened, still deferred.
