# Licences and source attribution

Project code is distributed under **GPL-2.0-only**; see [LICENSE](LICENSE).
The two device-tree overlays in `boot/` retain their **BSD-3-Clause** licence;
see their SPDX identifiers and the [licence text](LICENSES/BSD-3-Clause.txt).
Existing copyright notices and SPDX identifiers in the Linux driver remain applicable.

## Linux CAMSS driver

`driver/camss/` contains the complete CAMSS source used here, including the
Makefile and headers, for Ubuntu `linux-qcom 6.8.0-1080.85`.
The original Linux Foundation, Linaro, and Qualcomm notices are preserved.
The code was reconstructed from official Linux v6.8 sources and Ubuntu source patches.
Source provenance and checksums are recorded in [driver/provenance.json](driver/provenance.json).

Project changes, dated October 2026, are provided separately in `driver/patches/`:

- QCS8300 uses the existing SA8775P CSI-PHY table.
- Pipeline power is tied to starting and stopping streaming.
- A guard prevents dereferencing missing sensor pads.

The pipeline power backport is based on Linux commit
[`164202f682030cf8702f11cb63ccbcf2a81b2e75`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=164202f682030cf8702f11cb63ccbcf2a81b2e75).
Both the original upstream patch and the local backport are included.

## Software not included

Arduino App Lab, Arduino Bricks, Docker, Python packages, and AI models are
external dependencies with their own licences and terms. This package does not
redistribute model weights, Arduino software images, or Ubuntu kernel images.
App Lab downloads the selected model through its own facilities.

Arduino, VENTUNO, Raspberry Pi, Sony, and Qualcomm are names of their respective
owners. This is an independent community project, not an officially supported
camera driver from those manufacturers.
