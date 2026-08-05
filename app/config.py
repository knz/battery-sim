"""Runtime configuration for the Home Battery Simulator (docs/specs/08-architecture.md §5.4).

Resolves the data directory: `BATTERY_SIM_DATA_DIR`, or — see `data_dir()` — `./data/` beside
the repo for an ordinary source run and a per-user OS location for a frozen build. Created on
first use.

This module used to carry a `Config` dataclass and a `load()` that read `config.toml`, holding
the `feature_interest_url` / `installation_id` pair for the feature-interest telemetry. That
whole limb went when feature requests moved to GitHub issues (app/features.py): nothing about a
request is recorded or transmitted, so neither value has a consumer, and the app no longer reads
or writes `config.toml` at all. What remains is data-directory resolution.

## Why the per-user path helper lives HERE rather than in app/desktop.py

`user_data_dir()` is the launcher's concern: it is what `app.desktop` puts into
`BATTERY_SIM_DATA_DIR` before importing the app. But `data_dir()` needs the same answer for its
frozen fallback, and `app.config` is imported by every persistence module — so putting the helper
in `app.desktop` would mean `config` importing `desktop`, and `desktop` already has to import
`config` to know the env var name. One of the two directions had to go, and this one is the
cleaner: `config` stays a leaf that imports nothing from the app, and `desktop` sits above it.

Main items:
    APP_VERSION            the app version, single-sourced from app/__init__.py.
    ENV_DATA_DIR           the name of the data-directory environment variable.
    user_data_dir()        the per-user, per-OS data location (no side effects, not created).
    data_dir()             resolved, ensured-to-exist data directory.
"""

import os
import sys
from pathlib import Path

from app import __version__

# Single-sourced from `app/__init__.py`, which is also what `pyproject.toml` reads via
# `[tool.hatch.version]`. This used to be a literal with a note to revisit "when packaging
# lands"; packaging has landed, and `app.__version__` is now the one place the string exists.
APP_VERSION = __version__

ENV_DATA_DIR = "BATTERY_SIM_DATA_DIR"
_ENV_DATA_DIR = ENV_DATA_DIR

_REPO_ROOT = Path(__file__).resolve().parent.parent

_APP_DIR_NAME = "BatterySim"
"""The directory name used on macOS and Windows, where per-app directories are Title Case."""

_XDG_DIR_NAME = "battery-sim"
"""The directory name used on Linux, where `$XDG_DATA_HOME` entries are lowercase-hyphenated."""


def user_data_dir() -> Path:
    """The conventional per-user data location for this OS. Not created, no side effects.

    Hand-rolled rather than taken from `platformdirs`: the runtime dependency list is
    deliberately six packages, and this is fifteen lines that will not change.

      * macOS   `~/Library/Application Support/BatterySim`
      * Linux   `$XDG_DATA_HOME/battery-sim`, else `~/.local/share/battery-sim`
      * Windows `%LOCALAPPDATA%\\BatterySim\\data`

    **LOCALAPPDATA, not APPDATA, on Windows.** APPDATA roams: on a domain-joined machine its
    contents are copied to and from a server at every logon and logoff. What this directory holds
    is a SQLite database and `.npz` series files — machine-local state, potentially hundreds of
    megabytes, and a database file that a roaming copy can corrupt outright by restoring a stale
    version over one that is open. LOCALAPPDATA is the location for exactly that kind of state.

    Falls back to LOCALAPPDATA's documented default when the variable is unset, which happens in
    stripped service environments rather than in a normal user session.
    """
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / _APP_DIR_NAME
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / _APP_DIR_NAME / "data"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else home / ".local" / "share"
    return base / _XDG_DIR_NAME


def data_dir() -> Path:
    """The resolved data directory, created if missing.

    `BATTERY_SIM_DATA_DIR` wins when set — that is the seam `app.desktop`, the test suite and any
    operator use, and it is why no storage module needed changing when packaging arrived.

    Otherwise the default depends on whether this is a frozen build:

      * **Source run:** `./data` beside the repo, unchanged. Developers have data there and
        relocating it silently would be a worse outcome than the small inconsistency.
      * **Frozen build:** the per-user path above. `_REPO_ROOT` is derived from `__file__`, which
        inside a bundle points at the bundle itself — read-only on macOS (a signed .app), and
        under PyInstaller onefile a temporary extraction directory that is DELETED when the
        process exits. Writing workspaces there loses them all on quit, with no error at any
        point. So `_REPO_ROOT / "data"` is never a defensible answer when frozen.

    In practice `app.desktop` sets the env var before anything imports this module, so the frozen
    branch is a backstop for a frozen entry point that bypasses the launcher rather than the
    normal path. It is here anyway because the failure it prevents is silent data loss.
    """
    env = os.environ.get(_ENV_DATA_DIR)
    if env:
        d = Path(env)
    elif getattr(sys, "frozen", False):
        d = user_data_dir()
    else:
        d = _REPO_ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


