"""The view-model for the configure-data screen (docs/specs/20-workspaces-ux.md §2′.5, §2′.8).

`GET /w/{id}/data` and `POST /w/{id}/data` render and write the one thing on that screen the
server persists: the household's two scope answers, `has_pv` and `has_battery`. Everything else the
screen shows — the slot roster, the source drawer, the HA connection modal, the data-quality box
and "Your data at a glance" — is panel ①'s existing view-model, unchanged, and reaches the template
through the same `data` / `data_summary` context keys `index()` already builds.

This module is therefore deliberately thin. It exists for the reason `workspace_edit_view` exists:
so the template does not decide anything, and so the two footer modes and the save-error notice
have one named source rather than being spelled out at each render site.

## What this screen persists, and what it does NOT

**It writes `has_pv` and `has_battery`, and nothing else.** §2′.5 says the two answers "are still
committed with the fetch", and that is kept — `app/static/ha_fetch.js` still sends them on the
ingest WS `header`. The footer's `[ Save ]` / `[ Next → ]` persists them TOO, because §2′.8 gives
this screen a footer that promises a save and a `[ Save ]` that saved nothing would be a lie. Both
writers share one body — `main._write_setup_answers` — so they cannot disagree about what committing
these two answers means. They differ only in error handling, and deliberately: the fetch path wraps
it in `main._persist_setup_answers`, which swallows failure because it runs after a dataset is
already on disk and must not fail a fetch whose real work succeeded; the footer's `[ Save ]` calls
the raising form directly, because a swallowed failure there would show a saved screen with nothing
saved.

**The submission does not go through `params_view.parse_form`, on any path.** That is a decision
with a reason (see `changelog/20260726-workspaces-phase4.md`): `parse_form` inherits absent fields
from its base, EXCEPT checkboxes, which are gated on the hidden `sections` marker — and a marker
that over-claims silently clears stored state, which is how phase 3 shipped two data-loss defects.
This screen draws ZERO checkboxes, so the correct marker would be the empty one; rather than emit
a marker that means nothing and rely on it staying meaningless, the form carries no `sections`
field at all and the route reads its two radios directly. There is consequently no marker here to
get wrong.

**`pricing_configured` is not touched.** `simconfig_store.save`'s keyword defaults to `None`,
meaning "carry forward", and `_persist_setup_answers` does not pass it. That is relied upon rather
than incidental: §2′.6 makes the EDIT screen the one that means "the user has told us what they
pay", and a data save that set the flag would unblock the results screen's cost toggle from the
wrong screen.

## The dirty warning is not a form-dirty check

§2′.8 is explicit that "changed" on this screen means **a slot mapping that has changed since the
last fetch** — the roster says one thing and the loaded data reflects another. The radios do not
trigger it on their own, and the spec says so: flipping one changes which slots are ASKED FOR, not
which data is loaded.

That state is not on the server. It is the generation-tagged `localStorage` entry
`ha.slots.<workspace>` (§2′.11), whose `gen` is compared against the rendered `source_generation` —
see `app/static/ha_fetch.js`'s header, branch 2 of "Two things carry a source choice across a
reload". An entry at the CURRENT generation is by definition a staged-but-unfetched choice, because
a fetch is the only thing that bumps the generation and it re-renders the slot server-side
afterwards. So the check lives in the template's script, not here, and this module contributes
nothing to it beyond the fact that the screen renders `source_generation` at all.

## The wizard's step-2 gate

§2′.8 blocks `[ Next → ]` here until §6.3's load reconstruction — `load = imp − exp + pv +
batt_dis − batt_chg` — is computable, and the blocked button NAMES the missing series rather than
saying "load data first", because the user is looking at the roster that would fix it.

`load_gate` is that condition and nothing else. It is a pure function over the set of series names
in the loaded dataset, so the route supplies the names and this module decides — the no-I/O rule,
and the reason the answer is available to the POST route too, which needs it with nothing rendered.

Main items:
    LOAD_GATE_ROLES                                       the roles the gate can require, in
                                                          roster order.
    load_gate(names, *, has_pv, has_battery)              the missing role names, in roster order.
    data_screen_view(cfg, title, *, wizard, save_error, missing_for_load)
                                                          the dict `workspace_data.html` renders.
"""

from __future__ import annotations

from app.data_view import ROLE_LABEL
from app.domain.simconfig import SimulationConfig

# The roles §2′.8's gate can require, in the order the roster draws them, so a message naming
# several reads in the same order as the table beside it.
#
# **T1 only, and T2 deliberately absent.** §2′.8's parenthetical says "both T1/T2 register pairs",
# but the code disagrees in three places and the code is right: `series_vocab.SERIES_SLOTS` marks
# the T2 registers "optional"; `reconcile._combined` folds the two registers so an absent T2
# contributes zero and the reconstruction succeeds on T1 alone; and `workspaces._data_facts` gates
# the §2′.2 card badge on T1 with the note that "T1 is §4.1's required slot of each pair, so its
# presence answers 'is this role filled'". A single-tariff household HAS no T2 register, so
# requiring it would lock those users out of the wizard permanently behind a message naming a
# series they cannot supply — the opposite of the gate's purpose. Filed as a spec-wording
# correction; see `changelog/20260726-workspaces-phase5.md` D2.
#
# `price_spot` is deliberately absent for a different reason: §2′.8 says so directly. The spot
# price is needed for dispatch but not for LOAD, and the gate is "a lower bar than a full run" —
# step 3 can render the battery-free glance from load alone, and a missing price is something the
# results screen states in context.
LOAD_GATE_ROLES: tuple[str, ...] = (
    "grid_import_t1",
    "grid_export_t1",
    "solar_production",
    "battery_charge",
    "battery_discharge",
)


def load_gate(
    names: set[str] | frozenset[str],
    *,
    has_pv: bool,
    has_battery: bool,
) -> list[str]:
    """The series §2′.8's gate wants and this dataset does not have, in roster order.

    An empty list means `[ Next → ]` is live. Anything else is the Blocked reason, and the caller
    renders each name through `ROLE_LABEL` so the message and the roster word a slot identically.

    `names` is the set of series in the LOADED dataset (D1) — the frames the data screen already
    holds, not `workspaces.DataFacts`, which reads the same question back out of SQLite and does
    not cover the two existing-battery slots. The two must not disagree about the three roles they
    share; a test pins that they do not.

    The PV and battery slots are required only when the household declared them. This is not
    leniency: without the declared PV series the reconstruction attributes the array's output to a
    house that does not exist, which is check 7's negative-load symptom (§7.3). A household that
    says it has no array has nothing to attribute, so there is nothing to require.

    There is deliberately no duration test and no window test. §2′.8: "the gate is about which
    series exist, not how long they run" — §2.4's short-window box already caveats a brief window,
    and duplicating that judgement here would turn away a user legitimately checking a week.
    """
    required = {"grid_import_t1", "grid_export_t1"}
    if has_pv:
        required.add("solar_production")
    if has_battery:
        required.update(("battery_charge", "battery_discharge"))
    return [role for role in LOAD_GATE_ROLES if role in required and role not in names]


def data_screen_view(
    cfg: SimulationConfig,
    title: str,
    *,
    wizard: bool = False,
    save_error: bool = False,
    missing_for_load: list[str] | None = None,
) -> dict:
    """The dict `workspace_data.html` renders (§2′.5). Pure presentation — no I/O, no mutation.

    `title` comes from the `workspaces` row rather than from the config, because that is where a
    workspace's title lives; this screen only DISPLAYS it (in the header, per §2′.5's wireframe)
    and never writes it — renaming is the edit screen's job (§2′.4).

    `wizard` selects §2′.8's footer: `[ ← Previous ] [ Next → ]` instead of `[ Cancel ] [ Save ]`.
    A flag rather than a second view, for the reason phase 3 gives: the two modes differ only in
    the footer and in where a successful save goes, so a second view would be a second render site
    for two buttons.

    `save_error` says the two answers could not be written (a read-only or full data directory),
    the same flag and the same reasoning `params_view.params_view` and `workspace_edit_view` carry.
    It matters more here than it looks: the writer the ingest-WS path uses
    (`main._persist_setup_answers`) is contractually silent about failure because that path depends
    on the silence, so this route calls the raising `main._write_setup_answers` instead and reports
    through this flag. Phase 4.1 nearly shipped the swallowing version, which would have redirected
    to a saved-looking list with nothing on disk.

    There is deliberately no `valid` key and no issue list. This screen draws no numeric input and
    no enum the user can put out of range: two booleans cannot fail `validate()`, so there is
    nothing for a blocking-issue path to report and no re-render-with-errors branch to build.

    `missing_for_load` is `load_gate`'s answer — the route computes it, because the gate reads a
    loaded dataset and this module does no I/O. It becomes `next_blocked` and `missing_labels`, the
    two keys the footer renders.

    **`next_blocked` is false outside the wizard even when series are missing.** §2′.8 blocks the
    wizard's forward step, not `[ Save ]`: the card path's save persists two booleans and returns
    to the list, and greying it because the dataset is incomplete would refuse a save that has
    nothing to do with the dataset. The `and wizard` here is what keeps the two paths separate.
    """
    missing = list(missing_for_load or ())
    # Deliberately NOT echoing the two answers: the household box reads `cfg.has_pv` /
    # `cfg.has_battery` off the shared `cfg` context key, exactly as panel ① does, so putting them
    # here too would be a second source for one pair of answers.
    return {
        "title": title,
        "wizard": bool(wizard),
        "save_error": bool(save_error),
        "next_blocked": bool(wizard and missing),
        # The msgids, not translated text: the template runs each through `_()`, so the message
        # and the roster row for the same slot come out of the same catalog entry.
        "missing_labels": [ROLE_LABEL[role] for role in missing],
    }
