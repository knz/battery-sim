<!--
Changelog for the user-facing documentation restructure: slimming the top-level README to a
landing page, moving the developer/maintainer material into docs/maintainers/, and relocating
specs/ under docs/.
-->

# 2026-08-05 — User-facing docs restructure

## Task specification

Iterate on the user-facing documentation, in a dedicated worktree
(`.claude/worktrees/user-docs`, branch `worktree-user-docs`).

As given by the user, in three additions:

1. **README.md** — make it minimal: what someone landing on the GitHub project page needs.
   Overall project description, links to how-to-use docs, status, licence, supporting the
   project. Nothing else.
2. **A maintainers docs directory** — separate files for (a) the stack, how to run, repository
   layout; (b) working on the styles, self-testing; (c) internationalisation.
3. *Mid-task:* the README should also show the app icon.
4. *On review of the plan:* `docs/maintainers/` is the right location, and `specs/` should move
   into `docs/` as well, with `AGENTS.md` paths updated.

## Starting state

`README.md` was 238 lines and mixed both audiences: it opened by telling households to go read
`docs/` instead, then spent ~200 lines on developer material. `docs/` already held the
household-facing tree (`en/`, `nl/`, index); `specs/` sat at the repository root.

## High-level decisions

**The README keeps only what a landing page needs.** Description, how-to-use links, licence,
sponsorship, and one pointer to the maintainer docs. 238 → 49 lines.

**No status section.** It was first condensed from three paragraphs to two, then dropped
entirely on the user's call: stale, and not informative enough to earn the maintenance. Two of
its facts were load-bearing for a first-time visitor and were kept elsewhere — "Linux AppImage
only, no macOS or Windows build" already sits in the *Using the app* paragraph, and "some
features are specified but not built, and the app marks them pending" became a single sentence
pointing at `docs/specs/implementation-progress.md`. A pointer cannot drift from the file it
points at, which is how the old section went stale.

**Maintainer docs are English only**, matching `docs/specs/`. The bilingual requirement covers
the product, not its development instructions.

**Moved material was carried over as-is**, editing only relative link paths and adding the
file-top explanatory comment the repository rules require. The rewriting effort went into the
README. The i18n section in particular is long and detailed and was moved intact.

**`specs/` moved to `docs/specs/` via `git mv`**, so all prose lives under `docs/` and rename
detection keeps the history. Checked first that nothing depends on the path at runtime: all
351 references are prose, including the two that looked like config (`pyproject.toml:48` and
`.github/workflows/test.yml:41` are both comments). No code opens, globs or resolves a path
under `specs/`.

**`changelog/` was deliberately left untouched** — 47 files reference `specs/`, and they are a
historical record of what was true when written. Rewriting them would make the record describe
a layout that did not exist at the time. Their links to spec files are now stale by design.

**The icon is `packaging/icon/battery-sim.svg`**, the master the PNGs are rendered from
(`app/static/favicon.svg` is a byte-identical copy). Centered above the title via an HTML
block. It carries a `viewBox` and an `aria-label`, so it scales to 96px. Unverified: GitHub
sanitizes SVGs in rendered Markdown and does not always display them from a repo path — if it
comes out blank, the fallback is to point the `<img>` at `app/static/favicon-180.png`.

## Requirements change — document all three platforms as available

After the first commit (`8fe01d7`), the user asked for the docs to be updated "to read as if
these release artifacts are available", since a release pipeline had been built in parallel.

**What the evidence showed.** Release run `31032747998` (workflow_dispatch on master,
2026-08-05) is green on all three non-Linux jobs, and all four artifacts uploaded:
`appimage-x86_64` (110 MB), `bundle-macos-arm64` (23 MB), `bundle-macos-x86_64` (25 MB),
`bundle-windows-x86_64` (34 MB). So the jobs do now run and do produce files.

**But the artifacts are not finished packaging**, per the workflow's own header
(`.github/workflows/release.yml:46-51`): the jobs are labelled "(unfinished)", are
`continue-on-error: true`, and the comment states there is no macOS or Windows build script,
the PyInstaller spec has no `BUNDLE(...)` block, no icon, no code signing and `console=True`,
so what comes out is "a raw PyInstaller onedir directory: not a double-clickable `.app`, not an
installer" — and on Windows a console window opens beside the app. There are no tags and no
published GitHub release.

**This was raised with the user before writing anything**, with three options: document the
artifacts as experimental, wait for the packaging work to land, or write the docs as asked. The
user chose the third. Recorded here because the docs now describe a state the pipeline's own
comments say does not fully exist yet.

**Known gaps between the docs and the artifacts**, to close when packaging is finished:

- The macOS pages say to open a `battery-sim` launcher inside the unpacked folder. There is no
  `.app`, so the described double-click experience is not what a Mac user will get.
- The Windows console window is mentioned as ignorable rather than absent — accurate today,
  but it should disappear once the spec sets `console=False`.
- The security-warnings pages' macOS and Windows steps come from Apple's and Microsoft's
  documentation, not from running these builds. A note saying so was added to both header
  comments, so a reader's report of different wording outranks the page.
- No GitHub release exists yet, so every download link points at a releases page that is
  currently empty.

## Files modified

**Created**

- `docs/maintainers/README.md` — index for the tree
- `docs/maintainers/development.md` — stack, running from source, layout tree
- `docs/maintainers/styles-and-testing.md` — Tailwind rebuild, Playwright screenshots + smoke tests
- `docs/maintainers/i18n.md` — the full internationalisation section

**Rewritten**

- `README.md` — 238 → 49 lines, icon added
- `docs/README.md` — now indexes three trees rather than two; the closing developer pointer
  targets `maintainers/` and `specs/` instead of the top-level README

**Moved**

- `specs/` → `docs/specs/` (`git mv`, 25 files)

**Platform availability pass** (second commit)

- `docs/en/install.md`, `docs/nl/installatie.md` — rewritten: the platform table now lists four
  downloads by artifact name instead of two "no build yet" rows; new download-and-run sections
  for macOS (both architectures) and Windows; the data-directory section became a per-platform
  table (`~/.local/share/battery-sim`, `~/Library/Application Support/BatterySim`,
  `%LOCALAPPDATA%\BatterySim\data`, read off `app/config.py:72-95`); the browser fallback and
  the GStreamer note moved out of the Linux section, since the fallback is cross-platform and
  the GStreamer message is Linux-only.
- `docs/en/security-warnings.md`, `docs/nl/beveiligingswaarschuwingen.md` — dropped the three
  "no build exists yet / this is advance notice" framings. The vendor-sourced mechanics are
  unchanged and were already written as present-tense steps.
- `docs/en/sponsor.md`, `docs/nl/sponsor.md` — "the Linux build is verified on a narrow set of
  machines" now covers all three platforms.
- `README.md` — the Linux-only paragraph now names all four downloads.

**Swept** (path rewrite `specs/` → `docs/specs/`)

- 59 source files under `app/` and `tests/` (prose comments only), plus `AGENTS.md`,
  `pyproject.toml`, `.github/workflows/test.yml`, `followups.md`, `docs/en/sponsor.md`,
  `docs/nl/sponsor.md` — 100 lines changed, all one-for-one.

## Obstacles and solutions

- **Four links inside `docs/specs/` escaped the tree after the move** (`../changelog/`,
  `../app/static/ha_fetch.js`) — they resolved from the old root location and now landed inside
  `docs/`. Rewritten to `../../`. Found by a link checker, not by eye.
- **Two pre-existing broken links, fixed in passing** (both confirmed broken at HEAD before
  this work, so neither is fallout from the move): `docs/specs/02-ux-wireframes.md:951` linked
  to `../specs/08-simulation-core.md`, a file that has never existed — the target is
  `08-architecture.md`, and as a sibling it needs no `../`. `followups.md:779` linked to
  `04-state-machine.md` as though it sat inside the spec directory.
- **The sponsor files' spec citations looked like relative links but are root-relative paths**
  inside an HTML comment, alongside `changelog/…` references. They needed the same rewrite as
  source files, not the `../` treatment their location suggested.

## Verification

- A link checker over all 39 tracked non-changelog `.md` files: every relative link resolves.
- `uv run pytest -q`: **1341 passed, 24 skipped** — the skips are the live-HA suite, which is
  expected to skip without a configured instance.
- Not verified: how GitHub renders the README's inline SVG (see the icon decision above).

## Current status

First scope committed as `8fe01d7` and opened as PR #2: README slimmed with the icon,
`docs/maintainers/` written, `specs/` moved and all references swept.

Second scope done, not yet committed: the household docs now present Linux, macOS and Windows
builds as available, per the user's decision above.

Possible next steps, not decided:

- The gap list in the requirements-change section above is the honest backlog. Finishing the
  macOS `.app` bundle and setting `console=False` would make the docs true as written; until
  then they run ahead of the artifacts.
- Cutting an actual release (there is no tag and no published release) would make the download
  links resolve.
- The maintainer docs were moved rather than edited. `i18n.md` in particular is long and reads
  as one continuous argument; it could be tightened or split, but that is a separate pass.
- The household-facing `docs/en/` and `docs/nl/` pages have not been reviewed in this pass —
  they were only touched by the path sweep.
