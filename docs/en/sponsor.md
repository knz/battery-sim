<!--
The sponsorship invitation (English).

PLACEMENT DECISION: this lives in docs/ and README.md and MUST NOT appear anywhere in the
app UI. specs/01-product-brief.md:186 and specs/15-data-quality-and-limits.md §7.5 rule out
telemetry and outward-facing affordances; an in-app sponsor link would be the first one the
product has. See changelog/20260805-desktop-packaging.md §17.1.

Costs verified 2026-08-05: Apple Developer Program USD 99/yr, incl. Developer ID +
notarization, from Apple's membership-comparison page. Azure Artifact Signing (renamed from
Trusted Signing) approx. USD 10/month, from Microsoft Learn's smartscreen-reputation page;
Microsoft's public pricing page shows the tiers but not the figures. The hardware-token
requirement for OV certificates traces to the CA/Browser Forum baseline effective
2023-06-01.

There is NO sponsorship channel yet — no account, no FUNDING.yml. The URL is a single marked
placeholder line; picking the platform is the user's call.
Dutch counterpart: ../nl/sponsor.md.
-->

# Supporting the project

The app is free software under the AGPL-3.0, it runs entirely on your own machine, and it
collects nothing about you. There is no paid tier and nothing is held back.

There is one thing money would change, and this page is about that one thing, so you can judge
whether it is worth anything to you.

## The problem money would solve

The app is unsigned. macOS and Windows both react to that, and the
[security-warnings page](security-warnings.md) describes exactly how. Signing is not a
technical problem — the build already produces working artifacts — it is a recurring bill.

## What it costs, and what it actually buys

### macOS — roughly USD 99 per year

Apple's Developer Program is USD 99 per membership year. It includes a Developer ID
certificate and access to notarization, which is what an app distributed outside the App Store
needs. A free Apple account does not include either.

**What it buys: an app that opens by double-click.** Today a macOS user must attempt to open
the app, be refused, go into System Settings, find a **Open Anyway** button that expires after
about an hour, and enter their password. That is a real barrier for a household, and Apple has
been narrowing the path at each release. On macOS a certificate is closer to *required* than
cosmetic.

### Windows — roughly USD 10 per month, and it buys less than you would think

Since June 2023 the CA/Browser Forum's rules have required code-signing keys to live in
certified hardware — a USB token or a hosted HSM. A token is awkward for an automated build,
which is why the practical route is a hosted signing service. **Azure Artifact Signing**
(renamed from Trusted Signing during 2026) is currently among the cheapest credible options at
around USD 10/month, needs no hardware, and plugs into a CI pipeline. It is available to
businesses and self-employed individuals in the EU, so it is at least plausible for a Dutch
project.

**What it buys is more modest, and it would be dishonest to claim otherwise.** Microsoft's own
developer documentation is explicit that signing does *not* remove the SmartScreen warning: a
signed release still shows it until that specific file accumulates download history, which
Microsoft describes as potentially several weeks and hundreds of clean installs. What signing
does buy is that the warning shows a verified publisher name instead of nothing, and that
reputation carries forward across releases instead of resetting each time. (EV certificates
used to skip the warning outright. Microsoft states that they no longer do, so paying the EV
premium for that reason is not worth it.)

So: on Windows, signing removes friction gradually. On macOS, it removes a wall.

### Linux — nothing

There is no gate and nothing to buy. The AppImage runs as it is.

## Priority, if you are wondering where a contribution goes

macOS first. It is the platform where the absence of a certificate genuinely stops people, and
at USD 99/year it is the smaller of the two bills.

## How to contribute

> **A sponsorship channel has not been set up yet.** No account exists, so there is nothing to
> link to at the time of writing. When one is chosen, the link goes here.

If you would rather contribute in a way that costs nothing:

- **Report what breaks.** The Linux build is verified on a narrow set of machines. A report
  that it fails to start on your distribution is worth more than most things.
- **Report a documentation error.** The macOS and Windows sections of the
  [security-warnings page](security-warnings.md) are written from Apple's and Microsoft's
  documentation, not from running those systems. If your screen says something different, that
  is a correction worth having.
- **Check the Dutch.** The interface and these pages are written in Dutch as well as English.
  Awkward phrasing is a bug.

## What sponsorship does not buy

To be clear about what is not on offer: no feature is behind a payment, no contributor gets
priority support, and nothing about the app changes for people who do not contribute. The app
will also not ask you for money — this invitation exists in the documentation and in the
project's README, and deliberately nowhere in the application itself. The app makes no
outbound network calls except to your own Home Assistant, and adding a sponsor link to the
window would be the first thing it ever pointed at the outside world. That is not a trade
worth making.
