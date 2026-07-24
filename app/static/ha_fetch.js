/*
 * ha_fetch.js — browser-side Home Assistant fetch + the slot-first source-picker drawer
 * (specs/06-home-assistant-ingestion.md, specs/02-ux-wireframes.md §2.2).
 *
 * Two responsibilities live here now:
 *
 *  1. The shared Home Assistant connection and browser-side fetch. The data import runs in the
 *     browser, not the backend: the user's browser is the only thing that can reach their (often
 *     LAN-only, self-signed) HA instance, and keeping the fetch here means the long-lived access
 *     token never leaves the browser (specs §7.5). The token is held in localStorage and sent
 *     only to the user's own HA. The connection is SHARED across slots: the user tests once
 *     (URL + token + Test connection), and the listed statistic ids are then reused for every
 *     HA-source slot. Fetched rows stream to our backend over WS /data/ingest/ws
 *     (app/ingest_ws.py), which normalises and persists them.
 *
 *  2. The slot-first source-picker drawer. Each slot row (templates/_panel_data.html) has a
 *     "Choose source…" button carrying the slot name, its kind (energy/price), and its source
 *     list (data-slot-sources). A click opens the shared right-side drawer (#source-drawer in
 *     index.html) listing those sources as radios. Picking a source:
 *       * home_assistant (browser_fetch) → the drawer reveals a single entity <select>
 *         (#drawer-entity-select), populated for THIS slot from the shared connection's listing.
 *       * energy_charts (backend_load)   → Confirm POSTs /data/slot/{slot}/load {source, window}
 *         and reloads so panel ① re-renders from the persisted dataset (specs §3.5).
 *       * data_source_csv (pending)      → the shared "not built yet" dialog (#pending-dialog).
 *
 * Staged-then-confirm model (the crux). The drawer is TRANSACTIONAL: nothing commits on mere
 * selection or on closing. While the drawer is open, all in-drawer controls (source radios, entity
 * <select>) write ONLY to a drawer-local `draft = { slot, source, statId }`. The committed per-slot
 * state lives in `slotState[name] = { source, statId, kind }` and is the ONLY thing updateSlotButton
 * and mappedSlots read. openDrawer seeds `draft` from the committed slotState (so the current choice
 * shows pre-selected) without touching slotState. A single Confirm button commits:
 *       * HA source   → writes draft → slotState, refreshes the row label, closes. No reload.
 *       * backend     → runs the load POST (as the old "Use this source" did) and reloads on success.
 * Cancel / Escape / ✕ / backdrop DISCARD: closeDrawer reverts to the committed state and never
 * mutates slotState or the row label. slotState is seeded from each .slot-source-btn's data-*
 * attributes at load (the committed initial state). mappedSlots() (used by Fetch history) reads
 * slotState — the HA slots whose statId is set — so the fetch depends only on committed state.
 *
 * User actions on the connection card:
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
  var LS_URL = "ha.base_url";
  var LS_TOKEN = "ha.token";

  var conn = document.getElementById("ha-connection");
  if (!conn) return;  // panel not on this page

  var urlInput = document.getElementById("ha-base-url");
  var tokenInput = document.getElementById("ha-token");
  var testBtn = document.getElementById("ha-test-btn");
  var statusEl = document.getElementById("ha-status");
  var fetchBtn = document.getElementById("ha-fetch-btn");
  var fetchStatus = document.getElementById("ha-fetch-status");
  var progressEl = document.getElementById("ha-fetch-progress");

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

  // Restore the last URL/token from localStorage (browser-local; never server-side, §7.5).
  urlInput.value = localStorage.getItem(LS_URL) || urlInput.value || "";
  tokenInput.value = localStorage.getItem(LS_TOKEN) || "";

  // Seed slotState from the slot source buttons. Each button carries the slot name, its persisted
  // source (data-slot-source), and its kind (data-slot-kind). The persisted view-model does not
  // carry a re-selectable statistic id (only a coverage summary), so statId starts empty and is
  // set when the user picks an entity in the drawer this session.
  Array.prototype.slice.call(document.querySelectorAll(".slot-source-btn")).forEach(function (btn) {
    var name = btn.getAttribute("data-slot");
    if (!name) return;
    slotState[name] = {
      source: btn.getAttribute("data-slot-source") || null,
      statId: "",
      kind: btn.getAttribute("data-slot-kind") || slotKind(name)
    };
  });

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
        reject(new Error("Could not open a WebSocket to " + self.url));
        return;
      }
      self.ws = ws;
      ws.onerror = function () {
        reject(new Error("Connection failed. Check the URL, and that your browser trusts the "
          + "certificate (open " + self.url.replace(/^ws/, "http") + " once to accept it)."));
      };
      ws.onclose = function () {
        Object.keys(self.pending).forEach(function (k) {
          self.pending[k].reject(new Error("connection closed"));
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
          reject(new Error("Home Assistant rejected the token."));
        } else if (msg.type === "result") {
          var p = self.pending[msg.id];
          if (p) {
            delete self.pending[msg.id];
            if (msg.success) p.resolve(msg.result);
            else p.reject(new Error((msg.error && msg.error.message) || "HA error"));
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
      setStatus(statusEl, "Enter a base URL and token first.", "text-warning");
      return;
    }
    localStorage.setItem(LS_URL, base);
    localStorage.setItem(LS_TOKEN, token);
    setStatus(statusEl, "Connecting…", "text-base-content/60");
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
      // "connect first" hint; repopulate it now. Otherwise the ids are just stored for the next
      // drawer open.
      if (draft.slot && draft.source === "home_assistant") {
        fillDrawerEntitySelect(draft.slot);
      }
      setStatus(statusEl, "✓ Connected · " + statIds.energy.length + " energy + "
        + statIds.price.length + " measurement statistics", "text-success");
      fetchBtn.disabled = false;
    } catch (e) {
      setStatus(statusEl, "✗ " + e.message, "text-error");
      fetchBtn.disabled = true;
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
      hint.textContent = t("connect_first", "Connect Home Assistant above first");
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
    // Preselect: the draft's current id, else a heuristic guess. The guess is a staged default —
    // shown pre-selected in the dropdown and stored in draft.statId, but NOT committed; it only
    // reaches slotState (and the row label) on Confirm. Nothing here touches slotState.
    var pick = draft.statId || guessId(slotName, statIds[kind]) || "";
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

  // Slots whose chosen source is Home Assistant AND that have an entity chosen (slotState). This
  // is the sole source of truth for the fetch — there is no per-row DOM select any more.
  function mappedSlots() {
    return Object.keys(slotState)
      .filter(function (name) {
        var st = slotState[name];
        return st && st.source === "home_assistant" && st.statId;
      })
      .map(function (name) {
        var st = slotState[name];
        return { name: name, kind: st.kind === "price" ? "price" : "energy", statId: st.statId };
      });
  }

  async function fetchHistory() {
    var base = urlInput.value.trim(), token = tokenInput.value.trim();
    var slots = mappedSlots();
    if (!slots.length) {
      setStatus(fetchStatus, "Map at least one Home Assistant series first.", "text-warning");
      return;
    }
    fetchBtn.disabled = true;
    testBtn.disabled = true;
    progressEl.classList.remove("hidden");
    progressEl.removeAttribute("value");  // indeterminate until we know totals

    var ha = new HaClient(base, token);
    var backend = null;
    try {
      await ha.connect();
      backend = await openBackend();

      var w = historyWindow();
      var win = { start: w.start, end: w.end };
      backend.send(JSON.stringify({ type: "header", source: "home_assistant", window: win }));

      var total = slots.length, done = 0;
      for (var i = 0; i < slots.length; i++) {
        var slot = slots[i];
        setStatus(fetchStatus, "Fetching " + slot.name + " (" + (i + 1) + "/" + total + ")…",
          "text-base-content/60");
        backend.send(JSON.stringify({ type: "series", name: slot.name, kind: slot.kind }));

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

      var result = await finishBackend(backend);
      setStatus(fetchStatus, "✓ Imported " + result.series + " series. Reloading…", "text-success");
      // The server now has the dataset; reload so panel ① re-renders from it (§3.5).
      setTimeout(function () { window.location.reload(); }, 600);
    } catch (e) {
      setStatus(fetchStatus, "✗ " + e.message, "text-error");
      fetchBtn.disabled = false;
    } finally {
      ha.close();
      testBtn.disabled = false;
      progressEl.classList.add("hidden");
    }
  }

  // Fetch one (slot, window, period) from HA and forward its rows to the backend. Rows are
  // reshaped to the compact arrays the ingest protocol expects: [start_ms, sum] for energy,
  // [start_ms, mean, min, max] for price (specs app/ingest_ws.py).
  async function fetchAndForward(ha, backend, slot, startIso, endIso, period) {
    var payload = {
      type: "recorder/statistics_during_period",
      start_time: startIso, end_time: endIso,
      statistic_ids: [slot.statId], period: period
    };
    if (slot.kind === "price") payload.types = ["mean", "min", "max"];
    else payload.types = ["sum"];

    var result = await ha.call(payload);
    var rows = (result && result[slot.statId]) || [];
    if (!rows.length) return;

    var packed = rows.map(function (r) {
      if (slot.kind === "price") {
        return [r.start, nz(r.mean), nz(r.min), nz(r.max)];
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
      ws.onerror = function () { reject(new Error("Could not reach the app's ingest endpoint.")); };
    });
  }

  // Send `done` and await the backend's `result` (or surface its `error`). Progress frames the
  // backend emits after each rows batch are consumed here without blocking.
  function finishBackend(ws) {
    return new Promise(function (resolve, reject) {
      ws.onmessage = function (ev) {
        var msg = JSON.parse(ev.data);
        if (msg.type === "result") resolve(msg);
        else if (msg.type === "error") reject(new Error("Ingest rejected: " + msg.message));
        // "progress" frames are ignored — the client tracks its own per-series progress.
      };
      ws.onclose = function () { reject(new Error("Ingest connection closed early.")); };
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
      statId: "",
      kind: btn.getAttribute("data-slot-kind") || slotKind(name)
    };
    draft.slot = name;
    draft.source = st.source;
    draft.statId = st.statId || "";
    loading = false;

    var role = btn.getAttribute("data-slot-role") || name;
    drawerSources = [];
    try { drawerSources = JSON.parse(btn.getAttribute("data-slot-sources") || "[]"); } catch (e) { drawerSources = []; }

    // Start with the entity picker hidden; onSelectSource reveals it for the HA radio (if the
    // slot's current source is HA, renderSourceList re-checks that radio and calls onSelectSource).
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

  // Render the radio list for the current slot's sources, plus the pending "Upload CSV" option.
  function renderSourceList(sources) {
    drawerList.textContent = "";

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
      text.className = "flex flex-col";
      var name = document.createElement("span");
      name.className = "font-medium";
      name.textContent = s.label;
      var blurb = document.createElement("span");
      blurb.className = "text-xs text-base-content/60";
      blurb.textContent = s.blurb || "";
      text.appendChild(name); text.appendChild(blurb);
      label.appendChild(radio); label.appendChild(text);
      drawerList.appendChild(label);
      if (radio.checked) onSelectSource(s);
    });

    // Pending "Upload CSV" option — disabled, with the [?] affordance that opens the shared
    // pending dialog (index.html #pending-dialog, feature key data_source_csv).
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
    // The shared pending dialog (index.html) binds these attributes via a delegated click
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

  // Enable Confirm when the draft has a source selected and no backend load is in flight. A
  // backend source can Confirm as soon as it is picked; an HA source can Confirm with or without
  // an entity (committing HA with an empty id shows "· choose entity…" on the row and leaves the
  // slot un-fetchable — a deliberate, reversible state).
  function updateConfirmEnabled() {
    if (!drawerConfirmBtn) return;
    drawerConfirmBtn.disabled = loading || !draft.source;
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
  //   * HA (browser_fetch): write draft → committed slotState, refresh the row label, close. No
  //     round-trip; the fetch picks the slot up via mappedSlots(). Committing with an empty entity
  //     is allowed (row shows "· choose entity…", slot not yet fetchable).
  //   * backend (backend_load): POST the slot load and reload on success (as "Use this source"
  //     did). On error the message stays in the drawer and nothing is committed/closed.
  // The pending CSV option's radio is disabled, so draft.source can never be it here.
  function confirmDraft() {
    var s = selectedSource();
    if (!s || loading) return;

    if (s.kind === "backend_load") { confirmBackend(s); return; }

    // HA (or any non-backend selectable source): commit to slotState, update the row, close.
    var name = draft.slot;
    slotState[name] = {
      source: draft.source === "home_assistant" ? "home_assistant" : draft.source,
      statId: draft.source === "home_assistant" ? (draft.statId || "") : "",
      kind: slotKind(name)
    };
    updateSlotButton(name);
    closeDrawer();
  }

  // The backend arm of Confirm: POST the slot load and reload. Kept separate for the async flow.
  async function confirmBackend(s) {
    var w = historyWindow();
    var slot = draft.slot;
    loading = true;
    updateConfirmEnabled();
    drawerBackendStatus.textContent = t("loading", "Loading…");
    drawerBackendStatus.className = "text-sm text-base-content/60";
    try {
      var resp = await fetch("/data/slot/" + encodeURIComponent(slot) + "/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: s.key, window: { start: w.start, end: w.end } })
      });
      if (!resp.ok) {
        var detail = "";
        try { detail = (await resp.json()).detail || ""; } catch (e) { /* non-JSON error */ }
        throw new Error(detail || (resp.status + " " + resp.statusText));
      }
      drawerBackendStatus.textContent = t("loaded_ok", "Loaded. Reloading…");
      drawerBackendStatus.className = "text-sm text-success";
      // The server persisted the slot; reload so panel ① re-renders from the dataset (§3.5).
      setTimeout(function () { window.location.reload(); }, 500);
    } catch (e) {
      drawerBackendStatus.textContent = "✗ " + (e.message || t("load_failed", "Could not load."));
      drawerBackendStatus.className = "text-sm text-error";
      loading = false;
      updateConfirmEnabled();
    }
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
  // Cancel / ✕ / backdrop / Escape all DISCARD (closeDrawer commits nothing). Confirm commits.
  if (drawerClose) drawerClose.addEventListener("click", closeDrawer);
  if (drawerCancelBtn) drawerCancelBtn.addEventListener("click", closeDrawer);
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);
  if (drawerConfirmBtn) drawerConfirmBtn.addEventListener("click", confirmDraft);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && drawer && !drawer.classList.contains("hidden")) closeDrawer();
  });
})();
