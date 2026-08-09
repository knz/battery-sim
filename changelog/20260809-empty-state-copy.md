# Empty-state copy on the analyses list

## Task Specification

Review the explanatory sentence shown in the empty state of the analyses list
(`app/templates/workspaces.html`) for legibility, then apply the chosen rewrite.

Original text:

> An analysis is one household and one question: your data, your contract, and the
> battery you are considering.

## Review findings

- The colon sets up a definition, but the clause after it enumerates three inputs
  rather than restating the equation. A reader looking for "the question" in the
  list does not find it.
- "one question" is undefined at this point in the flow. This is the empty state:
  the user has not seen the app yet and does not know which question it answers.
  The actual question is never stated on this screen.
- "one household and one question" is really a scoping hint (why you would create
  more than one analysis), phrased as a definition.
- Register mismatch: the surrounding lines are plain and concrete; this is the only
  aphoristic one, and it carries the explanatory load.
- "the battery you are considering" breaks the parallelism of the three-item list
  and ends the sentence on its longest, least parallel item.
- The aphoristic shape (colon-as-definition, "one X and one Y") translates poorly;
  the Dutch catalogue already carries it.

## High-Level Decisions

Chose the rewrite that states the question outright:

> An analysis answers one question for one household: what would this battery have
> saved you, on your data and your contract?

Rationale: the empty state is where naming the question earns its space, and it is
the one thing the previous sentence gestured at without saying. Alternatives
considered: a minimal fix keeping the original shape but dropping "question"
("Each analysis covers one household and one battery: ..."), and a plainer version
with no colon. Both were lower-risk but left the app's central question unstated.

## Files Modified

- `app/templates/workspaces.html` — replaced the empty-state subtitle.
- `app/locales/messages.pot`, `app/locales/en/...messages.po`,
  `app/locales/nl/...messages.po` — catalogue update for the changed msgid;
  Dutch translation supplied.
- `.mo` files recompiled.

## Current Status

Applied. Extraction, translation, and compilation done.
