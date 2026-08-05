"""Build provenance: which commit this copy of the application was built from.

Main items:
    BUILD_SHA        the short commit SHA, or "unknown" outside a build.
    BUILD_SHA_SOURCE where BUILD_SHA came from ("ci", "git", "default" or "unknown").

**This file is COMMITTED with placeholder values and OVERWRITTEN at build time** by
`packaging/build_info.py`, which the packaging scripts invoke before PyInstaller runs.

Committed rather than generated-only, deliberately. If this file were gitignored and written
only by the build, a plain `git clone` followed by `python -m app` would raise ImportError in
whatever imports it — the development path would depend on having run a packaging script. A
stale placeholder in a source checkout is the better failure: it says "unknown", which is
exactly true of a tree nobody built.

The distinction between "unknown" and a real SHA is load-bearing for support: an artifact that
cannot say what it was built from should say so, not silently report a value it inferred from
whatever happened to be in the working directory.

Deliberately NOT folded into `app.__version__`. That string is compared to the release tag by
exact string equality (`.github/workflows/release.yml`); appending a SHA to it would change that
comparison. Provenance is a separate value with separate consumers.

Note that a build overwrites this file IN the source tree. `packaging/build-linux.sh` restores
it from git afterwards (on a trap, so an interrupted build restores it too), which is why a
build does not leave the checkout dirty. `tests/test_packaging_metadata.py` asserts the
committed copy still says "unknown", so a stamped copy cannot be committed by accident.
"""

BUILD_SHA = "unknown"
"""Short commit SHA the artifact was built from; "unknown" in an unbuilt source tree."""

BUILD_SHA_SOURCE = "default"
"""Provenance of BUILD_SHA itself: "ci", "git", or "default" for this committed placeholder."""
