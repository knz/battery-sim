<!--
Household-facing explanation of the per-platform security gates (English). Structure is
deliberate: one section per platform, each "what you see" then "what to do", with all
explanation folded into a single collapsed <details> at the end. A reader hitting a dialog
wants the steps, not the reasoning.

Three things that look like explanation are kept OUT of the fold because they are steps: the
macOS failed-attempt precondition and the ~1 hour expiry, the Windows Unblock fallback, and
Smart App Control (the one case with no way through).

Verified 2026-08-05 against: Apple's Mac User Guide "Open a Mac app from an unidentified
developer" (the System Settings path, the password prompt, the ~1 hour window on the Open
Anyway button); Microsoft Learn "SmartScreen reputation for Windows app developers", page
dated 2026-05 (that signing does NOT remove the first-download warning, that EV no longer
bypasses SmartScreen, and Smart App Control's harder gate). Linux is from this repo's own
phase 4-6 verification rather than a vendor page.

The macOS and Windows steps are written from those vendor pages, NOT from observing the
project's own builds on those systems — the release jobs for both are new. Treat a reader's
report of different on-screen wording as more authoritative than this page.

The fold deliberately holds only what a signature is and what the check does not prove, ending
on the sponsor pointer. Earlier drafts also carried the per-platform reasoning and the sourcing
note above; both were cut for length. The sourcing above is now the only record of where these
claims come from, so keep it current when the steps change.

Tone constraint: this page must not read as "click through the scary dialog".
Dutch counterpart: ../nl/beveiligingswaarschuwingen.md.
-->

# Security warnings when you open the app

The app is not code-signed, so macOS and Windows warn you the first time you open it. On Linux
there is no warning and nothing to do. For the download and unpacking steps themselves, see
[Installing and running](install.md).

**Go straight to your platform:** [macOS](#macos) · [Windows](#windows) — or read
[why these warnings appear](#why).

## macOS

**What you see:** a dialog saying the app cannot be opened because it is from an unidentified
developer, or that Apple could not verify it is free of malware. The only buttons are along the
lines of **Done** and **Move to Trash** — there is no "Open Anyway" here.

Right-clicking the app and choosing **Open**, which many older guides still describe, no longer
works. Apple removed it in macOS 15.

**What to do:**

1. **Try to open the app and dismiss the refusal.** Do not skip this — the button in step 3
   only appears after macOS has recorded a blocked attempt.
2. Open **System Settings** → **Privacy & Security**, and scroll to the **Security** section.
3. Find the line naming the app and click **Open Anyway**. It is offered for only *about an
   hour* after the blocked attempt; if the line is not there, go back to step 1.
4. **Enter your login password** and confirm.

You only do this once. Note that this override is the usual way a Mac picks up malware, so it
is only a reasonable thing to do because you know where you downloaded this file from — if you
cannot account for where your copy came from, do not open it.

## Windows

**What you see:** a blue Microsoft Defender SmartScreen window, **"Windows protected your PC"**,
saying it prevented an unrecognized app from starting. The only visible button is **Don't run**.

**What to do:** click the small **More info** link above the button, then click **Run anyway**.
No password, no settings, no time limit.

If **Run anyway** does not appear, the file may still be marked as blocked: right-click it →
**Properties** → tick **Unblock** at the bottom of the General tab → **OK**, then try again.

One case has no way through: **Smart App Control**, on by default on clean installs of Windows
11, blocks unsigned programs outright and offers no "Run anyway". There is no workaround short
of the app being signed.

## Why

<details>
<summary>What these warnings are actually checking</summary>

macOS and Windows prefer applications carrying a **code signature**: a cryptographic stamp
bought from Apple or a certificate authority, tying the file to an identity they have checked.
This app is unsigned, so the warnings say, in effect, *this program does not come with a
signature, so I cannot tell you who made it*.

They do **not** say the app was examined and found harmful. The check is about provenance, not
content — an unsigned honest program and an unsigned harmful one look identical to these
systems, which is why they warn rather than decide.

To remove the security warnings, consider [sponsoring the project](sponsor.md).

</details>
