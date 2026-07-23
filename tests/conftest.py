"""Pytest bootstrap: put the repository root on sys.path so `import app` works in-process.

The frontend smoke test launches uvicorn as a subprocess (cwd=repo root), so it never needs
`app` importable in the test process. The feature-interest unit tests, by contrast, import
`app.config` / `app.db` / `app.interest` directly. Prepending the repo root here makes those
imports resolve without a src layout or an editable install.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
