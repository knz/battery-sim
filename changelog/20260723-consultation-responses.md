# 20260723 — Consultation responses (Wijzigingsregeling Energieregeling) + statutory citation check

## Task specification

Research-only. Two tasks, following on from `changelog/20260723-open-question-1-research.md`
(read in full; its findings are not repeated here).

1. **Primary:** retrieve and read all nine public reactions to the internetconsultatie
   "Wijziging van de Energieregeling in verband met presenteren en factureren
   terugleverkosten … en Regeling garanties van oorsprong"
   (https://www.internetconsultatie.nl/wijzigingsregeling_energieregeling_en_regeling_gvo/b1),
   published 15 Jun 2026, closed 10 Jul 2026. For each: submitter, date, and whether it
   bears on (a) the 50% feed-in floor and its base, (b) dynamic/spot-following contracts,
   (c) supplier markup / inkoopvergoeding in relation to the floor, (d) any request to
   clarify "overeengekomen prijs".
2. **Secondary:** verify against the consolidated Energiewet on wetten.overheid.nl which
   lid of art. 2.34 carries the 50% floor. Amendment 36611 nr. 17 as tabled said **lid 8**;
   the ACM Besluit and the Wijzigingsregeling toelichting cite **lid 7** (duty) and
   **lid 9** (floor).

## Scope constraints

- File-conflict constraint from the caller: another agent concurrently owns
  `specs/19-prototype-experiments.md`, `specs/17-open-questions.md`, `specs/README.md`,
  `changelog/20260723-prototype-experiments.md`. This changelog is the ONLY file written.
  No file under `specs/` was touched.
- Primary sources; secondary labelled. Verbatim Dutch quotes with English rendering.
- Do not manufacture a finding; "none of the nine addresses it" is a valid outcome.

## Method

- Consultation reactions index fetched by `curl`
  (`.../wijzigingsregeling_energieregeling_en_regeling_gvo/reacties`); nine reaction UUIDs
  extracted from the raw HTML, matching the "[9]" count shown on the page.
- Each of the nine detail pages downloaded by `curl` and the response body extracted from
  the HTML. Five carry inline answers to the two consultation questions; four carry a
  PDF attachment and no inline text.
- Attachment links follow the pattern `/reactie/<numeric-id>/bestand`, recovered from the
  raw HTML (they are not exposed as `.pdf` hrefs). All four PDFs downloaded and extracted
  with `mutool draw -F txt`; cross-checked with pypdf where the layout was multi-column.
- All nine texts keyword-scanned for the terms listed in the task.

**Retrieval was complete: nine of nine responses obtained in full text.** No response was
inaccessible, truncated, or substituted with a summary.

## Findings — the nine responses

Order as listed on the consultation page (most recent first). "Bears on §8.1" means:
does it say anything about the 50% floor's base, dynamic contracts, or supplier markup.

### 1. Energie-Nederland (R. Kaljee), Den Haag — 10 Jul 2026 — PDF attachment

The sector trade body for energy suppliers. Two pages. The only industry-side submission.

Bears on §8.1: **no, not on the base.** It does not use the words "overeengekomen prijs",
"kale", "leveringsprijs", "leveringstarief", "dynamisch", "beursprijs", "spotprijs",
"marktprijs" or "inkoopvergoeding" anywhere. "terugleververgoeding" occurs once, only to
observe that a €/kWh presentation makes the terugleverkosten comparable *with* it:

> "Het op de afrekening (ook) opnemen van de terugleverkosten in een euro/kWh helpt daarbij
> en zijn deze daarmee ook te vergelijken met de terugleververgoeding."

(Including the terugleverkosten on the bill in euro/kWh helps, and makes them comparable
with the feed-in compensation.)

**One passage is adjacent and worth recording**, because it is the closest any respondent
comes to the contract-type dimension — but it concerns the *presentation* obligation, not
the floor:

> "De verplichtingen gelden voor alle soorten contracten, ongeacht de prijsstructuur. Dit
> lijkt nu niet benoemd te worden. Hiervoor zou bijvoorbeeld in de volgende bestaande zin
> de cursieve tekst kunnen worden toegevoegd: 'Hoe de marktdeelnemer aan deze verplichting
> voldoet is afhankelijk van het type actieve afnemer, *de kenmerken van het contract* en
> de gekozen berekeningswijze van de marktdeelnemer.'"

(The obligations apply to all types of contract, regardless of price structure. This does
not appear to be stated. The italicised words "the characteristics of the contract" could
be added to the existing sentence.)

This is Energie-Nederland asking for confirmation that the *terugleverkosten presentation
and invoicing* duty is price-structure-neutral — i.e. that it also covers dynamic
contracts. It says nothing about the 50% base. Its other two points are: clarify why
art. 2.6 (aggregation-contract invoice) rather than art. 2.5 is amended, and defer the
€/kWh presentation duty to 1 Jan 2027 rather than applying it to 2026 costs.

### 2. Anoniem, Amersfoort — 10 Jul 2026 — PDF attachment

The attachment identifies the submitter as **Vereniging Eigen Huis** (homeowners'
association; contact Karin Boog, k.boog@eigenhuis.nl) — the anonymity is only on the index
page. Two pages.

Bears on §8.1: **no.** None of the scanned terms occurs. Entirely about comparability of
terugleverkosten: supports the €/kWh presentation, but wants staffels and fixed monthly
amounts banned outright in statute, and full standardisation of terms and bill layout.

> "Er mag wat Vereniging Eigen Huis betreft alleen nog maar gerekend worden met € per
> teruggeleverde kWh."

(As far as Vereniging Eigen Huis is concerned, only € per fed-in kWh may be charged.)

### 3. Anoniem, Best — 9 Jul 2026 — inline text

Individual. **The only response that quotes the 50% floor.** Bears on §8.1 **partially,
but not on the dynamic base.**

> "Daarnaast roept de wettelijke eis van een 'redelijke vergoeding' vragen op. Vanaf 2027
> geldt een minimumvergoeding van 50% van de overeengekomen leveringsprijs. Naar mijn
> mening is het moeilijk om dit een eerlijke vergoeding te noemen. Als een leverancier
> slechts de helft van de leveringsprijs hoeft uit te keren, vertegenwoordigt de
> teruggeleverde elektriciteit voor de leverancier minimaal twee keer zoveel economische
> waarde als de vergoeding die de consument ontvangt."

(Furthermore the statutory requirement of a "reasonable compensation" raises questions.
From 2027 a minimum compensation of 50% of the agreed supply price applies. In my view it
is hard to call this a fair compensation. If a supplier need pay out only half the supply
price, the fed-in electricity represents at least twice as much economic value to the
supplier as the compensation the consumer receives.)

> "Bovendien kunnen energieleveranciers naast deze minimumvergoeding nog steeds
> terugleverkosten in rekening brengen. Daardoor kan de netto vergoeding zelfs uitkomen op
> nul of negatief worden. … Daarmee wordt de wettelijke ondergrens van 50% in de praktijk
> eenvoudig uitgehold."

(Moreover suppliers may still charge terugleverkosten on top of this minimum compensation.
The net compensation can therefore even come out at zero or negative. … The statutory 50%
floor is thereby easily hollowed out in practice.)

Note the wording: "50% van de overeengekomen **leveringsprijs**" — the respondent's own
paraphrase, not a statutory term; the statute says "de voor de te leveren elektriciteit
overeengekomen prijs". No decomposition into spot vs markup is offered or requested. The
complaint is that the floor is too low and is circumvented by terugleverkosten, not that
its base is undefined. Dynamic contracts are not mentioned.

### 4. Holland Solar (MC Gütle), Utrecht — 6 Jul 2026 — PDF attachment

Trade body for the solar sector. One page (verified complete: pypdf and mutool both
report a single page; the text ends after the section on per-kWh terugleverkosten).

Bears on §8.1: **no.** None of the scanned terms occurs; the 50% floor is not mentioned at
all. The submission welcomes the €/kWh rule and notes the cost-allocation consequence:

> "Kosten die energieleveranciers maken voor het terugleveren moeten dus vanaf 2027 geheel
> worden betaald door de klanten die terugleveren. … Hierdoor worden de terugleverkosten
> definitief een doorslaggevende kostenfactor voor consumenten met zonnestroominstallaties."

(Costs suppliers incur for feed-in must therefore from 2027 be borne entirely by the
customers who feed in. … Terugleverkosten thereby definitively become a decisive cost
factor for consumers with PV installations.)

### 5. Zonnestroomproducentenvereniging (mr. B.A.G. Scholte Lubberink), Joure — 5 Jul 2026 — PDF attachment

PV producers' association. Two pages, the most legally detailed of the nine.

Bears on §8.1: **no.** None of the scanned terms occurs; the 50% floor is not mentioned.
Its subject is entirely the *terugleverkosten* side. It argues proposed art. 2.2a is too
weak (stating *how* costs are calculated is not enough; the customer needs the grounds,
cost types, periods, data and data provenance, plus an enforceable right to verify), asks
that the Energieregeling set out **exhaustively** which cost elements may count as
terugleverkosten, and proposes adding to art. 2.6 sub h:

> "…uitgedrukt in € per teruggeleverde kWh, waarbij iedere andere vorm van doorbelasting
> van kosten met betrekking tot deze teruglevering is uitgesloten."

(…expressed in € per fed-in kWh, whereby any other form of passing on costs relating to
this feed-in is excluded.)

Also asks that ACM be required to supervise actively and publish findings twice yearly.

### 6. Anoniem, Wijk bij Duurstede — 1 Jul 2026 — inline text

Individual. **The only response containing the word "dynamisch"** — and it does not raise
the base question. Bears on §8.1 **only obliquely.**

> "Als de afspraak is dat minimaal 50% van de minimale kale energieprijs moet worden
> vergoed, dan moet dat ook minimaal worden vergoed en niet wegstrepen tegen een
> terugleverkostenvergoeding."

(If the agreement is that at least 50% of the minimum bare energy price must be
compensated, then that must actually be paid as a minimum and not netted off against a
terugleverkosten charge.)

> "Terugleveren levert na deze aanpassingen niks meer op (1 cent per kWh, waar dit voorheen
> zo'n 25 cent per kWh was voor het deel je kon salderen), tenzij je een dynamisch contract
> hebt."

(After these changes feed-in yields nothing (1 cent per kWh, where it was previously some
25 cent per kWh for the part you could net off), unless you have a dynamic contract.)

The "dynamisch" mention is an aside about dynamic contracts being the remaining
worthwhile option, not a question about how the floor applies to them. "kale energieprijs"
appears but is used loosely and without a spot/markup decomposition. The substantive ask
is the same as respondent 3's: the floor should not be netted against terugleverkosten —
which is already what the draft toelichting says it does.

### 7. Mw W. A. M. Robles, Broekhuizenvorst — 18 Jun 2026 — inline text

Individual. Bears on §8.1 **only obliquely** — it is the one response that defines what it
means by the base, though for a counterfactual 80% rule rather than the enacted 50% one:

> "In het oorspronkelijke idee, jaren geleden, stond een 80% regel: een leverancier moest
> minimaal 80% van de kale energieprijs (dus zonder netwerk, accijns en btw) terugbetalen
> bij teruglevering. De overige 20% was dan bedoeld om onbalans kosten op te vangen en te
> investeren in opslag van energie. Dat was eerlijk en duidelijk voor iedereen. Laat het
> eventueel 75 of 70% worden, maar houdt dit systeem aan, zonder additionele
> terugleverkosten."

(The original idea, years ago, had an 80% rule: a supplier had to pay back at least 80% of
the bare energy price (so without network, excise and VAT) on feed-in. The other 20% was
meant to cover imbalance costs and to invest in energy storage. That was fair and clear
for everyone. Make it 75 or 70 if need be, but keep this system, without additional
terugleverkosten.)

Note what this gloss subtracts: network charges, tax and VAT — the same tax-exclusive
direction ACM took in Besluit modelcontracten 2026 rn. 65. It says nothing about supplier
markup, and does not address dynamic contracts. It is an individual's recollection, not a
source of law.

### 8. SME (I. Tegels), Utrecht — 17 Jun 2026 — inline text

Bears on §8.1: **no.** Asks that all suppliers settle per kWh so that costs and
compensation can be netted into a single comparable tariff, and criticises the staffel
(volume-band) structures as impossible to compare in advance. Note this asks for exactly
the netting that the draft toelichting forbids — an ask, not a statement of the rule.

### 9. AH management & Advies (AA Hanemaaijer), Westland — 16 Jun 2026 — inline text

Bears on §8.1: **no.** Two short paragraphs, both about guarantees of origin (GvO) being
too complex and obsolete. Contains the phrase "De prijs op de dagmarkt bepaald de fair
prijs elektra" (the day-market price determines the fair price of electricity) — a remark
about GvOs and fossil pricing, not about the feed-in floor. Included here for completeness
because it is the only occurrence of a market-price notion across the nine.

## Keyword scan, all nine responses

| term | responses containing it |
|---|---|
| "overeengekomen prijs" | **0** |
| "overeengekomen" (any) | 1 (nr. 3, as "overeengekomen leveringsprijs") |
| "kale" | 2 (nr. 6 "kale energieprijs", nr. 7 "kale energieprijs") |
| "leveringsprijs" | 1 (nr. 3) |
| "leveringstarief" | **0** |
| "dynamisch"/"dynamische" | 1 (nr. 6, as an aside) |
| "beursprijs" | **0** |
| "spotprijs" | **0** |
| "marktprijs" | **0** |
| "inkoopvergoeding" | **0** |
| "50%" | 2 (nr. 3, nr. 6) |
| "redelijke vergoeding" | 1 (nr. 3) |
| "terugleververgoeding" | 1 (nr. 1, Energie-Nederland) |

## Verdict on Task 1

**No respondent raised the dynamic-contract base as an issue.** Nine of nine read in full.

- Not one response asks what "de voor de te leveren elektriciteit overeengekomen prijs"
  means. The phrase does not appear in any of the nine.
- No response distinguishes spot price from supplier markup on the feed-in side. The words
  "inkoopvergoeding", "beursprijs", "spotprijs" appear nowhere.
- The single mention of dynamic contracts (nr. 6) is an aside that dynamic contracts remain
  the only worthwhile feed-in option — not a question about how the floor applies to them.
- Energie-Nederland, the supplier trade body and the party best placed to flag the gap, did
  raise price-structure neutrality — but about the *presentation and invoicing* duty, not
  the floor. It did not mention the floor's base at all.
- The two responses that engage with the 50% floor (nr. 3, nr. 6) both complain about the
  same thing: that terugleverkosten can be netted against the compensation, hollowing the
  floor out. Both are individuals. Neither questions the base.

This is consistent with the prior passes' conclusion and adds a new, independent line of
support for it: the floor does not currently bind under any dynamic offer, so industry has
no live dispute about its base, and none was voiced when the opportunity existed. Two
caveats on how much weight this carries: (i) this consultation's subject matter is
terugleverkosten presentation and invoicing, not the feed-in floor, so a respondent might
reasonably have judged the base out of scope; (ii) nine responses, only three of them from
organisations, is a small sample. The finding is therefore *consistent with* the industry
not treating the gap as a live problem; it is not proof of it.

## Findings — Task 2: statutory citation verified

**The 50% floor is art. 2.34, negende lid (lid 9) Energiewet.** The prior pass's
"lid 8" (taken from amendment 36611 nr. 17 as tabled) is superseded; the ACM Besluit and
the Wijzigingsregeling toelichting are correct.

Source: consolidated Energiewet, BWBR0050714, wetten.overheid.nl. Two versions retrieved:

- Version in force on 2026-07-01
  (https://wetten.overheid.nl/BWBR0050714/2026-07-01/0/Hoofdstuk2/Afdeling2.3/Artikel2.34):
  art. 2.34 has **five leden only** and contains no feed-in floor and no reasonable-
  compensation duty. The page carries the marker
  "[Toekomstige wijziging(en) voorzien met ingang van: 01-01-2027.]".
- Version as it will read from 2027-01-01 (https://wetten.overheid.nl/BWBR0050714/2027-01-01/0,
  marked "[Wijziging per 01-01-2027]"): art. 2.34 runs to **ten leden**.

Note on locating it: art. 2.34 sits in **Afdeling 2.3** ("Terugleveren, faciliteren in
peer-to-peer-handel en vraagrespons ten behoeve van actieve afnemers"), not Afdeling 2.4,
and its heading is "aggregatieovereenkomsten". A per-article URL for the 2027-01-01 version
404s; only the whole-regulation URL for that date resolves.

Verbatim, art. 2.34 as it reads from 1 January 2027 — the four leden that matter:

> **6** Artikel 2.5, eerste, derde en zesde lid, is van overeenkomstige toepassing op de
> kosten en voorwaarden met betrekking tot het terugleveren van zelfopgewekte hernieuwbare
> elektriciteit door een actieve afnemer aan een marktdeelnemer. Bij of krachtens algemene
> maatregel van bestuur worden in ieder geval regels gesteld over de wijze waarop
> marktdeelnemers deze kosten en voorwaarden op een uniforme wijze presenteren en factureren.
>
> **7** De actieve afnemer ontvangt voor de teruggeleverde elektriciteit een redelijke
> vergoeding, die in het geval van een actieve afnemer met een kleine aansluiting gemiddeld
> gewogen over een periode van een maand niet kan worden vastgesteld op een negatief bedrag.
> Een vergoeding is niet redelijk indien die vergoeding:
> a. onevenredig laag is gezien de kosten en baten van de marktdeelnemer; en
> b. niet concurrerend is.
>
> **8** Kosten die gerelateerd zijn aan het terugleveren van zelfopgewekte hernieuwbare
> elektriciteit door actieve afnemers, die tevens huishoudelijk eindafnemer of een
> micro-onderneming zijn, aan een marktdeelnemer, kunnen uitsluitend in rekening worden
> gebracht bij die actieve afnemers.
>
> **9** Indien een marktdeelnemer een leverings- en terugleveringsovereenkomst heeft met een
> actieve afnemer met een kleine aansluiting, dan bedraagt de redelijke vergoeding, bedoeld
> in het zevende lid, tot 1 januari 2030 niet minder dan 50% van de voor de te leveren
> elektriciteit overeengekomen prijs.
>
> **10** Een actieve afnemer met een kleine aansluiting heeft het recht om zelfopgewekte
> hernieuwbare elektriciteit terug te leveren aan zijn leverancier van elektriciteit.

English (lid 7 and 9): (7) The active customer receives a reasonable compensation for the
electricity fed back, which in the case of an active customer with a small connection
cannot be set at a negative amount when weighted-averaged over a period of one month. A
compensation is not reasonable if it (a) is disproportionately low given the supplier's
costs and benefits, and (b) is not competitive. (9) If a market participant has a supply
and feed-in contract with an active customer with a small connection, the reasonable
compensation referred to in the seventh paragraph amounts, until 1 January 2030, to not
less than 50% of the price agreed for the electricity to be supplied.

Three substantive differences from the amendment text quoted in the prior changelog, which
should be carried into any spec citation:

1. **Numbering:** lid 9, not lid 8. Confirmed against the consolidated text.
2. **Scope narrowed to small connections.** The tabled amendment read "een actieve afnemer";
   the enacted lid 9 reads "een actieve afnemer **met een kleine aansluiting**". For a Dutch
   household this is the normal case (≤3×80 A), so it does not change the simulator's
   applicability, but the spec should not state the floor as applying to all active customers.
3. **The monthly non-negativity rule is statutory and sits in lid 7**, not only in the ACM
   besluit. The prior changelog recorded ACM rn. 70 as an unverified observation relevant to
   §8.14; it is now verified in the statute: "…gemiddeld gewogen over een periode van een
   maand niet kan worden vastgesteld op een negatief bedrag". Also note lid 7's two-limb
   test for unreasonableness (disproportionately low given the supplier's costs and benefits,
   **and** not competitive) — cumulative, conjunctive.

Also confirmed: lid 8 (the enacted one) is the cost-allocation rule that terugleverkosten
may be charged only to the active customers who feed in — the provision Holland Solar's
submission turns on.

**On the §8.1 question itself, the consolidated text changes nothing.** Lid 9 still says
"de voor de te leveren elektriciteit overeengekomen prijs" with no decomposition, and lid 7
gives a reasonableness test framed on the supplier's costs and benefits and on
competitiveness — neither of which resolves whether, for a dynamic contract, the base is
hourly spot alone or spot plus markup.

## Obstacles and solutions

- Attachment URLs on internetconsultatie.nl are not exposed as `.pdf` hrefs. Solved by
  extracting the `/reactie/<numeric-id>/bestand` pattern from raw HTML.
- Two respondents are listed as "Anoniem" on the index; one (Amersfoort) is identifiable
  from its attachment letterhead as Vereniging Eigen Huis. The other (Best) submitted
  inline and remains anonymous.
- `wetten.overheid.nl` returns 404 for per-article URLs at a future date; the whole-
  regulation URL for 2027-01-01 works. Solved by fetching the full text and extracting.

## Current status

Both tasks complete. Nine of nine consultation responses retrieved and read in full; none
raises the dynamic-contract base. Statutory citation verified as art. 2.34 lid 9 Energiewet
(as in force from 1 Jan 2027), with three corrections to the prior pass's citation noted
above. No spec files modified; this changelog is the only file written.
