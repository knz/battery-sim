<!--
Pagina over probleemoplossing voor huishoudens (Nederlands). Geschreven op 2026-08-06, samen met
de wijziging die het consolevenster op alle drie de platformen uitzet en per start een logbestand
wegschrijft.

De volgorde is bewust gekozen en volgt wat een vastgelopen lezer nodig heeft: eerst het logbestand
vinden, dan het adres eruit lezen, dan het meesturen in een melding. De paden per platform staan
vooraan omdat elke volgende sectie ervan uitgaat dat de lezer de map gevonden heeft.

De paden komen uit app/config.py::user_data_dir() — macOS ~/Library/Application Support/BatterySim,
Linux $XDG_DATA_HOME/battery-sim (anders ~/.local/share/battery-sim), Windows
%LOCALAPPDATA%\BatterySim\data. Verandert die functie, dan klopt deze pagina niet meer en moet ze
mee veranderen, net als de Engelse tegenhanger.

De lijst "wat stuur je mee" is bewust kort. Een lange lijst wordt overgeslagen, en de kop van het
logbestand bevat het platform en de datamap al — daar apart om vragen zou de lezer laten overtypen
wat hij toch al meestuurt.

Let op: het log gaat over de STARTER, niet over de hele toepassing. Het wegschrijven begint pas
zodra de datamap bekend is, dus fouten in de opdrachtregel en --help komen alleen in de terminal
terecht. Daarom staat er "als de app überhaupt gestart is".

Engelse tegenhanger: ../en/troubleshooting.md.
-->

# Als er iets misgaat

De app schrijft bij elke start een logbestand weg. Gaat de app niet open, gebeurt er niets na het
starten, of kun je de pagina niet vinden in je browser, dan is dat bestand de eerste plek om te
kijken — en het nuttigste wat je kunt meesturen bij een melding.

**Direct naar:** [Het logbestand vinden](#het-logbestand-vinden) · [Het adres vinden](#het-adres-vinden) ·
[Een probleem melden](#een-probleem-melden)

## Het logbestand vinden

Logbestanden staan in een map `logs` binnen de datamap van de app. Er is één bestand per start,
met een naam die begint met `session-` gevolgd door datum en tijd. Het nieuwste bestand is dus de
poging die je zojuist deed.

### macOS

```
~/Library/Application Support/BatterySim/logs/
```

De map `Library` is standaard verborgen. Gebruik in Finder **Ga → Ga naar map…** (Shift-Cmd-G) en
plak het pad hierboven.

### Windows

```
%LOCALAPPDATA%\BatterySim\data\logs\
```

Plak dit precies zo in de adresbalk van Verkenner, inclusief de procenttekens — Windows vult ze
zelf in. Meestal kom je uit op `C:\Users\<jouw naam>\AppData\Local\BatterySim\data\logs\`.

### Linux

```
~/.local/share/battery-sim/logs/
```

Heb je `XDG_DATA_HOME` ingesteld, dan is het `$XDG_DATA_HOME/battery-sim/logs/`.

Logbestanden zijn gewone tekst. Elke teksteditor opent ze, en je kunt ze veilig lezen — kijk wel
even bij [wat er in het log staat](#wat-er-in-het-log-staat) voordat je er een openbaar plaatst.

## Het adres vinden

De app draait een kleine webserver op je eigen machine en toont die in een venster. Verschijnt dat
venster niet, dan draait de server vaak gewoon — je hebt alleen het adres nodig.

Open het nieuwste logbestand en zoek een regel als:

```
Home Battery Simulator on http://127.0.0.1:8137/
```

Typ dat adres in je browser en je krijgt de app. Het poortnummer is meestal 8137, maar verandert
als iets anders op je machine die poort al bezet houdt. Precies daarom is het adres uit het log
lezen betrouwbaarder dan gokken.

Twee andere regels die het weten waard zijn:

- **`Home Battery Simulator is already running at …`** — er staat al een exemplaar open. Gebruik
  het genoemde adres, of sluit het andere eerst af.
- **Een regel over een venster dat niet geopend kon worden** — de app kon zijn eigen venster niet
  tekenen en is teruggevallen op je browser. De app werkt gewoon; het adres staat in hetzelfde log.

## Een probleem melden

Stuur mee:

1. **Het logbestand** van de mislukte poging — als bijlage, of de inhoud geplakt.
2. **Wat je deed** en wat je in plaats daarvan verwachtte.
3. **Welke download je gebruikt** — de bestandsnaam, of de release waar je hem vandaan hebt.

Je hoeft je besturingssysteem en de locatie van je gegevens niet apart te vermelden: bovenaan elk
logbestand staan het platform en de datamap al.

Melden kan op [github.com/knz/battery-sim/issues](https://github.com/knz/battery-sim/issues). In
het Nederlands of het Engels, wat je zelf prettig vindt.

### Wat er in het log staat

Het log bevat de opstartmeldingen van de app zelf: het adres waarop hij draait, of er al een
exemplaar liep, en waarom een venster niet openging. Het bevat **geen** energiegegevens, geen
prijzen en geen Home Assistant-token.

Er staat wél **het pad naar je datamap** in, en daar zit normaal gesproken je gebruikersnaam in.
Vind je dat bezwaarlijk, vervang het dan door iets anders voordat je het plaatst — niets in een
melding hangt af van de echte naam.

### Oudere logbestanden

Bestanden ouder dan drie maanden worden bij de volgende start automatisch verwijderd. Aan de rest
van de datamap wordt niets veranderd. Wil je een log bewaren, kopieer het dan ergens anders heen.

## Als er helemaal geen log is

Een lege of ontbrekende map `logs` betekent dat de app al eerder gestopt is. Dat is op zichzelf
een bruikbaar gegeven en het melden waard — schrijf erbij dat de map leeg was, en of de datamap
zelf wel bestaat.

De app vanuit een terminal starten toont meestal de reden waarom hij stopte, en die uitvoer is in
dit geval het nuttigst om mee te sturen. Open op Windows PowerShell in de map waar je de app hebt
uitgepakt en voer `.\battery-sim.exe` uit; op macOS en Linux start je de app op dezelfde manier
vanuit een terminal.

## Zie ook

- [Installeren en starten](installatie.md)
- [Beveiligingswaarschuwingen](beveiligingswaarschuwingen.md)
