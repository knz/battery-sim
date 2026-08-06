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

De sectie over certificaten is het enige probleem op deze pagina dat NIET over de starter gaat —
de app is gestart, alleen de verbinding met HA mislukt — en staat daarom los van de reeks over het
logbestand. Het ophalen draait in de browser (app/static/ha_fetch.js opent de WebSocket
rechtstreeks naar HA), dus het vertrouwen ligt bij de certificaatopslag van het systeem en niet
bij dit project. Verhuist het ophalen ooit naar de server, dan klopt dit advies niet meer: dan
telt de opslag van Python, niet die van de sleutelhanger.

Hoort bij ws_connect_failed in ha_fetch.js, die hierheen linkt — pas je de een aan, controleer dan
de ander. Die melding noemt drie mogelijke oorzaken in plaats van TLS aan te wijzen, omdat de
foutgebeurtenis van de WebSocket geen reden meegeeft: een geweigerd certificaat, een verkeerde
host en een gestopte HA zijn niet uit elkaar te houden.

De sectie "In een browser accepteren werkt niet" is geen antwoord op de melding maar op een
gewoonte. Het venster is pywebview met de renderer van het besturingssysteem, en dat leest de
SYSTEEMopslag, terwijl een browseruitzondering per browser wordt bewaard. Laat de sectie staan,
ook als de melding verandert.

De stappen voor macOS en Linux zijn door gebruikers gemeld en bevestigd. Windows is naar analogie
beredeneerd en zegt dat erbij; haal die slag om de arm weg zodra iemand het verifieert.

De sectie over prijzen laden gaat over de ANDERE certificaatopslag en staat bewust los van die
over HA, ook al melden beide CERTIFICATE_VERIFY_FAILED. Dat verzoek doet de backend via urllib, in
het proces van de app zelf, dus daar controleert Python's `ssl` en wijst app/net_trust.py
(truststore) die naar de opslag van het besturingssysteem. Een lezer die de stappen voor de
sleutelhanger heeft gevolgd en dan hierop stuit, zou anders denken dat die stappen niet werkten;
de sectie zegt daarom expliciet dat ze hier niet van toepassing zijn. Hoort bij
`_load_failed_message` in app/main.py, die hierheen linkt.

De sectie vraagt bewust om een melding in plaats van een oplossing te geven: werkt truststore,
dan valt er voor de gebruiker niets te repareren, en het logbestand bevat de regel die zegt of het
geladen is. Zet hier pas echte stappen neer als er een oorzaak opduikt waar een gebruiker iets
mee kan.

Engelse tegenhanger: ../en/troubleshooting.md.
-->

# Als er iets misgaat

De app schrijft bij elke start een logbestand weg. Gaat de app niet open, gebeurt er niets na het
starten, of kun je de pagina niet vinden in je browser, dan is dat bestand de eerste plek om te
kijken — en het nuttigste wat je kunt meesturen bij een melding.

**Direct naar:** [Het logbestand vinden](#het-logbestand-vinden) · [Het adres vinden](#het-adres-vinden) ·
[Certificaatfouten bij Home Assistant](#verbinding-testen-mislukt-met-een-certificaatfout) ·
[Certificaatfouten bij prijzen laden](#prijzen-laden-mislukt-met-een-certificaatfout) ·
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

## "Verbinding testen" mislukt met een certificaatfout

**Verbinding testen** kan mislukken terwijl het adres en het token allebei kloppen. De app kan je
niet vertellen waarom — de browser meldt de fout zonder reden — dus noemt de melding alle drie de
mogelijkheden: het adres, of Home Assistant draait, en het certificaat.

Het certificaat is de waarschijnlijke oorzaak als je Home Assistant HTTPS gebruikt met een
certificaat dat je machine nog niet vertrouwt: meestal een certificaat van je eigen
certificaatautoriteit, of een zelfondertekend certificaat.

Je loopt hier waarschijnlijk niet tegenaan als Home Assistant op gewoon `http://` draait, of als
je Nabu Casa (Home Assistant Cloud) gebruikt, waarvan het certificaat van een autoriteit komt die
je systeem al vertrouwt.

De oplossing: laat je machine het **root-CA-certificaat** vertrouwen — het certificaat van de
autoriteit zelf, niet het certificaat dat aan Home Assistant is uitgegeven. Elk certificaat dat
die CA uitgeeft wordt dan geaccepteerd, dus als je dat van Home Assistant later opnieuw uitgeeft,
komt het probleem niet terug. Start daarna de app opnieuw.

### macOS

1. Open het root-CA-certificaat; meestal opent dan **Sleutelhangertoegang**.
2. Voeg het toe aan de sleutelhanger **login**, of aan **Systeem** voor iedereen op de machine.
3. Open het in de lijst, klap **Vertrouwen** uit en zet **Bij gebruik van dit certificaat** op
   **Vertrouw altijd**.

### Linux

Op Ubuntu:

```
sudo cp jouw-root-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

Het bestand moet de extensie `.crt` hebben en PEM-inhoud bevatten. Andere distributies gebruiken
andere paden en commando's — kijk in de documentatie van je distributie naar de
certificaatopslag van het systeem.

### Windows

Importeer het root-CA-certificaat in **Vertrouwde basiscertificeringsinstanties**. We hebben de
stappen niet nagelopen; kom je ze tegen, meld ze dan in een issue, dan zetten we ze erbij.

### In een browser accepteren werkt niet

Door een certificaatwaarschuwing heen klikken in Safari, Chrome of Firefox slaat een uitzondering
op in alleen die browser. De app tekent zijn eigen venster met de renderer van je
besturingssysteem, en dat venster leest de certificaatopslag van het **systeem** — waar een
uitzondering uit een browser nooit terechtkomt. Firefox houdt ook op Linux een eigen opslag bij,
dus een CA daar vertrouwen zet hem evenmin systeembreed.

Zet de certificaatcontrole alsjeblieft niet uit om hier langs te komen. Daarmee verdwijnt precies
de bescherming waarvoor het certificaat bedoeld is, en je eigen CA vertrouwen is nauwelijks meer
werk.

## Prijzen laden mislukt met een certificaatfout

Een andere fout, met een melding als:

```
could not load 'price_spot' from 'energy_charts': <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: unable to get local issuer certificate>
```

Deze gaat niet over je Home Assistant. De app haalt spotprijzen op bij een openbare server en kon
het certificaat van die server niet controleren. De stappen hierboven helpen hier niet: het gaat
om een gewoon openbaar certificaat, en er is niets mis met jouw installatie.

De app hoort hiervoor de certificaten van je systeem te gebruiken, dus op de meeste machines komt
dit niet voor. Zie je het toch, [meld het dan](#een-probleem-melden) met het logbestand erbij —
daarin staat of de app de certificaatopslag van je systeem kon bereiken, en dat is het eerste wat
we willen weten.

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
