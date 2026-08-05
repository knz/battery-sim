# Phase 5 level 3 — verifying `ws://` to a plain-HTTP Home Assistant

**Status: NOT RUN.** This is a procedure for the user to run against their own Home Assistant.
Nothing in this file has been executed.

## The one question this answers

> Does `ws://` from a page served at `http://127.0.0.1:<port>` reach a **plain-HTTP** LAN Home
> Assistant, and does HA's origin check accept that origin?

The whole desktop direction rests on this. It has been probed **once** and it passed — but that HA
was served over `https://`, so the connection exercised was `wss://`, not `ws://`. The plain-HTTP
LAN case is untested, and it is the configuration that hosting was abandoned for.

## Step 0 — which case will you actually exercise? (do this first)

`app/static/ha_fetch.js` derives the HA scheme from what you type into the HA base-URL field, not
from the page:

- you type `https://ha.local:8123` → it opens **`wss://`** — the case already proven, not the one
  in question;
- you type `http://192.168.x.x:8123` or a **bare** `192.168.x.x:8123` → note the bare form
  **silently becomes `https://`** (`ha_fetch.js` around line 331). So to exercise `ws://` you must
  type the `http://` prefix **explicitly**.

Check now, from any machine on your LAN:

```sh
curl -sS -o /dev/null -w '%{http_code}\n' http://<HA-LAN-IP>:8123/
```

- **200/302/401** → plain HTTP works; the decisive case is testable. Continue.
- **connection refused / timeout / redirect to https** → your HA is https-only. The decisive case
  is **not testable without reconfiguring HA**. Options, in increasing cost: check whether HA also
  listens on plain HTTP by its LAN IP alongside the https route (common when a reverse proxy adds
  the TLS and HA itself is still plain behind it — try the proxy's backend port, often 8123
  directly on the HA host); or temporarily disable the `http:` `ssl_certificate` block in HA's
  `configuration.yaml` and restart. If neither is acceptable, **stop and record that the premise
  remains unverified** — do not report a `wss://` success as if it answered this.

Write down which case you ran. That is the single most important thing to capture.

## Step 1 — what to run

```sh
./Home-Battery-Simulator-x86_64.AppImage
```

It prints `Home Battery Simulator on http://127.0.0.1:<port>/`. Note the port — it is 8137 or an
ephemeral fallback, and **not** the 8000 the earlier probe used, so this also settles the
open question of whether HA's origin check cares about the port.

**For diagnosis, prefer `--browser`:**

```sh
./Home-Battery-Simulator-x86_64.AppImage --browser
```

See "Seeing the console" below for why. `--browser` still serves from `http://127.0.0.1:<port>`,
so it exercises the **same origin and the same scheme** — it is a valid proxy for the origin
question, and the only thing it does not exercise is the WebKit renderer itself.

## Step 2 — what to click

1. Open a workspace (or **+ New analysis**).
2. On the configure-data screen, find the Home Assistant slot roster.
3. Enter the HA base URL **with an explicit `http://` prefix** (step 0) and your long-lived access
   token.
4. Map at least one slot to a real statistic (e.g. `grid_import_t1` → your import meter).
5. Press **Fetch history** over a short window — a few days is plenty. A long window only makes a
   failure slower to reach.

## Step 3 — what SUCCESS looks like

- The slot list populates with your real HA statistic ids (this alone already proves the WebSocket
  connected and authenticated — listing ids is a WS call).
- Progress advances and the fetch completes.
- The configure-data screen then shows a **Data quality** panel and your entity id next to the
  mapped slot, after a page reload — that is the server-side read-back, so the rows persisted.

## Step 4 — the failure signatures, and how to tell them apart

They look similar in the UI ("could not reach Home Assistant") and are distinguished only in the
console and in HA's log. This is why step 5 matters.

| what you see | most likely cause | how to confirm |
|---|---|---|
| Console: `SecurityError` / "insecure WebSocket" / "mixed content" | **Mixed content.** The page is somehow on `https:`, not `http://127.0.0.1`. | Check the address bar scheme. Should not happen with this AppImage — if it does, that is the finding. |
| Console: connection closed immediately after open; HA log shows a rejected/disallowed origin | **HA origin rejection.** The decisive negative result. | HA log line naming the origin. Fix: add `http://127.0.0.1:<port>` to HA `http:` → `cors_allowed_origins`. |
| Console: `ERR_CONNECTION_REFUSED` / connection failed before any HA response | **Network / wrong URL / HA not on plain HTTP.** Not an origin problem at all. | Re-run the `curl` from step 0 from *this* machine. |
| Fetch reaches HA, then an auth error; `auth_invalid` in console or HA log | **Token problem**, unrelated to scheme or origin. | Regenerate the long-lived token in HA → profile → security. |
| Error mentions "could not reach the app's ingest endpoint" | **Our own backend socket**, not HA's. | Already covered by automated tests; report separately. |

The distinction that matters most: an **origin rejection** means HA answered and refused, and is
fixable by config. A **connection refused** means nothing answered, and says nothing about origins.
Do not record one as the other.

## Step 5 — seeing the console (this is the part that makes it diagnosable)

The HA fetch runs in the **browser/webview**, so its console is inside the window. Investigated,
with what is and is not currently possible:

- **`--browser` mode is the practical answer.** It opens your normal browser, where F12 gives you
  full devtools, a network pane that shows the WebSocket frames, and a copyable console. It serves
  the same `http://127.0.0.1:<port>` origin, so the origin question is answered identically.
  **Use this for diagnosis.**
- **The pywebview window has no inspector today.** pywebview *supports* one — `webview.start()`
  takes `debug=True`, and pywebview's GTK backend then sets `enable_developer_extras` and (with
  its default `OPEN_DEVTOOLS_IN_DEBUG`) opens the inspector automatically. But `app/desktop.py`
  does **not** pass `debug`, and there is no CLI flag for it, so right-click → Inspect Element is
  not available in the shipped window. Adding a `--debug` flag would be a small change; it was not
  made as part of phase 5. **Verified by reading `app/desktop.py::_show_window` and pywebview
  6.2.1's `webview/platforms/gtk.py`; not verified by opening an inspector.**
- **`WEBKIT_INSPECTOR`-style env vars do not substitute for it** — the inspector is gated on the
  `enable_developer_extras` WebKitSettings property, which is what `debug=True` sets.
- **stderr still works in both modes.** Run from a terminal; the launcher and any Python-side
  error print there. It will **not** carry JS console output.

So: run `--browser` for the diagnosis, and — if you want to confirm the native window behaves the
same — run the window mode afterwards and check only whether the fetch succeeds, using stderr and
the on-screen error text.

## Step 6 — what to capture

1. **Which case you ran** — `http://` or `https://` in the HA URL field (step 0). Without this the
   result is uninterpretable.
2. The app's port, from the startup line.
3. Browser console: all output during the fetch, especially the first error.
4. Browser network pane: the WebSocket entry to `<HA>/api/websocket` — its status and close code.
5. HA's log around the attempt: Settings → System → Logs, or `home-assistant.log`. Origin
   rejections appear here and nowhere else.
6. Whether the rows landed (step 3's read-back after a reload).

## Step 7 — fallback if it fails

- **If it is an origin rejection:** add to HA `configuration.yaml` and restart:
  ```yaml
  http:
    cors_allowed_origins:
      - http://127.0.0.1:8137
  ```
  This works but is a **user-facing precondition**, which is exactly the cost the desktop direction
  was chosen to avoid. Record it as such. The port must match; pin the app's port with `--port` so
  the allow-list entry stays valid across launches.
- **If it is mixed content:** that would contradict the browser rule the direction rests on and is
  a significant finding. Capture the exact console text.
- **If plain HTTP is untestable at all (step 0):** record the premise as still unverified. Do not
  substitute the `https://` result.

## What a pass here does and does not establish

A pass establishes that a page at `http://127.0.0.1:<port>` can open `ws://` to a plain-HTTP LAN
Home Assistant and that HA accepts that origin — closing R1 for the configuration that motivated
the whole direction.

It does not establish anything about macOS or Windows, about HA installs behind a reverse proxy
that rewrites origins, or about long fetch windows. And a pass obtained in `--browser` mode
exercises the same origin and scheme but not the WebKit renderer — if you only ran `--browser`,
say so.
