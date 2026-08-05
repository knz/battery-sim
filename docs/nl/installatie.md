<!--
Installatiepagina voor huishoudens (Nederlands). Behandelt alleen de Linux-AppImage — dat is
het enige platform waarvoor een build bestaat. Documenteert bewust NIET het draaien vanuit de
broncode; dat hoort in de README voor ontwikkelaars. De downloadlink is een gemarkeerde
placeholder: er is nog geen release.

Register: informeel je/jouw, conform changelog/20260725-nl-register-consistency.md.
Engelse tegenhanger: ../en/install.md.
-->

# De Thuisbatterij-simulator installeren en starten

De app draait op je eigen computer. Hij leest je gegevens uit Home Assistant of uit
CSV-exports, rekent lokaal, en laat het resultaat in een venster zien. Er gaat niets naar
buiten, en de app belt niet naar huis.

## Wat je nodig hebt

- Een computer met Linux (zie [Welke platforms er zijn](#welke-platforms-er-zijn) hieronder).
- De energiegegevens van je eigen huishouden — een Home Assistant die je op je thuisnetwerk
  kunt bereiken, of CSV-exports daaruit.

Je hoeft géén Python, Node of iets dergelijks te installeren. Alles wat de app nodig heeft zit
in het bestand dat je downloadt.

## Welke platforms er zijn

| Platform | Stand van zaken |
| --- | --- |
| **Linux** (64-bit x86) | Er is een werkende build: één AppImage-bestand. |
| **macOS** | **Nog geen build.** |
| **Windows** | **Nog geen build.** |

Alleen de Linux-build is gemaakt en getest. macOS en Windows staan wel op de rol, maar er is
op dit moment niets om te downloaden. Werk je op een van die twee, dan beschrijft de pagina
over [beveiligingswaarschuwingen](beveiligingswaarschuwingen.md) waar je tegenaan gaat lopen
zodra die builds er zijn. Dat is dus vooruitblik, geen stappenplan voor vandaag.

## Linux: downloaden en starten

De Linux-build is een **AppImage**: één bestand met de hele applicatie erin. Geen installatie,
geen pakketbeheerder, en er wordt niets in je systeemmappen gezet. Wil je de app weg hebben,
dan gooi je het bestand weg.

**1. Download de AppImage.**

> **Deze link bestaat nog niet.** Er is nog geen publieke release. Zodra die er is, heet het
> bestand `Home-Battery-Simulator-x86_64.AppImage` en komt de downloadlink hier te staan.

**2. Maak het bestand uitvoerbaar.** Een gedownload bestand mag niet zomaar draaien; je moet
daar eerst toestemming voor geven. In een terminal, in de map waar je het hebt neergezet:

```
chmod +x Home-Battery-Simulator-x86_64.AppImage
```

Het kan ook zonder terminal, in de meeste bestandsbeheerders: rechtermuisknop op het bestand →
Eigenschappen → Rechten → vink "Uitvoeren als programma toestaan" aan (de precieze
formulering verschilt per bureaubladomgeving).

**3. Start het.**

```
./Home-Battery-Simulator-x86_64.AppImage
```

Of dubbelklik erop in je bestandsbeheerder. Er opent een venster met de titel **Home Battery
Simulator**.

Meer is het niet. Linux laat geen waarschuwing zien en vraagt nergens om bevestiging — waarom
dat op macOS en Windows anders ligt, staat op de pagina over
[beveiligingswaarschuwingen](beveiligingswaarschuwingen.md).

### Als het venster niet opengaat

Dan valt de app terug op je gewone webbrowser, en meldt dat ook. Daar werkt hij precies
hetzelfde. Dat gebeurt als de grafische bibliotheken die het venster nodig heeft niet geladen
kunnen worden op jouw systeem.

Je kunt ook expres om de browser vragen:

```
./Home-Battery-Simulator-x86_64.AppImage --browser
```

### Eén melding die je kunt negeren

Bij het opstarten zie je misschien dit in de terminal:

```
GStreamer element appsink not found. Please install it.
```

Dat is onschuldig en hoeft niet opgelost te worden. De melding komt uit de browser-engine die
in de app is meegebakken; die kijkt bij het starten of er een onderdeel voor videoweergave is.
De app heeft geen video of geluid, dus er ontbreekt voor jou niets. Het is uitgezocht en het
is niet weg te krijgen zonder een mediabibliotheek mee te leveren die de app nooit gebruikt;
de details staan in `changelog/20260805-desktop-packaging.md` §16.

### Systeemeisen

De Linux-build is gebouwd tegen glibc 2.39 en heeft dus een distributie nodig van ongeveer de
leeftijd van Ubuntu 24.04 of nieuwer. Op Debian 12 of ouder start hij niet. Je hebt een
X11- of Wayland-sessie nodig; op een server zonder beeldscherm draait hij niet.

## Waar de app je gegevens bewaart

In `~/.local/share/battery-sim` — je workspaces, je instellingen, en je Home
Assistant-token als je dat hebt ingevuld. Je energiegegevens verlaten je machine niet.

Dat token staat bewust op schijf, zodat je het niet elke keer opnieuw hoeft in te typen. Wil je
dat niet, gooi die map dan weg; de app maakt bij de volgende start een lege aan.

## Verder lezen

- [Beveiligingswaarschuwingen van je besturingssysteem](beveiligingswaarschuwingen.md)
- [Het project steunen](sponsor.md) — wat ondertekenen kost, en wat het oplost
