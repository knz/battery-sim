# Feature requests: redirect thumbs-up to GitHub issues

Worktree: `.claude/worktrees/ux-feature-request-counters`, branch
`worktree-ux-feature-request-counters`.

## The user's prompts, verbatim

Recorded per `docs/specs/AGENTS.md`, which requires the original prompts in the changelog when
files under `docs/specs/` change.

1. > create a worktree for a UX/feature update related to feature request counters

2. > ok so currently we have infrastructure to record the feature requests in the database.
   > In the feature request popup, when the user clicks the thumbs up button, instead of
   > recording the request locally in the DB redirect them to the github issues page with a
   > suitable template (and maybe the link URL can be composed such that the title / template
   > is already filled in in relation to the feature being requested)

3. In answer to a question about how the issue URL should be composed:
   > can you rebase on top of master, it now has issue templates. then check our options again.

   Alongside that, three choices selected from options offered: remove the local recording
   entirely; add a per-key human-readable title map; infer the GitHub repo slug from the git
   remote.

4. > go ahead

   — approving the implementation plan, which had flagged three trade-offs: existing installs
   lose their counter data irreversibly; filing a request now requires a GitHub account; and
   removing `installation_id` closes the hosted-mode telemetry question by deletion.

## Task specification (as stated by the user)

Today, clicking the thumbs-up button in the feature-request popup records the request
locally in the SQLite `feature_interest` table. Instead, the button should send the user
to the project's GitHub issues page, opening a **new issue** pre-filled from a suitable
template — with the URL composed so the title (and template selection) already relate to
the feature the user was asking about.

Open at the time of writing: whether the local DB counter is dropped entirely or kept
alongside the redirect; whether the outbound reporting in `app/interest.py` stays; what
the GitHub repo slug and template are; and where the human-readable per-feature title
comes from.

## Current state (before changes)

- `app/features.py` — closed vocabulary of `FEATURE_KEYS` (7 active) and `RETIRED_KEYS`,
  with an explicit "never rename, never reuse, retire rather than delete" discipline tied
  to the meaning of stored counter rows.
- `app/db.py` — `feature_interest(feature_key, count, last_clicked_at)`, installation-wide
  (a deliberate exception to the per-workspace rule, §5.5 / specs/20-workspaces-ux.md
  §2′.10), plus a migration that re-keys the old workspace-scoped shape.
- `app/main.py` — `POST /feature-interest/{feature_key}` (204), rejects unknown keys with
  404, calls `db.record_interest` and fires `interest.report(...)` as a background task.
- `app/interest.py` — outbound reporting (details being surveyed).
- Templates `workspace_edit.html`, `workspace_results.html`, `workspace_data.html` carry
  the `feature_key="..."` attributes on pending controls.

## Rebase onto master

The user asked for a rebase before deciding the URL shape, because master had gained issue
templates. `HEAD` (`60316d2`) turned out to be a strict ancestor of `origin/master`
(`fc0305e`), so this was a clean fast-forward, not a rebase — no conflicts. It brought in:

- `.github/ISSUE_TEMPLATE/{broken,docs,dutch,other}.md` — four **legacy Markdown** templates.
- `specs/` → `docs/specs/`, and the loose root docs folded into `docs/`.

## High-level decisions

- **D1 — Remove the local recording entirely.** The GitHub issue becomes the only record of
  a feature request. Confirmed by the user after being offered keep-alongside variants.
  Survey finding that makes this tractable: `installation_id` and `feature_interest_url`
  exist *only* to serve the interest reporter — no other consumer — so the whole
  config/telemetry limb comes out with the feature.
- **D2 — Add a YAML issue form, not another Markdown template.** The four templates on
  master are legacy `.md`, where the `body` URL parameter *replaces* the template body
  rather than filling it in — so a `.md` template can only be pre-filled in its title. A
  `.yml` issue form supports per-field pre-filling, which is what lets the composed URL
  name the requested feature in a dedicated field while leaving the user's "why" empty.
  GitHub permits `.yml` forms and `.md` templates to coexist in one repo.
- **D3 — A per-key human-readable title map.** The survey found no server-side key→title
  mapping: the human name lives only in `data-pending-name` on each trigger, and for the
  three pricing keys indirectly in `app/workspace_edit_view.py`. A per-key title belongs in
  `app/features.py` beside the closed vocabulary.
- **D4 — Reword the dialog, don't just re-point the button.** The current copy says "it is
  the only signal we get" and, after clicking, "Thanks. We have recorded that you want
  this." Both become false once nothing is recorded and the click leaves the app. The
  dialog says instead that the button opens GitHub to file the request.
- **D5 — Repo slug `knz/battery-sim`,** taken from the existing hardcoded links in
  `app/templates/_footer.html`. There is no `[project.urls]` in `pyproject.toml`.

## Obstacles

- **Three duplicated dialogs.** `workspace_results.html`, `workspace_data.html` and
  `workspace_edit.html` each carry a verbatim copy of the `#pending-dialog` markup *and* of
  the wiring IIFE. Any change has to land in all three, or be de-duplicated into a shared
  partial as part of this work.
- **`installation_id` has a wide test-fixture blast radius.** `tests/conftest.py`,
  `tests/test_desktop.py` and `tests/test_workspaces.py` all contain workarounds for the
  fact that importing `app.main` runs `config.load()`, which *writes* an id into the data
  directory. Removing it should let those workarounds go, but they must be checked
  individually rather than deleted wholesale.

## Decisions taken during implementation

- **D6 — De-duplicate the dialog into `app/templates/_pending_dialog.html`.** The markup and
  its wiring IIFE were copied verbatim into three pages. Every line of both was changing,
  so the alternative was making one edit three times; approved as part of the plan.
- **D7 — Compose the URL server-side, reach the template via a Jinja global.** Registered in
  `i18n.env_for` beside `locale_code` rather than passed per-render: all three screens carry
  the dialog and would otherwise thread the same locale-independent map through three
  separate view models. `configure(**globals_)` was the other candidate but nothing calls it
  with globals today, and driving it from `main.py` would add an import-time side effect to
  a module the tests deliberately avoid importing early.
- **D8 — Feature titles are deliberately NOT translated.** The title crosses into a GitHub
  issue the maintainer reads alongside issues from every locale, so it is stable English.
  The dialog around the link is translated; the string that leaves the app is not.
- **D9 — Drop the retired table, keep the FILE name.** `_drop_feature_interest` removes
  `feature_interest` on every connect, so a table nothing reads or writes stops implying the
  app still records clicks. The database file stays `feature_interest.db`: renaming it would
  strand the workspace index of every existing installation, a real cost for a cosmetic gain.
- **D10 — Swap the packaging tests' witness from `config.toml` to a file still written.**
  Removing `config.load()` left nothing writing `config.toml`, and two tests used its
  presence to prove state landed in the right directory. They now check `feature_interest.db`
  (test_desktop) and `desktop.lock` (test_packaged); both prove the same property, and the
  real subject of those tests is the `sys.frozen` data-directory guard either way.
- **D11 — Keep `desktop.py`'s deferred `app.main` import.** Its stated reason (a module-level
  `config.load()` that wrote into the data directory) is gone, but importing `app.main` still
  binds paths and mounts static files, so the ordering requirement stands. The comment was
  corrected rather than the code changed.

## Files modified

**Added**
- `.github/ISSUE_TEMPLATE/feature.yml` — YAML issue *form* (not a Markdown template) with a
  pre-fillable `feature` field, a required "why", and an optional "how often".
- `app/templates/_pending_dialog.html` — the shared dialog + its wiring, replacing three
  verbatim copies.

**Changed**
- `app/features.py` — added `GITHUB_REPO`, `FEATURE_TITLES`, `title_for()`, `issue_url()`,
  and an import-time check that every key has a title. Docstring rewritten: the vocabulary's
  discipline is now justified by issues already filed, not by counter rows.
- `app/i18n.py` — registers `feature_issue_url` and `feature_keys` as per-locale globals.
- `app/main.py` — removed `POST /feature-interest/{key}`, `CONFIG`, and the `config` /
  `features` / `interest` imports; docstrings updated (flat routes are three, not four).
- `app/config.py` — removed `Config`, `load()`, the installation-id generation/persistence and
  both env vars. What remains is data-directory resolution; the app no longer reads or writes
  `config.toml` at all.
- `app/db.py` — removed the `feature_interest` table, its re-key migration, `record_interest`
  and `interest_count`; added `_drop_feature_interest`. Module docstring rewritten.
- `app/workspaces.py`, `app/desktop.py`, `app/__init__.py`, `app/_build_info.py`,
  `app/domain/simconfig.py` — comments corrected where they described the removed limb.
- Three screen templates — each now `{% include %}`s the partial.
- `app/locales/{en,nl}` + `messages.pot` — one new msgid, Dutch translation written by hand
  to match the retired string's register; obsolete entries dropped by `pybabel update`.

**Deleted**
- `app/interest.py`, `tests/test_feature_interest.py`.

**Tests changed**
- `tests/test_smoke.py` — `test_thumbsup_acknowledges_in_place` became
  `test_thumbsup_links_to_a_prefilled_github_issue`; the two route tests and `_post` removed.
- `tests/test_params_route.py` — the interest-route test now asserts the issue URL and the
  key → URL map rendered into the page.
- `tests/test_workspace_list.py` — the "deletion spares the counter" test became one asserting
  the retired table is dropped on connect (the upgrade path, which nothing else covered).
- `tests/test_workspaces.py` — same test minus its counter assertion, renamed.
- `tests/test_desktop.py`, `tests/test_packaged.py`, `tests/conftest.py` — witness swap (D10)
  and corrected rationales.

## Obstacles and solutions

- `href="#"` on the link failed `test_every_link_and_form_action_on_the_page_resolves`
  (fragment resolving to nothing) — the anchor now renders with no `href` and `btn-disabled`
  until a `[?]` is clicked, which is also the more honest semantic.
- The new dialog sentence failed 20 `test_no_english_leakage` cases until translated.
- Jinja's `tojson` emits `&` as `&` inside `<script>`, so a literal substring assertion
  on the URL failed; the test compares against the escaped form (the code was correct).
- **CI's "app.css is up to date" job failed after the first push, because of `feature.yml`.**
  That job rebuilds the stylesheet from its Tailwind sources and diffs it against the
  committed file. The delta was six daisyUI `.textarea` rules, and the cause is the new issue
  form: **Tailwind v4 auto-scans the repository root** in addition to the explicit
  `@source '../../templates'`, so the `type: textarea` lines in
  `.github/ISSUE_TEMPLATE/feature.yml` are read as class names and pull in daisyUI's textarea
  component. The rules are inert — nothing renders a `.textarea` element — but the generated
  file is committed and the gate compares bytes, so the rebuild has to be committed with it.

  Worth knowing for the next person who adds a YAML issue form or any root-level file
  containing bare words that happen to be daisyUI class names: it will grow `app.css`, and the
  fix is `npm run build:css` plus committing the result.

  **I got this wrong first and recorded the wrong cause.** My initial check restored
  `origin/master`'s `app/static/` and `app/templates/` but left `.github/` at the branch
  version, so the rebuild still saw `feature.yml` and still produced `.textarea` — which I read
  as proof of pre-existing drift on master. It is not: exporting `origin/master` to a clean
  directory reproduces its committed CSS byte-for-byte, and adding only `feature.yml` makes
  `.textarea` appear. The first "Rebuild app.css" commit message stated the wrong cause and was
  amended.

  (Unrelated trap in the same area: `npm install` inside a git worktree rewrites
  `package-lock.json`'s `name` field to the worktree directory name. Reverted, not committed —
  and `npm ci` is what CI runs anyway.)

## Specs updated

`02-ux-wireframes.md` §2.1 (dialog wireframe + the whole "clicking the thumbs-up" passage),
`08-architecture.md` (layer diagram, schema block, §5.1 "Feature interest", §5.4, §5.5),
`15-data-quality-and-limits.md` §7.5 (egress list, the reports bullet, the installation-id
bullet), `01-product-brief.md` (the no-telemetry non-goal), `06-home-assistant-ingestion.md`,
`03-topology-selector.md` (why that dialog is not the pending affordance — argument survives,
wording adjusted), `17-open-questions.md`, `appendix-a-defaults.md` (both rows removed),
`followups.md` (I5 closed as moot), `20-workspaces-ux.md` §2′.10 + decision table (marked
superseded rather than rewritten — it is a historical design record), `implementation-progress.md`.

Two changes there are worth calling out because they simplify statements made elsewhere:
§5.5's invariant 1 ("every persisted row carries `workspace_id`") now holds with **no
exceptions**, and the backend has **exactly one** egress case (the optional spot-price fetch)
rather than two.

## Verification

- `pytest tests/` excluding the packaged suite: **1381 passed, 15 skipped** — this includes
  the 39 Playwright smoke tests, which run a real browser, and among them the new assertion
  that the dialog's link carries a pre-filled `issues/new` URL with `target=_blank`.
- Dialog copy rendered in both locales and checked by hand.
- Not run: `tests/test_packaged.py`, which needs a built binary. Its one changed assertion
  (the `config.toml` → `desktop.lock` witness swap) is therefore **unverified**; the
  equivalent swap in `test_desktop.py` did run and passes.
- No linter is configured in this repo, so the test suite is the whole gate.

## Current status

Complete. Nothing committed — the worktree is left dirty for review.

Follow-ups noted, not done (none block this work):
- The "Currently pending" table in `implementation-progress.md` names templates
  (`_panel_data.html`, `_panel_params.html`) that earlier refactors appear to have moved or
  renamed. Predates this change; left alone rather than fixed blind.
- `.github/ISSUE_TEMPLATE/` now mixes one YAML form with four Markdown templates. That is
  supported, but converting the other four would make the set consistent and give them the
  same required-field behaviour.
- The `enhancement` label the new form applies must exist in the repo, or GitHub silently
  drops it on submission. Unverified from here.
