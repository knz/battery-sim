# Slot info affordance (per-series explanation popup)

## Task specification

User's original request (paraphrased across the exchange):

- Q: "why is the user invited to provide data series for 'grid power' and 'house load'?"
  — answered from the specs: both are optional cross-checks on the error-prone
  PV-household load reconstruction (`house_load` = ground truth to validate against;
  `power_grid` = independent clock to catch a meter/inverter timestamp offset).
- "I'd like to add an 'info' button/icon next to these two data series name in the
  picker, to pop up an explanation of what you just said."
- "I think we have a dict somewhere which describes for each possible data series which
  sources are allowed for it. It would be nice if the info text was stored alongside, so
  we can use this info button machinery for more data series in the future without
  changing the template."
- "add them to the demo" (show the icons on the sample/demo landing page too).

Scope: add an `ⓘ` info icon next to the role label on slot rows that carry an info
blurb; clicking it opens a concise DaisyUI modal. The blurb is stored as per-series
metadata so the mechanism is generic (any future series gets an icon by adding a field,
no template change).

## High-level decisions

- **Blurb lives on `SlotSpec` (`app/domain/series_vocab.py`)**, not on the source
  registry. The user pointed at the "which sources are allowed per series" dict
  (`app/sources/registry.py`, keyed off `SlotSpec`), but that describes *sources*. The
  blurb describes the *series*, and `SlotSpec` already holds the per-series metadata
  (name, kind, requirement, pv_only, cost_only). Added `info: str | None = None` there.
- **Popup style: DaisyUI modal dialog** (consistent with `#ha-config-dialog`), **concise
  text** (1–2 sentences) — user-selected.
- **Generic template rendering**: the Role cell renders the icon `{% if row.info %}`, so
  the roster does not hard-code which series get an icon. One shared `<dialog>`; JS fills
  its title/body from the clicked button's `data-*`.
- **Copy passes through Jinja `_()`** (title + body), so translation works with no
  JS-side i18n. English source strings become msgids via `pybabel extract`.
- **Demo shows the icons**: the sample `mapping` (a hand-written literal in
  `app/sample_data.py`) previously omitted the `power_grid`/`house_load` rows; added both
  so the demo is a faithful preview of the full roster.

## Files modified

- `changelog/20260724-slot-info-affordance.md` — this file (new).
- `app/domain/series_vocab.py` — `info` field on `SlotSpec`; blurbs for `power_grid`,
  `house_load`; header comment updated.
- `app/data_view.py` — real-path row dict carries `"info": slot.info`.
- `app/sample_data.py` — sample `mapping` gains the two rows, each with its `info`.
- `app/templates/_panel_data.html` — generic info icon in the Role cell; shared
  `#slot-info-dialog`.
- `app/static/ha_fetch.js` — click handler that fills + opens the dialog.
- `app/locales/*` — extracted/updated/compiled catalogs for the new msgids.
- `tests/` — assertion that the icon + dialog render for a slot with `info`.

## Requirements changes mid-task

- House-load copy corrected: the reconstruction adds back **both** solar and existing-battery
  data (both optional); with neither, house load equals grid load. The blurb was rephrased
  accordingly (was solar-only). Applied in `series_vocab.py`; the sample/real paths and both
  catalogs pick it up as one msgid.

## Obstacles and solutions

- `info` blurbs are plain strings on `SlotSpec`, not in `sample_data.py` — so `pybabel extract
  -k _N` would miss them. Solution: added a local `_N` no-op marker in `series_vocab.py`
  (mirroring sample_data.py) and wrapped the blurbs, so extraction finds them wherever the
  view-model sources them.
- The two role labels ("Grid power", "House load") existed only in `data_view.ROLE_LABEL` as
  bare strings (never extracted). Adding the sample rows with `_N(...)` made them extractable.
- `pybabel update` auto-matched "About"/"Grid power" to wrong fuzzy translations in both
  catalogs; corrected by hand and cleared the fuzzy flags (left three pre-existing, unrelated
  fuzzy entries in en untouched).

## Current status

Done.

- All 78 tests pass (`pytest`, excluding the live-HA test); the new `test_slot_info_affordance`
  smoke test asserts exactly two ⓘ buttons render and clicking "House load" opens the dialog
  with the blurb.
- Dutch translations verified to resolve from the compiled `.mo` (labels + both blurbs).
- Catalogs recompiled (`pybabel compile`).
