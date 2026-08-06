# Windows build: ship the tzdata package

## Task Specification

The Windows job of the Release workflow failed. The user reported it as "a timezone-related
error" and asked for it to be checked, then to be fixed as a separate commit on the
`worktree-network-troubleshooting` branch (which is about backend TLS — see
`changelog/20260806-backend-tls-system-trust.md`; the two are unrelated beyond sharing a branch).

## Investigation

Release run 31123841713, job "Windows (unfinished)" (id 92694463006), step "Build the onedir
bundle". PyInstaller never got as far as analysing anything — the spec file itself raised:

    File "packaging/battery-sim.spec", line 134, in <module>
      BABEL_LOCALE_KEEP = babel_locale_keep_set()
    File "packaging/battery_sim_babel_locales.py", line 56, in babel_locale_keep_set
      from app.i18n import DEFAULT_LOCALE, SUPPORTED
    File "app/i18n.py", line 360, in <module>
      DISPLAY_TZ = ZoneInfo("Europe/Amsterdam")
    zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key Europe/Amsterdam'

with a `ModuleNotFoundError: No module named 'tzdata'` as the cause.

The mechanism: `zoneinfo` resolves a key by looking first at the system tz database (the
directories in `zoneinfo.TZPATH` — `/usr/share/zoneinfo` and friends), and only then at the
`tzdata` PyPI package as a fallback. Linux and macOS ship that database with the OS. Windows does
not ship one at all, so on Windows the `tzdata` package is the ONLY source. It is not in
`pyproject.toml`, so `uv sync --no-dev` in the build job installed nothing to fall back to.

Confirmed locally that this is the mechanism and not a coincidence: `tzdata` is absent from this
checkout's environment too (`uv run python -c "import tzdata"` → ModuleNotFoundError), and
`zoneinfo.TZPATH` points at `/usr/share/zoneinfo`. Linux passes on the OS files alone.

**Not caused by this branch.** `DISPLAY_TZ` was introduced by `bf562f5` ("Build the Energy flows
chart tab in panel 3"), inside PR #16, already merged to master. The last green Release run was
31098778566 at `5837bb8`, and `git merge-base --is-ancestor bf562f5 5837bb8` is false — i.e. the
Windows build has been broken for every commit since PR #16 merged. Same origin as the app.css
drift fixed in the preceding commit on this branch.

## High-Level Decisions

**Add `tzdata` as an unconditional runtime dependency, and change nothing in the spec.**

Two gaps had to be closed, and it was worth checking they were not the same one:

1. *Build time* — the spec imports `app.i18n` on the build machine, so `tzdata` must be installed
   in the build environment. `uv sync --no-dev` installs `[project.dependencies]`, so listing it
   there is sufficient.
2. *Runtime* — a user's Windows machine has no system database either, so the bundle must CARRY
   the data. Fixing (1) does not imply (2): the dependency being installed on the builder says
   nothing about PyInstaller collecting its data files.

(2) turns out to need no work, which was verified rather than assumed. PyInstaller 6.21.0's
contrib hooks (2026.6, the version the workflow pins) include both halves:

- `_pyinstaller_hooks_contrib/stdhooks/hook-zoneinfo.py` — `if is_win: hiddenimports = ['tzdata']`.
  `zoneinfo` never imports `tzdata` by name, so static analysis would otherwise miss it; this hook
  is exactly the Windows-only bridge.
- `_pyinstaller_hooks_contrib/stdhooks/hook-tzdata.py` — `collect_data_files("tzdata")` plus
  `collect_submodules("tzdata")`, the latter because each zone directory is a package whose
  `__init__.py` `importlib.resources` needs to find the data through.

So `packaging/battery-sim.spec` needs no new `HIDDENIMPORTS` or `DATAS` entry. Adding one would
duplicate what the hooks already do.

## Rationales and Alternatives

**Unconditional, not `; sys_platform == 'win32'`.** A marker would express the platform fact
precisely and keep 2.6 MB out of the Linux and macOS environments. Rejected on balance: an
unconditional dependency means every developer and every CI job resolves the same lock entry, so
`zoneinfo` behaves identically everywhere and a machine with an incomplete or absent system tz
database (a slim container, a stripped image) is covered too. The cost is small and bounded —
2.6 MB installed, against the 150 MB bundle ceiling in `packaging/build-linux.sh` — and on the
platforms that do not need it the `hook-zoneinfo` guard means it is not even collected into the
bundle. If the size ever matters, the marker is a one-line change.

**Not vendoring or pinning the tz database.** `tzdata` tracks IANA releases and the app displays
Europe/Amsterdam wall-clock times including DST transitions; a stale pinned copy would silently
misplace times after a future rule change. A floating lower bound is right here.

**Not moving `DISPLAY_TZ` to a lazy lookup.** Deferring the `ZoneInfo(...)` call would make the
spec import succeed without the package, fixing the build error alone — and leaving the runtime
failure in place on Windows, differently disguised. It also treats a module-level constant as the
problem when the missing data is the problem.

## Files Modified

- `pyproject.toml` — `tzdata>=2026.3` added to `[project.dependencies]`, with a comment recording
  that Windows has no system tz database and that the PyInstaller hooks do the bundling.
- `uv.lock` — one new entry, `tzdata 2026.3`.
- `THIRD-PARTY-NOTICES.md` — regenerated; one row added.
- `tests/test_packaging_metadata.py` — one test asserting `tzdata` is a declared runtime
  dependency, so removing it fails a fast test rather than only a Windows build.

## Obstacles and Solutions

- PyInstaller is not a project dependency (the workflow installs it with `uv pip install` at a
  pinned version), so its hooks could not be inspected from this checkout — installed
  `pyinstaller==6.21.0` into a scratch venv to read `hook-zoneinfo.py` and `hook-tzdata.py`
  directly rather than assuming what they do.

## Current Status

Committed on `worktree-network-troubleshooting`, separately from the TLS work.

Later cherry-picked onto `worktree-fixes` (as 90cd91c) to ship independently of that
branch — see [20260807-assembled-fixes.md](20260807-assembled-fixes.md). The TLS
references above describe where the work was written, not what ships with it: only the
tzdata half was carried across.

Verified:

- the failure mechanism, from the CI traceback and from reproducing the missing-`tzdata` /
  system-database split locally;
- that the regression predates this branch, by locating `DISPLAY_TZ`'s introducing commit and
  showing it is not an ancestor of the last green Release build;
- that PyInstaller 6.21.0 + contrib 2026.6 carry hooks which add `tzdata` as a Windows hidden
  import and collect its data files and submodules — read from the installed hook sources.

Not verified:

- **that the Windows build now succeeds.** It needs a Release run; nothing local exercises the
  Windows path.
- that the built Windows app resolves `Europe/Amsterdam` at RUNTIME. The hooks say it should, but
  this is the same class of claim as the `truststore` `hiddenimports` in the TLS work — reasoned
  from hook sources, not observed in a bundle.
- macOS and Linux are unaffected in practice; they resolve through the system database as before,
  and the new package is installed but unused there.

### Possible follow-ups (not decided)

- `tests/test_packaged.py` drives a built binary and could assert that a formatted wall-clock time
  comes back in Europe/Amsterdam, which would turn the runtime claim above into an observed one.
  That only helps on a Windows runner, where that suite does not currently run.
- The Windows build being red since PR #16 went unnoticed because the Release workflow is
  dispatch-only. Whether it should run on pushes to master, or on a schedule, is a separate
  question about CI policy rather than about this bug.
