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

## 4.2 — findings from reading the code before starting

**The setup band's deletion has one concrete dangling reference.** §2′.7 flags it and it is real:
`_panel_results.html:298`'s invitation box (`"Want to know what this is worth in euros?"`) links to
`href="#setup-simulate-cost"`, an id that exists only in `_setup_band.html:47`. Deleting the band
leaves a link to nothing. §2′.7 says the invitation "stays as it is" and is explicitly a hold rather
than a conclusion — so the anchor is repointed at the toggle's new home, and the box must say
something useful when that toggle is Blocked, but the box itself is not redesigned here.

**`simulate_cost` keeps gating a control on a different screen.** It moves to results, but still
gates the `price_spot_min` / `price_spot_max` roster rows on configure-data. 4.1 already reworded
the legend away from "the answers in the setup band above"; the cross-screen gating itself is
unchanged and must keep working.

**Sizes, for scope.** `_panel_params.html` is 538 lines, `_panel_results.html` 416, `index.html` 693
(including the ~320-line IIFE, which 4.1 established is almost entirely panel-②/③ and therefore
belongs to this half), `params_view.py` 1004. This is the largest single piece of the restructure.

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

## 4.2 — what was built

`GET /w/{id}/results` is §2′.6's screen: the capacity-first battery box above the results block, on
one page. Panel ①, the setup band and the three-panel layout are gone.

- **`app/templates/_panel_params.html` reshaped in place**, keeping `id="panel-params"` and
  `id="params-form"` — both are contracts with `POST /w/{id}/params` and the swap handler. Usable
  capacity alone up front with its ⓘ, then a `<details id="params-advanced">` whose summary carries
  the "N changed from default" badge, holding three tabs.
- **`app/templates/index.html` → `workspace_results.html`** (a `git mv`, so the diff shows the
  edits rather than a delete-plus-add).
- **`app/results_screen_view.py` — new.** The title, the Blocked flag, and `ADVANCED_PATHS` /
  `advanced_changed_count`.
- **`app/templates/_setup_band.html` and `_panel_data.html` deleted**, and
  `_data_household.html`'s `titled=False` branch with them, as 4.1 said they should be.

### The tab order, and where the two boxes §2′.6 does not place ended up

§2′.6 names three tabs and assigns §2.3's boxes 3, 4 and 5. It does not say where §2.3's box 2
(Grid connection) or the Pricing box go, and both had to land somewhere.

**Grid connection went on the Battery tab.** The fuse rating and phase count set `max_import_kw`,
which §6.8 step 6 clamps every interval against — they are the battery's operating envelope, so
they sit with the other limits. Installation was the alternative and was rejected because §2′.6
gives that tab to the ILLUSTRATED selectors specifically, for a reason about width.

**The Pricing box went on Charge & discharge**, below the overlap warning. It prices the bands two
cards above it. A fourth tab would contradict the tab list §2′.6 draws; putting it on Battery would
separate the rates from the bands they evaluate.

Neither is what the spec asked for, because the spec did not ask. Both are recorded as fills rather
than transcriptions.

### The tabs are radios plus CSS, and that is a data-loss decision

A JS-swapped or conditionally-rendered tab would submit the two tabs the user did not open as
CLEARED fields — the same defect as rendering a collapsed `<details>` conditionally, with a
different trigger. `display:none` does not exclude a control from a form body (only `disabled`
does), so hiding by CSS is safe where removing is not.

The mechanism is three `name="params-tab"` radios before the panels and a `:has(…:checked)` rule in
`app.tailwind.css`. The radios carry no dotted path, so `parse_form` never sees them. The rules are
UNLAYERED for the reason the cost tint already documents: Tailwind nests daisyUI's rules in a layer
declared after ours, and a layered block loses whatever its specificity.

### `Installation` on a 1-phase household without PV says so, rather than being blank

§2.3 says that box "empties entirely" there and tells the caller not to render it. A tab cannot be
dropped — a strip with a dead third entry is worse than an empty panel — so the panel states the
reason instead. A new msgid, and a fill rather than a transcription.

### The cost toggle: what moved and what deliberately did not

`setup.simulate_cost` kept its NAME, its `form="params-form"` association and its `setup` section
marker. Only its position in the document changed. That is why `params_view` needed no behavioural
change and why the `setup.`-prefixed `change` handler works unmodified: it matches on the prefix,
not on the band.

**Blocked is enforced by `disabled` on the radios, and only from the client side.** The route has no
check of its own, deliberately: §2′.6 makes the edit screen the one place the precondition is
cleared, and a second gate here would put the rule in two places. A hand-crafted POST is therefore
honoured — see the open item below.

`cost_toggle_blocked` defaults to false in the template so a caller that omits it draws a live
toggle; both real callers pass the flag, and `POST /w/{id}/results` re-reads it per request because
the recompute that triggers a swap can be the one the toggle itself just caused.

### The dangling anchor, and the one thing the invitation box had to gain

`#setup-simulate-cost` was kept as the toggle's id, so §2.4's invitation links to a control on the
page that renders the link. When the toggle is Blocked the box swaps its button for
`[ Set up my contract → ]` pointing at `/w/{id}/edit#contract` — the same destination the ⓘ dialog
offers, because there is one way to clear this and two buttons claiming to lead there would be two
answers to one question. §2′.7's hold was honoured otherwise: the question is unchanged.

**`workspace_edit.html` gained `id="contract"` on its Contract box.** §2′.6 says the dialog
"navigates to the workspace's edit screen with the Contract box in view", and that anchor did not
exist — the link would have resolved to the top of the screen with the box below the fold, passing
any `href` check.

## 4.2 — the `sections` marker, traced

The brief asked for each claim to be named explicitly. Re-derived by rendering the screen against
every config shape that changes which checkboxes it draws:

| shape | `sections` | checkboxes drawn |
|---|---|---|
| appendix-A defaults | `setup battery grid charge discharge topology` | `allow_grid_export` |
| cost on | + `pricing pricing_advanced` | + `economic_guard`, `dal_weekends` |
| no PV, 1-phase | `setup battery grid charge discharge` (no `topology`) | `allow_grid_export` |
| 3-phase, unsupported topology | `… topology` | + `topology.approximated` |

- **`policy.allow_grid_export` / `discharge`** — always drawn, always claimed.
- **`policy.economic_guard` / `pricing`** — drawn iff `cfg.simulate_cost`; claimed iff the same.
  `guard_was_submitted` additionally requires the SERVER's `stored.simulate_cost`, so a client that
  claims `pricing` with cost off gets no authority over the stored guard.
- **`pricing.dal_weekends` / `pricing_advanced`** — drawn and claimed together with the box.
- **`topology.approximated` / `topology`** — the one asymmetry, and it is correct. `topology` is
  claimed whenever the topology BOX is drawn, but the checkbox exists only while the selected phase
  topology is unsupported. `parse_form` handles the gap on purpose: inside a form that drew the box
  it sets `approximated = False` for a supported topology, "so a user who moves back to the 3-phase
  inverter is no longer carrying an approximation caveat they did not earn". Pinned in both
  directions rather than exempted.
- **`setup.simulate_cost` / `setup`** — drawn (in the results block) and claimed.
- **`setup.has_pv` / `setup`** — NOT drawn, and the marker over-claims it in the letter of the rule.

That last one was examined rather than waved past. It is safe for a structural reason: `has_pv` is a
RADIO GROUP, so its branch is guarded by `"setup.has_pv" in form` and an absent group inherits. The
marker only ever grants permission to READ a value that is present; the defect it exists to prevent
is the checkbox one, where absence is indistinguishable from unticked. Splitting `setup` in two
would buy nothing and would leave one screen emitting a marker no parser branch reads.
`_sections_for`'s docstring now says all of this, and `parse_form`'s `setup.has_pv` branch is
recorded as dead-but-kept.

## 4.2 — obstacles and defects found

**The advanced pane snapped shut on every `[ Calculate → ]`.** A real defect, found by driving the
screen in Chromium and invisible to every non-browser test. `POST /w/{id}/params` answers with a
fresh render whose `<details>` has no `open` attribute and whose tab strip has `checked` on Battery
— those are the template's defaults and the server cannot know better. Swapping that in verbatim
closed the pane and reset the tab, hiding the field the user had just edited. §2′.6 says the pane
"preserves state and does not reset on collapse"; resetting it on a swap the user did not ask for is
the same failure with a worse trigger. Fixed with `readPaneState` / `applyPaneState` around the
swap, carrying ONLY which pane is open and which tab is selected — no value travels that way, since
the response is the authority on what is stored. Pinned by a Playwright test, and by the mutation
that removes the two calls.

**A mutation the suite could not catch.** Switching `ADVANCED_PATHS`'s `policy.economic_guard` to
the forced `economic_guard` property left all 1131 tests green. The count would then drop when cost
simulation went off even though the stored answer was retained. Closed with a unit test on the view
model — and the finding is that it could NOT be closed through the route: `simconfig_store.load`
lifts the retained guard back into `policy` only when `simulate_cost` is on, so the divergent state
is unreachable from the store today. The difference is latent rather than live, and the test says so.

**Two route tests were pinning §2.3's collapsed summary line**, which §2′.6 removed with the panel
it summarised. `params_view.summary_line` still exists and is still covered by
`tests/test_params_view.py`; nothing renders it. Both tests were re-aimed at the input VALUES, which
is the stronger property anyway — it is what the user sees and what the next submission sends. The
summary's disappearance is a real loss of a compact readout and is recorded as such, not as a
tidy-up.

**Test-side casualties of the split, all repointed rather than weakened.** `test_i18n.py`'s
`#drawer-i18n` block, three `test_ingest_ws.py` page assertions, and two `test_results_route.py`
glance tests were reading panel ①'s content off `/w/{id}/results`. They now read `/w/{id}/data`,
via a new `tests/conftest.py:data_page()` beside `page()`. One of them INVERTED and that is the
specified behaviour, not a loosening: `test_page_shows_sample_before_any_fetch` looked for a
sample-only quality string as proof of the empty state, and 4.1's review gated the quality box on
`has_dataset` precisely so those figures do NOT appear for data the user never supplied.

**`test_the_cost_tint_actually_renders` had to grow a step.** It turned cost simulation on through
the setup band's radio; that radio is now Blocked on a fresh workspace. Rather than writing a config
file, it now drives both steps — asserts the toggle is disabled, opens the ⓘ, saves the edit screen,
returns and finds it live. That is a stronger test than the one it replaced: it proves the
precondition is real rather than decorative.

**An active-tab assertion that could not fail.** The first version compared the selected tab's text
COLOUR against an unselected one's. daisyUI's `.tabs-bordered` already tints a checked tab, so
deleting our own rules left it green. Re-aimed at the underline and the font weight, which are what
those rules contribute, and re-checked against the same mutation.

**`git checkout` on a mutated file destroyed the rewritten template once.** The mutation loop used
`git checkout <file>` to revert, which for a file whose new content was never staged reverts to the
PRE-4.2 version rather than to the working copy. `_panel_params.html` had to be rewritten. The rest
of the loop used a scratchpad backup instead. Recorded because the failure is silent — the tests go
green again, against the old file.

## 4.2 — verification

**Suite: 1131 passed, 2 skipped** (baseline **1087 passed, 2 skipped**, measured on this tree before
starting). 44 added: 41 in `tests/test_workspace_results.py`, 2 Playwright, and 1 net from the
leakage scan. The only skips remain `tests/test_ha_live.py`'s two, confirmed with `-rs`.

**Playwright: 37 passed** (35 before). Ten pre-existing browser tests had to be repointed at the
configure-data screen or re-aimed at what replaced panel ①; none was weakened to pass, and each
change is a screen moving rather than an assertion softening.

**Every assertion was mutation-checked — 27 mutations, all caught, two only after a test was added
or fixed.** Both sides of a template/parser contract were mutated together where one existed.

| mutation | caught by |
|---|---|
| capacity moved inside the pane | 1 |
| Installation tab rendered only when selected | 6 |
| pane contents rendered only when open | 13 |
| Battery not the default tab | 1 |
| overlap warning back inside the discharge card | 2 |
| `cost_toggle_blocked` hardcoded false | 4 |
| Blocked HIDES the toggle (Inapplicable) | 4 |
| Blocked radios not `disabled` | 2 |
| `#contract` anchor removed from the edit screen | 2 |
| invitation keeps the old anchor when blocked | 2 |
| a footer added to the screen | 1 |
| `sections` over-claims `pricing` | 3 |
| `sections` drops `setup` — marker AND parser gate together | 2 |
| `advanced_changed` counts the capacity — path list AND template | 1 |
| `advanced_changed` reads the FORCED economic guard | **nothing — see Obstacles** (now 1) |
| `POST /results` forgets the toggle's state | 1 |
| `POST /params` redirects instead of returning a fragment | 3 |
| header shows the app name, not the analysis | 2 |
| `params-form` action flattened to `/params` | 2 |
| Installation empty state renders blank | 1 |
| blocked dialog's link drops `#contract` | 3 |
| count badge always says "1" | 1 |
| tab labels lose their `for=` | 1 |
| pane-state carry-over removed (the real defect) | 2 browser tests |
| `.tab-panel` shows every panel | 1 browser test |
| the SVGs squeezed to 48px | 1 browser test |
| active-tab styling removed | **nothing until the assertion was re-aimed** (now 1) |

**Driven in Chromium and looked at, not only asserted on.** The tabbed pane works: exactly one panel
visible at a time with all three in the DOM, panels 884px wide at a 1280px viewport, and the
illustrated selector — three frames deep at pane → tab → card — renders its SVGs at 398×265 (PV) and
248×165 (phases), against the ~250px the chooser needs. No horizontal overflow, no console errors.
That was the item the plan flagged as needing a real look, and it survives the nesting.

**Rendered against a real temp data dir and read**, in four config shapes and both locales. Present:
`#panel-params` with the capacity outside the pane, the three tabs with Battery checked, the
`sections` marker, `#panel-results` with `#setup-simulate-cost` under the period selector, the
Blocked dialog, `#slot-info-dialog` and `#pending-dialog` at page level. Absent, checked outside
comments and script bodies: `#slot-roster`, `#setup-band`, `#source-drawer`, `#ha-config-dialog`,
`#source-generation`, `#drawer-i18n`, `data-ingest-ws`, `setup_haspv`, `ha_fetch.js`, the ① and ②
badges, `Next: parameters`, `PARAMETERS` and `data-footer`. No duplicate ids in the real markup.
Every link and form action resolves, and every fragment link resolves to an id on the page it points
at — including `#contract` on the edit screen, verified by fetching that page.

**Fresh install driven end to end in a browser**: `[ + New analysis ]` → the results screen, capacity
visible, results rendered, toggle Blocked, no console errors. **The no-JS path** was driven with
JavaScript disabled: `[ Calculate → ]` posts to the scoped `/w/{id}/params` and returns the
re-rendered box.

**Both locales rendered and read.** Dutch is complete on this screen; the catalog check reports 0
untranslated and 0 fuzzy for `nl`. 12 new msgids, all translated; the obsolete `#~` block grew from
230 to 262 entries and lost none. The `en` catalog gains the msgids as empty msgstrs, which is that
catalog's convention.

**`app/static/app.css` regenerated** — `npm run build:css`, and this time the output really changed:
the CSS-only tab rules and `.blocked-control` are new, and both were confirmed present in the
minified bundle and load-bearing by mutation.

## 4.2 — review findings and fixes

An adversarial review found one BLOCKING defect and two minor ones. All three were fixed; three
further items it raised were filed rather than decided.

**BLOCKING, fixed — a blocking validation error inside the advanced pane was invisible.** The
pre-4.2 panel compensated for exactly this hazard: `git show HEAD:app/templates/_panel_params.html`
line 77 carried `{% if not params.valid %}checked{% endif %}` on its collapse toggle, so the panel
**force-opened itself whenever the run was invalid** and an error could never hide behind a closed
box. The reshape replaced that collapse with a `<details>` plus three tabs — two new ways for an
input to be off-screen — and dropped the compensation. `applyPaneState` then made it worse by
re-applying the user's pre-submit display state, deliberately re-closing the pane over the errors the
response had just added.

Reproduced directly: a `POST /params` with `battery.max_charge_kw=-5` answers `X-Params-Valid: 0`,
the message "Must be greater than zero." is present in the DOM, and the `<details>` renders with no
`open` attribute — so the message is `display: none`. The config is not persisted (`result.blocking`
skips the save), and the results below still show figures computed from a config the user did not
submit. What the user sees is `✕ needs attention` and nothing else: no field, no message, no red
input. The review reproduced the same thing in Chromium in two sub-cases (collapsed pane, and an
error on a non-active tab).

**Why 41 route tests and 37 browser tests missed it.** Every assertion checks that a message is
RENDERED — a substring on the HTML — which stays true while it is hidden. No test submitted an
invalid value from a browser; the one browser test that drives the pane
(`test_the_advanced_pane_survives_a_parameter_swap`) drives only the valid path. This is the "quality
box that vanished exactly when needed" shape from 4.1, with the same trigger: a container that hides
content, where the hiding is correct in the normal case.

The fix is the pair the review identified, because either half alone leaves a gap:

- `params_view` gains `hidden_errors` (blocking messages for fields the pane draws, de-duplicated)
  and `error_tab` (which tab holds the first one). Both derive their field→tab map from
  `results_screen_view.ADVANCED_PATHS`, so the pane's contents stay described in one place.
- The template renders `hidden_errors` in an alert **outside** the pane, forces the `<details>`
  `open` when it is non-empty, and gives the offending tab the `checked` attribute instead of
  Battery. Reopening alone would still land on one tab while the error sat on another.
- `applyPaneState` detects the server's force-open (`[data-hidden-errors]`) and honours it rather
  than restoring the pre-submit state. A valid render never carries the marker, so the ordinary
  swap-preservation behaviour is untouched.

`hidden_errors` carries messages only, not field labels: the labels are translated literals beside
their inputs in the template, and copying them into Python would be a second set of msgids free to
drift. `error_tab` is what locates the error; the message then sits beside its own labelled input.

Five regression tests, four route and one browser. Confirmed discriminating by mutation: reverting
the template fails three of the four route tests, and reverting **both sides** — the template's
force-open and the `applyPaneState` guard — fails the browser test with the defect's own signature
(`assert False is True` on `details.open`). The fourth route test pins the opposite direction (a
valid submission must leave the pane closed) and correctly passes either way.

**minor, fixed — the tab strip's ARIA was an incomplete hybrid.** `role="tablist"` and three
`role="tab"`s, but no `role="tabpanel"`, no `aria-controls`, and no `aria-selected` — nothing could
update the last, since the selected state lives on an off-screen radio. `role="tab"` on a `<label>`
also overrides its native label role, so the annotation cost a screen reader the one thing the markup
had right. Keyboard operation was never affected (it rides the native radio group, verified in
Chromium). Removed rather than completed: unannotated, the radios announce as a labelled group of
three and the selection is real state rather than an attribute something must remember to maintain.

**minor, fixed — a test named for behaviour that does not exist.**
`test_results_stale_dims_the_previous_figures_rather_than_blanking_them` pinned the spinner and the
4xx contract, which its docstring said honestly, but nothing in the app dims anything. Renamed to
`test_a_refused_recompute_keeps_…` and the gap recorded in the docstring and in `followups.md` L1 —
a green test named for `RESULTS_STALE` dimming reads as coverage of a thing that was never built.
Confirmed **not** a 4.2 regression: the pre-restructure page had no dimming either, so §2′.6's
"still renders … dimmed" describes something that has never been true.

**Filed, not decided** — `followups.md` L1 (the dimming gap above), **L2** (`POST /w/{id}/edit` sets
`pricing_configured` on every successful save, not only when the Contract box was touched — a phase-3
decision that §2′.6's own rationale argues against, and which 4.2 merely made visible), and **L3**
(the known-latent contradictory state: a hand-crafted POST turning cost on while the flag is false).
L3 was confirmed latent — the rendered radios carry `disabled`, no browser path reaches it, and the
review found no other entrance. All three turn on what "the user has told us what they pay" should
mean, and L2 probably wants deciding first.

The review also confirmed clean, with reproductions: the `_panel_params.html` reshape lost nothing
(a rendered control-set diff across 12 config shapes shows only the two unnamed collapse checkboxes
correctly replaced by `<details>`); all three tabs' inputs stay in the DOM and in the form body; the
`sections` marker matches the drawn checkboxes across all 24 config shapes; the deletions leave no
live reference; the JS move resolves every id it looks up; and the pane-state fix survives validation
failures, rapid successive swaps, and a tab vanishing mid-swap.

## Current status

**Phase 4 complete.** All four screens of the restructure exist: the list (§2′.2), edit (§2′.4),
configure data (§2′.5) and results (§2′.6). The wizard walks edit → data → results and stops there,
which is where §2′.6 says it ends. Suite: **1136 passed, 2 skipped** (37 Playwright), up from 1087
at 4.1 and 1023 at phase 3.

Open, and none decided here:

- **A Blocked toggle is a client-side guard only.** A hand-crafted POST turns cost simulation on
  with `pricing_configured` still false, and the screen then renders a checked-but-Blocked toggle
  beside a drawn Pricing box — coherent (the user can set rates; they still have not committed a
  contract) but contradictory to read. The §2′.10 migration sets the flag from `simulate_cost`, so
  a migrated user never lands there; a hand-edited document could. Fixing it means deciding which
  of three things wins — force cost off, unblock the toggle, or hide the Pricing box — and that is
  a product call, not a bug fix. Left as it is, and stated. Confirmed latent by the review (the
  rendered radios carry `disabled`, and no other entrance exists); filed with its trade-offs as
  `followups.md` **L3**, alongside **L2**, which probably wants deciding first.
- **§2.3's collapsed summary line is no longer rendered anywhere.** `summary_line` still computes
  the whole run in one line and is still tested; §2′.6's wireframe replaced it with the pane's
  count and does not offer it a home. Worth revisiting if the count proves too thin.
- **A parameter edit still needs `[ Calculate → ]`.** §3.5 calls `PARAMS_CHANGED` "debounced" and
  the app has never implemented a debounce — only `setup.`-prefixed controls auto-submit. Confirmed
  unchanged from before 4.2 (the handler is byte-identical). Now more visible, because §2′.6's whole
  argument is that a capacity change and its effect are visible at once, and today that costs a
  click.
- **The same-site question** for the three parameter-writing routes remains open as phases 3 and 4.1
  left it: revisit all three together or not at all.
- **`followups.md` K1 and K2** from 4.1 are untouched.
