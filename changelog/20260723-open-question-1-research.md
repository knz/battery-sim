# 20260723 — Research: open question §8.1, feed-in reference for dynamic contracts

## Task specification

Research-only task (no spec edits). Establish, from primary sources where possible:

1. The legal definition of "kale leveringsprijs" and where it lives.
2. How the 50% feed-in floor applies to DYNAMIC (spot-following) contracts.
3. What Dutch suppliers actually do in practice, pre- and post-2027.
4. Most important: whether the question is settled in law at all for the post-2027
   regime, or genuinely undetermined pending legislation / ACM rulemaking / supplier
   practice that does not yet exist.

Explicit instruction: do not manufacture a resolution. "Not settled" is an acceptable
and useful outcome if evidenced.

## Scope constraints

- No spec file may be edited. This changelog is the only file written.
- Primary sources preferred: wetten.overheid.nl, acm.nl, rijksoverheid.nl,
  officielebekendmakingen.nl (Kamerstukken), supplier terms.
- Secondary sources allowed for orientation and supplier practice, labelled as such.
- Today is 2026-07-23; post-early-2026 material is what matters. Training data is not
  to be relied on for current law.

## Context read

- `specs/17-open-questions.md` §8.1 (and §8.14, the related assessment-period question)
- `specs/10-pricing.md` §6.5 — `bare_supply_price()`, `export_price_net()`,
  `feedin_floor_topup()`, the (α, β) preset table
- `specs/18-dutch-electricity-background.md` — E2.1 (bill build-up), E5.1–E5.3 (2027
  regime), E7 (what is not yet known; row 5 is this question)

The spec's current position: `bare = spot + markup` for import (E2.1 arguably treats
`inkoopvergoeding` as a separate additive term, while `bare_supply_price()` folds
`supplier_markup` into `bare`), and α = 0.50 applied to that same `bare` for export.
Flagged in-spec as a choice, not a finding.

## Findings

### The operative provision is in the Energiewet, not the Elektriciteitswet

Correction to a background-doc assumption: the vehicle is the **Energiewet** (in force
1 Jan 2025), amended by the *Wet beëindiging salderingsregeling* (Kamerstukken 36.611).
The 50% floor sits in **artikel 2.34, achtste lid Energiewet**, inserted by amendment
**36611 nr. 17** (Grinwis/Rooderkerk/Erkens, 4 Nov 2024).

### The statutory wording contains no "kale" and no "exclusief belastingen"

Verbatim (Kamerstuk 36611 nr. 17, primary):

> "Indien een marktdeelnemer een leverings- en terugleveringsovereenkomst heeft met een
> actieve afnemer, dan bedraagt de redelijke vergoeding, bedoeld in het zevende lid, tot
> 1 januari 2030 niet minder dan 50% van de voor de te leveren elektriciteit
> overeengekomen prijs."

The base is "de voor de te leveren elektriciteit **overeengekomen prijs**" — the agreed
price for the electricity to be supplied. The words *kale leveringsprijs* are a gloss
applied downstream by the ministry, ACM communications, suppliers and press; they are
not the statutory term. The statute does not define the contract-price base component-
wise, and does not contemplate time-varying (spot-following) prices at all.

### ACM asked for exactly this to be defined, and was not given it

ACM advice on the bill, 17 Sep 2024 (primary, acm.nl):

> "De ACM constateert in de UHT dat het begrip 'redelijke terugleververgoeding' niet in
> het wetsvoorstel wordt gedefinieerd."
> "De ACM adviseert daarom om in het wetsvoorstel toe te lichten wat een redelijke
> terugleververgoeding is, zodat dit voor iedereen duidelijk is."

The adopted amendment supplied a *floor* (50% of the agreed price) but not a
*definition* of the base. The gap ACM flagged is the gap §8.1 sits in.

### No ACM instrument resolves the dynamic case

- Besluit modelcontracten 2026 (ACM, 12 Dec 2025) regulates terugleverkosten (must be
  per fed-in kWh) and requires model contracts; model contracts are *variabel* and
  *vast* only — dynamic contracts are outside the model-contract regime.
- No ACM leidraad, interpretation note, published decision or dispute on the dynamic
  base was located.

### Rulemaking is live and very recent

Wijzigingsregeling Energieregeling, internetconsultatie published 15 Jun 2026, closed
**10 Jul 2026** (13 days before this task), status "gesloten" — responses not yet
processed. It governs *presentation and invoicing* of terugleverkosten (uniform €/kWh)
and bars netting the vergoeding against the kosten. It does not, on the material found,
define the 50% base for dynamic contracts.

### Supplier practice does not settle it, structurally

Pre-2027 dynamic practice (keuze.nl, 21 Jul 2025 upd. 19 Jun 2026, secondary) splits
three ways on the feed-in side: markup **added** (Frank +1.82 ct, Zonneplan +2 ct,
NextEnergy bonus), **absent** (Budget Thuis, Coolblue: kale marktprijs), **subtracted**
(Tibber −2.48 ct, Essent/Eneco −2.5/−2.9 ct outside saldering). All three sit far above
0.5·(spot+markup), so the floor never binds and practice generates no evidence about
the base. No supplier has published binding post-2027 terms.

## Obstacles

- No PDF text extraction available (no pdftotext/poppler/pypdf); the ACM model-contract
  decision and the consultation regulation could only be read via secondary reporting
  and ACM HTML pages. Their operative text was not verified verbatim.
- Post-2027 tariffs do not exist yet, so "what suppliers do" has no post-2027 answer to
  find — a real finding, not a search failure.

## Current status

Research complete; reported to caller. No spec files modified. Conclusion: §8.1 is
**not answerable from available evidence** — the ambiguity is in the statute itself,
the regulator identified it and did not get it closed, and no practice exists that
would disambiguate it. Recommendation is to record it as undetermined with the
determining events named, not to pick a reading.

---

## Addendum (same day) — PDF text now extractable; operative texts verified verbatim

The obstacle recorded above (no PDF text extraction) is resolved: `mutool draw -F txt`
(/usr/bin/mutool) and pypdf in a venv both work. This addendum records a narrow
follow-up pass whose only purpose was to read the operative text of the two documents
that the first pass could only reach through HTML/secondary reporting, and to search
them for a determination of the 50% base for dynamic (spot-following) contracts. No
new web research beyond locating and downloading these two documents. No spec files
edited.

### Document 1 — ACM Besluit modelcontracten 2026

- URL: https://www.acm.nl/system/files/documents/besluit-vaststelling-modelcontracten.pdf
- Real PDF (43 pages, PDF 1.7). Both `mutool` and pypdf extracted it; text agrees.
- Decision of 12 December 2025, kenmerk ACM/UIT/664047, zaak ACM/24/190808, in force
  1 January 2026, cited as "Besluit modelcontracten 2026" (art. 4). Signed drs. M.R.
  Leijten. Structure: 5 articles, then a toelichting, then Bijlage 1 (modelcontract
  bepaalde tijd / vaste tarieven) and Bijlage 2 (onbepaalde tijd / variabele tarieven).

**Keyword search results** (line refs are to the extracted text; page refs from pypdf):

| term | hits | where |
|---|---|---|
| "overeengekomen prijs" | 3 | model contract text pp. 7, 19; toelichting rn. 20 (p. 34) |
| "kale" (as leveringstarief/leveringsprijs) | 5 | pp. 7, 19, 31, 34, and rn. 65 |
| "leveringstarief" | 6 | model contracts + rn. 63, 65 |
| "leveringsprijs" | 3 | toelichting rn. 4, rn. 21, rn. 65 |
| "dynamisch"/"dynamische" | 4 | rn. 53–55 only (p. 39) |
| "50%" | 11 | model contracts pp. 7, 19; toelichting rn. 4, 20, 21; zienswijzen rn. 64–66 |
| "redelijke vergoeding" | 9 | throughout |
| "terugleververgoeding" | 34 | throughout |
| "beursprijs", "spotprijs", "inkoopvergoeding", "marktprijs" | 0 | — |

**The one passage that directly addresses the base** — toelichting, randnummers 64–66,
under the heading "50% regel in wet tot beëindiging van de salderingsregeling":

> "64. Uit verschillende reacties op de zogenaamde 50% regel, maakt de ACM op dat er
> onduidelijkheid bestaat over de 50%-regel die tussen 1 januari 2027 en 1 januari 2030
> geldt.
>
> 65. De 50%-regel houdt in dat de terugleververgoeding vanaf het moment dat de
> wettelijke salderingsregeling wordt afgeschaft op 1 januari 2027 tot en met 1 januari
> 2030 minimaal 50% van de voor de levering van elektriciteit overeengekomen
> leveringsprijs bedraagt. Dit betreft het kale leveringstarief, dus het leveringstarief
> per kWh zonder energiebelasting en btw.[13] Dit laatste volgde nog niet duidelijk uit
> de tekst van het concept besluit dat ter consultatie was voorgelegd, dus dit heeft de
> ACM verduidelijkt in het besluit.
>
> 66. Deze 50%-regel volgt uit de Wet tot beëindiging van de salderingsregeling. Deze
> regel is vastgesteld door de wetgever en niet door de ACM en de ACM kan deze regel dus
> ook niet aanpassen of wijzigen. Deze minimumvergoeding geldt voor elk type contract en
> dus niet specifiek voor de modelcontracten."

Footnote 13 = Kamerstukken EK 2024/25, Nota naar aanleiding van het verslag, 36611, D.

English: (64) ACM infers from various responses that there is uncertainty about the 50%
rule. (65) The rule means the feed-in compensation is at least 50% of the supply price
agreed for the supply of electricity. This concerns the *kale leveringstarief*, i.e. the
supply tariff per kWh without energy tax and VAT. That last point did not yet follow
clearly from the draft decision put out to consultation, so ACM clarified it in the
decision. (66) The rule follows from the statute, was set by the legislator not ACM, ACM
cannot change it, and this minimum applies to *every type of contract*, not specifically
to the model contracts.

The same gloss appears in the model contract text itself, identically in both annexes
(p. 7 fixed-price, p. 19 variable-price), under "Terugleveren van elektriciteit":

> "In de Energiewet is geregeld dat deze redelijke vergoeding tussen 1 januari 2027 en 1
> januari 2030 minimaal 50% bedraagt van de voor de te leveren elektriciteit
> overeengekomen prijs (kale leveringstarief per kWh zonder energiebelasting en btw)."

And in toelichting rn. 4 and rn. 21, with "(exclusief btw en energiebelasting)".

**What this does and does not settle.** It is the first primary-source instrument found
that glosses the statutory "overeengekomen prijs". The gloss is *exclusively
tax-directional*: it subtracts energiebelasting and btw and says nothing about whether
the remaining supply tariff includes or excludes a supplier markup / inkoopvergoeding.
The words "inkoopvergoeding", "beursprijs", "spotprijs", "marktprijs" do not occur
anywhere in the 43-page document. There is no formula and no worked example for the
feed-in floor. So on the specific question — for a dynamic contract, is the base the
hourly spot price alone or spot plus markup — the decision is silent.

Rn. 66 is materially relevant but not dispositive: "Deze minimumvergoeding geldt voor
elk type contract" confirms the 50% floor *binds* dynamic contracts (they are not
carved out), which is a point the prior pass had left slightly open. It does not tell
you what the base is for them.

**Dynamic contracts are addressed only to exclude them from the model-contract regime**
(rn. 53–55, p. 39):

> "54. Meerdere partijen hebben de vraag gesteld of de ACM ook een modelcontract voor
> dynamische energieleveranciers opstelt.
>
> 55. De Energiewet bepaalt dat de ACM een modelcontract voor bepaalde tijd met vaste
> tarieven opstelt én een modelcontract voor onbepaalde tijd met variabele tarieven. De
> Energiewet schrijft niet voor dat de ACM ook een modelcontract voor de levering van
> elektriciteit en/of gas tegen dynamische prijzen opstelt. De ACM zal dan ook geen
> modelcontract voor levering tegen dynamische prijzen vaststellen."

**Against the prior pass's characterisation:** confirmed on both points, now from the
operative text rather than from ACM HTML pages and a secondary source.
- Two model contracts only, vast (bepaalde tijd) and variabel (onbepaalde tijd) —
  art. 1 of the besluit; dynamic explicitly excluded — rn. 55.
- Terugleverkosten as a separate tariff component per fed-in kWh — rn. 22 introduces
  the component; rn. 23 onward gives ACM's cost reasoning.
One refinement: the prior pass said "no ACM instrument resolves the dynamic case". That
stands, but the besluit is not silent on the base generally — rn. 65 supplies the
tax-exclusive reading, and rn. 66 confirms the floor applies to dynamic contracts. It
simply stops short of the markup question.

Also noted, adjacent and possibly relevant to §8.14 (assessment period), rn. 70:

> "Na de beëindiging van de wettelijke salderingsregeling, mag de terugleververgoeding
> gemiddeld gewogen over een periode van een maand niet negatief zijn."

(The feed-in compensation may not be negative when weighted-averaged over a one-month
period — footnoted to art. I.C lid 7 of Stb. 2025, 17.) Recorded as an observation; it
was not the object of this pass and has not been checked against the statute directly.

### Document 2 — Wijzigingsregeling Energieregeling (consultation draft)

- Consultation page: https://www.internetconsultatie.nl/wijzigingsregeling_energieregeling_en_regeling_gvo/b1
- Document: "Concept Wijzigingsregeling met Toelichting",
  https://www.internetconsultatie.nl/wijzigingsregeling_energieregeling_en_regeling_gvo/document/15770
  (document/15771, listed as "Effectentoets in hoofdstuk 3", is a different file by
  checksum but extracts to byte-identical text — it is the same document, second link).
- Real PDF, 9 pages, PDF 1.7. `mutool` extracted cleanly; whole document read.
- Published 15 Jun 2026, closed 10 Jul 2026, status gesloten, 9 public reactions.
- Full title: "Regeling van de Minister van Klimaat en Groene Groei van [datum], nr.
  WJZ/106158659, tot wijziging van de Energieregeling in verband met presenteren en
  factureren terugleverkosten en tot wijziging van de Regeling garanties van oorsprong".
  Legal basis: art. 2.7 lid 2 Energiewet; art. 2.8 lid 3 and 2.10 lid 3 Energiebesluit.

**Post-consultation status: not yet finalised.** The draft's own toelichting §4.1 still
reads "In totaal hebben [PM aantal] partijen een consultatiereactie ingediend", and §5.1
/ §5.2 record only that the draft was submitted to ACM (UHT) and ATR on 15 Jun 2026 with
no outcomes filled in. No Staatscourant publication of the final text was found. As
expected thirteen days after close.

**Operative text is short.** Article I has four parts:
- A: new art. 2.2a Energieregeling — "Een marktdeelnemer geeft bij het presenteren van
  de kosten en voorwaarden met betrekking tot het terugleveren van de door een actieve
  afnemer zelfopgewekte hernieuwbare elektriciteit aan, op welke wijze deze kosten
  worden berekend." (must state *how* the terugleverkosten are calculated).
- B: new art. 2.6 lid 1 sub h — terugleverkosten on the invoice "uitgedrukt in € per
  teruggeleverde kWh", for active customers who are also household or micro-enterprise.
- C: technical cross-reference correction in art. 2.10 lid 2 sub d.
- D: new art. 2.28 lid 2 sub j — multi-site contract administration.
Article II corrects the Regeling garanties van oorsprong. Article III: in force
1 January 2027 (except I.C and II, day after publication).

**Keyword search results over the full 9-page text (articles + toelichting):**

| term | hits |
|---|---|
| "overeengekomen prijs" | 1 (toelichting §2.1, p. 5) |
| "redelijke vergoeding" | 1 (same sentence) |
| "50%" | 1 (same sentence) |
| "terugleververgoeding" | 3 (p. 5 once, p. 6 twice) |
| "kale" | 0 (the single grep hit is the substring in "lokale vestigingen") |
| "leveringsprijs", "leveringstarief" | 0 |
| "dynamisch"/"dynamische" | 0 |
| "beursprijs", "spotprijs", "inkoopvergoeding", "marktprijs" | 0 |

**The only passage touching the 50% floor** — toelichting §2.1, p. 5:

> "Echter, de kosten die de marktdeelnemer maakt omdat hij moet voldoen aan artikel
> 2.34, zevende en negende lid, van de Energiewet zoals die per 1 januari 2027 geldt,
> vallen hierbuiten. Op grond van die leden moet de marktdeelnemer voor de
> teruggeleverde elektriciteit een redelijke vergoeding betalen aan de actieve afnemer,
> waarbij geldt dat de vergoeding tot 1 januari 2030 niet minder dan 50% van de voor de
> te leveren elektriciteit overeengekomen prijs mag zijn. De kosten die de
> marktdeelnemer hiervoor maakt, mag hij dus niet betrekken bij de terugleverkosten. Ook
> de terugleververgoeding zelf mag niet worden verrekend in de terugleverkosten."

English: The costs the supplier incurs in complying with art. 2.34 lid 7 and 9
Energiewet fall outside [the terugleverkosten]. Under those paragraphs the supplier must
pay a reasonable compensation for fed-back electricity, at not less than 50% of the
agreed price for the electricity to be supplied until 1 Jan 2030. The costs the supplier
incurs for this may therefore not be counted in the terugleverkosten. Nor may the
feed-in compensation itself be netted against the terugleverkosten.

This restates the statutory phrase without decomposing it, and adds no gloss — it does
not even carry ACM's "kale / exclusief belastingen" reading. Its actual subject is the
firewall between terugleverkosten and terugleververgoeding, not the base.

Note also the numbering: the toelichting cites **art. 2.34 lid 7 and lid 9** Energiewet
as the source of the reasonable-compensation duty and the 50% floor, and ACM's besluit
footnotes the floor to art. I.C **lid 9** of Stb. 2025, 17. The prior pass recorded the
floor at art. 2.34 **lid 8** (from amendment 36611 nr. 17 as tabled). Amendment
renumbering on adoption is the obvious explanation, but this has not been verified
against the consolidated Energiewet text and should be checked before any spec cites a
paragraph number.

The one formula in the document (toelichting §2.1, p. 6) concerns terugleverkosten
presentation, not the feed-in floor:

> "T(t) = K(t) / E_invoeding(t)" — T terugleverkosten in €/kWh, K costs under the
> supplier's chosen tariff structure in €, E_invoeding the fed-in volume in kWh, t the
> invoice period.

**Against the prior pass's characterisation:** confirmed exactly. It governs presentation
and invoicing (uniform €/kWh), bars netting the vergoeding against the kosten, and does
not define the 50% base for dynamic contracts. The prior pass's assessment that this was
"the most likely place a clarification would appear" was reasonable, and the answer is
that the clarification is not there.

### Verdict

Neither document resolves the dynamic-contract base.

- The ACM Besluit modelcontracten 2026 supplies a partial gloss — "kale leveringstarief
  per kWh zonder energiebelasting en btw" (rn. 65) — which fixes the base as
  tax-exclusive, and confirms the floor applies to every contract type including
  dynamic (rn. 66). It says nothing about supplier markup / inkoopvergoeding, gives no
  formula and no worked example, and explicitly declines to produce a dynamic model
  contract (rn. 55).
- The consultation Wijzigingsregeling restates the statutory phrase once, verbatim and
  undecomposed, in a passage whose subject is something else. The final post-
  consultation text is not yet published.

The §8.1 conclusion recorded above therefore stands, now on verified operative text
rather than on secondary sourcing: for a dynamic contract, whether the 50% base is the
hourly spot price alone or spot plus markup is undetermined in the instruments that
exist as of 2026-07-23. What the addendum adds is (i) the base is at least
tax-exclusive, on ACM's own reading, and (ii) the floor is not carved out for dynamic
contracts. What remains open is the markup component only.

Files written: this changelog only. No spec files modified.
