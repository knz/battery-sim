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

## Follow-up task — third-party licence notices (2026-08-06)

Committed as d6f5ded; the work below is the next increment on the same branch.

### Question asked

Whether Plotly is the only vendored dependency needing a licence mention. It is not. Three
categories of redistributed third-party code were found:

1. **Vendored browser assets, committed in the repo.**
   - `app/static/vendor/plotly.min.js` — plotly.js v2.35.2, MIT. Its banner cites a
     `plotly.min.js.LICENSE.txt` that does not exist in the repo, so the full-text requirement
     of the MIT licence is unmet.
   - `app/static/app.css` — easy to miss, because nothing sits in `vendor/`: this committed,
     *generated* file is Tailwind v4.3.3 + daisyUI v5.7.0 compiled output. Tailwind's MIT
     banner survives minification at line 1; **daisyUI's attribution is absent entirely**.
     Both are MIT (confirmed from their `package.json`).

2. **Python runtime dependencies shipped inside the desktop bundles** — ~24 packages
   (FastAPI, Starlette, numpy, uvicorn, pywebview, Babel, Jinja2 and their transitive set).
   Licences read via `importlib.metadata`: all permissive — MIT / BSD-3-Clause / Apache-2.0 /
   PSF-2.0. Notice-only obligations, none currently reproduced. The `dev` group
   (pytest/playwright/httpx) is excluded from bundles by design and so is out of scope.

3. **System GTK/WebKit libraries bundled into the AppImage** — the legally significant one.
   `packaging/build-appimage.sh:165-177` copies the transitive `ldd` closure of
   libwebkit2gtk-4.1, libjavascriptcoregtk-4.1, libgtk-3, libgdk-3, libgirepository-1.0 and
   python3-gi's `_gi`, plus every plugin `.so` under `gdk-pixbuf-2.0/`, `gio/modules/` and
   `webkit2gtk-4.1/`. These are **LGPL**, not permissive. LGPL §4/§6 requires notice, source
   availability (or a written offer), and the ability to relink. AGPL-3.0 and LGPL are
   compatible, so this is an unmet *notice* obligation rather than a licensing conflict.

### Decisions

- **Full scope** (all three categories) and **auto-generation**, both at the user's direction.
  A hand-written file was the alternative and was rejected: it would silently go stale as
  dependencies change.
- **Implementation delegated to subagents**, at the user's request, to keep the main context
  clear.
- **The generator is sequenced before the CI gate.** The gate depends on the generator's
  `--check` contract, so wiring it first would mean building against an interface that does
  not exist yet.
- The Python section is generated from `uv.lock` + `importlib.metadata`; the AppImage's system
  libraries cannot be read from this repo (they live on the build host), so that section is
  either derived from `LIB_ROOTS` or carried as a curated, commented table.

### Findings from enumerating the built AppImage

A research pass enumerated the real artifact at `dist/AppDir/` rather than inferring from the
build script. This corrected the initial scoping in several material ways — all verified
directly:

- **119 shared objects from ~86 Debian source packages ship in the AppImage.** `LIB_ROOTS` in
  `build-appimage.sh` is only the set of *roots*; what ships is the transitive `ldd` closure.
  Deriving the notice list from `LIB_ROOTS` would have understated it by an order of magnitude.
- **LGPL-3 is in scope, not only LGPL-2.1.** `libnettle`/`libhogweed`, `libgmp`,
  `libunistring` and `libidn2` are all "LGPL-3+ OR GPL-2+", reaching the bundle via
  `libgiognutls` → GnuTLS → Nettle → GMP (presence confirmed by listing the AppDir). LGPL-3
  §4(b) requires shipping the GPL text alongside the LGPL text, so **four** verbatim licence
  texts are needed: LGPL-2.1, LGPL-3, GPL-3, GPL-2.
- **The shipped `libwebkit2gtk-4.1.so.0` is modified.** `build-appimage.sh:258-281`
  binary-patches two `.rodata` strings to repoint WebKit's compiled-in helper path. LGPL-2.1
  §6(a) requires corresponding source "including whatever changes were used in the work", so
  citing Ubuntu's archive alone is incomplete: the notice must disclose the modification and
  point at `packaging/build-appimage.sh` in this project's own published source.
- **§6(b) is unavailable.** That option covers using a copy already present on the user's
  system; an AppImage ships its own. The satisfaction route is **§6(d)** — offer equivalent
  source access from the same place the binary is distributed (the releases page) — which
  requires recording each source package's name *and version*.
- **Host-provided libraries need no notice**: glibc/loader, libstdc++, libgcc_s, the GL/EGL/DRI
  stack, X11/xcb/Wayland. LGPL-2.1 §6 exempts major OS components. The authoritative list is
  `HOST_PROVIDED` in `packaging/check-appdir-closure.py:57-99`.
- **Much of the bundle is permissive**, not copyleft (fontconfig, harfbuzz, libpng, zlib, ICU,
  SQLite, libxml2, OpenSSL, libwebp, pixman, freetype…). These carry notice-only obligations
  and are recorded as such rather than padded into the LGPL list.
- **Debian copyright files are an unreliable input.** Several are not machine-readable DEP-5
  (cairo, fontconfig, pixman, libxslt, gnutls, libgcrypt, gstreamer, libjpeg-turbo, libtasn1),
  and the `Files: *` stanza is actively misleading for three: WebKit (states BSD-2; the core is
  LGPL-2.1+), gobject-introspection (states GPL-2+; the shipped library is LGPL-2+), and
  libidn2 (states GPL-3+; the shipped library is LGPL-3+/GPL-2+).

### Architectural consequence

The system-library data can only be produced **on the Ubuntu 24.04 build host** — it needs
`dpkg -S`, `dpkg-query` and `/usr/share/doc/*/copyright`, none of which exist in a developer
checkout or on a generic CI runner. The generator is therefore split:

- **(a) Python dependencies and vendored web assets** — regenerable anywhere from the repo
  (`uv.lock`, `importlib.metadata`, `package-lock.json`, the Plotly banner). This is the part a
  CI `--check` can genuinely validate.
- **(b) The AppImage system libraries** — host-derived, grouped by source package, and
  explicitly **not** verified by `--check`.

Both the script docstring and the generated document must state that split plainly. A document
that reads as wholly machine-verified when only half of it is would be exactly the kind of
overclaim this project's writing rules exist to prevent.

### Open question deferred

The AppImage bundles `MiniBrowser`, a standalone WebKit browser executable the app never uses
(copied wholesale with the `webkit2gtk-4.1` helper directory at `build-appimage.sh:140`).
Dropping it would shed a binary and slightly narrow the notice surface. Not a licensing
defect; noted for a future packaging pass.

### What was built

- `scripts/generate_third_party_notices.py` — follows `extract_entsoe_prices.py`'s conventions
  (shebang, explanatory docstring with a "Main items" index, argparse, `--dry-run`). Two
  separated paths, as decided above: repo-derived sections regenerate anywhere;
  `--refresh-system-libs` re-derives the host inventory and is runnable only on the build host.
- `THIRD-PARTY-NOTICES.md` — the generated document.
- `packaging/appimage-system-libraries.json` — the committed host inventory: **119 libraries
  across 85 source packages, none unmapped**. This machine turned out to *be* the build host
  (`dist/AppDir` present, `dpkg` available), so this is real enumerated data rather than a
  curated estimate. The count independently matches the research pass.
- `licenses/{LGPL-2.1,LGPL-3,GPL-2,GPL-3}.txt` — verbatim FSF texts, per LGPL-3 §4(b).
- `app/static/vendor/plotly.min.js.LICENSE.txt` — resolves the dangling banner reference.

Verified directly rather than taken on report: `--check` exits 0 on a current file and exits 1
with an actionable message on a perturbed one (both exercised, file restored); the WebKit
modification is disclosed at `THIRD-PARTY-NOTICES.md:176`; the §6(b)-unavailable / §6(d)-route
reasoning is stated; and the document itself says in its own scope table that section 3 is a
host snapshot **not** checked by CI.

### Correctness fix in the packaging path

The generated notice asserted that the four licence texts are "distributed with the AppImage".
`packaging/build-appimage.sh` contained no reference to `licenses/` at all, so the claim was
false as written — the same failure mode as the install docs' token paragraph, in a document
whose whole purpose is to be relied upon. Rather than weaken the sentence, the build script now
copies `THIRD-PARTY-NOTICES.md` and `licenses/` into
`$APPDIR/usr/share/doc/battery-sim/`, making it true.

That copy fails hard if a licence text is missing, unlike the optional icon-theme and schema
copies above it: a missing icon theme degrades appearance, whereas a missing licence text is a
distribution-terms problem, and an image that silently ships without one is the outcome worth
preventing. `bash -n` passes; the script's size reporting has no threshold to breach and ~87 KB
is negligible against a 110 MB image.

### Known limitations, recorded rather than smoothed over

- The per-package licence strings are a **hand-reviewed reading** of the Debian copyright
  files, not a DEP-5 parse (many are not machine-readable, and `Files: *` is misleading for
  webkit2gtk, gobject-introspection and libidn2 — two of the three independently confirmed).
  Not all 85 were read in full. Legal review before release remains the right next step; this
  work does not substitute for it.
- `--check` validates sections 1–2 and the *rendering* of section 3. It cannot detect drift
  between the committed JSON and a real build host; refreshing that is a manual step.
- Twelve platform-specific packages (pyobjc, pythonnet, cffi, …) carry curated licences so a
  macOS contributor's `--check` does not fail for environment reasons. Where a package is
  installed locally the script cross-checks and warns on stderr, so a stale entry surfaces.
### CI freshness gate

Added to `.github/workflows/test.yml` as a **step in the existing `tests` job**, not a separate
job, and placed before the ~100s pytest run so drift fails in seconds. The reasoning follows the
file's existing "one job, no splitting" logic applied to cost: `--check` needs the resolved
Python environment (it reads installed distribution metadata), and `tests` has already paid for
that with `uv sync`; a separate job would repeat the expensive sync for a check taking about a
second. `css-freshness` stays separate for the opposite reason — it needs Node, which `tests`
has no other use for. The step carries its own `::error file=` annotation, so the failure signal
stays distinguishable without job isolation.

The gate's comments state what it does **not** cover: a green run means the committed file
matches what the repo plus the *committed snapshot* produce, not that every statement in the
document is true of a real AppImage.

### Notices now actually ship with the artifacts

Both packaging paths were changed so the document's claims are true rather than aspirational:

- `packaging/build-appimage.sh` copies `THIRD-PARTY-NOTICES.md` and `licenses/` into
  `$APPDIR/usr/share/doc/battery-sim/`, and fails hard if a licence text is missing.
- `packaging/battery-sim.spec` collects `THIRD-PARTY-NOTICES.md` into the macOS/Windows onedir
  bundles. Those carry the Python dependency set — permissive, but MIT/BSD/Apache-2.0 all
  require the notice travel with the redistributed binary. They do not carry the LGPL stack, so
  the `licenses/*.txt` texts are AppImage-only.

Worth recording: **neither omission would have been caught by anything**. `check_assets` guards
the four asset directories, not these files, and the notices CI gate compares the document
against its generator and knows nothing about packaging. Both spec and script comments say so at
the point of the change, since a silent omission is the failure mode here.

## Verification

- `scripts/generate_third_party_notices.py --check` exits 0; exits 1 with an actionable message
  on a perturbed file (exercised, then restored).
- `bash -n packaging/build-appimage.sh`, `ast.parse` on `packaging/battery-sim.spec`,
  `yaml.safe_load` on `.github/workflows/test.yml` — all pass.
- `uv run pytest tests/test_packaging_metadata.py tests/test_desktop.py` — 94 passed.
- The AppImage licence-copy claim re-checked against the build script after the fix.

The full suite was not re-run here; it carries benchmarks and is slow, and CI runs it on the PR.

### README pointer, and a dangling reference closed

Added a paragraph to the README's Licence section — the natural home, since that section already
sets out the project's *own* terms and the third-party position is the complement to it. It names
the three things the builds carry (browser libraries, Python packages, and the AppImage's LGPL
GTK/WebKit stack), links `THIRD-PARTY-NOTICES.md` and `licenses/`, and notes that both ship
inside the builds rather than living only in the repository.

Writing it surfaced the loose end flagged earlier: the notice's route 3 offered source "by
written request to the address in this repository's README", and the README carried no address —
a notice sending a reader somewhere that does not exist. Fixed in the generator rather than the
output, pointing at `https://raphaelposs.com/contact/`, the contact channel the project already
publishes in `docs/*/sponsor.md`. An address invented for this file would be one nobody watches.

Worth being clear about what that route is: routes 1 and 2 (`apt-get source` and Ubuntu's
archive) are what actually discharge §6(d). Route 3 is the §6(c) written-offer fallback for a
recipient who cannot use either, and costs one line to offer.

## Current Status

The four doc/scrub items are committed (d6f5ded), as is the third-party notices work (f07f676).
The README pointer and the contact-URL fix are complete and verified.

Still open and unchanged: legal review of the 85 per-package licence readings before release;
CSV import (separate work); no git tags or releases; missing `SECURITY.md` and `CONTRIBUTING.md`;
no page on obtaining an HA token; unpinned appimagetool and PyInstaller.

Out of scope by instruction and still open: everything CSV-related (`README.md:11`,
`install.md:11,34`, `installatie.md:14,36`), which the separate CSV-import work will address.
Also still open from the review: no git tags/releases, missing `SECURITY.md` and
`CONTRIBUTING.md`, no page on getting an HA token, unpinned appimagetool and PyInstaller, the
missing Plotly licence file, and the stale HTMX mention in
`docs/maintainers/development.md:12`. The aggregate household figures across the changelogs
were left alone, as agreed they are low-risk.
