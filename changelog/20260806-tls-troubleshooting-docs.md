# TLS troubleshooting for Home Assistant connections

## Task Specification

The user hit a "Test connection" failure on macOS when importing from Home Assistant: the
connection failed with a TLS error because their HA instance uses a custom certificate. They
fixed it by adding their custom root CA to the macOS keychain and marking it as trusted there.

Requested: document this in the repository's troubleshooting docs, with a note that the problem
is not expected when HA has TLS disabled (plain `http://`) or when using the Nabu Casa hosting
option.

## Requirements Changes

**1 — the in-app message must change too.** After the first docs draft, the user pointed out that
the existing message could not work: the app runs in a pywebview window, and trusting a
certificate in a separate browser does not propagate to it. This was correct and widened the
scope from docs-only to docs plus the user-visible string and its catalogs. Confirmed against
`app/desktop.py:389` — pywebview uses the OS renderer (WKWebView / WebView2 / WebKit2GTK), all of
which read the system trust store, while a browser exception is stored per-browser.

Two follow-on decisions, taken with the user:

- *Message length* — short, with a link to the troubleshooting page on GitHub, rather than
  self-contained remedy text. Keeps the string translatable and lets the docs carry the detail.
- *How to name the cause* — list the candidates (address, HA not running, certificate) instead of
  leading with the certificate. The browser's WebSocket error event carries no reason, so a TLS
  rejection, a wrong host and a stopped HA are indistinguishable at that point; a message that
  named TLS would be guessing.

**2 — Linux confirmed, not hypothetical.** The user hit the same problem on Linux and fixed it by
adding the root CA to the system trust store (`/usr/local/share/ca-certificates` +
`update-ca-certificates` on Ubuntu), noting other distributions differ. The Linux steps were
promoted from "we have not verified this" to a reported fix with the distro caveat kept. Windows
remains reasoned-by-analogy and still says so.

**3 — terser prose, no version archaeology.** The user asked for a holistic reword of both pages:
shorter, and with no reference to earlier versions of the app's message — a reader arriving at
the page has no memory of what it used to say, so "an earlier version told you to…" is noise to
them. Both sections were rewritten in one pass rather than patched further; the per-platform
steps lost their prose preambles, and the two-item "unlikely if" list became one sentence. The
history that is genuinely useful to a maintainer moved into the HTML header comments, which
readers never see.

## High-Level Decisions

**Both language versions.** `docs/en/troubleshooting.md` and `docs/nl/probleemoplossing.md` are
maintained as counterparts and cross-reference each other in their header comments. A section
added to one without the other would break that invariant, so both get the content.

**A new top-level section, not an insert into the existing flow.** The page as written is about
the *launcher*: find the session log, read the address out of it, attach it to a report. Its
sections are ordered so each depends on the reader having found the log folder. A connection
failure is a different failure class — the app started fine — so it goes in its own section
placed before "Reporting a problem", and the log-file sections are left undisturbed.

**System trust store is the only fix documented; the browser route is explained as a dead end.**
The first draft kept the per-site browser exception as a "lighter alternative worth trying".
That was wrong, and the section now says so outright: the pywebview window never consults a
browser's certificate store, so accepting it there cannot help no matter how convenient it would
be. The section explaining why is kept even though the in-app message no longer suggests it —
clicking through a browser warning is a widespread habit, and the page should head it off.

**One shared explanation, three sets of steps.** The cause and the fix are identical across
platforms (trust the issuing CA, not the leaf certificate), so that is stated once before the
per-platform sections rather than repeated in each. macOS and Linux carry user-confirmed steps;
Windows is explicitly marked as reasoned-by-analogy and asks for a report.

## Rationales and Alternatives

*Why mention Nabu Casa and plain HTTP at all?* Requested by the user, and it narrows the
audience: a reader on Nabu Casa or on `http://` who sees a connection failure knows to stop
looking at certificates and look elsewhere. Both carry their own caveat — the note explains why
each avoids the problem rather than just asserting it.

*Why is the docs URL a translatable string?* `docs_troubleshooting` goes through `_()` like any
other message, so the Dutch catalog can translate it to the Dutch page. Hard-coding the URL in
`ha_fetch.js` would have sent every locale to the English page. The cost is a URL sitting in the
catalogs, which reads oddly to a translator; the block's header comment explains why it is there.

*Why not make it a clickable link?* The status line renders through `el.textContent`, so markup
would appear literally. Making it clickable means changing `setStatus` and auditing its other
callers — more surface than this change needs. The bare URL is visible and copyable, which is
enough to act on.

## Files Modified

- `docs/en/troubleshooting.md` — new "Test connection fails with a certificate error" section
  covering the cause, the two cases where it does not arise, per-platform steps for
  macOS/Linux/Windows, and why a browser exception does not carry over; header comment extended.
- `docs/nl/probleemoplossing.md` — the Dutch counterpart of all of the above.
- `app/static/ha_fetch.js` — rewrote the `ws_connect_failed` message; added a comment recording
  why it must not say "your browser" and why it lists causes instead of naming TLS.
- `app/templates/workspace_data.html` — new `docs_troubleshooting` string; reworded
  `ws_connect_failed`; header comment on why a URL is carried as translatable.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.po` and the compiled
  `.mo` files — the two msgids, with the Dutch URL pointing at the Dutch page.
- `tests/test_i18n.py` — `ws_connect_failed` now carries `docs`, not `url`.

## Obstacles and Solutions

- The existing page had no place for a non-launcher failure — gave the connection problem its own
  section rather than threading it through the log-file narrative.
- A `{# … #}` comment inside the `{% set %}` dict literal is a Jinja syntax error — moved it into
  the block's existing header comment.
- The system `pybabel` is Babel 2.10.3 against the project's 2.18.0, and regenerating with it
  silently dropped 156 unrelated msgids — reverted, and used `uv run pybabel` thereafter.
- Hand-edited catalog entries wrapped differently from Babel's own output — adopted a generated
  `.pot` and matched the `.po` wrapping to it, so the committed files are byte-identical (bar the
  timestamp) to what the documented workflow produces.

## Current Status

Docs, message, catalogs and test updated. `tests/test_i18n.py` passes (80 tests), and a fresh
`pybabel extract` reproduces the committed `.pot` exactly.

Verified: the macOS and Linux (Ubuntu) trust-store steps, both from user reports.

Not verified: the Windows steps, which the page marks as such; and the new message has not been
seen rendered by an actual failing connection — it is covered by the i18n tests, not by an
end-to-end run.

### Possible follow-ups (not decided)

- Link the new section from `docs/en/install.md` / `docs/nl/installatie.md`, where the HA import
  is first described.
- Make the status line render a real link, if the `setStatus` audit above is judged worthwhile.
- Fill in the Windows steps once someone confirms them.
