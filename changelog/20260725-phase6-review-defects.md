# Phase 6 review defects — fixes

## Task specification

An adversarial review of Phase 6 (panel ② parameters: form layer + persistence) returned
DEFECT FOUND with three defects and a set of nitpicks. The core of the phase was verified
correct and must not be disturbed: all 21 form controls reach `SimulationConfig`, persistence
degrades safely on every corruption mode, path traversal is blocked, coercion is right,
validation surfacing works, gating consumes the config's own queries, fixture 12 passes
byte-identically, i18n is clean.

Scope: fix D1, D2, D3; scope the `retained` slot to `economic_guard` only (FLAG 1); triage the
nitpicks. Do not commit.

## The three defects

**D1 — `save()` used a fixed temp filename (HTTP 500 under concurrency).**
`simconfig_store.save()` wrote to `path.with_suffix(".json.tmp")`, a name shared by every
writer. Two overlapping saves both write it, the first `os.replace` consumes it, and the second
raises `FileNotFoundError` — an `OSError`, which `main.py`'s handler turns into a 500. Two
browser tabs or a double-click on "Calculate →" reproduce it.

Fix: `tempfile.mkstemp(dir=path.parent)` for a per-writer unique name, `finally:
tmp.unlink(missing_ok=True)` so a failed write leaves no litter, and an explicit `os.chmod`
to 0644-modulo-umask because `mkstemp` creates 0600 while the rest of the data dir (the SQLite
file, the `.npz` arrays) is created at the default umask. The fsync-then-`os.replace` is kept
unchanged — it is what makes the write atomic against truncation.

**D2 — `OverflowError` on a long numeric input (HTTP 500 on ordinary input).**
`coerce_number` tries `int(text)` first, which succeeds for digit strings up to Python's
4300-digit limit. `_finite` then calls `float()` on that unbounded int and raises
`OverflowError` before reaching its `math.isfinite` guard. `POST /params` with a 4000-digit
value → 500. Roughly 310 < digits < 4300 is the window; longer strings are safe because
`int()` hits its own digit limit and the `float()` fallback yields `inf`, which `_finite`
rejects cleanly.

Fix in `_finite` (`app/domain/simconfig.py`): wrap the `float()` in
`try/except OverflowError: return None`. This is a Phase 2 module, but the defect breaks that
module's own stated contract ("construction never raises"), so the fix belongs there rather
than in the form layer.

**`_finite` was not the only site.** A route-level test over every numeric field found three more
`OverflowError`s on the same unfloatable int, all in the RENDER path, which runs for a blocking
config too: `_fmt` (fixed-point formatting of an int goes through float), `_g` (`%g`, same), and
`_pct_to_frac`/`_frac_to_pct` (the ×100 scaling on the two percent-typed fields). Each now falls
back to passing the value through unscaled and stringifying it, which shows the user their own
digits back — the error path's job anyway. Fixing only `_finite`, as the review scoped it, would
have left `POST /params` still 500ing on the same input.

**D3 — a forged `sections` value cleared the retained `economic_guard`.**
`sections` is an unprotected hidden field and `guard_was_submitted` trusted it. With
`simulate_cost` false the Pricing box is never drawn, but a client claiming it was got
`guard_submitted=True`, skipping the carry-forward and wiping the retained value.

Fix: `guard_was_submitted(form, stored)` is now `_section(form, "pricing") and
stored.simulate_cost` — the server already knows whether it could have drawn the box, so it no
longer takes the client's word alone. The three legitimate cases (drawn+ticked, drawn+unticked,
never-drawn) are unchanged.

## FLAG 1 — `retained` is scoped to `economic_guard`, deliberately

The reviewer found that `economic_guard` is NOT on appendix A's retained list. The spec names
it separately: it is "additionally **forced** off rather than merely hidden, because it reads a
cost-model output" (`specs/appendix-a-defaults.md:79-81`). The twelve cost-only parameters are
merely INERT — nothing normalises them away, so they retain themselves through `parse_form`'s
existing inherit-if-absent rule, which is already implemented and tested.

So the `retained` slot is single-purpose and stays that way. Generalising it to thirteen fields
would build a shadow copy of the parameter set with its own drift surface for no benefit. The
module comment now says this explicitly, so the next implementer does not dutifully extend it.
If a second forced-off field ever appears, revisit — a list of two is still not a pattern.

## Nitpicks

Fixed:
- **`"version"` is now checked.** A document whose `version` is not 1 yields appendix-A
  defaults, like any other unreadable document. Previously `"version": 99` parsed as v1, which
  made the docstring's migration claim untrue.
- **`coerce_number` tightened.** Underscore grouping (`"1_000"` → 1000) and non-ASCII digits
  (`"١٢"` → 12) are no longer silently accepted; they fall through to the raw-string error path
  like any other thing a user did not mean to type. `"nan"`/`"inf"` also fall through now, which
  fixes the related render bug (the input used to show `nan` rather than the user's literal
  text). `validate()` already blocked them, so no wrong number ever reached the simulation
  either way.
- **A rapid second valid submit could leave panel ③ stale.** `recompute()` returned early when
  `recalcInFlight`, dropping the newer body. It now parks the newest body and re-fires when the
  in-flight request settles.
- **A read-only data dir gave a 500.** It is now a visible non-field error on the panel ("The
  parameters could not be saved…"), still not pretending the save worked. New EN/NL strings.

Left alone:
- **CSRF.** The POST is state-changing and unprotected. Local-only app, `workspace_id` is the
  hardcoded `"local"`, no exfiltration path, and the response is same-origin-read-blocked, so a
  cross-site POST could at worst rewrite the local user's own parameters with values the
  attacker cannot read back. A token would add a session/secret surface this app does not
  otherwise have. Decision recorded here rather than implemented.

## Obstacle: the Phase 6 message catalogs had never actually been regenerated

`changelog/20260725-panel2-parameters-phase6.md` records the catalogs as "extracted, translated
to NL, EN source catalog filled, both `.mo`s recompiled". They were not: `app/locales/` in the
working tree predates panel ②, so `pybabel extract` picked up 31 new msgids on the first run
here — every panel-② label, every validation message, and the soft-block dialog. A Dutch user
would have seen the whole parameter panel in English.

The catalogs are now extracted, the 31 NL strings translated (plus two multiline band-overlap
entries the run also surfaced), the EN source catalog filled, and both `.mo`s recompiled.
Verified by rendering panel ② and the soft-block dialog under `Accept-Language: nl`.

This inflates the catalog diff well beyond the one string this task added, which is expected —
it is Phase 6's own catalog update landing late, not new work.

## Correction to the record

An earlier task brief cited "20 kWh/8 kW → 1,582 kWh saved". That figure was wrong. The correct
figures on the real dataset are 10 kWh/5 kW → 341 kWh and 20 kWh/8 kW → 317 kWh: the saving
DECREASES with a bigger battery, because grid-charge round-trip loss plus standby outgrow the
gain. No changelog or comment in the repo cited 1,582, so nothing needed correcting; it is
recorded here so the number does not resurface. This also confirms why
`test_a_parameter_change_moves_panel_3s_figures` asserts movement rather than direction.

## Files modified

- `app/simconfig_store.py` — D1 temp-file fix; version check; `retained` scoping comment.
- `app/domain/simconfig.py` — D2 `_finite` OverflowError guard.
- `app/params_view.py` — D3 `guard_was_submitted` signature; `coerce_number` tightening.
- `app/main.py` — D3 call site; read-only-data-dir save failure as a panel error.
- `app/templates/_panel_params.html` — render the save-failure notice.
- `app/templates/index.html` — pending-body re-fire in `recompute()`.
- `app/translations/*` — two new strings.
- `tests/test_params_view.py`, `tests/test_params_route.py`, `tests/test_simconfig.py` — new
  regression tests for each defect.

## Verification

Reproduced before each fix and re-measured after, over real HTTP (three threads, 30 submissions
each, `POST /params`):

| | before | after |
|---|---|---|
| D1 concurrency | `Counter({200: 57, 500: 33})` | `Counter({200: 90})` |
| D2 4000-digit value | 500 | 200 + field error |
| D3 forged `sections` | stored `True` → `False` | stays `True` |

The 33/90 measured here is lower than the review's 40/90; the rate depends on thread
interleaving, so the two are consistent. The final document is a complete config from one writer
in every run, and no `*.tmp` litter is left.

End to end against a running app: valid submit persists; a 4000-digit value, `abc` and `nan` all
return 200 with the value echoed verbatim and an inline error; a read-only `data/local/` returns
200 with the save-failure notice instead of a 500; panel ② and the soft-block dialog render fully
in Dutch.

Test suite: **458 passed, 2 skipped** (from 434/2 — 24 new tests). No `simconfig.json` left in
`data/`.

## Current status

Fixes applied and verified. Not committed, per instruction.
