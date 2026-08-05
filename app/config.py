"""Runtime configuration for the Home Battery Simulator (docs/specs/08-architecture.md §5.4).

Resolves the data directory and reads `config.toml` from it. In this increment the only
config that matters is the feature-interest egress pair:

    feature_interest_url   the outbound POST endpoint; empty by default, and while empty no
                           request is ever made (§7.5). A packager/user sets it deliberately.
    installation_id        a random, persistent pseudonymous identifier (§7.5). Generated on
                           first run, written back to config.toml, regenerated if the line is
                           cleared. It is NOT derived from hardware/host/account/data.

Resolution order for each value: environment variable → config.toml → default. The data
directory itself is `BATTERY_SIM_DATA_DIR`, or — see `data_dir()` — `./data/` beside the repo
for an ordinary source run and a per-user OS location for a frozen build. Created on first use.

## Why the per-user path helper lives HERE rather than in app/desktop.py

`user_data_dir()` is the launcher's concern: it is what `app.desktop` puts into
`BATTERY_SIM_DATA_DIR` before importing the app. But `data_dir()` needs the same answer for its
frozen fallback, and `app.config` is imported by every persistence module — so putting the helper
in `app.desktop` would mean `config` importing `desktop`, and `desktop` already has to import
`config` to know the env var name. One of the two directions had to go, and this one is the
cleaner: `config` stays a leaf that imports nothing from the app, and `desktop` sits above it.

Main items:
    APP_VERSION            the app version reported in the POST body.
    ENV_DATA_DIR           the name of the data-directory environment variable.
    user_data_dir()        the per-user, per-OS data location (no side effects, not created).
    data_dir()             resolved, ensured-to-exist data directory.
    load() -> Config       the resolved config; generates+persists installation_id if absent.
    Config                 dataclass carrying feature_interest_url, installation_id, app_version.
"""

import os
import secrets
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from app import __version__

# Single-sourced from `app/__init__.py`, which is also what `pyproject.toml` reads via
# `[tool.hatch.version]`. This used to be a literal with a note to revisit "when packaging
# lands"; packaging has landed, and `app.__version__` is now the one place the string exists.
APP_VERSION = __version__

ENV_DATA_DIR = "BATTERY_SIM_DATA_DIR"
_ENV_DATA_DIR = ENV_DATA_DIR
_ENV_URL = "BATTERY_SIM_FEATURE_INTEREST_URL"
_ENV_INSTALL_ID = "BATTERY_SIM_INSTALLATION_ID"

_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration (only the egress pair is used in this increment)."""

    feature_interest_url: str
    installation_id: str
    app_version: str = APP_VERSION


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


def _config_path() -> Path:
    return data_dir() / "config.toml"


def _read_toml() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _generate_installation_id() -> str:
    """A random pseudonymous id — see §7.5. Not derived from anything about the machine."""
    return secrets.token_hex(16)


def _persist_installation_id(install_id: str) -> None:
    """Append `installation_id` to config.toml, creating the file if needed.

    Deliberately minimal: we only ever add this one line, so a full TOML writer is not
    warranted. Existing content is left untouched; the line is appended once.
    """
    path = _config_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    line = f'installation_id = "{install_id}"\n'
    path.write_text(existing + line, encoding="utf-8")


def load() -> Config:
    """Resolve config; generate and persist an installation_id on first run.

    The URL is empty unless set (env or config.toml) — while empty, no POST is ever made.
    The installation_id is read from env or config.toml; if neither has it, a fresh one is
    generated and written back to config.toml so it stays stable across runs.
    """
    toml = _read_toml()

    url = os.environ.get(_ENV_URL, toml.get("feature_interest_url", "")).strip()

    install_id = os.environ.get(_ENV_INSTALL_ID) or toml.get("installation_id")
    if not install_id:
        install_id = _generate_installation_id()
        # Only persist when the value did not come from the environment — an env-provided id
        # is the operator's to manage, and we should not write it into the file.
        if not os.environ.get(_ENV_INSTALL_ID):
            _persist_installation_id(install_id)

    return Config(feature_interest_url=url, installation_id=install_id)
