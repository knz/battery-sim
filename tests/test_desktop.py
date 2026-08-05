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

    uv run pytest tests/test_desktop.py
"""

import json
import os
import subprocess
import sys
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

    def fake_run(port=None, open_browser=True):
        seen.update(port=port, open_browser=open_browser)
        return 0

    monkeypatch.setattr(desktop, "run", fake_run)
    assert desktop.main(["--port", "8137", "--no-browser"]) == 0
    assert seen == {"port": 8137, "open_browser": False}


def test_the_browser_opens_by_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(desktop, "run", lambda **kw: seen.update(kw) or 0)
    desktop.main([])
    assert seen == {"port": None, "open_browser": True}


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
