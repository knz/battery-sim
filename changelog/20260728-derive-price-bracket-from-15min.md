# Derive the §6.16 price bracket from 15-minute prices instead of asking the user

## Task Specification

User proposal, on the two optional `price_spot_min` / `price_spot_max` slots:

- Never ask the user for these two series.
- Derive the hourly min/max from the main spot series when that series has 15-minute
  resolution.
- Treat the bracket as absent when the spot series is natively hourly.

Discussion first; no code changes yet.

## Findings from the existing code and spec

- The bracket slots are declared in `app/domain/series_vocab.py:107-108`
  (`cost_only=True`, requirement `cost_optional`), rendered in the data roster
  (`app/templates/_data_roster.html:31`, gated on `cfg.simulate_cost`), and labelled in
  `app/data_view.py:68-69`.
- **Only the HA path can fill them today.** Both backend_load price sources explicitly
  refuse: `app/sources/entsoe.py:36-38` and `app/sources/energy_charts.py:38` state that
  a day-ahead series has one cleared price per interval and no spread. `tests/test_sources.py:63-65`
  asserts neither source is offered for the slot. So for any user on the preset sources
  the two rows are permanently unfillable — a roster row that can never be satisfied.
- `ingest.price_frame` (`app/domain/ingest.py:200-233`) carries `value_min`/`value_max`
  only when the HA `PriceRow`s bring them; `SeriesFrame` holds them
  (`app/domain/frames.py:79-80`) and `dataset.py:204-222` persists them.
- **§6.16 is not implemented in the simulation yet.** `app/domain/simframe.py:290` records
  spot_min/spot_max as out of scope for the current increment. So the plumbing exists up to
  the frame, and stops there.
- The ENTSO-E on-disk dataset already records a per-row `resolution_s`
  (`app/sources/entsoe_store.py`, 3600 before 2025-10-01 local, 900 after), but
  `ingest.price_frame` collapses it to one modal value per frame — a known, documented
  follow-up.

## Assessment of the proposal

The proposal is a strict improvement over the current design *for the preset-source path*,
and it makes the bracket reachable for the first time.

## Decisions (user, this session)

- **D1. Key the derivation to the simulation grid, not to "the hour".** Derive min/max over
  exactly the intervals `_resample_price_mean` collapses; emit nothing when it collapses
  nothing. A 15-min-meter run has grid 900 s, no collapse, and therefore no bracket — the
  spread inside a quarter-hour is unobservable.
- **D2. Straddling windows: derive per interval.** Where the source interval was already at
  grid resolution (hourly rows before 2025-10-01), min = max = mean and the bracket collapses
  naturally. No whole-window gating, no new flag. UI copy must say what fraction of the window
  actually carries a spread.
- **D3. Remove the two slots entirely.** `price_spot_min` / `price_spot_max` leave the
  vocabulary, the roster and the labels. min/max exist only as derived, in-computation
  quantities. The HA ingest path stops carrying its statistic's own min/max into the bracket;
  the derived quartet is the single definition, so the quantity does not vary by source.
- **D4. Ask for `supplier_settlement`.** Add the question to the *Pricing* parameters on the
  workspace edit screen (resolves the direction of open question §12, though the spec's
  default may stay as the initial value).
- **D5. Implement §6.16 and report it.** The bracket runs and its results surface in the UI —
  previously out of scope (`simframe.py:290`).

## Revised direction (after working the numbers)

Five- and seven-scenario synthetic runs (scratchpad `bracket_demo*.py`) reframed the goal.
Two candidate products were compared:

- **Narrowed-band dispatch** (user's first instinct): decide charging on the hour's max and
  discharging on its min, one sequential pass. Behaves as a pessimised savings estimate;
  never exceeded the mean-based figure across five price shapes, and collapses to today's
  behaviour when there is no intra-hour spread. Not adopted as the headline: it is a
  *different, more cautious battery*, not a better estimate of the actual one, and it
  understates badly (0.780 → 0.200 in one scenario).
- **The bracket** (§6.16 as specified): one dispatch, three cost evaluations. Endpoints are
  a true worst-case envelope but a poor uncertainty estimate — in three of seven scenarios
  the width exceeded the central estimate, and two went negative at the low end.

**Adopted: report the bracket's WIDTH as a caveat, not its endpoints as a range.**
Phrasing: "Your hourly data can't pin this down closer than ±€X (worst case)."

An ordering bug in the first two demo scripts is worth recording, since it nearly drove the
wrong conclusion: the split of min/max prices must be **by direction of flow** (imports
billed at min optimistic / max pessimistic; exports credited at max optimistic / min
pessimistic), NOT by "charging vs everything else". With the correct split
`low ≤ central ≤ high` holds by construction rather than by test.

## Decisions, revised

- **D5′ (supersedes D5).** Implement the bracket computation, but surface only the width, as
  a results caveat. Endpoints stay internal. This drops the §4.5 `price_bracket` result
  block, its null-when-off contract, and the low/central/high public fields.
- **D9.** Say "worst case" in the caveat text. A statistically typical error would be far
  narrower (errors across thousands of hours partially cancel), but the independence
  assumption needed to claim that is not supportable — household load has strong intra-hour
  structure and battery charging is deliberately timed. Not attempted.
- **D10.** Suppress the caveat entirely when `supplier_settlement == HOURLY`: the hourly
  price is then exactly what the user paid and there is no uncertainty to report.

## Current Status

Steps 1–6b done and committed (1–5 as bbe55f6, 6a as 05673f2, 6b as b37d7b2); the bracket is
computed and its width surfaced as a results caveat, the two slots and their vocabulary are gone,
and the copy has been through one adversarial review round. Step 7 (spec updates) is done in the
working tree, uncommitted.

**Remaining:**

- **Step 8 — the tests step 7 implies.** Step 7 is documentation only, so it adds no assertions
  of its own. The two spec/code disagreements it uncovered are both places where the spec was
  stale rather than the code wrong, so neither implies a test. What may still be worth pinning:
  fixture 10 has no test carrying that number, and the ordering invariant it names is asserted
  only under a descriptive test name in `tests/test_results_view.py`.

**Open, not blocking:** what the "ideal scenario" benchmarks should compute. The user asked to
reconsider this from first principles — the concept was introduced during the initial
specification work, not requested — and deferred the discussion until the savings estimate was
settled. Nothing in steps 1–5 depends on the answer.

**Deliberately not done.** The bracket's ENDPOINTS remain internal (D5′). The caveat reports a
width and does not attach it to the saving as a ± interval, for the reason recorded under step 5
F1: the width exceeds the saving on realistic fixtures, where a ± reading invites the conclusion
that the battery might lose money — a far stronger claim than a worst-case bound on the PRICING
supports.

### Step 7 — bring `specs/` in line with the shipped behaviour (done)

Documentation only. No file under `app/` or `tests/` was touched.

**User prompts this step.** "go ahead with step 7". Then, in answer to two questions: on the
§6.16 heading, the user first chose "Rename, fix all anchors", and on being shown that the
existing title ("Price bracketing under settlement/resolution mismatch") already describes the
shipped behaviour accurately, revised to **"Keep the title, rewrite the body"** — so the
heading and every inbound anchor
(`#616-price-bracketing-under-settlementresolution-mismatch`) are unchanged. On depth, the
user chose **"Behaviour only"**: state what is computed, when it applies, and what the user
sees; no internal construction (the ULP clamp, the sort mechanics, the per-interval envelope
machinery) in the spec.

**§6.16 rewritten, same length band.** 53 lines before, 61 after — the house's ~20-line
sections are not the norm in this file, and the neighbouring §6.13 and §6.17 are comparable.
The `price_bracket_runs` pseudocode block is gone rather than shrunk: it encoded the old
data-source premise (`if frame.spot_min is None`) and the old per-run corner structure
(`charge_px` / `discharge_px`), both of which the shipped code contradicts. The
`intra_hour_spread` standalone-indicator block went with it — nothing computes it, and the
"large spread with hourly settlement is an argument for switching supplier" insight it fed was
never built. Four things are now stated that the old text did not say: the min/max are derived
from the spot series' own spacing; the envelope is chosen per interval and why the uniform
corners do not work; the report is a WIDTH and not an interval, with the reason; and the suppression
conditions plus the sub-half-euro display suppression.

**§8.12 resolved as D4 actually resolved it.** The app asks — a radio pair in the Contract
box's Advanced pane — and the stored default stays hourly. Recorded together with the fact that
experiment X8's width distribution was *not* waited for, since the resolution was a judgement
rather than a measurement. X8 itself is rewritten: it is no longer decision-blocking, and the
open measurable is restated as whether the width is worth the caveat.

**Fixture 10's rationale was disproved and is corrected rather than deleted.** The claim
"violation means charge and discharge price arrays were swapped" does not survive step 3's
finding: with correct arrays the central saving can still fall outside the two evaluated
extremes, because the saving is a difference of bills and the feed-in floor's window-level
clamp breaks separability. One such window was witnessed (central −0.380 against −0.597 and
−0.460, roughly one in three hundred random windows). The fixture now says it pins the
containment, not any particular mechanism, and names the construction that produces the strict
case.

**Two claims in `specs/` that the code contradicted, found while checking rather than from the
task list.** Both corrected:

- `06-home-assistant-ingestion.md` §4.3 said the min and max "are fetched regardless, because
  they cost nothing extra in the same request". `ha_fetch.js:758` requests `types: ["mean"]`
  for price slots — verified in the shipped file, not inferred. The §4.3 WS payload sketch
  (`types: ["sum"] | ["mean","min","max"]`) was wrong for the same reason and is narrowed.
- `16-validation-harness.md` fixture 19 and `07-internal-representation.md` §4.5 both listed
  `price_bracket` as a result-object field that is `null` without cost simulation. D5′ dropped
  that block; the bracket never reaches the result JSON in either mode. §4.5's block is replaced
  by a comment recording the internal object's actual shape (`width_eur`,
  `bracketed_fraction`, `saved_low`/`saved_central`/`saved_high`), read off `PriceBracket` in
  `app/results_view.py`.

**`supplier_settlement` was missing from the screen wireframes** — confirmed by grep, it
appeared only in appendix A and in the open question. Added as a Settlement sub-box in the
Advanced pane of §2′.4's Contract box, matching `workspace_edit.html`'s placement and wording
("Your supplier bills" / "Hourly average" / "Every 15 minutes", with the info line saying
supplier-not-market). §2′.4 gains a short prose subsection saying why the wording asks about
the invoice. §2.3 gets a one-line pointer to §2′.4 instead of a drawn control — see the review
round below for why.

**Footnote renumbering in `05-data-formats.md`.** Removing the two slot rows orphaned footnote
5 (the cost-only gate). Rather than leave a gap, ⁶ (the existing-battery slots) was renumbered
to ⁵ — three call sites, all in that file, no inbound references to footnote numbers found
elsewhere.

**Files changed (18 under `specs/`, plus this changelog).**

| File | Change |
| --- | --- |
| `14-diagnostics.md` | §6.16 body rewritten; availability-table row and two intro sentences realigned |
| `17-open-questions.md` | §8.12 marked RESOLVED with the resolution and its basis |
| `07-internal-representation.md` | `spot_min`/`spot_max` no longer nullable and documented as derived; §4.5's `price_bracket` block replaced by a comment; three other `price_bracket` mentions |
| `05-data-formats.md` | two slot rows and footnote 5 removed, ⁶→⁵, `price_spot` row notes the derivation |
| `02-ux-wireframes.md` | two roster wireframes and both legends; two slot-description passages; caveat scope and its bracket gate; a one-line pointer from §2.3 to §2′.4 for the settlement question |
| `appendix-a-defaults.md` | `supplier_settlement` dropped from the "open questions" list, count six → five |
| `20-workspaces-ux.md` | `◒` out of the §2′.5 legend line; §2′.7's cross-screen gating consequence rewritten; Settlement box + prose added to §2′.4 |
| `04-state-machine.md` | slot re-derivation example no longer cites the removed slots |
| `16-validation-harness.md` | fixture 10 rationale corrected; fixture 19's `price_bracket` reference removed |
| `06-home-assistant-ingestion.md` | preset-source paragraph; §4.3 spot-price bullet; the request line; the WS payload sketch; the file header's "min/max columns" |
| `implementation-progress.md` | §6.16 and the settlement question moved to built; fixture-10 caveat added |
| `19-prototype-experiments.md` | X8 rewritten as non-blocking |
| `01-product-brief.md`, `README.md`, `appendix-b-glossary.md`, `15-data-quality-and-limits.md`, `09-ingest-algorithms.md`, `10-pricing.md` | one- to three-line realignments |

**Checked and deliberately not changed.**
`18-dutch-electricity-background.md`'s two §6.16 references are about MTU15 and the energy-tax
bracket structure (an unrelated sense of "bracket") and need nothing. `02-ux-wireframes.md`'s
caveats paragraph was already correct about the bracket appearing only with cost simulation;
only its scope wording ("the euro figure" → "the saving") and the two extra gates were added.

**Review round on step 7's own edits.** A review pass over the uncommitted `specs/` diff found
ten problems, all of them in the new text rather than in the code. All were corrected;
documentation only, nothing under `app/` or `tests/` was touched.

- *A wireframe drawing a control the screen does not have.* The Settlement box had been added
  to §2.3's Pricing wireframe as well as §2′.4's Contract box. But commit 667047c removed the
  Pricing box from that screen — `_panel_params.html` says so in its header comment, and
  `supplier_settlement` appears in no template but `workspace_edit.html`. The §2.3 drawing also
  placed the box first inside Advanced with Feed-in outside it, matching nothing shipped. It is
  removed and replaced by a one-line pointer to §2′.4, whose placement does match
  `workspace_edit.html`. The trailing note's field list is back to its committed wording for the
  same reason.
- *Radio labels transcribed loosely.* Both wireframes rendered the options as "the hourly
  average" / "every 15 minutes". The shipped msgids are "Hourly average" and "Every 15 minutes"
  (`workspace_edit_view.py`, and the same strings in both catalogs). §2′.4 now carries them
  verbatim.
- *The suppression conditions were miscounted.* §6.16 said three; `_price_bracket` has four
  `return None` guards — cost-off, hourly settlement, no priced interval anywhere in the window,
  and no interval carrying a spread. The all-unpriced case had been folded into the no-spread one
  in the prose but is a separate guard with a separate reason, and an all-unpriced window
  producing no bracket is user-visible. Corrected to four, with the display suppression becoming
  the fifth condition.
- *The display boundary was off by the endpoint.* §6.16 said a width "under half a euro" renders
  "€ 0". The comparison is `> WATERFALL_DISPLAY_EPS_EUR`, so exactly €0.50 is suppressed too —
  the code comment records why (half-to-even rounding prints "€ 0" at 0.5).
- *The gate was described as a resolution test, and it is not.* Three sites (§6.16's availability
  row, §15's check-8 note, §2.3's caveat note) said the bracket applies when the spot series is
  "finer than the grid". The code tests `count_nonzero(spread > 0)`, so a nominally 15-minute
  series carrying identical values within each hour is finer than the grid and still yields no
  bracket. All three now say at least one interval's native prices differ. §6.16's own body was
  already right about this.
- *"Billed three times" overstated the arithmetic.* `_price_bracket` performs two cost
  evaluations; the central saving is passed in from the main run (`results_view.py:1598`), which
  is what guarantees the band contains the figure on screen rather than a re-derivation of it.
  Reworded.
- *`appendix-a-defaults.md` went stale.* Its "six of these defaults **are** themselves open
  questions" list still named `supplier_settlement`, which this change marks RESOLVED. Dropped
  from the list, count to five. An earlier draft of this entry claimed that list needed nothing;
  that was wrong. The other four entries (§8.3, §8.13, §8.14, §8.16, §8.18) were checked and are
  still open.
- *Fixture 10 had grown past the house length.* Its corrected rationale ran ~13 lines carrying
  sort mechanics and per-interval envelope detail, where its neighbours run two to three. The
  substance is kept — the old "a violation means the arrays were swapped" claim is genuinely
  false — but compressed, and the construction detail dropped, consistent with the behaviour-only
  depth the user set for §6.16.
- *§8.12's resolution and X8 were not talking to each other.* §8.12 stated the resolution as
  settled while X8's restated measurable is whether the control earns its place on the edit
  screen. One sentence now says at the resolution that X8 can unmake it.
- *File count.* The table said 16; the diff touches 18 spec files. Corrected, and
  `appendix-a-defaults.md` added as a row.

Two smaller edits went with it: X8's "some synthetic scenarios" now names the number (three of
seven, and €2.46 against €0.45 on the standard fixture — both verified against the code comments
at `results_view.py:1925-1930` and the tests that carry them), and §2′.4's "It is **not
decorative**" was dropped, since the sentence after it makes the point on its own.

**Not verified.** The repo's cross-file anchors were spot-checked against existing usage
(`#24-edit-workspace` is already used from `02-ux-wireframes.md`) rather than validated
mechanically; a naive link checker reported ~155 pre-existing mismatches across `specs/`, which
is a property of its normalisation rather than a finding about these edits, and chasing it was
out of scope.

### Step 6b — remove the two bracket SLOTS and the cost-only slot vocabulary (D3, D6) (done)

The change the thread started from. Steps 1–5 built the replacement (the bracket is derived from
`price_spot`'s own interval spacing and reported as a width), so the slots go without losing the
capability.

**D6 verified, not assumed.** A scan of `SERIES_SLOTS` confirms `price_spot_min` and
`price_spot_max` were the only entries carrying `cost_only=True` or `requirement="cost_optional"`.
So D6 is a mechanical consequence of D3, and the two had to be done in one pass — see the mutant
table below, where splitting them is exactly what would have left an unreachable template branch.

**Removed:**

- `app/domain/series_vocab.py`: both `SlotSpec` entries; `SlotSpec.cost_only`; `"cost_optional"`
  from the `Requirement` Literal. The remaining price slot carries a comment saying the bracket is
  derived from it rather than asked for.
- `app/data_view.py`: the two `ROLE_LABEL` entries and `"cost_only"` from the roster row dict.
- `app/sample_data.py`: the two static mapping rows and the comments describing the gate.
- `app/templates/_data_roster.html`: `row.cost_only` out of `row_hidden`, the `data-cost-only`
  attribute, the `◒` marker branch, and the legend's `◒` clause. Header comment realigned.
- `app/static/ha_fetch.js`: the comment in `applySetupGating` explaining why it does not act on
  `data-cost-only`. No behavioural code — the attribute was never read.
- `app/sources/entsoe.py`, `app/sources/energy_charts.py`: their comments named the removed slots.
  Both `available_for` are allowlists keyed on `price_spot`, so nothing functional changed; the
  reworded comments now say there is no separate bracket slot at all.
- `tests/test_sources.py`: `test_bracket_slot_offers_ha_only` deleted (it indexed
  `SLOT_BY_NAME["price_spot_min"]`). Its siblings at the same allowlist still cover both branches.
- `app/main.py`: `simulate_cost` dropped from the configure-data route's `ctx["cfg"]`. **Found by
  review, missed by every grep in this pass** — the comment justifying the key spelled neither
  `cost_only` nor `price_spot_min`, and it was the only recorded reason for passing it: "the
  roster's two price-bracketing rows are gated on it". That mechanism is gone. Verified before
  deleting rather than assumed, which mattered: Jinja's default `Undefined` is silent, so a missed
  consumer would have rendered falsy instead of raising and the suite would have stayed green. A
  runtime probe wrapped `ctx["cfg"]` in a dict that records every key lookup and rendered the real
  page through the route — `['has_battery', 'has_pv']`, nothing else. The results route builds its
  own `ctx["cfg"]` and still carries `simulate_cost`, which is where the toggle lives (§2′.6).

**The orphan-frame problem, measured and handled READ-side only.** A returning user's dataset still
has `price_spot_min.npz` / `price_spot_max.npz` and their `series_meta` rows.
`dataset._restore_frames` reads every row BY NAME with no vocabulary check, so those frames loaded
into `LoadedDataset.frames` after the slots were gone — invisible in the roster (built from
`SERIES_SLOTS`) but present. Reproduced on the real gitignored dataset at `data/local/series/`
(read-only): eight frames restored before the filter, six after, and `normalize.grid_report` listed
`price_spot_min` and `price_spot_max` as their own granularity rows in the panel-① table. That is
the phantom-row half, it is real, and the filter fixes it.

**Correction — the `price_granularity_lost` half of that claim was wrong as first written.** An
earlier draft of this entry said the orphans also caused `normalize.price_granularity_lost` to
return `{'lost': True, 'native_resolution_s': 900}` on the real dataset. It does return that — but
it returns it *after* the filter too, on six frames. The real `price_spot` in that dataset is itself
natively 900 s against an hourly grid, so the diagnostic fires legitimately on its own account and
the orphans changed nothing about it. The measurement was taken and read as if it discriminated,
which it did not.

The mechanism itself is real, and is stated here as what it is — a constructed case, not a measured
one. `price_granularity_lost` filters on `kind == "price"` across all frames and never on the
vocabulary, so on a dataset whose `price_spot` is natively HOURLY, a 900 s orphan alone flips it:
verified on hand-built frames, `{'lost': False, None}` for the hourly `price_spot` alone versus
`{'lost': True, 900}` with the orphan added. No such dataset was to hand, so this remains a
hypothesis about a reachable state rather than an observed defect.

`choose_grid` / `effective_window` filter on energy series so the grid was unaffected — luck, not
design.

**Decision: a vocabulary filter in `_restore_frames`, and NO deletion of rows or files here.**
Three reasons, and the alternatives were real:

- The vocabulary is already what ingest validates against, so "loaded" and "known" should not
  diverge in the first place. Filtering at the one place that turns rows into frames fixes every
  consumer at once, rather than teaching `grid_report` and `price_granularity_lost` — and whatever
  reads frames next — each to check separately.
- A one-shot cleanup in `_migrate` was considered and rejected for THIS commit. `_migrate` only
  ever ADDs columns and there is no version field on the dataset store, so a delete there is a new
  kind of operation in a function whose contract is "idempotent forward-compatibility". More to the
  point it is destructive and has a different failure mode from a vocabulary change: if the
  filtering turns out to be wrong, nothing is lost; if a delete is wrong, the user's data is gone.
- The filter also covers the general case (any future slot removal), which a cleanup keyed on two
  hard-coded names does not.

The cleanup is therefore **deliberately left out and recommended as a separate commit** if it is
wanted at all. With the filter in place the orphan files are inert — they cost disk and nothing
else — so the case for deleting them is housekeeping rather than correctness.

**Catalogs.** Four msgids left the active catalogs through the documented Babel workflow
(`--no-fuzzy-matching`, `--no-location`, exit codes checked on all three commands): "Spot price
(min)", "Spot price (max)", "offered if you simulate costs", and the old roster legend. The legend
is a REWORD rather than a deletion — it named `◒` and intra-hour bracketing — so it comes back as a
new msgid with the clause dropped, and the old one is retained as a `#~` obsolete alongside the
other three. The EN msgstr for the legend was EMPTY before this change (a pre-existing gap that
made the English page fall back to the msgid); the replacement is filled rather than reproducing
it. Dutch translated.

The hand-filled msgstrs were verified to reproduce Babel's own wrapping: re-running `pybabel
update` over the edited catalogs produced byte-identical files. One piece of incidental churn was
kept — Babel re-wrapped the Dutch pricing-uncertainty caveat msgstr (identical text, different
line breaks), the same normalisation step 5 recorded. No other unrelated churn appeared; the `.pot`
diff is exactly the four msgids plus the timestamp.

**Tests added** — four in `tests/test_workspace_data.py` (the vocabulary group) plus one for the
orphan case:

- `test_the_bracket_slots_are_out_of_the_vocabulary` (parametrised): absent from `SLOT_BY_NAME`,
  `SERIES_SLOTS`, and rejected by `is_known_series` — which is the ingest gate, not only the roster.
- `test_the_slot_vocabulary_has_exactly_one_price_slot`.
- `test_the_cost_only_slot_vocabulary_is_gone` (D6): the field is off `SlotSpec` and no slot
  carries the requirement level.
- `test_the_roster_renders_no_row_for_the_removed_bracket_slots` — **the one that actually pins
  D3.** The rest assert the view-model; this asserts the SERVED MARKUP. It matters here more than
  usual because a `cost_only` row was rendered-and-hidden rather than omitted, so a leftover would
  have shipped as invisible markup that `applySetupGating` could un-hide. It carries a positive
  assertion (`data-slot-row="price_spot"` present) so the absences cannot pass vacuously.
- `test_a_saved_bracket_slot_series_is_not_restored_after_the_slots_were_removed` — forges the
  returning-user state (a real `.npz` plus a `series_meta` row via `dataset.connect()`), then reads
  it back through the shipped `load_latest` and asserts both diagnostics are clean and the file is
  still on disk.

**Mutants** (each run alone against `test_workspace_data.py`, `test_sources.py`, `test_slot_load.py`,
`test_i18n.py`):

| Mutant | Result |
| --- | --- |
| `price_spot_min` re-added to `SERIES_SLOTS` | KILLED (3 tests) |
| both bracket slots re-added | KILLED (4 tests) |
| `SlotSpec.cost_only` field re-added | KILLED (the D6 test) |
| `"cost_optional"` back in the `Requirement` Literal | **SURVIVED — equivalent** |
| template's `◒` marker branch re-added, alone | SURVIVED |
| template's `◒` marker branch re-added **+ one `sample_data.py` row set to `"cost_optional"`** | KILLED (the rendered-markup test) |
| template's legend `◒` clause re-added | KILLED (the rendered-markup test) |
| template emits `data-cost-only="1"` on every row | KILLED (the rendered-markup test) |
| the vocabulary filter deleted from `_restore_frames` | KILLED (the orphan test) |
| the vocabulary filter inverted to a no-op | KILLED (the orphan test) |
| the two `ROLE_LABEL` entries re-added, alone | SURVIVED — dead dict entries |

**Correction — the "the `◒` branch is unreachable" claim was wrong, and it is the more useful
finding.** An earlier draft of this entry argued that mutant was equivalent, because no entry in
`SERIES_SLOTS` carries `requirement == "cost_optional"` any more. That reasoning covers only one of
the template's TWO producers of `row.req`:

- `data_view.panel_data_from` derives `req` from `slot.requirement`, so it is vocabulary-driven and
  the argument holds there;
- `sample_data._panel_data()` supplies `req` as HARDCODED STRING LITERALS, and
  `app/main.py` renders the configure-data screen from `sample_view()` whenever no dataset loads,
  overwriting `ctx["data"]` only when one does. Both mappings are therefore live on that route.

Demonstrated rather than argued: re-adding the branch AND setting one `sample_data.py` row's `req`
to `"cost_optional"` fails `test_the_roster_renders_no_row_for_the_removed_bracket_slots`
(1 failed / 95 passed in that file). The branch was reachable — via a hand-written string in a
second file — so it was dead code kept alive by an argument that held for only one producer, not
dead code that could not be reached at all. Removing it is still correct; the reason is different
and stronger. A future contributor hand-adding a `req` value in `sample_data.py` gets no protection
from the vocabulary argument, which is exactly why the rendered-markup assertion (and not the
view-model ones) is what pins this.

The same caveat applies to the `ROLE_LABEL` survivor: equivalent as measured, but its reachability
is controlled from elsewhere too. `ROLE_LABEL` is consulted per `SERIES_SLOTS` entry, so an entry
for a name outside the vocabulary is never looked up — restore the slot as well and it IS killed
("both bracket slots re-added" above). "Equivalent" here means "equivalent given the rest of the
tree as it stands", not "equivalent by construction".

The `Requirement` Literal survivor IS genuinely equivalent: it is a type annotation with no runtime
enforcement and nothing calls `get_args` on it, so restoring a member nothing takes cannot change
behaviour.

**On the D3+D6 coupling.** The original claim — that splitting D6 off would leave an unreachable
template branch — needs the same correction. It would have left a branch that is reachable but
unreachable-in-practice via the vocabulary, and reachable in fact via `sample_data.py`. The
argument for doing them in one pass stands, but the hazard is the more ordinary one: a marker
branch and a legend clause describing a requirement level no slot claims, kept honest only by
whoever next edits the hand-written sample table.

Suite: 1269 passed, 2 skipped (1264 before: −1 deleted, +6 new — five in the vocabulary group,
counting the parametrised one twice, plus the orphan-restore test).

**A false failure worth recording, because it looked exactly like a real order-dependency.** One
full-suite run reported `test_a_saved_bracket_slot_series_is_not_restored_after_the_slots_were_removed`
failing with the orphan present in `loaded.frames`, while the same test passed in isolation and
under every pairing tried. The cause was operator error, not the code: that run had been launched
in the BACKGROUND and the mutation harness was then run against the same working tree, so mutant B
(both slots restored to `SERIES_SLOTS`) was live in the tree while the suite was still executing.
File mtimes confirmed it. Re-run serially: 1269 passed, twice. The lesson for the next mutation
round is procedural — a background suite run and a mutation harness must never share a working
tree, and a surprising failure should have its timestamps checked before it is debugged as an
interaction.

Not done here: the spec updates (step 7). `specs/05-data-formats.md:32-33`,
`04-state-machine.md:109`, `06-home-assistant-ingestion.md:111-112` and `20-workspaces-ux.md:679`
still describe the two slots.

### Step 6a — remove `SeriesFrame.value_min` / `value_max` and the chain that fed them (done)

D7's half of step 6. The `price_spot_min` / `price_spot_max` SLOTS (D3, D6) are a separate
removal and are not touched here — `series_vocab.py`, `data_view.py`, `sample_data.py` and
`_data_roster.html` are unchanged.

**Verified, not assumed: nothing read the fields.** A grep across the working tree found
`value_min` / `value_max` only in the write/read pair in `dataset.py` and in two tests.
`simframe.py` does not mention them; `_spot_on_grid` derives its bounds from `frame.values`
alone (step 1). So the removal has no user-visible effect, and a full `results_from` run over the
real local dataset before and after produces the same view-model.

**Removed:**

- `app/domain/frames.py`: the two fields, their `__post_init__` length check, and the docstring
  paragraph, replaced by a sentence saying where the bracket actually comes from now.
- `app/domain/ingest.py`: `PriceRow.min` / `.max`, and `price_frame`'s `have_bracket` / `vmin` /
  `vmax` construction and the two constructor arguments. Module and function docstrings updated.
- `app/dataset.py`: the conditional npz write and read.
- `app/sources/entsoe.py`, `app/sources/energy_charts.py`: the `min=None, max=None` call-site
  arguments. Their comments explaining why they cannot fill the bracket slots cited a mechanism
  that no longer exists ("an HA measurement statistic's own min/max"); the claim about the SLOTS
  stands, so only the parenthetical rationale changed — the day-ahead series has one cleared price
  per interval, which is a property of the source and not of how HA reports.

**The wire format narrowed too (user instruction).** `[start_ms, mean, min, max]` →
`[start_ms, mean]`, and `ha_fetch.js` now asks HA for `types: ["mean"]` instead of
`["mean","min","max"]`. Both ends changed in this pass, and the module comment in `ingest_ws.py`
that documents the protocol was updated with them.

Keeping browser and backend in agreement, two ways:

- The parser is **tolerant of the old shape**, deliberately. It reads `r[0]` and `r[1]` and
  ignores anything past them, so a browser holding a cached copy of the previous `ha_fetch.js`
  still ingests correctly — it just wastes the two columns it fetched. A stricter parser was tried
  as a mutant and rejected: the failure mode is a fetch that errors out for a user who has done
  nothing wrong and cannot tell why.
- A **static scrape test** (`test_the_browser_asks_home_assistant_for_the_mean_only`) pins the
  two JS lines that build a price row. Nothing else in the suite executes `ha_fetch.js`, so
  without it the browser half could drift back — the same class of unasserted glue that step 2's
  review finding hit in the template.

**Review findings on that scrape test, fixed.** Its first version had two defects, both of the
kind a static scrape is prone to and worth naming so the next one avoids them.

- *Brittle to formatting.* The regexes matched source text literally, including quote style and
  spacing, so `['mean']` or `[ "mean" ]` — a Prettier run, or a quote-style normalisation, neither
  with any behavioural content — failed the test. That is worse than no test: whoever hits the
  false positive loosens or deletes it, and the real protection goes with it. Both regexes now
  tolerate quote style and inner whitespace. The `nz(r.min)` / `nz(r.max)` check stays a plain
  substring, because there is no innocent spelling of that.
- *An assertion that asserted nothing.* A first line bound a `payload.types` match and never used
  it — and being unscoped and end-anchored it matched the ENERGY branch's `["sum"]` two lines down,
  so it would have passed with the price branch deleted outright. Removed, and the surviving regex
  is scoped to `slot.kind === "price"` so the deletion case is caught. That case is now a mutant in
  its own right.

Re-verified after loosening: three formatting-only mutants (single quotes with a brace block;
spaces inside the array literal; a Prettier-style row-packing rewrite) all PASS, while mutants C
(request `["mean","min","max"]` again), D (pack `min`/`max` again) and E (delete the price branch)
all still FAIL. The loosening cost no coverage.

**Backward compatibility, verified by running rather than by reasoning.** `_load_frame` now names
only three keys, and `np.load` returns an `NpzFile` whose extra members are simply not looked up.
Two checks:

- A test (`test_a_price_npz_written_with_the_old_bracket_arrays_still_loads`) writes a
  five-array `.npz` into the real per-workspace path with `np.savez`, exactly as the old writer
  did, then reads it back through the shipped `dataset.load_latest`.
- The real gitignored dataset at `data/local/series/` was loaded (read-only). Its
  `price_spot_min.npz` and `price_spot_max.npz` DO carry the `value_min`/`value_max` arrays on
  disk; all eight frames load, and `results_from` over them completes. Worth recording since it
  corrects an expectation in the plan: the leftover arrays are on the two BRACKET-SLOT files, not
  on `price_spot.npz`, which on this machine was written by the Energy-Charts path that never
  supplied a bracket.

**Tests.** Two deleted assertions became one replacement rather than a straight deletion:
`test_price_frame_carries_the_mean_and_nothing_else` keeps the mean/kind coverage the old
`test_price_frame_carries_mean_and_bracket` also had, and adds `hasattr` assertions so the
removal itself is pinned. `tests/test_ha_live.py`'s bracket test (in the skipped live-HA suite,
so it would not have failed CI) was likewise narrowed to a mean-only price fetch rather than
dropped. `tests/test_ingest_ws.py`'s main fixture moved to two-element price rows, with the
four-element shape kept alive in the dedicated compatibility test above.

**Mutants, all seven killed** (each run alone against the relevant test files):

| Mutant | Killed by |
| --- | --- |
| `_load_frame` asserts the npz has exactly the three keys | the old-npz compatibility test |
| WS parser rejects a price row whose length is not 2 | the four-element-shape test |
| `ha_fetch.js` requests `["mean","min","max"]` again | the static scrape test |
| `ha_fetch.js` packs `[start, mean, min, max]` again | the static scrape test |
| `ha_fetch.js` deletes the price branch, leaving only `["sum"]` | the static scrape test |
| `SeriesFrame.value_min` / `value_max` reintroduced | all three new tests |
| `PriceRow.min` / `.max` reintroduced | `test_price_frame_carries_the_mean_and_nothing_else` ALONE |
| `entsoe.py` passes `min=None, max=None` again | 3 tests in `test_sources.py` (TypeError) |
| `energy_charts.py` passes `min=None, max=None` again | 8 tests across `test_ingest_ws.py`, `test_slot_load.py`, `test_sources.py` |

The first two are the ones worth having: they pin the two behaviours a reader would otherwise have
to take on trust — that an old file loads and an old browser still works — neither of which any
pre-existing test covered.

The `PriceRow` row is recorded as single-killer deliberately. The WS tests do NOT catch it, because
re-adding two defaulted fields nobody passes changes no WS behaviour — the mutant is arguably
equivalent there, and only the explicit `hasattr` assertion in the ingest test distinguishes it. An
earlier draft of this table credited the WS tests as well; that was wrong, and the correction is
recorded rather than silently applied, since "two tests cover this" is exactly the kind of claim a
later reader would rely on without re-running it.

Suite: 1264 passed, 2 skipped (1262 before: −2 deleted, +1 replacement, +3 new).

Not done here: the D3/D6 slot removal, and the spec updates (step 7). `specs/` still describes a
user-supplied bracket and an HA statistic's min/max riding on the frame.

### Step 1 — derive per-grid-interval min/max in the SimulationFrame (done)

- `app/domain/simframe.py`: `_resample_price_mean` renamed to `_resample_price_stats` and
  extended to return `(mean, vmin, vmax)` from the same bucketing pass, using `np.minimum.at` /
  `np.maximum.at` over accumulators seeded at ±inf and overwritten with NaN where `counts == 0`.
  The mean's arithmetic is untouched.
- `_spot_on_grid` now returns `(spot, spot_min, spot_max, extrapolated)`. The forward-fill path
  returns copies of `spot` for both bounds (a held price has no observed spread — D2's natural
  collapse), and the `frame is None` path returns three independent all-NaN arrays.
- `SimulationFrame` gains `spot_min` / `spot_max` as real fields; they leave the "not built here"
  list in both the module and the class docstring, and the `_SPOT_SLOT` comment now says the
  bounds are DERIVED rather than pointing at the (soon-removed) `price_spot_min`/`_max` slots.
- Computed unconditionally per D8: no `simulate_cost` branch and no config gate.
- `tests/test_simulate.py`'s hand-built frame helper fills both bounds from `spot`, matching what
  the builder produces for a single-point interval.
- `tests/test_simframe.py`: five new tests — the four-quarter bracket, the single-point collapse,
  NaN exactly where `spot` is NaN (both the partial-coverage and the no-slot branch), NaN native
  values excluded from the extrema, and the held path giving `min == max == spot`.

**Review finding, fixed.** The claim that `spot_min <= spot <= spot_max` "holds by construction"
was false as first written. The mean is a sequential `np.add.at` accumulation, so a bucket of
three IDENTICAL prices yields `x + x + x` whose quotient by 3 lands one ULP *above* x — the mean
then exceeds the max of its own inputs. Divisors that are powers of two are exact, so a full
four-quarter hour is safe while a three-quarter one is not, and three-point buckets are the
ordinary shape of an hour with one gap quarter (or the DST spring-forward hour). Fixed by clamping
`vmin`/`vmax` around the mean before returning, which makes the documented invariant literally
true at negligible cost. Magnitude was ~1e-16 EUR/kWh — immaterial as a price, but the width
computation in step 3 is entitled to treat the ordering as an invariant rather than clamping
defensively at every use.

Two tests were added beyond the original five: the ULP case above (mutation-checked — it fails
when the clamp is removed, unlike a first version of the test built on random jitter, which passed
either way and was therefore worthless), and negative prices, which the ±inf sentinel choice exists
to handle and which nothing else exercised.

Note for later steps: only the bucket path can produce a non-zero width, so a run whose price is
natively hourly reports zero width everywhere. That is the intended D1/D2 behaviour, but it means
the UI copy must distinguish "no uncertainty" from "uncertainty not measurable", and the fraction
of the window that carries a spread has to be computed from `spot_max - spot_min` rather than
assumed from the price frame's modal `resolution_s`.

### Step 2 — `supplier_settlement` config field + workspace-edit radio (done)

Captures D4's question and D10's suppression condition in the parameter set, ahead of the
caveat that will read it.

- `app/domain/simconfig.py`: new `SupplierSettlement` enum (HOURLY / QUARTER_HOURLY) next to
  `TlkMode`; `PricingConfig.supplier_settlement` defaulting to HOURLY (appendix A); a fourth
  entry in `validate()`'s enum-selector loop, inside the `if self.simulate_cost:` block since
  the field only matters for cost. Nothing added to `_force_invariants` — the field is
  retained, never cleared, like the rest of `PricingConfig`.
- Rewrote the "not modelled" note in `PricingConfig`'s docstring: it had grouped
  `feedin_floor_period` and `supplier_settlement` as fields no code reads. Only the
  `feedin_floor_period` half still holds.
- `app/simconfig_store.py`: symmetric write (`to_dict`) and read (`_enum_or_default`). No
  `_VERSION` bump and no migration — an absent key already falls back to the appendix-A
  default field by field, which is the group's standing forward-compatibility rule.
- `app/params_view.py`: form parsing via the existing `_enum_or_keep` selector pattern. Not in
  the numeric FIELDS table (numbers only); no `_section()` gate, since a radio group with a
  checked default always submits.
- `app/workspace_edit_view.py` + `app/templates/workspace_edit.html`: a `settlements` list of
  {key, label, selected} and a radio pair in the Contract box's Advanced pane, beside the
  other pricing selectors. No "pending" entries — both members are real. Help line says the
  question is how the SUPPLIER bills, not how the market settles.
- Catalog entries added for the new msgids (nl translated, en identity), `.mo` recompiled.

**Review finding, fixed.** The template control had NO test coverage: deleting the entire
settlement box from `workspace_edit.html` left all 1232 tests green. Every test stopped either at
`edit_view()`'s dict or at `parse_form()`'s dict, so the template between them was unasserted —
and the template is the only place a user can ever answer the question, so losing it would
silently make the caveat unfireable while the config field, store and parser all kept working.
Added `test_the_settlement_question_is_actually_on_the_page` (both options present, enabled, and
`hourly` pre-checked) and `test_the_settlement_choice_round_trips` (POST both directions through
the real route), matching the convention the contract radio already follows — whose own docstring
records having had this exact defect. Mutation-checked: renaming the field in the template now
fails the suite. Also added the field to `_form()`, whose docstring promises "every input on the
screen is present".

Corrected an overstatement in `params_view.py`: the `in form` guard was described as needed for
partial POSTs, but `_enum_or_keep` already returns the current value on a `None` lookup, so the
guard is redundant and kept only for symmetry with the three enum blocks above it.

Rationale for the labels: "Hourly average" / "Every 15 minutes" describes the billing period
the user can read off their contract, rather than naming EPEX's settlement change, which is
not what the answer depends on.

### Step 3 — compute the pricing-uncertainty width (done)

The number D5′ reports. One dispatch, three cost evaluations; nothing re-runs the simulation and
nothing feeds back into `run_all`, so fixture 18 stays structural.

- `app/results_view.py`: a frozen `PriceBracket` dataclass (`width_eur`, `bracketed_fraction`,
  and the internal `saved_low`/`saved_central`/`saved_high`) and `_price_bracket(cfg, frame, runs,
  saved_central)`, called inside the existing `if cfg.simulate_cost:` block right after the
  monthly euro series. Exposed as a TOP-LEVEL `price_bracket` key on the view-model — deliberately
  not a `cost.price_bracket` block, which D5′ dropped. The template does not read it yet.
- The split is by DIRECTION OF FLOW: imports from one spot vector, exports from the other. Each
  extreme is therefore assembled from TWO `price_curves` calls, taking `p_import` from one set and
  `p_export_net`/`compensation` from the other. Both extremes are derived from the extreme SPOT and
  run through the full §6.5 construction, rather than bracketing the finished prices, so the
  arithmetic stays correct if §6.5 ever gains a non-affine term.
- Gates, all three required: `cfg.simulate_cost`; `supplier_settlement == QUARTER_HOURLY` (D10,
  compared against the enum member); and at least one interval with `spot_max > spot_min`. Returns
  `None` rather than a zero width in every suppressed case — the caveat must be able to tell "no
  width to state" from "the width is zero", which a float cannot express.
- NaN handling is an explicit `count_nonzero(~isnan(spread))` rather than `nanmax(spread) > 0`. The
  latter is right by IEEE accident on an all-NaN window (`NaN > 0` is False) and warns; the count
  also gives `bracketed_fraction` a denominator that excludes unpriced intervals.

**Finding: the prompt's premise that `saved_low <= saved_central <= saved_high` "holds by
construction" is false for the SAVING.** It holds for each BILL — the two price vectors do bracket
`cost(A)` and `cost(C)` individually. But the saving is
`Σ(impA − impC)·p_import − Σ(expA − expC)·p_export_net`, linear over a two-dimensional box of price
vectors with four corners, and only two are evaluated. On a window where the battery net-imports
more than the baseline (`impA − impC < 0`, i.e. it grid-charges), a different corner is the extreme
of the difference and the central figure can fall outside the evaluated pair. Witnessed, not
argued: a random search over price and flow shapes hit it roughly once in three hundred, and one
such window is pinned as a fixture (central −0.380 against extremes −0.597 and −0.460). Fixed by
sorting all three evaluations, `saved_central` included — which costs nothing and makes the
invariant unconditional. Had it been left to construction, the failure mode would have been a
caveat printing a band that does not contain the figure beside it, on a small minority of windows.

- `tests/test_results_view.py`: thirteen tests. A quarter-hourly price fixture (15-min price frame
  against hourly energy frames, so `simulation_frame` collapses four points per grid interval)
  covers the ordinary case; then the ordering, the HOURLY-settlement suppression, the natively
  hourly case, the flat-quarter case, the partial `bracketed_fraction`, NaN gaps, an all-NaN
  window, cost-off, the absence of a `cost.price_bracket` key, and the central saving being
  bit-identical to today's headline.
- Two of those are mutation-checked, because the first drafts of both passed against a wrong
  implementation. `test_the_split_is_by_direction_of_flow_not_by_price_vector` needs a fixture
  where runs A and C export DIFFERENT amounts — with `expA == expC` the export half cancels out of
  the saving and the crossed and uncrossed arrangements coincide exactly, which is true of the
  first bracket fixture and made the split unobservable there. The second is the crossing case
  above; it is the only test that fails when `saved_central` leaves the sort.

**Review finding, fixed — the envelope was the wrong shape.** The construction above evaluated
two corners of the price box: bill EVERY interval at `spot_min`, or every one at `spot_max`. That
is the right pair for a single BILL's envelope. It is the wrong pair for a DIFFERENCE of bills.

The saving is `Σᵢ (impAᵢ − impCᵢ)·p_importᵢ − Σᵢ (expAᵢ − expCᵢ)·p_export_netᵢ`, which is
SEPARABLE, so its extremum picks each interval's price on the sign of that interval's own flow
difference. Where the battery grid-charges, `impA − impC` is negative and the interval wants the
opposite extreme from one where the battery cuts import. A window mixing the two — 182 of 200
realistic windows — has the uniform corners cancel against each other. Measured through the real
`results_from`: the reported width was understated in 88% of realistic windows (mean ratio 0.62,
p5 0.087), and in a symmetric four-hour case with alternating flow signs it collapsed to exactly
€0.00 against a true envelope of ±€0.48 — the caveat announcing "no uncertainty" precisely where
uncertainty is largest.

Fixed by choosing the envelope per interval: four `np.where` passes over arrays already in hand.
No extra `price_curves` calls, no extra simulations, the one-dispatch constraint untouched. The
export pair is mirrored relative to the import pair because the export term is subtracted.

**What the number now is, stated precisely for step 4's wording.** A worst case over intra-interval
price placement — exact wherever the feed-in floor is slack, and a lower bound where it binds.
`price_curves` is affine and monotone in spot for every shipped configuration (verified: slopes
1.21 import, 0.50 export), so markup, energy tax, VAT and terugleverkosten do not break
separability. The §6.5 feed-in floor top-up does, but only under `FeedinFloorMode.MONTHLY` and only
when spot straddles the binding boundary; there the greedy pick errs by UNDER-stating, the same
direction as before, so it never overclaims. Sorting all three evaluations (central included) keeps
`saved_low ≤ saved_central ≤ saved_high` and `width ≥ 0` true unconditionally.

Two tests, both mutation-verified against a revert to the uniform construction:
`test_the_split_is_by_direction_of_flow_not_by_price_vector` (rewritten to re-derive the
per-interval envelope) and `test_the_width_does_not_cancel_itself_on_a_grid_charging_window`. The
second needed strengthening after a first version passed under both constructions: `width > 0` does
not discriminate, because the uniform corners cancel only partially on that fixture rather than to
zero. It now asserts the shipped width strictly exceeds what the uniform construction would report.

Four mutants survive the suite; all four were analysed as equivalent or unreachable rather than
test gaps — the `simulate_cost` guard inside `_price_bracket` is dead code (its call site is
already inside that branch), the `priced == 0` gate is subsumed by the `bracketed == 0` gate, and
swapping `spot_min`/`spot_max` merely exchanges two arguments to a symmetric `min`/`max`.

Not done here (step 4): the user-facing caveat text. The number is available; nothing prints it.

### Step 4 — surface the width as a results caveat (done)

D5′'s deliverable: the number reaches the user. Nothing in `_price_bracket`, `PriceBracket` or
`app/domain/` changed; this is wording and plumbing only.

- `app/results_view.py`: a caveat appended to the existing `caveats` list when
  `price_bracket is not None`, placed immediately after the price-granularity caveat. The two are
  the same fact on two sides — that one says the DISPATCH acted on an averaged price, this one
  says the BILL is uncertain by a stated amount for the same reason — so they read as a pair. It
  does not wait for the euro block further down, which carries the tariff notes rather than the
  granularity ones. The `is not None` is the whole gate: step 3 already returns None for all
  three suppression reasons.
- **Two wordings, branching on `bracketed_fraction < 0.95`.** Below the threshold the window
  genuinely straddles a resolution change (D2's 2025-10-01 case) and the copy states the share;
  at or above it the exceptions are single held or gap-filled hours, not worth a qualifying
  clause. The fraction counts INTERVALS, so the partial copy attaches it to "the priced hours" and
  never to energy or euros. Two msgids rather than one with a substituted phrase, for the reason
  the SoC-drift pair already gives.
- **A second suppression, on DISPLAY rather than on the number.** `num(_, "eur")` prints whole
  euros — there is no cents-precision kind in `_NUM_KINDS`, deliberately (appendix A's 2027
  tariffs do not support one) — so a width under half a euro renders "€ 0", a sentence claiming a
  worst case of nothing. Gated on `width_eur > WATERFALL_DISPLAY_EPS_EUR`, the constant that
  already encodes exactly this rounding rule for waterfall rows. The bracket itself is unaffected;
  this is a display decision.
- **The sentence is deliberately NOT "your saving is €X ± €Y".** The width can exceed the saving:
  measured at €2.46 against a central €0.45 on the standard test fixture, and in three of seven
  synthetic scenarios in the "Revised direction" work. A ± phrasing reads as absurd in that regime
  and invites the reader to conclude they might lose money — a far stronger claim than a
  worst-case bound on the PRICING supports. The copy instead states the width as how far the euro
  figures on the page could shift, with no arithmetic relation to the saving implied, and reads
  the same whichever is larger. D9's "worst case" is stated explicitly, together with what makes
  it a worst case (every hour landing on its least favourable quarter) and an explicit denial that
  it is a typical error.

**The wording is a proposal, not user-approved.** English, whole-window form:

> Your energy data is hourly, but the electricity market prices every 15 minutes, so the
> simulation cannot see when inside each hour your electricity actually moved. In the worst case
> — every hour landing on its least favourable quarter — that shifts the euro figures on this
> page by € X. Treat it as a bound on how far the pricing could be off, not as a typical error: a
> real hour will sit somewhere inside its quarters, and this run cannot tell you where.

The partial form replaces the first clause's ending with "so for N% of the priced hours here the
simulation cannot see when inside the hour your electricity actually moved", and "every one of
those hours" for "every hour".

- Catalog entries added for both msgids (nl translated, en identity), `.mo` recompiled. The `.po`
  edits were made by hand rather than through Babel's writer: `pofile.write_po` re-wraps at a
  different width and churned 750 lines across the two catalogs.
- `tests/test_results_view.py`: six tests — the caveat appearing, the three suppression reasons,
  the partial and whole-window wordings as a pair, and the sub-euro display suppression. The
  first also pins the absence of a ± phrasing on a fixture where the width exceeds the saving,
  because that is the natural way to write the sentence and it is wrong here.
- `tests/test_results_route.py`: two RENDERED-PAGE tests over their own quarter-hourly fixture —
  the caveat in the served markup with its figures substituted (both the full page and the POST
  fragment), and its absence with the settlement back to HOURLY.

**All eight mutants killed**, checked one at a time against the new tests: forcing the gate false,
forcing it true, dropping the €0 display threshold, pinning each wording branch, swapping the
`"eur"` num-kind, dropping the interpolation params, and deleting the template's caveat loop. The
last is the one that matters most — it confirms the route tests cover the template path that has
been this project's recurring blind spot, rather than restating the view-model.

**Obstacle.** The `bracketed_fraction == 0.5` fixture inherited from step 3 puts its spread in the
window's QUIET half, where the flows the width multiplies are small; the width came out at €0.06
and the new display threshold correctly suppressed the caveat, making the partial-wording test
assert nothing. Moved the spread to the half where the battery actually cycles (width €0.91).

Suite: 1255 passed (1248 before).

### Step 5 — adversarial-review fixes to step 4's copy and its tests (done)

Five findings from a review of step 4. No change to `_price_bracket`, `PriceBracket`, or anything
under `app/domain/`; this is wording, one formatting helper, and test coverage.

**F1. The caveat claimed more than the number bounds (user-approved narrowing).** Both wordings
said the width shifts "the euro figures on this page". `width_eur` is `(saved_high − saved_low)/2`
and all three evaluations are DIFFERENCES of two bills, so it bounds the SAVING and only the
saving. The individual bills are on the same page — the KPI sentence prints them ("X without a
battery → Y with one") and the waterfall decomposes one of them — and each moves by MORE than the
stated width, because the two bills' errors partly cancel in their difference. Measured on
`_bracket_dataset`: width €2.46, against a €2.72 half-range on the battery bill alone. A sentence
sold as a worst case must not understate the quantity it names, so both wordings now say "shifts
the saving shown on this page". The computation is unchanged — the decision was to narrow the
claim, not to widen the number, since widening it would report a bound on a quantity D5′
deliberately does not report.

Rationale for keeping "shifts the saving" rather than reverting to a ± phrasing now that the
scope is the saving: the ± objection from step 4 still holds. The width exceeds the saving on this
very fixture, and "your saving is € 0, give or take € 2" still reads as "you might lose money".
Naming the saving as the thing that SHIFTS states a displacement rather than an interval.

**F2. The share could round to "0%".** The partial branch formatted `bracketed_fraction` with
`num(_, "pct")`, pattern `#,##0`. A 365-day window with three spread hours (fraction 0.00034)
rendered "so for 0% of the priced hours here … that shifts the saving by € 2" — a sentence that
states a width while denying there is anything to state it about.

Neither existing kind is right across the whole range the branch can produce (0 to 0.95): `"pct"`
prints "0%" at the bottom, and `"pct_dec2"` writes an ordinary half-window straddle as "50.00%",
two digits of precision an interval count does not carry meaning to. A `"#,##0.##"` pattern (trailing
zeros suppressed) was considered and rejected — it fixes both ends but writes 22/24 as "91.67%",
which is worse than "92%" for the same reason. So a two-kind helper, `_share_pct`: whole percent
where the value survives that rounding, two decimals where it does not. Both kinds already exist
and `pct_dec2`'s own docstring names this exact case; no new kind was introduced.

The test for "survives the rounding" is to RENDER and inspect rather than to compare against
0.005. `#,##0` rounds half to even, so 0.005 itself prints "0%" and a `>= 0.005` cut would admit
precisely the value the helper exists to catch. Mutation-checked: the `>= 0.005` form fails.

**F3. The 0.95 threshold was untested.** Every step-4 fixture had a fraction of exactly 0.5 or
exactly 1.0, so `bracketed_fraction < 0.51` and `bracketed_fraction < 0.999` both reproduced the
suite's results — the threshold was unpinned in both directions. Two fixtures now sit either side
of it, at 23/24 (0.958, whole-window) and 22/24 (0.917, partial); both mutants die.

The fixtures flatten hours from the QUIET part of the day, not the cycling part. This is the trap
step 4 already hit once and it is worth stating plainly: the width scales with the FLOW DIFFERENCE
in the spread hours, not with the spread alone, so removing spread from an hour where the battery
cycles shrinks the width toward `WATERFALL_DISPLAY_EPS_EUR`, the caveat suppresses itself, and the
test asserts nothing. Both tests carry an anti-vacuity assertion on `width_eur >
WATERFALL_DISPLAY_EPS_EUR` with a message saying so.

`test_the_full_window_wording_omits_the_fraction_entirely`'s docstring claimed the 0.5/1.0 pair
"pins the threshold". It did not, and the claim is now corrected in place rather than left to be
believed by the next reader.

**F4. The whole-window wording dropped the "priced" qualifier.** `bracketed_fraction`'s
denominator is PRICED intervals. A window whose first half carries no spot price at all and whose
second half has a spread everywhere therefore has a fraction of exactly 1.0 and takes the
whole-window branch — where "every hour landing on its least favourable quarter" claims something
about hours that were never priced. Both mentions in that branch now say "priced hour"; the phrase
is the same length and this is the common branch, so it stays readable. A test builds that exact
half-NaN window (reachable through `results_from`, width €1.78, above the display gate) and pins
both mentions.

**F5. Two Dutch strings (both user-approved).**

- The caveat's closing clause said "een echt uur ligt ergens tussen zijn kwartieren in", which
  reads as BETWEEN the quarters rather than within one — denying the thing the sentence exists to
  explain. Now "ligt ergens binnen een van zijn kwartieren", in both wordings.
- The step-2 settlement pair did not compose: stem "Je leverancier rekent af per" with options
  "Uurgemiddelde" / "Elk kwartier" reads as "per Uurgemiddelde" / "per elk kwartier". The user
  chose option A — stem "Je leverancier rekent af op basis van", options "Het uurgemiddelde" /
  "Elk kwartier". English unchanged; it composed correctly already.

Both were invisible to the suite, which asserted only the English page. Two Dutch tests now exist
(`test_the_settlement_labels_compose_into_a_sentence_in_dutch` on the edit screen,
`test_the_pricing_uncertainty_caveat_is_translated_on_the_dutch_page` on the rendered results
page), each pinning the superseded string as ABSENT as well as the new one as present. They also
catch a missing msgstr, which otherwise falls back to the English msgid and renders without error.

**The catalogs went through the documented Babel workflow this time**, not by hand — a reviewer
had verified the step-4 hand edits reproduce Babel's output byte-identically. The four superseded
msgids were removed as active entries and retained as `#~` obsoletes, which is the form the
committed catalogs already carry for 50 earlier strings.

One piece of unrelated churn appeared and was kept rather than reverted: Babel re-wrapped the
"Om dezelfde reden wijkt de zelfvoorziening" msgstr (added by hand in commit 04b5f10), moving line
breaks to sit before a leading space. The msgid and the text are identical; only the wrap points
moved. Reading: that earlier hand edit did NOT reproduce Babel's wrapping, and this run normalised
it. Keeping Babel's form makes the catalog reproducible from the documented commands, which the
hand-wrapped form was not.

**Not reachable, and stated rather than papered over.** The sub-half-percent share that F2 exists
for cannot be produced through `results_from` at any plausible fixture: the fraction and the width
are driven by the same few hours, so lengthening the window to dilute the fraction also shrinks the
width below the display gate. Attempts at 10-day windows with a single spread hour reached fraction
0.0042 with widths of €0.02–€0.09, an order of magnitude under the €0.50 gate; forcing it through
needed a spot spike near €50/kWh. The formatting decision is therefore pinned on `_share_pct`
directly, and the CALL SITE is pinned separately by patching `_share_pct` to a spy — without that
spy a `num(_, "pct")` call site is indistinguishable by value at a fraction of 0.5, and the mutant
survived until it was added.

**Mutants, all killed** (each run alone against `tests/test_results_view.py` +
`tests/test_results_route.py`, or + `tests/test_workspace_edit.py` for the Dutch ones):
threshold to `< 0.51`; threshold to `< 0.999`; force the partial branch; force the whole-window
branch; revert the scope wording to "the euro figures" in the partial branch; the same in the
whole-window branch; drop "priced" from the whole-window branch; drop "priced" from the partial
branch's denominator phrase; the call site back to `num(_, "pct")`; `_share_pct` always
`pct_dec2`; `_share_pct` always `pct`; `_share_pct` cutting at `>= 0.005` instead of rendering;
and four on the Dutch catalog (each of the two caveat edits, the stem, the option label).

Two mutants survived a first pass and were killed by strengthening the tests rather than being
argued away: the partial branch's scope revert (no test pinned that branch's scope) and the
`num(_, "pct")` call site (the tautological assertion that first covered it passed either way).

Suite: 1262 passed, 2 skipped (1255 before).
