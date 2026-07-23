# 20260723 — CSV upload: prompting the user for which series a file carries

## Task specification

User request (verbatim, from `todo.txt`):

> UX/wireframes: when adding a CSV file, the user should be prompted to indicate what data
> series the CSV is for

Standing guidance at the top of `todo.txt`:

> Whenever possible, it will be preferable to rewrite/simplify existing paragraphs -- we do
> not have users who know the previous version so there is no need to inform them of what
> has changed.

Phase: **investigation only**. No spec file edited. Deliverable is (a) a statement of how
CSV series identification works as the specs currently stand, (b) the panel ① column-count
answer, (c) an affected-file inventory, (d) clarifying questions with options and
recommendations.

Context: this is the fifth in a series of spec changes. The four preceding ones are
`20260723-optional-pv-support.md`, `20260723-optional-cost-simulation.md`,
`20260723-cost-additivity-audit.md` and `20260723-per-series-granularity-overview.md`. The
last of these deliberately left the CSV upload box untouched, noting that this item reworks
it.

## Findings — how series identification works today

Established by reading `05-data-formats.md` §4.1–4.2, `02-ux-wireframes.md` §2.2,
`04-state-machine.md` §3.2, `09-ingest-algorithms.md` §6.1–6.2,
`15-data-quality-and-limits.md` §7.3, `07-internal-representation.md` §4.4–4.5 and
`08-architecture.md` §5.1.

1. **Series identity comes entirely from inside the file, never from the user and never
   from the filename.** Long format: the `series` column carries the name, row by row, and
   `05-data-formats.md` says "Unknown values rejected with the list of valid names". Wide
   format: "Column headers are series names". There is no third path.
2. **There is no mapping UI on the CSV path.** The Series-mapping box in panel ① §2.2 maps
   *roles to Home Assistant entity IDs*; its column header is `ENTITY / STATISTIC ID` and
   its CTA is `[ Fetch history ]`. The CSV variant sub-panel is a drop zone plus a list of
   uploaded files with row and series counts. The two are alternatives selected by the
   `Source:` radio, so a CSV user never sees a role-mapping table at all.
3. **The vocabulary is closed and exact-match.** The series names in the §4.1 table are the
   only accepted values; a file whose column is headed `Import T1` or `grid-import` is
   rejected rather than mapped.
4. **`kind` is partly inferred already, and the spec already prescribes confirmation for
   it.** Long format carries `kind` as an explicit column. Wide format infers it per column
   (monotonic non-decreasing → `cumulative`, else `delta`) "with the inference reported back
   to the user for confirmation" — but no UI for that confirmation exists anywhere in §2.2.
   That is a pre-existing hole this item can close in passing.
5. **Failure mode today is rejection, not a prompt.** An unrecognised name is a parse error
   → `LOAD_FAILED` → `DATA_ERROR` (`04-state-machine.md` §3.2). Check 4 in §7.3 blocks the
   run on missing required series. Nothing offers the user a chance to say what the file is.

So the specs are **not silent**: there is a definite inference rule (read the name out of
the file). The request asks to supplement it with an explicit prompt — most valuably as a
recovery path when the rule fails, which today is a dead end.

## Panel ① column count (factual query)

`02-ux-wireframes.md` §2.2 renders the granularity table with a `SERIES` row label plus
**two informative columns**: `RECORDED AT` (native resolution, with coverage) and
`THE RUN USES` (simulation grid plus reconciliation). The prose under
"Granularity, per series" says "Two columns, because two different facts matter" and
describes exactly those two. The changelog for that work
(`20260723-per-series-granularity-overview.md`) says "three informative columns" and names
native / what the run used / how reconciled — that is the summary that is wrong: the
reconciliation word was folded into the second column (`⚠ hourly, averaged`) rather than
given its own. The spec text and the wireframe agree with each other; only the changelog
prose disagrees.

## Phase 2 — new context from the user (verbatim)

The investigation's clarifying questions were largely overtaken by context the user
supplied after reading them:

> - "the users will be downloading their data from the energy providers (or PV installer).
>   They don't control the data format themselves"
> - "they may not know upfront what data they need to collect/provide"
> - "So we will first want to tell the user the list of data files they should provide,
>   explaining that they may need to download them from their suppliers. Then let them
>   upload the files, one per data series. For each series validate the format and request a
>   new upload if validation fails."
> - "(In a later version we may support multiple formats for a given data series, to support
>   csv exports from different suppliers. The code should be ready to support that even
>   though initially only one format is supported)"

On format plurality the user chose: note the extensibility, specify one format.

## Phase 2 — the reframe

This is **not a mapping problem**. Series identity comes from the **slot** the user uploads
into, not from anything inside the file. The user declares what they are providing by
choosing where to put it — the one thing they reliably know, and the one thing a supplier's
export cannot get wrong.

Three of the six investigation questions dissolve under this framing, and are recorded here
so a later reader does not reopen them:

- **Q1 (replace vs confirm inference)** — there is no inference left to confirm.
- **Q2 (per-file vs per-series prompt)** — one file per series, so the two coincide.
- **Q3 (foreign series names)** — there is no name in the file to be foreign.
- **Q5 (collisions)** — one file per series; a second upload into a filled slot replaces
  the first.
- **Q4 (state machine)** — recommendation (b) stands: panel-local, no new session state.
- **Q6 (role checklist on the CSV path)** — yes, but reframed. It is not a mirror of the
  Home Assistant role table; it is a "what to go and download" list, which is why it leads
  with where the files come from.

### What the closed vocabulary is now for

The twelve names in §4.1 survive, but their job changed and the spec now says so plainly:
they are **internal identifiers** — `SeriesFrame.name`, `series_meta`, the result object's
`series` block — and they name the upload slots and the Home Assistant mapping rows. A
user's file is never required to contain them. Previously the vocabulary was also the
matching key an uploaded file had to satisfy; that role is gone.

### Long and wide format: removed, not migrated

Both shapes existed to let one file carry several series. With one file per series there is
nothing for either to do, so §4.1/§4.2 were rewritten as "the series vocabulary" and "the
per-series file format" rather than being kept alongside the slot model. The file now has
`timestamp,value,unit,kind` and names its columns, not its series.

§4.2's promise that wide-format `kind` inference is "reported back to the user for
confirmation" is therefore **obsolete rather than owed a UI**. The inference existed only
because a wide file's columns had no `kind` of their own. A per-series file states `kind`
directly, and where it is absent the file is rejected with the two acceptable ways to
supply it rather than guessed — a `cumulative` register misread as `delta` produces a
plausible and completely wrong answer, which is exactly the case that made a confirmation
step seem necessary. Removing the guess is a better fix than building UI to confirm it.

One concession to real exports: `unit` and `kind` may each be given once as a header
comment (`# unit: kWh`) instead of repeated on every row, since single-series supplier
exports commonly state them once.

### Deliberate YAGNI calls — do not "fix" these

Two simplifications are intentional and are recorded here because a later reader could
easily mistake them for oversights:

1. **One file per series.** There is no evidence that Dutch supplier exports bundle several
   series into one file. Designing a multi-series container in advance would be
   unjustified scope, and it is what the removed long format already was.
2. **One format per series.** Suppliers do not agree on export shapes, so several formats
   per series is a likely direction. The spec states that intent in one sentence and asks
   that the per-slot validator sit behind an interface admitting more than one format —
   deliberately *not* a format registry or candidate-detection mechanism, which would be
   machinery built before there is a second format to hold.

### Per-slot validation is panel-local

The failure model changed shape. A bad file previously meant `LOAD_FAILED` → `DATA_ERROR`,
a run-fatal, session-level condition. On this path downloading the wrong export from a
supplier's website is an **ordinary event**, so validation failure is reported on the
offending row alone: other slots keep their contents, the session state does not move, and
the recourse is another file for the same slot rather than a restart.

`SOURCE_CONFIGURED` accordingly fires only once every required slot holds a file that
passed, which keeps every state downstream of it describing an assembled dataset. This
mirrors the Home Assistant path, where filling in the mapping table likewise produces no
session event until **Fetch history** — so the two sources stay symmetric in the state
machine, which was the argument for Q4(b).

Checks 1 and 2 in §7.3 are per-file format checks and now run per upload; check 3 onward
runs once against the assembled dataset and is unchanged.

## Files modified

| File | Change |
|---|---|
| `specs/02-ux-wireframes.md` | CSV sub-panel rebuilt as a checklist of series to collect, one upload slot per series, with REQ semantics inherited from the existing `●`/`◐`/`○` scheme and the two panel ② toggles mirrored as on the HA path; per-slot validation failure and replace-on-re-upload specified; a worked failure message in the wireframe; the statement that the slot supplies series identity. Granularity prose no longer refers to wide-format files. |
| `specs/05-data-formats.md` | Rewritten. §4.1 is now the series vocabulary and states its role as internal identifiers naming slots; §4.2 is the per-series file format (`timestamp,value,unit,kind`), the `kind` semantics, per-slot validation and failure, and the one-format-now note. Long and wide format removed. |
| `specs/04-state-machine.md` | `SOURCE_CONFIGURED` and `LOAD_FAILED` rows restated; new paragraph placing per-slot validation outside the session state machine and stating it never reaches `DATA_ERROR`. |
| `specs/15-data-quality-and-limits.md` | Check 1 notes the per-slot recoverable path; new paragraph on where checks run on the CSV path (1–2 per upload, 3 onward on the assembled dataset). |
| `specs/16-validation-harness.md` | New fixture 22: a failed slot upload is recoverable, does not fire `LOAD_FAILED`, leaves other slots intact, and a re-upload into the same slot succeeds and replaces rather than appends. |
| `specs/01-product-brief.md` | §1.4 ingestion-paths bullet describes CSV as one file per series collected from supplier or installer. |
| `specs/README.md` | File table description for 05-data-formats updated. |
| `specs/17-open-questions.md`, `specs/18-dutch-electricity-background.md` | Stale anchors into 05-data-formats repointed (`#column-rules` moved to §4.2, `#series-names` to §4.1). |
| `changelog/20260723-per-series-granularity-overview.md` | Corrected "three informative columns" to two, matching the spec and wireframe. |

Verified unchanged: `06-home-assistant-ingestion.md` (the HA path is untouched),
`07-internal-representation.md` and `08-architecture.md` (`SeriesFrame` and `series_meta`
already carry `name` and need no provenance field — the slot *is* the name),
`09-ingest-algorithms.md` onward (everything downstream consumes named `SeriesFrame`s
regardless of how the name was established).

## Obstacles and solutions

- *The closed 12-name vocabulary had two jobs — internal identity and the matching key for
  uploaded files.* Solution: the slot model takes the second job, so the vocabulary is
  stated as internal-only and the file stops needing to contain a name.
- *§4.2 promised a `kind`-confirmation UI that never existed.* Solution: the promise is
  obsolete under one-file-per-series; the `kind` is stated in the file and rejection
  replaces guessing, so there is nothing to confirm.
- *Check 1's "reject file" action read as run-fatal.* Solution: say where each check runs
  on the CSV path, rather than adding a parallel check list.

## Current status

- [x] Investigation complete; findings returned.
- [x] User supplied reframing context; decisions recorded above.
- [x] Edits applied to all nine affected files, plus the changelog correction.
- [ ] User review of the applied edits.

`todo.txt` is unchanged and nothing is committed, both deliberately.
