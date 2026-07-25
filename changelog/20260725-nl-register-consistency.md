# Dutch register consistency — `u`/`uw` → `je`/`jouw`

## Task specification

The Dutch catalog (`app/locales/nl/LC_MESSAGES/messages.po`) is mixed in register: some
msgstrs address the reader formally (`u`, `uw`), others informally (`je`, `jouw`). The user
asked to make it consistent, using **`je` everywhere**.

Scope: Dutch msgstrs only. No English source text changes, no msgid changes, no code changes
beyond recompiling the `.mo`. The msgid set stays byte-identical, so extraction and the
leakage test are unaffected.

## Starting state (measured)

Surveyed the 319-entry catalog with a whole-word regex over every msgstr (including plural
forms):

- **33 msgstrs matched `u`/`uw`/`U`/`Uw`** — but 2 are false positives: the plural pair
  `%(n)s gat/gaten van in totaal %(hours)s u  (%(pct)s)`, where `u` is the unit abbreviation
  for *uur* (hours), not the pronoun. **31 real entries to convert.**
- **14 msgstrs already use `je`/`jouw`** — these are the target style and stay as they are.
- **0 msgstrs mix both registers**, so no entry is internally inconsistent today. The split is
  clean along panel lines, roughly as the earlier session's changelog described (panel ② and
  the panel-③ caveats formal; the setup bar and source drawer informal).

## Why this is not a token substitution

`u` → `je` changes verb conjugation and possessive forms, so a blind search-and-replace would
produce ungrammatical Dutch. The transformations needed:

- **Possessive:** `uw` → `je` (attributive), `Uw` → `Je` sentence-initially.
- **Subject pronoun:** `u` → `je`. Verb follows: `u heeft` → `je hebt`, `u aanlevert` →
  `je aanlevert` (unchanged, already the right form), `u hebt geaccepteerd` → `je hebt
  geaccepteerd` (unchanged), `u dit wilt` → `je dit wilt` (unchanged). The `hebben` present
  singular is the main one that moves: formal `heeft` → informal `hebt`.
- **Object pronoun:** `u` → `je` — e.g. "kan u niet vertellen" → "kan je niet vertellen".
- **Inversion:** after a fronted element, `heeft u` → `heb je` (the -t drops in inversion).
  Checked for; the catalog has no interrogative inversions with `u` as subject.
- **Emphatic possessive:** `uw eigen zon` → `je eigen zon`; `jouw` reserved for contrastive
  stress, matching the existing "Jouw strategie" entry.

## Plan (approved)

1. Rewrite the 31 msgstrs by hand, entry by entry, applying the transformations above and
   leaving the 2 `u`-as-hours entries alone.
2. Leave all `%(name)s` placeholders, HTML entities and the `−` / `÷` typography untouched.
3. Recompile both `.mo` files.
4. Verify: msgid set unchanged, no `u`/`uw` pronoun remains, placeholder parity, tests green.

The user additionally asked to **improve idiom while passing through**, rather than doing a
minimal pronoun swap.

## What was done

All 31 entries rewritten by hand. Conjugation changes actually applied (the cases the survey
predicted, all present):

- `Als u deze sensor heeft` → `Als je deze sensor hebt`
- `Als u een directe huisverbruiksensor heeft` → `Als je een directe huisverbruiksensor hebt`
- `of u sensoren per fase heeft` → `of je sensoren per fase hebt`
- `Omdat u een bestaande batterij heeft` → `Omdat je een bestaande batterij hebt`
- object pronoun: `kan u niet vertellen` → `kan je niet vertellen`
- `die u al bezit` → `die je al hebt` (see idiom note below)

Forms that are shared between registers and so changed only in the pronoun: `u aanlevert` →
`je aanlevert`, `u hebt geaccepteerd` → `je hebt geaccepteerd`, `u dit wilt` → `je dit wilt`,
`dat u zelf hebt gebruikt` → `dat je zelf hebt gebruikt`.

### Idiomatic improvements made in passing

- **`die u al bezit` → `die je al hebt`.** `bezitten` is a register-heavy verb for a household
  appliance; `hebben` is what a Dutch speaker says about owning a battery. The formal register
  was carrying the stilted verb, so the two changes travel together.
- **`gebruikt de app die echte waarde en toont ze hoever de reconstructie zou zijn afgeweken`
  → `… en laat ze zien hoever …`.** `tonen` with an indirect question reads as a translation
  artefact; `laten zien` is the ordinary construction.

Deliberately NOT changed: the headings kept the possessive (`Je gegevens in één oogopslag`
rather than dropping to `Gegevens in één oogopslag`). Both are idiomatic; the possessive was
kept because the English msgid says "Your data at a glance" and the panel-③ heading
distinguishes *your* selected-range figures from the general case.

`jouw` was not introduced anywhere. It stays reserved for contrastive stress, where the
catalog already uses it ("Jouw strategie").

## Verification

- msgid set byte-identical before/after (318 non-header entries, set equality checked).
- Exactly 31 msgstrs changed.
- Residual `u`/`uw` pronouns: **0**. The 2 remaining `u` tokens are the *uur* unit in the
  gap-count plural pair, correctly left alone.
- Placeholder parity: per-entry `%(name)s` sets identical before/after (0 mismatches), and no
  msgstr contains a placeholder absent from its msgid.
- Re-extraction: 0 missing, 0 obsolete, 0 fuzzy, 0 empty in both NL and EN; `.mo` in sync
  with `.po` for both locales.
- Full suite: **557 passed, 2 skipped**.

## Obstacles and solutions

- **`tests/test_results_route.py::test_data_glance_is_translated_in_both_copies` failed.** It
  asserts literal Dutch strings ("Uw gegevens in één oogopslag", "zoals uw meter ze heeft
  geregistreerd", "Uw energieverbruik …") as a proxy for "the macro picked up the request
  locale" — the regression it guards is a Jinja macro-import context bug, not the wording.
  Updated the four assertions and one stale comment to the new register; the regression it
  actually tests is unaffected.

## Files modified

- `app/locales/nl/LC_MESSAGES/messages.po` — 31 msgstrs rewritten to the `je` register.
- `app/locales/nl/LC_MESSAGES/messages.mo` — recompiled.
- `app/locales/en/LC_MESSAGES/messages.mo` — recompiled (unchanged content; `pybabel compile`
  rewrites both locales).
- `tests/test_results_route.py` — four literal-Dutch assertions and one comment updated.

## Current status

Complete and verified. Not committed, per the repo's default.
