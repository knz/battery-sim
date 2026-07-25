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

