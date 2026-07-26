# Phase 4 — Configure data, and results

Part of the workspaces restructure; plan in `20260726-workspaces-implementation-plan.md`,
spec in `specs/20-workspaces-ux.md` §2′.5 (configure data) and §2′.6 (results).

## Task specification

Split the remaining single-page UI into the two screens the restructure ends with.

**4.1 — `/w/{id}/data`, configure data (§2′.5).** Mostly a move: panel ①'s roster, source
drawer, HA modal, quality box and glance keep their behaviour unchanged. Adds the titled
"About your household" box around `has_pv` / `has_battery`, the §2′.8 footer, and a dirty
warning keyed on staged-but-unfetched slots (the generation-tagged `localStorage` entry
already answers this — §2′11).

**4.2 — `/w/{id}/results`, results (§2′.6).** Panels ② and ③ combined, with ② reduced to a
capacity-first battery box: usable capacity alone, then a collapsed "More settings" pane
holding three tabs (Battery / Installation / Charge & discharge). The cost toggle moves
inside the results block, under the period selector, and is **Blocked** with an ⓘ dialog
until the workspace has a contract configured.

Constraints from the spec that are easy to get wrong:

- **This screen has no footer buttons** (§2′.6). Parameter edits recompute and persist as
  they always have; the screen is left through the back link. It is the end of both the
  card path and the wizard path.
- **The battery box and the results scroll together on one screen.** §2′.6 calls this the
  equivalent of §3.4's "reopening panel ① or ② does not collapse panel ③", which that spec
  names the single most important interaction detail in the app. It is why parameters were
  not given a screen of their own.
- **`RESULTS_STALE` still dims previous results rather than blanking them**, and editing a
  parameter still does not navigate away from the figures.
- **The advanced pane preserves state and does not reset on collapse**, with a collapsed
  summary naming how many values differ from the defaults — as on the edit screen.
- **Tabs are a presentation choice**; the four groups keep their §2.3 contents, validation
  and gating (PV-blocked charge policies, cost-gated economic guard, the soft block on
  unsupported battery phases). Stacked boxes remain a valid fallback if tabs prove awkward.
- **Charge and discharge share one tab** because the overlap warning compares band A/B
  against band C/D; splitting them would put the warning on one tab and the values it
  indicts on the other.
- The cost toggle is **Blocked, not Inapplicable** — the precondition is one screen away
  from met, so hiding it would leave the user nothing to click and nothing to read.

## Findings from reading the code before starting

Two things reduce the scope the plan anticipated, and one adds to it.

**`has_pv` / `has_battery` have already moved.** §2′.5 reads as though they must be relocated
from the setup band, but `_panel_data.html:95` shows they already sit at the top of panel ①,
under the names `setup_haspv` / `setup_hasbattery` — deliberately *not* the `setup.` prefix,
so they are independent of `params-form`. Phase 4's work here is wrapping them in the titled
box, not rewiring form association.

**The setup band is down to one control.** `_setup_band.html` now carries only
`setup.simulate_cost`, via `form="params-form"` (HTML's explicit form association). That single
radio pair is what §2′.6 turns into the cost toggle inside the results block. So the band
disappears rather than being split.

**The JS is delegated, which makes the split tractable.** The ~320-line IIFE at the bottom of
`index.html` attaches its listeners to `document` and looks its targets up by id, so a handler
whose elements are absent is inert rather than broken. The panel-① and panel-②/③ handlers are
interleaved in one block and have to be separated, but not rewritten.

**`pricing.configured` is `retained.pricing_configured`.** §2′.6 names the flag
`pricing.configured`; phase 0 implemented it in the `retained` block with
`simconfig_store.is_pricing_configured()`, and phase 3's edit screen already sets it. The
spec's name is spec-side; the code's name is the real one.

## 4.1 — plan taken into the build

1. Split `_panel_data.html`'s body into four includes — household box, roster, quality box, and
   the existing `_data_glance.html` — so `index.html`'s panel ① and the new screen render the
   SAME markup rather than two copies.
2. Add `app/data_screen_view.py` (the phase-3 view-model idiom) and
   `app/templates/workspace_data.html` (the phase-3 full-page idiom).
3. `GET /w/{id}/data` + `POST /w/{id}/data` in `main.py`, with `?mode=wizard`.
4. Move the panel-①-relevant JS out of `index.html`'s IIFE onto the new page; leave panel-②/③
   handlers where they are.
5. Dirty check keyed on the generation-tagged `localStorage` store, not on form state.

## High-level decisions

### The POST does not go through `parse_form` at all

This is the decision the brief's `sections` warning forced, and it resolves the hazard by
removing it rather than by getting the marker right.

The only persistable state on this screen is `has_pv` / `has_battery`. Everything else — the
source mapping, the dataset — is already committed by the drawer's Confirm and by
`[ Fetch history ]`. Those two answers are NOT `params_view.FIELDS` entries: they are
`setup_haspv` / `setup_hasbattery`, deliberately outside the `setup.` namespace (phase-3 finding),
and `parse_form` has no `has_battery` branch at all — only `setup.has_pv`, gated on `setup`.

So routing this screen's submission through `parse_form` would mean adding a branch AND choosing
a `sections` value, for a form that draws exactly zero checkboxes. Instead the route reads the two
radios directly and writes them through `main._persist_setup_answers` — **the same function the
ingest WS `done` handler already uses to commit these very two answers**. It clones before saving
(so `_force_invariants` re-runs: turning PV off must drop a stored DC coupling) and passes
`guard_submitted=False`.

Consequence, stated plainly: **this screen's form carries no `sections` field and reaches
`parse_form` on no path**, so there is no marker to over-claim and no checkbox it can clear. That
is the strongest available form of the phase-3 defect being impossible here.

`pricing_configured` is deliberately not passed: it stays `None` ("carry forward"). §2′.6 makes
the EDIT screen the one that means "the user has told us what they pay"; a data save must not
unblock the cost toggle.

### `[ Save ]` persists the two radios, and the fetch still does too

§2′.5 says the radios are "still committed with the fetch". That is kept — nothing in
`ha_fetch.js`'s header path changed. The footer's `[ Save ]` ALSO persists them, because a
`[ Save ]` that saved nothing would be a lie on a screen whose footer promises one. **This fills a
gap the spec leaves rather than transcribing something it states:** §2′.8 gives this screen a
footer with a `[ Save ]`, and §2′.5 names the fetch as the commit point, but neither says what
`[ Save ]` itself writes. Two writers for one pair of answers is a drift risk, so they share a
body and a test drives both and compares the stored result.

### The writer had to be split, because its contract is "never raises"

**This was a defect caught in review before it shipped, not a design decision.** The obvious reuse
was `_persist_setup_answers`, which already commits these exact two answers from the ingest-WS
path. It is documented as NEVER RAISES and swallows everything with a `log.warning`, deliberately:
it runs *after* a fetch has persisted a dataset, so an exception there would fail a fetch whose real
work succeeded and report LOAD_FAILED for data that is on disk.

That is right for the WS path and wrong for a form POST. A `[ Save ]` against an unwritable data
directory would have logged a warning, returned 303, and shown the user a successfully-saved screen
with nothing saved.

Fixed by splitting rather than by changing the contract, since the WS path depends on the silence:

- `_write_setup_answers` — the shared body, which RAISES.
- `_persist_setup_answers` — the unchanged never-raises wrapper the WS path keeps calling.

`POST /w/{id}/data` uses the raising variant and renders the `save_error` notice, the same
treatment `POST /params` and `POST /w/{id}/edit` give an unwritable data directory. Verified end to
end (200 + notice, not 303), and pinned by three tests including one that the never-raises wrapper
still never raises.

### No `csrf.require_same_site` on `POST /w/{id}/data`

`app/csrf.py` states its line as "can this request destroy something the user cannot recreate",
not "is this a POST", and phase 3 applied that to `POST /w/{id}/edit`. This route is strictly
weaker than that one: it writes two booleans, both recoverable by clicking the other radio, and it
destroys nothing — it does not touch the dataset, the mapping, or the workspace row's title. It is
therefore left uncovered, consistently with `POST /params` and `POST /w/{id}/edit`. Phase 3's
standing note applies: if that judgement is revisited it should be revisited for all three
parameter-writing routes together, not drifted into on one.

### The dirty check reads `localStorage`, not the form

§2′.8 is explicit that "changed" on this screen means a slot mapping that has changed since the
last fetch, not form-dirty. §2′.11's generation-tagged `ha.slots.<workspace>` entry already
answers it: an entry whose `gen` equals the rendered `source_generation` is by definition a
PRE-FETCH staged choice (a fetch is the only thing that bumps the generation, and it re-renders
the slot server-side afterwards). So the check is: parse that key, compare `gen`, and warn if it
holds any slot. A stale-generation entry is not dirty — the server already superseded it.

The spec's own open question ("is 'since the last fetch' tracked today?") is therefore answered
yes, by branch 2 of `ha_fetch.js`'s two-branch architecture, for exactly the slots that matter.
The honest limit: a slot whose choice was staged in a DIFFERENT browser is invisible here, which
is the same browser-local property the store has everywhere else.

### The JS split: three handlers move, panel-②/③ handlers stay

`index.html`'s IIFE turned out to be almost entirely panel-②/③: the chart, the benchmark fetch,
`recompute`, the `params-form` submit, the `setup.`-prefixed change handler and the feed-in preset.
None of those belong on the data screen and none were moved. What the data screen needs is the
pending-affordance IIFE (a separate block, copied as phase 3 copied it for its standalone page),
the info dialog (already delegated inside `ha_fetch.js`, which the new page loads), and the new
dirty check. `ha_fetch.js` needed no change at all: it gates on `#slot-roster` and looks
everything else up by id, so it runs unmodified on the new screen and is inert on a screen without
a roster.

## Files modified

- `app/templates/_data_household.html` — **new.** §2′.5's titled "About your household" box,
  wrapping the `setup_haspv` / `setup_hasbattery` radios lifted verbatim out of `_panel_data.html`.
- `app/templates/_data_roster.html` — **new.** The `#slot-roster` card, lifted with one string
  changed: the legend no longer says the answers come from "the setup band above" (see Obstacles).
- `app/templates/_data_quality.html` — **new.** The Data-quality card, lifted verbatim.
- `app/templates/_panel_data.html` — body replaced by four includes; header comment updated.
  Panel ① renders the same markup it did, minus the `[ Next: parameters → ]` CTA on the new
  screen only (the CTA stays on panel ①, which phase 4.2 removes with the rest of it).
- `app/templates/workspace_data.html` — **new.** The full page: household box, roster, quality,
  glance, footer, plus the drawer, the HA modal and the three dialogs.
- `app/data_screen_view.py` — **new.** `data_screen_view()`, the dict the template renders.
- `app/main.py` — `GET`/`POST /w/{workspace_id}/data`; `_data_page` renderer; module docstring and
  route table updated. `POST /w/{id}/edit`'s wizard destination now points at `/w/{id}/data`.
- `app/templates/_workspace_card.html` — the phase-3 note updated: no card action 404s now.
- `tests/test_workspace_data.py` — **new**, 42 tests.
- `tests/test_smoke.py` — six browser tests (the round trip, roster re-gating, the dirty warning's
  three branches, `[ Leave anyway ]`, the drawer opening here, and the wizard chain).
- `tests/test_no_english_leakage.py` — `/w/{id}/data` added to `_PAGES`; it takes the 200-word panel
  floor rather than needing its own, since it renders ~300 words even in the empty state.
- `app/locales/*` — full `babel.cfg` workflow; 6 new msgids, all Dutch, zero fuzzy.
- `app/static/app.css` — **not changed.** `npm run build:css` was run and produced a
  byte-identical file: every utility class the new screen uses was already in the bundle, which
  follows from the markup having been lifted from an existing page rather than written fresh.

## Obstacles and solutions

**The never-raises writer.** Recorded as a decision above; caught in review before shipping.

**A test that could not fail.** `test_turning_pv_off_re_applies_the_forced_invariants` was written
believing the clone in `_write_setup_answers` was what re-applied §2.5's invariants. Dropping the
clone was tried and the test still passed: `simconfig_store.save` normalises through `to_dict` on
the write path, so the stored result is AC/None either way. The clone is defence in depth, not the
mechanism. The test now asserts the user-visible property and says explicitly what it does not
cover; `main.py`'s comment was corrected from claiming the clone was load-bearing. Worth recording
because the passing test had looked like coverage of that line and was not.

**A string had to change, not just move.** The roster legend read "Which rows appear comes from the
answers in the setup band above" — false on both screens now, since the band no longer holds those
answers. Reworded to "the answers above", which makes it a new msgid; the old one became an
obsolete `#~` entry and was translated afresh.

**The legend's translation landed in an obsolete block first.** The scripted `.po` edit anchored on
a slice of the msgid that also appears in two commented-out `#~` entries, so the first pass filled
one of those instead of the live entry. Caught by the catalog check still reporting one
untranslated, and redone as a targeted edit on the live entry. Phase 3's lesson about not
round-tripping the catalog through babel's writer held: zero `#~` entries were dropped.

## Verification

**Suite: 1085 passed, 2 skipped** (baseline **1023 passed, 2 skipped** on the same tree, measured
before starting). 62 added: 42 in `tests/test_workspace_data.py`, 6 Playwright, and 14 from the
leakage scan's seven scenarios × two checks on the new page. The only skips remain
`tests/test_ha_live.py`'s two, confirmed with `-rs`.

**Playwright: 35 passed** (29 before). The 29 pre-existing ones passed UNMODIFIED — none needed
editing or weakening. That is the strongest available signal that splitting `_panel_data.html` into
shared partials is behaviour-preserving, since three of them drive panel ①'s roster, its
`setup_haspv` radios and its source drawer through the real browser.

**Every assertion was checked for discrimination by mutation**, and where a template and a parser
form one contract, BOTH sides were mutated together — the phase-3 lesson that mutating only the
parser leaves a test green because the form helper hardcodes the corrected value. Each mutation was
reverted immediately and the tree re-verified clean.

| mutation | caught by |
|---|---|
| route uses the never-raises writer | 3 tests |
| both sides renamed to `setup.has_pv` / `setup.has_battery` | 7 route tests + 2 browser tests |
| a `sections` marker added to the form | 1 |
| `pricing_configured=True` from this route | 1 |
| absent radio defaults to False instead of None | 1 |
| the quality box rendered before any data | 1 |
| wizard `[ ← Previous ]` pointing at `/` | 1 |
| the clone dropped from the writer | **nothing — see Obstacles** |
| dirty check ignoring the generation | 1 browser test (the stale branch) |
| footer's `form=` association dropped | 2 browser tests |
| wizard step 1 skipping step 2 | 1 browser test |

**Rendered against a real temp data dir and read**, empty and with a persisted dataset. Present: the
titled household box, both radios, `#slot-roster` with the correct scoped `data-ingest-ws`, the
fetch button, the drawer with its Confirm/Cancel, the HA modal, all three dialogs, `ha_fetch.js`,
`#source-generation` and `#drawer-i18n`. Absent: `params-form`, `#panel-params`, `#panel-results`,
`setup.simulate_cost`, `#setup-band`, Plotly, the panel badge, the `[ Next: parameters → ]` CTA and
any `sections` field — so no panel-②/③ markup leaked in. The quality box and the glance are absent
before a fetch and both present after one.

**POST behaviour confirmed through the real route:** both answers round-trip in both directions;
card save → 303 to `/`, wizard save → 303 to `/w/{id}/results`; an absent radio leaves its stored
answer alone; turning PV off stores `coupling=AC` and `pv_coupling=None`; `pricing_configured` stays
False and a stored True survives; a failing save returns 200 with the notice rather than 303.

**4.2's files are byte-identical**, confirmed with `git diff --stat`: `app/templates/index.html`,
`_panel_params.html`, `_panel_results.html`, `_setup_band.html`, `app/params_view.py` and
`app/static/ha_fetch.js` are all unchanged. `ha_fetch.js` in particular needed no edit at all.

**Both locales rendered and read.** Dutch is complete on this screen; the catalog check reports 0
untranslated and 0 fuzzy for `nl`. The `en` catalog gains the new msgids as empty msgstrs, which is
that catalog's existing convention (an empty English msgstr falls back to the msgid).

## Review findings and fixes

An adversarial review found seven items, none blocking. Four were fixed here, two filed, one was
already correct in the code and wrong only in a docstring.

**Fixed — the quality box disappeared exactly when it was most needed.** The new screen gated BOTH
the quality box and the glance on `data_summary`; panel ① gates only the glance. `data_summary` is
None in two unlike situations, and the template treated them as one: "no dataset at all" (hide both,
correct) and "a dataset that loaded but yields no simulatable grid" (the glance should go, the
quality box must not). A price-only dataset is the second case and a real intermediate state — the
spot-price preset is a `backend_load` source that loads on its own, before any meter is mapped.
Reproduced: with a price-only dataset on disk, `/w/{id}/data` rendered no quality box while
`/w/{id}/results` rendered one. A user whose fetch produced an unusable dataset therefore saw a
roster and nothing else, indistinguishable from having fetched nothing, on the screen whose whole
job is saying why the data cannot be used. `has_dataset` is now a separate context key and the two
boxes have separate gates.

That fix took two attempts, which is worth recording. The first replaced the gate but left
`ctx["data_summary"]` reachable in the empty state, because `ctx` starts as `sample_view()` and both
keys arrive pre-populated with SAMPLE figures — so the empty state briefly rendered the glance for
data the user had never supplied. Caught by probing the empty state rather than only the new one;
the replace-or-drop is now explicit and commented.

**Fixed — `test_a_successful_save_advances_updated_at` could not fail.** `assert after >= before` on
a monotonic clock is a tautology: deleting `workspaces.touch` from the route left the entire
non-browser suite green. Rewritten to assert the ORDER of two workspaces, which is the property the
list screen actually reads, and confirmed to fail against the same mutation. The `>=` idiom was
copied from `test_workspace_edit.py:643` and `test_workspaces.py:291`, which share it — those are
not fixed here, and are worth a look in phase 6.

**Fixed — `touch()` fired on a save that stored nothing.** The route's comment claimed touch happens
"only after something was actually stored", but `_write_setup_answers` returns early when both
answers are None, so an empty body moved the workspace to the top of the list with its "last saved"
badge advanced. Only reachable by a hand-made POST, since a rendered form always submits both
radios — but the comment asserted a guarantee the code did not have. Now checked explicitly, with a
test.

**Fixed — a corrupt store whose `slots` is an array produced a spurious warning.**
`Object.keys(["a"]).length > 0` is true, so `{"gen":0,"slots":["x"]}` warned about a mapping that
does not exist. `Array.isArray` guards on both the envelope and `slots`. Every other malformed shape
already failed open as documented, and none threw.

**Fixed — a stale docstring in `data_screen_view.py`.** It still named `_persist_setup_answers` as
the writer both paths share, which the never-raises/raising split (itself a defect caught during the
build) made wrong. Also removed a dangling comment describing a key the function does not return.
The route and the template header were already correct.

**Filed as `followups.md` K1 — no config-writing route checks `is_document_readable`.** An
unreadable config document (a `version` from a newer build, or a hand-edit syntax error) is silently
replaced by appendix-A defaults: a 17.5 kWh battery and a 63 A fuse become 10.0 and 25.0, the
version is downgraded to 1, and the route returns 303. `simconfig_store.is_document_readable` exists
for precisely this and its docstring states the rule; no write path calls it. Verified class-wide —
`POST /w/{id}/edit` from phase 3 does exactly the same, as does `POST /params` and the fetch path —
so this pre-dates the workspaces work and 4.1 did not introduce it. What 4.1 changed is exposure: it
puts a `[ Save ]` button on the behaviour. Not fixed on one route, because a guard on this route
alone would leave the other three clobbering, which is the drift the standing same-site note warns
against.

**Filed as `followups.md` K2 — `[ Save ]` leaves a staged-but-unfetched mapping without a warning.**
§2′.8 says the check "does not guard `[ Save ]` or `[ Next → ]`, which persist", and this screen
follows that literally. But on the edit screen `[ Save ]` persists what the check is about, whereas
here it persists two booleans while the mapping stays unfetched — the rule honoured, its rationale
not. Confirmed in Chromium: no dialog, navigation proceeds, and the entry survives in
`localStorage`, so nothing is lost. A missing signal rather than data loss, and the fix changes what
`[ Save ]` means on this screen, so it is a product call.

The review also confirmed clean, with reproductions: split fidelity (a normalised-whitespace diff of
the rendered results page shows only the two documented differences; nothing disappeared from the
old `_panel_data.html`), all 25 ids and four classes `ha_fetch.js` resolves are present, no duplicate
ids, the no-JS fallback submits and every link and form action resolves, all four dirty-check
branches, injection via a crafted `mode` or a `<script>` title, `simulate_cost` row-gating parity
with panel ①, fresh install, and every mutation the changelog claims.

## Current status

**4.1 complete.** `GET`/`POST /w/{id}/data` are live, `[ Configure data ]` on a card reaches a real
screen, and no card action 404s any more. The wizard's step-1 `[ Next → ]` now points at step 2
instead of skipping to the results page. Suite: **1087 passed, 2 skipped** (35 Playwright), up from
1023 at phase 3.

Carried forward, none decided here:

- **4.2 is untouched and is the remaining work**: the capacity-first battery box, the tabbed
  advanced pane, and the cost toggle moving into the results block (Blocked until
  `pricing_configured`, which phase 3 made real). Panel ① and the setup band are 4.2's to delete —
  `_panel_data.html` keeps its `[ Next: parameters → ]` CTA until then, deliberately.
- **The shared partials are now the integration point with `ha_fetch.js`.** When 4.2 deletes
  panel ①, `_data_household.html`'s `titled=False` branch and `_panel_data.html` itself become dead
  and should go with it.
- **The dirty warning is browser-local.** A mapping staged in another browser is invisible to it.
  That is inherent to where §2′.11 puts the state, not a shortcut taken here, but it is the kind of
  thing worth stating before someone reports it as a bug.
- **The same-site question** for the three parameter-writing routes remains open as phase 3 left
  it: revisit all three together or not at all.
