<!--
Index for the maintainer documentation. This tree is written for someone working ON the app;
household-facing pages live in docs/en/ and docs/nl/, and the specification in docs/specs/.
English only, matching docs/specs/ — the bilingual requirement covers the product, not its
development instructions.
-->

# Maintainer documentation

Working *on* the app. If you just want to run it as a household, start at
[`docs/README.md`](../README.md) instead.

- **[Development](development.md)** — the stack, running from source, repository layout
- **[Styles and self-testing](styles-and-testing.md)** — rebuilding the stylesheet, Playwright
  screenshots and the smoke tests
- **[Internationalisation](i18n.md)** — the bilingual UI: catalogs, extraction keywords,
  messages with runtime values, number and date formatting

The specification these documents implement is in [`docs/specs/`](../specs/README.md); the
running record of decisions is in [`changelog/`](../../changelog/), and the repository rules
for working in it are in [`AGENTS.md`](../../AGENTS.md).
