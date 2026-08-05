# Phase 6 — remaining untranslated catalog entries

## Task specification

A review of the Phase 6 i18n work found that six msgids were still untranslated in
`app/locales/nl/LC_MESSAGES/messages.po` (five of them verified as reachable UI), plus a set
of empty `msgstr` entries in the `en` source catalog. Task: translate them, fill the `en`
catalog per the repo's convention (source text repeated as its own msgstr), recompile both
`.mo` files, and verify the strings render in Dutch in the live app. Do not commit.

## What was translated

Six NL msgstrs, written to match terminology already in the catalog rather than inventing new
terms:

1. **Band overlap warning** (§7.3 check 12) — "Het laadband en het ontlaadband overlappen;
   laad- en ontlaadverzoeken worden tegen elkaar weggestreept." Reuses `laadband` /
   `ontlaadband` and the exact clause "worden tegen elkaar weggestreept" already used by the
   parameterised `⚠ Charge band [%(a)s, %(b)s] …` variant, so the two phrasings of the same
   warning read identically.
2. **Initial SoC outside window** — "De begin-laadtoestand ligt buiten het werkbereik en wordt
   bij het eerste interval afgekapt." `begin-laadtoestand` matches the existing "Initial SoC" →
   "Begin-laadtoestand" label; `afgekapt` matches the existing renderings of "clamped".
3. **Round-trip + DC bonus above 100** — "Het retourrendement plus de DC-bonus komt boven de
   100, waardoor het DC-laadpad energie zou creëren." `retourrendement` is the catalog's
   existing term for round-trip efficiency.
4. **No-PV charge-policy hint** — "Zonder zon is er geen overschot om op te vangen, dus laden
   vanaf het net is de enige manier om de batterij te vullen." "laden vanaf het net" matches
   the existing "Grid charge when spot price is in band" translation.
5. **§2.5b phase-approximation soft block** — "Uw slimme meter saldeert over de fasen heen, …"
   Uses `slimme meter`, `1-fase`, `3-fase` and `zekeringwaarde`, all consistent with the panel.
6. **Pending-affordance prompt** — "Vertel ons over uw opstelling — omvormermodel, verdeling
   over de fasen, en of u sensoren per fase heeft. …"

The `en` catalog's remaining empty msgstrs were filled with their own msgid text, matching the
convention already visible throughout that file.

## Terminology choices

- **"saldeert over de fasen heen"** for "nets across phases". `salderen` is the established
  Dutch term and is what a Dutch reader will recognise, even though the app's subject is the
  post-2027 regime in which salderen (as a *policy*) no longer exists — here it describes the
  meter's arithmetic, not the tariff scheme, so the overlap is not misleading. The alternative,
  "verrekent over de fasen", is less specific about the netting being bidirectional.
- **"werkbereik"** rather than "werkvenster" for "operating window". The catalog had no prior
  translation for the term; `werkbereik` reads as the SoC range the battery is allowed to use,
  which is what the check means, whereas `werkvenster` suggests a time window.
- **Register.** Panel ② already uses `u`/`uw` ("Hoe is uw batterij over de fasen aangesloten?",
  "Uw opstelling — …"), so the three panel-② strings use `uw`. The catalog is mixed overall
  (panel ③ uses `je`), but consistency within a panel was preferred over a global change.
- **No literal `%`** in any msgstr — `app/i18n.py` uses `newstyle=True`, so a bare `%` before a
  non-ASCII character raises. The DC-bonus string says "boven de 100" rather than "100%".

## Obstacles and solutions

- **Accidental revert of both `.po` files.** An initial `git checkout` of the two catalogs
  (intended to undo a bad rewrite) restored the *committed* versions, which predate Phase 6 —
  the git status snapshot in context was stale and the Phase 6 catalogs were uncommitted
  working-tree state. Recovered by rebuilding both `.po` from `app/locales/messages.pot` (the
  msgid set, still intact) plus the compiled `.mo` files (the translations, never touched);
  the reconstruction was verified to reproduce exactly the same 6 untranslated entries the
  review reported, with 0 fuzzy.
- **First rewrite dropped the obsolete `#~` entries** because it round-tripped through babel's
  `write_po`. The final fill edits only the empty `msgstr ""` lines in place, leaving the rest
  of each file byte-identical.
- **`write_po` re-added a `#, fuzzy` header flag**, which made `pybabel compile` skip both
  catalogs. Stripped before the final compile.
- **The DC-bonus warning (item 3) is not currently reachable in the UI.** Its issue attaches to
  `battery.roundtrip_dc_bonus`, and `_panel_params.html` renders no input for that field, so
  the warning has no slot to appear in. This is why the review listed five strings, not six.
  Translated anyway (the msgid is extracted and the check does fire in `validate()`), but the
  missing control is a separate open question, not fixed here.

## Files modified

- `app/locales/nl/LC_MESSAGES/messages.po` — 6 msgstrs filled.
- `app/locales/en/LC_MESSAGES/messages.po` — remaining empty msgstrs filled with source text.
- `app/locales/{en,nl}/LC_MESSAGES/messages.mo` — recompiled.

## Verification

- Both catalogs: 260 entries, **0 untranslated, 0 fuzzy**; 0 `#:` location comments retained.
- `pybabel compile -d app/locales` clean; both `.mo` load via `gettext` with 260 entries.
- Live app on port 8090 under `Accept-Language: nl`: the band-overlap warning (POST with
  overlapping bands), the initial-SoC clamp warning, the phase-approximation soft block and its
  pending-affordance prompt (3-phase grid + 1-phase battery), and the no-PV charge hint
  (`has_pv=false`) all render in Dutch. The DC-bonus warning could not be rendered — see above.
- `uv run python -m pytest tests/ -q` → **458 passed, 2 skipped**, matching the baseline.
- No `simconfig.json` left in `data/`.

## Current status

Complete, uncommitted. Open item: the missing `battery.roundtrip_dc_bonus` control in panel ②.
