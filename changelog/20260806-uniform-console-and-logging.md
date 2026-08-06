# Uniform console behaviour and session logging across all three platforms

## Task specification

The user asked for uniform behaviour across the Linux, macOS and Windows builds:

1. Redirect stdout/stderr to files in the application's data directory, so they can be picked up
   for debugging.
2. Actually disable the console on all three platforms.
3. Keep the existing fallback that shows the server URL in a native control when the webview
   cannot open, and see whether equivalent work helps the other platforms.

Added mid-conversation:

4. A troubleshooting doc page, with Dutch translation, covering: where the application directory
   is on each platform, where to find the server URL in the log, and what to include in bug
   reports.
5. Check the issue templates and cross-reference the new doc where relevant.

### Answers given to the clarifying questions

| question | answer |
|---|---|
| Log rotation | Timestamped file per launch, prune old, keep 3 months |
| One file or two | One file, stdout and stderr interleaved |
| Windows console flip | Flip now; the user will verify on Windows later, trusting output to file |
| Keep stderr on a TTY | Tee to both when a TTY is present |

## Finding that preceded the plan: the tkinter fallback is currently dead on Linux

`packaging/battery-sim.spec:215-224` records that `tkinter` was deliberately **un-excluded** so
`_show_fallback_dialog` works, with the size cost measured (Windows artifact 33,556,296 →
36,608,686 bytes). That reasoning is sound but rests on tkinter being importable at build time,
and it is not:

```
python3 -c "import tkinter"                 → ModuleNotFoundError
uv run --no-sync python -c "import tkinter" → ModuleNotFoundError
```

PyInstaller bundles what it can import. With no tkinter in the build environment, the dialog takes
its `ImportError` branch and returns `False` — silently, on exactly the machines it exists for,
which is the outcome the spec comment was written to prevent.

This does not block the work; it strengthens the case for it. With `console=False` the log file
becomes the only diagnostic channel whenever the dialog cannot draw. Whether the macOS/Windows
runners' uv-provided Python carries tkinter is a separate question, checked during implementation
rather than assumed.

## High-level decisions

### D1 — One timestamped file per launch, pruned at 90 days

Chosen by the user over overwrite-per-launch and size-capped rotation. Consequence to keep in
view: a user who launches the app many times accumulates many small files. Pruning is by mtime
against a 90-day cutoff, not by count, so a burst of launches inside the window is retained.

The prune glob is scoped strictly to `session-*.log` **inside the app's own `logs/` directory**.
Deletion is the one genuinely destructive operation in this change, and a loose glob over the data
directory could take user data with it.

### D2 — `console=False` unconditionally, and what that does not mean on Linux

`console=` is a PE/Mach-O subsystem flag. PyInstaller ignores it on Linux entirely: an AppImage
launched from a file manager has no terminal, and launched from a shell it inherits that shell's
streams. There is no console to disable there.

So "disable the console on all three platforms" is precisely: macOS already done, Windows flipped
here, Linux not applicable. **Uniformity comes from the log file, not from this flag.** Recorded
because the spec comment currently explains why Windows *keeps* its console, which this change
makes wrong.

### D3 — Logging must not be able to break the launcher

Every failure path in the redirect is survivable and returns quietly: an unwritable data
directory, a full disk, a permission error. A launcher that dies because it could not open its own
log file is worse than one with no log. This mirrors the reasoning already applied to
`_show_fallback_dialog`, which returns a boolean rather than raising for the same reason.

### D4 — The `None`-stream guard is kept and now runs first

`_ensure_std_streams()` exists because a windowed frozen build can start with `sys.stdout` and
`sys.stderr` as `None`. That was insurance while Windows kept `console=True`; with D2 it becomes
load-bearing on a real shipping configuration. It must run before any write and before the tee is
constructed, since the tee wraps whatever the original stream is.

### D5 — Ordering: logging starts after the data directory is resolved

An ordering constraint found by reading, not assumed: `_ensure_std_streams()` is called in
`main()` (desktop.py:939) but `resolve_data_dir()` runs later, inside `run()` (desktop.py:776).
The log file's path depends on the data directory, so redirection cannot begin at the top of
`main()` where the stream guard sits.

Resolution: keep the `None` guard first in `main()`, and start file logging immediately after the
data directory is resolved. The cost is that anything printed before that point — argument parsing
errors, `--help` — does not reach the file. Accepted: those are terminal-invoked paths, where a
console is present anyway.

### D6 — The fallback dialog's code is unchanged

It is already shared across all three platforms and already correct. The useful work is making
tkinter actually present in the build environments and verifying the dialog renders. Editing
working code would add risk without adding function.

## The tkinter finding, confirmed against CI and narrowed to Linux

The local import check that opened this work was ambiguous evidence — and it turned out the local
machine's state changed mid-session (`python3-tk` was installed by something outside this session,
after the first probe and before a later one, which is why the same command gave two answers).
Local state was therefore not a sound basis for the conclusion.

CI logs settled it independently. From run 31094839305:

| job | evidence | fallback dialog |
|---|---|---|
| Linux AppImage | `WARNING: tkinter installation is broken. It will be excluded from the application` | **absent** |
| Windows | `hook-_tkinter`, `pyi_rth__tkinter`, no warning | present |
| macOS arm64 | `hook-_tkinter`, `pyi_rth__tkinter`, no warning | present |
| macOS x86_64 | `hook-_tkinter`, `pyi_rth__tkinter`, no warning | present |

So this was **Linux-only**, and every AppImage built before 2026-08-06 shipped without the
fallback dialog. Silently: the function's `ImportError` branch returns False, which is
indistinguishable from the dialog being declined.

Also confirmed from the same run's log that the AppImage build resolves `uv venv --python 3.12`
to `/usr/bin/python3.12`. That is what makes `python3-tk` the correct fix — tkinter is a C
extension against the system Tcl/Tk, not a PyPI package, and a uv-managed standalone interpreter
would not have been helped by it.

### D7 — Warn locally, install in CI

CI gets the apt package. `build-linux.sh` gets a **warning, not a hard failure**: the dialog is
itself a fallback, the browser still opens without it, and a hard stop would block someone
building on a machine with no Tk headers. This is deliberately weaker than the adjacent `_gi` ABI
gate, which stays fatal because that one produces a broken import at the user's launch rather
than a missing nicety.

Verified by simulating a Python that cannot import tkinter: the warning fires when absent, and is
silent when present.

## Files modified

- `changelog/20260806-uniform-console-and-logging.md` — this file (new).
- `app/desktop.py` — `start_session_log()`, `_Tee`, `_prune_old_logs()`; called from `run()` right
  after the data directory resolves. `_ensure_std_streams` retained and still runs first.
- `packaging/battery-sim.spec` — `console=False`; rewritten comment block; corrected the
  un-exclude note, whose Linux size figure was measuring a bundle that never contained tkinter.
- `packaging/build-linux.sh` — tkinter warning after the build venv is created.
- `.github/workflows/release.yml` — `python3-tk` added to the Linux job's apt list.
- `docs/en/troubleshooting.md`, `docs/nl/probleemoplossing.md` — new pages.
- `docs/en/install.md`, `docs/nl/installatie.md`, `docs/README.md`, `README.md` — cross-links.
- `.github/ISSUE_TEMPLATE/broken.md` — the "terminal or console window" question replaced with a
  request for the log file, including the per-platform paths and the privacy note.
- `tests/test_desktop.py` — 9 new tests.
- `tests/test_packaging_metadata.py` — the console assertion inverted; a new test pairing
  `console=False` with the existence of the logging, since those are one decision.

## Verification

- **Full suite: 1432 passed, 25 skipped** (1390 + 42 browser smoke tests, run separately).
- **End-to-end, real launch**: `session-20260806-132438.log` was created under `<data_dir>/logs/`
  containing the header, the platform, the data directory and
  `Home Battery Simulator on http://127.0.0.1:8137/` — the exact line the troubleshooting page
  tells users to look for.
- **Documented paths checked against `config.user_data_dir()`** rather than transcribed: all three
  match.
- **The tkinter warning** fires on a simulated missing interpreter and is silent on a real one.

Not verified: the Windows console flip on a real Windows machine (the user has said they will
check later), and the fallback dialog rendering on any platform.

## Obstacles and solutions

- **tkinter absent from the Linux build** — confirmed via CI logs after local state proved
  unreliable; fixed with `python3-tk` in CI plus a local warning. See D7.
- **Local machine state changed mid-session** — `python3-tk` appeared between two probes. Resolved
  by relying on CI logs, which are reproducible, rather than on this machine.
- **A test asserted the old console behaviour** — `test_the_console_is_off_on_macos_only` failed as
  designed and was replaced.
- **Stream guard and data directory ordering** — see D5.

## Current status

Complete. All the requested pieces are done: stream redirection to per-launch files with 90-day
pruning, console off everywhere it has meaning, the fallback dialog kept and now actually present
on Linux, troubleshooting pages in both languages, and the issue template cross-referenced.
