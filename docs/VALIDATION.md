# Validatie van 1.0.0-rc.1

Datum: 25 oktober 2026.

## Werkende cameraketen

De voorafgaande versie op het ontwikkelboard is hardwarematig gebruikt voor
1920 × 1080 RAW10, RGB/JPEG-livebeeld, YOLOX Small QNN, automatisch starten via
App Lab en bewaarde helderheid-/contrastregelaars. Ook het stoppen en opnieuw
starten van de app is gecontroleerd, met dezelfde geladen CAMSS-module.

## Publiek installatiepakket

- Op macOS: 27 automatische tests voor RGB-verwerking, regelaars, bootmenu's,
  bron-/platformcontroles en installatie-/herstelgedrag in tijdelijke testmappen.
- Dezelfde tests worden op de Ventuno Q uitgevoerd als gewone gebruiker.
- Driverbroncode is op `6.8.0-1080-qcom` gebouwd; de module heeft de verwachte
  `F5A7796BFE69666C456ECFB`-bronversie en passende kernel-ABI.
- De aarch64 RGB-bibliotheek is uit de meegeleverde C-bron gebouwd.
- Beide camera-overlays zijn opnieuw op de originele board-DTB toegepast.
  De deltakontroles voor sensor, CAMSS, CCI-klok en behoud van andere nodes slagen.
- De nieuw gebouwde module wordt tijdens deze pakketcontrole **niet geladen**;
  de bestaande installatie wordt niet vervangen en GRUB wordt niet aangepast.

Een volledige installatie vanaf een schone Ubuntu-boot en een test op een
**tweede board** zijn nog niet uitgevoerd. Daarom is dit een release candidate.
GitHub Actions controleert bronnen en CPU-verwerking; het vervangt geen camera-
of QNN-hardwaretest. De geselecteerde QNN-modelvariant is gecontroleerd; de
uitvoering op de NPU is niet afzonderlijk geprofileerd.
