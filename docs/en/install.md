<!--
Household-facing install page (English). Covers all three platforms: the Linux AppImage, and
the macOS and Windows bundles produced by .github/workflows/release.yml. Deliberately does NOT
document running from source — that is docs/maintainers/'s job, and pointing a household at
`uv` invites them to install a Python toolchain they do not need. Download URLs point at the
GitHub releases page. Dutch counterpart: ../nl/installatie.md.
-->

# Installing and running the Home Battery Simulator

The app runs on your own computer. It reads your Home Assistant data or your CSV exports,
does its calculation locally, and shows you the result in a window. Nothing is uploaded, and
the app does not phone home.

**Go straight to your platform:** [Linux](#linux-download-and-run) ·
[macOS](#macos-download-and-run) · [Windows](#windows-download-and-run)

On this page:

- [What you need](#what-you-need)
- [Which platforms exist](#which-platforms-exist)
- [Linux: download and run](#linux-download-and-run)
- [macOS: download and run](#macos-download-and-run)
- [Windows: download and run](#windows-download-and-run)
- [If the window does not open](#if-the-window-does-not-open)
- [One message you can ignore](#one-message-you-can-ignore)
- [Where the app keeps your data](#where-the-app-keeps-your-data)

## What you need

- A computer running Linux, macOS or Windows (see [Which platforms
  exist](#which-platforms-exist) below).
- Your household's own electricity data — either a Home Assistant instance you can reach on
  your home network, or CSV exports from it.

You do **not** need to install Python, Node, or anything else. The download contains
everything the app needs.

## Which platforms exist

| Platform | Download |
| --- | --- |
| **Linux** (64-bit x86) | `Home-Battery-Simulator-x86_64.AppImage` — a single file |
| **macOS** (Apple silicon) | `battery-sim-macos-arm64.zip` |
| **macOS** (Intel) | `battery-sim-macos-x86_64.zip` |
| **Windows** (64-bit x86) | `battery-sim-windows-x86_64.zip` |

All builds are published at https://github.com/knz/battery-sim/releases. Pick the one matching
your machine; on macOS, Apple silicon means an M-series Mac, and Intel means a Mac from before
that changeover.

None of the builds is signed, so macOS and Windows will both show a warning the first time you
open the app. That is expected, it is not a sign that anything is wrong, and the
[security-warnings page](security-warnings.md) walks through exactly what you will see and how
to get past it.

## Linux: download and run

The Linux build is an **AppImage**: one file that contains the whole application. There is no
installer, no package manager, and nothing is written into your system directories. To remove
the app, delete the file.

**1. Download `Home-Battery-Simulator-x86_64.AppImage`** from the
[releases page](https://github.com/knz/battery-sim/releases).

**2. Make it executable.** A downloaded file is not allowed to run until you say it may. In a
terminal, in the directory you downloaded it to:

```
chmod +x Home-Battery-Simulator-x86_64.AppImage
```

You can also do this without a terminal, in most file managers: right-click the file →
Properties → Permissions → tick "Allow executing file as program" (the exact wording varies
between desktops).

**3. Run it.**

```
./Home-Battery-Simulator-x86_64.AppImage
```

Or double-click it in your file manager. A window titled **Home Battery Simulator** opens.

That is the whole procedure. Linux shows no security warning and asks for no confirmation —
see [the security-warnings page](security-warnings.md) for why that differs from macOS and
Windows.

### System requirements

The Linux build is compiled against glibc 2.39, so it needs a distribution of roughly Ubuntu
24.04 vintage or newer. On Debian 12 or older it will not start. It needs an X11 or Wayland
desktop session; it will not run on a headless server.

## macOS: download and run

**1. Download the zip for your Mac** from the
[releases page](https://github.com/knz/battery-sim/releases) —
`battery-sim-macos-arm64.zip` for Apple silicon, `battery-sim-macos-x86_64.zip` for Intel. If
you are unsure which you have:  → About This Mac.

**2. Unpack it.** Double-click the downloaded zip. You get a folder named `battery-sim`. Move
it wherever you keep your applications; everything the app needs is inside that folder, so it
can live anywhere and is removed by deleting it.

**3. Open the app.** Inside the folder, open the `battery-sim` launcher.

macOS will refuse the first attempt, because the app is not signed. This is the expected
first-run behaviour and the [security-warnings page](security-warnings.md) has the steps: in
short, System Settings → Privacy & Security → scroll to Security → **Open Anyway**, then open
the app a second time. You only do this once.

## Windows: download and run

**1. Download `battery-sim-windows-x86_64.zip`** from the
[releases page](https://github.com/knz/battery-sim/releases).

**2. Unpack it.** Right-click the downloaded zip → **Extract All**. You get a folder named
`battery-sim`. Move it wherever you like; everything the app needs is inside it, and removing
the app means deleting the folder.

**3. Open the app.** Inside the folder, run `battery-sim.exe`.

Windows will show a blue **"Windows protected your PC"** box, because the app is not signed.
Click **More info**, then **Run anyway**. The
[security-warnings page](security-warnings.md) explains what that warning is actually
measuring. A console window opens alongside the app window; it belongs to the app and can be
ignored, but closing it closes the app.

## If the window does not open

On any platform, the app falls back to opening in your normal web browser instead, and prints a
line saying so. It works the same way there. This happens when the graphics libraries the
window needs cannot be loaded on your system.

You can also ask for the browser deliberately, by passing `--browser` — for example, on Linux:

```
./Home-Battery-Simulator-x86_64.AppImage --browser
```

## One message you can ignore

On Linux, on startup, you may see this on the terminal:

```
GStreamer element appsink not found. Please install it.
```

This is harmless and does not need fixing. It comes from the browser engine bundled inside the
app, which checks at startup for a video-playback component. The app has no video or audio, so
nothing is missing from your point of view. It has been investigated and cannot be removed
without bundling a media library the app never uses; see
`changelog/20260805-desktop-packaging.md` §16 if you want the detail.

## Where the app keeps your data

Your workspaces, your settings, and your Home Assistant token if you entered one:

| Platform | Location |
| --- | --- |
| **Linux** | `~/.local/share/battery-sim` |
| **macOS** | `~/Library/Application Support/BatterySim` |
| **Windows** | `%LOCALAPPDATA%\BatterySim\data` |

Your energy data never leaves your machine.

The Home Assistant token is stored on disk, deliberately, so that you do not have to type it
in again each time you open the app. If that is not what you want, delete that directory; the
app recreates an empty one on the next start.

## Next

- [The security warnings your operating system shows](security-warnings.md)
- [Supporting the project](sponsor.md) — what code signing would cost, and what it would fix
