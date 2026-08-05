"""Unit tests for the desktop launcher (app/desktop.py).

Pure-Python, no browser and — with one deliberate exception — no server: what is under test here
is the launcher's decisions, not the app it starts. Five properties are load-bearing enough that
a regression in any of them would ship silently, so each gets its own test:

  * **the per-user data directory**, on all three platforms. All three are exercised from Linux
    by monkeypatching `sys.platform` and the relevant environment variables, because the failure
    mode (data written into a roaming profile, or into the app bundle) is a per-OS one that no
    single CI machine would otherwise see.
  * **the ordering hazard**: `BATTERY_SIM_DATA_DIR` must be set BEFORE `app.main` is imported,
    since importing that module runs `config.load()` and writes an installation_id into whatever
    directory is resolved at that instant. `tests/conftest.py::_isolate_data_dir` documents the
    same hazard; `app.desktop._load_asgi_app` is what avoids it, and a module-level import
    creeping back into `app/desktop.py` is exactly what is asserted against here.
  * **the bind host**, which is a security property (`app/csrf.py`'s threat model assumes the
    loopback), so it is asserted to be 127.0.0.1 and to be absent as a configurable.
  * **the single-instance lock**, held and taken over, since two processes against one SQLite
    file is the corruption case the lock exists to prevent.
  * **the version**, cross-checked against pyproject.toml so the two cannot drift.

Phase 2 adds a second group, around the native window and the threading inversion it forced:

  * **UI-mode dispatch** — the three CLI flags, and what each mode actually does. The default
    being the native WINDOW is the phase-2 behaviour change and is pinned here.
  * **the fallback** when pywebview is absent or cannot produce a window. This is not a
    hypothetical: it is the path taken on this dev machine, where the venv cannot see the system
    `gi` bindings, so `webview.start()` raises. Tested for both the import failure and the
    start failure, and for reporting non-blocking so `run` does not kill the server.
  * **the shutdown handshake** — the server now runs on a background thread (pywebview owns the
    main one) and must be stopped by `should_exit` plus a bounded join, not by the daemon flag.

**No test here opens a real window or a real browser.** `webview` is faked into `sys.modules`
and `webbrowser.open` is monkeypatched; the machine running the suite has no display, and on one
that does, a suite that pops up windows is unusable.

    uv run pytest tests/test_desktop.py
"""

import inspect
import json
import os
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest

from app import config, desktop

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── per-user data directory ──────────────────────────────────────────────────


def test_macos_data_dir_is_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config.user_data_dir() == tmp_path / "Library" / "Application Support" / "BatterySim"


def test_windows_data_dir_uses_localappdata_not_appdata(monkeypatch, tmp_path):
    """LOCALAPPDATA, because a roaming profile must not carry a SQLite file or .npz series.

    APPDATA is set to a different directory here on purpose: picking it would satisfy a test that
    only checked "somewhere under the user's profile", and it is the mistake this pins against.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    resolved = config.user_data_dir()
    assert resolved == tmp_path / "Local" / "BatterySim" / "data"
    assert "Roaming" not in str(resolved)


def test_windows_data_dir_falls_back_when_localappdata_is_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config.user_data_dir() == tmp_path / "AppData" / "Local" / "BatterySim" / "data"


def test_linux_data_dir_respects_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.user_data_dir() == tmp_path / "xdg" / "battery-sim"


def test_linux_data_dir_falls_back_to_local_share(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config.user_data_dir() == tmp_path / ".local" / "share" / "battery-sim"


def test_user_data_dir_has_no_side_effects(monkeypatch, tmp_path):
    """It must not CREATE anything: `data_dir()` owns creation, and the frozen guard calls this
    helper to decide a path before knowing whether it will be used."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert not config.user_data_dir().exists()


# ── data_dir()'s defaults, including the frozen guard ────────────────────────


def test_data_dir_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path / "explicit"))
    assert config.data_dir() == tmp_path / "explicit"


def test_source_run_still_defaults_to_the_repo_data_dir(monkeypatch):
    """Unfrozen and with no env var, `./data` beside the repo — developers' data does not move."""
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert config.data_dir() == REPO_ROOT / "data"


def test_frozen_run_falls_back_to_the_per_user_dir(monkeypatch, tmp_path):
    """Frozen, `_REPO_ROOT / "data"` points inside the bundle — read-only, or a temp dir deleted
    on exit. The per-user path is the only defensible answer."""
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    resolved = config.data_dir()
    assert resolved == tmp_path / "xdg" / "battery-sim"
    assert resolved.is_dir()  # data_dir(), unlike user_data_dir(), does create it


# ── resolve_data_dir(): setdefault semantics ─────────────────────────────────


def test_resolve_data_dir_sets_the_env_var_for_the_app_to_read(monkeypatch, tmp_path):
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    resolved = desktop.resolve_data_dir()

    assert resolved == tmp_path / "xdg" / "battery-sim"
    assert os.environ[config.ENV_DATA_DIR] == str(resolved)
    assert resolved.is_dir()


def test_resolve_data_dir_keeps_a_preexisting_value(monkeypatch, tmp_path):
    """`setdefault`, not assignment: an operator or a test that pointed the variable somewhere
    keeps that choice — the same rule `tests/conftest.py::_isolate_data_dir` follows."""
    chosen = tmp_path / "chosen-by-the-user"
    monkeypatch.setenv(config.ENV_DATA_DIR, str(chosen))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert desktop.resolve_data_dir() == chosen
    assert os.environ[config.ENV_DATA_DIR] == str(chosen)
    assert not (tmp_path / "xdg").exists()  # the per-user path was not touched


# ── the import-ordering hazard ───────────────────────────────────────────────


def test_desktop_does_not_import_app_main_at_module_level():
    """The property `_load_asgi_app` exists to preserve, asserted where it can be seen.

    Importing `app.main` runs `CONFIG = config.load()`, which WRITES an installation_id into
    whatever data directory is resolved at that moment. A module-level `from app.main import app`
    in `app/desktop.py` would fix that directory before `resolve_data_dir()` ever ran — invisible
    in a source checkout, and in a packaged build it puts the user's data inside the app bundle.

    Checked two ways, because either alone is weak: the source has no top-level import of it, and
    importing `app.desktop` in a fresh interpreter leaves `app.main` absent from `sys.modules`.
    """
    source = (REPO_ROOT / "app" / "desktop.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith(("import ", "from ")):
            assert "app.main" not in line, f"module-level import of app.main: {line!r}"

    probe = (
        "import sys; import app.desktop; "
        "sys.exit(1 if 'app.main' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"importing app.desktop pulled in app.main: {result.stdout}{result.stderr}"
    )


# ── port selection ───────────────────────────────────────────────────────────


def test_choose_port_returns_a_bindable_port():
    port = desktop.choose_port()
    assert isinstance(port, int) and port > 0
    assert desktop._is_bindable(port)


def test_choose_port_prefers_the_default_when_it_is_free(monkeypatch):
    monkeypatch.setattr(desktop, "_is_bindable", lambda p: True)
    assert desktop.choose_port() == desktop.DEFAULT_PORT


def test_choose_port_falls_back_when_the_preferred_port_is_taken():
    """A real listener on the preferred port, so this exercises the bind rather than a stub."""
    import socket

    with socket.socket() as taken:
        taken.bind((desktop.BIND_HOST, 0))
        taken.listen(1)
        occupied = taken.getsockname()[1]

        chosen = desktop.choose_port(occupied)

        assert chosen != occupied
        assert desktop._is_bindable(chosen)


def test_an_explicit_port_is_honoured_by_the_argument_parser(monkeypatch):
    """`--port N` reaches `run()` verbatim — no free-port probe, no silent substitution."""
    seen = {}

    def fake_run(port=None, ui=desktop.UiMode.WINDOW):
        seen.update(port=port, ui=ui)
        return 0

    monkeypatch.setattr(desktop, "run", fake_run)
    assert desktop.main(["--port", "8137", "--no-browser"]) == 0
    assert seen == {"port": 8137, "ui": desktop.UiMode.NONE}


# ── the UI mode: flag parsing and dispatch ───────────────────────────────────


@pytest.mark.parametrize(
    "argv, expected",
    [
        ([], desktop.UiMode.WINDOW),
        (["--browser"], desktop.UiMode.BROWSER),
        (["--no-browser"], desktop.UiMode.NONE),
    ],
)
def test_the_flags_select_the_ui_mode(monkeypatch, argv, expected):
    """The native window is the DEFAULT — the phase-2 behaviour change, pinned here."""
    seen = {}
    monkeypatch.setattr(desktop, "run", lambda **kw: seen.update(kw) or 0)
    assert desktop.main(argv) == 0
    assert seen == {"port": None, "ui": expected}


def test_browser_and_no_browser_are_mutually_exclusive():
    """Not a style point: with both accepted, the last one would silently win and a CI job that
    passed `--no-browser` after a configured `--browser` would open a window on the runner."""
    with pytest.raises(SystemExit):
        desktop.main(["--browser", "--no-browser"])


def test_the_cli_documents_all_three_modes():
    result = subprocess.run(
        [sys.executable, "-m", "app", "--help"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--browser" in result.stdout and "--no-browser" in result.stdout


# ── the UI mode: what each one actually does ─────────────────────────────────


@pytest.fixture
def fake_webview(monkeypatch):
    """A stand-in `webview` module in `sys.modules`, so `_show_window` imports THIS.

    No test in this suite may open a real window: the machine running them has no display, and
    on one that does, a suite that pops up windows is unusable. `_show_window` imports `webview`
    inside the function precisely so it can be swapped here.
    """

    class FakeWebview:
        def __init__(self):
            self.windows = []
            self.start_kwargs = []
            self.started = 0
            self.create_raises = None
            self.start_raises = None

        def create_window(self, title, url, **kwargs):
            if self.create_raises is not None:
                raise self.create_raises
            self.windows.append((title, url, kwargs))
            return object()

        def start(self, *args, **kwargs):
            self.started += 1
            self.start_kwargs.append(kwargs)
            if self.start_raises is not None:
                raise self.start_raises

    fake = FakeWebview()
    monkeypatch.setitem(sys.modules, "webview", fake)
    return fake


def test_window_mode_opens_a_window_and_reports_that_it_blocked(monkeypatch, fake_webview, tmp_path):
    """`_show_ui` returning True is what tells `run` the user has quit — see `run`'s shutdown."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    monkeypatch.setattr(desktop.webbrowser, "open", _never_called)

    assert desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW) is True

    assert fake_webview.started == 1
    (title, url, kwargs) = fake_webview.windows[0]
    assert url == "http://127.0.0.1:8137/"
    assert title


def test_the_session_is_not_private_and_stores_under_the_data_dir(
    monkeypatch, fake_webview, tmp_path
):
    """pywebview defaults to private_mode=True, which discards localStorage on close.

    `app/static/ha_fetch.js` keeps the Home Assistant base URL and long-lived token there, so the
    default would make the user re-enter their token on every launch. Asserted because it is a
    silent, per-launch data loss that no other test would notice.

    Both settings live on `start()`, not on `create_window()` — see
    `test_our_pywebview_arguments_are_accepted_by_the_installed_pywebview`, which is what pins
    that down against the real library rather than against this fake.
    """
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW)

    kwargs = fake_webview.start_kwargs[0]
    assert kwargs["private_mode"] is False
    # Under the data dir, which the launcher owns — never inside the bundle, which is read-only on
    # macOS and a temp directory deleted on exit under PyInstaller onefile.
    assert Path(kwargs["storage_path"]) == tmp_path / "webview"


def test_our_pywebview_arguments_are_accepted_by_the_installed_pywebview(monkeypatch, tmp_path):
    """Bind the arguments we actually pass against the REAL pywebview signatures.

    This is the test that was missing when `private_mode`/`storage_path` were passed to
    `create_window()` instead of `start()`. Every other test here runs against `fake_webview`,
    whose `**kwargs` accepts anything, so they all passed while the real call raised TypeError —
    which the then-blanket `except Exception` printed as "native window unavailable".

    `Signature.bind` reproduces exactly the check CPython performs when calling the function, so a
    misplaced or renamed keyword fails here. It needs no display and no window: nothing is called,
    only bound. If pywebview is genuinely absent the check is not possible and is skipped rather
    than faked, since a fake signature would be the same mistake again.
    """
    webview = pytest.importorskip("webview")

    recorded = {}

    class RecordingWebview:
        def create_window(self, *args, **kwargs):
            recorded["create_window"] = (args, kwargs)

        def start(self, *args, **kwargs):
            recorded["start"] = (args, kwargs)

    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    monkeypatch.setitem(sys.modules, "webview", RecordingWebview())
    desktop._show_window("http://127.0.0.1:8137/")

    assert set(recorded) == {"create_window", "start"}
    for name in ("create_window", "start"):
        args, kwargs = recorded[name]
        signature = inspect.signature(getattr(webview, name))
        # Raises TypeError on an unexpected or misplaced keyword — the real failure, surfaced as
        # a test failure naming the argument instead of as a silent browser fallback at runtime.
        signature.bind(*args, **kwargs)


def test_browser_mode_opens_the_browser_and_reports_that_it_did_not_block(monkeypatch, fake_webview):
    """`webbrowser.open` returns in milliseconds while the tab lives on, so reporting True here
    would make `run` shut the server down immediately after opening it."""
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, **kw: opened.append(url))

    assert desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.BROWSER) is False

    assert opened == ["http://127.0.0.1:8137/"]
    assert fake_webview.started == 0  # no window was even attempted


def test_none_mode_shows_nothing_at_all(monkeypatch, fake_webview):
    monkeypatch.setattr(desktop.webbrowser, "open", _never_called)
    assert desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.NONE) is False
    assert fake_webview.started == 0


def _never_called(*args, **kwargs):
    raise AssertionError("the browser must not be opened in this case")


# ── the fallback when there is no renderer ───────────────────────────────────


def _webview_exception(message: str) -> BaseException:
    """pywebview's real `WebViewException`, or a stand-in when pywebview is not installed.

    The real class is used when available so the test pins the actual inheritance rather than a
    look-alike; the fallback keeps this file importable in an environment without pywebview.
    """
    try:
        from webview.errors import WebViewException
    except Exception:  # pragma: no cover - only on a machine without pywebview
        return RuntimeError(message)
    return WebViewException(message)


@pytest.mark.parametrize(
    "attr, failure",
    [
        # pywebview absent entirely — a build that did not collect it, or a stripped environment.
        ("create_raises", ImportError("No module named 'webview'")),
        # pywebview present, no renderer. This is the REAL case on a Linux machine without
        # gir1.2-webkit2-4.1 (or with it installed system-wide but invisible to the venv):
        # `create_window` succeeds and `start()` is what raises. pywebview 6.2.1 raises its own
        # WebViewException here; older versions and some backends raise a bare RuntimeError.
        ("start_raises", RuntimeError("You must have either QT or GTK … installed")),
        ("start_raises", _webview_exception("Failed to initialize WebKit2")),
    ],
)
def test_a_failed_window_falls_back_to_the_browser(monkeypatch, fake_webview, tmp_path, capsys,
                                                   attr, failure):
    """A machine with no webview renderer must still get a usable app, not a traceback."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    setattr(fake_webview, attr, failure)
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, **kw: opened.append(url))
    # No dialog: this test is about the BROWSER half of the fallback. Patched to the
    # "could not be shown" answer rather than left to chance, because an unpatched call would
    # open a real window on any machine with tkinter and a display — see the module docstring.
    monkeypatch.setattr(desktop, "_show_fallback_dialog", lambda url, reason: False)

    blocked = desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW)

    assert opened == ["http://127.0.0.1:8137/"]
    # False, not True: the dialog could not be shown, so all the user got was a TAB, and a tab
    # does not own the session. Reporting True here would have `run` stop the server the instant
    # the browser was launched.
    assert blocked is False
    # One line, on stderr, naming the reason — not a silent downgrade.
    message = capsys.readouterr().err
    assert "browser" in message
    assert len(message.strip().splitlines()) == 1


def test_a_missing_pywebview_module_falls_back_rather_than_raising(monkeypatch, tmp_path, capsys):
    """The import itself failing, exercised through the real import machinery rather than a stub."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    monkeypatch.setitem(sys.modules, "webview", None)  # forces ImportError on `import webview`
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, **kw: opened.append(url))
    monkeypatch.setattr(desktop, "_show_fallback_dialog", lambda url, reason: False)

    assert desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW) is False
    assert opened == ["http://127.0.0.1:8137/"]
    assert "browser" in capsys.readouterr().err


def test_a_shown_dialog_owns_the_session(monkeypatch, fake_webview, tmp_path):
    """A dialog that appeared BLOCKED until the user closed it, so its close is the user quitting.

    This is the mirror of the assertion above, and the pair is the whole contract: the boolean
    `_show_ui` returns tracks whether anything blocked, not whether the window succeeded. Getting
    it wrong in this direction would leave the server running after the user closed the dialog.
    """
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    fake_webview.start_raises = _webview_exception("Failed to initialize WebKit2")
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, **kw: None)
    monkeypatch.setattr(desktop, "_show_fallback_dialog", lambda url, reason: True)

    assert desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW) is True


def test_the_dialog_is_told_the_url_and_the_reason(monkeypatch, fake_webview, tmp_path):
    """The URL is the point of the dialog; the reason is what makes it more than a dead end."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    fake_webview.start_raises = _webview_exception("Failed to initialize WebKit2")
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, **kw: None)
    calls = []
    monkeypatch.setattr(
        desktop, "_show_fallback_dialog", lambda url, reason: calls.append((url, reason)) or True
    )

    desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW)

    assert len(calls) == 1
    url, reason = calls[0]
    assert url == "http://127.0.0.1:8137/"
    assert "Failed to initialize WebKit2" in reason


def test_the_browser_is_opened_even_when_the_dialog_appears(monkeypatch, fake_webview, tmp_path):
    """The dialog ADDS to the fallback rather than replacing it.

    If the browser were opened only when the dialog could not be shown, a user who closed the
    dialog without pressing either button would be left with a running server and no page. The
    ordering makes the worst case a browser tab that was not needed.
    """
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    fake_webview.start_raises = _webview_exception("Failed to initialize WebKit2")
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, **kw: opened.append(url))
    monkeypatch.setattr(desktop, "_show_fallback_dialog", lambda url, reason: True)

    desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW)

    assert opened == ["http://127.0.0.1:8137/"]


def test_the_dialog_reports_false_when_tkinter_is_missing(monkeypatch, tmp_path):
    """No tkinter (a separate package on many Linux distributions) must not become a crash.

    Exercised through the real import machinery, the same way the missing-pywebview test above
    works, rather than by stubbing the function that does the importing.
    """
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    monkeypatch.setitem(sys.modules, "tkinter", None)  # forces ImportError on `import tkinter`

    assert desktop._show_fallback_dialog("http://127.0.0.1:8137/", "no renderer") is False


def test_the_dialog_reports_false_when_tk_cannot_open_a_display(monkeypatch, tmp_path):
    """A headless machine has no display to draw on; the browser fallback still stands."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))

    class _FakeTkModule:
        class TclError(Exception):
            pass

        @staticmethod
        def Tk():
            raise _FakeTkModule.TclError("no display name and no $DISPLAY environment variable")

    monkeypatch.setitem(sys.modules, "tkinter", _FakeTkModule)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", object())

    assert desktop._show_fallback_dialog("http://127.0.0.1:8137/", "no renderer") is False


def test_a_keyboard_interrupt_in_the_gui_loop_is_not_a_renderer_failure(
    monkeypatch, fake_webview, tmp_path
):
    """Ctrl-C during the window's event loop means quit. Opening a browser tab in response would
    be the opposite of what was asked, so the fallback catches Exception and not BaseException."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    fake_webview.start_raises = KeyboardInterrupt()
    monkeypatch.setattr(desktop.webbrowser, "open", _never_called)

    with pytest.raises(KeyboardInterrupt):
        desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW)


@pytest.mark.parametrize("attr", ["create_raises", "start_raises"])
def test_a_bad_call_into_pywebview_is_not_disguised_as_a_missing_renderer(
    monkeypatch, fake_webview, tmp_path, attr
):
    """A TypeError from our own call must propagate, not become a browser fallback.

    This is the regression guard for the shipped bug: `private_mode`/`storage_path` were passed to
    `create_window()` rather than `start()`, and the fallback's `except Exception` reported the
    resulting TypeError to the user as "native window unavailable". A wrong argument is a coding
    error nobody can fix by installing a package, so it must be loud. Both call sites are covered
    because either could be the one that drifts after a pywebview upgrade.
    """
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    setattr(fake_webview, attr, TypeError("got an unexpected keyword argument 'private_mode'"))
    monkeypatch.setattr(desktop.webbrowser, "open", _never_called)

    with pytest.raises(TypeError, match="private_mode"):
        desktop._show_ui("http://127.0.0.1:8137/", desktop.UiMode.WINDOW)


# ── the server thread and its shutdown ───────────────────────────────────────


class _FakeServer:
    """Stands in for `uvicorn.Server`: blocks in `run()` until `should_exit` is set.

    That is the contract `_ServerThread` depends on and the only part of uvicorn it uses, so it
    is the part worth faking. A real uvicorn here would need a port, an ASGI app and a data dir.
    """

    def __init__(self, exit_on_flag=True):
        self.should_exit = False
        self.ran = threading.Event()
        self._exit_on_flag = exit_on_flag

    def run(self):
        self.ran.set()
        while not (self.should_exit and self._exit_on_flag):
            time.sleep(0.01)


def test_the_server_runs_on_a_background_thread_not_the_main_one():
    """The whole reason for the phase-2 restructure: `webview.start()` needs the main thread."""
    server = _FakeServer()
    thread = desktop._ServerThread(server)
    thread.start()
    try:
        assert server.ran.wait(timeout=5)
        assert thread.is_alive()
        assert threading.current_thread() is threading.main_thread()
    finally:
        assert thread.stop(timeout=5)


def test_stop_sets_should_exit_and_joins():
    """`should_exit` rather than the daemon flag, because it is what runs the ASGI shutdown.

    A daemon thread killed by interpreter exit never fires the lifespan shutdown event and can be
    mid-request when it dies — which is why `stop()` both sets the flag and waits for the thread.
    """
    server = _FakeServer()
    thread = desktop._ServerThread(server)
    thread.start()
    assert server.ran.wait(timeout=5)

    assert thread.stop(timeout=5) is True

    assert server.should_exit is True
    assert not thread.is_alive()


def test_stop_reports_false_when_the_server_ignores_the_flag():
    """A request that will not finish must not hang a closed window's process forever. `stop()`
    returns False, `run` says so on stderr, and the daemon flag ends the thread at exit."""
    server = _FakeServer(exit_on_flag=False)
    thread = desktop._ServerThread(server)
    thread.start()
    try:
        assert server.ran.wait(timeout=5)
        assert thread.stop(timeout=0.3) is False
        assert thread.is_alive()
    finally:
        server._exit_on_flag = True  # let the daemon thread wind down


def test_the_server_thread_is_a_daemon():
    """The backstop for a `stop()` that times out, not the primary mechanism (see above)."""
    assert desktop._ServerThread(_FakeServer())._thread.daemon is True


def test_stop_reports_false_when_the_thread_object_falsely_claims_to_have_stopped():
    """The regression test for the interrupted-join defect. See `_ServerThread`.

    CPython's `Thread._wait_for_tstate_lock` catches an exception raised while a `join()` is in
    progress — a Ctrl-C, in the case that matters — and calls `self._stop()`, permanently marking
    the Thread object stopped while the OS thread runs on (bpo-45274). After that, `join(timeout)`
    returns in about a millisecond and `is_alive()` answers False.

    A `stop()` built on either would then report a clean shutdown INSTANTLY, at exactly the moment
    the user pressed Ctrl-C and uvicorn had not yet run the ASGI lifespan shutdown — and the "did
    not stop in time" warning could never fire, because the false answer arrives before the real
    one is possible.

    The corrupted state is induced here the same way CPython induces it — dropping the reference
    to the thread-state lock and then calling the private `Thread._stop()`, which is precisely the
    pair of statements `_wait_for_tstate_lock` runs in its own `except` clause — on a thread that
    is genuinely still running. So this is the real mechanism rather than a stand-in for it. The
    assertions below first confirm the Thread object really is lying, and only then require
    `stop()` to disagree with it.

    Driving it with an actual SIGINT was tried and rejected for this suite: it needs the signal to
    land while the main thread is inside `join()`, which under pytest means racing the test runner
    for the main thread and delivering a signal that a mistimed run leaves uncaught. The
    end-to-end SIGINT check was done out of process instead, against the real launcher.
    """
    server = _FakeServer(exit_on_flag=False)  # will not honour should_exit — still running
    thread = desktop._ServerThread(server)
    thread.start()
    try:
        assert server.ran.wait(timeout=5)

        # Induce exactly what an interrupted join leaves behind. `_stop()` requires the tstate
        # lock reference to be gone first and asserts on it, which is why both lines are needed.
        thread._thread._tstate_lock = None
        thread._thread._stop()

        # The premise: the Thread object now lies in both of the ways `stop()` must not trust.
        assert thread._thread.is_alive() is False, "premise broken: Thread still reports alive"
        started = time.monotonic()
        thread._thread.join(timeout=5)
        assert time.monotonic() - started < 0.5, "premise broken: join() actually waited"

        # The property under test: `stop()` is not fooled, because it waits on the completion
        # Event the thread sets in its own `finally` — which is still unset, correctly.
        started = time.monotonic()
        assert thread.stop(timeout=0.3) is False
        assert time.monotonic() - started >= 0.25, "stop() returned early — it trusted the Thread"
        assert thread.is_alive() is True  # ours, not the Thread object's
    finally:
        server._exit_on_flag = True


def test_stop_reports_true_only_once_the_server_call_has_returned():
    """Completion is the target function returning, not the thread being scheduled out.

    Pins the direction the fix must not overshoot in: an Event set anywhere other than after
    `server.run()` returns would make `stop()` true too early, which is the same false-clean
    shutdown by another route.
    """
    server = _FakeServer()
    thread = desktop._ServerThread(server)
    thread.start()
    assert server.ran.wait(timeout=5)

    # Running: not finished, whatever else is true.
    assert thread._finished.is_set() is False
    assert thread.stop(timeout=5) is True
    assert thread._finished.is_set() is True


def test_a_server_that_raises_still_counts_as_finished(monkeypatch):
    """`finally`, so a crashed server does not cost a full ten-second wait on the way out.

    A server that dies on `bind()` has finished as surely as one that shut down cleanly, and a
    `stop()` that waited the full ten seconds for a thread already gone would be a pointless hang
    on the way out.

    The exception is left to propagate out of the thread — `_ServerThread` deliberately does not
    swallow it, since a launcher that hid a server crash would be worse than a noisy one — so the
    excepthook is silenced for the duration rather than the exception being caught.
    """

    class _Crashing:
        should_exit = False

        def run(self):
            raise RuntimeError("bind failed")

    monkeypatch.setattr(threading, "excepthook", lambda args: None)

    thread = desktop._ServerThread(_Crashing())
    thread.start()
    assert thread.stop(timeout=5) is True
    assert thread.is_alive() is False


def test_run_waits_on_the_event_rather_than_joining_the_thread():
    """`run`'s non-blocking branch must not call `Thread.join()`, which POISONS the Thread object
    when a Ctrl-C interrupts it — after which the `stop()` in the except handler is worthless.

    Asserted at the seam rather than by driving a real signal: `_ServerThread.wait` is the method
    `run` is required to use, and `Thread.join` is the one it must not.
    """
    import inspect

    source = inspect.getsource(desktop.run)
    assert "thread.wait()" in source
    assert "thread.join()" not in source, "run() joins the Thread — see _ServerThread"

    # And `wait` must not be a `Thread.join` in disguise.
    wait_source = inspect.getsource(desktop._ServerThread.wait)
    assert "_finished.wait" in wait_source
    assert "_thread.join" not in wait_source


def test_both_shutdown_paths_warn_when_the_server_does_not_stop(capsys):
    """The warning must exist on the Ctrl-C path too, not only on the window path — the whole
    point of `stop()` returning an honest False is that something acts on it."""
    server = _FakeServer(exit_on_flag=False)
    thread = desktop._ServerThread(server)
    thread.start()
    try:
        assert server.ran.wait(timeout=5)
        desktop._stop_or_warn(thread)
        assert "did not stop" in capsys.readouterr().err
    finally:
        server._exit_on_flag = True


def test_no_warning_when_the_server_stops_cleanly(capsys):
    server = _FakeServer()
    thread = desktop._ServerThread(server)
    thread.start()
    assert server.ran.wait(timeout=5)
    desktop._stop_or_warn(thread)
    assert capsys.readouterr().err == ""


# ── run(): the shutdown handshake ────────────────────────────────────────────


def _run_with_fakes(monkeypatch, tmp_path, ui, blocked, server=None):
    """Drive `run()` with every collaborator faked but the sequencing real.

    What stays real is the part under test: the lock, the readiness gate, the order of the poll
    and the UI call, and what `run` does with `_show_ui`'s answer. Faked are uvicorn (no port to
    bind) and the UI (no display).
    """
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    server = server if server is not None else _FakeServer()
    calls = []

    monkeypatch.setattr(desktop, "_load_asgi_app", lambda: object())
    monkeypatch.setattr(desktop, "check_assets", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "choose_port", lambda *a, **kw: 8137)
    monkeypatch.setattr(desktop, "wait_until_ready", lambda *a, **kw: calls.append("ready") or True)

    def fake_show(url, mode):
        calls.append(("show", url, mode))
        return blocked

    monkeypatch.setattr(desktop, "_show_ui", fake_show)

    import uvicorn

    monkeypatch.setattr(uvicorn, "Config", lambda *a, **kw: kw)
    monkeypatch.setattr(uvicorn, "Server", lambda cfg: server)

    code = desktop.run(ui=ui)
    return code, calls, server


def test_run_shuts_the_server_down_when_the_window_closes(monkeypatch, tmp_path):
    """The native-window session: `_show_ui` returning is the user quitting, so the server stops.

    Without this, closing the window would leave uvicorn serving with no way back to it — the
    port stays bound and the single-instance lock stays held, so the next launch refuses to start.
    """
    code, calls, server = _run_with_fakes(
        monkeypatch, tmp_path, desktop.UiMode.WINDOW, blocked=True
    )

    assert code == 0
    assert server.should_exit is True
    # Readiness first, THEN the UI. A window opened before `GET /` answers shows a
    # connection-refused page and never retries.
    assert calls[0] == "ready"
    assert calls[1] == ("show", "http://127.0.0.1:8137/", desktop.UiMode.WINDOW)


def test_run_waits_instead_of_shutting_down_when_the_ui_did_not_block(monkeypatch, tmp_path):
    """Browser and headless modes: `_show_ui` returns at once and the session outlives it, so
    `run` must block on the server rather than treating the return as a quit."""
    server = _FakeServer()
    finished = threading.Event()

    def call_run():
        _run_with_fakes(monkeypatch, tmp_path, desktop.UiMode.BROWSER, blocked=False, server=server)
        finished.set()

    caller = threading.Thread(target=call_run, daemon=True)
    caller.start()
    try:
        assert server.ran.wait(timeout=5)
        # It is still inside run(), waiting — not returned, and the server was NOT asked to stop.
        assert not finished.wait(timeout=0.5)
        assert server.should_exit is False
    finally:
        server.should_exit = True
    assert finished.wait(timeout=5)


def test_run_gives_up_when_the_server_never_becomes_ready(monkeypatch, tmp_path):
    """No UI is shown and the exit code is non-zero: a window on a dead server is worse than a
    message, and the server thread is still stopped so the lock is not left held."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    server = _FakeServer()
    monkeypatch.setattr(desktop, "_load_asgi_app", lambda: object())
    monkeypatch.setattr(desktop, "check_assets", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "choose_port", lambda *a, **kw: 8137)
    monkeypatch.setattr(desktop, "wait_until_ready", lambda *a, **kw: False)
    monkeypatch.setattr(desktop, "_show_ui", _never_called)

    import uvicorn

    monkeypatch.setattr(uvicorn, "Config", lambda *a, **kw: kw)
    monkeypatch.setattr(uvicorn, "Server", lambda cfg: server)

    assert desktop.run(ui=desktop.UiMode.WINDOW) == 1
    assert server.should_exit is True


def test_a_second_launch_shows_the_running_instance_and_exits_zero(monkeypatch, tmp_path):
    """The single-instance rule survives phase 2: no second server, no second uvicorn thread.

    The UI IS shown — pointed at the running instance's port — because that is what a user
    double-clicking the icon again is asking for, and a second window on one server is not the
    two-SQLite-writers case the lock guards against.
    """
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    holder = desktop.SingleInstance(tmp_path / "desktop.lock")
    assert holder.acquire()
    holder.write_state(9137)
    try:
        monkeypatch.setattr(desktop, "server_answers", lambda port, **kw: port == 9137)
        shown = []
        monkeypatch.setattr(desktop, "_show_ui", lambda url, mode: shown.append(url) or True)
        # Nothing may start: a second server against one SQLite file is the corruption case.
        monkeypatch.setattr(desktop, "_load_asgi_app", _never_called)
        monkeypatch.setattr(desktop, "_ServerThread", _never_called)

        assert desktop.run(ui=desktop.UiMode.WINDOW) == 0
        assert shown == ["http://127.0.0.1:9137/"]
    finally:
        holder.release()


def test_a_second_launch_refuses_when_the_holder_is_not_answering(monkeypatch, tmp_path):
    """Locked but silent: a start in progress, or a wedged instance. Starting a second server
    against the same database is what the lock exists to prevent, so this refuses rather than
    races it."""
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    holder = desktop.SingleInstance(tmp_path / "desktop.lock")
    assert holder.acquire()
    holder.write_state(9137)
    try:
        monkeypatch.setattr(desktop, "server_answers", lambda port, **kw: False)
        monkeypatch.setattr(desktop, "_show_ui", _never_called)
        monkeypatch.setattr(desktop, "_load_asgi_app", _never_called)
        assert desktop.run(ui=desktop.UiMode.WINDOW) == 1
    finally:
        holder.release()


# ── the bind host ────────────────────────────────────────────────────────────


def test_the_bind_host_is_loopback_and_is_not_configurable():
    """A security property, not a default (see `desktop.BIND_HOST` and `app/csrf.py`).

    `csrf.is_same_site` deliberately ALLOWS a request carrying neither `Sec-Fetch-Site` nor
    `Origin`, on the stated grounds that such a request is the user on their own machine. Bound
    to a routable address, that reasoning fails and the LAN gets an unauthenticated delete.

    So this asserts both halves: the constant is the loopback, and the CLI offers no way to
    change it — a `--host` flag would be the regression, not a wrong default.
    """
    assert desktop.BIND_HOST == "127.0.0.1"

    # No routable literal anywhere in the module's CODE. Checked over the parsed string constants
    # rather than over the raw text, because `BIND_HOST`'s own docstring names `0.0.0.0` while
    # explaining why it is never used — that prose is the point of the constant, and a grep would
    # flag it. Docstrings are excluded here by taking only the constants a statement evaluates.
    import ast

    tree = ast.parse((REPO_ROOT / "app" / "desktop.py").read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    # A bare string statement is also documentation here — `BIND_HOST` and `DEFAULT_PORT` are
    # each followed by one, the attribute-docstring idiom this codebase uses throughout.
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            docstrings.add(id(node.value))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert not any("0.0.0.0" in s for s in literals), literals

    result = subprocess.run(
        [sys.executable, "-m", "app", "--help"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--host" not in result.stdout
    assert "--port" in result.stdout and "--no-browser" in result.stdout


# ── single instance ──────────────────────────────────────────────────────────


def test_a_second_acquisition_fails_while_the_lock_is_held(tmp_path):
    first = desktop.SingleInstance(tmp_path / "desktop.lock")
    assert first.acquire() is True
    first.write_state(8137)

    second = desktop.SingleInstance(tmp_path / "desktop.lock")
    assert second.acquire() is False
    # …and the loser can still read where the holder is serving, which is what lets a second
    # launch open the running instance instead of failing at the user.
    assert second.read_state() == {"port": 8137, "pid": os.getpid()}

    first.release()


def test_a_stale_lock_is_taken_over(tmp_path):
    """A crashed instance must not lock the user out of their own app.

    The lock is on an open file descriptor, so the kernel releases it when the holder dies — the
    file left on disk is not itself the lock. Exercised with a real subprocess that takes the
    lock and is then killed, because that is precisely the case (a crash, a kill -9, a machine
    losing power) where a PID-file scheme would leave a file nothing can safely remove.
    """
    lock_path = tmp_path / "desktop.lock"
    holder = subprocess.Popen(
        [
            sys.executable, "-c",
            "import sys, time; sys.path.insert(0, %r); "
            "from app.desktop import SingleInstance; "
            "s = SingleInstance(__import__('pathlib').Path(%r)); "
            "assert s.acquire(); s.write_state(9999); print('held', flush=True); "
            "time.sleep(60)" % (str(REPO_ROOT), str(lock_path)),
        ],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        # While it lives, we cannot have the lock.
        blocked = desktop.SingleInstance(lock_path)
        assert blocked.acquire() is False
        assert (blocked.read_state() or {}).get("port") == 9999
    finally:
        holder.kill()
        holder.wait(timeout=10)

    # The holder is gone; the file is still there and stale. It must be takeable.
    successor = desktop.SingleInstance(lock_path)
    assert successor.acquire() is True, "a stale lock file locked the user out"
    successor.write_state(8137)
    assert json.loads(lock_path.read_text())["port"] == 8137
    successor.release()


def test_acquiring_does_not_truncate_a_live_holder_state(tmp_path):
    """The failed `acquire()` must leave the holder's recorded port intact.

    An open in "w" mode truncates before the lock is attempted, so a second launch would blank
    the very line it then needs to read — leaving the running instance unreachable.
    """
    lock_path = tmp_path / "desktop.lock"
    first = desktop.SingleInstance(lock_path)
    assert first.acquire()
    first.write_state(8137)

    for _ in range(3):
        assert desktop.SingleInstance(lock_path).acquire() is False
    assert json.loads(lock_path.read_text())["port"] == 8137

    first.release()


def test_read_state_tolerates_an_absent_or_corrupt_file(tmp_path):
    absent = desktop.SingleInstance(tmp_path / "nothing-here.lock")
    assert absent.read_state() is None

    corrupt_path = tmp_path / "corrupt.lock"
    corrupt_path.write_text("not json at all")
    assert desktop.SingleInstance(corrupt_path).read_state() is None

    not_an_object = tmp_path / "list.lock"
    not_an_object.write_text("[1, 2, 3]")
    assert desktop.SingleInstance(not_an_object).read_state() is None


# ── asset self-check ─────────────────────────────────────────────────────────


def test_the_asset_check_passes_on_a_source_checkout():
    desktop.check_assets()  # must not raise against the real app/ directory


def test_the_asset_check_names_a_missing_directory(tmp_path):
    for name in desktop._ASSET_DIRS:
        (tmp_path / name).mkdir()
        (tmp_path / name / "placeholder").write_text("x")
    (tmp_path / "locales").rename(tmp_path / "locales-moved")

    with pytest.raises(RuntimeError) as excinfo:
        desktop.check_assets(tmp_path)

    message = str(excinfo.value)
    assert "locales" in message and "missing" in message
    # …and it does not accuse the directories that are fine.
    assert "templates" not in message and "static" not in message


def test_the_asset_check_rejects_an_empty_directory(tmp_path):
    """An empty directory is as broken as an absent one: a bundle entry that collected the
    directory but none of its files renders nothing, with no error until the first page."""
    for name in desktop._ASSET_DIRS:
        (tmp_path / name).mkdir()
        (tmp_path / name / "placeholder").write_text("x")
    (tmp_path / "static" / "placeholder").unlink()

    with pytest.raises(RuntimeError, match="static"):
        desktop.check_assets(tmp_path)


# ── version single-sourcing ──────────────────────────────────────────────────


def test_the_version_is_single_sourced():
    """`app.__version__`, `app.config.APP_VERSION` and pyproject.toml must agree.

    pyproject.toml declares the version `dynamic` and points hatchling at `app/__init__.py`, so
    the agreement is structural rather than maintained by hand — which is what this asserts:
    there must be no literal `version = "…"` under `[project]` to drift away from the code.
    """
    import app

    assert config.APP_VERSION == app.__version__

    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)

    assert "version" not in pyproject["project"], (
        "pyproject.toml restates the version instead of deriving it from app/__init__.py"
    )
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "app/__init__.py"
    assert pyproject["project"]["scripts"]["battery-sim"] == "app.desktop:main"


# ── the launcher end to end ──────────────────────────────────────────────────


def test_the_launcher_serves_on_the_chosen_port_and_writes_only_to_its_data_dir(tmp_path):
    """One end-to-end check: `python -m app --no-browser --port N` really answers.

    Out of process and against its own data directory, so nothing here can touch the developer's
    `./data`. This is the only test in the file that starts a server; the value it adds over the
    unit tests above is that the pieces are wired together at all — a launcher whose parts each
    pass in isolation and which fails to bind is the outcome worth catching here.
    """
    from urllib.request import urlopen

    port = desktop._ephemeral_port()
    data_dir = tmp_path / "data"
    env = {**os.environ, config.ENV_DATA_DIR: str(data_dir)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "app", "--no-browser", "--port", str(port)],
        cwd=REPO_ROOT, env=env,
    )
    try:
        assert desktop.wait_until_ready(port), "the launcher did not start a server"
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
        # The data directory it was given is the one it used, lock file included.
        assert (data_dir / "desktop.lock").exists()
        assert json.loads((data_dir / "desktop.lock").read_text())["port"] == port
        assert (data_dir / "config.toml").exists()  # written by the import-time config.load()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
