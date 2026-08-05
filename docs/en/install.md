<!--
Household-facing install page (English). Covers the Linux AppImage, which is the only
platform with a produced build; states plainly that macOS and Windows builds do not exist
yet. Deliberately does NOT document running from source — that is the top-level README's
job, and pointing a household at `uv` invites them to install a Python toolchain they do
not need. The download URL points to the GitHub releases page, which currently has no release.
Dutch counterpart: ../nl/installatie.md.
-->

# Installing and running the Home Battery Simulator

The app runs on your own computer. It reads your Home Assistant data or your CSV exports,
does its calculation locally, and shows you the result in a window. Nothing is uploaded, and
the app does not phone home.

## What you need

- A computer running Linux (see [Which platforms exist](#which-platforms-exist) below).
- Your household's own electricity data — either a Home Assistant instance you can reach on
  your home network, or CSV exports from it.

You do **not** need to install Python, Node, or anything else. The download contains
everything the app needs.

## Which platforms exist

| Platform | Status |
| --- | --- |
| **Linux** (64-bit x86) | A working build exists: a single AppImage file. |
| **macOS** | **No build yet.** |
| **Windows** | **No build yet.** |

Only the Linux build has been produced and tested. macOS and Windows are intended but not
built, so there is currently nothing to download for them. If you are on one of those, the
[security-warnings page](security-warnings.md) describes what you will run into when builds
do appear — it is written as advance notice, not as instructions for something you can do
today.

## Linux: download and run

The Linux build is an **AppImage**: one file that contains the whole application. There is no
installer, no package manager, and nothing is written into your system directories. To remove
the app, delete the file.

**1. Download the AppImage.**

> Releases are published at https://github.com/knz/battery-sim/releases. No release has been
> published yet, but when one is, the file will be named `Home-Battery-Simulator-x86_64.AppImage`
> and you can download it from there.

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

### If the window does not open

The app falls back to opening in your normal web browser instead, and prints a line saying so.
It works the same way there. This happens when the graphics libraries the window needs cannot
be loaded on your system.

You can also ask for the browser deliberately:

```
./Home-Battery-Simulator-x86_64.AppImage --browser
```

### One message you can ignore

On startup you may see this on the terminal:

```
GStreamer element appsink not found. Please install it.
```

This is harmless and does not need fixing. It comes from the browser engine bundled inside the
app, which checks at startup for a video-playback component. The app has no video or audio, so
nothing is missing from your point of view. It has been investigated and cannot be removed
without bundling a media library the app never uses; see
`changelog/20260805-desktop-packaging.md` §16 if you want the detail.

### System requirements

The Linux build is compiled against glibc 2.39, so it needs a distribution of roughly Ubuntu
24.04 vintage or newer. On Debian 12 or older it will not start. It needs an X11 or Wayland
desktop session; it will not run on a headless server.

## Where the app keeps your data

Under `~/.local/share/battery-sim` — your workspaces, your settings, and your Home Assistant
token if you entered one. Your energy data never leaves your machine.

The Home Assistant token is stored on disk, deliberately, so that you do not have to type it
in again each time you open the app. If that is not what you want, delete that directory; the
app recreates an empty one on the next start.

## Next

- [The security warnings your operating system shows](security-warnings.md)
- [Supporting the project](sponsor.md) — what code signing would cost, and what it would fix
