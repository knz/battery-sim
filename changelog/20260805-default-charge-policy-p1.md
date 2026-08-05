# 2026-08-05 — Default charge/discharge policies to P1 and D1

## Task specification

Make the shipped defaults for the charge and discharge policies **P1** and **D1**.

## Findings before changing anything

- `PolicyConfig` (`app/domain/simconfig.py:640-641`) currently defaults to
  `charge_policy = P3`, `discharge_policy = D1`.
- So **only `charge_policy` changes** (P3 → P1); `discharge_policy` is already D1.
- These two defaults are not from appendix A. The docstring and
  `tests/test_simconfig.py`'s `_WIREFRAME_DEFAULTS` both source them to the §2.3
  wireframe, which preselects P3 (`docs/specs/02-ux-wireframes.md:797`).

## Decisions

- Change the dataclass default only. Every other `P3` occurrence in `app/` and
  `tests/` is an explicit construction or an enumeration of all three policies,
  not a restatement of the default, so none of those need to follow.
- Update the two places that *assert* or *describe* the default:
  - `app/domain/simconfig.py` docstring ("Defaults P3 and D1 …")
  - `tests/test_simconfig.py:124` (`_WIREFRAME_DEFAULTS`)
- Flag, but do not unilaterally rewrite, the spec divergence: §2.3's wireframe
  shows P3 preselected. Left to the user to decide whether the spec follows the
  code here.

## Requirements changes

- User approved the plan and additionally asked that the §2.3 spec wireframe be updated
  to match, rather than left diverging. Done.

## Obstacles and solutions

Changing the default broke 14 tests beyond the three that assert the default directly.
All had the same root cause: their fixtures built a bare `SimulationConfig()` and relied
on P3 grid-charging inside the band to produce the effect under test (a price spread on
the bill, a negative saving, SoC drift, a floored self-sufficiency). Under P1 the battery
grid-charges nothing, so those fixtures went inert.

Resolved by making the policy explicit wherever the scenario depends on grid charging,
rather than by weakening the assertions:

- `_cost_cfg` in `test_results_view.py` now pins P3, with a new sibling `_energy_cfg`
  supplying the cost-OFF half of the toggle. This second helper is load-bearing: several
  tests assert the energy blocks are bit-identical across the cost toggle, which only
  holds if the two configs differ in `simulate_cost` alone — pinning only the cost-on
  side made those fail.
- A new `_grid_charging_cfg` helper serves the three tests sharing the negative-saving /
  drift / self-sufficiency-clamp scenario.
- `uncertainty_client` in `test_results_route.py` pins P3 for the same reason.

Each helper carries a comment stating why the policy is named rather than inherited.

## Files modified

- `app/domain/simconfig.py` — default `charge_policy` P3 → P1, docstring updated.
- `docs/specs/02-ux-wireframes.md` — §2.3 charge-policy wireframe now preselects P1.
  The no-PV variant already showed P2 selected (`effective_charge_policy` maps a stored
  P1 to P2 without PV), so it needed no change.
- `tests/test_simconfig.py` — expected wireframe default updated.
- `tests/test_params_view.py` — default assertion and summary-line string updated.
- `tests/test_results_view.py` — added `_energy_cfg` and `_grid_charging_cfg`; pinned P3
  in `_cost_cfg`; switched the cost-off halves of toggle comparisons to `_energy_cfg`.
- `tests/test_results_route.py` — `uncertainty_client` fixture pins P3.
- `changelog/20260805-default-charge-policy-p1.md` — this file.

## Status

Complete. Verified against the affected and adjacent test files —
`test_results_view`, `test_params_view`, `test_simconfig`, `test_results_route`,
`test_params_route`, `test_simulate`, `test_metrics`, `test_workspace_routes`,
`test_workspace_list`, `test_workspaces`, `test_workspace_results`,
`test_no_english_leakage`, `test_data_summary`, `test_simframe` — 865 passed.
The full suite was not re-run end to end at the user's request (it includes long
benchmarks); the files not run are ones with no dependency on the policy default.
