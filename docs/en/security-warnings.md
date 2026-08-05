<!--
Household-facing explanation of the per-platform security gates (English). Every factual
claim traces to a vendor page, named inline, because these behaviours change between OS
releases and a reader hitting something different needs to know where to check.

Verified 2026-08-05 against: Apple's Mac User Guide "Open a Mac app from an unidentified
developer" (the System Settings path, the password prompt, the ~1 hour window on the Open
Anyway button); Microsoft Learn "SmartScreen reputation for Windows app developers", page
dated 2026-05 (that signing does NOT remove the first-download warning, that EV no longer
bypasses SmartScreen, and Smart App Control's harder gate). Linux is from this repo's own
phase 4-6 verification rather than a vendor page.

The macOS and Windows steps are written from those vendor pages, NOT from observing the
project's own builds on those systems — the release jobs for both are new. Treat a reader's
report of different on-screen wording as more authoritative than this page.

Tone constraint: this page must not read as "click through the scary dialog". It says what
the gate is for, what it does and does not know, and then the steps.
Dutch counterpart: ../nl/beveiligingswaarschuwingen.md.
-->

# The security warnings your operating system shows

Depending on which system you run, downloading and opening this app may produce a warning
before it will start. This page explains what those warnings are checking, what they do and do
not tell you, and how to get past them.

## What "unsigned" means

macOS and Windows both prefer applications that carry a **code signature**: a cryptographic
stamp bought from Apple or from a certificate authority, which ties the file to an identity
they have checked. The system can then confirm two things — that the file comes from that
identity, and that nobody has altered it since.

This app is **unsigned**. Nobody has paid for that stamp. So the warnings you see say, in
effect:

> *This program does not come with a signature, so I cannot tell you who made it.*

They do **not** say the app was examined and found harmful. The check is about provenance,
not about content. An unsigned honest program and an unsigned harmful one look identical to
these systems, which is exactly why they warn rather than decide.

That cuts both ways, and it is worth being straight about it: the warning is doing a real job.
The reason to proceed here is not that the warning is a nuisance, but that you can check the
provenance yourself — you know where you downloaded the file from, the source code is public,
and you can build it yourself if you would rather not trust a download at all. If you cannot
account for where your copy came from, the right answer is to not open it.

[Why the app is unsigned, and what changing that would cost](sponsor.md).

## Linux: no gate at all

Linux does not check signatures on downloaded programs. Once you have marked the AppImage
executable with `chmod +x`, it simply runs. No dialog, no confirmation, no settings to change.

This is genuinely the easiest of the three platforms. See [Installing and running](install.md).

The reason is not that Linux is less careful, but that it distributes software differently:
trust normally comes from your distribution's package repositories, which are signed as a
whole, rather than from per-file stamps on downloads from the web. A file you fetched yourself
is treated as your own responsibility.

## macOS: the hardest of the three

When you download a file with a browser, macOS attaches a *quarantine* marker to it. On first
open, Gatekeeper inspects the marked file, finds no signature, and refuses.

### What you see

A dialog saying the app cannot be opened because it is from an unidentified developer, or that
Apple could not verify it is free of malware. The only obvious buttons are along the lines of
**Done** and **Move to Trash**. There is no "Open Anyway" here, and no way to proceed from
this dialog.

Right-clicking the app and choosing **Open** — the workaround many older guides still
describe — **no longer works**. Apple removed it in macOS 15 (Sequoia) and it has not come
back in macOS 26 (Tahoe).

### How to proceed

Apple documents the route in its Mac User Guide, under *"Open a Mac app from an unidentified
developer"*:

1. **Try to open the app first**, and dismiss the refusal dialog. This step is not optional —
   the option in step 3 only appears once macOS has recorded a blocked attempt.
2. Open **System Settings** → **Privacy & Security**, and scroll down to the **Security**
   section.
3. You should see a line naming the app, saying it was blocked because it is not from an
   identified developer. Click **Open Anyway**.
4. **Enter your login password** when asked, and confirm.

**There is a time limit.** Apple states that the **Open Anyway** button is offered for *about
an hour* after the blocked attempt. If you go and make coffee between steps 1 and 2, the line
may be gone from Privacy & Security — go back to step 1 and open the app again, then return.

You only do this once per app. After the exception is recorded, it opens normally.

### Read this before you do it

Apple's own page says, in plain words, that overriding this is the most common way a Mac gets
infected with malware. That is a fair warning and we are not going to talk around it. It is a
statement about the general case: most people who click past this dialog do so for a program
they know nothing about. Whether it applies to you depends entirely on whether you can account
for where your copy came from.

### This path has been narrowing

Apple has made this harder at each of the last few macOS releases — the right-click override
is gone, the button now lives in System Settings, it expires after about an hour, and it now
asks for your password. It is reasonable to expect further tightening. On macOS, therefore, a
signature is closer to *required* than to *nice to have*, and that is the single strongest
argument for [funding one](sponsor.md).

## Windows: a dismissible warning that fades over time


### What you see

On running the downloaded file, Microsoft Defender SmartScreen shows a blue window:

> **Windows protected your PC**
>
> Microsoft Defender SmartScreen prevented an unrecognized app from starting. Running this app
> might put your PC at risk.

The only visible button is **Don't run**.

### How to proceed

1. Click the small **More info** link, above the button.
2. The publisher and file name appear, along with a **Run anyway** button.
3. Click **Run anyway**.

That is all — no password, no settings, no time limit.

If **Run anyway** does not appear, the file may still be marked as blocked: right-click it →
**Properties** → at the bottom of the General tab, tick **Unblock** → **OK**, and try again.

### What SmartScreen is actually judging

Per Microsoft's own developer documentation (*SmartScreen reputation for Windows app
developers*), SmartScreen weighs two things: whether the file is signed by a publisher it
recognises, and whether this exact file has been downloaded by enough people without trouble.
An unsigned file starts from zero on both, and — because reputation attaches to the exact file
— every new release starts from zero again.

The practical consequence is that the warning tends to soften on its own as a release
circulates, and to reappear on the next one.

### One case where you cannot click through

Windows 11 has a separate, stricter feature called **Smart App Control**. Where it is switched
on, it blocks unsigned programs outright and offers no "Run anyway". It is only on by default
on clean installs of Windows 11, and switching it off is one-way — Windows will not let you
turn it back on without reinstalling. If you hit it, the honest answer is that there is no
workaround short of the app being signed.

## Summary

| | What you see | How to proceed | Gets easier over time? |
| --- | --- | --- | --- |
| **Linux** | Nothing | `chmod +x`, then run | n/a — there is no gate |
| **macOS** | Refusal, no "open" button | System Settings → Privacy & Security → Security → Open Anyway, within about an hour, with your password | No — Apple keeps tightening it |
| **Windows** | "Windows protected your PC" | More info → Run anyway | Yes, as a release accumulates downloads |

None of these warnings mean the app was inspected and found dangerous. They mean nobody has
paid to certify who wrote it. [What that would cost](sponsor.md).

---

*Checked against vendor documentation on 2026-08-05: Apple's Mac User Guide entry "Open a Mac
app from an unidentified developer", and Microsoft Learn's "SmartScreen reputation for Windows
app developers". These behaviours change between OS releases. If your screen does not match
what is written here, those two pages are the places to check, and please report the
difference so this page can be corrected.*
