# IMX219 op Arduino VENTUNO Q

Een installatiepakket voor de **Raspberry Pi Camera Module 2 (Sony IMX219)** op
**Camera0 van de Arduino VENTUNO Q**. Met Full HD-livebeeld, objectdetectie in
Arduino App Lab en regelaars voor helderheid en contrast.

**Versie 1.0.0-rc.1 — eerste publieke testversie.** De cameraketen en app zijn op
één Ventuno Q hardwarematig getest. De nieuwe complete installer wordt aanvullend
met automatische tests en bouw-/DTB-controles gecontroleerd. Een volledige
installatie op een tweede, schone Ventuno Q is nog niet geverifieerd.

Dit is een onafhankelijk communityproject, geen installer voor een Raspberry
Pi-computer en geen officieel camerastuurprogramma van Arduino.

## Ondersteunde combinatie

| Onderdeel | Ondersteuning in deze versie |
| --- | --- |
| Board | VENTUNO Q met device-tree-identificaties `arduino,monza` en `qcom,qcs8300` |
| Camera | Raspberry Pi Camera Module 2, Sony IMX219 |
| Aansluiting | Camera0, geschikte 15-naar-22-pins CSI-kabel |
| Linux | Ubuntu 24.04; getest met 24.04.4 LTS, aarch64 |
| Kernel | **Uitsluitend `6.8.0-1080-qcom`** |
| Ubuntu-kernelbron | `linux-qcom 6.8.0-1080.85` |
| Arduino App CLI | Getest met `0.14.0`, als onderdeel van Arduino App Lab |
| Opname | 1920 × 1080, packed RGGB RAW10 (`pRAA`), circa 30 RAW-frames/s |
| Livebeeld | RGB/JPEG, maximaal 10 verwerkte beelden/s, afhankelijk van belasting |
| Herkenning | YOLOX Small QNN, modelinvoer 640 × 640, maximaal 5 analyses/s |

**Andere boardvarianten en kernels worden geweigerd.** De naam VENTUNO Q alleen
is onvoldoende om compatibiliteit vast te stellen. Het pakket installeert geen
oudere kernel en werkt je besturingssysteem niet automatisch bij.
De RAW-snelheid is niet de snelheid van de webweergave of AI.

## Wat je krijgt

- Aangepaste CAMSS-driver met volledige gebruikte broncode en patches.
- Camera-instellingen opgebouwd uit de **eigen firmware-DTB van jouw board**.
- Aparte cameraboot met gewone Ubuntu-terugvaloptie.
- Cameradienst die wacht tot de App Lab-app wordt gestart.
- App met zelfstandig livebeeld, detectiekaders, detectiedrempel en beeldopslag.
- Helderheid en contrast van 50–150%, automatisch bewaard op het board.
- Herstelcommando en controlesommen voor bronbestanden en downloads.

Modelgewichten en Ubuntu-/Arduino-images zijn niet meegeleverd. App Lab beheert
het model. De eerste voorbereiding kan daarom internet nodig hebben.

## Vooraf

1. Zorg dat Arduino App Lab werkt op de Ventuno Q en je een terminal kunt openen.
2. Sluit de camera **met uitgeschakelde voeding** aan op Camera0. Controleer de
   contactzijde en gebruik een geschikte kabel; niet elke 15/22-pins kabel heeft
   dezelfde aansluiting.
3. Controleer `uname -r`. Ga alleen verder bij `6.8.0-1080-qcom`.
4. Secure Boot moet uit staan. De installer controleert dit en verandert die instelling niet.
5. Werk als de gewone App Lab-gebruiker. Gebruik `sudo` alleen waar aangegeven.
6. Sluit andere camera-apps. Houd toegang tot beeldscherm/GRUB beschikbaar voor de eerste cameraboot.

Gebruik dit pakket voor een **schone camera-installatie**. Een eerdere
experimentele installatie wordt niet overschreven; zie [bestaande installaties](#bestaande-installaties).

## Installeren

Voer deze commando's op de **Ventuno Q** uit, niet op je Mac of Windows-pc.

### 1. Downloaden

```bash
cd ~
git clone https://github.com/adalmolen/ventunoq-imx219.git
cd ventunoq-imx219
```

Ontbreekt `git`, installeer het met `sudo apt-get install git`.
Je kunt ook het bronpakket onder **Releases** downloaden en op het board uitpakken.
Gebruik dan de naam van die uitgepakte map bij de volgende stappen.

### 2. Installatie voorbereiden

```bash
bash setup.sh
```

Dit installeert afhankelijkheden, bouwt de driver en RGB-verwerking en
controleert camera-DTB en GRUB. Daarna worden cameradienst en bootoptie geïnstalleerd.
Bevestig de pakketinstallatie als Ubuntu daarom vraagt.

- Geen `apt upgrade`, systeemupgrade of automatische herstart.
- De oorspronkelijke CAMSS-module onder `/lib/modules` wordt niet vervangen.
- De gewone Ubuntu-optie blijft voorlopig standaard.
- Voor de eerstvolgende start wordt **eenmalig** de cameraboot gekozen.

Start zelf opnieuw:

```bash
sudo reboot
```

### 3. Na de herstart afronden

```bash
cd ~/ventunoq-imx219
bash setup.sh --finish
```

Gebruik bij een uitgepakt releasearchief de eigen mapnaam.

Deze stap laadt de gecontroleerde driver zonder een andere geladen CAMSS te
verwijderen. Daarna moeten **drie volledige Full HD-frames** worden ontvangen
zonder nieuwe kernel-/camerafouten. Alleen na die geslaagde test wordt de
cameraboot standaard gemaakt en de App Lab-app geïmporteerd.
Een bestaande app met dezelfde naam wordt niet overschreven.

### 4. De app starten

Open Arduino App Lab en start **Ventuno IMX219 Objectdetectie**. Gebruik
**Open in browser** of de URL die App Lab aangeeft.

De app bevat de modelkeuze **YOLOX Small QNN**. Laat App Lab het model en de
Bricks voorbereiden als dat nodig is. Controleer bij een modelmelding de Object
Detection-brick en het model `ei:yolox-small-qnn-object-detection`.

Voortaan hoef je alleen de app te starten. De cameradienst begint na inschakelen
in rust en activeert de camera zodra de app erom vraagt. Na stoppen van de app
sluit de stream na afloop van de korte lease. CAMSS blijft tot uitschakelen geladen.

## Beeld en herkenning

Onder **Beeld** staan Helderheid en Contrast. De waarden gelden voor livebeeld
én de JPEG die naar het model gaat; het zijn geen browserfilters.

- **100%** is het meegeleverde afgestemde profiel.
- **Herstellen** zet beide schuiven terug op 100%.
- Waarden blijven op het board bewaard na afsluiten van de app.
- Meerdere browsers delen dezelfde camera-instellingen.

Witbalans en profiel zijn startwaarden uit één gemeten opstelling. Ze zijn geen
automatische belichting/witbalans of volledige kleurkalibratie. Belichting
blijft in deze versie vast op 1600 sensorlijnen.

**Livebeeld** loopt zelfstandig door. **Met kaders** toont het beeld dat bij de
specifieke analyse hoort. Oude kaders worden zo niet op een nieuw livebeeld
getekend. Inferentietijd en leeftijd livebeeld meten verschillende delen van de
keten; snelheid varieert met belasting en netwerk.

Objectdetectie gebruikt de klassen van het gekozen model. Een zichtbaar object
wordt niet noodzakelijk juist herkend.

## Status en problemen

```bash
sudo python3 install.py status
sudo journalctl -b -u ventuno-imx219-camera.service -n 80 --no-pager
```

| Melding/situatie | Betekenis of vervolgstap |
| --- | --- |
| `Camera wacht op de app` / `idle` | Normaal zolang de juiste app niet draait. Start de meegeleverde app. |
| Kernel of boardvariant niet ondersteund | Stop; alleen de combinatie bovenaan deze README is ondersteund. |
| De stabiliteitsboot is vereist | Je zit nog in gewone Ubuntu. Volg de eenmalige camerabootstap. |
| Eenmalige GRUB-keuze bestaat al | Bekijk `sudo grub-editenv /boot/grub/grubenv list`. Rond de bestaande keuze af. Een lege `next_entry=` is toegestaan. |
| Camera niet in rust | Stop de app en wacht 15 seconden voor een losse opnametest of herstel. |
| `Connection refused` | Bekijk dienststatus en journal. Controleer dat je de meegeleverde app gebruikt. |
| Camerafout in deze boot | De dienst probeert niet onbeperkt opnieuw. Bewaar de diagnose en onderzoek de oorzaak. |
| `Skipping BTF ... vmlinux` bij bouwen | Debuggegevens ontbreken; dit bericht alleen betekent geen mislukte modulebouw. Controleer de eindcontrole. |
| Gebruiker zit niet in `video` | Voeg de App Lab-gebruiker zo nodig toe met `sudo usermod -aG video "$USER"` en meld opnieuw aan. |

Bij een camerafout: **geen `rmmod`, `modprobe -r` of live CAMSS-wissel gebruiken**.
Een verkeerd stop-/teruglaadpad veroorzaakte eerder vastlopers. Dit pakket
hergebruikt een eenmaal geladen juiste module.

De browserinterface heeft geen inloglaag en is bedoeld voor een vertrouwd
lokaal netwerk. Publiceer de poort niet rechtstreeks op internet. De hostbrug
bindt alleen aan de Docker-hostgateway, niet aan het LAN-adres.

### Herstellen

Stop de app in App Lab en wacht 15 seconden:

```bash
sudo python3 install.py rollback
```

Dit schakelt de cameradienst uit en herstelt de eerdere bootkeuze. Geen
automatische herstart en geen verwijdering van een geladen module. App,
bronbestanden en lokale diagnose blijven bewaard. De app kun je apart in App
Lab verwijderen. Start zelf opnieuw om de oorspronkelijke boot te gebruiken.

Start de cameraboot niet goed, kies dan **Ubuntu** in GRUB. Na permanent maken
van de cameraboot is het menu vijf seconden zichtbaar. Bij een vroege kernelpanic
is lokaal GRUB-herstel nodig; vertrouw dan niet alleen op SSH.

### Bestaande installaties

Dit pakket overschrijft geen eerdere proefinstallatie of camera-service. Het
ontwikkelboard waarop de camera al werkt hoeft niet opnieuw geïnstalleerd te
worden. Een automatische migratie van alle losse eerdere testpakketten valt
buiten `1.0.0-rc.1`. Verwijder zulke bestanden niet op goed geluk: gebruik de
herstelroute van die versie of begin met een schone, passende Ubuntu-installatie.

## Afzonderlijke stappen

```bash
sudo bash scripts/install-dependencies.sh
bash scripts/build.sh
sudo python3 install.py prepare
sudo python3 install.py install
sudo python3 install.py test-boot
sudo reboot
# Na inloggen en teruggaan naar de pakketmap:
sudo python3 install.py verify
sudo python3 install.py make-default
arduino-app-cli app import dist/ventuno-imx219-app.zip
```

`prepare` schrijft alleen voorbeelden in `.build/`. `install` voegt de dienst
vervolgens toe. `make-default` vereist een geslaagde test uit dezelfde boot.

## Bestanden op het board

| Locatie | Inhoud |
| --- | --- |
| `/opt/ventuno-imx219-v2/` | Beschermde runtime, lokaal gebouwde driver en RGB-bibliotheek |
| `/var/lib/ventuno-imx219-v2/` | Back-up, opnametest, diagnose en bewaarde instellingen |
| `/var/lib/ventuno-imx219-v2/public-installation.json` | Beschermde herstelmetadata van dit pakket |
| `/var/lib/ventuno-imx219-v2/picture-settings.json` | Helderheid en contrast |
| `/dev/ventuno-imx219-control.sock` | Lokale app/dienstverbinding |
| `/boot/ventuno-imx219-camss/` | Voor het eigen board gemaakte camera-DTB |
| `.build/` | Lokale bouwproducten en tijdelijke bootgegevens; niet publiceren |

Opnamen en diagnose kunnen camerabeelden en lokale bootgegevens bevatten.
Deel bij een issue alleen relevante, gecontroleerde uitvoer. De release bevat
geen voorbeeldopnamen uit de ontwikkelomgeving.

## Ontwikkelen en herkomst

Zie [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) voor tests, broncontrole en
releasebouw. Licenties en bronherkomst staan in [NOTICE.md](NOTICE.md).

Referenties: [Arduino VENTUNO Q](https://docs.arduino.cc/hardware/ventuno-q),
[Arduino App CLI](https://github.com/arduino/arduino-app-cli),
[Linux CAMSS v6.8](https://github.com/torvalds/linux/tree/v6.8/drivers/media/platform/qcom/camss).
