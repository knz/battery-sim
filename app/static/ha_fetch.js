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
 *       * data_source_csv (pending)      → the shared "not built yet" dialog (#pending-dialog).
 *
 *     A row may also carry an ⓘ info affordance (SlotSpec.info, specs §4.1). A delegated click on
 *     any .slot-info-btn fills the shared #slot-info-dialog from the button's data-info-title/body
 *     (rendered and translated server-side) and opens it — the same shared-dialog pattern as
 *     #pending-dialog, with no per-slot wiring.
 *
 * Staged-then-confirm model (the crux). The drawer is TRANSACTIONAL: nothing commits on mere
 * selection or on closing. While the drawer is open, all in-drawer controls (source radios, entity
 * <select>) write ONLY to a drawer-local `draft = { slot, source, statId }`. The committed per-slot
 * state lives in `slotState[name] = { source, statId, kind }` and is the ONLY thing updateSlotButton
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
 *     by a backend_load Confirm — and rendered into #source-generation. Confirm on an HA slot saves
 *     { gen, slots: { <slot>: {source, statId} } } tagged with the current generation. On load:
 *       * local gen === server gen → USE LOCAL wholesale (source AND statId): the pre-fetch choice
 *         survives the reload.
 *       * server gen  >  local gen → a fetch has happened since (here or on another client in the
 *         same workspace); the server is authoritative, the stale local slots are dropped.
 *     A fetch advances the generation, so a pre-fetch entry saved beforehand is superseded by the
 *     freshly-persisted server state (which now renders that slot itself, per 1).
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

  // The slot roster carries data-ingest-ws (it used to live on the removed #ha-connection card).
  // Its presence also gates the whole module: no roster → panel not on this page.
  var conn = document.getElementById("slot-roster");
  if (!conn) return;  // panel not on this page

  // Which workspace this page is showing (workspace_data.html's <body data-workspace-id>). The routes are
  // workspace-scoped (docs/specs/08-architecture.md §5.1); the ingest WebSocket path is rendered
  // server-side onto the roster's data-ingest-ws, so this id is needed here only to key the slot
  // store below.
  var WORKSPACE_ID = document.body.getAttribute("data-workspace-id") || "";

  // Per-slot Home Assistant selections, browser-local (specs §7.5, same posture as URL/token).
  // A JSON object { gen: <int>, slots: { <slot>: { source, statId } } } holding ONLY browser_fetch
  // (HA) slots, tagged with the source generation the client saw when it saved (see the file header
  // for the reconcile rule). It exists so an HA slot's source AND chosen entity survive the full-
  // page reload a backend_load Confirm triggers. Backend-load choices are never stored — they are
  // already server-side, and a stored copy would only drift.
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
  //   slotState[name] = { source: <key|null>, statId: <string>, kind: "energy"|"price" }
  // Filled below once we can read the .slot-source-btn nodes; kind derives from the slot name the
  // same way the old template did ('price' in name ? price : energy).
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

  // localStorage-backed HA slot selections, tagged with the generation they were saved at.
  //   { gen: <int>, slots: { <slot>: { source, statId } } }
  // loadSlotStore returns a normalised object (empty slots + gen -1 on any parse error, so it can
  // never equal a real serverGen ≥ 0). saveSlotStore writes only the HA slots out of slotState and
  // stamps the CURRENT serverGen; backend-load choices never land here.
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

  // Persist the locally-customized HA slots, tagged with the generation the client currently sees.
  // This covers only PRE-FETCH customizations: once a slot has been fetched, its source AND entity
  // are persisted server-side (series_meta) and render from the dataset, so the store is not what
  // carries a fetched slot across a reload.
  function saveSlotStore() {
    var slots = {};
    Object.keys(locallyCustomized).forEach(function (name) {
      var st = slotState[name];
      if (!st || !st.source) return;
      // HA is stored only once it has an entity (otherwise it is not yet fetchable); a backend
      // source is stored as soon as it is chosen (it has no entity to wait for).
      if (st.source === "home_assistant") {
        if (st.statId) slots[name] = { source: "home_assistant", statId: st.statId };
      } else {
        slots[name] = { source: st.source, statId: "" };
      }
    });
    try {
      localStorage.setItem(LS_SLOTS, JSON.stringify({ gen: serverGen, slots: slots }));
    } catch (e) { /* quota; ignore */ }
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
    if (local) {
      slotState[name] = { source: local.source, statId: local.statId || "", kind: slotKind(name) };
      // A store entry at the current generation is a pre-fetch customization: keep tracking it so a
      // later save (from customizing another slot) preserves it rather than dropping it.
      locallyCustomized[name] = true;
    } else {
      slotState[name] = {
        source: serverSource,
        statId: serverStatId,
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
  function stagedBackendSlots() {
    return Object.keys(slotState)
      .filter(function (name) {
        var st = slotState[name];
        return st && st.source && backendSourceKeys[st.source] && !slotHidden(name);
      })
      .map(function (name) { return { name: name, source: slotState[name].source }; });
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
        backend.send(JSON.stringify({
          type: "backend_load", name: backends[b].name, source: backends[b].source, window: win
        }));
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

  // The "Configure" button rendered beside the Home Assistant radio (created in renderSourceList).
  // Held here so testConnection / drawer opens can refresh its label to reflect the shared
  // connection state ("Configure…" vs "✓ Connected").
  var haConfigBtn = null;

  // Drawer-local staging. `draft` is the ONLY thing the in-drawer controls write to while the
  // drawer is open; it is seeded from the committed slotState on open and applied to slotState
  // only on Confirm. `sources` holds the current slot's source descriptors (for Confirm to read
  // the selected source's kind). `loading` guards Confirm during a backend load.
  var draft = { slot: null, source: null, statId: "" };
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
    loading = false;

    var role = btn.getAttribute("data-slot-role") || name;
    drawerSources = [];
    try { drawerSources = JSON.parse(btn.getAttribute("data-slot-sources") || "[]"); } catch (e) { drawerSources = []; }

    // Start with the entity picker hidden; onSelectSource reveals it for the HA radio.
    // renderSourceList re-checks the radio for the slot's current source and calls onSelectSource —
    // and for a slot with no source yet it stages a default first, so that path runs on a fresh
    // slot too rather than leaving every radio unchecked.
    if (drawerHaEntity) drawerHaEntity.classList.add("hidden");
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
    drawerBackendStatus.textContent = "";
    draft = { slot: null, source: null, statId: "" };
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

  // Render the radio list for the current slot's sources, plus the pending "Upload CSV" option.
  //
  // A slot with no committed source gets one STAGED here (defaultSourceFor) before the radios are
  // built, so the pre-checked radio and draft.source agree. This is staging only: slotState and the
  // row label are still untouched until Confirm, exactly as for a user-clicked radio.
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
      drawerList.appendChild(label);
      if (radio.checked) onSelectSource(s);
    });
    updateHaConfigButton();

    // Pending "Upload CSV" option — disabled, with the [?] affordance that opens the shared
    // pending dialog (workspace_data.html #pending-dialog, feature key data_source_csv).
    drawerList.appendChild(csvPendingOption());
  }

  function csvPendingOption() {
    var wrap = document.createElement("label");
    wrap.className = "flex items-start gap-3 rounded-box border border-base-300 bg-base-100 "
      + "p-3 opacity-60";
    var radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "drawer-source";
    radio.className = "radio radio-sm mt-0.5";
    radio.disabled = true;
    var text = document.createElement("div");
    text.className = "flex flex-col";
    var row = document.createElement("span");
    row.className = "flex items-center gap-2 font-medium";
    var name = document.createElement("span");
    name.textContent = t("upload_csv", "Upload CSV");
    var help = document.createElement("button");
    help.type = "button";
    help.className = "btn btn-ghost btn-xs";
    help.textContent = "[?]";
    // The shared pending dialog (workspace_data.html) binds these attributes via a delegated click
    // listener, so this dynamically-created button opens it with no wiring here (§2.1).
    help.setAttribute("data-pending-name", t("upload_csv", "Upload CSV"));
    help.setAttribute("data-feature-key", "data_source_csv");
    row.appendChild(name); row.appendChild(help);
    var blurb = document.createElement("span");
    blurb.className = "text-xs text-base-content/60";
    blurb.textContent = t("pending_hint", "Not built yet");
    text.appendChild(row); text.appendChild(blurb);
    wrap.appendChild(radio); wrap.appendChild(text);
    return wrap;
  }

  // React to a source radio choice: stage it in the draft and show the HA entity picker / note or
  // the backend hint as appropriate. Writes ONLY to the draft — slotState and the row label are
  // untouched until Confirm.
  function onSelectSource(s) {
    draft.source = s.key;
    // A different source invalidates the previously staged entity id.
    if (s.kind !== "browser_fetch") draft.statId = "";
    var name = draft.slot;

    var isHa = s.kind === "browser_fetch";
    var isBackend = s.kind === "backend_load";
    drawerHaNote.classList.toggle("hidden", !isHa);
    if (drawerHaEntity) drawerHaEntity.classList.toggle("hidden", !isHa);
    drawerBackendAction.classList.toggle("hidden", !isBackend);
    drawerBackendAction.classList.toggle("flex", isBackend);
    drawerBackendStatus.textContent = "";

    // Picking HA populates the entity <select> for this slot from the shared connection (or shows
    // the connect-first hint) and stages a default id into the draft. Nothing is committed.
    if (isHa) applyHaChoice(name);
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
  function updateConfirmEnabled() {
    if (!drawerConfirmBtn) return;
    var ok;
    if (draft.source === "home_assistant") ok = haConnected && !!draft.statId;
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
  // when HA is chosen but no entity yet), the plain source label for other sources, or the
  // "Choose source…" affordance when unchosen. The [change] hint is kept if present.
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
  //   * backend (backend_load): no statId; the fetch reifies it via a backend_load WS message.
  // The pending CSV option's radio is disabled, so draft.source can never be it here.
  function confirmDraft() {
    var s = selectedSource();
    if (!s || loading) return;

    var name = draft.slot;
    var isHa = draft.source === "home_assistant";
    slotState[name] = {
      source: draft.source,
      statId: isHa ? (draft.statId || "") : "",
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
  // Cancel / ✕ / backdrop / Escape all DISCARD (closeDrawer commits nothing). Confirm commits.
  if (drawerClose) drawerClose.addEventListener("click", closeDrawer);
  if (drawerCancelBtn) drawerCancelBtn.addEventListener("click", closeDrawer);
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);
  if (drawerConfirmBtn) drawerConfirmBtn.addEventListener("click", confirmDraft);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && drawer && !drawer.classList.contains("hidden")) closeDrawer();
  });
})();
