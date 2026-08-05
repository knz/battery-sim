"""The build-time metadata generators: build provenance and the Windows version resource.

Two modules under `packaging/` are covered here:

  * **`build_info.py`** — resolves the commit SHA the artifact is built from, preferring
    `GITHUB_SHA` over `git rev-parse` and answering "unknown" when neither is available. The
    fallback is the interesting case: a build from a source tarball must SUCCEED and must not
    invent a SHA, and both halves of that are asserted here.
  * **`battery_sim_version_info.py`** — renders the VERSIONINFO resource embedded in
    `battery-sim.exe`. The version tuple it derives is checked against `app.__version__`, so the
    resource cannot drift from the single source the way a hand-written file would.

**Nothing here runs PyInstaller or writes into the source tree.** The generators' pure functions
are called directly and their output is inspected as text; the two that write files are pointed
at tmp_path. Note in particular that PyInstaller's own `versioninfo` module cannot even be
imported off Windows (it needs `win32api`), so validating the rendered resource by parsing it
with PyInstaller is not possible on Linux or macOS — the shape is asserted structurally instead.

    uv run pytest tests/test_packaging_metadata.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app import __version__

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"


def _load(name: str):
    """Import a module from `packaging/` by path.

    `packaging/` is not a package and is not on `sys.path` — the spec adds it at build time. A
    path-based import keeps that arrangement intact rather than requiring the test run to
    replicate it.
    """
    spec = importlib.util.spec_from_file_location(name, PACKAGING / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_info = _load("build_info")
version_info = _load("battery_sim_version_info")


# ── the build SHA ─────────────────────────────────────────────────────────────


def test_ci_sha_wins_and_is_shortened(monkeypatch):
    """GITHUB_SHA names the commit the workflow checked out, which beats asking git locally."""
    monkeypatch.setenv("GITHUB_SHA", "1a2b3c4d5e6f7890abcdef1234567890abcdef12")

    sha, source = build_info.resolve_build_sha()

    assert sha == "1a2b3c4"
    assert source == "ci"


def test_an_empty_ci_sha_is_ignored(monkeypatch):
    """An empty GITHUB_SHA is not an answer. Falling through to git is better than reporting ""."""
    monkeypatch.setenv("GITHUB_SHA", "")

    sha, source = build_info.resolve_build_sha()

    assert source in {"git", "unknown"}
    assert sha != ""


def test_git_is_used_when_there_is_no_ci_sha(monkeypatch):
    """The local development path. Skipped where the tests are not run from a git checkout."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    inside_git = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--git-dir"],
        capture_output=True,
    ).returncode == 0
    if not inside_git:
        pytest.skip("not a git checkout; the git branch cannot be exercised here")

    sha, source = build_info.resolve_build_sha()

    assert source == "git"
    assert len(sha) == build_info.SHORT_SHA_LENGTH
    # Hex, and nothing else — a stray newline or a `fatal:` leaking through would show up here.
    assert all(c in "0123456789abcdef" for c in sha)


def test_no_ci_and_no_git_is_unknown_rather_than_a_failure(monkeypatch, tmp_path):
    """Building from a source tarball is legitimate and must not fail.

    It must equally not GUESS. The value's only purpose is answering "which commit is this?"
    during support, and a fabricated answer there is worse than no answer.
    """
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    # Point the lookup at a directory that is not a git repository. tmp_path is outside the
    # checkout, so `git rev-parse` there fails the way it would in an unpacked tarball.
    monkeypatch.setattr(build_info, "ROOT", tmp_path)

    sha, source = build_info.resolve_build_sha()

    assert sha == "unknown"
    assert source == "unknown"


def test_a_missing_git_binary_is_unknown_rather_than_a_crash(monkeypatch):
    """`git` absent from PATH is an environment fact, not an error."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    def _no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(build_info.subprocess, "run", _no_git)

    assert build_info.resolve_build_sha() == ("unknown", "unknown")


def test_the_generated_module_is_importable_python(monkeypatch, tmp_path):
    """The generated file is imported by the app, so it must parse and expose both names."""
    target = tmp_path / "_build_info.py"
    monkeypatch.setattr(build_info, "TARGET", target)
    monkeypatch.setenv("GITHUB_SHA", "deadbeefcafe0000000000000000000000000000")

    sha, source = build_info.write_build_info()

    namespace: dict[str, object] = {}
    exec(compile(target.read_text(), str(target), "exec"), namespace)
    assert namespace["BUILD_SHA"] == sha == "deadbee"
    assert namespace["BUILD_SHA_SOURCE"] == source == "ci"


def test_the_committed_placeholder_says_unknown():
    """The file in the repository must not claim a SHA — see its own docstring.

    A committed placeholder that had picked up a real SHA (from someone running the generator and
    committing the result) would make every source checkout claim to be that one build.
    """
    from app import _build_info

    assert _build_info.BUILD_SHA == "unknown"
    assert _build_info.BUILD_SHA_SOURCE == "default"


# ── the Windows version resource ──────────────────────────────────────────────


def test_the_version_tuple_tracks_app_version():
    """The resource is generated FROM `app.__version__`, so the two cannot drift apart."""
    major, minor, patch, build = version_info.version_tuple(__version__)

    assert f"{major}.{minor}.{patch}" == __version__
    # Always 0: nothing in this project produces a monotonic build number, and a field that is
    # always 0 is more honest than one that restarts at 1 on every machine.
    assert build == 0


@pytest.mark.parametrize(
    "version",
    ["0.1", "1.2.3.4", "1.2.3-rc1", "v1.2.3", "1.2.3+g1a2b3c4", "", "one.two.three"],
)
def test_an_unparseable_version_is_refused(version):
    """Substituting zeroes would ship an exe claiming 0.0.0.0 while the release says otherwise.

    Note that `1.2.3-rc1` and `1.2.3+g1a2b3c4` are in this list deliberately: if the project ever
    adopts prerelease or build-metadata versions, this test is the thing that stops the resource
    silently misreporting them, and the fix is to decide how they map rather than to loosen it.
    """
    with pytest.raises(ValueError):
        version_info.version_tuple(version)


def test_the_sha_rides_in_the_product_version_string():
    """Semver build metadata: `+g<sha>`, which is defined as not affecting precedence."""
    assert version_info.product_version_string("0.1.0", "1a2b3c4") == "0.1.0+g1a2b3c4"


@pytest.mark.parametrize("sha", ["unknown", ""])
def test_an_unknown_sha_leaves_the_version_string_clean(sha):
    """No SHA is better than a `+gunknown` suffix that reads like a commit."""
    assert version_info.product_version_string("0.1.0", sha) == "0.1.0"


def test_the_rendered_resource_carries_the_version_and_the_sha():
    """The numeric tuple cannot hold hex, so the SHA must appear in the string block instead."""
    text = version_info.render_version_info("0.1.0", "1a2b3c4")

    assert "filevers=(0, 1, 0, 0)" in text
    assert "prodvers=(0, 1, 0, 0)" in text
    # In the strings, and specifically as ProductVersion.
    assert "'0.1.0+g1a2b3c4'" in text
    assert "StringStruct(\"ProductVersion\", '0.1.0+g1a2b3c4')" in text
    # The exe's own name, which is what Windows shows when the file has been renamed.
    assert "StringStruct(\"OriginalFilename\", 'battery-sim.exe')" in text


def test_the_rendered_resource_is_syntactically_valid_python():
    """PyInstaller reads this file by evaluating it, so a syntax error would fail the build.

    Compiled rather than executed: the names it calls (`VSVersionInfo`, `FixedFileInfo`, …) live
    in a PyInstaller module that cannot be imported off Windows, so evaluating it here is not
    possible. Compilation still catches the realistic failure — a quoting or escaping mistake in
    the generator's f-string.
    """
    text = version_info.render_version_info("0.1.0", "1a2b3c4")

    compile(text, "version_info.txt", "eval")


def test_the_resource_is_written_where_the_spec_looks_for_it(monkeypatch, tmp_path):
    """`packaging/battery-sim.spec` passes `version_info.txt` to EXE(); the name is a contract."""
    assert version_info.TARGET.name == "version_info.txt"
    assert version_info.TARGET.parent == PACKAGING

    monkeypatch.setattr(version_info, "TARGET", tmp_path / "version_info.txt")
    written = version_info.write_version_info()

    assert written.exists()
    assert "VSVersionInfo(" in written.read_text()
