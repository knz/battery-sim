<!--
Household-facing troubleshooting page (English). Written 2026-08-06, alongside the change that
turned the console off on all three platforms and started writing session logs.

Structure is deliberate and ordered by what a stuck reader needs first: find the log, read the
URL out of it, then attach it to a report. The per-platform paths come first because every other
section depends on the reader having found the folder.

The paths are generated from app/config.py::user_data_dir() — macOS
~/Library/Application Support/BatterySim, Linux $XDG_DATA_HOME/battery-sim (else
~/.local/share/battery-sim), Windows %LOCALAPPDATA%\BatterySim\data. If that function changes,
this page and its Dutch counterpart are wrong and must change with it.

The "what to include in a report" list is deliberately short. A longer list gets skimmed, and the
log file already carries the platform, the frozen flag and the data directory in its header — so
asking for those separately would be asking the reader to retype what they are already attaching.

Note the log covers the LAUNCHER, not the whole app: redirection starts once the data directory
is resolved, so argument-parsing errors and --help still go to the terminal only. That is why the
page says "if the app started at all".

Dutch counterpart: ../nl/probleemoplossing.md.
-->

# When something goes wrong

The app writes a log file every time it starts. If it will not open, opens and does nothing, or
you cannot find the page in your browser, that file is the first place to look — and the most
useful thing to attach to a bug report.

**Go straight to:** [Finding the log](#finding-the-log) · [Finding the address](#finding-the-address) ·
[Reporting a problem](#reporting-a-problem)

## Finding the log

Logs live in a `logs` folder inside the app's data directory. There is one file per launch, named
`session-` followed by the date and time, so the most recent file is the run you just tried.

### macOS

```
~/Library/Application Support/BatterySim/logs/
```

The `Library` folder is hidden by default. In Finder, use **Go → Go to Folder…** (Shift-Cmd-G)
and paste the path above.

### Windows

```
%LOCALAPPDATA%\BatterySim\data\logs\
```

Paste that into the File Explorer address bar exactly as written, including the percent signs —
Windows expands it for you. It usually resolves to
`C:\Users\<your name>\AppData\Local\BatterySim\data\logs\`.

### Linux

```
~/.local/share/battery-sim/logs/
```

If you have set `XDG_DATA_HOME`, it is `$XDG_DATA_HOME/battery-sim/logs/` instead.

Log files are plain text. Any text editor opens them, and they are safe to read — see
[what is in them](#what-is-in-the-log) before you post one publicly.

## Finding the address

The app runs a small web server on your own machine and shows it in a window. When the window
does not appear, the server is often running anyway — you just need its address.

Open the newest log file and look for a line like:

```
Home Battery Simulator on http://127.0.0.1:8137/
```

Type that address into your browser and you should get the app. The port number is usually 8137
but changes if something else on your machine already holds that port, which is exactly why
reading it from the log is more reliable than guessing.

Two other lines worth knowing when you see them:

- **`Home Battery Simulator is already running at …`** — a copy is open. Use the address given,
  or close the other one first.
- **A line mentioning a fallback or a window that could not open** — the app could not draw its
  own window and fell back to your browser. The app still works; the address is in the same log.

## Reporting a problem

Please include:

1. **The log file** from the run that went wrong — attach it, or paste its contents.
2. **What you did** and what you expected instead.
3. **Which download you used** — the filename, or the release you took it from.

You do not need to list your operating system or where your data lives separately: the top of
every log file records the platform and the data directory already.

Report at [github.com/knz/battery-sim/issues](https://github.com/knz/battery-sim/issues). Dutch
or English, whichever you prefer.

### What is in the log

The log holds the app's own start-up messages: the address it is serving, whether another copy
was already running, and the reason a window did not open. It does **not** contain your energy
data, your prices, or any Home Assistant token.

It does contain **the path to your data directory**, which normally includes your username. If
that matters to you, replace it with something else before posting — nothing in a bug report
depends on the real name.

### Older logs

Files older than three months are deleted automatically the next time the app starts. Nothing
else in the data directory is touched. If you want to keep a log, copy it somewhere else.

## If there is no log at all

An empty or missing `logs` folder means the app stopped before it got that far. That is a real
result and worth reporting as-is — say that the folder was empty, and note whether the data
directory itself exists.

Running the app from a terminal will usually print the reason it stopped, and that output is the
most useful thing to include in this case. On Windows, open PowerShell in the folder you unpacked
and run `.\battery-sim.exe`; on macOS or Linux, run the app from a terminal the same way.

## Related

- [Installing and running](install.md)
- [Security warnings when you open the app](security-warnings.md)
