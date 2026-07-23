"""Runtime configuration for the Home Battery Simulator (specs/08-architecture.md §5.4).

Resolves the data directory and reads `config.toml` from it. In this increment the only
config that matters is the feature-interest egress pair:

    feature_interest_url   the outbound POST endpoint; empty by default, and while empty no
                           request is ever made (§7.5). A packager/user sets it deliberately.
    installation_id        a random, persistent pseudonymous identifier (§7.5). Generated on
                           first run, written back to config.toml, regenerated if the line is
                           cleared. It is NOT derived from hardware/host/account/data.

Resolution order for each value: environment variable → config.toml → default. The data
directory itself is `BATTERY_SIM_DATA_DIR` or `./data/` beside the repo, created on first use.

Main items:
    APP_VERSION            the app version reported in the POST body.
    data_dir()             resolved, ensured-to-exist data directory.
    load() -> Config       the resolved config; generates+persists installation_id if absent.
    Config                 dataclass carrying feature_interest_url, installation_id, app_version.
"""

import os
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Kept in step with pyproject.toml [project].version. A single source is overkill for one
# string at this stage; revisit when packaging lands.
APP_VERSION = "0.1.0"

_ENV_DATA_DIR = "BATTERY_SIM_DATA_DIR"
_ENV_URL = "BATTERY_SIM_FEATURE_INTEREST_URL"
_ENV_INSTALL_ID = "BATTERY_SIM_INSTALLATION_ID"

_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration (only the egress pair is used in this increment)."""

    feature_interest_url: str
    installation_id: str
    app_version: str = APP_VERSION


def data_dir() -> Path:
    """The data directory (`BATTERY_SIM_DATA_DIR` or ./data), created if missing."""
    d = Path(os.environ.get(_ENV_DATA_DIR, _REPO_ROOT / "data"))
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
