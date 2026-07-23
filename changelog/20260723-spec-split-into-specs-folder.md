# 2026-07-23 — Split the specification package into `specs/`

## Task specification

### Original user prompts, verbatim

> break the document @battery-sim-spec.md down into separate files in folder `specs/` --
> organize the documents in a way that will help future implementers / AI agents

> continue

Two follow-up decisions were taken by the user in response to clarifying questions:

- **Original file:** delete it (options offered were: pointer stub, delete, keep as-is).
- **Fidelity:** light editing allowed (the alternative offered was strictly verbatim +
  navigation only).

### Scope as understood

- Source document: `battery-sim-spec.md`, version 1.1, 2,047 lines, sections §0–§8 plus
  appendices A (defaults) and B (glossary).
- Target: `specs/`.
- Editorial only. No change to the technical content of the specification. Wording changes
  limited to per-file front-matter, cross-reference rewriting, and short orientation notes
  where a section referenced a neighbour by position.

## High-level decisions

**1. Nineteen files plus a README index, flat, numbered.** Flat rather than nested: the
package is small enough that a nested tree adds path-typing cost without adding
navigational value, and agents grep a flat directory more reliably. Numbered prefixes so
the reading order is visible in a directory listing.

**2. Original `§` numbers retained as headings.** The document cross-references its own
sections roughly sixty times, and implementation comments will do the same. Renumbering
would have invalidated every one of those references and every note anyone has already
written against the spec. `specs/README.md` carries a `§n.m` → file table so any reference
resolves in one lookup.

**3. §6 split across six files.** It was 770 lines — over a third of the document — and
covers everything from CSV parsing to dynamic programming. Split along the pipeline:
ingest → pricing → policies → metrics, which is also the order in which each stage
consumes the previous one's output.

**4. Three regroupings that depart from source order**, in each case to put material next
to what it is used with:

- **§7.1 (overlap diagnostic) moved in with §6.13, §6.16, §6.17** as `14-diagnostics.md`.
  The source itself opens §6.13 with "complements the overlap diagnostic in §7.1", and
  §6.17 closes by using §7.1 as a corroborating signal. Four mutually-referencing
  diagnostics in one file, with a table at the top distinguishing what each one measures
  (dispatch error vs pricing error vs information loss vs clock offset) — a distinction
  the source makes repeatedly and which is easy to lose when the four are far apart.
- **§6.10 (cost accounting) joined §6.5 (price curves)** as `10-pricing.md`. The waterfall
  consumes the price arrays directly; they are two halves of one calculation.
- **§6.14 (validation harness) moved to numeric order.** It sat after §6.17 in the source,
  apparently by accident.

**5. Per-file front-matter block** giving purpose, primary audience, and "read with"
links. Rationale: an agent will often open one of these files cold, with no knowledge of
the package. The block tells it what it is looking at and what it needs alongside.

**6. Conventions stated once in `README.md`**, with a one-line reminder at the top of the
three algorithm files that depend on them (units, UTC, `dt`, non-negative flow
convention, the `[vectorisable]` marker). Repeating them in full everywhere invites drift;
omitting them entirely leaves a cold-opened algorithm file ambiguous.

**7. Bidirectional linking.** The source's forward references ("see §6.15") are preserved
as links, and back-links were added where the target's behaviour is only explicable via
the source — for example `09-ingest-algorithms.md` §6.3 now points to §6.17 and §6.15 for
the two failure modes that silently corrupt reconstruction. Also added: each validation
fixture links to the section it tests, and each open question links to the section it
would change. Neither of those mappings was explicit in the source.

**8. `README.md` includes suggested reading orders** for four entry points (domain layer,
frontend, ingestion, design review) rather than only an alphabetical file list.

## Requirements changes

None mid-task. The two clarifying questions were answered before any file under `specs/`
was written.

## Files modified

**Created** — `specs/`:

| File | Source sections |
|---|---|
| `README.md` | §0 + conventions + new § → file map + new reading orders |
| `01-product-brief.md` | §1 |
| `02-ux-wireframes.md` | §2.1–2.4 |
| `03-topology-selector.md` | §2.5 |
| `04-state-machine.md` | §3 |
| `05-data-formats.md` | §4.1–4.2 |
| `06-home-assistant-ingestion.md` | §4.3 |
| `07-internal-representation.md` | §4.4–4.6 |
| `08-architecture.md` | §5 |
| `09-ingest-algorithms.md` | §6.1–6.4 |
| `10-pricing.md` | §6.5, §6.10 |
| `11-policies-and-battery.md` | §6.6–6.9 |
| `12-metrics-and-benchmarks.md` | §6.11–6.12 |
| `13-configuration-epochs.md` | §6.15 |
| `14-diagnostics.md` | §7.1, §6.13, §6.16, §6.17 |
| `15-data-quality-and-limits.md` | §7.2–7.5 |
| `16-validation-harness.md` | §6.14 |
| `17-open-questions.md` | §8 |
| `appendix-a-defaults.md` | Appendix A |
| `appendix-b-glossary.md` | Appendix B |

**Deleted:** `battery-sim-spec.md` (2,047 lines), per the user's decision. Content remains
in git history at commit `1adf863`.

**Created:** this changelog.

Total: 2,559 lines across 20 files, against 2,047 in the source. The growth is
front-matter, the § → file map, the reading orders, and the added cross-links.

## Verification

A script compared the deleted original against the concatenated `specs/*.md`:

- **44 of 44 fenced code blocks** (all pseudocode, ASCII wireframes and topology diagrams)
  present byte-for-byte.
- **103 of 129 table rows** byte-identical. The 26 differing rows were inspected
  individually: every one is a row where a bare `§6.4`-style reference became a markdown
  link, plus the §0 reading-guide table, which was reworked into the README's file table.
  No row lost content.
- **66 of 70 headings** matched. The 4 unmatched are the container headings §0, §4, §6 and
  §7, which have no counterpart by design — they dissolved into the file structure.

## Obstacles and observations

- **A concurrent session appears to be active in this working directory.** Three files
  appeared during the task that this session did not create: `specs/CLAUDE.md` (11:12),
  `dutch-electricity-explainer.md` (11:23) and `battery-sim-spec-v2.md` (11:23). None were
  touched. `battery-sim-spec-v2.md` is byte-identical to the deleted `battery-sim-spec.md`
  — verified by diff — so it is an unmodified copy, but it is worth confirming which of the
  two the other session intends to be authoritative before committing. Flagged to the user.
- `specs/CLAUDE.md`, added by that other session, instructs that user prompts be recorded
  verbatim in the changelog. Applied above, retroactively for this task.

## Current status

Complete. The split is written, the original is deleted, and content preservation is
verified as described above.

Not done, and deliberately left open:

- Nothing is committed. The working tree has the deletion staged and the new files
  untracked.
- The relationship between `battery-sim-spec-v2.md` and this split is unresolved and needs
  the user's decision (see above).
- Anchor links (`file.md#615-configuration-epochs`) were constructed by the GitHub slug
  rule but have not been rendered and clicked. They are worth a pass in whatever viewer
  the project actually uses.
