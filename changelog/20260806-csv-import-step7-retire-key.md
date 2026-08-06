# CSV import, step 7 — retire the `data_source_csv` pending key

## Task specification

Step 7 of the CSV-import plan (`changelog/20260805-csv-import.md:336`, elaborated in
`changelog/20260805-csv-import-implementation-brief.md:749`): now that step 6 has built the
"Upload CSV" source, its pending-control key must be retired.

Per the ongoing-work rule at `app/features.py:18-27`:

- move the key from `FEATURE_KEYS` to `RETIRED_KEYS`,
- **keep its title** in `FEATURE_TITLES` — issues filed under the key are still open on GitHub
  and still have to read as something a human recognises,
- never rename the key or repoint it at another control.

Scope is deliberately narrow: this step changes the pending vocabulary and the documentation
that mirrors it. It does not touch the CSV feature itself.

## Why this is a real fix and not bookkeeping

Between step 6 and step 7 the key is an **orphan**: it sits in the active `FEATURE_KEYS`
vocabulary while nothing in any template carries `data-feature-key="data_source_csv"`. Step 6
deleted the disabled stub that used to render it.

That state is benign — an orphan key renders nothing, so no user sees a `[?]` for a feature that
exists. But it is exactly the drift the module's import-time check and its ongoing-work rule are
written to prevent, and leaving it would make `FEATURE_KEYS` a slightly-wrong answer to "what is
still unbuilt?". The orphan was planned and recorded in step 6's changelog rather than left as a
surprise.

## Files modified

- **`app/features.py`** — `data_source_csv` moved from `FEATURE_KEYS` to `RETIRED_KEYS` with a
  comment naming what shipped. Its `FEATURE_TITLES` entry ("Upload CSV") is unchanged in value
  and moved down to the retired group, matching how `simulate_cost` and
  `discharge_allow_export` are already grouped.
- **`docs/specs/implementation-progress.md`** — the `data_source_csv` row moves from the
  "Currently pending" table to "Retired (feature shipped, key kept)". Its old row named
  `_panel_data.html` as the template, which stopped being true in step 6.
- **`tests/test_params_route.py`** — the existing retirement assertions
  (`test_a_retired_key_is_gone_from_the_vocabulary_but_keeps_its_title`, formerly asserting only
  `simulate_cost`) extended to cover `data_source_csv`: absent from `FEATURE_KEYS`, no
  `data-feature-key` for it in the rendered page, title still readable.
- **`tests/test_smoke.py`** — the comment in `test_new_pending_controls_marked` said the key "is
  still in `app/features.py`" and that step 7 would retire it. Updated to record that it now is
  retired, so the comment does not become a false statement about the module.

## Rationales and alternatives

**Extend the existing retirement test rather than write a new one.** `test_params_route.py`
already had a test pinning exactly this three-part property for `simulate_cost`. Adding a second
key to it keeps one place that answers "what does retirement mean", instead of two tests that
could drift apart. The loop is written over a list so a third retirement is a one-line change.

**Assert the absence of the rendered attribute, not just the vocabulary.** `key not in
FEATURE_KEYS` alone would pass even if a template still carried the attribute — the `[?]`
affordance would then be live for a shipped feature, pointing users at an issue form for
something they can already use. Checking the HTML too is what makes the test about the
user-visible consequence.

**Considered and rejected: deleting the key.** The module's rule forbids it, and for a reason
that outlives this change — an issue filed months ago under `data_source_csv` still has to be
traceable to the control it was about.

## Obstacles and solutions

None. The change is mechanical and had a worked precedent in the same file.

## Current status

Complete. Steps 1–7 of the CSV-import plan are done; step 8 (test the CSV import path) remains,
carrying the two coverage gaps deferred from step 6 and harness fixtures 22/22a.

Verification run: the feature-key tests plus the pending-affordance smoke tests, and a grep
confirming no template references the retired key.
