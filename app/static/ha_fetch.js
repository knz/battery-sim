/*
 * ha_fetch.js — browser-side Home Assistant fetch and hand-off (specs/06-home-assistant-ingestion.md).
 *
 * The data import runs in the browser, not the backend: the end user's browser is the only thing
 * that can reach their (often LAN-only, self-signed) Home Assistant instance, and keeping the fetch
 * here means the long-lived access token never leaves the browser (specs §7.5). The token is held
 * in localStorage and sent only to the user's own HA. The rows we fetch are streamed to our backend
 * over a WebSocket (WS /data/ingest/ws), which normalises and persists them (app/ingest_ws.py).
 *
 * Two user actions, wired to the panel-① controls (templates/_panel_data.html):
 *   Test connection  — open wss://<ha>/api/websocket, auth, recorder/list_statistic_ids, and fill
 *                       the mapping <select>s (energy ids for energy slots, mean ids for price).
 *   Fetch history    — for each mapped slot, recorder/statistics_during_period over the full window
 *                       at period "hour", plus period "5minute" over the trailing HA_FINE_WINDOW_DAYS
 *                       (specs §4.3). Stream the rows to the backend, then reload so the server
 *                       re-renders panel ① from the persisted dataset (specs §3.5 LOAD_SUCCEEDED).
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
  var selects = Array.prototype.slice.call(document.querySelectorAll(".ha-map-select"));

  // Restore the last URL/token from localStorage (browser-local; never server-side, §7.5).
  urlInput.value = localStorage.getItem(LS_URL) || urlInput.value || "";
  tokenInput.value = localStorage.getItem(LS_TOKEN) || "";

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
  // Test connection: list ids, fill the mapping selects.
  // -----------------------------------------------------------------------------------------
  var statIds = { energy: [], price: [] };  // populated by testConnection

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
      fillSelects();
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

  function fillSelects() {
    selects.forEach(function (sel) {
      var kind = sel.getAttribute("data-kind") === "price" ? "price" : "energy";
      var current = sel.value;
      // Keep the "— none —" first option, replace the rest.
      while (sel.options.length > 1) sel.remove(1);
      statIds[kind].forEach(function (id) {
        var opt = document.createElement("option");
        opt.value = id; opt.textContent = id;
        sel.appendChild(opt);
      });
      // Best-effort auto-map: if a stat id contains the series name's key tokens, preselect it.
      if (!current) {
        var guess = guessId(sel.getAttribute("data-series"), statIds[kind]);
        if (guess) sel.value = guess;
      } else {
        sel.value = current;
      }
    });
  }

  // Heuristic auto-map from the slot name to a statistic id. Purely a convenience — the user
  // confirms by fetching; a wrong guess is corrected in the dropdown. Not a mapping authority.
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
  // Fetch history: pull statistics per mapped slot, stream to the backend.
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

  function mappedSlots() {
    return selects
      .filter(function (sel) { return sel.value; })
      .map(function (sel) {
        return {
          name: sel.getAttribute("data-series"),
          kind: sel.getAttribute("data-kind") === "price" ? "price" : "energy",
          statId: sel.value
        };
      });
  }

  async function fetchHistory() {
    var base = urlInput.value.trim(), token = tokenInput.value.trim();
    var slots = mappedSlots();
    if (!slots.length) {
      setStatus(fetchStatus, "Map at least one series first.", "text-warning");
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

      var endMs = Date.now();
      var startMs = endMs - HISTORY_DAYS * 86400000;
      var win = { start: new Date(startMs).toISOString(), end: new Date(endMs).toISOString() };
      backend.send(JSON.stringify({ type: "header", source: "home_assistant", window: win }));

      var total = slots.length, done = 0;
      for (var i = 0; i < slots.length; i++) {
        var slot = slots[i];
        setStatus(fetchStatus, "Fetching " + slot.name + " (" + (i + 1) + "/" + total + ")…",
          "text-base-content/60");
        backend.send(JSON.stringify({ type: "series", name: slot.name, kind: slot.kind }));

        // Hourly over the full window, chunked.
        var chunks = chunkWindows(startMs, endMs, HA_CHUNK_DAYS);
        for (var c = 0; c < chunks.length; c++) {
          await fetchAndForward(ha, backend, slot, chunks[c][0], chunks[c][1], "hour");
        }
        // 5-minute over the trailing fine window (§4.3), for the resolution-bias diagnostic.
        await fetchAndForward(ha, backend, slot, isoDaysAgo(HA_FINE_WINDOW_DAYS),
          new Date(endMs).toISOString(), "5minute");

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

  // --- wiring ------------------------------------------------------------------------------
  testBtn.addEventListener("click", testConnection);
  fetchBtn.addEventListener("click", fetchHistory);
})();
