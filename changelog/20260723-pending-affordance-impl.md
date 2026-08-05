# 20260723 — Implement the pending affordance: backend counter + interest reporter, and annotate pending UI

## Task specification

User request (verbatim):

> we've started implementing the app from specs. we have a dialog related to "features not
> yet implemented". we'd like to use it to annotate the UI elements we've not implemented yet,
> so the later implementation work will replace/remove references to this dialog incrementally.
> this is also the moment we'd like the backend to start storing counts for the "thumbs up"
> clicks.
>
> we'd also like a note for the ongoing work to add feature IDs as necessary.

Three parts:
1. Annotate the currently-unimplemented UI controls as **pending** (§2.1), each with a stable
   feature key, so later feature work removes those annotations one at a time.
2. Stand up the backend the spec already describes: the `feature_interest` counter table
   (upsert once per (workspace, key)) and the `InterestReporter` outbound POST, wired to the
   thumbs-up button — the piece the scaffold's index.html comment defers ("No counter/POST yet").
3. A durable note for ongoing work: allocate feature IDs as controls are marked pending, retire
   them (not the counter rows) as features land.

## Spec basis (already written, item seven of the 2026-07-23 series)

- §2.1 (02-ux-wireframes.md): the four availability states; **pending** = disabled + `[?]`;
  the dialog; acknowledge-in-place (`✓ Noted`); no count shown; second click does not double-count;
  feature keys are a closed, stable vocabulary allocated when a control is first marked pending.
- §5.1 (08-architecture.md): `feature_interest(workspace_id, feature_key, count, last_clicked_at)`,
  PK `(workspace_id, feature_key)`; `routes/feedback.py` → `POST /feature-interest/{feature_key}`;
  `InterestReporter` adapter. Three invariants: failed POST invisible; counter upserts exactly
  once per (workspace, key); unset endpoint disables only the request.
- §5.4 + appendix-a: `feature_interest_url` empty by default; `installation_id` random on first
  run, stored in config, regenerated if cleared.
- §7.5 (15-data-quality-and-limits.md): egress posture; POST body is exactly three fields —
  feature key, app version, installation id; fire-and-forget; id is a persistent pseudonymous
  identifier, not anonymous.

## Current state of the code

- Scaffold only: `app/main.py` serves the static `sample_view()`; no service layer, no DB, no config.
- The dialog already exists in `index.html`; a small script wires `[data-pending-name]` buttons to
  it but explicitly does no counter/POST (that is this increment).
- Two controls already carry `data-pending-name` with a human label but **no feature key**:
  "Allow export to grid" (_panel_params.html) and "Export CSV" (_panel_results.html).
- SQLite/SQLAlchemy are named in the spec but not yet dependencies; no `config.toml` machinery.

## High-level decisions (proposed — awaiting approval)

- D1 — Feature keys as data, not scattered in templates. Carry `feature_key` alongside the
  existing `data-pending-name` on each pending control. Two keys to start: `export_csv`,
  `discharge_allow_export`. Keys are a closed vocabulary; document the list + allocation/retirement
  rule in one place.
- D2 — Minimal persistence now: SQLite via stdlib `sqlite3` (no SQLAlchemy yet) to avoid pulling a
  heavy dependency for one table, OR SQLAlchemy to match the spec's stated stack. (Open question 1.)
- D3 — `workspace_id` present from the start (§5.5 invariant 1). Single local workspace → a constant
  `"local"` until multi-workspace lands.
- D4 — Config: read `feature_interest_url` and `installation_id` from `config.toml` (+ env override);
  generate and write back `installation_id` on first run. POST body = {feature_key, app_version,
  installation_id}. Egress off when URL empty.
- D5 — Endpoint `POST /feature-interest/{feature_key}`: upsert the counter, fire-and-forget POST,
  always return success (204/JSON) regardless of POST outcome. Validate key against the closed set.
- D6 — Frontend acknowledge-in-place: on click, POST via fetch; flip button to `✓ Noted` and show
  the thanks line; reopening a thumbed feature shows Noted; second click does not re-count.

## Resolved with the user

1. Storage: **stdlib `sqlite3`** for the single `feature_interest` table now; SQLAlchemy deferred
   until the full §5.1 schema lands.
2. Location: **repo-local `./data/`** (gitignored) for the SQLite file and `config.toml`,
   overridable via env var.
3. Annotation scope: **not** a broad sweep. Add feature keys to the two controls already marked
   pending (`export_csv`, `discharge_allow_export`), and additionally mark two specific controls
   pending: the **"Also simulate cost savings"** toggle and the **"Upload CSV"** source radio.
   Four pending controls, four keys, total.

## Feature keys (initial closed vocabulary)

| Key | Control | Location |
|---|---|---|
| `export_csv` | Export CSV button | _panel_results.html |
| `discharge_allow_export` | Allow export to grid checkbox | _panel_params.html |
| `simulate_cost` | Also simulate cost savings toggle | _panel_params.html |
| `data_source_csv` | Upload CSV source radio | _panel_data.html |

Keys are stable and not reused. As each feature lands, the control's pending marker is removed;
the counter row for its key is kept.

## Files modified

New:
- `app/config.py` — data-dir + config.toml loader; first-run `installation_id` generation and
  write-back; env overrides (`BATTERY_SIM_DATA_DIR`, `_FEATURE_INTEREST_URL`, `_INSTALLATION_ID`).
- `app/features.py` — the closed `FEATURE_KEYS` vocabulary + allocation/retirement rule.
- `app/db.py` — stdlib `sqlite3` `feature_interest` table; upsert-once `record_interest`.
- `app/interest.py` — `InterestReporter.report`, fire-and-forget POST (urllib in a thread),
  off when URL empty; three-field body.
- `specs/implementation-progress.md` — durable ongoing-work note (pending controls + keys).
- `tests/conftest.py` — put repo root on sys.path for in-process `import app`.
- `tests/test_feature_interest.py` — unit tests for upsert, config, reporter egress.

Modified:
- `app/main.py` — load config at import; `POST /feature-interest/{key}` (204 known, 404 unknown,
  fire-and-forget report).
- `app/templates/index.html` — dialog gains a thanks line; script POSTs, acknowledges in place
  (`✓ Noted`), remembers thumbed keys, second click no-ops.
- `app/templates/_panel_results.html`, `_panel_params.html` — `data-feature-key` on the two
  existing `[?]` buttons.
- `app/templates/_panel_params.html`, `_panel_data.html` — "Also simulate cost savings" and
  "Upload CSV" marked pending (disabled + `[?]`).
- `app/locales/*` — three new msgids (Simulate cost savings, ✓ Noted, thanks line) extracted,
  translated (nl), compiled.
- `.gitignore` — `data/`.
- `specs/README.md` — file table row for implementation-progress.md.

No new dependencies (stdlib `sqlite3`, `tomllib`, `urllib`).

## Verification

- 19 tests pass (`uv run pytest tests/`): 13 browser smoke (incl. two new pending controls +
  acknowledge-in-place) + 6 unit (upsert idempotence, installation_id persistence, reporter
  egress on/off, failure swallowed).
- Manual: URL empty by default; POST body is exactly {feature_key, app_version, installation_id};
  route 204 known / 404 unknown; counter stays 1 on repeat. Screenshot confirms the four
  pending controls render greyed with `[?]`.

## Current status

Complete. Nothing committed, per project convention (commit on request).
