"""The Home Battery Simulator application package.

Holds only the package version. Everything else lives in the sibling modules — `app.main` is
the ASGI app, `app.desktop` the launcher, `app.config` the runtime configuration.

`__version__` is the SINGLE source of the version string. Three consumers read it:

  * `pyproject.toml`, via `[tool.hatch.version] path = "app/__init__.py"`, so the distribution
    version is derived from the code rather than restated beside it;
  * `app.config.APP_VERSION`, the version the app reports about itself;
  * a test in `tests/test_desktop.py` that reads the built metadata back, so the two cannot
    drift apart silently.

Deliberately NOT read from `importlib.metadata`: a PyInstaller bundle does not reliably collect
the `.dist-info` directory that lookup depends on, so the frozen app would raise
`PackageNotFoundError` at import time for a string that is already in the source.

**This file also makes `app` a regular package.** It was an implicit namespace package before
packaging landed; hatchling and PyInstaller both handle a regular package more predictably, and
a namespace package has no place to put a `__version__` at all.
"""

__version__ = "0.1.0"
