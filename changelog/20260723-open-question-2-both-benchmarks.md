# Open question §8.2 — compute both export baselines side by side

## Task specification

**Original user prompts (verbatim):**

1. "Let's work on the open questions. Can you tell me about the 2nd question"
2. "Maybe offer/compute both baselines side by side (and we'll observe the results as
   answer to X10)"
3. "Please let's avoid magic constants in the code, ensure in arch doc that constants are
   named"

Scope: change the specification so the perfect-foresight benchmark computes **both** the
export-inheriting and the export-unconstrained bound, rather than the spec picking one.
The choice §8.2 asks the product owner to make is deferred to observed data from
[experiment X10](../specs/19-prototype-experiments.md), which the side-by-side output then
supplies as a by-product of ordinary runs.

## Background — what §8.2 asked

The perfect-foresight DP (§6.12) obeys the household's physical limits but deliberately
ignores the user's price bands, so the capture ratio measures policy quality.
`allow_grid_export` sat ambiguously between the two: it is a physical/contractual
permission, it defaults **off**, and §8.2 asked whether the DP should inherit it.

- *Inherit* → capture ratio compares policy decision quality alone.
- *Do not inherit* → capture ratio also absorbs the cost of the user's export setting, and
  stops being comparable across users with different settings.

§8.2 recommended inheriting plus offering the unconstrained bound as a secondary figure,
but rested that recommendation on an asserted-not-measured claim that the two "differ
materially". X10 exists to measure it.

## High-level decisions

Decisions taken with the user in this session (all four via explicit selection):

1. **Second DP only when export is off.** When `allow_grid_export` is true the two bounds
   coincide by construction, so the second pass is skipped and the unconstrained fields
   report `null`. Avoids paying seconds of DP for a provably identical number.
   Rejected: always running the full cross (energy×{inherit,unconstrained} plus
   cost×{...}), which costs up to four DP passes for no information in the export-on case.

2. **JSON: sibling nullable fields, not nested variant blocks.** Add
   `perfect_foresight_*_unconstrained` and `capture_ratio_unconstrained` alongside the
   existing fields inside each benchmark block. The existing field names keep their current
   meaning (the inheriting bound), so §6.12, the wireframes and fixture 6 need no renaming.
   Rejected: restructuring each block into `{inherited, unconstrained}`, which is more
   symmetric but renames fields already referenced across four spec files.
   Rejected: echoing identical values when export is on, which removes the reader's signal
   that no second DP ran.

3. **UI: secondary line shown only when the two bounds differ, with a provisional
   threshold that is flagged as a guess.** A numeric threshold is specified so the frontend
   is implementable now, and explicitly marked as untested and to be revisited from X10's
   data. Rejected: leaving the threshold unspecified (panel carries the extra line
   indefinitely meanwhile); rejected: keying purely on `allow_grid_export` being off, which
   is deterministic but shows the line even when the divergence is negligible.

4. **§8.2 stays open, with its position updated.** Computing both does not answer which
   bound the capture ratio should be *labelled with* — it defers that to data. The decision
   still owed shrinks from "which bound" to "which bound is primary in the panel, and does
   the secondary figure earn its place". Rejected: closing §8.2 outright.

### Requirements change mid-conversation — named constants (prompt 3)

After the §8.2 plan was presented, the user added a general requirement: no magic constants
in the code, and the architecture document must state that constants are named. This
broadens the task beyond §8.2. Two effects:

- The divergence threshold introduced for §8.2 must not be a literal in a comparison. It
  becomes `benchmark_divergence_display_threshold`, a named `config.toml` entry listed in
  appendix A — user-facing, because it changes what the panel shows and X10 is expected to
  revise it.
- `specs/08-architecture.md` gains a new **§5.6 Named constants**. The doc currently says
  nothing about constants at all: §5.4 covers `config.toml` and points at appendix A, but
  is silent on literals that are not user-facing defaults, which is why a threshold like
  this had no obvious home.

§5.6 draws a three-way distinction:

1. **User-facing defaults** → `config.toml`, listed in appendix A. Already the practice;
   §5.6 states it explicitly.
2. **Internal tunables** — no user meaning, but someone may need to change them, and they
   appear in the spec's own pseudocode (DP `n_soc`/`n_actions`, `EPS`, epoch-detection and
   data-quality thresholds). **Decision: module-level named constants in code, with an
   origin comment — not `config.toml`.** Keeps `config.toml` and appendix A a user-facing
   surface rather than growing entries no user should touch.
3. **Genuine literals** — `0`, `1`, unit conversions such as 3600. Explicitly *not* named,
   so the rule does not degenerate into `ONE = 1`.

**Decision: state the rule and sweep now.** The existing pseudocode literals are fixed in
the same pass, so the spec obeys its own new rule rather than visibly violating it.
Rejected: stating the rule only and deferring the sweep (leaves the doc inconsistent);
rejected: sweeping only §6.12 (leaves the same inconsistency, just smaller).

An inventory agent was run over `specs/` to enumerate every unnamed literal in pseudocode
and stated thresholds, classified into the three categories above, to scope the sweep.

## Rationale

The user's framing — compute both, observe the answer — turns a decision that currently
rests on an unmeasured magnitude into one that ordinary runs will settle. It also converts
X10 from an experiment someone must set up into a report someone must read: the two bounds
land in every export-off result object, so the euro/kWh delta accumulates across whatever
households run the simulator.

The cost is bounded: one extra DP pass (a few seconds, §6.12 complexity ≈ 36M vectorised
ops) in the export-off case only, and two nullable fields per benchmark block.

## Files to modify

- `specs/12-metrics-and-benchmarks.md` — §6.12: state that both export variants are
  computed when export is off, and that the second pass is skipped when it is on.
- `specs/07-internal-representation.md` — §4.5: add the sibling fields to
  `benchmarks.energy` / `benchmarks.cost`, with the null rule; confirm the additive-layer
  guarantee still holds.
- `specs/02-ux-wireframes.md` — §2.4: benchmark boxes gain a conditional secondary line.
- `specs/17-open-questions.md` — §8.2: rewrite to record the new position.
- `specs/19-prototype-experiments.md` — X10: rewrite the method, since the data now arrives
  from ordinary runs rather than from a bespoke A/B.
- `specs/16-validation-harness.md` — fixture 6: the bound invariant must hold for the
  unconstrained figures too, and `unconstrained ≥ inherited` is a new invariant.

## Implementation progress

### Step 1 — mechanical duplication fixes (done)

Where the spec restated a digit for a parameter appendix A already names, the pseudocode
now references the parameter:

- `12-metrics-and-benchmarks.md` — `perfect_foresight` now binds `n_soc`/`n_actions` from
  `cfg.dp_soc_levels`/`cfg.dp_action_levels` in the body (not as default-arg expressions,
  which do not evaluate at definition time); complexity note references the parameter names.
- `14-diagnostics.md` — `detect_time_offset` takes `max_lag_intervals` (fed from
  `cfg.time_offset_max_lag`). Fixed a pre-existing latent bug in the same edit: the body
  used an undefined `max_lag` while the signature declared `max_lag_intervals`.
- `04-state-machine.md` — debounce table row and `schedule_debounce` call reference
  `cfg.debounce_ms`.
- `13-configuration-epochs.md` — `changepoints` call references `cfg.epoch_min_segment_days`.

Left as-is (display, not duplication): `03-topology-selector.md:48` (prose showing the
`roundtrip_dc_bonus` default value), `10-pricing.md:155` (preset table showing α/β values).

### detect_dal_register window — investigated, verdict (B)

A sub-agent investigated whether the hardcoded `hour >= 23 | hour < 7` in
`detect_dal_register` (`09-ingest-algorithms.md:279`) is a deliberate fixed reference window
or a latent inconsistency. Verdict: **latent inconsistency**, change to read
`cfg.dal_start_hour`/`cfg.dal_end_hour` like `tariff_zone`. Decisive evidence:
`18-dutch-electricity-background.md` states the register-identification rule and immediately
follows with "Do not hard-code it"; the detector's own docstring describes the window
agnostically ("the hours the dal tariff applies"). The 21:00-start operator areas degrade
the detector (extra dal hours scored as normaal, pushing toward the `UNCERTAIN` threshold or
a wrong answer). The detector also omits the weekend term that `tariff_zone` applies.

The weekend term was verified against the Dutch market before folding it in: on dubbeltarief
meters the low tariff applies weekday 23:00–07:00 (21:00 in Noord-Brabant, Limburg, parts of
Zuid-Holland), **all weekend, and nationally recognised public holidays** (sources: Budget
Thuis, Essent). So `tariff_zone`'s existing `dayofweek >= 5` term is correct and the detector
omitting it was the anomaly.

**Done, with user sign-off.** `detect_dal_register` now takes `cfg` and uses the same mask
as `tariff_zone`: `cfg.dal_start_hour`/`cfg.dal_end_hour` plus `dayofweek >= 5`. Added a
docstring explaining why the window is configured rather than fixed. No code caller needed
updating (only a prose reference in `16-validation-harness.md`).

**Holidays gap surfaced (pre-existing, not fixed).** Both `tariff_zone` and the detector
model weekday-hours + weekends but not public holidays, which are also dal (≈ 8–10 days/yr,
priced as `NORMAAL`). Recorded as a note under `tariff_zone` and flagged for a watch item,
since it is pricing correctness beyond this task's scope.

### Step 2 — §8.2 both export baselines (done)

Six edits:

- `12-metrics-and-benchmarks.md` §6.12 — "Both export baselines are computed, not one":
  inheriting (primary) and unconstrained bounds, second DP skipped when export is on
  (identity, not approximation). New invariant `unconstrained ≥ inheriting`, equality-or-null
  when export is on.
- `07-internal-representation.md` §4.5 — sibling nullable fields
  `perfect_foresight_*_unconstrained` + `capture_ratio_unconstrained` in each block; note
  that these are governed by `allow_grid_export`, orthogonal to the `simulate_cost`
  additive-layer invariant.
- `02-ux-wireframes.md` §2.4 — conditional "…if export allowed" row in both benchmark boxes,
  gated on non-null fields AND capture-ratio gap > `benchmark_divergence_display_threshold`.
- `appendix-a-defaults.md` — new `benchmark_divergence_display_threshold = 0.02`, flagged
  provisional pending X10.
- `17-open-questions.md` §8.2 — rewritten: spec computes both, decision narrows to
  presentation (primary-figure label, threshold value), both answerable from accumulated data.
- `19-prototype-experiments.md` X10 — rewritten as a reading off ordinary export-off runs
  rather than a bespoke A/B; fixture 16 validates the second DP.
- `16-validation-harness.md` fixture 6 — bound invariant extended to the unconstrained
  figures plus the export-on null case.

### New open question §8.21 — Dutch public-holiday list source

Added at user request during step 2. On dubbeltarief meters the dal tariff also applies on
nationally recognised public holidays, which `tariff_zone`/`detect_dal_register` do not
model (≈ 8–10 days/yr priced as `NORMAAL`). Unlike a modelling choice this needs an actual
list of dates that changes yearly (moveable feasts from the Easter computus). The question
records three source/update models — static dated table, compute-from-algorithm (flagged as
the likely preference for an offline-by-default tool), or external fetch — and notes the
correction's euro impact is unmeasured and worth an experiment before the source decision is
urgent. The prior watch item renumbered §8.21 → §8.22; its one internal cross-reference (in
§8.1) updated.

### Step 3 — §5.6 named-constants convention + sweep (done)

Two user decisions taken before the sweep: the 90-day floor becomes **two** independent
constants (annualisation vs tiered-TLK), both defaulting to 90; **all** category-(a)
literals promoted into appendix A.

- `08-architecture.md` — new **§5.6 Named constants**: three-category convention
  (user-facing→config.toml+appendix A; internal tunable→module constant with origin comment;
  genuine literal→leave, explicitly not `ONE = 1`). Includes a table pinning the four EPS
  replacement tolerances.
- **`EPS` split** (done directly, not delegated): every bare undefined `EPS` replaced by one
  of `DIV_GUARD_EPS` (1e-9), `SOC_COMPARE_EPS_KWH` (1e-6), `STD_GUARD_EPS` (1e-9),
  `FLAT_SPAN_EPS_KWH` (1e-6), by role. `DIV_GUARD_EPS`/`STD_GUARD_EPS` share a value but not
  a meaning, kept separate deliberately.
- **Category-(a) sweep** (delegated to a context-inheriting fork, output verified): 18 named
  config defaults added to appendix A — `min_annualisation_days`, `min_tlk_tiering_days`
  (the two 90-day constants), `gap_factor`, `pv_yield_max_kwh_per_kwp`, `load_max_kwh_per_year`,
  `rte_min` (upper 1.0 left as physics literal), `pv_capacity_min_rel_step`,
  `overlap_warn_pct`/`overlap_prominent_pct`, `residual_mean_warn_pct`/`residual_diurnal_warn_pct`,
  `tariff_zone_mismatch_pct`, `ha_fine_window_days`/`ha_chunk_days`, `sse_poll_fallback_ms`,
  `params_persist_debounce_ms`/`result_cache_runs`.
- **Category-(b) sweep**: module-level constants with origin comments in the files that use
  them — epoch heuristics (13, ~14 constants incl. `FLAT_TOP_NIGHT_FRACTION` flagged
  "no stated derivation, see X11"), diagnostics (14: `FINE_GRID_S`/`COARSE_GRID_S`,
  `BIAS_FLOOR_KWH`/`BIAS_FLOOR_EUR` kept as two magnitudes, `TIME_OFFSET_CONFIDENCE_MIN`),
  `CANCEL_CHECK_INTERVAL`, `CLOSURE_TOL`, `DAL_SHARE_GAP_MIN`, `RESET_TOLERANCE_KWH`/`RESET_FLOOR_KWH`,
  `SOC_DRIFT_WARN_FRAC`/`_EUR`.
- **Left as category (c)** with reasons: `rte_min`'s 1.0 upper bound (physics), HA's own
  ~10-day retention (external fact, not our config), the `90 days` inside the UI mockup box
  (display copy showing the real number), unit conversions and `dayofweek >= 5`.

Verification after the sweep: no bare `EPS` remains; the two surviving `90` mentions are
intentional (the prose naming both constants, and UI display copy); every category-(a) name
is present in appendix A and referenced; sampled category-(b) constants are defined-then-used
within their file; the §8.2 benchmark work and dal-window edits are intact.

## Current status

All three steps complete. Changes are working-tree edits across 10 spec files plus this
changelog; nothing committed. Awaiting user review.

## Open items

- The provisional divergence threshold (0.02) is a guess, to be revisited once X10 data
  exists.
- Whether the *primary* capture ratio should remain the inheriting one is still §8.2's
  question; this change does not settle it.
- §8.21: the public-holiday list source is undecided; the euro impact of the missing
  holidays is unmeasured.
- Step 3 pending: §5.6 + naming sweep, including splitting `EPS` into role-specific
  tolerances.
