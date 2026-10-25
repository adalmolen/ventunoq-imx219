# Licenties en herkomst

De projectcode wordt verspreid onder **GPL-2.0-only**; zie [LICENSE](LICENSE).
De twee device-tree-overlays in `boot/` behouden hun **BSD-3-Clause**-licentie;
zie de SPDX-regel in die bestanden en [de licentietekst](LICENSES/BSD-3-Clause.txt).
Bestaande copyright- en SPDX-vermeldingen in de Linux-driver blijven geldig.

## Linux CAMSS-driver

`driver/camss/` bevat de volledige gebruikte CAMSS-broncode, inclusief
Makefile en headers, voor Ubuntu `linux-qcom 6.8.0-1080.85`.
De oorspronkelijke Linux Foundation-, Linaro- en Qualcomm-vermeldingen zijn behouden.
De code is gereconstrueerd uit de officiële Linux v6.8-bronnen en de Ubuntu-bronpatches.
De herkomst en controlesommen staan in [driver/provenance.json](driver/provenance.json).

De projectaanpassingen, gedateerd oktober 2026, staan afzonderlijk in `driver/patches/`:

- QCS8300 gebruikt de bestaande SA8775P CSI-PHY-tabel.
- Pipeline power wordt gekoppeld aan starten/stoppen van streaming.
- Een controle voorkomt derefereren van ontbrekende sensor-pads.

Het pipeline-power-backport is gebaseerd op Linux-commit
[`164202f682030cf8702f11cb63ccbcf2a81b2e75`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=164202f682030cf8702f11cb63ccbcf2a81b2e75).
De originele upstream-patch en de lokale backport zijn beide opgenomen.

## Niet meegeleverde software

Arduino App Lab, Arduino Bricks, Docker, Python-pakketten en AI-modellen zijn
externe afhankelijkheden met hun eigen licenties en voorwaarden. Dit pakket
herdistribueert geen modelgewichten, Arduino-software-images of Ubuntu-kernelimages.
App Lab haalt het geselecteerde model via zijn eigen voorzieningen op.

Arduino, VENTUNO, Raspberry Pi, Sony en Qualcomm zijn namen van hun respectieve
rechthebbenden. Dit is een onafhankelijk communityproject, geen officieel
ondersteund camerastuurprogramma van die fabrikanten.
