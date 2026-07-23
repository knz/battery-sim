# Implementation progress — pending controls and feature keys

> **Purpose:** track which specified controls are built, which are still *pending*
> ([§2.1](02-ux-wireframes.md#the-four-availability-states)), and the feature keys the
> pending affordance uses. This is a living implementation record, not a specification — the
> specs state intent; this states how far the build has got.
> **Audience:** implementers.
> **Read with:** [02-ux-wireframes.md §2.1](02-ux-wireframes.md) (the pending affordance),
> [08-architecture.md §5.1](08-architecture.md) (the counter table and reporter).

## The app is built behind a complete UI

The UI is laid out in full from the wireframes; features are implemented one at a time behind
it. A control that is specified but whose machinery is not yet built renders **pending**:
disabled, greyed, with a `[?]` button that opens the "Not built yet" dialog and offers a
thumbs-up. Interest is recorded locally and, if an endpoint is configured, reported outward.

**As you build a feature, remove its control's pending markup** (the `disabled` attribute and
the `[?]` button in the template). Do **not** delete the control's feature key — retire it
(see below), so its counter row keeps its meaning.

## Feature keys — the closed vocabulary

Feature keys are short, stable strings naming pending controls in the counter table and the
POST body. They are allocated when a control is first marked pending and never reused. The
authoritative list is `app/features.py` (`FEATURE_KEYS`); the templates carry the same key in
`data-feature-key="..."`; the route `POST /feature-interest/{key}` rejects unknown keys.

### Currently pending

| Key | Control | Template | Blocked on |
|---|---|---|---|
| `data_source_csv` | "Upload CSV" data source | `_panel_data.html` | CSV ingestion |
| `simulate_cost` | "Simulate cost savings?" choice in the setup band | `_setup_band.html` | cost/pricing model |
| `discharge_allow_export` | "Allow export to grid during D2/D3" | `_panel_params.html` | export dispatch |
| `export_csv` | "Export CSV" of results | `_panel_results.html` | results export |

### Retired (feature shipped, key kept)

*(none yet)*

## How to add a pending control

1. Choose a `<box>_<control>`-shaped key (e.g. `battery_rte`). Add it to `FEATURE_KEYS` in
   `app/features.py` and to the table above.
2. In the template, render the control disabled and add a `[?]` button carrying
   `data-pending-name="<human label>"` and `data-feature-key="<key>"`. The shared dialog and
   its script (in `index.html`) do the rest.
3. Record the allocation in the changelog.

## How to retire a key (feature shipped)

1. Remove the control's `disabled` and its `[?]` button from the template.
2. Move the key's row from *Currently pending* to *Retired* above, and in `app/features.py`
   move it from `FEATURE_KEYS` to `RETIRED_KEYS`. The counter row in the database is left
   untouched — the key must never be reused or repointed, or historical counts become a lie.

## Backend status

Built ([changelog 20260723-pending-affordance-impl](../changelog/20260723-pending-affordance-impl.md)):

- `feature_interest(workspace_id, feature_key, count, last_clicked_at)` in a local SQLite
  file under the data dir (`app/db.py`), upsert-once per `(workspace_id, feature_key)`.
- `InterestReporter` outbound POST (`app/interest.py`): fire-and-forget, off unless
  `feature_interest_url` is set; body is `{feature_key, app_version, installation_id}`.
- `config.toml` loading and first-run `installation_id` generation (`app/config.py`).
- `POST /feature-interest/{key}` (`app/main.py`) and the dialog's acknowledge-in-place script.

Storage note: this uses the standard-library `sqlite3` for the single counter table. The full
six-table schema of [§5.1](08-architecture.md) is expected to move to SQLAlchemy when it lands;
`feature_interest` migrates with it.
