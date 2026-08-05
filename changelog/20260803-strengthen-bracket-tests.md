# Step 8 — strengthen the price-bracket tests (M42/M43, fixture 10, step-7 coverage)

## Task Specification

Test-only work at `3b173c8`. No production behaviour may change; `app/` must be byte-identical to
HEAD at the end. Do not commit.

- **Task A (primary).** Mutants M42/M43 — dropping `saved_central` from `_price_bracket`'s `min(...)`
  and from its `max(...)` respectively — reportedly SURVIVE the suite, contradicting the step-3
  changelog claim that `test_the_band_still_contains_the_headline_when_the_two_extremes_do_not` is
  the test that dies. Reproduce, diagnose, fix the test so both mutants die, verify by mutation.
- **Task B (secondary).** `specs/16-validation-harness.md` fixture 10 names the ordering invariant
  `saved_low ≤ saved_central ≤ saved_high`; no test carries the fixture number. Follow whatever
  convention fixtures 1–9 / 11+ already use; invent no machinery.
- **Task C.** Check whether the behaviours step 7 newly documented are covered: the four `return None`
  guards in `_price_bracket` (in particular `priced == 0`), and the display suppression at exactly
  `width_eur == 0.5`. Add tests only where genuinely uncovered, each verified by mutation.

Standing hazard named in the prompt: the **vacuous-fixture trap** — bracket width scales with the
flow difference in the spread hours, not with the price spread alone.

## Task A

### Reproduced, exactly as reported

Each mutant applied by hand and run against the FULL suite, one at a time:

| Mutant | Result |
| --- | --- |
| M42 — `saved_low = min(saved_optimistic, saved_pessimistic)` | **SURVIVED**, 1269 passed / 2 skipped |
| M43 — `saved_high = max(saved_optimistic, saved_pessimistic)` | **SURVIVED**, 1269 passed / 2 skipped |

### Diagnosis — the audit's hypothesis is confirmed, but its stated mechanism is only half of it

The crossing test's premise assertion built its two "extremes" from the **window-uniform** corners
(`lo.p_import` over the whole window against `hi.p_export_net`, and the reverse). That is the
envelope shape the code had BEFORE step 3's review fix. The shipped code chooses the extreme **per
interval** on the sign of that interval's own flow difference. Measured on the pinned fixture:

| Envelope | Extremes | Central | Crosses? |
| --- | --- | --- | --- |
| window-uniform (what the premise computed) | −0.597, −0.460 | −0.380 | yes |
| per-interval (what the code does) | −1.470, +0.414 | −0.380 | **no** |

So the premise passed on an envelope nothing evaluates, and the conclusion
(`saved_low <= saved_central <= saved_high`) held trivially because the per-interval band was wide
enough to contain the central figure with room to spare. Neither mutant could be seen.

**The further finding, which the audit did not state and which matters for constructing a
replacement.** The per-interval pick is the *exact* extremum of a separable sum, so under the
four-corner argument alone the central figure can no longer escape it at all — that argument appears
to be inapplicable now, not merely unexercised. The separability argument is a mathematical claim
about all inputs, checked here on two fixtures and one config ablation rather than proved, so it is
stated as the working explanation and not as settled. The remaining source of a crossing found is
the one term that is not separable: §6.5's feed-in floor under `FeedinFloorMode.MONTHLY`
(appendix A's default), a
window-level `max(0, −Σ export·c)`. That clamp binds only where compensation is negative, which at
appendix-A tariffs is spot below about −0.02 EUR/kWh. Any replacement fixture therefore needs mostly
negative prices, which is why the old "grid-charges in some intervals and cuts import in others"
recipe (still in the spec — see Out of scope) no longer produces one.

### The other half of the defect: one fixture can only kill one mutant

Where central sits BELOW both extremes, `max(opt, pess, central)` and `max(opt, pess)` agree, so
that fixture leaves the `max` call unpinned — and vice versa. A single crossing window can never
kill both mutants. This is why the fix is a parametrised pair, not one replacement fixture.

Search (scratchpad, not the repo): 12 000 windows over spot in [−0.30, 0.10] with the MONTHLY floor
produced only LOW-side crossings. Varying the config as well (floor mode, battery size, price band)
found HIGH-side ones at roughly 1 in 1 400 windows. Both fixtures pinned as literals.

| Fixture | Extremes | Central | Margin | Width |
| --- | --- | --- | --- | --- |
| low-side (`default_rng(5)`, spot in [−0.20, 0.06]) | 0.3191, 0.3466 | 0.2827 | €0.036 below | €0.032 |
| high-side (`default_rng(224)`, spot in [−0.268, 0.196]) | −0.1131, 0.2410 | 0.4921 | €0.251 above | €0.303 |

### What changed in `tests/test_results_view.py`

- `_CROSS_*` replaced by `_CROSS_LOW_*` / `_CROSS_HIGH_*`; `_crossing_dataset(side)` takes a side.
- New `_shipped_extremes(ds, cfg)` re-derives the **per-interval** envelope — the pair
  `_price_bracket` actually sorts. The premise is computed from this and nothing else; computing
  anything else is precisely how the test came to assert nothing.
- The test is parametrised `["low", "high"]`. The premise is asserted **per side** (`central < lo_e`
  / `central > hi_e`) rather than as a side-agnostic "outside the pair": a low-side fixture that
  drifted into crossing high would satisfy a side-agnostic premise while leaving the `min`
  unpinned. The containment is asserted as two separate bounds so a failure names which end lost
  `saved_central`, plus `saved_low == central` (low) / `saved_high == central` (high).
- Not done: no monkeypatching of the envelope, no weakening. Both fixtures go through the real
  `results_from`.

### Mutation evidence

| Mutant | `[low]` | `[high]` |
| --- | --- | --- |
| M42 (`min` loses `saved_central`) | **FAILED** — `assert 0.31909538150925654 <= 0.2827064822334473` | passed |
| M43 (`max` loses `saved_central`) | passed | **FAILED** — `assert 0.492142984116279 <= 0.24101113467789048` |
| unmutated | passed | passed |

Both mutants now die. Each parameter is load-bearing; neither is redundant.

## Task B

**Convention found, not invented.** `tests/test_benchmark.py`, `test_metrics.py` and
`test_simulate.py` all reference fixtures by number in a docstring first line or a section-header
comment — `"""§6.14 fixture 6, over 162 configurations…"""`, `"""Fixture 16's no-PV arbitrage
run…"""`, `# ── Fixture 3: conservation ──`. No registry, no marker, no ID parameter anywhere.

Followed it, in two places, since fixture 10 has two halves:

- `test_the_three_evaluations_are_ordered_low_central_high` — the plain invariant on the ordinary
  fixture. Docstring now opens `"""§6.16 fixture 10 on the ordinary fixture: …"""`, notes that the
  width being the half-difference and non-negative is the rest of what fixture 10 names, and says
  explicitly that this test passes on either implementation and does not substitute for the strict
  case.
- `test_the_band_still_contains_the_headline_when_the_two_extremes_do_not` — `"""§6.16 fixture 10,
  in its STRICT case — the ordering is not free."""`

No machinery added.

## Task C

Every guard and the display boundary were checked by mutation rather than by reading.

| Behaviour | Mutant | Result |
| --- | --- | --- |
| `simulate_cost` guard | `if False:` | **SURVIVED — equivalent.** Dead code: the call site at `results_view.py:1598` is already inside `if cfg.simulate_cost:`. Recorded by step 3; re-confirmed. No test possible. |
| `supplier_settlement` guard (D10) | `if False:` | KILLED, 3 tests |
| `priced == 0` guard | guard deleted | **SURVIVED — provably equivalent.** `spread` NaN implies `spread > 0` is False, so `priced == 0` implies `bracketed == 0` and the next guard catches every input the first one would. There is no input distinguishing them. Recorded by step 3; the step-7 spec text is still right that it is a separate guard with a separate *reason*, and the reason (the `nanmax` warning it avoids) is real — it is the OUTCOME that is unreachable. No test added. |
| `bracketed == 0` guard | `if False:` | KILLED, 3 tests |
| display gate `> WATERFALL_DISPLAY_EPS_EUR` | `>=` | **SURVIVED — a genuine gap.** Fixed below. |

**The one gap: the display boundary at exactly €0.50.** The code comment at
`results_view.py:1910` deliberately explains why the comparison is `>` and not `>=` (half-to-even
rounding prints "€ 0" at 0.5), and nothing asserted it. Added
`test_a_width_of_exactly_the_display_threshold_is_suppressed_too`.

*Why it is patched rather than driven from a fixture.* This was first recorded here as "the
boundary value is not reachable by construction", citing a bisection whose neighbouring widths
measured 0.49999999999999956 and 0.5000000000000013. That was wrong: the bisection scaled prices
about the window's grand mean, which barely moves `width_eur`. Scaling each quarter's deviation
from **its own hour's** mean — the axis `spot_max - spot_min` actually measures — reaches exactly
0.5 at a scale of 0.2035372163776674, through the unpatched `results_from`, on a well-formed window
(24 of 24 intervals bracketed, sign-alternating `d_imp`). Verified independently.

The reason to patch is therefore not unreachability but fragility. That landing holds over a basin
of roughly 21 ULPs of the scale, with immediate neighbours 0.4999999999999991 and
0.5000000000000009 — a relative width near 3e-15. It depends on the summation order inside
`compute_costs` and `price_curves`, so there is no evidence it survives a numpy version bump, a
different BLAS or SIMD path, or another platform. Measured on Python 3.12.3 / numpy 2.5.1 /
x86_64 Linux. Pinning a boundary test to a value that fragile would plant a cross-platform flake,
so the width is supplied directly instead. The seam
used (`monkeypatch.setattr(rv, "_price_bracket", …)`) is the one already used for `_share_pct` in
`test_a_share_too_small_for_a_whole_percent_is_not_printed_as_zero`, and the assertion is about the
DISPLAY decision, not about the number. The ULP above the threshold is asserted to emit, so a gate
that suppressed everything would not pass either.

Mutation evidence: with the gate at `>=`, the test FAILS on
`assert _uncertainty_caveat(at) is None` (the caveat text is emitted). Unmutated, it passes.

## Files Modified

- `tests/test_results_view.py` — the two crossing fixtures and `_shipped_extremes`; the crossing
  test parametrised by side; two fixture-10 docstring references; one new boundary test.
- `changelog/20260803-strengthen-bracket-tests.md` — this file.
- Nothing under `app/`, `specs/` or the locale catalogs. Verified with `git diff --stat app/`
  (empty) after every mutation round.

## Obstacles and Solutions

- *All strict crossings found under the default config were LOW-side.* Widened the search over the
  config (floor mode, battery size, price band) as well as over the data; HIGH-side crossings exist
  at roughly 1 in 1 400 windows.
- *The vacuous-fixture trap, avoided by construction rather than by luck.* The crossing test asserts
  the view-model directly, not the caveat, so the €0.50 display gate does not apply to it — but the
  premise assertion is what makes it non-vacuous, and it is now computed from the shipped envelope.
- *The `>=` boundary is not reachable through a real fixture.* Bisected to confirm before patching,
  and recorded the two neighbouring float values.

## Current Status

Done. Suite 1271 passed, 2 skipped (1269 before: +1 from parametrising the crossing test, +1 new
boundary test). `app/` byte-identical to HEAD.

## Out of scope, worth filing

- **`specs/16-validation-harness.md` fixture 10's construction advice is stale.** It says "Construct
  the strict case on a window that grid-charges in some intervals and cuts import in others". That
  recipe describes the OLD window-uniform envelope; under the shipped per-interval envelope such a
  window does not cross (the pinned fixture was exactly that shape and stopped crossing). The strict
  case now needs the §6.5 feed-in floor to bind, i.e. mostly negative spot. The "witnessed roughly
  once in three hundred random windows" figure is also from the old envelope. Not changed — this is
  test work, and it is a spec edit.
- **The step-3 changelog's claim that the crossing test "is the only test that fails when
  `saved_central` leaves the sort" was false at the time of writing and is now doubly so** (it takes
  two fixtures, one per call). Left as recorded history; this entry corrects it.
- **The `simulate_cost` guard in `_price_bracket` is dead code.** Confirmed again. Harmless, but it
  is the kind of defensive guard whose deadness a reader has to re-derive; a comment saying so, or
  its removal, would both be defensible. Not touched — production change.
