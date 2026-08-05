<!--
Uitleg over de beveiligingswaarschuwingen per platform (Nederlands). De structuur is bewust
gekozen: één sectie per platform, telkens "wat je ziet" en dan "wat je doet", met alle uitleg
ingeklapt in één <details> aan het eind. Wie tegen zo'n venster aanloopt wil de stappen, niet
de redenering.

Drie dingen die op uitleg lijken staan bewust BUITEN de vouw, omdat het stappen zijn: de
mislukte openpoging die macOS eerst nodig heeft plus het venster van circa een uur, de Windows
"Blokkering opheffen"-omweg, en Smart App Control (het enige geval zonder uitweg).

Gecontroleerd op 2026-08-05 tegen: Apple's Mac-gebruikershandleiding "Open a Mac app from an
unidentified developer" (het pad in Systeeminstellingen, het wachtwoordverzoek, en het venster
van circa een uur waarin de knop beschikbaar is); Microsoft Learn "SmartScreen reputation for
Windows app developers", pagina van 2026-05 (dat ondertekenen de eerste waarschuwing NIET
wegneemt, dat EV SmartScreen niet meer omzeilt, en de hardere blokkade van Smart App Control).
Linux komt uit de eigen verificatie in fase 4-6 van dit project, niet uit leveranciersdocumentatie.

De stappen voor macOS en Windows komen uit die leveranciersdocumentatie en NIET uit het draaien
van de eigen builds op die systemen — de release-jobs daarvoor zijn nieuw. Meldt een lezer een
andere tekst op het scherm, dan weegt die melding zwaarder dan deze pagina.

De vouw bevat bewust alleen wat een handtekening is en wat de controle níét aantoont, met de
verwijzing naar sponsoring als afsluiting. Eerdere versies hadden daar ook de uitleg per
platform en de bronvermelding staan; beide zijn geschrapt vanwege de lengte. De bronvermelding
hierboven is nu de enige vastlegging van waar deze beweringen vandaan komen — houd die actueel
zodra de stappen wijzigen.

Toon: deze pagina mag niet lezen als "klik maar door die enge melding heen".
Register: informeel je/jouw, conform changelog/20260725-nl-register-consistency.md.
Engelse tegenhanger: ../en/security-warnings.md.
-->

# Beveiligingswaarschuwingen bij het openen van de app

De app is niet digitaal ondertekend, dus macOS en Windows waarschuwen je de eerste keer dat je
hem opent. Op Linux krijg je geen waarschuwing en hoef je niets te doen. Voor het downloaden en
uitpakken zelf, zie [Installeren en starten](installatie.md).

**Direct naar jouw platform:** [macOS](#macos) · [Windows](#windows) — of lees
[waarom deze waarschuwingen verschijnen](#waarom).

## macOS

**Wat je ziet:** een venster dat zegt dat de app niet geopend kan worden omdat hij van een
niet-geverifieerde ontwikkelaar komt, of dat Apple niet heeft kunnen controleren of er geen
malware in zit. De enige knoppen zijn iets als **Gereed** (Done) en **Verplaats naar
prullenmand** (Move to Trash) — een "Open toch" staat er hier niet bij.

Met de rechtermuisknop op de app klikken en **Open** kiezen, de omweg die in veel oudere
handleidingen nog staat, werkt niet meer. Apple heeft die in macOS 15 verwijderd.

**Wat je doet:**

1. **Probeer de app te openen en klik de weigering weg.** Sla dit niet over: de knop in stap 3
   verschijnt pas nadat macOS een geblokkeerde poging heeft genoteerd.
2. Ga naar **Systeeminstellingen** (System Settings) → **Privacy en beveiliging** (Privacy &
   Security), en scroll naar het kopje **Beveiliging** (Security).
3. Zoek de regel met de naam van de app en klik op **Open toch** (Open Anyway). Die blijft maar
   *ongeveer een uur* na de geblokkeerde poging staan; staat de regel er niet, ga dan terug
   naar stap 1.
4. **Voer je inlogwachtwoord in** en bevestig.

Dit doe je één keer. Let wel: zo'n uitzondering maken is de gebruikelijke manier waarop een Mac
malware oploopt, dus het is hier alleen een redelijke stap omdat je weet waar je dit bestand
vandaan hebt gehaald — kun je niet verklaren waar jouw kopie vandaan komt, open hem dan niet.

## Windows

**Wat je ziet:** een blauw venster van Microsoft Defender SmartScreen, **"Windows heeft uw pc
beveiligd"**, met de mededeling dat het starten van een onbekende app is voorkomen. De enige
zichtbare knop is **Niet uitvoeren** (Don't run).

**Wat je doet:** klik op het kleine linkje **Meer informatie** (More info) boven de knop, en
daarna op **Toch uitvoeren** (Run anyway). Geen wachtwoord, geen instellingen, geen tijdslimiet.

Verschijnt **Toch uitvoeren** niet, dan staat het bestand mogelijk nog als geblokkeerd
gemarkeerd: rechtermuisknop → **Eigenschappen** → onderaan het tabblad Algemeen **Blokkering
opheffen** (Unblock) aanvinken → **OK**, en probeer het opnieuw.

Eén geval heeft geen uitweg: **Smart App Control**, dat aanstaat bij een schone installatie van
Windows 11, blokkeert niet-ondertekende programma's zonder meer en biedt geen "Toch uitvoeren".
Daar is geen omweg voor zolang de app niet ondertekend is.

## Waarom

<details>
<summary>Waar deze waarschuwingen eigenlijk op controleren</summary>

macOS en Windows zien het liefst dat een programma een **digitale handtekening** draagt: een
stempel die je koopt bij Apple of bij een certificaatuitgever, en die het bestand koppelt aan
een identiteit die zij hebben gecontroleerd. Deze app is niet ondertekend, dus de
waarschuwingen zeggen eigenlijk: *bij dit programma zit geen handtekening, dus ik kan je niet
vertellen wie het gemaakt heeft*.

Ze zeggen **niet** dat de app onderzocht is en gevaarlijk bleek. De controle gaat over herkomst,
niet over inhoud — een niet-ondertekend eerlijk programma en een niet-ondertekend kwaadaardig
programma zijn voor deze systemen niet uit elkaar te houden, en precies daarom waarschuwen ze in
plaats van te beslissen.

Wil je van de beveiligingswaarschuwingen af, overweeg dan om [het project te
steunen](sponsor.md).

</details>
