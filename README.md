<p align="center">
  <img src="packaging/icon/battery-sim.svg" alt="" width="96" height="96">
</p>

<h1 align="center">Home Battery Simulator</h1>

**Nederlands**

Een webapp die op je eigen computer draait en achteraf uitrekent wat een thuisbatterij een
Nederlands huishouden bespaard zou hebben — op basis van de eigen historische gegevens van dat
huishouden, gerekend met de regels van na 2027, wanneer salderen niet meer bestaat. De app
beantwoordt de vraag "wat als ik deze batterij had gehad, in deze periode".

**English**

A locally-run web app that retrospectively simulates what a home battery would have saved a
Dutch household, using that household's own historical data under the post-2027 Dutch regime in
which net metering (*salderen*) no longer exists. It answers "what if I had owned this battery,
over this period".

## Using the app

The app is released as a **desktop app**.

Builds are published on the [releases
page](https://github.com/knz/battery-sim/releases):

- for **Linux** (an AppImage),
- **macOS** (Apple silicon and Intel),
- **Windows**.

None of them is signed, so macOS and Windows [show a warning on first
open](docs/en/security-warnings.md).

More documentation:

- **[Installing and running](docs/en/install.md)** — [Installeren en starten](docs/nl/installatie.md)
- **[The security warnings your OS shows](docs/en/security-warnings.md)** — [Beveiligingswaarschuwingen](docs/nl/beveiligingswaarschuwingen.md)
- **[When something goes wrong](docs/en/troubleshooting.md)** — [Als er iets misgaat](docs/nl/probleemoplossing.md)
- **[Supporting the project](docs/en/sponsor.md)** — [Het project steunen](docs/nl/sponsor.md)

Every page exists in English and Dutch; the index is [`docs/README.md`](docs/README.md).


## Licence

**GNU Affero General Public License v3.0 only** (`AGPL-3.0-only`). The full text is in
[LICENSE](LICENSE).

The AGPL's distinguishing clause is §13: if you run a modified version and let other people use
it over a network, those users are entitled to the source of your modified version. Running the
app on your own machine for yourself — which is what it is designed for — triggers nothing.

That covers this project's own code. The app is built on other people's, and the downloadable
builds carry it: the browser libraries served by the app, the Python packages inside every
bundle, and — in the Linux AppImage — the GTK and WebKit libraries it brings with it, which are
LGPL. Who wrote what, under which licence, and where to get its source is set out in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md); the licence texts it refers to are in
[licenses/](licenses/).

## Supporting the project

The desktop builds are unsigned, which is why macOS and Windows warn about them. What signing
would cost and what it would actually fix is set out in
[docs/en/sponsor.md](docs/en/sponsor.md) ([Nederlands](docs/nl/sponsor.md)).

## Working on the app

Running from source, the stack and repository layout, rebuilding the stylesheet, the test
suite, and updating translations are documented in
**[docs/maintainers/](docs/maintainers/README.md)**.

The full specification lives in [`docs/specs/README.md`](docs/specs/README.md).
