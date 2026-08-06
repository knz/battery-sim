---
name: Something is broken
about: The app does not start, or does something it should not
title: ''
labels: bug
---

<!--
Reported from the "Report what breaks" item on docs/en/sponsor.md and docs/nl/sponsor.md.
Answer in Dutch or English, whichever you prefer.
-->

**Which platform?**

<!-- Linux (and which distribution), macOS (Apple silicon or Intel), or Windows. -->

**Which version of the app?**

<!-- The filename you downloaded, or the release you took it from. -->

**What happened?**

**What did you expect to happen instead?**

**The log file from the run that went wrong**

<!--
Attach it, or paste the contents. The app writes one file per launch and it is the single most
useful thing in a report of this kind.

Where to find it — docs/en/troubleshooting.md and docs/nl/probleemoplossing.md have the full
steps, including how to read the app's address out of it:

  macOS    ~/Library/Application Support/BatterySim/logs/
  Windows  %LOCALAPPDATA%\BatterySim\data\logs\
  Linux    ~/.local/share/battery-sim/logs/

The newest `session-*.log` is the run you just tried. It contains no energy data, no prices and
no Home Assistant token — but it does contain the path to your data directory, which usually
includes your username. Feel free to replace that before posting.

If there is no logs folder at all, say so: it means the app stopped before it got that far,
which is itself useful. Running the app from a terminal will usually print the reason.
-->
