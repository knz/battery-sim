# 20260809 — Visual restyle (colour, type, texture)

## Task specification

From the user, working in the `ui-layout` worktree:

> i'd like you to help making the UI more visually appealing. i'm thinking about updating
> the color scheme, fonts/sizes, adding background elements etc.
> I'm not interested in changing the layout of UI widgets / controls.

Scope: **appearance only**. Colour scheme, typography (families, sizes, weights, spacing),
background/surface treatment, borders, and similar surface-level polish. Explicitly **out of
scope**: moving, adding, removing or regrouping controls; changing information architecture;
changing copy beyond what a purely visual change forces.

## Starting state (observed, not assumed)

Captured baseline screenshots of four screens by driving the app with Playwright through the
demo workspace (home empty, home with cards, results, configure-data, configure-analysis).

- Stack: Tailwind v4 + daisyUI v5, CSS-first (no `tailwind.config.js`). Source stylesheet is
  `app/static/src/app.tailwind.css`; the committed, minified `app/static/app.css` is generated
  by `npm run build:css` and is what the browser loads. A CI gate checks the generated file is
  fresh, so any CSS change must be rebuilt and committed.
- `@plugin 'daisyui' { themes: light --default, dark --prefersdark; }` — both screens'
  `<html>` elements currently hardcode `data-theme="light"`, so the dark theme is defined but
  never reached in practice.
- The look is stock daisyUI `light`: indigo/violet `primary`, neutral grey `base-200` page
  background, white cards, default Tailwind sans stack (with a pinned fallback chain added for
  headless rendering).
- Existing custom CSS that a restyle must not break: `.radio-card`, `.bench-track` /
  `.bench-fill` / `.bench-dot`, `.figure-col` (tabular figures), the CSS-only `.tab-*` machinery
  for the More-settings pane, `.blocked-control`, and the deliberately **unlayered**
  `.cost-label` / `.cost-field` cost-accent rules (unlayered because daisyUI's own utilities
  layer is emitted after ours and would otherwise win).

## Constraints carried over from the codebase

- `source(none)` plus a single `@source '../../templates/**/*.html'` glob: class names are read
  **only** from templates. Any new utility class used from anywhere else will not be generated.
- The cost accent must stay a *hue distinct from* `primary`, because `primary` is already
  load-bearing for selection state, and it must keep its per-theme contrast split (light theme
  uses `accent-content`, dark uses `accent`) — the reason is contrast, not taste, and a new
  palette has to re-check both.
- Colour is never the only signal for state (existing rule, §2.5 of the UX spec).

## Direction chosen (user's answers)

- **Fonts:** ship two self-hosted webfonts.
- **Palette:** "Dutch grid / energy instrument" — cool slate ground, deep blue primary, amber
  for solar, green for savings.
- **Dark mode:** make it real *and* add a visible toggle. The user chose this explicitly after
  being told the toggle adds a control, which brushes against the no-layout-changes constraint.
- **Background:** subtle and structural — a soft wash plus a low-contrast grid motif.

## High-level decisions

**Typography: IBM Plex Sans + IBM Plex Mono, self-hosted (159 KB, OFL 1.1).**
Chosen over the more common Inter/JetBrains pairing because Plex is a *superfamily*: the mono
is a true sibling of the sans, sharing skeleton, terminals and vertical metrics. Nearly every
screen here sets a mono figure directly against a sans label, so a superfamily makes the pair
read as one voice. Subset to `latin` + `latin-ext` only (the app ships EN/NL). The sans turned
out to be a variable font — Google's four weight URLs resolve to one file — so it is stored
once per subset with a `font-weight: 400 700` range rather than as four byte-identical copies;
that alone cut the payload from 384 KB to 159 KB.

**Palette: two named daisyUI themes (`northsea`, `northsea-dark`) replacing stock light/dark.**
Hue assignments are load-bearing rather than decorative: `primary` stays selection state (the
existing `.radio-card` / `.bench-*` rules depend on it), `accent` is reserved for the cost
tint, `warning` is generation, `success` is savings. OKLCH throughout so the base ramps step in
perceptually even lightness increments.

**Theme persistence: a `/theme/{mode}` route mirroring `/lang/{code}`.**
daisyUI's `theme-controller` is CSS-only and cannot survive a page load; every screen here is a
full server render, so a cookie set server-side is what avoids a flash of the wrong theme on
first paint. Resolution lives in `app/i18n.py` beside the language cookie, since it is the same
kind of thing. The toggle is a plain `<a>`, so it works with scripting off.

**Figure typography: values up, labels down.** The stock treatment had bold-ish labels
competing with the value they describe. `.stat-value` becomes larger, lighter and mono
(tabular, so a repainting panel does not jitter as digit widths change); `.stat-title` becomes
a small tracked-out uppercase micro-label. Done entirely in CSS — `source(none)` means a class
used outside the templates is never generated, so a markup change would have been needed for
any new class, and the templates already used `.stat-*`.

## Obstacles and solutions

- Google served the sans as one variable file under four weight URLs → detected by md5, stored
  once per subset with a weight range.
- `.btn-active` (the selected state shared by the language toggle, the period presets and the
  chart tabs) is implemented by daisyUI as *relative* darkening — 5% toward black. That reads
  as "pressed" on light but makes the selected chip **darker than its neighbours** on dark,
  i.e. less prominent than the things it must stand out from. Reported by the user against both
  the language switcher and the period presets; both are the same rule. Replaced with an
  absolute, theme-aware pair (`neutral` / `neutral-content`) plus a weight bump.
- Tuning that chip's lightness by eye failed twice (34% → 1.72:1, 45% → 2.41:1 against the
  unselected ground; both looked fine in a screenshot). Two thresholds apply at once and move
  in opposite directions as lightness rises — the chip needs 3:1 against its neighbours, its
  own label needs 4.5:1 on it. Measured sweep found the window at L=0.51–0.54; 52% chosen
  mid-window (surface 3.26:1, label 5.04:1).

## Verification

A throwaway OKLCH→sRGB contrast script checked the ten pairs the design depends on, in both
themes. All pass: body text 14.62:1 / 12.99:1, cost accent 8.16:1 / 8.54:1, primary 6.34:1 /
4.72:1, selected-chip label 10.23:1 / 5.04:1, selected-vs-unselected surface 9.80:1 / 3.26:1.
The cost-accent figures were re-derived for the new palette rather than carried over — the
light/dark token split exists for contrast, not taste.

Full suite: **1868 passed, 25 skipped** (the pre-existing live-HA skips). `app/static/app.css`
rebuilt and committed, so the css-freshness CI gate is satisfied. Screenshots taken at each
iteration in both themes across the home, results and configure-data screens.

Quality floor added while in the file: a `prefers-reduced-motion` block, a `prefers-contrast:
more` block that drops the ornament, and an explicit `:focus-visible` ring (the header's ghost
buttons had only a background tint, which the wash behind them nearly cancelled).

## Files modified

- `app/static/src/app.tailwind.css` — themes, faces, page ground, figure type, `.btn-active`,
  a11y floor. The `.cost-label` / `.cost-field` rules keep their deliberately *unlayered*
  placement; their dark selector moved from `[data-theme='dark']` to
  `[data-theme='northsea-dark']`, and the `prefers-color-scheme` copy was dropped because every
  page now sets `data-theme` explicitly, so the bare-`:root` case can no longer occur.
- `app/static/app.css` — regenerated (committed, as the repo requires).
- `app/static/vendor/fonts/` — **new**: 8 woff2 subsets + `OFL.txt`.
- `app/i18n.py` — `THEMES` / `DEFAULT_THEME` / `THEME_COOKIE_NAME`, `resolve_theme`,
  `theme_context`.
- `app/main.py` — the `/theme/{mode}` route; `theme` added at the four render sites.
- The four screen templates — `data-theme` from context, plus the toggle in each header. The
  block is duplicated four times deliberately: these headers are already duplicated line-for-
  line, and factoring them into a partial is a structural refactor this visual pass is not
  doing.
- `app/locales/*` — two new msgids ("Switch to dark theme", "Switch to light theme"),
  translated to Dutch, catalogs updated and compiled.
- `scripts/generate_third_party_notices.py` — a fonts entry in section 1, enumerating the
  shipped files from disk rather than hardcoding them, matching the file's read-it-back-from-
  the-artifact principle. `THIRD-PARTY-NOTICES.md` regenerated.

## Current status

Complete and committed. Packaging needed no change: `packaging/battery-sim.spec` bundles
`app/static` wholesale, so the fonts travel in every distribution form already.

Open, deliberately not decided here:

- The grid-texture ground and the uppercase tracked micro-labels are the two places this pass
  spends its boldness. Both are reversible in one commit if they wear badly in daily use.
- The theme toggle currently offers light/dark only. A third "follow the OS" setting is
  possible but needs a client round trip to read `prefers-color-scheme`, which is exactly what
  the cookie approach avoids — worth doing only if someone actually wants it.
- The four duplicated headers are now duplicated in one more respect. If a fifth screen
  appears, factoring them into a partial becomes clearly worth it.
