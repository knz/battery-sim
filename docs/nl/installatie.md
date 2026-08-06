<!--
Installatiepagina voor huishoudens (Nederlands). Behandelt alle drie de platforms: de
Linux-AppImage, en de macOS- en Windows-bundels die .github/workflows/release.yml maakt.
Documenteert bewust NIET het draaien vanuit de broncode; dat hoort in docs/maintainers/.
De downloadlinks wijzen naar de GitHub-releases-pagina.

Register: informeel je/jouw, conform changelog/20260725-nl-register-consistency.md.
Engelse tegenhanger: ../en/install.md.
-->

# De Thuisbatterij-simulator installeren en starten

De app draait op je eigen computer. Hij leest je gegevens uit Home Assistant of uit
CSV-exports, rekent lokaal, en laat het resultaat in een venster zien. Er gaat niets naar
buiten, en de app belt niet naar huis.

**Direct naar jouw platform:** [Linux](#linux-downloaden-en-starten) ·
[macOS](#macos-downloaden-en-starten) · [Windows](#windows-downloaden-en-starten)

Op deze pagina:

- [Wat je nodig hebt](#wat-je-nodig-hebt)
- [Welke platforms er zijn](#welke-platforms-er-zijn)
- [Linux: downloaden en starten](#linux-downloaden-en-starten)
- [macOS: downloaden en starten](#macos-downloaden-en-starten)
- [Windows: downloaden en starten](#windows-downloaden-en-starten)
- [Als het venster niet opengaat](#als-het-venster-niet-opengaat)
- [Eén melding die je kunt negeren](#eén-melding-die-je-kunt-negeren)
- [Waar de app je gegevens bewaart](#waar-de-app-je-gegevens-bewaart)

## Wat je nodig hebt

- Een computer met Linux, macOS of Windows (zie [Welke platforms er
  zijn](#welke-platforms-er-zijn) hieronder).
- De energiegegevens van je eigen huishouden — een Home Assistant die je op je thuisnetwerk
  kunt bereiken, of CSV-exports daaruit.

Je hoeft géén Python, Node of iets dergelijks te installeren. Alles wat de app nodig heeft zit
in het bestand dat je downloadt.

## Welke platforms er zijn

| Platform | Download |
| --- | --- |
| **Linux** (64-bit x86) | `Home-Battery-Simulator-x86_64.AppImage` — één bestand |
| **macOS** (Apple silicon) | `battery-sim-macos-arm64.zip` |
| **macOS** (Intel) | `battery-sim-macos-x86_64.zip` |
| **Windows** (64-bit x86) | `battery-sim-windows-x86_64.zip` |

Alle builds staan op https://github.com/knz/battery-sim/releases. Pak degene die bij je machine
hoort; op macOS betekent Apple silicon een Mac met M-chip, en Intel een Mac van vóór die
overstap.

Geen van de builds is ondertekend, dus macOS en Windows laten allebei een waarschuwing zien de
eerste keer dat je de app opent. Dat hoort erbij en betekent niet dat er iets mis is. De pagina
over [beveiligingswaarschuwingen](beveiligingswaarschuwingen.md) loopt precies langs wat je te
zien krijgt en hoe je erlangs komt.

## Linux: downloaden en starten

De Linux-build is een **AppImage**: één bestand met de hele applicatie erin. Geen installatie,
geen pakketbeheerder, en er wordt niets in je systeemmappen gezet. Wil je de app weg hebben,
dan gooi je het bestand weg.

**1. Download `Home-Battery-Simulator-x86_64.AppImage`** van de
[releases-pagina](https://github.com/knz/battery-sim/releases).

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

### Systeemeisen

De Linux-build is gebouwd tegen glibc 2.39 en heeft dus een distributie nodig van ongeveer de
leeftijd van Ubuntu 24.04 of nieuwer. Op Debian 12 of ouder start hij niet. Je hebt een
X11- of Wayland-sessie nodig; op een server zonder beeldscherm draait hij niet.

## macOS: downloaden en starten

**1. Download de zip die bij je Mac hoort** van de
[releases-pagina](https://github.com/knz/battery-sim/releases) —
`battery-sim-macos-arm64.zip` voor Apple silicon, `battery-sim-macos-x86_64.zip` voor Intel.
Weet je niet welke je hebt:  → Over deze Mac.

**2. Pak hem uit.** Dubbelklik op de gedownloade zip. Je krijgt **Home Battery Simulator.app**.
Sleep die naar je map **Programma's** (Applications); alles wat de app nodig heeft zit erin,
dus hij kan overal staan en je verwijdert de app door hem naar de prullenmand te slepen.

**3. Open de app.** Dubbelklik op **Home Battery Simulator**.

macOS weigert de eerste poging, omdat de app niet ondertekend is. Dat hoort bij de eerste keer
opstarten; de stappen staan op de pagina over
[beveiligingswaarschuwingen](beveiligingswaarschuwingen.md). Kort gezegd: Systeeminstellingen →
Privacy en beveiliging → naar beneden scrollen tot Beveiliging → **Toch openen**, en daarna de
app een tweede keer openen. Dit hoef je maar één keer te doen.

## Windows: downloaden en starten

**1. Download `battery-sim-windows-x86_64.zip`** van de
[releases-pagina](https://github.com/knz/battery-sim/releases).

**2. Pak hem uit.** Rechtermuisknop op de gedownloade zip → **Alles uitpakken**. Je krijgt een
map `battery-sim`. Zet die neer waar je wilt; alles wat de app nodig heeft zit erin, en je
verwijdert de app door de map weg te gooien.

**3. Open de app.** Start in die map `battery-sim.exe`.

Windows laat een blauw kader zien met **"Windows heeft uw pc beveiligd"**, omdat de app niet
ondertekend is. Klik op **Meer informatie** en daarna op **Toch uitvoeren**. Wat die
waarschuwing eigenlijk meet, staat op de pagina over
[beveiligingswaarschuwingen](beveiligingswaarschuwingen.md). Naast het app-venster gaat er een
terminalvenster open; dat hoort bij de app en je kunt het negeren, maar sluit je het, dan sluit
de app ook.

## Als het venster niet opengaat

Dan valt de app op elk platform terug op je gewone webbrowser, en meldt dat ook. Daar werkt hij
precies hetzelfde. Dat gebeurt als de grafische bibliotheken die het venster nodig heeft niet
geladen kunnen worden op jouw systeem.

Je kunt ook expres om de browser vragen, met `--browser` — op Linux bijvoorbeeld zo:

```
./Home-Battery-Simulator-x86_64.AppImage --browser
```

## Eén melding die je kunt negeren

Op Linux zie je bij het opstarten misschien dit in de terminal:

```
GStreamer element appsink not found. Please install it.
```

Dat is onschuldig en hoeft niet opgelost te worden. De melding komt uit de browser-engine die
in de app is meegebakken; die kijkt bij het starten of er een onderdeel voor videoweergave is.
De app heeft geen video of geluid, dus er ontbreekt voor jou niets. Het is uitgezocht en het
is niet weg te krijgen zonder een mediabibliotheek mee te leveren die de app nooit gebruikt;
de details staan in `changelog/20260805-desktop-packaging.md` §16.

## Waar de app je gegevens bewaart

Je workspaces en je instellingen:

| Platform | Locatie |
| --- | --- |
| **Linux** | `~/.local/share/battery-sim` |
| **macOS** | `~/Library/Application Support/BatterySim` |
| **Windows** | `%LOCALAPPDATA%\BatterySim\data` |

Je energiegegevens verlaten je machine niet.

**Je Home Assistant-token staat daar niet bij.** Als je er een hebt ingevuld, bewaart je
browser dat, en het gaat alleen naar je eigen Home Assistant — het bereikt deze app nooit.
Daarom haal je het ook niet weg door de map hierboven te verwijderen. Wil je het wissen, wis
dan in je browser de sitegegevens van het adres van de app, net als bij elke andere site.

## Verder lezen

- [Beveiligingswaarschuwingen van je besturingssysteem](beveiligingswaarschuwingen.md)
- [Het project steunen](sponsor.md) — onder meer wat deze waarschuwingen zou weghalen
