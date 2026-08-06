# 2026-08-06 — GitHub publication readiness review

## Task Specification

User asked for an evaluation of whether this project is ready to be made public on GitHub
(the repository already exists but is private). The evaluation was to be done **from the
perspective of a user in the intended audience** — a Dutch household considering a home
battery, not a developer.

Follow-up scope (this worktree): act on a subset of the findings. Explicitly in scope:

1. Fix the privacy section in the install docs (EN + NL).
2. Update the macOS install steps to reflect the `.app` bundle that is actually shipped.
3. Update `.github/workflows/release.yml` (stale header comments about macOS packaging).

Explicitly **out of scope**, by the user's instruction: anything about CSV import. CSV is
being implemented separately, so the docs that promise it are deliberately left alone.

Work happens in the git worktree `.claude/worktrees/docs-fixes` on branch
`worktree-docs-fixes`, branched from `origin/master` (dadc8ab).

## Review findings (2026-08-06)

Verdict: code and CI are in good shape; the user-facing docs are not, and two of the problems
would be hit by the intended audience within minutes.

### Blockers found

1. **CSV is promised but not built.** `README.md:11` and both install pages present the app as
   reading "Home Assistant *or* CSV exports". `data_source_csv` is in the pending set
   (`app/features.py:49`) and no household-CSV source module exists under `app/sources/` — all
   CSV code there handles internal spot-price data. Home Assistant is the only way in.
   *Deferred by the user: CSV is being implemented separately.*
2. **The privacy section is factually wrong.** `docs/en/install.md:158,168-170` states the
   Home Assistant token is stored in the app's data directory and tells a privacy-conscious
   user to delete that directory to remove it. The token is in browser `localStorage`
   (`app/static/ha_fetch.js:133`) and never reaches the backend — the code asserts this in at
   least six places (`app/main.py:24`, `app/sources/home_assistant.py:46`, `app/dataset.py:5`).
   The architecture is *better* than documented, but the stated remedy does not work.
3. **No releases exist.** `git tag -l` is empty, so every install path dead-ends at an empty
   releases page. `release.yml` creates a *draft*, so tagging alone is not sufficient.

### Personal data in tracked files

An initial pass reported this category clean; that pass only grepped for `/home/` and the
username, and was wrong. Present in the working tree:

- The author's home Home Assistant LAN IP plus token-file location, in
  `tests/test_ha_live.py:10-11` and `changelog/20260723-ha-data-import.md:8,125,157`.
- A fingerprint of the author's HA install at `changelog/20260723-ha-data-import.md:23-36`:
  exact HA patch version, statistic counts, a real meter register value, and an integration
  name identifying the electricity supplier.
- The household's real aggregate annual figures across several changelogs (import 3,924 kWh,
  export 2,096 kWh, 21% self-sufficiency, 162 PV days).

No secrets, keys or tokens anywhere, including history. These lines do not appear in deleted
blobs, so a working-tree edit suffices — no history rewrite. The stale backup/worktree branches
do carry them.

### Other findings (not in this worktree's scope)

- macOS install steps describe a `battery-sim` folder; the workflow ships
  `Home Battery Simulator.app`. *In scope here.*
- `release.yml:61-62,410-411` claims macOS has no `BUNDLE(...)` block; it does
  (`packaging/battery-sim.spec:321-325`). *In scope here.*
- Missing `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `.github/FUNDING.yml`.
- No household-facing page explaining how to create an HA long-lived token, what base URL to
  use, or which entities to pick. With CSV unbuilt this is the only path in.
- appimagetool is fetched from the rolling `continuous` tag
  (`packaging/build-appimage.sh:466`); PyInstaller is unpinned. Releases are not reproducible.
- The vendored Plotly banner references a `plotly.min.js.LICENSE.txt` that is not committed.
- `docs/maintainers/development.md:12` mentions HTMX, which is not used.

### What is in good shape

Token-free architecture (verified against the code). Full EN/NL parity on all three
household-facing pages, in idiomatic informal Dutch. No secrets in tree or history. CI uses no
secrets, defaults to `contents: read`, and gates releases on the tag matching
`app.__version__`. Committed data is public market data only. History is ~35 MB with no stray
large blobs.

## High-Level Decisions

- **Work in a worktree**, at the user's request, so these doc fixes stay isolated from the
  separate CSV-import work.
- **The changelog moved into the worktree** rather than being left on master: it was still
  untracked, so it did not follow the branch automatically and was recreated here.
- **Branched from `origin/master` (dadc8ab)**, one commit behind local master (5dbbd6c). That
  commit touches `docs/maintainers/development.md` and a changelog — no overlap with the three
  files in scope, so no rebase was needed first.
- **The token fix states the stronger, true property** rather than merely deleting the wrong
  sentence: the token never reaches the backend at all. This is a privacy selling point for
  the intended audience and is currently understated.

## Requirements Changes

Mid-task the user added the `tests/test_ha_live.py` personal-value scrub to the approved scope
("you can scrub the personal values in test_ha_live as well"). Acting on it made the two
changelog occurrences of the same values inconsistent to leave behind, so those were scrubbed
in the same pass — see the rationale below.

## Files Modified

- `changelog/20260806-github-publication-readiness.md` — created (this file); the copy on
  master's working tree was removed.
- `docs/en/install.md` — privacy section corrected; macOS steps rewritten for the `.app`.
- `docs/nl/installatie.md` — same two changes, Dutch counterpart, parity preserved.
- `.github/workflows/release.yml` — two stale comment blocks corrected (header §"the
  unfinished platforms", and the `release` job's draft rationale). Comments only; no step,
  trigger or permission changed.
- `tests/test_ha_live.py` — docstring example: LAN IP → `homeassistant.local`, token path →
  `~/.ha-token`.
- `changelog/20260723-ha-data-import.md` — same two values scrubbed, plus the HA patch version
  generalised and the supplier-identifying sensor name replaced with a description.

## Rationales and Alternatives

- **The token paragraph states the stronger, true property rather than just deleting the false
  one.** The token never reaches the backend at all — a privacy point the page was
  understating. It also now gives a remedy that works (clear browser site data); the old advice
  to delete the data directory does not touch the token.
- **The lead-in above the directory table lost "and your Home Assistant token if you entered
  one".** That table enumerates the directory's contents, and the token is not among them.
- **macOS steps name `Home Battery Simulator.app` and Applications/Trash**, matching what
  `release.yml` actually zips (`battery-sim.spec:68`, `MACOS_APP_NAME`). The Gatekeeper
  paragraph and its link to security-warnings.md were checked against the `.app` flow and left
  unchanged — the "Open Anyway" route is unaffected by bundling.
- **`release.yml`'s macOS comment now separates bundling from signing.** Bundling has landed;
  signing has not (`codesign_identity=None`, ad-hoc signature only). The old text conflated the
  two and would have led a reader to think macOS was further behind than it is.
- **The draft-release rationale kept its other reasons** (continue-on-error platforms may be
  missing, nothing signed, notes need a human) and gained an explicit note that nothing checks
  the asset count against what the README promises.
- **Changelog scrub kept the technical findings and removed only the identifying values.** The
  probe table's value is its findings about HA's statistics API; the exact patch version and
  the supplier's sensor name carry none of that and identify the author's household. The
  third-party entity id in `20260805-ha-entity-preselect.md:262` was left: it is an opaque
  device-model string, not personally identifying, and it is the concrete example that makes
  the hint-matching point.
- **`homeassistant.local`** was chosen over an invented IP because it is HA's documented
  default hostname and already appears elsewhere in the tree.

## Obstacles and Solutions

- The worktree branched from `origin/master` (dadc8ab), one commit behind local master —
  checked the delta first; it touches only `docs/maintainers/development.md` and an unrelated
  changelog, so no rebase was needed.
- The changelog was untracked and so did not follow the branch — recreated in the worktree and
  deleted from the main checkout.

## Verification

- `uv run pytest tests/test_ha_live.py tests/test_i18n.py tests/test_no_english_leakage.py` —
  205 passed, 2 skipped (the live-HA tests, which require `HA_URL`/`HA_TOKEN_FILE`). The full
  suite was not run: it carries benchmarks and is slow, and these changes are docs, comments
  and one docstring.
- `release.yml` re-parsed with `yaml.safe_load`; all four jobs still present.
- `tests/test_ha_live.py` re-parsed with `ast.parse`.
- Grep confirms the LAN IP and `~/.homeassistant` no longer appear in any tracked file.
- Both install pages re-read end to end for EN/NL parity.

## Current Status

All four approved items are done. Not committed — awaiting review of the diff.

Out of scope by instruction and still open: everything CSV-related (`README.md:11`,
`install.md:11,34`, `installatie.md:14,36`), which the separate CSV-import work will address.
Also still open from the review: no git tags/releases, missing `SECURITY.md` and
`CONTRIBUTING.md`, no page on getting an HA token, unpinned appimagetool and PyInstaller, the
missing Plotly licence file, and the stale HTMX mention in
`docs/maintainers/development.md:12`. The aggregate household figures across the changelogs
were left alone, as agreed they are low-risk.
