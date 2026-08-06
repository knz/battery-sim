"""Desktop launcher: resolve the data directory, start uvicorn on the loopback, show the UI.

This is what a packaged Home Battery Simulator runs when the user double-clicks it, and what
`python -m app` runs from a source checkout. Phase 2 of desktop packaging: the UI is a native
pywebview window by default, with the browser kept as a fallback and as an explicit flag. No
packaging tooling yet — that is phase 3.

The order of operations is load-bearing and is the main reason this module exists at all:

  1. `multiprocessing.freeze_support()`, before anything else;
  2. resolve the per-user data directory and put it in `BATTERY_SIM_DATA_DIR`, then start the
     session log and point `ssl` at the OS trust store (`app/net_trust.py`) — in that order, so
     the one thing the second can complain about lands in the file;
  3. take the single-instance lock, or hand off to the instance that already holds it;
  4. **only then** import `app.main` — see `_load_asgi_app` for what breaks otherwise;
  5. check the bundled assets are really there;
  6. start uvicorn bound to 127.0.0.1 on a BACKGROUND thread, poll until it answers, show the UI
     on the MAIN thread, and shut the server down when the UI is done.

Step 6 is inverted from phase 1, where uvicorn owned the main thread. `webview.start()` is a
blocking GUI loop that must run on the main thread (GTK and Cocoa both require it), so uvicorn
moved off it. `_ServerThread` and `UiMode` carry the consequences; see `run`.

Main items:
    main()                  entry point; parses --port / --browser / --no-browser.
    run(port, ui)           the launcher itself, once the arguments are parsed.
    UiMode                  WINDOW / BROWSER / NONE — the three ways the UI can be presented.
    _show_ui(url, mode)     dispatch over `UiMode`; returns whether the call blocked.
    _show_window(url)       the pywebview window. Raises when there is no renderer.
    _show_fallback_dialog() the tkinter "here is the URL" dialog, when the window fails.
    _ServerThread           uvicorn on a daemon thread, with a cooperative `stop()`.
    resolve_data_dir()      per-user data dir, set into the environment via `setdefault`.
    choose_port(preferred)  `preferred` if bindable, otherwise an ephemeral port.
    BIND_HOST               `127.0.0.1`. Never made configurable — see `run`.
    DEFAULT_PORT            8137.
    SingleInstance          the `<data_dir>/desktop.lock` exclusive lock, and its takeover rules.
    check_assets()          fail early and by name when a bundled asset directory is missing.
    _ensure_std_streams()   stdout/stderr are never None, even in a windowed frozen build.
    start_session_log()     redirect stdout/stderr into `<data_dir>/logs/session-*.log`.
    _Tee                    write to the log and the terminal at once, when a TTY is attached.
    _prune_old_logs()       delete session logs older than 90 days.
"""

from __future__ import annotations

import argparse
import enum
import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

# `net_trust` is safe to import here because it pulls in no part of the ASGI app — `app.main` is
# loaded later and inside a function (`_load_asgi_app`), the data directory having to be resolved
# first. It imports `truststore` lazily, inside the call, so this line stays cheap.
from app import config, net_trust

BIND_HOST = "127.0.0.1"
"""The only host this app is ever bound to. Not a setting — see `run` for why.

`app/csrf.py` states the threat model plainly: every route is unauthenticated, and a request
carrying neither `Sec-Fetch-Site` nor `Origin` is ALLOWED because "what DOES arrive with neither
is curl, a test client, a scripted local tool … all of which are the user acting on their own
machine". That sentence is true only while the socket is on the loopback. Bound to `0.0.0.0`,
every machine on the LAN can delete the user's workspaces with a header-free POST, and the
`csrf` module's one deliberate hole becomes an unauthenticated remote delete.

docs/specs/15-data-quality-and-limits.md §7.5 requires the same thing from the other direction:
"Bind to 127.0.0.1 by default. If the user wants LAN access, make them change the [setting]" —
and this launcher offers no such setting, so the loopback is the only reachable configuration.
"""

DEFAULT_PORT = 8137
"""The port tried first. Chosen high, outside the ephemeral range, and unassigned by IANA.

A MOSTLY STABLE port rather than always-ephemeral, because the page origin is part of the app's
externally visible identity: Home Assistant applies an origin check to its WebSocket API, so a
user whose HA instance has been told to allow `http://127.0.0.1:8137` keeps working across
launches. An ephemeral port would move the origin on every start and break that allowance each
time. It is a preference and not a guarantee — `choose_port` falls back when the port is taken.
"""

_LOCK_FILENAME = "desktop.lock"

_READY_TIMEOUT_S = 20.0
"""How long `wait_until_ready` waits for the server's first answer before giving up.

Mirrors the smoke test's deadline (`tests/test_smoke.py`), which starts the same app the same
way. Generous: a cold start on a slow disk imports numpy, fastapi and the Jinja environments.
"""

_SHUTDOWN_TIMEOUT_S = 10.0
"""How long `run` waits for the server thread to finish after asking it to stop.

`uvicorn.Server.should_exit` is a cooperative flag — the serve loop notices it on its next tick
and then runs the normal ASGI shutdown — so a request in flight delays the exit by however long
that request takes. Ten seconds covers a simulation run finishing its response; past that the
thread's `daemon=True` is what actually ends the process, and the launcher says so on stderr
rather than hanging a closed window's process forever.
"""

_WINDOW_TITLE = "Home Battery Simulator"
_WINDOW_SIZE = (1280, 860)
"""Opening size of the native window. Wide enough for the results screen's charts side by side;
the window is resizable, so this is a starting point rather than a layout commitment."""

_ASSET_DIRS = ("templates", "static", "locales", "data")
"""Directories that must be present and non-empty beside `app/` for the app to render anything.

Each is loaded lazily by a different module — templates by `app.i18n`, static files by the mount
in `app.main`, locales by the catalog loader, `data/` by the ENTSO-E spot-price source — so a
bundle that failed to collect one surfaces as a 500 on whichever page the user happens to open
first, hours later and far from the cause. `check_assets` turns that into a startup failure that
names the missing directory.
"""


# ── data directory ────────────────────────────────────────────────────────────


def resolve_data_dir() -> Path:
    """Put the per-user data directory into `BATTERY_SIM_DATA_DIR` and return it.

    `os.environ.setdefault`, never assignment: a user, an operator or a test that deliberately
    pointed the variable somewhere keeps that choice. This is the same reasoning — and the same
    spelling — as `tests/conftest.py::_isolate_data_dir`.

    **This must run before `app.main` is imported.** See `_load_asgi_app`.
    """
    resolved = os.environ.setdefault(config.ENV_DATA_DIR, str(config.user_data_dir()))
    path = Path(resolved)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── port ──────────────────────────────────────────────────────────────────────


def _is_bindable(port: int) -> bool:
    """Can we bind `port` on the loopback right now?

    Deliberately without `SO_REUSEADDR`: the question is "is anything using this port", and
    SO_REUSEADDR would answer yes to a port a lingering socket still holds, after which uvicorn's
    own bind would fail and the launcher would have nothing to fall back to.
    """
    with socket.socket() as s:
        try:
            s.bind((BIND_HOST, port))
        except OSError:
            return False
    return True


def _ephemeral_port() -> int:
    """A free port, chosen by the OS. Same idiom as `tests/test_smoke.py::_free_port`.

    Inherently a small race — the port is released when this socket closes and could in principle
    be taken before uvicorn binds it — but on a single-user desktop machine, in the microseconds
    between the two, it is not a case worth carrying machinery for.
    """
    with socket.socket() as s:
        s.bind((BIND_HOST, 0))
        return s.getsockname()[1]


def choose_port(preferred: int = DEFAULT_PORT) -> int:
    """`preferred` when it is free, otherwise an ephemeral one (see `DEFAULT_PORT`)."""
    if _is_bindable(preferred):
        return preferred
    return _ephemeral_port()


# ── single instance ───────────────────────────────────────────────────────────


class SingleInstance:
    """An exclusive lock on `<data_dir>/desktop.lock`, recording the live instance's port and PID.

    **Needed rather than nice to have.** Two processes against one SQLite file (`app/db.py`) and
    one workspace directory tree can interleave a `upsert_series` DELETE/INSERT pair or a
    workspace deletion with a write, and users double-click a desktop icon twice as a matter of
    course. A second launch must therefore not start a second server.

    The lock is an OS-level advisory lock on an open file descriptor, not the mere existence of
    the file — `fcntl.flock` on POSIX, `msvcrt.locking` on Windows, imported per platform. That
    choice is what makes staleness self-resolving: when the holding process dies, however it dies,
    the kernel releases the lock, so a crashed instance leaves a file that the next launch simply
    takes over. A PID-file scheme would instead need to guess whether the recorded PID is still
    this app, and PIDs are reused.

    The file's CONTENT (`{"port": …, "pid": …}`) is read by the loser of the race, so a second
    launch can open the running instance's URL instead of failing with a message. It is written
    after the lock is taken and is only ever trusted after a `GET /` to that port answers.
    """

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        """Try to take the lock. True if this process now holds it, False if another does.

        Non-blocking: the caller wants an answer, not a queue position.
        """
        # Opened "a+" so the file is created if absent and an existing holder's content is NOT
        # truncated — a "w" open would blank the port line before we knew whether we could lock,
        # leaving the running instance unreachable for the next launch.
        fh = open(self.path, "a+")
        try:
            _lock_exclusive(fh)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def write_state(self, port: int) -> None:
        """Record the port and PID for a later launch to find. Only valid while holding the lock."""
        assert self._fh is not None, "write_state called without the lock"
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(json.dumps({"port": port, "pid": os.getpid()}))
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def read_state(self) -> dict | None:
        """The holder's recorded state, or None if the file is absent, empty or unparseable.

        Unparseable is treated as absent rather than as an error: the file may be being written
        by the holder at this instant, and a launcher is not the place to be strict about it.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            state = json.loads(text)
        except ValueError:
            return None
        return state if isinstance(state, dict) else None

    def release(self) -> None:
        if self._fh is not None:
            try:
                _unlock(self._fh)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *exc) -> bool:
        self.release()
        return False


if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
    import msvcrt

    def _lock_exclusive(fh) -> None:
        # LK_NBLCK: non-blocking exclusive lock. Windows locks a byte RANGE rather than a file,
        # so a fixed one-byte region at offset 0 stands in for the whole file; every instance
        # agrees on that region, which is all the convention has to achieve.
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fh) -> None:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock_exclusive(fh) -> None:
        # EWOULDBLOCK/EAGAIN — "someone else holds it" — is the expected failure on a second
        # launch, and `acquire` treats any OSError the same way. Anything else (a filesystem
        # without flock support, say) surfaces as a refusal to start rather than as a silent
        # second server, which is the safer of the two readings.
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ── readiness ─────────────────────────────────────────────────────────────────


def server_answers(port: int, timeout: float = 1.0) -> bool:
    """Does something answer `GET /` on this port? Any HTTP status counts as an answer."""
    try:
        with urlopen(f"http://{BIND_HOST}:{port}/", timeout=timeout):
            return True
    except URLError:
        return False
    except OSError:
        return False
    except Exception:
        # An HTTPError is a subclass of URLError and already handled; this catches the odd
        # protocol-level exception. Something spoke HTTP badly, which still means it is there.
        return True


def wait_until_ready(port: int, deadline_s: float = _READY_TIMEOUT_S) -> bool:
    """Poll `GET /` until the server answers or the deadline passes.

    The UI must not be opened before this returns True: a browser (or, in phase 2, a webview)
    pointed at a socket nothing is listening on yet shows a connection-refused page and stays
    there — nothing retries it, so the user's first impression of the app is an error page.

    Same shape as the smoke test's startup wait: 0.2 s between attempts, ~20 s total.
    """
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if server_answers(port):
            return True
        time.sleep(0.2)
    return False


# ── assets ────────────────────────────────────────────────────────────────────


def check_assets(base_dir: Path | None = None) -> None:
    """Assert the bundled asset directories exist and are non-empty; raise naming what is missing.

    Cheap (four `iterdir`s) and worth it in a packaged build, where a mis-specified bundle entry
    otherwise produces a 500 on whichever page first needs the missing directory — far from the
    cause and impossible for a user to report usefully. In a source checkout it never fires.
    """
    base = base_dir if base_dir is not None else Path(__file__).resolve().parent
    missing = []
    for name in _ASSET_DIRS:
        path = base / name
        if not path.is_dir():
            missing.append(f"{path} (missing)")
        elif not any(path.iterdir()):
            missing.append(f"{path} (empty)")
    if missing:
        raise RuntimeError(
            "the application assets are incomplete — this build is missing:\n  "
            + "\n  ".join(missing)
        )


# ── the UI ────────────────────────────────────────────────────────────────────


class UiMode(enum.Enum):
    """How the UI is presented. One value per CLI flag, and the only three options there are.

    WINDOW is the default and the point of phase 2. BROWSER is phase 1's behaviour, kept both as
    an explicit `--browser` flag and as the automatic fallback when WINDOW cannot be produced —
    a machine without a webview renderer must still get a usable app rather than a traceback.
    NONE is for CI and for the packaged end-to-end test, which drive the server over HTTP.
    """

    WINDOW = "window"
    BROWSER = "browser"
    NONE = "none"


def _show_browser(url: str) -> None:
    """Open `url` in the user's default browser.

    `new=2` asks for a new tab in an existing window rather than a new window; browsers treat it
    as a hint, and there is nothing to do when they ignore it.

    Returns as soon as the browser has been asked — it does NOT wait for the tab to be closed,
    which is why `_show_ui` reports this mode as non-blocking. See `run`.
    """
    webbrowser.open(url, new=2)


def _show_window(url: str) -> None:
    """Open a native pywebview window on `url` and BLOCK until the user closes it.

    Two things about this function are structural rather than incidental:

    **It must run on the main thread.** `webview.start()` enters a GTK/Cocoa/WinForms event loop,
    and those toolkits require the process's main thread. That constraint is what pushed uvicorn
    onto a background thread in `run`; it is not a preference.

    **It raises rather than degrades.** pywebview does not bundle a renderer — it uses the OS one
    (WKWebView, WebView2, WebKit2GTK) — so on a Linux machine without the GTK/WebKit Python
    bindings `import webview` may succeed while `webview.start()` then raises `WebViewException`.
    Deciding what to do about that belongs to the caller, which has a browser to fall back on, so
    this function does not catch anything.

    `webview` is imported here rather than at module level so that a build or an environment
    without it can still run `--browser` and `--no-browser`, and so that importing this module
    stays cheap.
    """
    import webview

    webview.create_window(
        _WINDOW_TITLE,
        url,
        width=_WINDOW_SIZE[0],
        height=_WINDOW_SIZE[1],
        # The app is a data tool with tables and charts; a fixed-size window would clip them.
        resizable=True,
    )
    # Session persistence is configured on `start()`, NOT on `create_window()` — it is a
    # process-wide property of the webview profile, not a per-window one. Passing either of these
    # to `create_window()` raises TypeError (pywebview 6.2.1, and per the documented API).
    #
    # pywebview's default is a PRIVATE session, which discards localStorage on close. That would
    # be a data-loss bug here rather than a privacy nicety: `app/static/ha_fetch.js` keeps the
    # Home Assistant base URL and long-lived token in localStorage (`ha.base_url`, `ha.token`),
    # so a private session would make the user re-enter their token every launch.
    #
    # `storage_path` must be the app's data dir and never a path inside the bundle: under
    # PyInstaller onefile the bundle is a temp directory deleted on exit, and on macOS it is
    # read-only. pywebview's own default (`~/.pywebview`) would work but scatters app state
    # outside the directory the user can back up or delete as a unit.
    webview.start(
        private_mode=False,
        storage_path=str(Path(os.environ[config.ENV_DATA_DIR]) / "webview"),
    )


def _webview_exception_types() -> tuple[type[BaseException], ...]:
    """pywebview's own "cannot produce a window" exception class, as a tuple for `except`.

    Resolved at call time rather than imported at module level because pywebview may not be
    installed at all — the case `_show_ui` must survive. When it is missing, the ImportError from
    `import webview` is what `_show_ui` sees, and that is listed in the `except` clause directly.

    The tuple always contains `ImportError` and `RuntimeError`, and `WebViewException` too when
    pywebview is importable. pywebview 6.2.1 raises `WebViewException` for a missing renderer, but
    older versions and some backends surface the same condition as a bare `RuntimeError` ("You
    must have either QT or GTK … installed"), which `WebViewException` does NOT subclass. All of
    these are environment facts rather than programming errors, so all belong in the fallback.
    """
    try:
        from webview.errors import WebViewException
    except Exception:
        return (ImportError, RuntimeError)
    return (ImportError, RuntimeError, WebViewException)


def _show_fallback_dialog(url: str, reason: str) -> bool:
    """Show a native dialog carrying `url` when the webview could not open. True if it appeared.

    The problem this solves is specific to the packaged builds. When the native window fails, the
    launcher's only account of what happened is a line on stderr — and stderr is not somewhere a
    desktop user looks. On Windows it is a console window that `console=False` would remove
    entirely; on macOS a double-clicked bundle has no terminal attached at all. The user sees an
    application that started and then apparently did nothing.

    So the fallback gets a UI: the URL as SELECTABLE text (the whole point — a URL that cannot be
    copied is not much better than one printed where nobody looks), a copy button, and a button
    that opens the browser.

    **Tkinter and not the webview.** The window this replaces is the one that just failed, so
    pywebview is not available to draw its own error. Tkinter is in the standard library, needs
    no new dependency, and its toolkits (Win32/Cocoa/X11) are unrelated to the WebKit/WebView2
    renderers whose absence caused the failure — the two do not fail together.

    **It returns a boolean rather than raising**, because it is itself a fallback and every one of
    its failure modes is survivable. Tkinter is genuinely optional: it is absent from many Linux
    python packages (python3-tk is a separate apt package), and a headless machine has no display
    to draw on. The caller opens the browser regardless; this dialog only adds a way to reach the
    URL when that does not work either. A fallback that can break the thing it is backing up
    would be worse than no fallback.

    Note the deliberate asymmetry with `_show_window`, which raises on TypeError so that a bad
    call into pywebview stays loud. That reasoning does not carry over: this function runs only
    when the app is already degraded, and turning a cosmetic dialog bug into a crash at that
    moment would take away the browser fallback too.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        # No tkinter in this Python build. Common on Linux, where it ships separately.
        return False

    try:
        root = tk.Tk()
    except Exception:
        # No display, no window server, or a Tk that failed to initialise. `tk.TclError` is the
        # documented case, but Tk reports environment problems through several exception types
        # and this is a last-resort path — anything at all here means "no dialog".
        return False

    try:
        root.title(f"{_WINDOW_TITLE} — could not open a window")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=16)
        frame.grid(sticky="nsew")

        ttk.Label(
            frame,
            text="The application is running, but a native window could not be opened.",
            wraplength=460,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(
            frame,
            text=f"Reason: {reason}",
            wraplength=460,
            justify="left",
            foreground="#666666",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 12))

        ttk.Label(
            frame,
            text="Open this address in your browser:",
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        # `readonly` rather than `disabled`: both prevent editing, but a disabled Entry does not
        # allow selection either, which would defeat the purpose. The URL must be selectable so
        # it can be copied by hand when the button below is not what the user reaches for.
        url_var = tk.StringVar(value=url)
        url_entry = ttk.Entry(frame, textvariable=url_var, width=52, state="readonly")
        url_entry.grid(row=3, column=0, columnspan=2, sticky="we", pady=(4, 12))
        url_entry.focus_set()
        url_entry.selection_range(0, tk.END)

        status = tk.StringVar(value="")

        def copy_url() -> None:
            root.clipboard_clear()
            root.clipboard_append(url)
            # Tk's clipboard is owned by the process and is empty once it exits, on X11 in
            # particular. `update()` pushes the ownership out to the window server now, so the
            # copied text survives long enough to be pasted after this dialog closes.
            root.update()
            status.set("Copied.")

        def open_browser() -> None:
            _show_browser(url)
            status.set("Asked your browser to open the page.")

        ttk.Button(frame, text="Copy address", command=copy_url).grid(
            row=4, column=0, sticky="w"
        )
        ttk.Button(frame, text="Open in browser", command=open_browser).grid(
            row=4, column=1, sticky="e"
        )

        ttk.Label(frame, textvariable=status, foreground="#666666").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        ttk.Label(
            frame,
            text="Closing this window stops the application.",
            wraplength=460,
            justify="left",
            foreground="#666666",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 0))

        root.mainloop()
    except Exception:
        # Same reasoning as the constructor above: this is the degraded path already.
        return False
    finally:
        try:
            root.destroy()
        except Exception:
            # Already torn down by mainloop's exit; nothing to do.
            pass

    return True


def _show_ui(url: str, mode: UiMode) -> bool:
    """Show the app's UI at `url`. Returns True if the call OWNED the session, False otherwise.

    "Owned the session" means: this call blocked for as long as the user was using the app, so its
    return is the user quitting and the server should now be shut down. Only a successfully
    started native window does that. A browser tab does not — `webbrowser.open` returns in
    milliseconds while the tab lives on — and neither does `UiMode.NONE`, which shows nothing.

    That single boolean is what keeps `run` from having three shutdown policies. Getting it wrong
    in the fallback direction is the subtle case: if a WINDOW that fell back to the browser still
    reported True, the launcher would kill the server immediately after opening the tab.

    **The fallback is deliberately narrow.** It catches the exceptions that mean "this machine
    cannot show a native window" and nothing else. An earlier version caught `Exception`, which
    also caught our own bad call into pywebview and printed it as an environment limitation — the
    user saw "native window unavailable" for what was a plain coding error, and no test noticed
    because the mocks accepted whatever we passed. Anything not in that narrow set now propagates.
    """
    if mode is UiMode.NONE:
        return False
    if mode is UiMode.BROWSER:
        _show_browser(url)
        return False

    try:
        _show_window(url)
    except TypeError:
        # NOT swallowed, deliberately. A TypeError out of `_show_window` is our own call being
        # wrong — a bad keyword, a renamed argument after a pywebview upgrade — and it is not
        # something the user can fix by installing a package. This clause exists because that is
        # exactly what happened once: `private_mode`/`storage_path` were passed to
        # `create_window()` instead of `start()`, the blanket `except Exception` below turned the
        # resulting TypeError into "native window unavailable", and the bug shipped looking like
        # the expected no-renderer fallback. Letting it propagate makes a coding error loud.
        raise
    except _webview_exception_types() as exc:
        # The genuine environment cases, and only those: ImportError (no pywebview at all — a
        # build that did not collect it, or a stripped environment) and pywebview's own
        # WebViewException (pywebview present, no renderer — the common Linux case, where
        # gir1.2-webkit2-4.1 is absent, or is installed system-wide but invisible to the venv).
        # From the user's point of view these are one situation: the native window is not
        # available on this machine and the app should still open.
        #
        # Note this is `Exception`-descended and not `BaseException`: a KeyboardInterrupt raised
        # while the GUI loop is running is the user quitting, and re-opening the app in a browser
        # as a response to Ctrl-C would be wrong. It propagates, as does every other unexpected
        # error, which is now the default rather than the exception.
        reason = f"{type(exc).__name__}: {exc}"
        print(
            f"native window unavailable ({reason}); opening in your browser instead",
            file=sys.stderr,
        )
        # The browser is opened FIRST, and unconditionally. The dialog is an addition to the
        # fallback, not a replacement for it: if it were opened first and the user closed it
        # without pressing anything, they would be left with a running server and no page. This
        # ordering means the worst case is a browser tab the user did not need.
        _show_browser(url)

        # If the dialog appeared, it blocked until the user closed it, and that close is the
        # user quitting — the same signal `_show_window` returning normally carries. Reporting
        # True hands `run` its shutdown, exactly as a native window would.
        #
        # If it could not appear (no tkinter, no display), this is the pre-existing behaviour:
        # the browser tab is open, nothing is blocking, and False keeps the server running for
        # it. See the docstring above on why that distinction is a boolean rather than a raise.
        return _show_fallback_dialog(url, reason)
    return True


# ── the ASGI app ──────────────────────────────────────────────────────────────


def _load_asgi_app():
    """Import and return `app.main:app`. **Call only after `resolve_data_dir()`.**

    This import is inside a function, and that is not a style choice. Importing `app.main` pulls
    in the whole persistence layer and runs its module-level work — the lifespan's migrations and
    every `config.data_dir()` call resolve `BATTERY_SIM_DATA_DIR` as they find it. So the
    directory the installation uses is decided by whatever that variable holds around the moment
    this module is first imported, and a module-level `from app.main import app` at the top of
    this file would make that moment "before the launcher has run", i.e. the source-run default.

    `app/main.py` used to make this sharper still by running `CONFIG = config.load()` at module
    level, which WROTE a generated `installation_id` into the directory on import. That line is
    gone with the feature-interest telemetry (app/config.py), so the import no longer writes
    anything by itself — but it still binds paths, and the ordering requirement stands.

    The symptom is invisible in development, where the default happens to be right. In a packaged
    build it is data written INSIDE the app bundle: read-only on macOS, and under PyInstaller
    onefile a temp directory deleted when the process exits, taking every workspace with it. It
    would first appear on a clean machine, after shipping.

    `tests/conftest.py::_isolate_data_dir` documents the same hazard from the test side and works
    around it the same way, for the same reason.
    """
    from app.main import app as asgi_app

    return asgi_app


# ── the server thread ─────────────────────────────────────────────────────────


class _ServerThread:
    """uvicorn on a background daemon thread, with a cooperative stop.

    Phase 1 ran `server.run()` on the main thread. It cannot stay there: `webview.start()` needs
    the main thread for the GUI toolkit's event loop (see `_show_window`), and only one of the two
    can have it. The server is the one that can move, because uvicorn's loop has no such
    requirement and it already exposes a way to be stopped from another thread.

    **`should_exit`, not `daemon=True`, is the shutdown mechanism.** uvicorn's serve loop checks
    that flag on each tick and, when it is set, runs its ordinary shutdown: stop accepting, let
    in-flight requests finish, fire the ASGI lifespan shutdown event. Relying on the daemon flag
    instead would end the process with the thread wherever it happened to be — mid-request, with
    the lifespan shutdown never run. `daemon=True` is kept only as a backstop for a `stop()` whose
    wait times out, so a wedged request cannot leave a closed window's process alive forever.

    **Completion is reported by `_finished`, never by `Thread.is_alive()` or `Thread.join()`.**
    That is not defensive style; those two are actively unreliable on the path this class exists
    to serve. When a signal interrupts a `Thread.join()`, CPython's `_wait_for_tstate_lock`
    catches the resulting exception and calls `self._stop()`, permanently marking the Thread
    object as stopped even though the OS thread is still running (bpo-45274). Every later
    `join(timeout=…)` then returns in about a millisecond and `is_alive()` answers False. So a
    `stop()` that consulted either would report a clean shutdown, immediately, precisely when
    the user pressed Ctrl-C and uvicorn had not yet run the ASGI lifespan shutdown.

    An `Event` set in the target's `finally` cannot be corrupted that way: nothing but the
    thread itself ever sets it, and it is set only once `server.run()` has actually returned.
    """

    def __init__(self, server):
        self._server = server
        self._finished = threading.Event()
        """Set by the thread itself, in a `finally`, once `server.run()` has returned.

        The ONLY trustworthy answer to "has the server finished shutting down". See the class
        docstring for why `Thread.is_alive()` is not one.
        """
        self._thread = threading.Thread(
            target=self._run, name="battery-sim-uvicorn", daemon=True
        )

    def _run(self) -> None:
        try:
            self._server.run()
        finally:
            # `finally`, so a server that raises still reports completion. A crashed server has
            # finished as surely as a clean one has, and `stop()` waiting the full timeout for a
            # thread that is already gone would be a ten-second hang on the way out.
            self._finished.set()

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = _SHUTDOWN_TIMEOUT_S) -> bool:
        """Ask the server to exit and wait for it. True only if it really finished in `timeout`.

        The return value comes from `_finished`, so it stays truthful after an interrupted
        `join()` (see the class docstring). A False here is what lets `run` warn that the server
        did not stop, rather than exiting silently on a shutdown that never completed.
        """
        self._server.should_exit = True
        return self._finished.wait(timeout=timeout)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the server stops on its own — Ctrl-C, SIGTERM, or a crash.

        `Event.wait()` rather than `Thread.join()` for the reason in the class docstring, and
        also because it leaves the Thread object uncorrupted for the `stop()` that follows a
        `KeyboardInterrupt`: `join()` would have poisoned it on the way out.
        """
        return self._finished.wait(timeout=timeout)

    def is_alive(self) -> bool:
        """Whether the server is still running, by the `_finished` signal rather than the Thread.

        Deliberately NOT `self._thread.is_alive()`, and not that ANDed with anything either: a
        Thread object corrupted by an interrupted join reports False, so including it as a
        conjunct would carry the same lie straight through. `_finished` is the whole answer —
        it is set once, by the thread, after `server.run()` has returned.
        """
        return not self._finished.is_set()


# ── the launcher ──────────────────────────────────────────────────────────────


def run(port: int | None = None, ui: UiMode = UiMode.WINDOW) -> int:
    """Start the server, wait for it, show the UI, then shut down. Returns a process exit code.

    Returns 0 without starting anything when another instance already holds the lock and answers
    on its recorded port — the second launch has done its job by bringing the running instance's
    window forward.

    `host=BIND_HOST` is passed as a constant with no way to override it. That is deliberate and
    is a security property rather than a missing feature; the reasoning is on `BIND_HOST`.

    The main thread's job here is: poll, show the UI, and decide when to stop. Whether showing
    the UI blocked (a native window) or returned at once (a browser tab, or nothing) is what
    decides between "shut down now" and "wait for the server to be interrupted" — see `_show_ui`.
    """
    data_dir = resolve_data_dir()

    # Immediately after the data directory is known and before anything is printed, because the
    # log's path depends on that directory. `main()` has already guaranteed the streams are not
    # None; this replaces them with something that persists. Everything below reaches the file.
    #
    # Deliberately NOT at the top of `main()`: argument parsing runs before the data directory is
    # resolved, so `--help` and usage errors still go to the terminal only. Those are
    # terminal-invoked paths, where a console exists by definition.
    start_session_log(data_dir)

    # AFTER the log exists, so the one line this prints when it cannot use the system trust store
    # is captured in the file a bug report attaches rather than lost to a closed console. Nothing
    # above makes an HTTPS request, so nothing is verified before this runs. `app.main` installs
    # it too, at import; whichever gets there first wins and the other is a no-op.
    net_trust.install_system_trust()

    lock = SingleInstance(data_dir / _LOCK_FILENAME)
    if not lock.acquire():
        # Someone holds the lock. If they are serving, hand the user over to them and stop.
        state = lock.read_state() or {}
        running_port = state.get("port")
        if isinstance(running_port, int) and server_answers(running_port):
            url = f"http://{BIND_HOST}:{running_port}/"
            print(f"Home Battery Simulator is already running at {url}", file=sys.stderr)
            # Shown from THIS process, pointed at the other one's port. A second window on the
            # same server is not the corruption case the lock guards against — that is a second
            # SQLite writer — so it is allowed, and it is what a user double-clicking the icon
            # again is asking for.
            _show_ui(url, ui)
            return 0
        # Locked but not answering: a start still in progress, or an instance wedged between
        # taking the lock and binding. Starting a second server against the same SQLite file is
        # the outcome the lock exists to prevent, so refuse rather than race it.
        print(
            "Another Home Battery Simulator process holds the lock but is not answering.\n"
            f"If it is stuck, quit it and try again ({lock.path}).",
            file=sys.stderr,
        )
        return 1

    with lock:
        check_assets()

        chosen = port if port is not None else choose_port()
        lock.write_state(chosen)

        # Imported here, after the data dir is settled and never before. See `_load_asgi_app`.
        asgi_app = _load_asgi_app()

        import uvicorn

        server = uvicorn.Server(
            uvicorn.Config(
                # The imported ASGI OBJECT, not the "app.main:app" import string. A frozen bundle
                # makes no promise about import-path resolution from inside uvicorn's own
                # importer, and the object is already in hand.
                asgi_app,
                host=BIND_HOST,
                port=chosen,
                # Every protocol implementation is PINNED rather than left at "auto". uvicorn's
                # "auto" does a runtime probe — try to import the fast one, fall back — which
                # PyInstaller's static analysis cannot see, so the probed module is simply not
                # collected into the bundle.
                #
                # The WebSocket implementation is the one that matters most. The ingest route
                # `WS /w/{id}/data/ingest/ws` (app/main.py) is the app's only WebSocket, and with
                # "auto" a bundle that failed to collect the `websockets` package falls back to
                # "no WebSocket support" — so that single route breaks in the packaged build ONLY,
                # while every test and every other page stays green. Naming it here makes the
                # dependency visible to the packager and the failure loud rather than silent.
                #
                # `websockets-sansio` rather than the older `websockets`: both are backed by the
                # same `websockets` package (already in uv.lock), and uvicorn 0.51 deprecates the
                # latter — running it emits a UvicornDeprecationWarning on every start and it
                # becomes an alias for this one in a future release. Pinning the name that is not
                # scheduled to change is what keeps the pin meaningful.
                ws="websockets-sansio",
                # Same reasoning, plus a size benefit: pinning these two drops the compiled
                # `httptools` and `uvloop` from a future bundle (uv.lock already restricts uvloop
                # to non-Windows). The performance difference is irrelevant for one user on one
                # machine driving a browser.
                http="h11",
                loop="asyncio",
                reload=False,
                log_level="warning",
                access_log=False,
            )
        )

        url = f"http://{BIND_HOST}:{chosen}/"
        thread = _ServerThread(server)
        thread.start()

        # The poll is kept exactly where phase 1 had it, and for the same reason: a webview or a
        # browser pointed at a socket nothing is listening on yet shows a connection-refused page
        # and never retries. It is now on the main thread because the server is not.
        if not wait_until_ready(chosen):
            print("the server did not become ready in time", file=sys.stderr)
            thread.stop()
            return 1

        print(f"Home Battery Simulator on {url}", file=sys.stderr)

        blocked = _show_ui(url, ui)

        if blocked:
            # The window is closed; the user is done. Nothing else will stop the server.
            _stop_or_warn(thread)
        else:
            # A browser tab or no UI at all: the session lasts as long as the process does, and
            # the process ends on Ctrl-C or SIGTERM. Wait here rather than returning, which would
            # take the server thread down with the interpreter.
            try:
                thread.wait()
            except KeyboardInterrupt:
                # uvicorn installs its own SIGINT handler and is already stopping; give it the
                # same bounded wait a window close gets, so the ASGI shutdown can run.
                #
                # `thread.wait()` above is `Event.wait`, NOT `Thread.join` — which matters here
                # specifically. An interrupted `Thread.join` marks the Thread object stopped
                # (see `_ServerThread`), after which this `_stop_or_warn` would return True in
                # about a millisecond and report a clean shutdown that had not happened.
                _stop_or_warn(thread)

    return 0


def _stop_or_warn(thread: "_ServerThread") -> None:
    """Stop the server, and say so on stderr if it did not actually finish in time.

    Both shutdown paths — a closed window and a Ctrl-C — go through here, so the warning cannot
    be present on one and missing on the other.
    """
    if not thread.stop():
        print(
            f"the server did not stop within {_SHUTDOWN_TIMEOUT_S:.0f}s; exiting anyway",
            file=sys.stderr,
        )


def _ensure_std_streams() -> None:
    """Guarantee `sys.stdout` and `sys.stderr` are writable objects, not None.

    A windowed frozen build can start with no standard streams at all. PyInstaller documents this
    for Windows specifically — since aligning with `pythonw.exe`, it leaves both as `None` rather
    than substituting a null writer — and the failure it produces is nasty out of proportion to
    its cause: every `print(..., file=sys.stderr)` becomes `AttributeError: 'NoneType' object has
    no attribute 'write'`, so the launcher crashes at precisely the six places where it was
    trying to report something.

    The macOS `.app` this project builds sets `console=False` and is EXPECTED not to need this —
    a bundle inherits stderr from launchd and it lands in the unified log, which is why the
    console can be dropped there without losing the messages. This guard is insurance against
    that expectation being wrong on some macOS version, and against a future Windows build
    turning off its console. It costs two comparisons at startup.

    `devnull` rather than a buffer that accumulates: if there is genuinely nowhere for this
    output to go, discarding it is the honest outcome, and holding it in memory for a process
    that may run for hours would be worse.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - lives as long as the process
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115 - lives as long as the process


class _Tee:
    """Write to two streams at once. Used only when a TTY is attached.

    A packaged app started from a file manager has no terminal, and the log file is the only
    place its output can go. A developer running the same binary from a shell expects to see that
    output where they typed the command. Teeing satisfies both without a mode flag: the file
    always gets everything, the terminal additionally gets it when there is a terminal.

    Every method swallows errors from the SECONDARY stream only. If the log file goes away —
    a full disk, a removed USB volume, a user deleting the directory mid-run — that must not take
    the terminal output with it, nor raise inside a `print()` somewhere unrelated. The primary
    stream is left to fail normally, because if the console itself is broken the process has
    bigger problems than logging.
    """

    def __init__(self, primary, secondary) -> None:
        self._primary = primary
        self._secondary = secondary

    def write(self, data: str) -> int:
        n = self._primary.write(data)
        try:
            self._secondary.write(data)
        except Exception:
            pass
        return n

    def flush(self) -> None:
        self._primary.flush()
        try:
            self._secondary.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        # Reports the PRIMARY stream's answer. Callers ask this to decide whether to colourise or
        # to prompt; the presence of a log file behind the scenes does not change that answer.
        try:
            return bool(self._primary.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        # Delegated so that anything wanting a real descriptor — subprocess redirection, uvicorn's
        # logging setup — gets the terminal's, not an error. A tee has no descriptor of its own.
        return self._primary.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._primary, "encoding", "utf-8")


_LOG_DIRNAME = "logs"
"""Subdirectory of the data directory holding session logs. Also the prune scope — see `_prune`."""

_LOG_RETENTION_DAYS = 90
"""Three months, chosen by the user. Pruning is by mtime, not by file count."""


def _prune_old_logs(log_dir: Path, retention_days: int = _LOG_RETENTION_DAYS) -> None:
    """Delete `session-*.log` files in `log_dir` older than `retention_days`.

    Deletion is the only destructive thing this module does, so the scope is deliberately narrow
    on three axes at once: one directory (never recursive), one filename pattern, and one file
    type. A data directory holds the user's database and their workspaces; a glob that reached
    those would be a data-loss bug in a debugging feature.

    Age is mtime, not the timestamp in the filename. The two normally agree, but mtime is what the
    filesystem actually knows — a clock change or a copied file can make the name lie, and the
    consequence of trusting the name would be deleting something newer than it claims to be.

    Silent on every error. Pruning is housekeeping: a file that cannot be deleted (locked on
    Windows by another instance still writing it) is not a reason to fail a launch, and the next
    run tries again.
    """
    cutoff = time.time() - retention_days * 86400
    try:
        entries = list(log_dir.glob("session-*.log"))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            # Locked, already gone, or not ours to remove. Housekeeping is best-effort.
            continue


def start_session_log(data_dir: Path) -> Path | None:
    """Redirect `sys.stdout`/`sys.stderr` into a timestamped file under `<data_dir>/logs/`.

    Returns the log's path, or None if logging could not be started.

    **Why this exists.** With `console=False` on every platform (see packaging/battery-sim.spec),
    a double-clicked app has nowhere to print. The launcher's messages — the URL it is serving,
    the already-running notice, the reason the window fell back to a browser — are exactly what a
    bug report needs, and without this they are discarded. docs/en/troubleshooting.md tells users
    where to find the file this creates.

    **One file per launch, interleaved.** stdout and stderr share a handle, so their relative
    order is preserved; splitting them would make "which happened first" unanswerable, which is
    usually the question. Line-buffered, so a crash does not lose the lines leading up to it.

    **Teeing when a TTY is attached** keeps `battery-sim` from a shell behaving as it always has.
    The check is on the stream this function is about to replace, before replacement.

    **It never raises.** Every failure — unwritable directory, full disk, a read-only volume —
    leaves the existing streams untouched and returns None. A launcher that refuses to start
    because it could not open a log file would be a worse product than one with no log at all,
    and this runs on the path where the user has already double-clicked something.
    """
    try:
        log_dir = data_dir / _LOG_DIRNAME
        log_dir.mkdir(parents=True, exist_ok=True)

        # Local time, not UTC: the user reading this filename to find "the run that just failed"
        # is comparing it against their own clock. Colons are avoided — illegal in Windows
        # filenames — which is why this is not isoformat().
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = log_dir / f"session-{stamp}.log"

        # buffering=1 is line buffering, valid because the handle is opened in text mode. utf-8
        # explicitly: the default is locale-dependent, and a Windows machine on a legacy code page
        # would otherwise raise UnicodeEncodeError on a path or an error message containing
        # non-ASCII — which is a real case here, since Dutch is a supported language.
        handle = open(path, "a", buffering=1, encoding="utf-8", errors="replace")  # noqa: SIM115
    except OSError:
        return None

    _prune_old_logs(log_dir)

    header = (
        f"=== Home Battery Simulator — session started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
        f"platform: {sys.platform}  frozen: {getattr(sys, 'frozen', False)}\n"
        f"data directory: {data_dir}\n"
    )
    try:
        handle.write(header)
    except OSError:
        return None

    # Checked BEFORE replacing the streams, and on the streams being replaced. `_ensure_std_streams`
    # has already run, so these are never None here — but they may be the devnull writers it
    # substituted, which correctly report isatty() False.
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            attached = bool(stream.isatty())
        except Exception:
            # A substituted or exotic stream that cannot answer. Treat as no terminal: the file
            # gets the output either way, and guessing True would mean writing to something that
            # may not accept it.
            attached = False
        setattr(sys, name, _Tee(stream, handle) if attached else handle)

    return path


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m app`, for the `battery-sim` script, and for the frozen build."""
    # FIRST statement of the entry point, before argument parsing and before any import that
    # might spawn. A no-op today — nothing in the codebase uses multiprocessing — but
    # docs/specs/08-architecture.md §5.3 specifies a `ProcessPoolExecutor` with one worker per
    # workspace for the simulation runs. On Windows and on macOS's spawn start method, a frozen
    # child process re-executes the bundle's entry point; without `freeze_support()` that child
    # runs `main()` again, launches its own server and spawns its own children. Adding it now
    # costs nothing and removes a fork bomb that would otherwise appear the day §5.3 lands, in
    # the packaged build only.
    multiprocessing.freeze_support()
    _ensure_std_streams()

    parser = argparse.ArgumentParser(
        prog="battery-sim",
        description="Run the Home Battery Simulator on this machine.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port to serve on (default: {DEFAULT_PORT}, or a free port if that one is taken)",
    )
    # Mutually exclusive, because "--browser --no-browser" has no sensible reading and argparse
    # would otherwise silently let the last flag win.
    ui_group = parser.add_mutually_exclusive_group()
    ui_group.add_argument(
        "--browser",
        action="store_true",
        # The escape hatch for the native window: a user whose machine renders the app badly
        # under WebKit2GTK, or who simply prefers their own browser's devtools and extensions.
        help="open the user interface in your default browser instead of a native window",
    )
    ui_group.add_argument(
        "--no-browser",
        action="store_true",
        # Two callers need this: CI, and the packaged end-to-end test, both of which drive the
        # server over HTTP and would otherwise open a window on the build machine.
        help="start the server without opening any user interface",
    )
    args = parser.parse_args(argv)

    if args.no_browser:
        ui = UiMode.NONE
    elif args.browser:
        ui = UiMode.BROWSER
    else:
        ui = UiMode.WINDOW

    return run(port=args.port, ui=ui)


if __name__ == "__main__":
    sys.exit(main())
