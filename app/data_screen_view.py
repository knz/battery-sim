"""The view-model for the configure-data screen (specs/20-workspaces-ux.md §2′.5, §2′.8).

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

Main items:
    data_screen_view(cfg, title, *, wizard, save_error)   the dict `workspace_data.html` renders.
"""

from __future__ import annotations

from app.domain.simconfig import SimulationConfig


def data_screen_view(
    cfg: SimulationConfig,
    title: str,
    *,
    wizard: bool = False,
    save_error: bool = False,
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
    """
    # Deliberately NOT echoing the two answers: the household box reads `cfg.has_pv` /
    # `cfg.has_battery` off the shared `cfg` context key, exactly as panel ① does, so putting them
    # here too would be a second source for one pair of answers.
    return {
        "title": title,
        "wizard": bool(wizard),
        "save_error": bool(save_error),
    }
