/*
 * ha_fetch.js — browser-side Home Assistant fetch + the slot-first source-picker drawer
 * (docs/specs/06-home-assistant-ingestion.md, docs/specs/02-ux-wireframes.md §2.2).
 *
 * Two responsibilities live here now:
 *
 *  1. The shared Home Assistant connection and browser-side fetch. The data import runs in the
 *     browser, not the backend: the user's browser is the only thing that can reach their (often
 *     LAN-only, self-signed) HA instance, and keeping the fetch here means the long-lived access
 *     token never leaves the browser (specs §7.5). The token is held in localStorage and sent
 *     only to the user's own HA. The connection is SHARED across slots: the user configures it
 *     once (URL + token + Test connection) in the #ha-config-dialog MODAL, opened by a "Configure"
 *     button beside the Home Assistant radio in the drawer — there is no panel-level connection
 *     card any more. The listed statistic ids are then reused for every HA-source slot. Fetched
 *     rows stream to our backend over WS /w/{workspace_id}/data/ingest/ws (app/ingest_ws.py),
 *     which normalises and persists them. The scoped path is not built here — the roster carries
 *     it whole in data-ingest-ws, so this file never has to know the URL layout.
 *
 *  2. The slot-first source-picker drawer. Each slot row (templates/_data_roster.html) has a
 *     "Choose source…" button carrying the slot name, its kind (energy/price), and its source
 *     list (data-slot-sources). A click opens the shared right-side drawer (#source-drawer in
 *     workspace_data.html) listing those sources as radios. Picking a source:
 *       * home_assistant (browser_fetch) → the drawer reveals a single entity <select>
 *         (#drawer-entity-select), populated for THIS slot from the shared connection's listing,
 *         plus a "Configure" button that opens the shared connection modal. The entity picker is
 *         disabled and Confirm is blocked until the connection tests OK; Confirm then needs a
 *         chosen entity too, so a committed HA slot is always fetchable.
 *       * energy_charts (backend_load)   → the default staged for the price_spot slot. Confirm
 *         only STAGES the choice; the slot is reified
 *         server-side by the next Fetch history, as a `backend_load` message on the ingest WS.
 *         (A POST /w/{id}/data/slot/{slot}/load route does exist, but the all-or-nothing reify
 *         model puts that work in the fetch instead — see "Staged-then-confirm" below. Nothing
 *         in this file calls that route; only the tests do.)
 *       * csv_upload (backend_load)      → the drawer reveals the per-slot binding controls
 *         (#drawer-csv-binding: File, Column, Unit), plus an "Upload…" button that opens the
 *         shared upload modal (#csv-upload-dialog). The FILE is server state shared across slots
 *         and an upload survives Cancel, exactly as a tested HA connection does; the BINDING is
 *         per-slot, browser-local (D-BIND) and staged like everything else. Confirm is blocked
 *         until the binding names both a file and a column, which is what stops a bindingless CSV
 *         slot from failing an entire all-or-nothing fetch. A column the server flagged as looking
 *         like a cumulative meter register gets small print under the picker and nothing more —
 *         Confirm stays enabled (`updateCsvCumulativeWarning`).
 *
 *     A row may also carry an ⓘ info affordance (SlotSpec.info, specs §4.1). A delegated click on
 *     any .slot-info-btn fills the shared #slot-info-dialog from the button's data-info-title/body
 *     (rendered and translated server-side) and opens it — the same shared-dialog pattern as
 *     #pending-dialog, with no per-slot wiring.
 *
 * Staged-then-confirm model (the crux). The drawer is TRANSACTIONAL: nothing commits on mere
 * selection or on closing. While the drawer is open, all in-drawer controls (source radios, entity
 * <select>) write ONLY to a drawer-local `draft = { slot, source, statId, uploadId, column, unit }`
 * (the last three are the CSV binding — see carrier 2 below). The committed per-slot
 * state lives in `slotState[name] = { source, statId, uploadId, column, unit, kind }` and is the ONLY thing updateSlotButton
 * and mappedSlots read. openDrawer seeds `draft` from the committed slotState (so the current choice
 * shows pre-selected) without touching slotState; a slot with NO committed source gets a default
 * staged into the draft by renderSourceList (defaultSourceFor — the preset Energy-Charts source for
 * the spot-price slot, Home Assistant for every other slot that offers it), which
 * keeps the checked radio and draft.source in agreement and lets the entity <select> populate. That
 * staging is still not a commit. A single Confirm button commits:
 *       * HA source   → writes draft → slotState, refreshes the row label, closes. No reload.
 *       * backend     → the SAME thing, minus the entity. Neither branch calls the server: the
 *                       drawer is a pure staging surface and Fetch history reifies both kinds.
 * Cancel / Escape / ✕ / backdrop DISCARD: closeDrawer reverts to the committed state and never
 * mutates slotState or the row label. slotState is seeded from each .slot-source-btn's data-*
 * attributes at load (the committed initial state). mappedSlots() (used by Fetch history) reads
 * slotState — the HA slots whose statId is set — so the fetch depends only on committed state.
 *
 * Surviving the reload (localStorage ha.slots.<workspace> + a source GENERATION). A successful
 * Fetch history ends in a full window.location.reload() so the configure-data screen re-renders
 * from the persisted dataset. That reload drops all in-memory slotState, and the persisted
 * view-model carries no re-selectable statistic id for an unfetched slot — so without help a
 * STAGED HA slot's chosen entity and source are lost across any reload, including a plain refresh.
 *
 * Two things carry a source choice across a reload, split by whether the slot has been FETCHED:
 *
 *  1. Fetched slots → SERVER-SIDE. When a fetch persists a series, its HA statistic id travels in
 *     the WS `series` frame and is stored in series_meta alongside the source key. The view-model
 *     then renders the slot's source AND entity (the id) from the dataset, so a fetched HA slot
 *     shows "Home Assistant · <id>" after any reload with no client state involved. The statistic
 *     id is not secret (only the token is, §7.5), so persisting it server-side is fine.
 *
 *  2. Pre-fetch customizations → localStorage ha.slots.<workspace>, reconciled by a generation
 *     number (specs §2.2). These are choices the user made but has NOT yet fetched: HA picked for a
 *     data-less slot, or a source override on a slot the server fills differently. The server holds
 *     a per-workspace `source_generation`, bumped ONLY when a fetch persists a new dataset — never
 *     by a backend_load Confirm — and rendered into #source-generation. Confirm saves
 *     { gen, slots: { <slot>: {source, statId, uploadId, column, unit} } } tagged with the current
 *     generation. On load:
 *       * local gen === server gen → USE LOCAL wholesale (source, statId AND the CSV binding): the
 *         pre-fetch choice survives the reload.
 *       * server gen  >  local gen → a fetch has happened since (here or on another client in the
 *         same workspace); the server is authoritative, the stale local slots are dropped.
 *     A fetch advances the generation, so a pre-fetch entry saved beforehand is superseded by the
 *     freshly-persisted server state (which now renders that slot itself, per 1).
 *
 *     The three CSV fields — uploadId, column, unit — are the per-slot BINDING for an uploaded wide
 *     CSV (decision D-BIND of the CSV-import brief). They live here, and only here, for the reason
 *     this list exists: a binding is a choice the user has made but has NOT yet fetched, which is
 *     category 2 verbatim. An uploaded FILE is server state (app/uploads.py, one row and one file per
 *     upload); which column of it feeds which slot is not, and there is no server table for it. So a
 *     binding inherits this category's reconciliation unchanged, and inherits its limits too:
 *       * it does not follow the user to another browser or device (same as the HA entity choice and
 *         the URL/token — the uploaded file DOES follow them, only the mapping does not);
 *       * a fetch supersedes it rather than preserving it, because the fetch writes real provenance
 *         per 1 above;
 *       * deleting an upload cannot clear it server-side, so a stale binding fails validation on the
 *         next fetch (app/main.py `delete_upload` records why there is no cascade) and the drawer
 *         drops entries whose upload is no longer listed.
 *     The binding travels to the server on the ingest WS `backend_load` message and nowhere else,
 *     which is what keeps Confirm a pure client action — see stagedBackendSlots() below.
 *
 *     Server-side, the `upload_id` in that message is therefore CLIENT-SUPPLIED and is validated
 *     against `uploads.get(workspace_id, upload_id)` before anything is read. Nothing here should be
 *     read as a trust boundary: this file is the convenience layer, not the check.
 *
 * localStorage is browser-local by design (same as the URL/token): a PRE-FETCH customization does
 * not follow you across browsers. A FETCHED slot does, because it lives server-side.
 *
 * Workspace scoping (docs/specs/20-workspaces-ux.md §2′.11, docs/specs/08-architecture.md §5.1). The data
 * routes are under `/w/{id}/…`, and localStorage splits along the same line — but not uniformly,
 * because the two things stored here answer different questions:
 *
 *   * The CONNECTION (ha.base_url, ha.token) stays GLOBAL. It answers "where is this household's
 *     Home Assistant", which every analysis of that household shares.
 *   * The SLOT STORE is keyed `ha.slots.<workspace id>`. It answers "which entity feeds which role
 *     in THIS analysis", and a single key would make a mapping staged in one analysis look staged
 *     in all of them. The generation tag cannot substitute for the split: it compares an integer
 *     against this workspace's `source_generation`, and another workspace's counter is a different
 *     integer that can collide by coincidence.
 *
 * The ingest WebSocket path is not built here at all — the roster's data-ingest-ws carries the
 * whole scoped path, rendered server-side (_data_roster.html), so this file keeps knowing nothing
 * about the URL layout. It reads <body data-workspace-id> only to key the store.
 *
 * A pre-workspaces global `ha.slots` from an older build is DISCARDED rather than adopted into
 * `local` — the reasoning is beside the removal, below.
 *
 * User actions. Test connection lives in the #ha-config-dialog modal; Fetch history is the
 * roster's own button (_data_roster.html):
 *   Test connection  — open wss://<ha>/api/websocket, auth, recorder/list_statistic_ids, store
 *                       the listed ids (energy ids from "sum", mean ids from "mean"), and if a
 *                       drawer is open for an HA slot, (re)populate its entity <select>. Enables
 *                       Fetch history.
 *   Fetch history    — for each HA slot with a chosen statId in slotState,
 *                       recorder/statistics_during_period over the full window at period "hour",
 *                       plus period "5minute" over the trailing HA_FINE_WINDOW_DAYS (specs §4.3).
 *                       Stream to the backend, then reload (specs §3.5 LOAD_SUCCEEDED).
 *
 * No build step, no framework — plain DOM, matching the app's frontend posture (specs §5.1).
 */
(function () {
  "use strict";

  // --- tunables (specs §4.3) ---------------------------------------------------------------
  var HA_FINE_WINDOW_DAYS = 10;   // trailing days fetched at 5-minute resolution
  var HA_CHUNK_DAYS = 90;         // max days per statistics_during_period call (frame-size cap)
  var HISTORY_DAYS = 730;         // how far back to request hourly (long-term stats never purge)
  // The connection stays GLOBAL, deliberately (docs/specs/20-workspaces-ux.md §2′.11): one household,
  // one Home Assistant. Every workspace analyses the same house's data, so re-entering the URL and
  // the long-lived token per analysis would be friction with nothing behind it. They remain
  // browser-only either way (§7.5).
  var LS_URL = "ha.base_url";
  var LS_TOKEN = "ha.token";

  // The uploaded-CSV source's descriptor key, and the unit its binding defaults to.
  //
  // The key is `CsvSource`'s (`app/sources/csv_source.py`) and is stable by contract — it is
  // persisted with a slot's chosen source (specs §2.2), so it can be compared as a literal here. It
  // is spelled once, as a name, because several places need it: the store's two completeness gates,
  // the staged-binding builder, the drawer's Upload button and binding controls, the Confirm gate,
  // and the row label.
  //
  // `kWh` is the drawer's default radio and `CsvBinding`'s own default, so a stored entry without a
  // unit means kWh rather than "incomplete". Kept in agreement with `csv_wide.UNIT_FACTORS`, whose
  // only other member is `Wh`; the server rejects anything else by name, so a drifted value here
  // fails loudly rather than silently mis-scaling.
  var CSV_SOURCE_KEY = "csv_upload";
  var DEFAULT_CSV_UNIT = "kWh";

  // The slot roster carries data-ingest-ws (it used to live on the removed #ha-connection card).
  // Its presence also gates the whole module: no roster → panel not on this page.
  var conn = document.getElementById("slot-roster");
  if (!conn) return;  // panel not on this page

  // Which workspace this page is showing (workspace_data.html's <body data-workspace-id>). The routes are
  // workspace-scoped (docs/specs/08-architecture.md §5.1); the ingest WebSocket path is rendered
  // server-side onto the roster's data-ingest-ws, so this id is needed here only to key the slot
  // store below.
  var WORKSPACE_ID = document.body.getAttribute("data-workspace-id") || "";

  // Per-slot source selections, browser-local (specs §7.5, same posture as URL/token).
  // A JSON object { gen: <int>, slots: { <slot>: { source, statId, uploadId, column, unit } } },
  // tagged with the source generation the client saw when it saved (see the file header for the
  // reconcile rule). It exists so a slot's chosen source AND whatever that source needs to be
  // loadable survive the full-page reload a fetch triggers.
  //
  // Two kinds of entry, and the difference is which extra fields are meaningful:
  //   * home_assistant → `statId`, the chosen entity. Nothing else is needed; the connection is
  //     global and lives under its own keys.
  //   * csv_upload      → `uploadId`, `column`, `unit`: the per-slot BINDING (D-BIND). The FILE is
  //     server-side; which of its columns feeds this slot is not, and this is its only home.
  // A backend source that needs neither (energy_charts, entsoe) stores just its key. Those were
  // once not stored at all, on the grounds that they were "already server-side" — that was only
  // ever true of a slot that had been FETCHED, so the reasoning was wrong even then, and the CSV
  // binding makes it plainly wrong: a staged binding is nowhere else.
  //
  // The key is PER WORKSPACE (§2′.11) — `ha.slots.<workspace id>`. Unlike the connection, a slot
  // mapping is a statement about one analysis: which entity feeds which role here. A single global
  // key would make a mapping staged in one analysis appear staged in every other, and the staleness
  // rule cannot catch that, because it compares generations rather than workspaces — the store's
  // `gen` would be another workspace's `source_generation`, which is a different counter that
  // happens to be an integer. `source_generation` is per-workspace for the same reason — §5.5's
  // invariant 1 now holds with no exceptions at all.
  var LS_SLOTS = "ha.slots." + WORKSPACE_ID;

  // The Home Assistant connection UI now lives in the #ha-config-dialog modal (workspace_data.html),
  // opened by the drawer's "Configure" button. The field IDs are unchanged, so these bindings
  // resolve exactly as before — only their host node moved from the panel card into the modal.
  var haConfigDialog = document.getElementById("ha-config-dialog");
  var urlInput = document.getElementById("ha-base-url");
  var tokenInput = document.getElementById("ha-token");
  var testBtn = document.getElementById("ha-test-btn");
  var statusEl = document.getElementById("ha-status");
  var fetchBtn = document.getElementById("ha-fetch-btn");
  var fetchStatus = document.getElementById("ha-fetch-status");
  var progressEl = document.getElementById("ha-fetch-progress");

  // Slot info ⓘ affordance (specs §4.1). A single #slot-info-dialog (page level, in workspace_data.html,
  // so it survives every fragment swap and serves panels ①, ② and ③ alike) serves
  // every row's ⓘ button; a delegated click reads the (server-side, already-translated) title and
  // body off the clicked .slot-info-btn's data-* and opens the modal — same shared-dialog pattern
  // as #pending-dialog. Generic: any row whose view-model carries `info` renders a button, so no
  // per-slot wiring is needed here.
  var infoDialog = document.getElementById("slot-info-dialog");
  var infoTitle = document.getElementById("slot-info-title");
  var infoBody = document.getElementById("slot-info-body");
  if (infoDialog && infoTitle && infoBody) {
    document.addEventListener("click", function (ev) {
      var btn = ev.target.closest && ev.target.closest(".slot-info-btn");
      if (!btn) return;
      infoTitle.textContent = btn.getAttribute("data-info-title") || "";
      infoBody.textContent = btn.getAttribute("data-info-body") || "";
      if (typeof infoDialog.showModal === "function") infoDialog.showModal();
      else infoDialog.setAttribute("open", "");
    });
  }

  // Per-slot state, seeded from each slot's source button (no per-row DOM select any more).
  //   slotState[name] = {
  //     source: <key|null>, statId: <string>,          // Home Assistant's entity choice
  //     uploadId: <string>, column: <string>, unit: <"kWh"|"Wh">,   // the CSV binding (D-BIND)
  //     kind: "energy"|"price"
  //   }
  // The three CSV fields are empty strings (and `unit` its default) on every slot that is not bound
  // to an uploaded CSV, so the shape is uniform and no reader has to test for their presence — see
  // the file header's carrier 2 for why the binding lives here at all. Filled below once we can read
  // the .slot-source-btn nodes; kind derives from the slot name the same way the old template did
  // ('price' in name ? price : energy).
  var slotState = {};
  function slotKind(name) { return /price/.test(name || "") ? "price" : "energy"; }

  // Runtime i18n (rendered server-side into #drawer-i18n so gettext extracts the msgids).
  var I18N = {};
  try {
    var i18nEl = document.getElementById("drawer-i18n");
    if (i18nEl) I18N = JSON.parse(i18nEl.textContent);
  } catch (e) { I18N = {}; }
  function t(key, fallback) { return I18N[key] || fallback; }

  // Interpolating counterpart to t(), mirroring the server-side `_('… %(x)s …') | interpolate(…)`
  // pattern (app/i18n.py). Status strings that carry runtime values — a slot name, a progress
  // count — must not be built by concatenating translated fragments: word order differs between
  // languages, and a fragment on its own is not translatable. One msgid with named placeholders
  // keeps the whole sentence in the catalog and lets the translator move the values.
  function ti(key, fallback, values) {
    return t(key, fallback).replace(/%\((\w+)\)s/g, function (m, name) {
      return Object.prototype.hasOwnProperty.call(values, name) ? values[name] : m;
    });
  }

  // Restore the last URL/token from localStorage (browser-local; never server-side, §7.5).
  urlInput.value = localStorage.getItem(LS_URL) || urlInput.value || "";
  tokenInput.value = localStorage.getItem(LS_TOKEN) || "";

  // The server's current source generation, rendered into #source-generation (specs §2.2). Bumped
  // only by a persisted HA fetch. NaN/absent is treated as 0 so a broken tag falls back to "server
  // wins" rather than accidentally matching a stored generation.
  var serverGen = 0;
  try {
    var genEl = document.getElementById("source-generation");
    if (genEl) {
      var g = JSON.parse(genEl.textContent);
      serverGen = (typeof g === "number" && isFinite(g)) ? g : 0;
    }
  } catch (e) { serverGen = 0; }

  // The pre-workspaces global key. An installation upgraded across this change may still hold one,
  // and it is DISCARDED rather than migrated onto `ha.slots.local`. Two reasons, and the second is
  // the load-bearing one:
  //
  //   * What it holds is a PRE-FETCH staging convenience — a source, and for HA an entity, chosen
  //     but not yet fetched. Losing it costs one re-selection in a drawer the user is already
  //     standing in. Nothing fetched is in here; that lives in series_meta and renders from the
  //     dataset regardless.
  //   * Adopting it would be a silent write into a NAMED workspace on someone else's behalf. The
  //     generation tag does not make that safe: it would carry over intact and match, so a mapping
  //     staged before the upgrade would come back looking deliberately staged in `local` — exactly
  //     the "appears staged in another analysis" confusion §2′.11 asks us to prevent, arriving from
  //     the time axis instead of the workspace axis.
  //
  // Removed rather than left to sit, so it does not linger as a key nothing reads. This is a
  // one-time cleanup; once no browser holds it the removal is a no-op and can go.
  try { localStorage.removeItem("ha.slots"); } catch (e) { /* ignore */ }

  // localStorage-backed slot selections, tagged with the generation they were saved at.
  //   { gen: <int>, slots: { <slot>: { source, statId, uploadId, column, unit } } }
  // loadSlotStore returns a normalised object (empty slots + gen -1 on any parse error, so it can
  // never equal a real serverGen ≥ 0). saveSlotStore writes the locally-customized slots out of
  // slotState and stamps the CURRENT serverGen.
  //
  // loadSlotStore deliberately does NOT validate the per-slot objects, only the envelope. What the
  // fields mean is source-specific and grows (statId, then the three CSV binding fields), so a
  // per-field check here would need updating for every source and would silently drop an entry
  // written by a newer build of this same file. The seed loop below reads the fields it knows and
  // defaults the rest, and the server validates anything that reaches it — which is where a
  // nonsense uploadId is caught, not here.
  function loadSlotStore() {
    try {
      var obj = JSON.parse(localStorage.getItem(LS_SLOTS) || "null");
      if (obj && typeof obj === "object" && typeof obj.gen === "number" && obj.slots) {
        return { gen: obj.gen, slots: obj.slots };
      }
    } catch (e) { /* fall through */ }
    return { gen: -1, slots: {} };
  }
  // Slots the user has customized THIS session (a drawer Confirm), plus any carried over from a
  // still-current local store. Only these are written to localStorage — NOT slots whose statId was
  // seeded from the server (data-slot-stat-id). Persisting a server-seeded slot would duplicate
  // authoritative state into the store and let it wrongly "win" as a pre-fetch customization.
  var locallyCustomized = {};

  // Is this object's CSV binding complete enough to be worth anything? "A file AND a column" — and
  // `unit` deliberately not, because it has a documented default (kWh: DEFAULT_CSV_UNIT, the
  // drawer's pre-checked radio, and `CsvBinding`'s own), so an object without one is complete rather
  // than partial.
  //
  // **One predicate, three callers**, and they are three genuinely different objects that happen to
  // share these field names: the drawer's `draft` (is Confirm allowed?), a `slotState` entry (should
  // `saveSlotStore` write it?), and a raw `localStorage` entry (should the seed loop restore it?).
  // Written three times, they would drift — and the drift is not cosmetic. The three answers have to
  // agree because they are the same question asked at three moments of one lifecycle: what Confirm
  // permits must be exactly what the store persists, which must be exactly what a reload restores.
  // A gate that let one of them through alone would either lose a binding the user made or restore
  // one they could not have made, and an incomplete binding that reaches a fetch fails the WHOLE
  // all-or-nothing reify, HA slots included.
  //
  // It takes the object rather than two arguments so a caller cannot silently pass the fields in the
  // wrong order, and so adding a fourth required field is one edit here.
  function csvBindingComplete(o) {
    return !!(o && o.uploadId && o.column);
  }

  // Persist the locally-customized slots, tagged with the generation the client currently sees.
  // This covers only PRE-FETCH customizations: once a slot has been fetched, its source AND entity
  // are persisted server-side (series_meta) and render from the dataset, so the store is not what
  // carries a fetched slot across a reload.
  //
  // The gate per source kind is "would this entry be FETCHABLE if restored?", which is why the two
  // configurable sources are gated and the rest are not:
  //   * home_assistant → needs a chosen entity, so it is stored only once `statId` is set.
  //   * csv_upload     → needs a complete binding: `csvBindingComplete` above, which is the same
  //     predicate `usableStoreEntry` and the drawer's Confirm gate use.
  // Storing a partial entry would restore a slot that looks staged and then fails the next fetch —
  // and under the all-or-nothing reify contract that failure takes the whole fetch with it, HA slots
  // included, so a half-written binding is not a cosmetic problem.
  function saveSlotStore() {
    var slots = {};
    Object.keys(locallyCustomized).forEach(function (name) {
      var st = slotState[name];
      if (!st || !st.source) return;
      if (st.source === "home_assistant") {
        if (st.statId) slots[name] = { source: "home_assistant", statId: st.statId };
      } else if (st.source === CSV_SOURCE_KEY) {
        if (csvBindingComplete(st)) {
          slots[name] = {
            source: CSV_SOURCE_KEY,
            statId: "",
            uploadId: st.uploadId,
            column: st.column,
            unit: st.unit || DEFAULT_CSV_UNIT
          };
        }
      } else {
        // A backend source with nothing to configure (energy_charts, entsoe): the key is the whole
        // choice, and it is fetchable the moment it is picked.
        slots[name] = { source: st.source, statId: "" };
      }
    });
    try {
      localStorage.setItem(LS_SLOTS, JSON.stringify({ gen: serverGen, slots: slots }));
    } catch (e) { /* quota; ignore */ }
  }

  // The READ-side counterpart of saveSlotStore's completeness gate: "is this stored entry usable as
  // a staged choice?". saveSlotStore only decides what THIS build writes, and the seed loop reads
  // entries this build did not write — a store hand-edited in devtools, or one left by an older
  // build whose gate differed. So the write-side gate cannot be the only one, and the read side is
  // the robust place for it: everything downstream of the seed loop (slotState → stagedBackendSlots
  // → the backend_load frame) treats what it finds as already vetted.
  //
  // The rule is `csvBindingComplete`, the one predicate this file's three completeness gates share
  // (see its own comment for why they must agree): an entry for that source is usable only once it
  // names BOTH a file and a column.
  //
  // Only csv_upload is gated here, deliberately, even though saveSlotStore also requires a statId
  // before writing a home_assistant entry. An entry with an empty or HA-without-entity source is
  // already harmless — mappedSlots() skips a slot with no statId and stagedBackendSlots() skips one
  // whose source is not a backend key, so neither stages anything and neither can fail a fetch — and
  // it is a MEANINGFUL state to restore: an entry with an empty source is how a user clears a slot
  // the server committed, which is what `_make_slot_pristine` in tests/test_smoke.py relies on.
  // Rejecting those here would silently re-apply the server's choice over the user's deletion.
  //
  // An unusable entry is dropped WHOLE — the slot falls back to the server's committed source, the
  // same state as if there were no local entry at all — rather than being kept minus its binding.
  // Keeping `source: "csv_upload"` with no binding was the alternative and is worse in both places
  // it shows up: the row would read as CSV-configured while `stagedBackendSlots` sent an empty
  // upload_id, which the server rejects and which, under the all-or-nothing reify contract, fails
  // the ENTIRE fetch including every HA slot. Dropping to the server's choice leaves the slot in
  // exactly the state the drawer already knows how to show and the user already knows how to fix.
  // (The drawer now offers a real csv_upload radio, so the user CAN correct such a slot by hand —
  // but that is a reason to leave it correctable, not a reason to restore it half-bound.)
  function usableStoreEntry(entry) {
    if (!entry) return false;
    if (entry.source === CSV_SOURCE_KEY) return csvBindingComplete(entry);
    return true;
  }

  // Seed slotState from the slot source buttons, reconciled against localStorage by generation
  // (see the file header). The button carries the SERVER's committed choice: data-slot-source and,
  // for a fetched HA slot, data-slot-stat-id (the persisted statistic id — this is what makes a
  // fetched slot render its entity after a reload with no client state). A localStorage entry only
  // overrides that when it applies: its generation still matches the server's (a PRE-FETCH
  // customization not yet superseded by a fetch). When the server's generation is newer, the store
  // is stale — the server choice wins and the store is cleared.
  var slotStore = loadSlotStore();
  var storeCurrent = slotStore.gen === serverGen;  // local customization still applies?
  Array.prototype.slice.call(document.querySelectorAll(".slot-source-btn")).forEach(function (btn) {
    var name = btn.getAttribute("data-slot");
    if (!name) return;
    var serverSource = btn.getAttribute("data-slot-source") || null;
    var serverStatId = btn.getAttribute("data-slot-stat-id") || "";
    var local = storeCurrent ? slotStore.slots[name] : null;
    if (local && !usableStoreEntry(local)) local = null;
    if (local) {
      // The CSV binding fields are carried across verbatim (defaulting only `unit`, which has one).
      // They have no server-side counterpart to fall back to — unlike `statId`, which a fetched slot
      // renders from series_meta — so dropping them here would lose the binding on every plain
      // refresh, which is the whole thing this store exists to prevent. Verbatim is safe because
      // `usableStoreEntry` above has already rejected a csv_upload entry missing either of them.
      slotState[name] = {
        source: local.source,
        statId: local.statId || "",
        uploadId: local.uploadId || "",
        column: local.column || "",
        unit: local.unit || DEFAULT_CSV_UNIT,
        kind: slotKind(name)
      };
      // A store entry at the current generation is a pre-fetch customization: keep tracking it so a
      // later save (from customizing another slot) preserves it rather than dropping it.
      locallyCustomized[name] = true;
    } else {
      // No local entry: the server's committed choice. There is deliberately no server-side binding
      // to read here — under D-BIND a CSV binding is browser-local, so a slot whose server source is
      // `csv_upload` (i.e. one that HAS been fetched from a CSV) shows its provenance from the
      // dataset and needs no binding to render. It needs one again only to be re-fetched.
      slotState[name] = {
        source: serverSource,
        statId: serverStatId,
        uploadId: "",
        column: "",
        unit: DEFAULT_CSV_UNIT,
        kind: btn.getAttribute("data-slot-kind") || slotKind(name)
      };
    }
  });
  // Drop a stale store (older generation) so it does not shadow a future save at the new gen.
  if (!storeCurrent && slotStore.gen !== -1) {
    try { localStorage.removeItem(LS_SLOTS); } catch (e) { /* ignore */ }
  }

  // -----------------------------------------------------------------------------------------
  // HA WebSocket client. One connection per operation; HA closes idle sockets, and the fetch is
  // short-lived, so there is no pooling to do here.
  // -----------------------------------------------------------------------------------------
  function wsUrl(base) {
    // Accept "https://host:8123" or "host:8123"; derive the wss websocket endpoint.
    var u = base.trim().replace(/\/+$/, "");
    if (!/^https?:\/\//.test(u)) u = "https://" + u;
    return u.replace(/^http/, "ws") + "/api/websocket";
  }

  function HaClient(base, token) {
    this.url = wsUrl(base);
    this.token = token;
    this.ws = null;
    this.id = 0;
    this.pending = {};  // request id → {resolve, reject}
  }

  HaClient.prototype.connect = function () {
    var self = this;
    return new Promise(function (resolve, reject) {
      var ws;
      try {
        ws = new WebSocket(self.url);
      } catch (e) {
        reject(new Error(ti("ws_open_failed", "Could not open a WebSocket to %(url)s.", { url: self.url })));
        return;
      }
      self.ws = ws;
      ws.onerror = function () {
        reject(new Error(ti("ws_connect_failed",
          "Connection failed. Check the URL, and that your browser trusts the certificate "
          + "(open %(url)s once to accept it).",
          { url: self.url.replace(/^ws/, "http") })));
      };
      ws.onclose = function () {
        Object.keys(self.pending).forEach(function (k) {
          self.pending[k].reject(new Error(t("ws_closed", "connection closed")));
        });
        self.pending = {};
      };
      ws.onmessage = function (ev) {
        var msg = JSON.parse(ev.data);
        if (msg.type === "auth_required") {
          ws.send(JSON.stringify({ type: "auth", access_token: self.token }));
        } else if (msg.type === "auth_ok") {
          resolve();
        } else if (msg.type === "auth_invalid") {
          reject(new Error(t("ha_token_rejected", "Home Assistant rejected the token.")));
        } else if (msg.type === "result") {
          var p = self.pending[msg.id];
          if (p) {
            delete self.pending[msg.id];
            if (msg.success) p.resolve(msg.result);
            else p.reject(new Error((msg.error && msg.error.message) || t("ha_error", "HA error")));
          }
        }
      };
    });
  };

  HaClient.prototype.call = function (payload) {
    var self = this;
    return new Promise(function (resolve, reject) {
      self.id += 1;
      payload.id = self.id;
      self.pending[self.id] = { resolve: resolve, reject: reject };
      self.ws.send(JSON.stringify(payload));
    });
  };

  HaClient.prototype.close = function () {
    if (this.ws) try { this.ws.close(); } catch (e) { /* ignore */ }
  };

  // -----------------------------------------------------------------------------------------
  // Test connection: list ids once; the ids are shared across all HA slots. The drawer's single
  // entity <select> is populated per slot on open / on picking HA (fillDrawerEntitySelect).
  // -----------------------------------------------------------------------------------------
  var statIds = { energy: [], price: [] };  // populated by testConnection
  var haConnected = false;                  // set true after a successful test

  function setStatus(el, text, cls) {
    el.textContent = text;
    el.className = "text-sm " + (cls || "text-base-content/60");
  }

  async function testConnection() {
    var base = urlInput.value.trim();
    var token = tokenInput.value.trim();
    if (!base || !token) {
      setStatus(statusEl, t("need_url_token", "Enter a base URL and token first."), "text-warning");
      return;
    }
    localStorage.setItem(LS_URL, base);
    localStorage.setItem(LS_TOKEN, token);
    setStatus(statusEl, t("connecting", "Connecting…"), "text-base-content/60");
    testBtn.disabled = true;

    var client = new HaClient(base, token);
    try {
      await client.connect();
      var sums = await client.call({ type: "recorder/list_statistic_ids", statistic_type: "sum" });
      var means = await client.call({ type: "recorder/list_statistic_ids", statistic_type: "mean" });
      statIds.energy = sums.map(function (s) { return s.statistic_id; }).sort();
      statIds.price = means.map(function (s) { return s.statistic_id; }).sort();
      haConnected = true;
      // If the drawer is open with HA staged in the draft, its entity select was showing the
      // "configure first" hint; repopulate it now, refresh the Configure button, and re-evaluate
      // Confirm (now unlockable once an entity is chosen). Otherwise the ids are just stored for
      // the next drawer open. The connection is shared, so this state carries to every HA slot.
      if (draft.slot && draft.source === "home_assistant") {
        fillDrawerEntitySelect(draft.slot);
      }
      updateHaConfigButton();
      updateConfirmEnabled();
      setStatus(statusEl, ti("connected_counts",
        "✓ Connected · %(energy)s energy + %(price)s measurement statistics",
        { energy: statIds.energy.length, price: statIds.price.length }), "text-success");
      // Fetch enablement follows what is STAGED, not the connection alone (a backend-only config
      // is fetchable without a connection; a tested connection with nothing staged is not).
      updateFetchEnabled();
    } catch (e) {
      setStatus(statusEl, ti("failed_reason", "✗ %(reason)s", { reason: e.message }), "text-error");
      updateFetchEnabled();
    } finally {
      client.close();
      testBtn.disabled = false;
    }
  }

  // Populate the drawer's single entity <select> for one slot from the listed ids (kind-
  // appropriate: energy ids for energy slots, mean ids for price slots). Preselect the DRAFT's
  // chosen id, else a best-effort guess. When not connected yet, show a single disabled hint
  // instead of ids (the note tells the user to connect above). Writes only to the draft — the
  // guess is a staged default, visible in the open dropdown but not committed until Confirm.
  function fillDrawerEntitySelect(slotName) {
    if (!drawerEntitySelect) return;
    var kind = slotKind(slotName) === "price" ? "price" : "energy";
    var sel = drawerEntitySelect;

    // Reset to a single leading option, then either the hint or the ids.
    while (sel.options.length) sel.remove(0);
    if (!haConnected) {
      var hint = document.createElement("option");
      hint.value = "";
      hint.textContent = t("connect_first", "Configure the connection first");
      sel.appendChild(hint);
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    var none = document.createElement("option");
    none.value = ""; none.textContent = t("none", "— none —");
    sel.appendChild(none);
    statIds[kind].forEach(function (id) {
      var opt = document.createElement("option");
      opt.value = id; opt.textContent = id;
      sel.appendChild(opt);
    });
    // Preselect: the slot's chosen id when this instance offers it, else a heuristic guess. The
    // guess is a staged default — shown pre-selected in the dropdown and stored in draft.statId,
    // but NOT committed; it only reaches slotState (and the row label) on Confirm. Nothing here
    // touches slotState.
    //
    // A chosen id wins over the guess, but only if the CONNECTED instance actually offers it. An
    // id the instance does not have is not a usable choice — it cannot be shown (assigning an
    // absent value to a <select> silently leaves it at "") and it cannot be fetched — so falling
    // back to the guess beats presenting an empty picker. This is what a stale mapping looks like:
    // a slot pointing at an entity from another Home Assistant, or one since renamed.
    var offered = draft.statId && statIds[kind].indexOf(draft.statId) !== -1;
    var pick = (offered ? draft.statId : guessId(slotName, statIds[kind])) || "";
    sel.value = pick;
    draft.statId = sel.value;
    updateConfirmEnabled();
  }

  // Heuristic auto-map from the slot name to a statistic id. A convenience default only: the
  // guess is shown on the roster row and in the dropdown, and a wrong one is corrected there. Not
  // a mapping authority.
  function guessId(series, ids) {
    if (!series) return "";
    var hints = {
      grid_import_t1: ["consumed_tariff_1", "import_t1", "import_1"],
      grid_import_t2: ["consumed_tariff_2", "import_t2", "import_2"],
      grid_export_t1: ["produced_tariff_1", "export_t1", "export_1", "delivered_tariff_1"],
      grid_export_t2: ["produced_tariff_2", "export_t2", "export_2", "delivered_tariff_2"],
      solar_production: ["solar", "pv_production", "inverter"],
      price_spot: ["epex", "market_price", "spot", "elektriciteitsprijs"]
    };
    var keys = hints[series] || [series];
    for (var i = 0; i < ids.length; i++) {
      var low = ids[i].toLowerCase();
      for (var j = 0; j < keys.length; j++) {
        if (low.indexOf(keys[j]) !== -1) return ids[i];
      }
    }
    return "";
  }

  // -----------------------------------------------------------------------------------------
  // Fetch history: pull statistics for the HA slots only, stream to the backend.
  // -----------------------------------------------------------------------------------------
  function isoDaysAgo(days) {
    var d = new Date(Date.now() - days * 86400000);
    return d.toISOString();
  }

  function chunkWindows(startMs, endMs, chunkDays) {
    var out = [], step = chunkDays * 86400000, s = startMs;
    while (s < endMs) {
      var e = Math.min(s + step, endMs);
      out.push([new Date(s).toISOString(), new Date(e).toISOString()]);
      s = e;
    }
    return out;
  }

  // The HA history window (also reused for the energy_charts backend load, so both request the
  // same span; the backend clamps to what it can serve).
  function historyWindow() {
    var endMs = Date.now();
    var startMs = endMs - HISTORY_DAYS * 86400000;
    return {
      startMs: startMs, endMs: endMs,
      start: new Date(startMs).toISOString(), end: new Date(endMs).toISOString()
    };
  }

  // ── Household setup answers (specs §2.1) ───────────────────────────────────────────────────
  //
  // The two shape-determining answers — has_pv and has_battery — live as radio groups in
  // _data_household.html (they were in the since-deleted _setup_band.html when this was written).
  // They are NOT a form and post nowhere on change. Instead:
  //
  //   * changing one re-gates the slot roster IMMEDIATELY (applySetupGating below), so the
  //     user sees which series the app is asking for as they answer; and
  //   * the answers are PERSISTED with the fetch, as fields on the ingest WS `header` message —
  //     the fetch button commits the whole data configuration, and these are part of it.
  //
  // The params and results screens keep showing the STORED answers until the next fetch. That is
  // deliberate: they describe a simulation over data that has actually been loaded, so re-deriving
  // them from an uncommitted answer would describe a run that does not exist yet.

  // One setup answer as a boolean, read off the checked radio. Defaults matter: an absent group
  // (a template that did not render it) must not silently flip the answer, so each caller passes
  // the same default the server-side config uses.
  function setupAnswer(name, dflt) {
    var checked = document.querySelector('input[name="' + name + '"]:checked');
    if (!checked) return dflt;
    return checked.value === "1";
  }

  function hasPv() { return setupAnswer("setup_haspv", true); }
  function hasBattery() { return setupAnswer("setup_hasbattery", false); }

  // Is this slot's row currently gated out? A hidden row's slot must never be fetched, even if a
  // source was staged for it before the answer changed — otherwise turning PV off after choosing
  // a solar source would still stream solar data. The staged state is deliberately NOT cleared,
  // so turning the answer back on restores the user's choice.
  function slotHidden(name) {
    var row = document.querySelector('.slot-row[data-slot-row="' + cssEscape(name) + '"]');
    return !!(row && row.classList.contains("hidden"));
  }

  // Minimal attribute-value escape for the querySelector above. Slot names come from the closed
  // server-side vocabulary (lowercase + underscore), so this only has to be safe, not complete.
  function cssEscape(s) {
    return String(s).replace(/["\\]/g, "\\$&");
  }

  // Show/hide each gated slot row against the current answers. The server rendered the initial
  // state, so this is a no-op on load and only does work once a radio changes.
  function applySetupGating() {
    var pv = hasPv(), batt = hasBattery();
    Array.prototype.slice.call(document.querySelectorAll(".slot-row")).forEach(function (row) {
      var hide =
        (row.hasAttribute("data-pv-only") && !pv) ||
        (row.hasAttribute("data-battery-only") && !batt);
      if (row.hasAttribute("data-pv-only") || row.hasAttribute("data-battery-only")) {
        row.classList.toggle("hidden", hide);
      }
    });
    // Hiding a staged row can remove the last fetchable slot, so the button must re-evaluate.
    updateFetchEnabled();
  }

  document.addEventListener("change", function (ev) {
    var el = ev.target;
    if (!el || el.type !== "radio") return;
    if (el.name === "setup_haspv" || el.name === "setup_hasbattery") applySetupGating();
  });

  // Slots whose chosen source is Home Assistant AND that have an entity chosen (slotState). This
  // is the sole source of truth for the HA arm of the fetch — there is no per-row DOM select.
  function mappedSlots() {
    return Object.keys(slotState)
      .filter(function (name) {
        var st = slotState[name];
        return st && st.source === "home_assistant" && st.statId && !slotHidden(name);
      })
      .map(function (name) {
        var st = slotState[name];
        return { name: name, kind: st.kind === "price" ? "price" : "energy", statId: st.statId };
      });
  }

  // The source keys that are backend_load, learned from the drawer's per-slot source lists (each
  // descriptor carries its kind). Built once from every slot button's data-slot-sources so the
  // fetch can tell a staged backend source from an HA one without hardcoding "energy_charts".
  var backendSourceKeys = {};
  Array.prototype.slice.call(document.querySelectorAll(".slot-source-btn")).forEach(function (btn) {
    try {
      JSON.parse(btn.getAttribute("data-slot-sources") || "[]").forEach(function (d) {
        if (d && d.kind === "backend_load" && d.key) backendSourceKeys[d.key] = true;
      });
    } catch (e) { /* ignore */ }
  });

  // Staged backend-load slots: those whose committed source is a backend_load key. The fetch
  // reifies each by sending a backend_load WS message; the backend loads and persists it.
  //
  // A CSV slot also carries its BINDING on that message, and this is the only path the binding takes
  // to the server (D-BIND: it is browser-local, and Confirm writes nothing server-side). Field names
  // are snake_case here because they cross the wire into `app/ingest_ws.py`'s protocol, where every
  // other field is too; the camelCase spelling stops at this boundary.
  //
  // The binding is attached only for `csv_upload`, not for every backend slot, because the server
  // passes it on only to that source — the `DataSource` protocol is `load(slot, window)` and each
  // source's extras are its own, so `energy_charts` would raise on an unexpected keyword. Sending a
  // binding it will not use would be harmless today and misleading tomorrow.
  //
  // An INCOMPLETE binding is sent as-is rather than suppressed HERE, because it is kept out of
  // slotState in the first place: `saveSlotStore` writes only complete bindings and
  // `usableStoreEntry` refuses to restore an incomplete one on the way back in, so no slot reaches
  // this function bound to half a binding (step 6's Confirm gate adds the third, in-drawer, copy of
  // the same rule). Those are the gates; this is not one, and it must not become the only one — a
  // filter here would drop the SLOT silently and leave a fetch quietly missing a series the user
  // asked for. If a binding ever does arrive incomplete, sending it gets a server message naming the
  // missing field, which is a diagnosable failure rather than a vanished slot.
  function stagedBackendSlots() {
    return Object.keys(slotState)
      .filter(function (name) {
        var st = slotState[name];
        return st && st.source && backendSourceKeys[st.source] && !slotHidden(name);
      })
      .map(function (name) {
        var st = slotState[name];
        var out = { name: name, source: st.source };
        if (st.source === CSV_SOURCE_KEY) {
          out.binding = {
            upload_id: st.uploadId || "",
            column: st.column || "",
            unit: st.unit || DEFAULT_CSV_UNIT
          };
        }
        return out;
      });
  }

  // True while a fetch is running, so updateFetchEnabled does not re-enable the button mid-run.
  var fetchInFlight = false;

  // Fetch is possible once ANY slot is staged — an HA slot with an entity, or a backend slot.
  function updateFetchEnabled() {
    if (!fetchBtn) return;
    var any = mappedSlots().length > 0 || stagedBackendSlots().length > 0;
    // A live fetch disables the button itself; don't fight that (re-enabled in fetchHistory's
    // catch on failure; success navigates away).
    if (!fetchInFlight) fetchBtn.disabled = !any;
  }

  // Fetch REIFIES the staged config into one dataset (specs §2.2, §3.5): it streams the staged HA
  // slots from the browser and declares each staged backend-load slot (which the backend loads),
  // then persists both together. It works with HA slots only, backend slots only, or a mix.
  async function fetchHistory() {
    var base = urlInput.value.trim(), token = tokenInput.value.trim();
    var slots = mappedSlots();
    var backends = stagedBackendSlots();
    if (!slots.length && !backends.length) {
      setStatus(fetchStatus, t("need_source", "Choose a source for at least one slot first."), "text-warning");
      return;
    }
    // HA slots require a tested connection (the token lives only in the browser, §7.5).
    if (slots.length && (!base || !token)) {
      setStatus(fetchStatus, t("need_ha_connection", "Configure the Home Assistant connection first."), "text-warning");
      return;
    }

    fetchInFlight = true;
    fetchBtn.disabled = true;
    testBtn.disabled = true;
    progressEl.classList.remove("hidden");
    progressEl.removeAttribute("value");  // indeterminate until we know totals

    var ha = slots.length ? new HaClient(base, token) : null;
    var backend = null;
    try {
      if (ha) await ha.connect();
      backend = await openBackend();

      var w = historyWindow();
      var win = { start: w.start, end: w.end };
      // The setup-band answers ride along with the header: this fetch is what commits them
      // (specs §2.1), alongside the dataset itself and the source-generation bump.
      backend.send(JSON.stringify({
        type: "header", source: "home_assistant", window: win,
        has_pv: hasPv(), has_battery: hasBattery()
      }));

      // HA arm: stream the mapped slots' statistics.
      var total = slots.length, done = 0;
      for (var i = 0; i < slots.length; i++) {
        var slot = slots[i];
        setStatus(fetchStatus, ti("fetching_slot", "Fetching %(slot)s (%(n)s/%(total)s)…",
          { slot: slot.name, n: i + 1, total: total }), "text-base-content/60");
        // Carry the chosen HA statistic id so the backend can persist it (series_meta) and render
        // the slot's entity from the dataset after a reload. Not secret — only the token is (§7.5).
        backend.send(JSON.stringify({
          type: "series", name: slot.name, kind: slot.kind, stat_id: slot.statId
        }));

        // Hourly over the full window, chunked.
        var chunks = chunkWindows(w.startMs, w.endMs, HA_CHUNK_DAYS);
        for (var c = 0; c < chunks.length; c++) {
          await fetchAndForward(ha, backend, slot, chunks[c][0], chunks[c][1], "hour");
        }
        // 5-minute over the trailing fine window (§4.3), for the resolution-bias diagnostic.
        await fetchAndForward(ha, backend, slot, isoDaysAgo(HA_FINE_WINDOW_DAYS),
          new Date(w.endMs).toISOString(), "5minute");

        done += 1;
        progressEl.value = Math.round((done / total) * 100);
      }

      // Backend arm: declare each staged backend-load slot. The backend loads them server-side on
      // `done` (all-or-nothing) and folds them into the same dataset.
      for (var b = 0; b < backends.length; b++) {
        setStatus(fetchStatus, ti("loading_slot", "Loading %(slot)s…", { slot: backends[b].name }), "text-base-content/60");
        var msg = {
          type: "backend_load", name: backends[b].name, source: backends[b].source, window: win
        };
        // The per-slot binding, for the one source that needs one (stagedBackendSlots). Omitted
        // entirely rather than sent as null for a source with nothing to bind — `on_backend_load`
        // treats absent and null alike, but an absent field is what the protocol documents as the
        // normal case and keeps the message identical to what it was before CSV existed.
        if (backends[b].binding) msg.binding = backends[b].binding;
        backend.send(JSON.stringify(msg));
      }

      var result = await finishBackend(backend);
      setStatus(fetchStatus, ti("imported_series", "✓ Imported %(count)s series. Reloading…", { count: result.series }), "text-success");
      // The server now has ONE dataset with every staged slot — HA (source + statistic id) and
      // backend-load — so the roster re-renders all of them after the reload (§3.5, §2.2).
      setTimeout(function () { window.location.reload(); }, 600);
    } catch (e) {
      setStatus(fetchStatus, ti("failed_reason", "✗ %(reason)s", { reason: e.message }), "text-error");
      fetchInFlight = false;
      updateFetchEnabled();
    } finally {
      if (ha) ha.close();
      testBtn.disabled = false;
      progressEl.classList.add("hidden");
    }
  }

  // Fetch one (slot, window, period) from HA and forward its rows to the backend. Rows are
  // reshaped to the compact arrays the ingest protocol expects: [start_ms, sum] for energy,
  // [start_ms, mean] for price (specs app/ingest_ws.py). Only the "mean" statistic column is
  // requested for a price: the §6.16 intra-hour bracket is derived server-side from the values
  // themselves, so HA's own min/max would be fetched and then discarded.
  async function fetchAndForward(ha, backend, slot, startIso, endIso, period) {
    var payload = {
      type: "recorder/statistics_during_period",
      start_time: startIso, end_time: endIso,
      statistic_ids: [slot.statId], period: period
    };
    if (slot.kind === "price") payload.types = ["mean"];
    else payload.types = ["sum"];

    var result = await ha.call(payload);
    var rows = (result && result[slot.statId]) || [];
    if (!rows.length) return;

    var packed = rows.map(function (r) {
      if (slot.kind === "price") {
        return [r.start, nz(r.mean)];
      }
      return [r.start, nz(r.sum)];
    });
    // The period is carried so the backend keeps the two native resolutions apart (specs §4.3):
    // the hourly full-window copy the run uses, and the trailing 5-minute copy. They must never
    // be differenced across each other.
    backend.send(JSON.stringify({ type: "rows", name: slot.name, period: period, rows: packed }));
  }

  function nz(v) { return (v === undefined || v === null) ? null : v; }

  // --- backend WS (our own server) ---------------------------------------------------------
  function backendWsUrl() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + conn.getAttribute("data-ingest-ws");
  }

  function openBackend() {
    return new Promise(function (resolve, reject) {
      var ws = new WebSocket(backendWsUrl());
      ws.onopen = function () { resolve(ws); };
      ws.onerror = function () { reject(new Error(t("ingest_unreachable", "Could not reach the app's ingest endpoint."))); };
    });
  }

  // Send `done` and await the backend's `result` (or surface its `error`). Progress frames the
  // backend emits after each rows batch are consumed here without blocking.
  function finishBackend(ws) {
    return new Promise(function (resolve, reject) {
      ws.onmessage = function (ev) {
        var msg = JSON.parse(ev.data);
        if (msg.type === "result") resolve(msg);
        else if (msg.type === "error") reject(new Error(ti("ingest_rejected", "Ingest rejected: %(reason)s", { reason: msg.message })));
        // "progress" frames are ignored — the client tracks its own per-series progress.
      };
      ws.onclose = function () { reject(new Error(t("ingest_closed_early", "Ingest connection closed early."))); };
      ws.send(JSON.stringify({ type: "done" }));
    });
  }

  // -----------------------------------------------------------------------------------------
  // Source-picker drawer (§2.2 slot-first). One shared right-side panel, opened per slot.
  // -----------------------------------------------------------------------------------------
  var drawer = document.getElementById("source-drawer");
  var drawerBackdrop = document.getElementById("source-drawer-backdrop");
  var drawerClose = document.getElementById("drawer-close");
  var drawerTitle = document.getElementById("drawer-slot-title");
  var drawerList = document.getElementById("drawer-source-list");
  var drawerHaNote = document.getElementById("drawer-ha-note");
  var drawerHaEntity = document.getElementById("drawer-ha-entity");
  var drawerEntitySelect = document.getElementById("drawer-entity-select");
  var drawerBackendAction = document.getElementById("drawer-backend-action");
  var drawerBackendStatus = document.getElementById("drawer-backend-status");
  var drawerConfirmBtn = document.getElementById("drawer-confirm");
  var drawerCancelBtn = document.getElementById("drawer-cancel");

  // The per-slot CSV binding controls (workspace_data.html #drawer-csv-binding) and the shared
  // upload modal (#csv-upload-dialog). Looked up here with the rest of the drawer rather than
  // lazily, so a template rename fails at load in one place instead of at first click.
  var drawerCsvBinding = document.getElementById("drawer-csv-binding");
  var drawerCsvFile = document.getElementById("drawer-csv-file");
  var drawerCsvFileSummary = document.getElementById("drawer-csv-file-summary");
  var drawerCsvColumn = document.getElementById("drawer-csv-column");
  var drawerCsvCumulative = document.getElementById("drawer-csv-cumulative");
  var drawerCsvNoFiles = document.getElementById("drawer-csv-no-files");
  var csvUploadDialog = document.getElementById("csv-upload-dialog");
  var csvUploadChooseBtn = document.getElementById("csv-upload-choose");
  var csvUploadInput = document.getElementById("csv-upload-input");
  var csvUploadStatus = document.getElementById("csv-upload-status");
  var csvUploadError = document.getElementById("csv-upload-error");
  var csvUploadList = document.getElementById("csv-upload-list");
  var csvUploadEmpty = document.getElementById("csv-upload-empty");

  // The "Configure" button rendered beside the Home Assistant radio (created in renderSourceList).
  // Held here so testConnection / drawer opens can refresh its label to reflect the shared
  // connection state ("Configure…" vs "✓ Connected").
  var haConfigBtn = null;

  // Drawer-local staging. `draft` is the ONLY thing the in-drawer controls write to while the
  // drawer is open; it is seeded from the committed slotState on open and applied to slotState
  // only on Confirm. `sources` holds the current slot's source descriptors (for Confirm to read
  // the selected source's kind). `loading` guards Confirm during a backend load.
  // `uploadId`/`column`/`unit` are the CSV binding (D-BIND), staged like everything else: the
  // file/column/unit controls (#drawer-csv-binding) write them here and nowhere else, and Confirm is
  // what moves them into slotState. The UPLOADED FILE is not staged and is not in here — it is
  // server state, shared across slots, and survives Cancel; only the mapping is transactional.
  var draft = { slot: null, source: null, statId: "", uploadId: "", column: "", unit: DEFAULT_CSV_UNIT };
  var drawerSources = [];
  var loading = false;
  var lastFocus = null;

  // The entity <select> stages the chosen id into the draft (never slotState). Confirm commits it.
  if (drawerEntitySelect) {
    drawerEntitySelect.addEventListener("change", function () {
      draft.statId = drawerEntitySelect.value || "";
      updateConfirmEnabled();
    });
  }

  // -----------------------------------------------------------------------------------------
  // Uploaded CSVs: the shared upload modal, and the per-slot (file, column, unit) binding
  // controls (specs §2.2 "The CSV source" and "The upload dialog", §4.2a, decisions D-TZ/D-BIND).
  //
  // Two levels, and the split is the whole design:
  //
  //   * The FILE is server state, shared across every slot in this workspace, managed through
  //     POST/GET/DELETE /w/{id}/data/uploads. Uploading and removing are immediate — they are not
  //     staged, and an upload therefore SURVIVES the drawer's Cancel, exactly as a tested Home
  //     Assistant connection does. One wide file (timestamp column + one column per measurement)
  //     usually holds many series, so requiring one file per slot would make the user split their
  //     export by hand.
  //   * The BINDING — which file, which column, what unit — is per-slot, browser-local (D-BIND) and
  //     transactional like every other drawer choice: it lives in `draft` until Confirm.
  //
  // `csvUploads` caches the LIST route's answer. It is not merely an optimisation: `slotState` holds
  // an `uploadId` and never a filename (the id is what the server validates and what the binding
  // means), so the row label "Upload CSV · <file> · <column>" needs an id→filename map, and this is
  // it. It is refreshed whenever the list is fetched, and a binding whose id is not in it renders a
  // placeholder rather than a blank — an upload can genuinely be gone (removed in another tab, or a
  // workspace whose data was cleared), and a label that silently omits the file would read as
  // "unbound" when the binding is in fact stale.
  // -----------------------------------------------------------------------------------------
  var csvUploads = [];          // the LIST route's rows, newest first
  var csvUploadsLoaded = false; // has a list ever come back? (distinguishes "empty" from "unknown")

  // The workspace-scoped uploads collection. Built from WORKSPACE_ID rather than written as a
  // literal, the same rule the results screen's `wsPath` follows: these routes are `/w/{id}/…`
  // (§5.1) and no route path is spelled out with the id inlined by hand.
  function uploadsPath(suffix) {
    return "/w/" + encodeURIComponent(WORKSPACE_ID) + "/data/uploads" + (suffix || "");
  }

  // One upload row by id, or null. Linear over a list a user curates by hand — a handful of files,
  // not a data structure worth indexing.
  function csvUploadById(id) {
    if (!id) return null;
    for (var i = 0; i < csvUploads.length; i++) {
      if (csvUploads[i].id === id) return csvUploads[i];
    }
    return null;
  }

  // A human name for an inferred sample spacing. `resolution_s` is `infer_resolution_s`' modal
  // spacing and is null when no spacing covered more than half the gaps — an irregular file, which
  // says so rather than being rounded to a plausible-looking figure. The three named cases are the
  // ones a Dutch meter or PV export actually produces; anything else falls back to a count.
  function csvResolutionLabel(seconds) {
    if (!seconds) return t("csv_res_irregular", "irregular spacing");
    if (seconds === 3600) return t("csv_res_hourly", "hourly");
    if (seconds === 900) return t("csv_res_15min", "15-minute");
    if (seconds === 300) return t("csv_res_5min", "5-minute");
    if (seconds % 60 === 0) return ti("csv_res_minutes", "%(n)s-minute", { n: seconds / 60 });
    return ti("csv_res_seconds", "%(n)s-second", { n: seconds });
  }

  // A date for display, in the viewer's own locale. `toLocaleDateString` rather than a hand-built
  // format: these are ISO-8601 strings with an explicit offset (`_upload_json`), the browser knows
  // the user's conventions, and nothing here is parsed back. An unparseable value degrades to the
  // raw string instead of "Invalid Date".
  function csvShortDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    try { return d.toLocaleDateString(); } catch (e) { return d.toISOString().slice(0, 10); }
  }

  // Row counts in the viewer's locale too ("8.760" in Dutch, "8,760" in English), matching the
  // wireframe's thousands separator. Falls back to the bare number where Intl is unavailable.
  function csvNumber(n) {
    if (typeof n !== "number" || !isFinite(n)) return String(n);
    try { return n.toLocaleString(); } catch (e) { return String(n); }
  }

  // Turn a rejected upload/delete response into one translated sentence.
  //
  // The server's `detail` is `dict | str` and both shapes are real (app/main.py `create_upload`):
  // every 4xx the upload routes raise THEMSELVES carries `{code, message, row}`, but python-multipart
  // enforces its own part limits BEFORE our handler runs and answers with a bare string that
  // Starlette owns. So this keys off `detail.code` when it can and falls back otherwise; it never
  // assumes the envelope.
  //
  // The server's English `message` is not shown in place of the translated wording — that would put
  // an English sentence in a Dutch dialog — but it IS appended for the codes whose message carries
  // the specific fact (which cell, which column, what was found), because re-deriving that here
  // would mean parsing English prose. Those messages quote the user's own column names and cell
  // values, which is why every write below is `textContent` and never `innerHTML`.
  //
  // A 413 has no envelope of ours either (it is raised with a plain string detail by
  // `_read_capped_body`), so the status is consulted before the body shape.
  var CSV_ERROR_KEYS = {
    no_file: "csv_err_no_file",
    bad_timezone: "csv_err_bad_timezone",
    // Not in CSV_ERROR_DETAILED below, for the same reason bad_timezone is not: its server message
    // ("Unknown field separator 'pipe'. Expected one of: …") only restates the translated sentence.
    bad_delimiter: "csv_err_bad_delimiter",
    bad_encoding: "csv_err_bad_encoding",
    unreadable_csv: "csv_err_unreadable_csv",
    bad_upload_id: "csv_err_bad_upload_id",
    missing_header: "csv_err_missing_header",
    too_few_columns: "csv_err_too_few_columns",
    no_data_rows: "csv_err_no_data_rows",
    row_length_mismatch: "csv_err_row_length_mismatch",
    empty_timestamp: "csv_err_empty_timestamp",
    bad_timestamp: "csv_err_bad_timestamp",
    nonexistent_local_time: "csv_err_nonexistent_local_time",
    non_numeric_value: "csv_err_non_numeric_value",
    mixed_decimal_separator: "csv_err_mixed_decimal_separator",
    non_finite_value: "csv_err_non_finite_value",
    // No `cumulative_column` entry: the server no longer rejects a non-decreasing column. It warns
    // and proceeds (`csv_wide.column_frame`), and the user-facing wording is the small print under
    // the column picker (`updateCsvCumulativeWarning`), not an error.
    bad_unit: "csv_err_bad_unit",
    unknown_column: "csv_err_unknown_column"
  };
  // The codes whose server message names the specific offender and is worth appending verbatim.
  // Listed rather than "everything with a message", because for a code like `bad_encoding` the
  // English sentence merely restates the translated one and appending it reads as a stutter.
  var CSV_ERROR_DETAILED = {
    row_length_mismatch: true, empty_timestamp: true, bad_timestamp: true,
    nonexistent_local_time: true, non_numeric_value: true, non_finite_value: true,
    // Its server message quotes the offending cell and its column, which is the criterion above.
    mixed_decimal_separator: true,
    unknown_column: true, missing_header: true,
    too_few_columns: true, unreadable_csv: true
  };

  function csvErrorText(status, detail) {
    if (status === 413) return t("csv_err_too_large", "That file is too large to upload.");
    var generic = t("csv_error_generic", "That file could not be uploaded.");
    if (!detail || typeof detail !== "object") return generic;
    var key = CSV_ERROR_KEYS[detail.code];
    var text = key ? t(key, generic) : generic;
    if (CSV_ERROR_DETAILED[detail.code] && detail.message) {
      text = ti("csv_error_with_detail", "%(message)s — %(detail)s",
                { message: text, detail: detail.message });
    }
    // The row is 1-based and comes from the parser, which counts the header as row 1 — so it names
    // the line the user sees in their editor. Appended separately from the message so it survives a
    // code whose message is not shown.
    if (detail.row !== null && detail.row !== undefined) {
      text = ti("csv_error_at_row", "%(message)s (row %(row)s)", { message: text, row: detail.row });
    }
    return text;
  }

  // Read a fetch Response's error body into the same `(status, detail)` pair, tolerating a body
  // that is not JSON at all (a proxy's HTML error page, or an empty 502).
  function csvErrorFromResponse(resp) {
    return resp.text().then(function (body) {
      var detail = null;
      try { detail = JSON.parse(body).detail; } catch (e) { detail = null; }
      return csvErrorText(resp.status, detail);
    }, function () {
      return csvErrorText(resp.status, null);
    });
  }

  function showCsvError(text) {
    if (!csvUploadError) return;
    csvUploadError.textContent = text;   // never innerHTML: this quotes the user's own file
    csvUploadError.classList.remove("hidden");
  }

  function clearCsvError() {
    if (!csvUploadError) return;
    csvUploadError.textContent = "";
    csvUploadError.classList.add("hidden");
  }

  // Fetch the workspace's uploads and refresh everything that displays them: the dialog's list, the
  // drawer's File select, and every row label that names a file.
  //
  // It also discharges an obligation D-BIND left to this step: a binding whose upload is no longer
  // listed is dropped here. Under candidate E the server cannot clear a binding when a file is
  // removed — the binding is browser-local — so without this a stale binding would stay invisible
  // until the next fetch failed on it. Doing it when the list arrives means the drawer is the place
  // the staleness surfaces, which is also the place the user can fix it.
  function refreshCsvUploads() {
    return fetch(uploadsPath(), { headers: { "Accept": "application/json" } })
      .then(function (resp) {
        if (!resp.ok) return csvErrorFromResponse(resp).then(function (msg) { throw new Error(msg); });
        return resp.json();
      })
      .then(function (data) {
        csvUploads = (data && data.uploads) || [];
        csvUploadsLoaded = true;
        pruneStaleCsvBindings();
        // Re-label every CSV-bound row that SURVIVED the prune. Until a list arrives, such a row
        // renders the "(file no longer available)" placeholder — `updateSlotButton` has no filename
        // to show — and this is what resolves it. The prune re-labels only the rows it cleared, so
        // without this pass a restored binding would keep the placeholder for the whole session.
        Object.keys(slotState).forEach(function (name) {
          if (slotState[name] && slotState[name].source === CSV_SOURCE_KEY) updateSlotButton(name);
        });
        renderCsvUploadList();
        fillCsvFileSelect();
        return csvUploads;
      })
      .catch(function (err) {
        // A failed list is reported in the dialog when it is open, and is otherwise silent: the
        // drawer's own empty-state line already tells the user there is nothing to choose, and a
        // second error in the drawer for a network blip would be noise. `csvUploadsLoaded` stays
        // false, so a later open retries rather than trusting an empty cache.
        showCsvError(ti("csv_list_failed", "Could not list the uploaded files: %(reason)s",
                        { reason: err.message }));
      });
  }

  // Drop committed bindings whose upload the server no longer lists, and refresh those rows.
  //
  // Only slots whose COMMITTED state names a missing upload are touched; the open drawer's `draft`
  // is left alone, because the file select is rebuilt from the fresh list immediately afterwards and
  // will drop a vanished id there by itself. Returns the slot names cleared, so a caller that
  // removed a file on purpose can say which series it affected.
  function pruneStaleCsvBindings() {
    var cleared = [];
    Object.keys(slotState).forEach(function (name) {
      var st = slotState[name];
      if (!st || st.source !== CSV_SOURCE_KEY || !st.uploadId) return;
      if (csvUploadById(st.uploadId)) return;
      // Cleared WHOLE, source included, so the row returns to "Choose source…" exactly as §2.2
      // requires — rather than sitting as a CSV slot with no file, which is a state the fetch
      // rejects and the label cannot describe.
      slotState[name] = {
        source: null, statId: "", uploadId: "", column: "", unit: DEFAULT_CSV_UNIT,
        kind: st.kind || slotKind(name)
      };
      locallyCustomized[name] = true;
      cleared.push(name);
      updateSlotButton(name);
    });
    if (cleared.length) {
      saveSlotStore();
      updateFetchEnabled();
    }
    return cleared;
  }

  // The dialog's "Uploaded files" list: one row per upload with its summary and a [ remove ] link.
  function renderCsvUploadList() {
    if (!csvUploadList) return;
    csvUploadList.textContent = "";
    if (csvUploadEmpty) csvUploadEmpty.classList.toggle("hidden", csvUploads.length > 0);
    csvUploads.forEach(function (u) {
      var row = document.createElement("div");
      row.className = "flex flex-wrap items-baseline justify-between gap-2 py-1";
      row.setAttribute("data-upload-id", u.id);

      var left = document.createElement("span");
      left.className = "flex flex-wrap items-baseline gap-2";
      var nameEl = document.createElement("span");
      nameEl.className = "text-sm font-medium";
      nameEl.textContent = u.filename;   // the user's own filename; textContent, never innerHTML
      var sum = document.createElement("span");
      sum.className = "text-xs text-base-content/60";
      sum.textContent = ti("csv_list_summary", "%(rows)s rows · %(resolution)s · %(columns)s columns", {
        rows: csvNumber(u.rows),
        resolution: csvResolutionLabel(u.resolution_s),
        // The stored `columns` includes the timestamp at index 0; the count the user cares about is
        // of VALUE columns, which is what the drawer will offer them.
        columns: Math.max(0, (u.columns || []).length - 1)
      });
      left.appendChild(nameEl); left.appendChild(sum);

      var rm = document.createElement("button");
      rm.type = "button";
      rm.className = "btn btn-ghost btn-xs text-error";
      rm.textContent = "[ " + t("csv_remove", "remove") + " ]";
      rm.addEventListener("click", function () { removeCsvUpload(u); });

      row.appendChild(left); row.appendChild(rm);
      csvUploadList.appendChild(row);
    });
  }

  // Remove one uploaded file, after confirming, and cascade to any slot bound to it.
  //
  // §2.2: "Removing a file that a slot still uses clears that slot's binding and returns it to
  // 'Choose source…', reported when the removal is confirmed." Under D-BIND the SERVER cannot do
  // that — it holds no binding — so the cascade runs here, in the client that does hold it, and the
  // report is the status line below naming the slots it cleared.
  //
  // The cascade runs on any 2xx, not only when the server says the row `existed`. The DELETE is
  // idempotent by design (a double-click on [ remove ] is harmless), so `existed: false` is exactly
  // what a retry after a partial failure looks like — and a retry is the call that must still clear
  // a binding left stranded by the first attempt. This mirrors the "unconditionally, not gated on
  // `existed`" rule the brief recorded for a server-side cascade, applied where the cascade actually
  // lives.
  function removeCsvUpload(upload) {
    var question = ti("csv_confirm_remove",
      "Remove %(name)s? Any series that uses it will go back to “Choose source…”.",
      { name: upload.filename });
    if (!window.confirm(question)) return;
    clearCsvError();
    fetch(uploadsPath("/" + encodeURIComponent(upload.id)), { method: "DELETE" })
      .then(function (resp) {
        if (!resp.ok) return csvErrorFromResponse(resp).then(function (msg) { throw new Error(msg); });
        // Drop it locally first so the cascade below sees the post-removal list: `refreshCsvUploads`
        // re-fetches anyway, but doing the prune off a list we know is current keeps the report the
        // user reads in the same turn as the click.
        csvUploads = csvUploads.filter(function (u) { return u.id !== upload.id; });
        var cleared = pruneStaleCsvBindings();
        renderCsvUploadList();
        fillCsvFileSelect();
        if (cleared.length) {
          setStatus(csvUploadStatus, ti("csv_removed_cleared",
            "✓ Removed %(name)s. These series went back to “Choose source…”: %(slots)s",
            { name: upload.filename, slots: cleared.map(slotRoleLabel).join(", ") }), "text-success");
        } else {
          setStatus(csvUploadStatus,
            ti("csv_removed", "✓ Removed %(name)s", { name: upload.filename }), "text-success");
        }
        // Re-list anyway: another tab may have added or removed something since, and the authority
        // on what exists is the server, not the row we just spliced out.
        return refreshCsvUploads();
      })
      .catch(function (err) {
        showCsvError(ti("csv_remove_failed", "Could not remove that file: %(reason)s",
                        { reason: err.message }));
      });
  }

  // The roster's own label for a slot ("Grid import T1"), for messages that name slots to the user.
  // Read off the row button's data-slot-role, which the template renders already translated — the
  // internal series name (`grid_import_t1`) is an identifier and is never shown (§4.1).
  function slotRoleLabel(name) {
    var btn = document.querySelector('.slot-source-btn[data-slot="' + cssEscape(name) + '"]');
    return (btn && btn.getAttribute("data-slot-role")) || name;
  }

  // Upload the chosen file with the chosen zone and separator. Multipart with exactly the three
  // fields the route reads: `file`, `tz` (D-TZ; the value strings are `csv_wide.TZ_KEYS`) and
  // `delimiter` (`csv_wide.DELIMITER_KEYS` — names, not the characters). None of the value strings
  // is translated; they are the wire vocabulary.
  //
  // Rejection is panel-local and RECOVERABLE (§3.2 — downloading the wrong export is an ordinary
  // event, not a run-fatal one): the message lands in the dialog, the dialog stays open, and nothing
  // was stored (the route parses before it writes, so a rejected upload leaves no row and no file).
  function uploadCsvFile(file) {
    if (!file) return;
    clearCsvError();
    var tzInput = document.querySelector("input[name=csv-upload-tz]:checked");
    var tz = (tzInput && tzInput.value) || "Europe/Amsterdam";
    var delimInput = document.querySelector("input[name=csv-upload-delimiter]:checked");
    var delim = (delimInput && delimInput.value) || "comma";
    var body = new FormData();
    body.append("file", file);
    body.append("tz", tz);
    body.append("delimiter", delim);
    setStatus(csvUploadStatus, ti("csv_uploading", "Uploading %(name)s…", { name: file.name }),
              "text-base-content/60");
    if (csvUploadChooseBtn) csvUploadChooseBtn.disabled = true;
    fetch(uploadsPath(), { method: "POST", body: body })
      .then(function (resp) {
        if (!resp.ok) return csvErrorFromResponse(resp).then(function (msg) { throw new Error(msg); });
        return resp.json();
      })
      .then(function (data) {
        var name = (data && data.upload && data.upload.filename) || file.name;
        setStatus(csvUploadStatus, ti("csv_uploaded", "✓ Uploaded %(name)s", { name: name }),
                  "text-success");
        // The new file must reach the drawer's File select, which is what makes the sequence
        // "no files → Upload… → choose column → Confirm" work without closing anything.
        return refreshCsvUploads();
      })
      .catch(function (err) {
        setStatus(csvUploadStatus, "", "text-base-content/60");
        showCsvError(err.message);
      })
      .then(function () {
        if (csvUploadChooseBtn) csvUploadChooseBtn.disabled = false;
        // Clear the input so choosing the SAME file again still fires `change`. A user who fixed
        // their export and re-picked it would otherwise see nothing happen.
        if (csvUploadInput) csvUploadInput.value = "";
      });
  }

  // Open the shared upload modal, mirroring openHaConfig (including the `setAttribute` fallback for
  // a browser without showModal). The list is refreshed on every open rather than cached across
  // them: another tab in the same workspace may have uploaded or removed a file since.
  //
  // Neither radio group — zone or separator — is reset here, so a second file uploaded in the same
  // dialog session inherits the answers given for the first. That is deliberate and applies to both
  // equally: files uploaded back to back almost always come from the same exporter, so carrying the
  // answers forward is right far more often than it is wrong. If it is ever changed it should be
  // changed for both at once, which is why this is recorded rather than fixed for one of them.
  function openCsvUpload() {
    if (!csvUploadDialog) return;
    clearCsvError();
    setStatus(csvUploadStatus, "", "text-base-content/60");
    if (typeof csvUploadDialog.showModal === "function") csvUploadDialog.showModal();
    else csvUploadDialog.setAttribute("open", "");
    refreshCsvUploads();
  }

  // Populate the drawer's File select from the cached list and stage the resulting choice.
  //
  // Preselection follows the same rule as the HA entity select one level up: the DRAFT's chosen file
  // wins when the workspace still offers it, and otherwise the newest upload is staged as a default
  // (the list is newest-first, so `[0]`). Staging a default is what makes the common path — upload a
  // file, pick a column, Confirm — need no extra click, and it is still only staging: nothing
  // reaches slotState until Confirm.
  //
  // With no uploads at all the two selects are hidden behind an explanatory line, because two empty
  // dropdowns give the user nothing to press and no reason why.
  function fillCsvFileSelect() {
    if (!drawerCsvFile) return;
    var sel = drawerCsvFile;
    while (sel.options.length) sel.remove(0);

    var none = csvUploads.length === 0;
    if (drawerCsvNoFiles) drawerCsvNoFiles.classList.toggle("hidden", !none);
    sel.disabled = none;
    if (drawerCsvColumn) drawerCsvColumn.disabled = none;
    if (none) {
      draft.uploadId = "";
      draft.column = "";
      if (drawerCsvFileSummary) drawerCsvFileSummary.textContent = "";
      fillCsvColumnSelect();
      updateConfirmEnabled();
      return;
    }

    csvUploads.forEach(function (u) {
      var opt = document.createElement("option");
      opt.value = u.id;
      opt.textContent = u.filename;
      sel.appendChild(opt);
    });
    var offered = draft.uploadId && csvUploadById(draft.uploadId);
    sel.value = offered ? draft.uploadId : csvUploads[0].id;
    draft.uploadId = sel.value;
    fillCsvColumnSelect();
    updateConfirmEnabled();
  }

  // Populate the Column select from the staged file's header, and stage the resulting choice.
  //
  // **`columns[0]` is the timestamp and is deliberately excluded** — it is the one name `csv_wide`
  // does NOT uniquify (a header `,A,B` stores `["", "A", "B"]`), so it can be empty or duplicate a
  // value column. The value names ARE uniquified ("A (2)", "Column 4"), which is why the binding
  // carries the NAME and never an index: `columns.indexOf(name)` can legitimately return 0, i.e. the
  // timestamp, on a file whose first value column repeats the timestamp's name.
  //
  // A leading "— choose a column —" entry is offered rather than defaulting to the first column,
  // and that asymmetry with the File select is on purpose: nothing about a column says which series
  // it is (§4.1 — a header is shown to help the user choose and is never parsed for meaning), so a
  // silently pre-picked column would be an arbitrary guess presented as an answer. A file, by
  // contrast, has exactly one obvious default when there is only one.
  function fillCsvColumnSelect() {
    if (!drawerCsvColumn) return;
    var sel = drawerCsvColumn;
    while (sel.options.length) sel.remove(0);

    var up = csvUploadById(draft.uploadId);
    if (drawerCsvFileSummary) drawerCsvFileSummary.textContent = up ? csvFileSummary(up) : "";
    if (!up) {
      draft.column = "";
      // Cleared on this path too: with no file staged there is no verdict, and a stale line left over
      // from the previously staged file would attach a warning to a column that is no longer shown.
      updateCsvCumulativeWarning();
      return;
    }
    var placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = t("csv_choose_column", "— choose a column —");
    sel.appendChild(placeholder);
    (up.columns || []).slice(1).forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
    // Keep a chosen column across a re-render only when THIS file offers it: a column name is
    // meaningful only within its own file, so carrying it to another file would bind a slot to a
    // name that happens to collide.
    var keep = draft.column && (up.columns || []).slice(1).indexOf(draft.column) !== -1;
    sel.value = keep ? draft.column : "";
    draft.column = sel.value;
    updateCsvCumulativeWarning();
  }

  // Small print under the Column select when the staged column looks like a cumulative meter
  // register rather than per-interval amounts.
  //
  // **It warns and nothing else.** `updateConfirmEnabled` never sees this — Confirm stays enabled,
  // the fetch succeeds, and the server only attaches a `CSV_CUMULATIVE_COLUMN` warning. That is the
  // decided behaviour, because the detector has a documented false positive: it cannot distinguish a
  // register from a column that merely rises throughout the file, and a morning-only solar export is
  // exactly that (see csv_wide.py's note at MONOTONIC_MIN_SAMPLES). Blocking cost a user with valid
  // data their whole binding and gave them no override; this line costs a false positive one line of
  // small print. The other side of the trade is real and is stated in the message itself: a user who
  // proceeds with a genuine register gets a confidently wrong answer, and this is the only signal.
  //
  // The verdict comes from the upload row (`_upload_json`'s `cumulative_columns`), NOT from a fresh
  // parse, which is why it survives a page reload — the drawer's cache is filled from the LIST route.
  // `null` there means the row predates the column and no verdict was ever computed, and it is
  // treated as "say nothing" rather than as "nothing flagged": both render the same, but conflating
  // them in the condition would make a later reader think a null row had been checked.
  function updateCsvCumulativeWarning() {
    if (!drawerCsvCumulative) return;
    var up = csvUploadById(draft.uploadId);
    var flagged = up && up.cumulative_columns;   // array, or null/undefined when not computed
    var suspect = !!(draft.column && flagged && flagged.indexOf(draft.column) !== -1);
    // textContent, never innerHTML: the message is fixed, but keeping the rule uniform here means a
    // later edit that interpolates the column name cannot introduce an injection.
    drawerCsvCumulative.textContent = suspect
      ? t("csv_cumulative_warning",
          "This column never decreases, so it may be a meter reading (a running total) rather than " +
          "the amount used in each interval. If it is, the results will be wrong. You can continue " +
          "anyway — a column that only rises across the whole file, such as solar in a morning-only " +
          "export, is flagged here too.")
      : "";
    drawerCsvCumulative.classList.toggle("hidden", !suspect);
  }

  // The chosen file's coverage line under the File select (§2.2's "uploaded 2026-08-05 · 8,760 rows
  // · hourly / 2025-01-01 → 2025-12-31"). Two sentences joined here rather than one msgid, because
  // the span is absent on a file whose timestamps could not be summarised and the "when/how much"
  // half must still render.
  function csvFileSummary(u) {
    var head = ti("csv_file_summary", "uploaded %(date)s · %(rows)s rows · %(resolution)s", {
      date: csvShortDate(u.uploaded_at),
      rows: csvNumber(u.rows),
      resolution: csvResolutionLabel(u.resolution_s)
    });
    if (!u.first_ts || !u.last_ts) return head;
    return head + " · " + ti("csv_file_span", "%(first)s → %(last)s", {
      first: csvShortDate(u.first_ts), last: csvShortDate(u.last_ts)
    });
  }

  // The three binding controls stage into the draft and nowhere else, exactly like the entity
  // <select> above. Changing the FILE re-populates the columns (and drops a column the new file does
  // not have), which is why the file listener does not write `draft.column` itself.
  if (drawerCsvFile) {
    drawerCsvFile.addEventListener("change", function () {
      draft.uploadId = drawerCsvFile.value || "";
      fillCsvColumnSelect();
      updateConfirmEnabled();
    });
  }
  if (drawerCsvColumn) {
    drawerCsvColumn.addEventListener("change", function () {
      draft.column = drawerCsvColumn.value || "";
      // The warning is per COLUMN, so it is refreshed here as well as in `fillCsvColumnSelect` —
      // that covers a file change and a drawer open, this covers the user picking a column. Called
      // before `updateConfirmEnabled` only for readability; the two are independent, and Confirm's
      // state must not depend on this one (see `updateCsvCumulativeWarning`).
      updateCsvCumulativeWarning();
      updateConfirmEnabled();
    });
  }
  // Delegated, because the two unit radios are static template markup inside the drawer and there is
  // no reason to bind each. The unit is not part of the Confirm gate — it has a default — so this
  // only stages; `updateConfirmEnabled` is still called so the button's state is never computed from
  // a draft it has not seen.
  document.addEventListener("change", function (ev) {
    var el = ev.target;
    if (!el || el.name !== "drawer-csv-unit" || !el.checked) return;
    draft.unit = el.value || DEFAULT_CSV_UNIT;
    updateConfirmEnabled();
  });

  // Reflect the staged unit on the radios when the drawer opens or the CSV radio is picked. The
  // radios are page-level markup shared by every slot, so they hold the LAST slot's answer until
  // this runs — without it, opening a kWh slot after a Wh one would show Wh while the draft said
  // kWh, the same show/draft mismatch `defaultSourceFor` exists to prevent one level up.
  function syncCsvUnitRadios() {
    var unit = draft.unit || DEFAULT_CSV_UNIT;
    Array.prototype.slice.call(
      document.querySelectorAll("input[name=drawer-csv-unit]")
    ).forEach(function (el) { el.checked = (el.value === unit); });
  }

  // Show the CSV controls for this slot: list the workspace's uploads if that has not happened yet,
  // then populate both selects from whatever is cached. The list is fetched at most once per page
  // load here (each dialog open refreshes it separately), so re-picking the radio is instant.
  function applyCsvChoice() {
    syncCsvUnitRadios();
    if (!csvUploadsLoaded) {
      refreshCsvUploads();
    } else {
      fillCsvFileSelect();
    }
  }

  if (csvUploadChooseBtn && csvUploadInput) {
    csvUploadChooseBtn.addEventListener("click", function () { csvUploadInput.click(); });
    csvUploadInput.addEventListener("change", function () {
      uploadCsvFile(csvUploadInput.files && csvUploadInput.files[0]);
    });
  }

  function openDrawer(btn) {
    if (!drawer) return;
    var name = btn.getAttribute("data-slot");
    // Seed the draft from the slot's COMMITTED state (kept across opens), falling back to the
    // button's persisted value so a first open reflects the server's choice. slotState is NOT
    // mutated here — the draft is a private copy the in-drawer controls edit.
    var st = slotState[name] || {
      source: btn.getAttribute("data-slot-source") || null,
      statId: btn.getAttribute("data-slot-stat-id") || "",
      kind: btn.getAttribute("data-slot-kind") || slotKind(name)
    };
    draft.slot = name;
    draft.source = st.source;
    draft.statId = st.statId || "";
    // The CSV binding, seeded from the committed state like the entity id. There is no data-* fallback
    // for these: unlike `statId` the server has no copy to render from (D-BIND), so the `||` defaults
    // are the whole of the fallback and a slot with no committed binding opens with an empty one.
    draft.uploadId = st.uploadId || "";
    draft.column = st.column || "";
    draft.unit = st.unit || DEFAULT_CSV_UNIT;
    loading = false;

    var role = btn.getAttribute("data-slot-role") || name;
    drawerSources = [];
    try { drawerSources = JSON.parse(btn.getAttribute("data-slot-sources") || "[]"); } catch (e) { drawerSources = []; }

    // Start with the entity picker hidden; onSelectSource reveals it for the HA radio.
    // renderSourceList re-checks the radio for the slot's current source and calls onSelectSource —
    // and for a slot with no source yet it stages a default first, so that path runs on a fresh
    // slot too rather than leaving every radio unchecked.
    if (drawerHaEntity) drawerHaEntity.classList.add("hidden");
    // Likewise the CSV binding block: onSelectSource reveals it for the csv_upload radio and for no
    // other source, including the other backend_load ones.
    if (drawerCsvBinding) drawerCsvBinding.classList.add("hidden");
    drawerBackendStatus.textContent = "";

    // The heading is static ("Choose a source"); this subtitle names the slot's role.
    drawerTitle.textContent = role;
    renderSourceList(drawerSources);
    updateConfirmEnabled();

    lastFocus = btn;
    drawer.classList.remove("hidden");
    drawer.setAttribute("aria-hidden", "false");
    if (drawerClose) drawerClose.focus();
  }

  // Close WITHOUT committing: the draft is dropped and the committed slotState / row label are
  // left exactly as they were. This is the Cancel / Escape / ✕ / backdrop path. It must never
  // mutate slotState or call updateSlotButton.
  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.add("hidden");
    drawer.setAttribute("aria-hidden", "true");
    drawerBackendAction.classList.add("hidden");
    drawerHaNote.classList.add("hidden");
    if (drawerHaEntity) drawerHaEntity.classList.add("hidden");
    if (drawerCsvBinding) drawerCsvBinding.classList.add("hidden");
    drawerBackendStatus.textContent = "";
    // Reset in full, binding included. `openDrawer` assigns all six fields unconditionally, so a
    // leftover binding could not actually leak into the next slot's draft today — this keeps the
    // "closed drawer holds nothing" invariant true of the whole object rather than of the fields
    // that happen to be re-seeded, which is what the next reader will assume of it.
    //
    // This is where §2.2's "uploads survive Cancel; the binding does not" is actually true rather
    // than merely stated: the three CSV fields are dropped here, while `csvUploads` — and the files
    // themselves, which are server state — are untouched. An upload made from inside the dialog is
    // a side effect on state SHARED across slots, exactly as a tested Home Assistant connection is,
    // and Cancel has never discarded those.
    draft = { slot: null, source: null, statId: "", uploadId: "", column: "", unit: DEFAULT_CSV_UNIT };
    loading = false;
    if (lastFocus) { try { lastFocus.focus(); } catch (e) { /* ignore */ } }
  }

  // The slot whose default is NOT Home Assistant, and the source it takes instead. The spot price
  // is the one slot a household cannot generally supply from its own HA history: the preset
  // Energy-Charts dataset is committed on disk and bridged live to the end of the window, so it
  // fills the slot with no connection to configure. Defaulting to HA here would preselect the one
  // option that needs setup before it can produce anything.
  var PRESET_DEFAULT_SOURCE = { slot: "price_spot", key: "energy_charts" };

  // Pick the source to stage for a slot that has none committed yet. For the spot-price slot,
  // prefer the preset historical source (PRESET_DEFAULT_SOURCE) when it is offered; otherwise, and
  // as the fallback if it is not, prefer the first browser_fetch (Home Assistant) option, else the
  // first source offered at all. Returns null when the slot offers nothing selectable.
  //
  // Why this exists: without it a fresh slot leaves draft.source null, so NO radio matches at
  // render time, onSelectSource never fires, and the entity <select> is never populated — while the
  // drawer still LOOKS like Home Assistant is chosen. That mismatch between what the drawer shows
  // and what the draft holds is what kept a successful "Test connection" from filling the select.
  //
  // Must be called with a list every member of which actually gets a radio: staging a source whose
  // radio is never rendered would recreate exactly the show/draft mismatch above. Nothing is
  // filtered out of the list any more (`renderSourceList`), so today that is the whole list.
  //
  // `csv_upload` is therefore stageable by this function in principle, and on a slot that offered no
  // Home Assistant option it would be the staged default with an empty binding. Not reachable today:
  // enumerated over all ten slots, every slot whose `sources_for` offers `csv_upload` also offers
  // `home_assistant`, which sorts first in the registry and is what the browser_fetch loop below
  // returns. The PRESET_DEFAULT_SOURCE branch above cannot preempt that for a CSV slot either: it
  // fires only for `price_spot`, and D-PRICE means `price_spot` is never offered `csv_upload`. So
  // this is a guard rather than a live path — the same shape as the ordering note in
  // `renderSourceList`.
  // It is guarded anyway, and safely: `updateConfirmEnabled` will not let an incomplete binding be
  // committed, so the drawer would open on the CSV radio with its controls showing and Confirm greyed
  // out, which is the correct thing to show a user whose only option is a file they have not chosen
  // yet. Nothing here needs changing if a CSV-only slot is ever added.
  function defaultSourceFor(sources, slotName) {
    if (!sources || !sources.length) return null;
    var i;
    if (slotName === PRESET_DEFAULT_SOURCE.slot) {
      for (i = 0; i < sources.length; i++) {
        if (sources[i].key === PRESET_DEFAULT_SOURCE.key) return sources[i];
      }
    }
    for (i = 0; i < sources.length; i++) {
      if (sources[i].kind === "browser_fetch") return sources[i];
    }
    return sources[0];
  }

  // Render the radio list for the current slot's sources.
  //
  // Which slots offer "Upload CSV" is the REGISTRY's decision, not this file's: `CsvSource`'s
  // `available_for` allows every energy slot except `power_grid` and never `price_spot` (D-PRICE),
  // and the descriptor list arrives here already filtered by it, so the radio simply appears where
  // the backend says it can. This function no longer filters anything out. It used to: until step 6
  // there was no file/column/unit control, so selecting a live CSV radio would have staged a
  // `backend_load` slot with an EMPTY binding, which makes `CsvSource` raise and — under the
  // all-or-nothing reify contract — fails the WHOLE fetch, HA slots included. What replaced that
  // filter is `updateConfirmEnabled`'s CSV branch: Confirm stays disabled until a file AND a column
  // are chosen, so an empty binding cannot be committed in the first place. The guard moved from
  // "you may not choose this" to "you may not confirm this half-done", which is the guard the
  // wireframe asks for.
  //
  // A slot with no committed source gets one STAGED here (defaultSourceFor) before the radios are
  // built, so the pre-checked radio and draft.source agree. This is staging only: slotState and the
  // row label are still untouched until Confirm, exactly as for a user-clicked radio. Note that
  // `csv_upload` is now stageable that way — on a slot whose only offered source is CSV,
  // `defaultSourceFor` returns it, and the drawer opens with an empty binding and Confirm disabled.
  // That is the intended state, and it is the Confirm gate that makes it safe.
  function renderSourceList(sources) {
    drawerList.textContent = "";
    haConfigBtn = null;

    if (!draft.source) {
      var def = defaultSourceFor(sources, draft.slot);
      if (def) draft.source = def.key;
    }

    sources.forEach(function (s) {
      var label = document.createElement("label");
      label.className = "flex cursor-pointer items-start gap-3 rounded-box border border-base-300 "
        + "bg-base-100 p-3 hover:border-base-content/30";
      var radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "drawer-source";
      radio.className = "radio radio-sm mt-0.5";
      radio.value = s.key;
      radio.checked = (s.key === draft.source);
      radio.addEventListener("change", function () { onSelectSource(s); });
      var text = document.createElement("div");
      text.className = "flex flex-1 flex-col";
      var name = document.createElement("span");
      name.className = "font-medium";
      name.textContent = s.label;
      var blurb = document.createElement("span");
      blurb.className = "text-xs text-base-content/60";
      blurb.textContent = s.blurb || "";
      text.appendChild(name); text.appendChild(blurb);
      label.appendChild(radio); label.appendChild(text);
      // Home Assistant (browser_fetch) carries a "Configure" button that opens the shared
      // connection modal (#ha-config-dialog). Its label reflects the shared connection state.
      if (s.kind === "browser_fetch") {
        var cfg = document.createElement("button");
        cfg.type = "button";
        cfg.className = "btn btn-outline btn-xs self-center shrink-0";
        cfg.addEventListener("click", function (ev) {
          ev.preventDefault();   // the button sits inside the <label>; don't toggle the radio
          ev.stopPropagation();
          openHaConfig();
        });
        haConfigBtn = cfg;
        label.appendChild(cfg);
      }
      // "Upload CSV" carries an "Upload…" button that opens the shared upload modal
      // (#csv-upload-dialog), for the reason §2.2 gives for making it mirror HA's "Configure…":
      // both manage a resource SHARED across slots, configured once and referenced many times. It
      // is keyed on the source KEY rather than on the kind, because `energy_charts` is the same
      // kind and has nothing to configure.
      //
      // Unlike HA's, this button's label never changes. There is no single "connected" state to
      // reflect: a workspace can hold many uploads at once and none of them is the slot's, until
      // the File select below says which.
      if (s.key === CSV_SOURCE_KEY) {
        var up = document.createElement("button");
        up.type = "button";
        up.className = "btn btn-outline btn-xs self-center shrink-0";
        up.id = "drawer-csv-upload-btn";
        up.textContent = t("upload_button", "Upload…");
        up.addEventListener("click", function (ev) {
          ev.preventDefault();   // the button sits inside the <label>; don't toggle the radio
          ev.stopPropagation();
          openCsvUpload();
        });
        label.appendChild(up);
      }
      drawerList.appendChild(label);
      if (radio.checked) onSelectSource(s);
    });
    updateHaConfigButton();
  }

  // React to a source radio choice: stage it in the draft and show the HA entity picker / note or
  // the backend hint as appropriate. Writes ONLY to the draft — slotState and the row label are
  // untouched until Confirm.
  function onSelectSource(s) {
    draft.source = s.key;
    // A different source invalidates the previously staged entity id.
    if (s.kind !== "browser_fetch") draft.statId = "";
    // …and, symmetrically, the CSV binding. Nothing downstream would misread a stale one —
    // `saveSlotStore` and `stagedBackendSlots` both key on `source === csv_upload`, so a binding
    // sitting on an energy_charts slot is neither stored nor sent. What the clear buys is that
    // re-selecting csv_upload after a detour starts from an EMPTY binding rather than silently
    // reviving the one the user navigated away from, which is the same rule `statId` follows one line
    // up and the one the Confirm gate reads.
    if (s.key !== CSV_SOURCE_KEY) {
      draft.uploadId = "";
      draft.column = "";
      draft.unit = DEFAULT_CSV_UNIT;
    }
    var name = draft.slot;

    var isHa = s.kind === "browser_fetch";
    var isBackend = s.kind === "backend_load";
    // The CSV binding block keys on the source KEY, not on the kind. `csv_upload` IS a backend_load
    // source, so `isBackend` is true for it as well — and `energy_charts` shares that kind while
    // having nothing to bind. `#drawer-backend-action` is only a status line, so showing it for a
    // CSV slot too is harmless and deliberate; the binding controls are the part that must not
    // appear for the other backend sources.
    var isCsv = s.key === CSV_SOURCE_KEY;
    drawerHaNote.classList.toggle("hidden", !isHa);
    if (drawerHaEntity) drawerHaEntity.classList.toggle("hidden", !isHa);
    if (drawerCsvBinding) drawerCsvBinding.classList.toggle("hidden", !isCsv);
    drawerBackendAction.classList.toggle("hidden", !isBackend);
    drawerBackendAction.classList.toggle("flex", isBackend);
    drawerBackendStatus.textContent = "";

    // Picking HA populates the entity <select> for this slot from the shared connection (or shows
    // the connect-first hint) and stages a default id into the draft. Nothing is committed.
    if (isHa) applyHaChoice(name);
    // Picking CSV does the same one level over: list the workspace's uploads if they are not cached
    // yet, populate the File and Column selects, and stage a default FILE (never a default column —
    // see fillCsvColumnSelect). Also nothing committed.
    if (isCsv) applyCsvChoice();
    updateConfirmEnabled();
  }

  // Make the slot use the shared HA connection: (re)populate the drawer entity <select> for it,
  // staging the chosen id into the draft.
  function applyHaChoice(slotName) {
    fillDrawerEntitySelect(slotName);
  }

  // Open the shared HA connection modal. The connection state it produces (haConnected, statIds)
  // is shared across every slot, so configuring from any slot's drawer connects them all.
  function openHaConfig() {
    if (!haConfigDialog) return;
    if (typeof haConfigDialog.showModal === "function") haConfigDialog.showModal();
    else haConfigDialog.setAttribute("open", "");
  }

  // Reflect the shared connection state on the Configure button beside the HA radio:
  // "✓ Connected" once a Test has succeeded, "Configure…" otherwise.
  function updateHaConfigButton() {
    if (!haConfigBtn) return;
    haConfigBtn.textContent = haConnected
      ? t("ha_connected", "✓ Connected")
      : t("configure", "Configure…");
    haConfigBtn.classList.toggle("btn-success", haConnected);
  }

  // Enable Confirm when the draft is committable and no backend load is in flight. A backend
  // source can Confirm as soon as it is picked. A Home Assistant source requires BOTH a tested
  // connection (haConnected) AND a chosen entity (draft.statId) — so every committed HA slot is
  // immediately fetchable. Until the connection is configured, the entity picker stays disabled
  // and Confirm is blocked; the Configure button beside the radio opens the connection modal.
  //
  // An uploaded CSV requires a complete binding, by the SAME predicate the store's two gates use
  // (`csvBindingComplete`). This gate is what replaced the `PENDING_SOURCE_KEYS` filter that used to
  // hide the radio outright: an empty binding staged into a `backend_load` slot makes `CsvSource`
  // raise, and under the all-or-nothing reify contract that failure takes the whole fetch with it,
  // HA slots included. Blocking the commit is the narrowest place to stop that, and it is what §2.2
  // asks for — "Confirm is enabled once a file and a column are chosen".
  function updateConfirmEnabled() {
    if (!drawerConfirmBtn) return;
    var ok;
    if (draft.source === "home_assistant") ok = haConnected && !!draft.statId;
    else if (draft.source === CSV_SOURCE_KEY) ok = csvBindingComplete(draft);
    else ok = !!draft.source;
    drawerConfirmBtn.disabled = loading || !ok;
  }

  // The descriptor for the draft's currently-selected source (or null), from the slot's list.
  function selectedSource() {
    for (var i = 0; i < drawerSources.length; i++) {
      if (drawerSources[i].key === draft.source) return drawerSources[i];
    }
    return null;
  }

  // Update a slot's source-button label (and styling) on the main screen from slotState. The
  // .slot-source-label span carries the text: "Home Assistant · <entity>" (or "· choose entity…"
  // when HA is chosen but no entity yet), "Upload CSV · <file> · <column>" for a bound CSV slot,
  // the plain source label for other sources, or the "Choose source…" affordance when unchosen.
  // The [change] hint is kept if present.
  function updateSlotButton(slotName) {
    var btn = document.querySelector('.slot-source-btn[data-slot="' + cssEscape(slotName) + '"]');
    if (!btn) return;
    var labelEl = btn.querySelector(".slot-source-label");
    if (!labelEl) return;
    var st = slotState[slotName];
    if (!st || !st.source) {
      labelEl.textContent = t("choose_source", "Choose source…");
      return;
    }
    if (st.source === "home_assistant") {
      var suffix = st.statId || t("choose_entity", "choose entity…");
      labelEl.textContent = t("ha_source", "Home Assistant") + " · " + suffix;
    } else if (st.source === CSV_SOURCE_KEY && st.uploadId) {
      // §2.2: "The roster row shows it back as Upload CSV · meterstanden_2025.csv · Verbruik_T1."
      //
      // `slotState` holds the upload ID, never the filename — the id is what the binding means and
      // what the server validates, and a filename is not an identity (two exports may share one).
      // So the name is looked up in the list `refreshCsvUploads` cached, and there are two ways that
      // lookup legitimately misses: the page has not listed the uploads yet (no drawer opened, no
      // dialog opened), or the file is genuinely gone. Both render the placeholder rather than a
      // blank, because a label reading "Upload CSV ·  · Verbruik_T1" would look like a rendering bug
      // rather than a fact about the binding. The first case self-corrects the moment a list arrives
      // (`refreshCsvUploads` re-labels every row); the second is cleared outright by
      // `pruneStaleCsvBindings`, which runs off the same list — so the placeholder is what the user
      // sees only in the window before the workspace's uploads are known.
      var up = csvUploadById(st.uploadId);
      labelEl.textContent = ti("csv_row_label", "Upload CSV · %(file)s · %(column)s", {
        file: up ? up.filename : t("csv_unknown_file", "(file no longer available)"),
        column: st.column || ""
      });
    } else {
      labelEl.textContent = sourceLabel(slotName, st.source);
    }
  }

  // The translated label for a source key, read off the slot button's data-slot-sources payload
  // (labels arrive pre-translated from the template). Falls back to the raw key.
  function sourceLabel(slotName, key) {
    var btn = document.querySelector('.slot-source-btn[data-slot="' + cssEscape(slotName) + '"]');
    if (btn) {
      try {
        var srcs = JSON.parse(btn.getAttribute("data-slot-sources") || "[]");
        for (var i = 0; i < srcs.length; i++) if (srcs[i].key === key) return srcs[i].label;
      } catch (e) { /* fall through */ }
    }
    return key;
  }

  // Minimal CSS.escape shim (slot names are simple identifiers, but be safe for querySelector).
  function cssEscape(s) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(s);
    return String(s).replace(/["\\\]]/g, "\\$&");
  }

  // Confirm — the single primary action. Commits whatever is staged in the draft:
  // Confirm STAGES the choice — for HA and backend_load alike — and never writes server-side
  // (specs §2.2, §3.5): the drawer is a pure staging surface, and the dataset is reified only by
  // Fetch. It commits the draft to slotState, marks the slot locally-customized so saveSlotStore
  // persists it (localStorage, generation-tagged), refreshes the row label, and closes.
  //   * HA (browser_fetch): statId is committed too; the Confirm gate guarantees a tested
  //     connection + a chosen entity, so a staged HA slot is always fetchable.
  //   * backend (backend_load): no statId; the fetch reifies it via a backend_load WS message. For
  //     csv_upload the staged (uploadId, column, unit) binding is committed too and rides along on
  //     that message — the drawer still writes nothing server-side.
  // The CSV branch is reachable from the UI: the radio is live and `updateConfirmEnabled` will not
  // let this run until `csvBindingComplete(draft)` holds, so the committed binding always names both
  // a file and a column. That gate is the only thing standing between a half-filled drawer and a
  // fetch that fails on every slot at once, which is why it lives in `updateConfirmEnabled` rather
  // than as a re-check here — a disabled button is a state the user can see and act on, and a
  // silently-ignored Confirm is not.
  function confirmDraft() {
    var s = selectedSource();
    if (!s || loading) return;

    var name = draft.slot;
    var isHa = draft.source === "home_assistant";
    var isCsv = draft.source === CSV_SOURCE_KEY;
    slotState[name] = {
      source: draft.source,
      statId: isHa ? (draft.statId || "") : "",
      // The binding is committed only for the CSV source, so the committed state cannot carry a
      // binding that does not belong to it — the same rule `statId` follows for HA.
      uploadId: isCsv ? (draft.uploadId || "") : "",
      column: isCsv ? (draft.column || "") : "",
      unit: isCsv ? (draft.unit || DEFAULT_CSV_UNIT) : DEFAULT_CSV_UNIT,
      kind: slotKind(name)
    };
    // A staged choice is a local customization until a fetch persists it server-side. Mark it so
    // saveSlotStore persists it — and only it and its peers, never server-seeded slots — so the
    // choice survives the reload the app may trigger, and is reified on the next Fetch.
    locallyCustomized[name] = true;
    saveSlotStore();
    updateSlotButton(name);
    closeDrawer();
    // Fetch may have just become possible (a first staged slot) or its slot set changed.
    updateFetchEnabled();
  }

  // --- wiring ------------------------------------------------------------------------------
  testBtn.addEventListener("click", testConnection);
  fetchBtn.addEventListener("click", fetchHistory);

  Array.prototype.slice.call(document.querySelectorAll(".slot-source-btn")).forEach(function (btn) {
    btn.addEventListener("click", function () { openDrawer(btn); });
    // Initial label refresh: an HA slot with no re-selectable statId shows "Home Assistant ·
    // choose entity…" so the missing entity is visible before the drawer is opened.
    var name = btn.getAttribute("data-slot");
    if (name && slotState[name] && slotState[name].source) updateSlotButton(name);
  });
  // Seed the Fetch button from what is already staged (e.g. a staged backend slot restored from
  // localStorage, or a persisted HA slot), so a page load with a fetchable config enables it.
  updateFetchEnabled();

  // List the uploads eagerly IF — and only if — some slot arrived bound to one. Two things depend on
  // it and neither can wait for the user to open a drawer:
  //   * the row label, which needs an id→filename map to read "Upload CSV · <file> · <column>"
  //     rather than the "(file no longer available)" placeholder;
  //   * `pruneStaleCsvBindings`, which is how a binding whose file was removed elsewhere surfaces
  //     on this screen instead of at fetch time (the obligation D-BIND left to this step).
  // Gated on there being such a slot so an ordinary page load costs no extra request: with nothing
  // bound, nothing on screen names a file and the list is fetched on first drawer or dialog open.
  if (Object.keys(slotState).some(function (name) {
    return slotState[name] && slotState[name].source === CSV_SOURCE_KEY && slotState[name].uploadId;
  })) {
    refreshCsvUploads();
  }
  // Cancel / ✕ / backdrop / Escape all DISCARD (closeDrawer commits nothing). Confirm commits.
  if (drawerClose) drawerClose.addEventListener("click", closeDrawer);
  if (drawerCancelBtn) drawerCancelBtn.addEventListener("click", closeDrawer);
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);
  if (drawerConfirmBtn) drawerConfirmBtn.addEventListener("click", confirmDraft);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && drawer && !drawer.classList.contains("hidden")) closeDrawer();
  });
})();
