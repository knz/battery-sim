# Fuzzy translation cleanup

## Task Specification

The user noticed "fuzzy" entries in the translation catalogs and asked (1) what
they are and (2) to fix them. Agreed scope: inspect the Dutch (`nl`) catalog for
missing/stale strings first, then fix the fuzzy entries.

## Findings

`#, fuzzy` is a gettext marker meaning the translation is an unreviewed guess.
Fuzzy entries are ignored at runtime — gettext falls back to the `msgid`.

Two kinds of fuzzy were present:

- `messages.pot:6` — the fuzzy on the template header block. Standard Babel
  output for the placeholder header. Left untouched (not a defect).
- Three entries in `en/LC_MESSAGES/messages.po`:
  - `"Spot price (max)"` — stale `msgstr` "Spot price" (dropped "(max)")
  - `"Spot price (min)"` — stale `msgstr` "Spot price" (dropped "(min)")
  - The data-picker legend string — `msgid` had grown a `◒ = offered only if
    you simulate costs (intra-hour price bracketing)` clause; the `msgstr` still
    held the old, shorter text.

These arose from the last `pybabel update`: new/changed source strings were
fuzzy-matched to similar older strings and carried the stale copy forward.

## nl catalog check (requested step 3)

The Dutch catalog is already complete and correct for all three strings: no
fuzzy markers, and the translations include "(max)", "(min)", and the full `◒`
legend clause. The drift existed only in the `en` copy-through catalog. So the
nl-review step surfaced nothing to change.

## High-Level Decisions

- Fix only the three `en` fuzzy entries; leave the `.pot` header fuzzy as-is.
- Since `en` is a copy-through locale, reconcile each `msgstr` to equal its
  current `msgid` and remove the `#, fuzzy` line.
- Recompile `en/messages.mo` so the compiled catalog matches the `.po`.

## Files Modified

- `changelog/20260724-fuzzy-translation-cleanup.md` (new)
- `app/locales/en/LC_MESSAGES/messages.po` (3 fuzzy entries reconciled)
- `app/locales/en/LC_MESSAGES/messages.mo` (recompiled)

## Current Status

Complete: nl verified clean, three en entries fixed, mo recompiled.
