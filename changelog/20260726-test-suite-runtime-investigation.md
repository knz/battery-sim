# Test suite runtime investigation

## Task specification

Investigate why running the full test suite takes so long. Investigation only — no code
changes were requested or made. Carried out in a git worktree (`.claude/worktrees/test-timing`)
off `feat/pending-affordance-backend` (`0cbbcfe`).

## Method

- `uv run pytest --durations=0 --durations-min=0` to capture every phase of every test
  (2377 entries = 3 phases x ~792 tests), aggregated per file with awk.
- Direct measurement of the two sweep generators in isolation, to separate unique work from
  repeated work.
- A mutation/purity check on `_bench` to establish whether the repeated work is safely cacheable.

## Findings

Wall clock: **51.6s**, of which 48.0s is attributable to test phases (43.0s call, 4.6s setup,
0.3s teardown).

The cost is concentrated, not diffuse:

| file | time | share |
|---|---|---|
| `tests/test_benchmark.py` | 35.8s | ~75% |
| `tests/test_smoke.py` | 5.5s | ~11% |
| everything else (20 files) | ~6.7s | ~14% |

Within `test_benchmark.py`, six tests account for ~34s. All six iterate one of two
perfect-foresight DP sweeps.

**Root cause: the two sweep generators are recomputed once per test that consumes them.**

`_fixture_6_configs()` (162 configs, 52.4 ms/config = 8.48s per full pass) is a plain generator
with no caching, consumed at three call sites (lines 156, 220, 244). `_fixture_6_cost_configs()`
(144 configs, 26.6 ms/config = 3.83s per pass) is consumed at two (lines 1119, 1358).

Measured directly:

- energy sweep: 8.48s x 3 call sites = 25.45s
- cost sweep: 3.83s x 2 call sites = 7.66s
- total 33.11s, of which **unique work is 12.31s** — roughly **21s is repeated work**

These per-pass figures match the observed per-test durations closely (8.45/8.49/8.51s for the
three energy tests; 3.80/3.81s for the two cost ones), which supports the attribution.

The repeated work is redundant rather than merely similar: `_bench` was verified not to mutate
its frame or config, and to return an identical result when re-run on the same inputs. The three
energy tests assert three different properties (the bound, the capture ratio, unconstrained >=
inheriting) over the *same* computed benchmark objects.

Note this is a known, deliberate cost, not an oversight: the module docstring references "the
runtime budget it works to", and the cost half already runs at reduced DP grids
(`_FAST_DP = dp_soc_levels=41, dp_action_levels=41`) for exactly this reason. The sweeps are
genuinely doing real work — 306 DP solves of unique work is the floor at the current grids.

## Incidental observation (not part of the ask)

7 tests fail on this branch, all i18n/Dutch-rendering related — `test_i18n.py` (1) and
`test_no_english_leakage.py` (6), the latter from `/results` returning 409. Not investigated;
unrelated to runtime. Flagged only because it showed up in the run.

## Options (not decided)

Ordered roughly by effort, all preserving current assertions:

1. **Cache the sweeps** — memoise into a list at module scope, or a session-scoped fixture.
   Recovers ~21s of the ~52s for a small change. The purity check above suggests this is sound,
   but it does make the tests share objects, so a future test that mutated a result would couple
   them.
2. **Merge the co-iterating tests** — one pass asserting all three properties. Same saving,
   no shared mutable state, but loses one-property-per-test granularity, which this file's
   docstring argues for deliberately ("Every claim gets its own fixture").
3. **Apply `_FAST_DP` grids to the energy half too** — the cost half already does. Would need
   re-measuring `_DP_SLACK_KWH`, since the docstring states that constant is a measured figure
   at the current grids. Higher risk; changes what is being tested.
4. **Parallelise with `pytest-xdist`** — cuts wall clock without touching test semantics, but
   adds a dev dependency and hides rather than removes the redundant work.

Option 1 looks like the best effort/return trade-off, but 1 and 2 are alternatives to each other
and the choice depends on how much the per-property test granularity is worth. Left open.

## Requirements change (mid-conversation)

After the investigation the user asked for option 1, caching, to be implemented. On the design
question of how defensively to share the cached results, the user chose the plain session cache
with shared objects over the copy-on-handout variant.

## Implementation

A correction to the investigation's framing, found while implementing: caching the *generators*
would have saved nothing. Building the frame/config pairs costs ~0.01s for either sweep; the
entire expense is the DP inside `_bench` / `_cost_bench`. The cache therefore memoises the
**computed benchmark results**, not the configs.

Two module-level caches added to `tests/test_benchmark.py`:

- `_fixture_6_benched()` — the 162-config energy sweep with `_bench` already applied, yielding
  `(frame, cfg, bench, policy_drift)`. Consumed by the three tests at the former lines 156/220/244.
- `_fixture_6_cost_benched()` — the 144-config euro sweep with `_cost_bench` applied, yielding
  `(frame, cfg, bench)`. Consumed by the two tests at the former lines 1119/1358.

The generators themselves are untouched and still express the sweep; the caches wrap them.

### Why sharing results between tests is safe here

Established by check rather than assumed:

- `run_all` / `energy_benchmark` are pure over frame and config — neither is mutated by a run,
  and a re-run returns an equal block (verified before the change).
- `EnergyBenchmark` and `CostBenchmark` are both `@dataclass(frozen=True)`; attempting to assign
  to a field raises `FrozenInstanceError` (verified after). A consumer cannot corrupt what the
  next test reads, which is what made the copy-on-handout variant unnecessary.

Each test keeps its own single property — this is a cache, not a merge, so the
one-claim-per-test structure the module docstring argues for is preserved.

## Verification

- Full suite: **51.6s → 28.8s**, outcome unchanged at `7 failed, 784 passed, 2 skipped` — the
  same 7 pre-existing i18n failures as the baseline.
- `test_benchmark.py` alone: 35.8s → 15.4s, 45 passed.
- Each of the five sweep tests passes in isolation at full sweep cost, so none depends on
  another having warmed the cache.
- Sweep sizes still 162 and 144, so the `checked == 162` style guards would still catch a cache
  that silently dropped configurations.

## Files modified

- `tests/test_benchmark.py` — added the two result caches; repointed five tests at them
- `changelog/20260726-test-suite-runtime-investigation.md` (this file, created)

No application source was modified.

## Current status

Caching implemented and verified. Suite runtime roughly halved with no change in test outcomes.

Remaining, not addressed: the 7 pre-existing i18n / Dutch-rendering failures (`/results`
returning 409) are untouched and still failing — they predate this work. The other options from
the list above (fast DP grids on the energy half, xdist) remain open but are now lower-value,
since the redundant work they would have overlapped with is gone. `test_smoke.py` at 5.5s is
the next largest single item.
