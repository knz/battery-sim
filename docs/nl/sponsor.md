<!--
De uitnodiging om het project te steunen (Nederlands).

PLAATSINGSBESLUIT: dit hoort in docs/ en in README.md, en mag NERGENS in de app-interface
terechtkomen. docs/specs/01-product-brief.md:186 en docs/specs/15-data-quality-and-limits.md §7.5
sluiten telemetrie en naar buiten gerichte elementen uit; een sponsorlink in het venster zou
het eerste zijn dat het product naar buiten richt. Zie
changelog/20260805-desktop-packaging.md §17.1.

Bedragen gecontroleerd op 2026-08-05: Apple Developer Program USD 99/jaar, inclusief
Developer ID en notarisatie, van Apple's eigen vergelijkingspagina voor lidmaatschappen.
Azure Artifact Signing (hernoemd vanaf Trusted Signing) circa USD 10 per maand, van de pagina
smartscreen-reputation op Microsoft Learn; Microsofts publieke prijspagina toont wel de
tarieven maar niet de bedragen. De eis van een hardwaretoken voor OV-certificaten komt uit de
CA/Browser Forum-basisregels die per 2023-06-01 gelden.

Je kunt het project steunen via GitHub Sponsors: https://github.com/sponsors/knz.
Engelse tegenhanger: ../en/sponsor.md.
-->

# Het project steunen

De app is vrije software onder de AGPL-3.0, draait volledig op je eigen machine, en verzamelt
niets over je. Er is geen betaalde versie en er wordt niets achtergehouden.

Er is één ding dat met geld zou veranderen, en deze pagina gaat over dat ene ding — zodat je
zelf kunt bepalen of het je iets waard is.

## Het probleem waar geld voor is

De app is niet ondertekend. macOS en Windows reageren daarop, en de pagina over
[beveiligingswaarschuwingen](beveiligingswaarschuwingen.md) beschrijft precies hoe. Dat
ondertekenen is geen technisch probleem — de build levert al werkende bestanden op — het is
een terugkerende rekening.

## Wat het kost, en wat je er werkelijk voor terugkrijgt

### macOS — ongeveer USD 99 per jaar

Het Developer Program van Apple kost USD 99 per lidmaatschapsjaar. Daar zitten een Developer
ID-certificaat en toegang tot notarisatie bij, en dat is wat een app nodig heeft die buiten de
App Store om wordt verspreid. Een gratis Apple-account bevat geen van beide.

**Wat je ervoor terugkrijgt: een app die opent als je erop dubbelklikt.** Nu moet iemand op
macOS eerst proberen te openen, geweigerd worden, naar Systeeminstellingen gaan, daar een knop
**Open toch** vinden die na ongeveer een uur vervalt, en zijn wachtwoord invoeren. Voor een
huishouden is dat een echte drempel, en Apple maakt die route bij elke versie smaller. Op macOS
is een certificaat daarmee eerder noodzakelijk dan cosmetisch.

### Windows — ongeveer USD 10 per maand, en het levert minder op dan je zou denken

Sinds juni 2023 schrijven de regels van het CA/Browser Forum voor dat de sleutel waarmee je
ondertekent in gecertificeerde hardware moet zitten: een USB-token of een gehoste HSM. Met een
token valt slecht te werken in een geautomatiseerde build, en daarom is een gehoste
ondertekendienst de praktische route. **Azure Artifact Signing** (in 2026 hernoemd vanaf
Trusted Signing) is op dit moment een van de goedkoopste serieuze opties, kost rond de USD 10
per maand, heeft geen hardware nodig, en is in te bouwen in een CI-pijplijn. De dienst staat
open voor bedrijven en zzp'ers in de EU, dus voor een Nederlands project is het in elk geval
denkbaar.

**Wat je ervoor terugkrijgt is bescheidener, en het zou oneerlijk zijn dat anders voor te
stellen.** Microsofts eigen ontwikkelaarsdocumentatie zegt met zoveel woorden dat ondertekenen
de SmartScreen-waarschuwing *niet* wegneemt: ook een ondertekende versie laat hem zien totdat
dat specifieke bestand genoeg downloadgeschiedenis heeft opgebouwd, en Microsoft heeft het
daarbij over mogelijk weken en honderden schone installaties. Wat ondertekenen wél oplevert, is
dat er een geverifieerde uitgeversnaam in de waarschuwing staat in plaats van niets, en dat de
opgebouwde reputatie meegaat naar een volgende versie in plaats van weer bij nul te beginnen.
(EV-certificaten sloegen die waarschuwing vroeger helemaal over. Microsoft geeft aan dat dat
niet meer zo is, dus de meerprijs van EV is daarvoor niet meer de moeite.)

Kortom: op Windows haalt ondertekenen geleidelijk wrijving weg. Op macOS haalt het een muur
weg.

### Linux — niets

Er is geen drempel en er valt niets te kopen. De AppImage draait zoals hij is.

## Waar het geld het eerst naartoe zou gaan

Naar macOS. Dat is het platform waar het ontbreken van een certificaat mensen echt tegenhoudt,
en met USD 99 per jaar is het bovendien de kleinste van de twee rekeningen.

## Hoe je kunt bijdragen

> Je kunt het project steunen via [GitHub Sponsors](https://github.com/sponsors/knz).
> Het platform verzorgt maandelijkse bijdragen en eenmalige donaties.

Wil je liever bijdragen op een manier die niets kost:

- **Meld wat er stukgaat.** De builds zijn op een beperkt aantal machines gecontroleerd. Een
  melding dat er een niet start op jouw distributie, jouw Mac of jouw Windows-versie, is meer
  waard dan de meeste dingen.
- **Meld een fout in de documentatie.** De stukken over macOS en Windows op de pagina over
  [beveiligingswaarschuwingen](beveiligingswaarschuwingen.md) zijn geschreven op basis van
  documentatie van Apple en Microsoft, niet doordat iemand het daar heeft gedraaid. Ziet jouw
  scherm er anders uit, dan is dat een correctie die we graag hebben.
- **Kijk het Nederlands na.** Zowel de interface als deze pagina's zijn in het Nederlands
  geschreven, niet vertaald. Een houterige zin is een bug.

## Wat sponsoring níét koopt

Om duidelijk te zijn over wat er niet in het aanbod zit: er zit geen functie achter een
betaling, wie bijdraagt krijgt geen voorrang bij vragen, en voor wie niets bijdraagt verandert
er niets aan de app. De app zelf zal ook nooit om geld vragen — deze uitnodiging staat in de
documentatie en in de README van het project, en met opzet nergens in de applicatie. De app
maakt geen enkele verbinding naar buiten, behalve met je eigen Home Assistant, en een
sponsorlink in het venster zou het eerste zijn dat hij ooit naar de buitenwereld richt. Die
ruil is het niet waard.
