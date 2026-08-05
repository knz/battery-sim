<!--
The sponsorship invitation (English).

PLACEMENT DECISION: this lives in docs/ and README.md and MUST NOT appear anywhere in the
app UI. docs/specs/01-product-brief.md:186 and docs/specs/15-data-quality-and-limits.md §7.5 rule out
telemetry and outward-facing affordances; an in-app sponsor link would be the first one the
product has. See changelog/20260805-desktop-packaging.md §17.1.

Structure: three reasons someone might sponsor, then what sponsorship does not buy.

Costs verified 2026-08-05: Apple Developer Program USD 99/yr, incl. Developer ID +
notarization, from Apple's membership-comparison page. Azure Artifact Signing (renamed from
Trusted Signing) approx. USD 10/month, from Microsoft Learn's smartscreen-reputation page. The
USD 220/yr on the page is those two summed and rounded; update it if either changes.

The page does NOT carry the caveat that signing fails to remove the SmartScreen warning
immediately — Microsoft is explicit that reputation attaches per file, so a signed release still
warns until it accumulates download history. That was cut for length and survives in
changelog/20260805-desktop-packaging.md §17. Restore it if a sponsor asks what the money buys on
Windows, because "removes the warnings" is true of macOS and only gradually true of Windows.

Commercial enquiries go to the contact form at https://raphaelposs.com/contact/, deliberately
NOT to GitHub Sponsors, which cannot carry terms. General sponsorship is GitHub Sponsors at
https://github.com/sponsors/knz.

The three no-cost items link to .github/ISSUE_TEMPLATE/{broken,docs,dutch}.md via
?template=<filename>.md — the extension is part of the parameter. Renaming a template file
breaks the link here silently, since nothing validates these URLs.
Dutch counterpart: ../nl/sponsor.md.
-->

# Supporting the project

The app is free software under the AGPL-3.0, it runs entirely on your own machine, and it
collects nothing about you. There is no paid tier and nothing is held back.

If you would like to support it, there are three reasons people do.

## To remove the security warnings

The app is unsigned, so macOS and Windows warn you the first time you open it — the
[security-warnings page](security-warnings.md) describes what you see and how to get past it.

Signing is not a technical problem; it is a recurring bill. Apple's Developer Program is USD 99
per year, and a certificate service for Windows is around USD 10 per month — together roughly
**USD 220 per year**, every year, for as long as the app is published. Sponsorship is what would
pay it.

## To say thanks

If you have used the app and found it worth something, that is reason enough. It funds the time
that goes into it, and nothing about it is conditional.

## For a commercial arrangement

If you want to embed the app in something you are building, or extend and publish it under your
own branding, that can be arranged as a custom sponsorship package.

For this, please [get in touch through the contact form](https://raphaelposs.com/contact/)
rather than using GitHub Sponsors — these arrangements need terms, and the sponsors page cannot
carry them.

## How to contribute

You can support the project through [GitHub Sponsors](https://github.com/sponsors/knz), which
handles both recurring monthly contributions and one-time donations.

If you would rather contribute in a way that costs nothing, all of these go through
[the issue tracker](https://github.com/knz/battery-sim/issues):

- **[Report what breaks](https://github.com/knz/battery-sim/issues/new?template=broken.md).** The
  builds are verified on a narrow set of machines. A report that one fails to start on your
  distribution, your Mac or your Windows version is worth a great deal.
- **[Report a documentation
  error](https://github.com/knz/battery-sim/issues/new?template=docs.md).** The macOS and Windows
  steps in these docs are written from Apple's and Microsoft's documentation, not from running
  those systems. If your screen says something different, that is a correction worth having.
- **[Check the Dutch](https://github.com/knz/battery-sim/issues/new?template=dutch.md).** The
  interface and these pages are written in Dutch as well as English. Awkward phrasing is a bug.

Anything else — a question, an idea — is
[welcome too](https://github.com/knz/battery-sim/issues/new?template=other.md).

## What sponsorship does not buy

To be clear about what is not on offer: no feature is behind a payment, no contributor gets
priority support, and nothing about the app changes for people who do not contribute.
