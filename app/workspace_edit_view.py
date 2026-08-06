"""The view-model for the edit-workspace screen (docs/specs/20-workspaces-ux.md §2′.4, §2′.8).

`GET /w/{id}/edit` and `POST /w/{id}/edit` render and write the household's fixed facts: the
workspace title, the grid connection and the contract. `postcode` is still carried in the view
dict below, but the template no longer renders a box for it — nothing in the results reads it
yet, so §2′.4's Location box is hidden until something does. The key is kept deliberately, so
restoring the box costs one hunk in `templates/workspace_edit.html` and nothing here. This module turns a
`SimulationConfig` (plus the workspace row's title and a `ValidationResult`) into the dict
`templates/workspace_edit.html` renders, and answers the two questions the template must not
decide for itself — which connection entries the dropdown offers, and how many advanced values
are overridden.

Nothing here does I/O, nothing here mutates the config, and nothing here formats a number for a
locale: the figures on this screen are FORM VALUES (a `<option>` label naming a connection, an
`<input value=>` a browser will parse back), which `params_view._fmt` already argues must stay
un-localised or a Dutch user's own stored setting round-trips into a field error.

## The connection dropdown, and the one rule that must not be got wrong

§2′.4 replaces §2.3's phases-radio + free-text-fuse pair with ten presets, each writing the same
`grid.phases` and `grid.fuse_a` the two controls wrote before. `CONNECTION_PRESETS` is that list,
verbatim from the spec, and each entry is labelled with `connection_capacity_kw_display` — the
rounded display figure, never the exact one §6.8 step 6 compares against.

**A stored combination matching no preset renders as an ADDITIONAL, marked, selected entry.** It
is not snapped to the nearest preset, because the fuse feeds `max_import_kw` directly: turning a
stored `1×20 A` into `1×25 A` would raise the household's import cap by 1.15 kW and change the
answer, silently, on a screen the user opened to change something else. `connection_options`
emits that extra entry at the head of the list with `off_list=True`; it disappears on the next
save that selects a listed option, since nothing then holds the off-list pair any more.

The option VALUE is `"<phases>:<fuse>"` rather than two coordinated controls, because one select
that writes two fields is what §2′.4 asks for and because two hidden fields kept in step by
script would be a second place for the pair to disagree. `parse_connection` is the inverse and is
deliberately tolerant: a value it cannot read leaves both fields as they were, the same answer
`params_view._enum_or_keep` gives a radio group with a tampered value.

## The Contract box is always drawn

§2′.4 is explicit and calls it a deliberate exception to §2.3's Inapplicable rule: this box is a
standing fact about the household, not an input to the current run, and it is also what UNBLOCKS
the cost toggle on the results screen (§2′.6) — greying it while cost simulation is off would
make the two controls mutually blocking. So `contracts` is built unconditionally and carries no
`simulate_cost` gate at all. FIXED and VARIABLE stay rendered-but-disabled with their feature
keys — the pending affordance, not absence. `params_view._pricing_view` did the same for panel
②'s copy of these radios; §2′.1 moved the box here and that function went with it, so this is
now the only place the three contract types are offered. The same applies to `tlk_modes`, and to
`settlements` — which is built unconditionally for the same reason, but carries no pending entry
and no feature key, because both of its answers are implemented.

## Which issues this screen may show

`validate()` is whole-config, and this screen draws four fields out of ~30. An issue keyed to a
battery field has no input here to attach to, so `EDITED_FIELDS` is the filter: issues inside it
bind to their input, and any BLOCKING issue outside it is surfaced at page level rather than
dropped — a save that refuses to happen must say why even when the reason is off-screen.

Main items:
    CONNECTION_PRESETS   §2′.4's ten (phases, fuse_a) pairs, in the spec's order.
    EDITED_FIELDS        the dotted paths this screen draws an input for.
    connection_value(cfg) / parse_connection(raw)   the `<select>` value and its inverse.
    connection_options(cfg)   the dropdown, including the off-list entry when there is one.
    edit_view(cfg, title, ...)  the whole dict `workspace_edit.html` renders.
"""

from __future__ import annotations

from app.domain.simconfig import (
    Contract,
    SimulationConfig,
    SupplierSettlement,
    TlkMode,
    ValidationResult,
    connection_capacity_kw_display,
)
from app.params_view import _fmt, field_messages, issue_message
from app.sample_data import _N

# §2′.4's list, verbatim and in its printed order: 1×10 … 1×50, then 3×25 … 3×80. These are the
# connections a Dutch household can actually have, so the list is closed — there is no "other…"
# and no free-text fuse field, and a household whose operator set a different limit expresses that
# through the advanced import/export override instead.
CONNECTION_PRESETS: tuple[tuple[int, float], ...] = (
    (1, 10.0),
    (1, 25.0),
    (1, 35.0),
    (1, 50.0),
    (3, 25.0),
    (3, 35.0),
    (3, 40.0),
    (3, 50.0),
    (3, 63.0),
    (3, 80.0),
)

CONNECTION_LABEL = _N("%(phases)s × %(fuse)s A  (%(kw)s kW)")
"""One dropdown entry: `1 × 25 A  (5.75 kW)`.

A msgid with three holes rather than a concatenation, for `app/i18n.msg`'s reason — a
runtime-assembled string has no msgid `pybabel extract` can see. `_N` because a module-level
assignment is not a call the extractor recognises. The `×` is U+00D7, the multiplication sign the
wireframe uses and the one a Dutch meter cabinet label carries.
"""

CONNECTION_LABEL_OFF_LIST = _N("%(phases)s × %(fuse)s A  (%(kw)s kW) — your stored setting")
"""The extra entry for a stored combination that matches no preset (§2′.4).

Marked in the label rather than only in an attribute, because the marking is the whole point: the
user has to be able to see that this is their own value and not one of the standard connections.
"""

EDITED_FIELDS: frozenset[str] = frozenset(
    {"grid.phases", "grid.fuse_a", "grid.max_import_kw_override", "grid.max_export_kw"}
)
"""The dotted paths this screen draws an input for (module comment).

`postcode` is absent on purpose: `validate()` has no rule for it, so it can never key an issue.
The pricing fields are absent too — the Contract box draws the contract RADIO and its advanced
rates, and the rate inputs are listed in `ADVANCED_PRICING_FIELDS` below, which is folded in.
"""

ADVANCED_GRID_FIELDS: tuple[tuple[str, int], ...] = (
    ("grid.max_import_kw_override", 2),
    ("grid.max_export_kw", 2),
)
"""The Grid connection box's Advanced pane: the two override fields and their render precision.

Both default to `None` ("derive from the connection" / "same as import"), which is what makes the
"N values overridden" count meaningful — a non-None value here is by definition an override.
"""

ADVANCED_PRICING_FIELDS: tuple[tuple[str, int], ...] = (
    ("pricing.supplier_markup", 4),
    ("pricing.energy_tax_excl_vat", 5),
    ("pricing.vat_rate", 0),
    ("pricing.feedin_alpha", 2),
    ("pricing.feedin_beta", 4),
    ("pricing.tlk_eur_per_kwh", 4),
    ("pricing.dal_start_hour", 0),
    ("pricing.dal_end_hour", 0),
    ("pricing.degradation_eur_per_kwh", 4),
)
"""The Contract box's Advanced pane, in §2′.4's wireframe order, with render precisions.

The precisions are `_panel_params.html`'s, so the same stored number is written the same way on
both screens — a markup that reads 0.0205 in panel ② and 0.02 here would look like two different
settings.
"""

_CONTRACT_LABELS: dict[Contract, str] = {
    Contract.DYNAMIC: _N("Dynamic"),
    Contract.FIXED: _N("Fixed"),
    Contract.VARIABLE: _N("Variable"),
}

# Only DYNAMIC has a rate source behind it (§6.5). The other two render PENDING — disabled, with a
# `[?]` opening the shared "Not built yet" dialog — rather than being dropped, and the keys are the
# ones `app/features.py` already allocated for panel ②'s copy of this control. Reusing them is
# deliberate: the key names the FEATURE, not the screen it was clicked on, so interest registered
# from either place counts once and the counter row keeps one meaning.
_CONTRACT_FEATURE_KEYS: dict[Contract, str] = {
    Contract.FIXED: "pricing_contract_fixed",
    Contract.VARIABLE: "pricing_contract_variable",
}

# Terugleverkosten mode (§6.5). Same pending treatment and the same reuse of panel ②'s key: TIERED
# is vocabulary, not implementation (it needs a tier table, an annualisation and the
# `min_tlk_tiering_days` fallback), so the row is DRAWN and disabled rather than absent.
#
# **This pair came here late.** It was the one control the Pricing box carried that this screen did
# not, so when §2′.1's move was completed the selector briefly existed nowhere while
# `pricing_tlk_tiered` stayed registered in `app/features.py` and accepted by the interest route —
# a feature key with no control, which is precisely the state §2.1's pending doctrine exists to
# prevent. Rebuilt here rather than dropping the key.
_TLK_LABELS: dict[TlkMode, str] = {
    TlkMode.FLAT: _N("flat, per fed-in kWh"),
    TlkMode.TIERED: _N("tiered by annual volume"),
}
_TLK_FEATURE_KEYS: dict[TlkMode, str] = {TlkMode.TIERED: "pricing_tlk_tiered"}

# Supplier settlement period (§6.16). No pending treatment and no feature key, unlike the two
# selectors above: both answers are implemented, and which one is stored decides only whether the
# results screen admits an intra-hour price uncertainty. Labels name the BILLING period the user
# can read off their contract rather than EPEX's settlement change, which is not what the answer
# turns on — the help line carries that distinction.
_SETTLEMENT_LABELS: dict[SupplierSettlement, str] = {
    SupplierSettlement.HOURLY: _N("Hourly average"),
    SupplierSettlement.QUARTER_HOURLY: _N("Every 15 minutes"),
}


def _fmt_fuse(fuse_a: float) -> str:
    """A fuse rating for a label: "25" for 25.0, "1.5" for 1.5.

    Same rule and same reasoning as `workspace_list_view._fmt_fuse` — a rating is an identifier of
    a connection type rather than a quantity, so it is not localised and an integral value loses
    its ".0". Duplicated rather than imported because the list view's copy is documented as being
    about the BADGE, and a shared helper would tie two screens' formatting together for two lines.
    """
    try:
        return str(int(fuse_a)) if float(fuse_a).is_integer() else str(fuse_a)
    except (TypeError, ValueError):
        # A hand-edited document can hold a string here. Showing it back is the error path's job.
        return str(fuse_a)


def _fmt_kw(kw: float) -> str:
    """A connection capacity for a label, at its own natural precision.

    `connection_capacity_kw_display` has ALREADY decided the precision (two decimals below 10 kW,
    one at or above, so both published figures — 5.75 and 17.3 — come out as appendix A prints
    them). Re-padding to a fixed width here would turn 17.3 back into 17.30 and contradict it, so
    this is `:g`. `params_view._g` did the same for panel ②'s copy of the figure until §2′.1 made
    this screen the only one drawing the connection; that helper went with the box it served, so
    this is now the single renderer of it.
    """
    try:
        return f"{float(kw):g}"
    except (TypeError, ValueError, OverflowError):
        return str(kw)


def connection_value(cfg: SimulationConfig) -> str:
    """The `<select>` value naming the stored connection: `"1:25"`.

    One control writing two fields (§2′.4), so the pair travels as one token. `_fmt_fuse` keeps
    the token stable across a load — a stored 25.0 and a stored 25 produce the same value, so a
    document written by either path selects the same option.
    """
    return f"{cfg.grid.phases}:{_fmt_fuse(cfg.grid.fuse_a)}"


def parse_connection(raw: object) -> tuple[int, float] | None:
    """`"3:63"` → `(3, 63.0)`; anything unreadable → `None`.

    `None` means "leave both fields as they were", which is what `_enum_or_keep` does for a radio
    group and for the same reason: the dropdown is a closed vocabulary the user cannot type into,
    so an unrecognised value is a tampered or stale POST rather than a user mistake, and there is
    nothing to report inline. Resetting the connection to a default instead would silently move
    the household's import cap.

    Deliberately does NOT check the pair against `CONNECTION_PRESETS`. An off-list combination is
    a legitimate stored value the dropdown itself renders back (module comment), so a submission
    carrying one is the user leaving their own setting alone, not an attack.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if ":" not in text:
        return None
    phases_raw, _, fuse_raw = text.partition(":")
    try:
        phases = int(phases_raw)
        fuse = float(fuse_raw)
    except (TypeError, ValueError):
        return None
    return phases, fuse


def _same_connection(cfg: SimulationConfig, phases: int, fuse_a: float) -> bool:
    """Whether the stored connection IS this preset, compared numerically.

    Numeric rather than string comparison so a document holding `fuse_a: 25` and one holding
    `fuse_a: 25.0` both match the `1×25 A` preset. A non-numeric stored value (a hand-edited
    document) matches nothing, which is what puts it on the off-list entry.
    """
    try:
        return int(cfg.grid.phases) == int(phases) and float(cfg.grid.fuse_a) == float(fuse_a)
    except (TypeError, ValueError):
        return False


def connection_options(cfg: SimulationConfig) -> list[dict]:
    """§2′.4's dropdown: the ten presets, plus the stored combination when it matches none.

    **The off-list entry is the rule this function exists for.** The old free-text fuse field
    could have produced `1×20 A`, and `grid.fuse_a` feeds `max_import_kw` directly — so rendering
    the nearest preset instead would raise the household's import cap without telling anyone, on a
    screen opened to edit something else. The stored pair is therefore emitted as its own entry,
    marked in its label, and selected. It leads the list so it is visible without scrolling, and
    it is not persisted anywhere: the next save that picks a listed option simply stops producing
    it.

    Every label carries `connection_capacity_kw_display`, the ROUNDED figure — the exact value is
    what §6.8 step 6 compares the net flow against and is never printed.
    """
    options: list[dict] = []
    matched = any(_same_connection(cfg, p, f) for p, f in CONNECTION_PRESETS)
    if not matched:
        options.append(
            {
                "value": connection_value(cfg),
                "label": CONNECTION_LABEL_OFF_LIST,
                "phases": cfg.grid.phases,
                "fuse": _fmt_fuse(cfg.grid.fuse_a),
                "kw": _fmt_kw(connection_capacity_kw_display(cfg.grid.phases, cfg.grid.fuse_a)),
                "selected": True,
                "off_list": True,
            }
        )
    for phases, fuse in CONNECTION_PRESETS:
        options.append(
            {
                "value": f"{phases}:{_fmt_fuse(fuse)}",
                "label": CONNECTION_LABEL,
                "phases": phases,
                "fuse": _fmt_fuse(fuse),
                "kw": _fmt_kw(connection_capacity_kw_display(phases, fuse)),
                "selected": _same_connection(cfg, phases, fuse),
                "off_list": False,
            }
        )
    return options


def _get_path(cfg: SimulationConfig, path: str):
    """Read a dotted path off a config. Mirrors `params_view._get_path`."""
    obj = cfg
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _overridden_count(cfg: SimulationConfig, paths, defaults: SimulationConfig) -> int:
    """How many of `paths` differ from the appendix-A default (§2′.4's "N values overridden").

    Compared against a freshly-constructed `SimulationConfig` rather than a hardcoded table, so
    the count follows appendix A wherever appendix A moves. A raw string the user typed counts as
    overridden — it certainly is not the default — which is the honest answer for a summary line
    whose whole job is to stop a non-default value being left hidden in a collapsed pane.
    """
    n = 0
    for path in paths:
        if _get_path(cfg, path) != _get_path(defaults, path):
            n += 1
    return n


def edit_view(
    cfg: SimulationConfig,
    title: str,
    *,
    result: ValidationResult | None = None,
    wizard: bool = False,
    save_error: bool = False,
) -> dict:
    """The dict `workspace_edit.html` renders (§2′.4). Pure presentation — no I/O, no mutation.

    `result` is the validation of THIS config; when omitted it is computed here, so a GET does not
    have to. `title` comes from the `workspaces` row rather than from the config, because that is
    where it lives — the one field on this screen that is not in the config document.

    `wizard` selects §2′.8's footer: `[ ← Previous ] [ Next → ]` instead of `[ Cancel ] [ Save ]`.
    The two modes differ only in the footer and in where a successful save goes; everything above
    the footer is the same screen, which is why this is a flag rather than a second view.

    `save_error` says the config was valid but could not be written (a read-only or full data
    directory), the same flag and the same reasoning `params_view.params_view` carries.

    **Issues are filtered to what this screen draws** (module comment). A blocking issue keyed
    outside `EDITED_FIELDS` cannot be bound to an input, so it is surfaced at page level in
    `other_errors` — dropping it would mean a save that refused to happen with nothing on screen
    to explain why. Warnings outside the set are NOT surfaced: they do not block, so they would be
    a caveat about a field the user cannot see and did not touch, on a screen they came to for
    something else.
    """
    if result is None:
        result = cfg.validate()
    messages = field_messages(result)
    defaults = SimulationConfig()

    def field(path: str, places: int = 1) -> dict:
        """One input's render state: value, dotted name, inline messages.

        Percent-typed fields go through `params_view`'s own conversion table rather than a second
        copy of it, so `pricing.vat_rate`'s stored 0.21 shows as 21. Panel ② used to render the
        same field the same way; since §2′.1 moved the Pricing box here this is the only screen
        that renders it, but the table stays shared because `parse_form` — which reads THIS
        screen's submissions — is the other half of the same conversion and must not drift from it.
        """
        from app.params_view import _PCT_FIELDS, _frac_to_pct

        value = _get_path(cfg, path)
        if path in _PCT_FIELDS:
            value = _frac_to_pct(value)
        msg = messages.get(path, {})
        return {
            "name": path,
            "value": _fmt(value, places),
            "errors": msg.get("errors", []),
            "warnings": msg.get("warnings", []),
            "invalid": bool(msg.get("errors")),
        }

    contracts = [
        {
            "key": c.value,
            "label": _CONTRACT_LABELS[c],
            "selected": cfg.pricing.contract == c,
            "pending": c in _CONTRACT_FEATURE_KEYS,
            "feature_key": _CONTRACT_FEATURE_KEYS.get(c),
        }
        for c in Contract
    ]

    tlk_modes = [
        {
            "key": m.value,
            "label": _TLK_LABELS[m],
            "selected": cfg.pricing.tlk_mode == m,
            "pending": m in _TLK_FEATURE_KEYS,
            "feature_key": _TLK_FEATURE_KEYS.get(m),
        }
        for m in TlkMode
    ]

    settlements = [
        {
            "key": s.value,
            "label": _SETTLEMENT_LABELS[s],
            "selected": cfg.pricing.supplier_settlement == s,
        }
        for s in SupplierSettlement
    ]

    grid_advanced = [field(path, places) for path, places in ADVANCED_GRID_FIELDS]
    pricing_advanced = {path: field(path, places) for path, places in ADVANCED_PRICING_FIELDS}

    return {
        "title": title,
        # Produced but currently unrendered — the Location box is hidden (see the module header).
        # Kept so restoring it is a template-only change.
        "postcode": str(cfg.postcode or ""),
        "connection_options": connection_options(cfg),
        "connection_value": connection_value(cfg),
        "grid_advanced": {
            "max_import_override": grid_advanced[0],
            "max_export": grid_advanced[1],
            "overridden": _overridden_count(
                cfg, [p for p, _ in ADVANCED_GRID_FIELDS], defaults
            ),
        },
        "contracts": contracts,
        "tlk_modes": tlk_modes,
        "settlements": settlements,
        "pricing_advanced": pricing_advanced,
        "pricing_overridden": _overridden_count(
            cfg, [p for p, _ in ADVANCED_PRICING_FIELDS], defaults
        ),
        # The one checkbox in the Contract box's Advanced pane, and the ONLY checkbox this screen
        # draws. Read back through the `pricing_advanced` marker (`params_view._section`), which
        # exists so this screen can claim this checkbox without also claiming panel ②'s
        # `policy.economic_guard`. A collapsed pane — whose inputs are still in the DOM, see the
        # template — round-trips it rather than clearing it.
        "dal_weekends": bool(cfg.pricing.dal_weekends),
        "wizard": bool(wizard),
        "valid": not result.blocking,
        "save_error": bool(save_error),
        # Blocking issues this screen has no input for. See the docstring.
        "other_errors": [
            issue_message(i) for i in result.errors if i.field not in EDITED_FIELDS
        ],
    }
