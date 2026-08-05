# Cost toggle silently changes `battery.coupling`

## The user's prompts, verbatim

Recorded per `docs/specs/AGENTS.md` ("When updating files in the specs directory, also record the human
user's original prompts in the changelog"), since this task amended appendix A and two wireframes.

1. "please create a worktree, we're going to iterate on some UX features"
2. "when I change the toggle "simulate cost savings" on the result screens, I see it changes some
   battery settings (I get the badge "1 changed from default"). why is that?"
3. "fix the default; make AC the default."
4. (in answer to which of the two conflicting defaults to change) "pv_coupling → ac"
5. "happy to update the spec"

## Task specification

The user reported that flipping the "Simulate cost savings?" toggle on the results screen makes
the "More settings" pane show a `1 changed from default` badge, without them having changed any
battery setting. Investigate why, then fix it.

## Investigation — what actually happens

Reproduced by driving the real app (`TestClient`) through a full on → off → on toggle cycle,
posting the results screen's form exactly as the browser builds it. The badge count goes
`0 → 1 → 1 → 1`, and the single differing field is:

    battery.coupling = Coupling.DC_HYBRID   (appendix-A default: Coupling.AC)

It flips on the FIRST toggle in either direction, then stays. Cost simulation is only the
trigger, not the cause.

The chain:

1. A freshly-constructed `SimulationConfig` is internally inconsistent: `topology.pv_coupling`
   defaults to `DC_HYBRID` while `battery.coupling` defaults to `AC`. Appendix A specifies both
   values independently (`coupling | ac`, line 17; `pv_coupling | dc_hybrid`, line 38), so the
   inconsistency is in the spec, not introduced by the code.
2. The cost toggle carries `form="params-form"`, and the results screen's delegated `change`
   handler calls `requestSubmit()`. Flipping it therefore POSTs EVERY control on the screen,
   including `topology.pv_coupling`, whose `dc_hybrid` radio renders `checked`.
3. `params_view.parse_form` (app/params_view.py:329-338) re-derives the battery field from the
   topology field whenever `topology.pv_coupling` is present in the form:
   `cfg.battery.coupling = Coupling(cfg.topology.pv_coupling.value)`. The submitted `dc_hybrid`
   overwrites the stored `AC`.
4. `battery.coupling` is in `results_screen_view.ADVANCED_PATHS`, so once it differs from a
   freshly-constructed default the badge counts it.

**Not involved:** the `retained.economic_guard` machinery in `simconfig_store`, which the module
documents at length. It works correctly here — `advanced_changed_count` deliberately reads the
stored `cfg.policy.economic_guard` rather than the forced property, exactly to avoid this class
of problem. The first hypothesis (that the forcing of `economic_guard` was leaking into the
count) was checked and ruled out before `battery.coupling` was found.

A harness artifact cost some time: posting the form body as a list of `(name, value)` tuples
through `TestClient` sent an empty body, making the toggle appear not to persist at all. Posting
a plain dict fixed it.

## Decision

Two fixes were put to the user:

* **Fix the default** — make the two coupling defaults agree, so the round-trip is a no-op.
* **Fix the derivation** — re-derive `battery.coupling` only when `topology.pv_coupling` actually
  changed from the stored value.

The user chose to fix the default, and specified AC. Since `battery.coupling` is ALREADY `ac`,
that means changing `topology.pv_coupling`'s default from `DC_HYBRID` to `AC`.

This was queried once before implementing, because appendix A gives the `dc_hybrid` default an
explicit rationale ("Most new installs are hybrid; ask, do not assume") and the change has a
simulation consequence: `eta_c_dc` multiplies the PV-charge path in §6.8, so a default run's
round-trip efficiency changes. The user confirmed `pv_coupling → ac`.

The user then agreed to amend the spec as well ("happy to update the spec"), so code and spec stay
in agreement and appendix A's rationale is replaced rather than left contradicting the code.

## Files modified

* `app/domain/simconfig.py` — `TopologyConfig.pv_coupling` default `DC_HYBRID` → `AC`; the field's
  docstring updated; a note added to `TopologyConfig` recording that the two coupling defaults must
  agree AND why, so the invariant is not silently re-broken.
* `docs/specs/appendix-a-defaults.md` — the `pv_coupling` row now reads `ac`, with the old "most new
  installs are hybrid" rationale replaced by the constraint that forced the change.
* `docs/specs/03-topology-selector.md` — the illustrated selector's pre-selected radio moved to
  AC-coupled.
* `docs/specs/02-ux-wireframes.md` — the §2.3 Installation-topology wireframe's pre-selected radio,
  likewise.
* `tests/test_simconfig.py` — the appendix-A table row updated; new
  `test_the_two_coupling_defaults_agree` pinning the invariant as an equality between the two
  fields rather than against a literal.
* `tests/test_workspace_results.py` — new
  `test_the_cost_toggle_changes_nothing_the_advanced_pane_counts`, driving the reported symptom
  end-to-end over a full on/off/on cycle and asserting on the badge COUNT.
* `changelog/20260805-cost-toggle-changes-coupling.md` — this file.

`docs/specs/07-internal-representation.md` was deliberately NOT changed: its `"pv_coupling":
"dc_hybrid"` is an illustrative populated result object, not a defaults table.

The spec files were edited at `specs/` and moved to `docs/specs/` when this branch was rebased
onto master, which had meanwhile landed "Split the docs by audience and move specs/ under docs/"
(4e130f8). Git followed the renames with no conflicts; the paths above are the post-rebase ones.

## Current status

Done. The fix is verified two ways:

* Driving the real app through on → off → on, the badge count now stays `0` at every step while
  `simulate_cost` still persists correctly (it was `0 → 1 → 1 → 1` before).
* Both new tests were confirmed to FAIL against the old default before the change was restored, so
  they pin the bug rather than merely restating the new value.
* Full suite: 1343 passed, 24 skipped (the skips are the live-HA suite, as always).

Open, not addressed here:

* The underlying derivation in `parse_form` still fires on every submission that includes
  `topology.pv_coupling`, rather than only on an actual change. With the defaults now agreeing it
  is inert for a fresh workspace, but it remains the general mechanism by which an untouched
  control can be rewritten by an unrelated submission — a user who deliberately sets a coupling
  that disagrees with their PV selector would still see it overwritten. Worth considering on its
  own merits; not required to close this report.
* Changing the shipped coupling changes what a DEFAULT run computes, since `eta_c_dc` multiplies
  the PV-charge path (§6.8). Existing saved workspaces are unaffected (they carry their own stored
  value), but a fresh workspace's headline numbers will differ from before this change. Not
  measured.
