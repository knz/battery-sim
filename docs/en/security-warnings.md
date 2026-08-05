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

Tone constraint: this page must not read as "click through the scary dialog".
Dutch counterpart: ../nl/beveiligingswaarschuwingen.md.
-->

# Security warnings when you open the app

The app is not code-signed, so macOS and Windows warn you the first time you open it. Find your
platform below.

**Go straight to your platform:** [Linux](#linux) · [macOS](#macos) · [Windows](#windows) —
or read [why these warnings appear](#why).

## Linux

**What you see:** nothing. There is no warning and no confirmation.

Once you have made the AppImage executable with `chmod +x`, it just runs. See
[Installing and running](install.md).

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

That cuts both ways, and the warning is doing a real job. Apple's own page says overriding it is
the most common way a Mac gets infected with malware, which is fair: most people who click past
that dialog do so for a program they know nothing about. The reason to proceed here is not that
the warning is a nuisance, but that you can check the provenance yourself — you know where you
downloaded the file, the source code is public, and you can build it yourself if you would
rather not trust a download at all.

**Linux has no gate** because it distributes software differently: trust normally comes from
your distribution's package repositories, which are signed as a whole, rather than from
per-file stamps on web downloads. A file you fetched yourself is your own responsibility.

**On macOS the path keeps narrowing.** The right-click override is gone, the button moved into
System Settings, it expires after about an hour, and it now asks for your password. Expect
further tightening — on macOS a signature is closer to required than to nice to have, which is
the strongest argument for [funding one](sponsor.md).

**On Windows it fades on its own.** Per Microsoft's developer documentation, SmartScreen weighs
whether the file is signed by a publisher it recognises and whether this exact file has been
downloaded by enough people without trouble. An unsigned file starts at zero on both, and
because reputation attaches to the exact file, every new release starts from zero again. So the
warning softens as a release circulates and returns with the next one.

[Why the app is unsigned, and what changing that would cost](sponsor.md).

*Checked against vendor documentation on 2026-08-05: Apple's Mac User Guide entry "Open a Mac
app from an unidentified developer", and Microsoft Learn's "SmartScreen reputation for Windows
app developers". These behaviours change between OS releases. If your screen does not match what
is written here, those two pages are the places to check, and please report the difference so
this page can be corrected.*

</details>
