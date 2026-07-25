# 20260725 — Investigation of `followups.md` section A (i18n and message catalogs)

## Task specification

User request (verbatim):

> can you look at `followups.md` and investigate section A

Scope: section A of `followups.md` lists seven i18n follow-up items (A1–A7) collated from the
23–25 July changelogs. The collation explicitly states it was **not verified against the current
tree**. This task verifies each item against the code as it stands, reports what is still true,
what has been overtaken by later work, and what the real shape of the remaining work is.

Investigation only — no code, spec or catalog changes were made.

**Follow-on request (verbatim):**

> please make a plan to address all of them

The resulting plan is at the end of this file, under "Implementation plan". Awaiting approval;
no code changes made for it either.

## Method

Verified against the working tree at `feat/pending-affordance-backend` (098d61c), by:

- reading the named call sites rather than trusting the changelog citations;
- re-running `pybabel extract` (per process note G2 — verify catalog state by extracting, not by
  reading the record) and diffing msgids against the committed `.pot`;
- rendering the app in Dutch through `TestClient` — `GET /` plus the two live fragments
  `POST /results` and `POST /results/benchmark` (preset `last_1_year`) — stripping tags and
  reading the visible text, so leakage is measured rather than inferred;
- exercising the `newstyle=True` %-format behaviour directly in a Jinja env.

## Findings

### Summary

All seven items are still live. None was fixed in passing. Two need their framing corrected
(A2 understated, A5 half-done), and one relationship the collation missed changes what the work
costs: **the `%(name)s` mechanism A1 proposes already exists and ships in panel ②** — so A1 is an
application of a proven pattern, not a design problem.

Catalog state is clean: extraction produces zero msgid drift against the committed `.pot`, the NL
catalog has 256 entries with **0 untranslated and 0 fuzzy**. Everything that *is* extractable is
translated. The whole of section A is therefore about strings that never become msgids at all.

### A1 — runtime f-strings render in English under NL. **Confirmed, and measured.**

All named sites are present and unchanged: `results_view.py` benchmark gloss (~`:540-627`), the
annualisation notice (`:1022-1029`), the range label (`:698-704`), the KPI deltas (`:809-813`),
and the panel-① data-quality box in `data_view.py` (`:114-206`).

Rendered in Dutch, a fully-translated panel ③ shows these in English:

- all three caveats, in full — the resolution-mismatch paragraph, the averaged-price note, and
  "Computed for the battery configured in the parameters panel — 11 kWh usable, …";
- the entire benchmark gloss — "Your policy captures 51 percent of the grid import a
  perfectly-informed battery could have avoided. Perfect foresight knows every future price…";
- the KPI delta row — `0.36 / day`, `1,365 kWh throughput`;
- the range label — `… · 365 dagen · simulated hourly · 8,760 intervals` (Dutch and English in
  one line).

Panel ① leaks alongside it: `hourly (full)`, `5-min (last 9 days)`, `none detected`,
`⚠ hourly, averaged`, `Simulatieraster hourly · 3,890 intervals`, and a full English
price-resolution caveat.

**New: the fix mechanism is already in the tree.** `_panel_params.html` and `_data_glance.html`
use `_('… %(a)s …', a=value)` with matching `%(name)s` msgids in both catalogs (band-overlap
warnings, `A → max import %(kw)s kW`, the export note). So A1 does not need a mechanism designed
— it needs an established one applied to two more modules. That lowers its cost relative to how
the collation framed it ("touches every call site and both catalogs", declined three times).

### A2 — the `newstyle=True` percent trap. **Confirmed, and worse than recorded.**

`app/i18n.py:90` is unchanged. Measured behaviour under the installed env:

| input | result |
|---|---|
| `'50% saved'` | `'50{}aved'` — **silent corruption** |
| `'a 50%z thing'` | `ValueError: unsupported format character 'z'` → 500 |
| `'50%% ok'` | `'50% ok'` — correct |

The collation says a `%` before a letter is "silently eaten". It is not just eaten: `% s` is
consumed as a `%s` conversion and, with no arguments supplied, renders `{}` — the following
letter disappears and a brace appears. That is a corrupted user-facing string, not a dropped
character, and it is the more likely failure of the two because `% s` is a common shape.

**Mitigation is in place and holding**, and better documented than the collation knew: README
(`:70-73`) mandates the fullwidth `％` (U+FF05) for literal percent signs, and `sample_data.py`
follows it. Verified: no ASCII `%` appears inside any `_()` call in the templates, and no msgid
in either catalog carries a non-placeholder `%`. The trap is genuinely latent — but it is
guarded by a documented convention, not by the code, so it stays one careless string away.

### A3 — shared-Jinja-env locale race. **Confirmed, and now wider than recorded.**

The collation names three sites. There are **four**: `app/main.py:106` (`index`), `:222`
(`POST /params`), `:268` (`POST /results`) and `:347` (`POST /results/benchmark`). Each installs
the request catalog onto the module-level shared `templates.env` immediately before rendering.
Sync routes run in a threadpool, so install-then-render is not atomic. Unchanged in kind since
the collation; one more mirror of the same pattern has been added since.

### A4 — hardcoded English in `ha_fetch.js`. **Confirmed.**

`Connecting…` (`:345`) and the error strings (`:281`, `:286`, `:297`, `:303`) are literals. The
`t(key, fallback)` helper (`:157`) and `#drawer-i18n` mechanism exist and are used for the
drawer's own strings, so this is population of an existing mechanism, not new plumbing.

### A5 — the two undocumented `pybabel` flags. **Half-fixed.**

- `--no-location`: **now documented.** README `:63` and `babel.cfg`'s workflow comment both
  carry it on the `extract` line.
- `--no-fuzzy-matching`: **still undocumented.** Neither the README's nor `babel.cfg`'s `update`
  line carries it. The risk it guards against (fuzzy matching mistranslating "Extra grid import"
  as "Netafname T2") is unmitigated in the recorded workflow. Current catalogs carry 0 fuzzy
  entries, so nothing is presently wrong — but the documented command would reintroduce them.

This is the cheapest item in the section: one flag in two files.

### A6 — locale-aware number and date formatting. **Confirmed, wholly unstarted.**

No `babel.numbers` / `babel.dates` import anywhere; no `format_decimal`, `format_date` or
`locale=` call in any view or template. Every figure is formatted with a hardcoded English
convention (`f"{x:,.0f}"`, `f"{x:.3f}"`), so the Dutch render shows `3,924 kWh` and
`0.094 €/kWh` — English thousands-comma and decimal point — where Dutch expects `3.924` and
`0,094`. Visible in the measured NL render above, in the data band and the spot-price line.

### A7 — sample-data strings left in English on purpose. **Confirmed; the exemption no longer holds.**

The named strings are unmarked plain literals in `sample_data.py`: the panel summary
(`:91`, "Home Assistant · 5 series · simulated hourly"), the granularity cells
(`:134-139`, `"hourly (full)"`, `"5-min (last 9 days)"`, `"hourly, averaged"`), and the KPI
deltas (`:232-234`). 48 other strings in the file *are* `_N`-marked, so the exemption is
deliberate and narrow, as recorded.

The stated reason — these would arrive formatted from the domain layer — has now come true, and
that is precisely what breaks it. `data_view.py` and `results_view.py` build the same shapes at
runtime as f-strings, and they leak (measured above). So marking the sample strings alone would
fix nothing on the real page: **A7 is the same defect as A1 seen from the sample side**, and the
two must be resolved together or the sample and live renders will disagree about which language
they are in.

### Test coverage

`tests/test_smoke.py::test_dutch_renders` (`:239-246`) asserts a handful of positive Dutch
strings plus one negative. It would not catch any leakage found here — all of it is in strings
the test does not look at, and the live fragments (`POST /results`, `/results/benchmark`) are not
exercised in Dutch at all. Whatever is done about A1/A7 wants a leakage-shaped assertion rather
than a string-spotting one.

## Revised picture

The collation's own cross-cutting note said "A1 + A2 + A6 are one task". The measurement supports
grouping, but suggests a different split:

- **A1 + A7 are one task, and A6 belongs with them.** Same call sites in `results_view.py` and
  `data_view.py`; the `%(name)s` restructuring is the natural place to route numbers through a
  locale-aware formatter. The mechanism already exists in panel ②, so this is application work
  of known shape, not design work. This is the bulk of the section and all of the visible damage.
- **A2 is separate and is not urgent.** It shares a root cause with A1 but the mitigation
  (fullwidth `％`, documented in the README) is holding. Doing A1 shrinks its exposure surface
  incidentally. Fixing it properly (escape `%`→`%%` before translation, or `newstyle=False`) is
  its own catalog-wide change and does not need to block A1.
- **A5 is a two-line documentation fix**, independent of everything else.
- **A3 and A4 are unrelated to the rest** — one a concurrency defect app-wide, one a JS i18n pass.

Nothing in section A was overtaken by later work; the two corrections are that A2 is more severe
than recorded (silent corruption, not a dropped character) and A5 is half-done.

## Obstacles

- `POST /results` rejects `{"period": "1 year"}`; the preset keys are `last_1_year` etc.
  (`results_view.PERIOD_DAYS:153`). Used the correct keys.
- The index page renders from the sample view-model, so it understates live leakage. Had to
  exercise the two live fragments separately to measure A1 honestly.

## Files modified

- `changelog/20260725-followups-section-a-investigation.md` — this file (new). No code, spec,
  catalog or `followups.md` changes; nothing committed.

## Current status

Investigation complete. All seven items verified as live; framing corrected on A2 and A5; the
A1/A7 relationship and the already-shipped `%(name)s` mechanism are the two findings that change
what the work costs. No triage or prioritisation done — that is the user's call.

---

# Implementation plan (awaiting approval)

Covers all seven items. Sequenced so each step is independently committable and testable, and so
the two steps that touch every catalog entry do not collide.

## Two structural facts the plan is built on

1. **The templates already call `_()` on the leaking strings.** `_panel_results.html:251` renders
   `_(c)` per caveat and `_benchmark_box.html:38` renders `_(benchmark.gloss)`. The strings pass
   through gettext already — they just arrive as runtime-built f-strings whose msgid matches no
   catalog entry (verified: zero hits for "Your meter recorded" / "Perfect foresight knows every
   future price" in `messages.pot`). So the work is **not** adding translation calls; it is making
   the msgid a compile-time constant with `%(name)s` holes. That is a Python-side change in
   `results_view.py` / `data_view.py`; the templates mostly stay as they are.
2. **Number formatting is already funnelled through ~6 helpers** (`_fmt_kwh`, `_fmt_pct`,
   `_fmt_signed_kwh`, `_fmt_signed_pct`, `_fmt_eur`, `_fmt_res`) across `results_view.py` (35
   call sites), `summary_view.py` (18) and `data_view.py`. A6 therefore does not mean touching
   every call site — it means changing the helpers and giving them a locale.

## Ordering rationale

A5 first (trivial, and its `--no-fuzzy-matching` flag protects every later catalog step). Then
A2 (small, and it removes a trap the A1 work would otherwise keep tiptoeing around). Then A3 and
A4, which are independent of the catalog churn. Then A1+A7 (the bulk), and A6 last, because A6
changes the *rendered* form of numbers that A1's new msgids interpolate — doing it after means
one pass over the catalogs, not two.

---

## Step 1 — A5: document the two `pybabel` flags

**Change:** add `--no-fuzzy-matching` to the `pybabel update` line in `README.md:65` and in
`babel.cfg`'s workflow comment. Add one sentence naming the failure it prevents ("Extra grid
import" fuzzy-matched to "Netafname T2").

**Files:** `README.md`, `babel.cfg`.
**Test:** none needed — documentation. Verify by running the documented command and confirming 0
fuzzy entries result.
**Risk:** none.

---

## Step 2 — A2: remove the `newstyle` percent trap

**Decision required (see "Open questions" below):** two viable fixes.

- **(a) Keep `newstyle=True`, escape at the boundary.** Wrap the installed catalog so `%` is
  doubled before printf substitution, for msgids that carry no `%(name)s` placeholder. Fiddly —
  the wrapper must not break the ~6 msgids that *do* interpolate.
- **(b) Switch to `newstyle=False` and interpolate explicitly.** `_()` stops %-formatting; the
  ~6 existing `%(name)s` call sites become explicit `% {...}` or an explicit helper. Removes the
  trap class entirely rather than guarding it.

**Recommendation: (b).** It deletes the failure mode instead of policing it, and the blast radius
is small and known (grep gives 6 interpolating call sites, all in `_panel_params.html` and
`_data_glance.html`). It also lets the fullwidth-`％` convention be retired, which is one less
rule for a future contributor to know. The cost is that A1's new interpolating msgids must use
the explicit form — which is fine, since they are being written fresh in this same plan.

**Files:** `app/i18n.py`, the ~6 interpolating template call sites, `README.md` (retire or
restate the `％` rule).
**Test:** a new unit test pinning the three measured behaviours — `'50% saved'`, `'a 50%z thing'`
and a genuine `%(name)s` interpolation — so the trap cannot silently return.
**Risk:** moderate. Touches how every translated string renders. Mitigated by the full NL/EN
render diff in step 7.

---

## Step 3 — A3: fix the shared-Jinja-env locale race

**Change:** stop mutating module-level `templates.env`. Replace `i18n.install_for(templates.env,
locale)` at all four sites (`main.py:106, 222, 268, 347`) with a per-request environment that
carries the right catalog. Two implementations:

- **overlay:** `templates.env.overlay()` per request, install onto the overlay, render from it;
- **cached-per-locale envs:** build one env per supported locale once at startup, pick by code.

**Recommendation: cached-per-locale envs.** Only two locales exist, catalogs are already cached,
and it removes per-request env construction entirely — the race disappears because nothing is
mutated after startup. An overlay per request is correct but allocates on every render.

**Files:** `app/i18n.py` (add `env_for(code)`), `app/main.py` (four call sites).
**Test:** a concurrency test — render both locales from many threads and assert no cross-
contamination. This is the one item currently untestable-by-inspection, so the test is the point.
**Risk:** low-moderate. Isolated to render plumbing; caught immediately if wrong.

**Note:** this interacts with step 2 — both touch `i18n.py`'s install path. Doing A2 first means
A3 lands on the settled API.

---

## Step 4 — A4: translate `ha_fetch.js`'s status strings

**Change:** move the hardcoded literals (`Connecting…` `:345`, plus the error strings at `:281`,
`:286`, `:297`, `:303`, and `Fetching…`) to `t()` lookups, adding keys to the existing
`#drawer-i18n` JSON block in `index.html:229`. The mechanism already exists and is used — this is
population, not plumbing. Sweep the file for any further literals rather than only the named ones.

**Files:** `app/static/ha_fetch.js`, `app/templates/index.html`, both catalogs.
**Test:** extend the smoke test to assert the `#drawer-i18n` block carries the new keys and that
they are Dutch under `lang=nl`.
**Risk:** low. Worst case a status string falls back to its English literal.

---

## Step 5 — A1 + A7: restructure the runtime strings (the bulk)

The largest step. Split into three commits so review is tractable:

**5a. `results_view.py` — caveats and gloss.** 8 `caveats.append(...)` sites and 8 `gloss = / +=`
assignments become constant msgids with `%(name)s` holes, e.g.

    "Your meter recorded %(meter)s imported over this period; the simulation's no-battery
     baseline is %(baseline)s. …"

The template's `_(c)` call must then supply the values, so each caveat becomes a
`(msgid, params)` pair rather than a bare string — a view-model shape change the template and
`tests/test_results_view.py` both follow. **This is the one shape change in the plan**; flagged
because it ripples to any consumer asserting on `caveats` as plain strings.

**5b. `data_view.py` — the panel-① quality box.** Same treatment for `coverage`, `grid`, `gaps`,
`resets`, `summary`, `price_warning`, `_register_summary`, and the granularity cells
(`"hourly (full)"`, `"5-min (last 9 days)"`, `"hourly, averaged"`, `"not mapped"` /
`"mapped, active"` / `"mapped, flat"`).

**5c. `sample_data.py` (A7) — retire the exemption.** Mark the previously-exempt strings so the
sample renders in the same language as the live page. Must land with 5a/5b, not before: the
sample must mirror whatever shape the real view-models now emit, or the two renders diverge.

**Files:** `app/results_view.py`, `app/data_view.py`, `app/sample_data.py`,
`app/templates/_panel_results.html`, `_benchmark_box.html`, `_panel_data.html`, both catalogs,
`tests/test_results_view.py`, `tests/test_data_summary.py`.
**Test:** see step 7 — the leakage assertion is what proves this step.
**Risk:** high-ish, by volume rather than by subtlety. Every changed string is user-visible.
Pluralisation (`interval(s)`, and followups D6's "1 intervals") should be fixed with `ngettext`
while these lines are open — noted as in-scope-if-cheap, not as scope creep.

---

## Step 6 — A6: locale-aware number and date formatting

**Change:** give the `_fmt_*` helpers a locale and route them through `babel.numbers`
/`babel.dates` (confirmed working: `format_decimal(3924.5, locale='nl')` → `3.924,5`;
`format_decimal(0.094, locale='nl')` → `0,094`). The helpers are module-level and currently
locale-free, so the locale must reach them — either threaded through the view-model builders
(explicit, more churn) or via a context variable set per request (less churn, more implicit).

**Recommendation: thread it explicitly** through `results_from` / the `data_view` builder, which
already receive per-request context. A `ContextVar` would be less code but hides a request-scoped
dependency inside a pure formatting helper, which is the kind of thing that later bites under
concurrency — exactly the class of bug step 3 is removing.

**Known breakage:** `tests/test_results_view.py:368-371` and similar assert English-formatted
output directly (`_fmt_kwh(-1234.0) == "−1,234 kWh"`). These must gain an explicit locale rather
than being loosened — the English assertions stay valid *as English*.

**Files:** `app/results_view.py`, `app/summary_view.py`, `app/data_view.py`, `app/params_view.py`,
`tests/test_results_view.py` and neighbours.
**Risk:** moderate. Mechanically broad but conceptually simple; the tests pin it.

---

## Step 7 — the regression net (cross-cutting, lands with step 5)

The investigation found `test_dutch_renders` would not catch any of the measured leakage, and
that the live fragments are not exercised in Dutch at all. Rather than adding more
string-spotting assertions, add a **leakage-shaped** test:

- render `GET /`, `POST /results` and `POST /results/benchmark` under `lang=nl`;
- strip tags, and assert no English-only marker vocabulary survives (the heuristic used in this
  investigation: `the/your/and/of/is/…` above a threshold per line);
- keep an explicit allowlist for legitimately-untranslated tokens (entity IDs, `kWh`, `€/kWh`,
  ISO dates) so the test states its own exemptions rather than silently tolerating them.

This is the durable artefact of the whole plan: it converts "someone noticed English on a Dutch
page" into a failing test. **Recommend writing it first, before step 5**, so it starts red and
demonstrably goes green — otherwise it is written against already-fixed code and proves less.

---

## Sequencing summary

    1. A5   docs                 — trivial, protects later catalog steps
    2. A2   i18n percent trap    — decision needed (a) vs (b); recommend (b)
    3. A3   locale race          — lands on A2's settled API; needs a concurrency test
    4. A4   JS strings           — independent, low risk
    5. (7)  leakage test, RED    — written before the fix so it proves something
    6. A1+A7 restructuring       — 5a results_view, 5b data_view, 5c sample_data
    7. A6   locale formatting    — last: one catalog pass, not two
    8. re-extract, translate, compile, verify 0 fuzzy / 0 untranslated

## Open questions for the user

1. **A2: fix (a) escape-at-boundary or (b) `newstyle=False`?** Recommend (b). This is the one
   choice that changes the shape of later steps, so it is worth settling before step 2.
2. **A6 locale propagation: explicit threading or `ContextVar`?** Recommend explicit. Threading
   is more churn now and less risk later.
3. **Scope check on step 5a's view-model change.** Caveats becoming `(msgid, params)` pairs is a
   contract change to `results_from`'s output. Acceptable, or would you rather the params be
   pre-rendered into the string and the msgid carry fewer holes (less faithful translation, but
   no shape change)?
4. **Is D6 (the "1 intervals" pluralisation) in scope here?** It sits in the same lines step 5
   rewrites, so folding it in is nearly free — but it is filed under section D, not A.

## Estimated shape

Seven items, ~8 commits, touching ~12 source files, both catalogs and ~5 test modules. Steps 1–4
are small and low-risk; step 5 is the bulk of the work and the bulk of the review burden; step 6
is broad but mechanical. Nothing here needs a spec change.

---

## Decisions (user, in response to the plan)

1. **A2 → `newstyle=False`.** User instruction: "prioritize future maintainability over
   short-term implementation cost". Option (b) deletes the trap class rather than guarding it,
   so the fullwidth-`％` convention can be retired.
2. **A6 → explicit locale threading**, same rationale. No `ContextVar`; the locale is a visible
   parameter rather than ambient request-scoped state hidden inside a pure formatter.
3. **Step 5a's view-model shape change is approved** — caveats become `(msgid, params)` pairs.
4. **D6 pluralisation folded in**, since it sits in the lines step 5 rewrites.

**Execution method (user instruction):** the more expensive changes are to be done with
sub-agents — one implementing, one reviewing, iterating until the review comes back clean.
Applied to steps 5 (A1+A7) and 6 (A6); the small steps (1–4) are done directly.

Plan approved. Implementation begins below.

## Implementation log

### Steps 1–3 complete (A5, A2, A3)

**A5 — pybabel flags.** Added `--no-fuzzy-matching` to the `update` line in `README.md` and
`babel.cfg`, each with a sentence naming the failure it prevents (a fuzzy match shipped the Dutch
for a different string as "Netafname T2"; marked `#, fuzzy` in the .po but compiled and shown to
the user regardless). `--no-location` was already documented on the extract line.

**A2 — percent trap removed.** `install_for` now uses `newstyle=False`, so `_()` returns the
translated string untouched and a literal `%` is inert. Genuine interpolation moved to a new
`i18n.interpolate()`, registered as a Jinja filter; the four interpolating call sites became
`_('… %(kw)s …') | interpolate(kw=…)`. The fullwidth-`％` convention is retired in the README.

**A3 — locale race removed.** Replaced the shared mutable `templates.env` with one Jinja
environment per locale (`i18n.env_for`), built on first use and never mutated afterwards. All four
render sites in `main.py` now use it, including `index()` — which dropped `TemplateResponse`
(nothing in the templates used `request`/`url_for`, so all four routes are now consistent).
`Jinja2Templates` import removed.

*Design note:* `env_for` initially required a `configure()` call from `app/main.py` before use.
Writing the tests surfaced that as an import-ordering dependency — `tests/test_i18n.py` does not
import `main`, and got a RuntimeError. Rather than work around it in the test, `env_for` now
defaults to this package's own `templates/`, and `configure()` became optional (override +
globals registration only). Importing `i18n` alone is now enough to render.

**Verification.** The old design was emulated directly to confirm the race is real rather than
theoretical: one shared env, catalog installed immediately before render, 400 renders across 16
threads → **11 renders served the wrong locale's catalog** (an English request receiving
"max. afname"). The same load against the new per-locale environments gives 0.

**New tests** — `tests/test_i18n.py` (13 tests): literal-`%` survival across four shapes and both
locales; `interpolate` substitution, repeated placeholders, and its raise-on-missing-key contract;
the filter's presence on every locale env; translate-before-substitute ordering; per-locale env
caching; and the concurrent mixed-locale render test.

Full suite: 471 passed, 2 skipped.

### Step 4 complete (A4 — JS strings)

Converted every user-facing literal in `ha_fetch.js` to a catalog lookup. The collation named
five sites; a sweep found **17** — connection status, fetch/load progress, and the WebSocket and
ingest error paths.

Six of them carry runtime values (a slot name, a progress count, an error reason) and were built
by concatenating fragments. Those became single msgids with `%(name)s` placeholders, substituted
by a new `ti()` helper in the script — the same translate-then-interpolate split as the server's
`| interpolate` filter, and for the same reason: concatenation fixes English word order into
every language. It is not hypothetical here. The Dutch for "Fetching %(slot)s (%(n)s/%(total)s)…"
is "%(slot)s ophalen (%(n)s/%(total)s)…", value first — which fragment concatenation could not
express.

These msgids contain literal `%`, which only became safe when A2 landed.

Catalogs: 256 → 273 msgids (17 added, none removed). English filled from source; Dutch written
against the catalog's existing formal-neutral register. Both compile at 0 untranslated, 0 fuzzy.

**Correction to the step-4 investigation.** While working this step I reported that 7 of the 8
pre-existing `#drawer-i18n` strings were never extracted, and that Babel does not descend into a
`{{ {...} | tojson }}` dict literal. **Both claims were wrong.** The check behind them used
`grep -cF "msgid \"$s\""` inside a double-quoted heredoc, so the escaped quotes never reached
grep and the pattern could not match; Babel extracts the inline dict form fine, verified in
isolation. The strings were in `messages.pot` and translated in `nl.po` at HEAD~1 all along, and
the drawer was rendering Dutch correctly before this step. Nothing was broken and nothing needed
repairing there; the only genuinely-missing msgids were the 17 this step adds. The `{% set %}`
rewrite of the block was kept — it reads better than a long inline literal — but it is a
readability change, not a fix, and the code comment and test docstring that stated otherwise have
been corrected.

**New tests** (5, in `tests/test_i18n.py`): every `t()`/`ti()` key in the JS is present in the
rendered block; drawer strings differ between EN and NL (bar an allowlist); placeholder names
survive translation in both locales; no bare literal reaches `setStatus`; every rendered string
is a known msgid in `messages.pot`.

Full suite: 476 passed, 2 skipped.

### Step 7 landed first, deliberately RED (the leakage net)

`tests/test_no_english_leakage.py` renders `GET /`, `POST /results` and `POST /results/benchmark`
under `lang=nl` and asserts nothing reads as English prose. Two complementary checks:

- a **named** list of the exact fragments the investigation measured leaking, so a regression
  identifies itself rather than surfacing as an opaque marker count;
- an **open-ended** scan flagging any line carrying ≥2 closed-class English markers (articles,
  prepositions, auxiliaries — the words a translator always replaces), which can catch strings
  nobody has noticed yet.

An explicit token allowlist covers what legitimately stays untranslated (units, proper nouns,
Dutch homographs), so the exemptions are stated rather than silently tolerated. A fourth test
asserts the *English* page is full of those same markers — without it, a broken text extractor
would make the Dutch assertions pass vacuously.

Committed red on purpose, ahead of the fix: 6 of 7 failed, the sanity check passed. A later green
therefore means the strings got translated, not that the scan stopped working.

### Steps 5–6 in progress (sub-agent implementation/review cycles)

Per the user's instruction, the expensive steps run as implement-then-review sub-agent cycles.
Step 5a (`results_view.py` — 8 caveats, 8 gloss branches, the range label, the KPI deltas, the
annualisation notice, plus `ngettext` pluralisation) is with an implementation agent. Steps 5b
(`data_view.py`) and 5c (`sample_data.py`) follow; the catalog pass runs once at the end, after
all three, so the msgids are extracted a single time.

### Step 5a complete (A1 — `results_view.py`)

Implemented by a sub-agent, then adversarially reviewed by a second one. The implementation agent
**crashed on an API error before self-verifying**, so its work was checked from scratch rather
than taken on trust.

**The shape.** `_msg(msgid, **params)` and `_msg_n(singular, plural, n, **params)` return
`(msgid, params)` pairs; `templates/_msg.html` renders them — translate the constant msgid, then
substitute. 19 sites converted: 8 caveats, the benchmark gloss's every branch, the range label,
the KPI delta/extra, the annualisation notice. Two new extraction keywords (`-k _msg`,
`-k _msg_n:1,2`), documented in `babel.cfg` and `README.md`.

The one `gloss +=` was resolved into two complete msgids rather than concatenated fragments —
a translator can reorder a whole sentence but not a fragment glued on at runtime.

`_msg_n` fixes D6's "1 intervals" as a side effect: the count reaching `ngettext` and the count
printed in the text are the same value by construction, so they cannot drift.

**Verification.** English render byte-identical on all three routes (captured before/after and
diffed). All 19 message sites render without raising, including fault-gloss, zero-battery and
"n/a" branches no HTTP request reaches. A static AST check confirms every msgid's `%(name)s` set
equals its passed params — no `KeyError` risk. Extraction: 273 → 292 msgids, 19 added, 0 lost.
The reviewer independently reproduced all of this and additionally diffed all 10 gloss branches
and 5 dataset scenarios against a HEAD worktree: identical.

**Two latent hazards the review found, both fixed here:**

1. `msg("")` rendered the catalog's METADATA entry — the whole PO header — onto the page, because
   in gettext the empty msgid *is* the metadata. `msg(None)` rendered "None". Unreachable today
   (every producer sets the field) but `_panel_results.html:114` calls `msg(results.period_run)`
   unguarded, and 5b/5c add callers. Fixed with a falsy guard in the macro, so it is handled once
   rather than at each call site.
2. `i18n.interpolate`'s docstring claimed missing *or surplus* keys raise. Only missing ones do.
   Corrected, and the asymmetry is now stated as a decision: a missing key is a code bug that
   fails identically in every locale (raise), a surplus key means one catalog's translation
   dropped a placeholder — degrading to a sentence missing a figure beats a 500 on a page that
   renders fine in English.

**New tests** (10, in `tests/test_i18n.py`): the empty/None/`{}` guard; plain-string and pair
rendering; `ngettext` at n=0/1/2 (the counted branch has no natural coverage — the routes only
ever render it at one count); autoescaping of interpolated values; and a catalog invariant test
asserting every translation keeps the placeholders its msgid has. That last one is what makes the
lenient surplus-key behaviour safe, so it was verified by deliberately dropping `%(kw)s` from a
Dutch string — it fails with the offending msgid named.

Full suite: 486 passed, 2 skipped (leakage test still red, as designed — catalogs not yet
regenerated).

### Step 5b complete (A1 — `data_view.py`, the panel-① data-quality box)

Same treatment as 5a, applied to the ten sites in `panel_data_from` / `_register_summary`: the slot
coverage string, the granularity `uses`/`recorded` cells, `coverage`, `grid`, `gaps`, `resets`,
`registers`, `price_warning` and the panel summary. `_panel_data.html` renders all of them through
the `msg()` macro; `data.quality.price_warning` and `.load_warning` also lost their `_()` wrapper,
which was looking up a runtime string and could never match.

**`_msg` / `_msg_n` moved to `app/i18n.py`** (as `msg` / `msg_n`, imported under the private
aliases). They were in `results_view.py`, but `results_view` already imports `_fmt_res` from
`data_view`, so `data_view` importing them back would cycle. `i18n` is the module both already
depend on and the one that owns the other half of the mechanism (`interpolate`). The keywords in
`babel.cfg` match the name at the CALL SITE, so the aliases are load-bearing and both `babel.cfg`
and the README now say so.

**The `_fmt_res` seam.** The resolution label is a WORD embedded in a dozen sentences, and a bare
string param survives translation untouched — interpolation runs after the catalog lookup, so it
never sees a value's msgid. Three changes rather than one:

1. The five fixed labels became `_N`-marked msgids (a dict literal is not a call Babel sees), plus
   `irregular` and the `%(n)ss` fallback, which is now a msgid with a hole rather than an f-string.
2. A new `_res_msg(seconds)` returns the same label as a `_msg` pair.
3. `templates/_msg.html` now renders a param that is itself a message, recursively.

`_fmt_res` keeps its old signature and English return value, because `results_view` still needs it
for `results["period"]` — the deliberately-untranslated unsplit fallback line. Both read the same
`_RES_LABELS` table, so the two cannot drift. `results_view`'s three reader-facing uses moved to
`_res_msg`; that also closes the "translating that label is data_view's to do" note 5a left at
`results_view.py:766`.

**A double-escaping defect the new tests found.** The first nested-param implementation escaped a
nested render twice ("a & b" → "a &amp;amp; b"), because `str.__mod__` drops Markup's safety and
the outer `{{ }}` then escaped the result. Fixed by substituting into Markup (`| e | interpolate |
safe`), which escapes each value exactly once and passes an already-escaped nested render through.
`interpolate`'s docstring now states which of the two call shapes escapes where, so the two are not
"simplified" into one later.

**Pluralisation** (D6) folded in at four sites via `_msg_n`: the gap count ("N interval(s) flagged
as gaps" — a written-out plural, untranslatable into a language whose rule is not "add s"), the
coverage day count, the grid interval count, the fine-copy day count, and the slot coverage string.
`resets` was deliberately left uncounted (its English carries no noun); `summary` IS counted despite
identical English forms, because "series" is invariant in English but not in Dutch.

**Verification.** English visible text captured before/after and diffed on two renders — the three
routes as they stand, and a `GET /` backed by a synthetic ingested dataset built to hit every
branch (fine 5-min copy, 15-min price averaged down, both T1/T2 registers). Both diffs are exactly
two lines, and both are the intended plural fixes: `5-min (last 1 days)` → `(last 1 day)` and
`8 interval(s) flagged as gaps` → `8 intervals flagged as gaps`. Nothing else moved.

Extraction: 292 → 316 msgids, 24 added, 0 lost. Six of the new ones are the resolution labels; the
rest are the box's sentences. Catalogs untouched — the single update/compile pass still runs after
5c.

**New tests** (9): 7 in `tests/test_data_summary.py` — the first tests anywhere to exercise
`panel_data_from`, which had no direct coverage — asserting both the pair shape and the English it
renders to (the wording is the msgid, so shape alone would let the English drift), plus the
flat-vs-active register marks, the averaged-price branch, and the singular at n=1. 2 in
`tests/test_i18n.py` for the nested-param contract, one of which is the double-escaping regression.

Full suite: 496 passed, 2 skipped. The leakage test is still red on the same 6 of 7 and names the
same fragments as before — expected and not a regression: 5b makes these strings extractable, and
they stay English until the catalog pass translates them.

### Step 5b complete (A1 — `data_view.py`), and a correction to A2

Implemented and adversarially reviewed as before. Ten sites in panel ①'s quality box converted;
`msg`/`msg_n` moved to `app/i18n.py` (defining them in either view module would be circular —
`results_view` imports `_fmt_res` from `data_view`); resolution labels became `_N` msgids with a
new `_res_msg`, and `_msg.html` now renders a param that is itself a message, recursively, so an
embedded WORD gets translated rather than passed through as data.

Verified independently: 495 tests pass; the English render changed by exactly one line, the
intended `8 interval(s)` → `8 intervals`; extraction 292 → 316, 24 added and 0 lost; the static
placeholder check is clean across both view modules.

The implementing agent caught its own double-escaping defect en route (`"a & b"` → `"a &amp;amp; b"`,
because `str.__mod__` drops Markup's safety and the outer `{{ }}` escapes again) and pinned it.

**Correction: A2 was only half-closed, and this is my error, not the sub-agents'.** When step 2
landed I recorded the percent trap as removed. That was true only for the `_()` path. The
`(msgid, params)` mechanism introduced in 5a routes its strings through `interpolate`, which
*does* %-format — so inside `msg()` the original trap was fully alive:

| input | before | |
|---|---|---|
| `"50% saved"` | `"50{}aved"` | silent corruption |
| `"a 50%z thing"` | `ValueError` | 500 |
| `"50% of the %(v)s"` | `TypeError` | 500 |

Worse, my README rewrite told translators that a literal `%` was safe — about exactly the strings
5b was adding to the catalog. The hazard is in the **msgstr**, not just the msgid: a Dutch string
reading "50% lager" is ordinary copy, and it would have 500'd a page that renders fine in English.
The review caught this; I had not.

**Fixed properly rather than documented around.** `interpolate` now doubles every `%` that does
not begin a `%(name)s` placeholder, so a literal `%` is inert on every path. `%%` is deliberately
*not* exempt: with escaping handled for the caller there is no escape sequence left to know about,
and exempting it would preserve the one rule this was meant to delete for precisely the strings a
non-programmer edits. The fullwidth-`％` workaround is now obsolete; the two occurrences in
`_data_glance.html` were rendering a literal `％` to users and are now real percent signs
(`sample_data.py`'s five follow in 5c).

*A hole I introduced and caught while fixing it:* the first version applied `re.sub` to the
template, which returns a plain `str` even for a `Markup` input — silently discarding the escaping
5b depends on, so every substituted value would have reached the page unescaped. For panel ① those
values include Home Assistant entity ids. Two existing tests failed immediately, which is why they
were written; `interpolate` now rebuilds the original type, and two further tests pin the Markup
contract and the XSS case directly.

**New tests** (12): literal `%` inert across six msgid shapes, in a counted message, in a
*translation*, and combined with placeholders; `interpolate` still substitutes and still raises on
a missing key; Markup type preservation; and a value carrying `<img onerror=…>` cannot reach the
page unescaped through `msg()`.

Full suite: 506 passed, 2 skipped.


### Step 5c complete (A7 — `app/sample_data.py`)

The sample view-model now emits the same `(msgid, params)` pairs the real view-models do, so the
fresh-install page and the live page cannot disagree about which language they are in. The
exemption recorded in A7 ("these will arrive pre-formatted from the domain layer") is retired: that
did come true, and it is what broke the exemption.

**Converted** — panel ①: the summary line, `coverage`, `grid`, both granularity columns
(`recorded` / `uses`), `gaps`, `resets`, `price_warning`, `load_warning`. Panel ③: `period_run`,
the EFC tile's `delta` and `extra`, the benchmark gloss, and all three caveats.

**Left as data, deliberately** — entity/statistic ids, ISO dates, `period` (the real path's
unsplit fallback field is untranslated too), the whole `_data_summary()` band (the computed path
in `summary_view.py` also emits plain formatted strings there), the chart month abbreviations, and
the first two KPI tiles' `value`/`delta` (`"+34.2 %"`, `"+21 pp"` are figures with no word in them,
and the computed path has no msgid to offer for them either). `registers` stayed a plain `_N`
string rather than becoming a pair: with both marks fixed there is no runtime value to hold out,
and the macro renders a bare string.

**Msgid sharing over msgid copying.** Where the sample's wording matches the real path's, it now
uses the REAL msgid rather than a parallel copy — `summary`, `coverage`, `grid`, `resets`,
`%(res)s (full)`, `%(res)s (last %(n)s days)`, `%(res)s, averaged`, `period_run`, `%(n)s / day`,
`%(kwh)s throughput`. That is what makes "shape-compatible" mean something in the catalog rather
than only in the template: two copies would be two entries that can be translated differently.
Pinned by `test_sample_shares_the_computed_paths_msgids_where_the_wording_matches`.

**Four fields keep their own msgids** because their English genuinely differs: `gaps` (the
wireframe states a duration and a share; the real path counts flagged intervals), `registers`,
`price_warning` (worded from the meter's point of view, and spelling "15 minutes" out where the
real path nests the "15-min" label), and the panel ③ gloss and caveats (the wireframe's copy is
shorter and names the §6.13 diagnostic the real path does not compute). Preserving those was
required — the brief forbids English changes — but it is also the honest outcome: they are
different sentences, not the same sentence written twice.

**Shape mismatch found, and which side is wrong.** None that is a defect. `data_view.py:134`'s
"shape-compatible" claim now holds in the stronger sense above, and the docstring says so
explicitly rather than asserting it in passing. The two remaining divergences are documented on
both sides already: panel ③'s third `secondary` row (the sample keeps §2.4's wireframe row the
computed path does not emit) and `results["period"]`.

**The five fullwidth `％` are gone**, replaced by real `%`. They were rendering a literal `％` to
the reader — a visible defect, not a latent one — and the workaround they came from stopped being
necessary when `interpolate` started doubling non-placeholder percent signs (the A2 correction
above). No fullwidth `％` remains in any `app/` source outside the catalogs; the three left in
comments explain the retired convention.

**One thing the brief got wrong, worth recording:** it asked for pluralisation "wherever a count
drives singular/plural", implying visible plural fixes. There are none here. Every count in the
sample is greater than one (416 days, 8,760 intervals, 5 series, 9 days, 3 gaps), so `_msg_n`
selects the plural form and the English is unchanged. The counted shape is still correct and still
needed — the msgid is shared with the real path, which does reach n=1 — but unlike 5b it produced
no diff.

**Verification.** The English render was captured before and after and diffed twice, because
`GET /` on this machine has a persisted dataset and therefore renders the COMPUTED view-models,
not the sample — a diff of `GET /` alone would have proved nothing about this step. So: (1) the
sample view-model rendered through `index.html` directly, which is the fresh-install path — diff
is exactly the four `％`→`%` lines and nothing else; (2) `GET /` as it stands — byte-identical,
confirming nothing leaked sideways into the real path. Extraction: 316 → 316 msgids, 8 removed and
8 added, each removal a deliberate replacement (the `％` fixes, the parameterisations, and the two
KPI strings that now reuse the real path's existing msgids). Nothing lost.

**New tests** (8 in `tests/test_data_summary.py`, which previously covered the sample's
`_data_summary()` band only and never `_panel_data()` or `_panel_results()`): the pair shape and
the rendered English for panel ①'s box and panel ③'s messages; the nested-resolution contract; that
no `％` survives; the msgid-sharing invariant above; and a walk over every nested label in the
sample asserting it is one `data_view._RES_LABELS` `_N`-marks — `_res` passes its label as a
runtime value, so an unknown label would render English on a Dutch page with nothing else failing.

The module docstring, `data_view.panel_data_from`'s docstring and `templates/_msg.html`'s header
were all updated: each stated the old exemption as current fact.

Full suite: 515 passed, 2 skipped, 6 failed — all six in `tests/test_no_english_leakage.py`, the
same 6 of 7 as after 5b, still red for the same reason (the catalogs have not been regenerated;
that pass runs once now that 5a/5b/5c are all in).
### Step 5c complete (A7 — `sample_data.py`), and A1's restructuring is done

The sample view-model now emits the same `(msgid, params)` shapes as the real ones, so the
fresh-install render and the live render cannot disagree about which language they are in.

**Better than the brief asked for: the sample REUSES the real path's msgids** where the wording
matches (`summary`, `coverage`, `grid`, `resets`, the three granularity cells, `period_run`,
`%(n)s / day`, `%(kwh)s throughput`) rather than carrying parallel copies. A translator writes
each sentence once and the two paths cannot drift apart in the catalog. Four msgids stay separate
because the sample's wireframe copy genuinely says something different from what the pipeline
computes; the review verified each of those four rather than taking the claim.

The four fullwidth `％` in this file became real percent signs, completing the cleanup A2's fix
made possible.

**Verified independently:** 514 tests pass; the sample render diffed against HEAD in a worktree is
**exactly the four `％`→`%` lines**; extraction 316 → 316 with 10 msgids replaced by parameterised
equivalents and none lost. My first `GET /` diff showed more, which I traced to the persisted
config and simulation figures differing between trees, not to this change.

**The agent caught its own instance of the very defect this work is about:** it initially
parameterised `"15 minutes"` and `"5-minute"` as if they were data. Interpolation runs *after*
translation, so a word passed as a param stays English inside a translated sentence. Both are back
inside their msgids. The review swept every `%(name)s` in both panels and confirmed no other param
is a word — the only words riding as params are resolution labels, all nested messages.

**Review process incident, disclosed by the reviewing agent:** while mutation-testing it ran
`git checkout app/sample_data.py` and destroyed the uncommitted work, then reconstructed it from a
diff it had captured beforehand. I did not take that on trust — verified three ways: `git diff
--stat` matches my pre-review figures (226 lines on the file, 437 total), the rendered sample
output is **byte-identical** to the capture I took before the review, and re-extraction gives the
same 316 msgids with zero symmetric difference. The reconstruction is faithful.

**Docstring corrected** (`data_view.panel_data_from`): it claimed shape-compatibility for "the
same fields", which overstated by one. `mapping[*].entity` is a pair here and a plain string in
the sample. No template reads it, so the divergence is inert; the docstring now says "every field
the template renders" and names the exception.

*Follow-up worth filing, not fixed here:* `mapping[*].entity` is dead — produced by both
view-models, read by no template, JS or test — and now costs two translated msgids. Deleting it is
a separate change from an i18n pass, so it is recorded rather than done.

**New tests** (8, in `tests/test_data_summary.py`, which previously never covered `_panel_data()`
or `_panel_results()`): pair shape and rendered English for both panels; the nested-resolution
contract; no `％` survives; the msgid-sharing invariant; and a walk over every nested label
asserting it is one `data_view._RES_LABELS` marks — an unknown label would otherwise render
English on a Dutch page with nothing else failing. The reviewer mutation-tested five of these and
each failed as intended.

Full suite: 514 passed, 2 skipped.


### Step 6 in progress (A6 — locale-aware number and date formatting)

**Design chosen: (b) defer formatting to render time.** The view-models emit a NUMBER plus a
format kind — `num(3924.5, "kwh")` → `{"num": 3924.5, "fmt": "kwh"}` — and `templates/_msg.html`
formats it with the render locale, which is the only place that knows the locale.

Why (b) over threading a `locale` argument, given maintainability is the stated priority:

1. **The seam already exists.** 5a/5b/5c made every user-facing figure travel as a `params` entry
   inside a `(msgid, params)` pair, and `_msg.html` already renders a param that is itself a
   *message*, recursively, for exactly the same reason: a value that needs the catalog cannot be
   resolved before the locale is known. A number needs the locale for the same reason a word does.
   Adding a second kind of render-time param is one branch in one macro, not a new mechanism.
2. **Threading would make the locale a parameter of the numeric pipeline.** `results_from` is a
   simulation entry point — it reconciles series, runs A/B/C, computes §6.11 metrics. Giving it a
   `locale` means the language reaches into the module that owns the physics, and every future
   caller (a test, a CLI, an export) has to have an opinion about language to get a number. The
   view-models stay pure data under (b): same output for every locale, which is also what makes
   them cacheable and diffable.
3. **It cannot be half-done.** Threading is enforced by nothing — a new `_fmt_kwh(x)` call that
   forgets to pass the locale still compiles and still renders English on a Dutch page, which is
   this defect exactly. Under (b) a formatter is not callable without a locale at all (the
   `_fmt_*` helpers take `locale` as a required argument), and the only locale-free way to produce
   a figure is `num()`, which cannot render English because it does not render.

Costs accepted: a view-model field is no longer a `str`, so anything reading one as text needs the
renderer. That is why the change is scoped to the fields the templates render through `msg()`.

#### What was implemented

**`app/i18n.py`** gains the render-time half: `num(value, kind)` (the view-model's producer, which
raises on an unknown kind so a typo fails where the code is rather than mid-render), `format_num`
(the formatter, with `locale` as a REQUIRED argument), `month_abbr`, and a `_NUM_KINDS` table of 13
conventions. `env_for` registers two per-locale filters closed over the locale, `numfmt` and
`monthname` — sound only because an environment is built once per locale and never mutated, which
is step 3's change paying off a second time.

**`templates/_msg.html`** renders a figure the way it already rendered a nested message: as the
whole field, or as a param inside a `(msgid, params)` pair, which is where most figures live since
5a/5b/5c. The number branch is tested BEFORE the falsy guard, because `{"num": 0, "fmt": "kwh"}`
must render "0 kWh" — the benchmark box's "No battery" row is exactly that.

**The four view modules** stopped formatting. `results_view`'s and `summary_view`'s `_fmt_*` helpers
return figures instead of strings; `_g` became the `general` kind. Every count riding as a param in
`data_view` and `sample_data` became a figure, and the sample's glance band and panel-③ tiles with
them — leaving those as literal strings would have hardcoded English separators into the
fresh-install page, which is A7's defect from the other side.

**Three new msgids**, all composites the old code built with f-strings and now cannot:
`%(before)s → %(after)s` (`results_view._arrow` — the self-sufficiency tile, the self-consumption
and grid-export rows; two figures cannot be joined into a string when neither is one yet),
`%(pp)s pp`, and the sample's `%(full)s / %(empty)s`. Extraction: 265 → 268, **none lost**.

#### Decisions inside the scope the brief left open

**Units and symbols stay literal, in `_NUM_KINDS` rather than the catalogs.** `kWh`, `€/kWh`, `%`
and `pp` are written identically in Dutch; putting a symbol through gettext invites a translator to
change one of the two places it appears, and buys nothing.

**`pp` folded in, month names folded in, dates deliberately NOT.** `pp` needed a msgid anyway
because its number became a figure. The month abbreviations were an English table in `results_view`
that put "Jan Feb Mar" on a Dutch axis; babel's CLDR has every locale's, so the table is gone and
the view-models emit month NUMBERS which the template names — the chart is drawn client-side from a
JSON node, so that is the last point the server can put the reader's language on the axis. Dates
stay ISO in both locales: `en` short is `7/24/26` and `nl` short is `24-07-2026`, the same day
written two ways, so a reader unsure which convention a page follows cannot tell them apart — and
`_data_glance.html` SPLITS `solar.coverage` on " → " to show a start date, so the shape is a
contract, not free presentation.

**`params_view._fmt` is out of scope, and the brief was wrong to list it.** Its output is the
`value=` of `<input type="number">`, which `coerce_number` parses back on submit — and that function
REJECTS "1,5" on purpose, because a comma there could be either separator and guessing would
silently change the user's number. Localising it would round-trip a Dutch user's own stored setting
into a field error. Left alone, with the reasoning recorded in its docstring. `summary_line` shares
it and shares the reasoning.

**U+2212 preserved and now enforced in one place.** Babel emits ASCII "-" for both locales (their
CLDR minus IS the hyphen), so `format_num` substitutes after formatting. The signed-zero guard moved
there too. The two guards differ on zero, and deliberately: `pct_signed` drops the sign at zero
("0.0 %") and `dec0_signed` keeps it ("+0 pp"), because the f-strings they replace did — changing
either would have changed the English render.

#### Verification

**English render unchanged.** Captured before/after on all three routes plus the sample view-model
rendered directly through `index.html` (needed because `GET /` on this machine renders the persisted
COMPUTED view-models, not the sample, so a `GET /` diff alone proves nothing about `sample_data`).
Visible text: **byte-identical on all four**. RAW HTML against a HEAD worktree sharing the same data
directory: identical modulo whitespace (the `{%- set -%}` line the chart labels needed), which the
JSON chart node and every attribute are inside — so the check covers what visible-text stripping
would have hidden.

**Dutch renders Dutch.** `3.924 kWh`, `0,094 €/kWh`, `−0,500 €/kWh`, `+15,9 %`, `8.760 intervals`,
`0,95 round-trip`, `2.030 kWh → 1.104 kWh`, and the chart axis `jan feb mrt … okt`. English on the
same routes: `3,924 kWh`, `0.094 €/kWh`, `Jan Feb Mar … Oct`.

**Tests: 550 passed, 2 skipped, 6 failed** — the six are `test_no_english_leakage.py`, the same 6 of
7 as before this step, still red for the same reason (catalogs not regenerated; that pass runs
after).

Existing English assertions were given an EXPLICIT locale rather than loosened: `_en(m, locale="en")`
in `test_results_view.py` and `_render(m, locale="en")` in `test_data_summary.py`, both defaulting to
"en" and both documenting that the assertion is about English. `_render` already went through the
real per-locale env and the real macro; `test_no_caveat_contains_a_literal_percent_sign` was switched
to do the same, because its hand-rolled `_(msgid) | interpolate(...)` stopped being the whole render
once figures moved (it would have asserted against a reimplementation of itself).

**21 new tests** in `tests/test_i18n.py`: the convention table across both locales (the `3,924` /
`3.924` and `0.094` / `0,094` pair IS the defect); U+2212 asserted per kind × locale, parametrised
over `_NUM_KINDS` so a NEW kind is covered by construction; the two zero behaviours; the unknown-kind
raise; non-numeric fallback; the macro's figure rendering at top level and as a param; the zero-figure
guard; month names; the filters' locale binding; and an end-to-end route test asserting on the
SEPARATORS rather than on any figure, since the persisted dataset's numbers move between runs.

Mutation-tested: ASCII minus → 14 failures; `format_num` ignoring its locale → 11; moving the number
branch after the falsy guard → the zero-figure test alone, as intended.

#### Uncertainties and things left alone

- **The committed `messages.pot` is stale** (239 msgids against 265 extracted at HEAD), consistent
  with the catalog pass not having run since 5a. So the extraction diff above is HEAD-extract against
  final-extract, not against the committed file — diffing against the committed `.pot` would have
  attributed steps 5a–5c's msgids to this step.
- `_fmt_res` still formats its own `%(n)ss` fallback with a plain int. It feeds only
  `results["period"]`, the deliberately-untranslated unsplit fallback line, so it is consistent — but
  it is the one number in these modules still formatted at build time, and worth a second look if
  that field ever becomes user-facing.
- The `general` kind derives its digits from `%g` and only swaps the decimal separator, rather than
  handing the value to babel. Babel groups thousands where `%g` does not and expands `1e+20` to
  twenty zeroes; both are arguably nicer and both would have changed the English render. If the
  English is ever allowed to move, this is the place that should.
- The sample's `%(before)s → %(after)s` is written out again rather than imported from
  `results_view._arrow` (importing would cycle). Identical literals, so one catalog entry — but two
  places to keep in step, and only extraction proves they are.
### Step 6 complete (A6 — locale-aware figures), after one rework cycle

**Design: defer formatting to render time.** View-models emit `i18n.num(value, kind)`;
`templates/_msg.html` formats it in the render locale via a per-locale `numfmt` filter.
`format_num(value, kind, locale)` takes the locale as a *required* argument, and `num()` — the only
locale-free spelling — does not format. The user's ruling was "explicit, not a ContextVar"; within
that, deferring beat threading a `locale` parameter for three reasons:

- the seam already existed — 5a–5c made every figure travel as a `params` entry, and `_msg.html`
  already renders a param that is itself a *message*, recursively, for the same reason a figure
  needs deferring: the locale is not known when the view-model is built;
- threading would put the display language into the simulation's signature. `results_from` runs
  A/B/C and computes §6.11 metrics; a `locale` argument means every future caller — test, CLI,
  export — needs an opinion about language to get a number;
- it cannot be half-done. A new `_fmt_kwh(x)` that forgets its locale argument still compiles and
  still renders English on a Dutch page — this exact defect.

Month names now come from babel's CLDR (`month_abbr`), replacing an English `_MONTH_ABBR` table, so
the Dutch axis reads `jan feb mrt … okt`. Units (`kWh`, `€/kWh`, `%`, `pp`) stay literals in the
`_NUM_KINDS` table rather than going through gettext — they are written identically in Dutch, and
routing a symbol through a catalog invites a translator to change one of two places. **Dates are
deliberately NOT localised**: babel's short forms are `7/24/26` (en) and `24-07-2026` (nl), the same
day written two ways, so a reader unsure which convention a page follows cannot tell them apart.

**The brief was wrong about one thing** and the agent pushed back correctly: `params_view._fmt` must
stay English. Its output is the `value=` of an `<input type="number">` that `coerce_number` parses
back, and that function deliberately rejects `1,5` — localising it would turn a Dutch user's own
stored setting into a field error on next render.

Verified: 550 tests pass; English byte-identical on all three routes against a HEAD worktree sharing
the same `BATTERY_SIM_DATA_DIR` (my first attempt compared against an empty-state render and proved
nothing); Dutch shows `8.765 kWh`, `0,094 €/kWh`, `+15,9 %`; all 13 kinds emit U+2212 in both
locales; extraction 316 → 319, 3 added, none lost.

#### Review found one user-visible defect the verification missed, plus three real problems

**1. A raw Python dict printed on the page.** `_data_glance.html`'s `load_unreliable` warning used a
bare `_('…') | interpolate(export=…)`, which %-substitutes without formatting. With `export_kwh` now
a `num()` pair it rendered, in both locales:

    ⚠ {'num': 72.0, 'fmt': 'kwh'} was exported to the grid but your solar…

on the one warning whose entire job is to explain a real data problem. Fixed to render through
`msg()`.

*Why three verification methods all missed it, which is the instructive part.* The branch needs
export > import with no PV — no dataset in the tree produces that, so the page never rendered it and
the English diff could not see it. The Dutch leakage scan could not either: `num`/`fmt` are not
English words. And the existing test asserting the figure (`_render(note["export_kwh"]) == "72 kWh"`)
passes regardless, because `_render` goes through `msg()` — precisely the step the template was
skipping. A test can assert a path the page does not take. The new guard renders the real
`_data_glance` macro against the triggering fixture in both locales; it fails on the original form
and passes on the fix.

**2. Four test assertions had gone silently vacuous.** Each is a `!=` guard whose sibling `==` line
was correctly wrapped in `_en()` while it was left comparing a dict to a string — trivially unequal,
so unfailable. Each named a real defect it existed to catch ("a household with no load is not 100%
self-sufficient"). Re-wrapped and mutation-tested.

**3. The minus-zero guard had been dropped for unsigned kinds** — an English-render change the
"byte-identical" check missed because it needs a marginally-negative input. `format_num` handed
`-0.4` to babel with pattern `#,##0`, giving `−0 kWh` where the old `f"{round(total):,}"` gave
`0 kWh`. Reachable: `conversion_loss` is a floating difference of three sums and does land just
below zero when the battery barely cycles. The guard now applies to every kind, so `kwh`, `count`
and `pct` no longer disagree with `kwh_bare` about the same artefact.

**4. `general` put U+2212 inside an exponent** (`1e−07`), because it replaced every `-`. Only a
leading sign is the number's; the exponent's stays ASCII.

Full suite: 550 passed, 2 skipped. Leakage test still red — catalogs next.

### Catalog pass — the leakage test goes green

Extracted once, after all six code steps, so the msgids were translated a single time rather than
after each step. `pybabel extract` → `update --no-fuzzy-matching` (both locales) → hand-translate →
`compile`.

**318 entries, 0 untranslated, 0 fuzzy in both catalogs.** 56 Dutch strings were written for this
pass, including 10 plural pairs (`msgid_plural` / `msgstr[0]` / `msgstr[1]`), every one preserving
its `%(name)s` placeholders — the parity test added in step 5a asserts that, so a dropped
placeholder would have failed rather than shipped.

**`tests/test_no_english_leakage.py`: 6 of 7 failing → 7 of 7 passing.** That test was committed
red on purpose before any of the restructuring, so the transition means the strings were translated
rather than the scan being weakened. The English render is byte-identical to HEAD across all three
routes, verified again after the catalog pass.

What a Dutch reader now sees where English used to be:

    Uw strategie benut 100 procent van de netafname die een perfect geïnformeerde batterij…
    0,23 / dag · 830 kWh doorzet
    ⚠ Uw meter registreerde 3.924 kWh afgenomen over deze periode; de basislijn zonder
      batterij van de simulatie is 3.864 kWh…
    ⚠ Berekend voor de batterij die in het parameterpaneel is ingesteld — 10 kWh bruikbaar,
      10/10 kW, 0,95 retourrendement, laden P1 / ontladen D1.

Both the sentences and the figures: `3.924` and `0,95`, not `3,924` and `0.95`.

Full suite: 557 passed, 2 skipped, 0 failed.

## Current status — section A complete

All seven items are implemented, reviewed and committed:

| | item | outcome |
|---|---|---|
| A1 | runtime f-strings unextractable | fixed — `(msgid, params)` pairs across `results_view`, `data_view`, `sample_data` |
| A2 | `newstyle=True` percent trap | fixed twice — `newstyle=False`, then `interpolate` escaping after 5a re-opened it |
| A3 | shared-Jinja-env locale race | fixed — one environment per locale, never mutated |
| A4 | hardcoded English in `ha_fetch.js` | fixed — 17 strings (the collation said 5), 6 with placeholders |
| A5 | undocumented `pybabel` flags | fixed — `--no-fuzzy-matching` documented in two places |
| A6 | no locale-aware formatting | fixed — figures formatted at render time from `num()` pairs |
| A7 | sample strings exempt from i18n | fixed — sample mirrors the real shapes and shares its msgids |

Catalogs: 256 → 318 msgids. Test suite: 458 → 557.

### What this pass got wrong, for the record

Three of my own claims needed correcting, all found by review rather than by me:

1. **A2 reported as closed when it was half-closed.** The fix covered `_()` but not `interpolate`,
   and 5a then routed every new sentence through `interpolate`. My README rewrite told translators a
   literal `%` was safe about exactly the strings being added to the catalog.
2. **A false "not extracted" diagnosis** for the drawer strings, built on a `grep` whose quotes were
   eaten by a heredoc. Babel had been extracting them all along.
3. **An XSS hole introduced while fixing A2** — `re.sub` returns `str` for a `Markup` input, so
   every interpolated value would have reached the page unescaped. Two existing tests caught it
   immediately.

Common thread: **grep against catalog files is unreliable** (`.pot` wraps long msgids across lines;
heredoc quoting bites) and a passing test is not proof the page works — the `load_unreliable` dict
leak passed its own assertion because the test rendered through `msg()` while the template did not.
Parse the artefacts, and render the path the page actually takes.

### Follow-ups this pass created or left

- `mapping[*].entity` is dead code (produced by both view-models, read by nothing) and now costs
  two translated msgids. Deleting it is not an i18n change.
- `summary_view.clamped_kwh` is likewise produced and never read.
- `results_view`'s six `ValueError` messages reach the user as HTTP 400 bodies, untranslated.
  Pre-existing, out of scope, previously unrecorded.
- `interpolate` only recognises `%(name)s`; a translator writing `%(n)d` renders the placeholder
  literally. The parity test would flag it at the next catalog pass.
- `Decimal` and `np.int64` params render unlocalised and without their unit. No live path found —
  the domain layer sums to Python floats at the view boundary — but it fails silently.
