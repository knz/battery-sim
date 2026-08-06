# DST-ambiguous note in the data-quality box

## Task specification

The October DST ambiguity flag (`QualityFlags.DST_AMBIGUOUS`) is computed by the wide-CSV
parser, stamped on the affected intervals and persisted, but never shown to the user. Add a
note for it in the data-quality box (`app/templates/_data_quality.html`), in the same style as
the existing "Gaps" and "Counter resets" notes.

Requirements carried in with the task:

- The note must NAME THE DAY, not just print a count — the §16 fixture (22a) says the flag is
  "reported in the data-quality box naming the day".
- Wording must reflect what the flag records: an *irreducible ambiguity in the input*, not a
  repair the app performed (`app/domain/frames.py` `QualityFlags` docstring).
- All strings through `_msg` / `_msg_n`; catalogs updated per `babel.cfg`'s workflow, Dutch
  translated non-fuzzy.
- Keep `app/sample_data._panel_data()` shape-compatible (`tests/test_data_summary.py` asserts).
- Dates ISO, per `_fmt_date`'s reasoning.

## High-level decisions

**Date source: recompute from the quality bits and the frame index (option b), not the
persisted `CSV_DST_AMBIGUOUS_HOUR` warnings (option a).**

Rationale:

- `panel_data_from` already derives the gap and reset lines from the bits (`_count_flag`). The
  index is on the same `SeriesFrame` as the bits, so the day list and the count come from one
  authority and cannot disagree.
- `LoadedDataset.warnings` is read nowhere in `app/` today, and its `days` key exists only on
  the CSV path. An HA dataset that somehow carried the bit, or a dataset persisted before the
  warning shape existed, would show a count with no day under (a).
- The dates are derivable in four lines from data already in hand; (a) would need the warning
  list filtered by code, its `days` lists merged and de-duplicated, and a fallback for the
  missing-key case. (b) is the smaller and more robust of the two.

The UTC date is used directly, the same reasoning `csv_source._warnings_for_slice` records: at
the October transition the Amsterdam and UTC dates coincide (03:00 local is 01:00 UTC), so no
local rendering is needed.

**Wording.** "%(days)s — the clock went back on this day, so one hour appears twice in your
data and the run assumes the first (summer-time) one." for the flagged case; the shared "none
detected" for the clean case (same msgid the gaps and resets lines already use, so it stays one
catalog entry). The sentence says the input is ambiguous and states the assumption, rather than
claiming a correction was made.

Counted (`_msg_n`) on the number of DAYS, which is what the sentence prints. The first attempt
counted flagged INTERVALS and pluralised "hour" on them; that is wrong twice over — the
interval count varies with the series' resolution (four 15-min intervals are one repeated hour),
and two flagged hourly intervals on one day would have read "these hours" for what the sentence
elsewhere calls one repeated hour. The label is "Clock change" ("Klokwisseling").

A plain row rather than an `alert`: the file is sound and the run is usable, so the reader is
being informed, not warned. The row is unconditional, like Gaps — "none detected" is the
informative answer, and is the whole point of the change (a reader can tell "read exactly" from
"an assumption was made").

**Sample.** The sample gets the "none detected" branch: the wireframe demos a Home Assistant
dataset, which cannot carry this flag, so a fabricated day would misrepresent the demo. The
shape contract only requires the same pair shape, which "none detected" satisfies.

## Files modified

- `app/data_view.py` — `_flagged_days()` helper (dates of the intervals carrying a flag);
  the `dst` field in the `quality` dict; header comment updated.
- `app/templates/_data_quality.html` — a "Clock change" row next to Gaps / Counter resets.
- `app/sample_data.py` — `dst` in the sample quality dict.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.po` + `.mo` — the two
  new msgids, Dutch translated.
- `tests/test_data_summary.py` — the flagged and clean cases, and the day naming.

## Current status

Implemented and verified. Verification run: the four named test files plus the smoke suite;
the new test was mutation-checked by making the DST count always zero.
