# Hosted multi-user (option B) — investigation and plan

> **Status:** investigated, not chosen. Investigation started 2026-08-04; no code was ever written
> for it. On 2026-08-05 the user chose desktop packaging instead of hosting, on operational-cost
> grounds — see `changelog/20260805-desktop-packaging.md`, which takes finding F1 below as one of
> its two reasons for the direction.
>
> The findings in §2 (F1..F6) remain valid as written and are kept verbatim; only this status note
> was added. The owner-scoping work that preceded this file is not reverted.

## 1. Task specification

Follows directly from `20260804-owner-scoping.md`, which closed the owner-scoping gaps and left
four items for whoever adds authentication. The user has now chosen the destination.

### The user's prompts, verbatim

1. *"we just completed work to clean up user ownership / what work remains to make the app
   multi-user?"*
2. *"we're doing hosted. It's OK to keep the HA Connectivity client-side."*

### What the second prompt settles

Option **(B) hosted multi-tenant**, from the three scopes weighed in `20260804-owner-scoping.md`
§1. That changelog named browser→HA connectivity as the largest open question blocking (B); the
user has answered it: the browser keeps connecting straight to the household's Home Assistant over
`wss://`, and the backend still never sees the token.

That answer is narrower than it first appears and the consequences need working out rather than
assuming — see §3.

## 2. Findings — verified against the tree at `7a92950`

Each item below was checked in the code rather than carried over from the previous changelog.

### F1 — Keeping HA client-side works, but only over HTTPS, and that constrains the user

Confirmed the token never reaches the backend: `app/static/ha_fetch.js` holds `ha.base_url` and
`ha.token` in `localStorage` (`:128`, `:217`), opens `wss://<ha>/api/websocket` from the browser
(`:328-333`), and the ingest WebSocket to *our* backend carries only rows, never the token
(`app/ingest_ws.py` protocol; `main.py:1170` states this). So the "we never see your token" claim
survives hosting **as a backend property**.

What does not survive unchanged is reachability. A hosted page is served over `https:`, and
`ha_fetch.js:781` already derives our own socket scheme from `location.protocol`. But `wsUrl`
(`:328`) defaults a bare `host:8123` to `https://` and yields `wss://`. Consequences, in
descending order of how many users they bite:

1. **Mixed content.** An HTTPS page cannot open `ws://`. Any household whose HA is plain HTTP on
   the LAN — the common default — cannot fetch at all. Today the app is served over `http:` so
   `ws://` is allowed; hosting removes that.
2. **The browser must still reach HA.** Hosted only changes where the *page* comes from, not where
   the browser is. A user opening the app on the household LAN is fine; the same user on mobile
   data is not, unless HA is exposed (Nabu Casa, a tunnel, a port-forward).
3. **HA's own CORS/origin allowlist.** HA restricts which origins may use its WebSocket API. A new
   hosted origin is not on any existing user's allowlist.

None of these is a backend change and none is a blocker for the auth work — but they are user-
facing preconditions that hosting introduces, and they need a decision and a diagnostic, not
silence. **Not yet discussed with the user.**

### F2 — Identity does not exist and is new construction

`get_principal()` (`app/deps.py:100`) returns `Principal(id=workspaces.OWNER_ID)` unconditionally.
There is no users table (schema at `db.py:106-120` is `feature_interest`, `workspace_state`,
`workspaces`), no credential storage, and the only cookie in the codebase is `lang`
(`main.py:1494`). Everything about sessions is to be built.

### F3 — CSRF's central assumption is void once hosted

`app/csrf.py` allows a request when both `Sec-Fetch-Site` and `Origin` are absent, and its own
docstring justifies that by "the user acting on their own machine" and names it as the first thing
to change if the app stops being local-only. It also deliberately leaves `POST /w/{id}/params`
uncovered. Both rest on premises hosting removes.

### F4 — One SQLite file for all tenants, and no per-request isolation

`db.connect()` opens a single file (`db.py:125`, `:207`) that `dataset.py` and `workspaces.py`
layer their tables onto, with a 1-row-per-installation `feature_interest` table. Per-workspace
directories exist (`simconfig_store.py:150`) so *files* are already scoped, but the database is
not. Separately, `run_all` is called synchronously from `results_view.py:1546` on a sync route
(`main.py:773`), so a simulation occupies a threadpool worker for its whole duration —
§5.3's per-workspace `ProcessPoolExecutor` is still absent.

### F5 — `installation_id` telemetry stops meaning one household

`config.py` generates one `installation_id` per install and `interest.py:58` reports it;
`POST /feature-interest/{key}` (`main.py:1133`) is flat and documented as "once per key,
installation-wide". Hosted, one installation is every household, so both the counter and the
outbound report change meaning. This is a semantics decision, not just a scoping fix.

### F6 — Things hosting requires that are not code in this repo

Transport (TLS termination), per-tenant backup, and GDPR posture on household consumption data.
Recorded so they are not mistaken for solved; out of scope for any code plan.

## 3. Scope — not yet agreed

Nothing here is approved and no code has been written. The findings above are what a plan would
have to answer; the plan itself is presented to the user before any implementation, per the
repository rules.

## 4. Current status

Investigation complete. Plan presented to the user for approval; awaiting a decision on the
open questions in §2 (F1's HA-reachability handling, F5's telemetry semantics, and how far the
first increment should go). No code changed.

**Update 2026-08-05.** The decision came back as "not this direction": the user opted for desktop
packaging (`changelog/20260805-desktop-packaging.md`). The open questions above are therefore not
answered and not withdrawn — they are parked, and would have to be answered if hosting is ever
revisited. No code was changed for this plan at any point.
