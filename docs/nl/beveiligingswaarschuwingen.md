<!--
Uitleg over de beveiligingswaarschuwingen per platform (Nederlands). Elke feitelijke bewering
komt uit documentatie van Apple of Microsoft, en die bron staat er ook bij: dit gedrag
verandert per OS-release, en een lezer die iets anders op zijn scherm ziet moet weten waar hij
moet kijken.

Gecontroleerd op 2026-08-05 tegen: Apple's Mac-gebruikershandleiding "Open a Mac app from an
unidentified developer" (het pad in Systeeminstellingen, het wachtwoordverzoek, en het venster
van circa een uur waarin de knop beschikbaar is); Microsoft Learn "SmartScreen reputation for
Windows app developers", pagina van 2026-05 (dat ondertekenen de eerste waarschuwing NIET
wegneemt, dat EV SmartScreen niet meer omzeilt, en de hardere blokkade van Smart App Control).
Linux komt uit de eigen verificatie in fase 4-6 van dit project, niet uit leveranciersdocumentatie.

Toon: deze pagina mag niet lezen als "klik maar door die enge melding heen". Eerst waar de
controle over gaat en wat hij wel en niet weet, dan pas de stappen.
Engelse tegenhanger: ../en/security-warnings.md.
-->

# Beveiligingswaarschuwingen van je besturingssysteem

Afhankelijk van welk systeem je draait, kan het downloaden en openen van deze app een
waarschuwing opleveren voordat hij start. Deze pagina legt uit waar die waarschuwingen op
controleren, wat ze wel en niet zeggen, en hoe je verdergaat.

## Wat "niet ondertekend" betekent

macOS en Windows zien het liefst dat een programma een **digitale handtekening** draagt: een
stempel die je koopt bij Apple of bij een certificaatuitgever, en die het bestand koppelt aan
een identiteit die zij hebben gecontroleerd. Het systeem kan dan twee dingen vaststellen — dat
het bestand van die partij komt, en dat niemand het onderweg heeft aangepast.

Deze app is **niet ondertekend**. Voor die stempel is niet betaald. De waarschuwingen die je
ziet zeggen dus eigenlijk:

> *Bij dit programma zit geen handtekening, dus ik kan je niet vertellen wie het gemaakt heeft.*

Ze zeggen **niet** dat de app onderzocht is en gevaarlijk bleek. De controle gaat over
herkomst, niet over inhoud. Een niet-ondertekend eerlijk programma en een niet-ondertekend
kwaadaardig programma zijn voor deze systemen niet uit elkaar te houden — en precies daarom
waarschuwen ze in plaats van te beslissen.

Dat snijdt aan twee kanten, en daar moeten we eerlijk over zijn: die waarschuwing doet echt
zijn werk. De reden om hier door te gaan is niet dat de melding lastig is, maar dat je de
herkomst zelf kunt nagaan — je weet waar je het bestand vandaan hebt gehaald, de broncode is
openbaar, en je kunt hem desnoods zelf bouwen als je een download liever niet vertrouwt. Kun
je niet verklaren waar jouw kopie vandaan komt, dan is niet openen het juiste antwoord.

[Waarom de app niet ondertekend is, en wat daaraan veranderen zou kosten](sponsor.md).

## Linux: helemaal geen drempel

Linux controleert geen handtekeningen op gedownloade programma's. Zodra je de AppImage met
`chmod +x` uitvoerbaar hebt gemaakt, start hij gewoon. Geen melding, geen bevestiging, geen
instelling die je om moet zetten.

Dit is echt de makkelijkste van de drie, en het is meteen ook het enige platform waarvoor
vandaag een build bestaat. Zie [Installeren en starten](installatie.md).

Het is niet zo dat Linux minder voorzichtig is; software wordt er anders verspreid. Vertrouwen
komt daar normaal gesproken uit de pakketbronnen van je distributie, die als geheel
ondertekend zijn, en niet uit een stempel per bestand dat je van het web plukt. Iets wat je
zelf hebt opgehaald, geldt als je eigen verantwoordelijkheid.

## macOS: de lastigste van de drie

**Er is nog geen macOS-build.** Dit is dus een vooruitblik op wat er gaat gebeuren zodra die er
komt.

Download je een bestand met een browser, dan hangt macOS er een *quarantaine*-markering aan.
Bij de eerste keer openen kijkt Gatekeeper naar dat gemarkeerde bestand, vindt geen
handtekening, en weigert.

### Wat je ziet

Een venster dat zegt dat de app niet geopend kan worden omdat hij van een niet-geverifieerde
ontwikkelaar komt, of dat Apple niet heeft kunnen controleren of er geen malware in zit. De
enige knoppen zijn iets als **Gereed** (Done) en **Verplaats naar prullenmand** (Move to
Trash). Er staat hier géén "Open Anyway", en je komt vanuit dit venster niet verder.

Met de rechtermuisknop op de app klikken en **Open** kiezen — de omweg die in veel oudere
handleidingen nog staat — **werkt niet meer**. Apple heeft die in macOS 15 (Sequoia)
verwijderd, en in macOS 26 (Tahoe) is hij niet teruggekomen.

### Hoe je wel verdergaat

Apple beschrijft de route zelf in de Mac-gebruikershandleiding, onder *"Een Mac-app van een
niet-geverifieerde ontwikkelaar openen"*:

1. **Probeer de app eerst te openen**, en klik de weigering weg. Deze stap kun je niet
   overslaan: de knop in stap 3 verschijnt pas nadat macOS een geblokkeerde poging heeft
   genoteerd.
2. Ga naar **Systeeminstellingen** (System Settings) → **Privacy en beveiliging** (Privacy &
   Security), en scroll naar het kopje **Beveiliging** (Security).
3. Daar staat een regel met de naam van de app, met de mededeling dat hij geblokkeerd is omdat
   hij niet van een geverifieerde ontwikkelaar komt. Klik op **Open toch** (Open Anyway).
4. **Voer je inlogwachtwoord in** als daarom gevraagd wordt, en bevestig.

**Er zit een tijdslimiet op.** Apple geeft aan dat de knop **Open toch** ongeveer *een uur*
beschikbaar blijft na de geblokkeerde poging. Zet je tussen stap 1 en 2 eerst koffie, dan kan
die regel uit Privacy en beveiliging verdwenen zijn — ga in dat geval terug naar stap 1, open
de app opnieuw, en kom dan terug.

Je doet dit één keer per app. Zodra de uitzondering vastligt, opent hij daarna gewoon.

### Lees dit voordat je het doet

Apple schrijft er in zoveel woorden bij dat dit omzeilen de meest voorkomende manier is waarop
een Mac malware oploopt. Dat is een terechte waarschuwing en we gaan er niet omheen praten.
Het is een uitspraak over het algemene geval: de meeste mensen die door dit venster heen
klikken doen dat voor een programma waar ze niets van weten. Of het op jou van toepassing is,
hangt er volledig van af of je kunt verklaren waar jouw kopie vandaan komt.

### Deze route wordt steeds smaller

Apple heeft dit bij elk van de laatste paar macOS-versies moeilijker gemaakt: de omweg via de
rechtermuisknop is weg, de knop zit nu in Systeeminstellingen, hij vervalt na ongeveer een uur,
en er wordt om je wachtwoord gevraagd. Het ligt voor de hand dat het verder wordt
aangescherpt. Op macOS is een certificaat daarmee eerder *noodzakelijk* dan mooi meegenomen,
en dat is het sterkste argument om er [geld voor bij elkaar te brengen](sponsor.md).

## Windows: een waarschuwing die je weg kunt klikken, en die vanzelf slijt

**Er is nog geen Windows-build.** Ook dit is een vooruitblik.

### Wat je ziet

Als je het gedownloade bestand start, laat Microsoft Defender SmartScreen een blauw venster
zien:

> **Windows heeft uw pc beveiligd** — *"Windows protected your PC"*
>
> Microsoft Defender SmartScreen heeft voorkomen dat een onbekende app is gestart. Deze app
> uitvoeren kan een risico vormen voor uw pc.

De enige zichtbare knop is **Niet uitvoeren** (Don't run).

### Hoe je verdergaat

1. Klik op het kleine linkje **Meer informatie** (More info), boven de knop.
2. Nu verschijnen de uitgever en de bestandsnaam, met daarbij een knop **Toch uitvoeren** (Run
   anyway).
3. Klik op **Toch uitvoeren**.

Meer is het niet — geen wachtwoord, geen instellingen, geen tijdslimiet.

Verschijnt **Toch uitvoeren** niet, dan staat het bestand mogelijk nog als geblokkeerd
gemarkeerd: rechtermuisknop → **Eigenschappen** → onderaan het tabblad Algemeen **Blokkering
opheffen** (Unblock) aanvinken → **OK**, en probeer het opnieuw.

### Waar SmartScreen eigenlijk op let

Volgens Microsofts eigen ontwikkelaarsdocumentatie (*SmartScreen reputation for Windows app
developers*) weegt SmartScreen twee dingen: of het bestand ondertekend is door een uitgever
die het herkent, en of precies dit bestand al door genoeg mensen zonder problemen is
gedownload. Een niet-ondertekend bestand begint op beide punten bij nul — en omdat die
reputatie aan het exacte bestand hangt, begint elke nieuwe versie weer bij nul.

In de praktijk betekent dat: de waarschuwing wordt vanzelf milder naarmate een versie langer
rondgaat, en komt bij de volgende versie terug.

### Eén geval waarin doorklikken niet kan

Windows 11 heeft daarnaast een strengere voorziening, **Smart App Control**. Staat die aan, dan
blokkeert hij niet-ondertekende programma's zonder meer, en is er geen "Toch uitvoeren". Hij
staat alleen aan bij een schone installatie van Windows 11, en uitzetten is eenrichtingsverkeer
— Windows laat je hem niet meer aanzetten zonder opnieuw te installeren. Loop je hiertegenaan,
dan is het eerlijke antwoord dat er geen omweg is zolang de app niet ondertekend is.

## Samengevat

| | Wat je ziet | Hoe je verdergaat | Wordt het vanzelf makkelijker? |
| --- | --- | --- | --- |
| **Linux** | Niets | `chmod +x`, daarna starten | n.v.t. — er is geen drempel |
| **macOS** | Weigering, geen knop om te openen | Systeeminstellingen → Privacy en beveiliging → Beveiliging → Open toch, binnen ongeveer een uur, met je wachtwoord | Nee — Apple scherpt het juist aan |
| **Windows** | "Windows heeft uw pc beveiligd" | Meer informatie → Toch uitvoeren | Ja, naarmate een versie vaker gedownload wordt |

Geen van deze waarschuwingen betekent dat de app nagekeken is en gevaarlijk bleek. Ze
betekenen dat er niet betaald is om vast te leggen wie hem geschreven heeft. [Wat dat zou
kosten](sponsor.md).

---

*Gecontroleerd tegen documentatie van de leveranciers op 2026-08-05: Apple's
Mac-gebruikershandleiding, onderwerp "Open a Mac app from an unidentified developer", en
"SmartScreen reputation for Windows app developers" op Microsoft Learn. Dit gedrag verandert
per OS-versie. Ziet jouw scherm er anders uit dan hier beschreven, dan zijn die twee pagina's
de plek om te kijken — en laat het vooral weten, dan kan deze pagina worden bijgewerkt.*
