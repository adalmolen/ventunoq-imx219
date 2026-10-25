# Validation of 1.0.0-rc.2

Date: 25 October 2026.

## Working camera pipeline

The preceding version on the development board has been used with 1920 × 1080
RAW10 capture, RGB/JPEG live preview, YOLOX Small QNN, automatic camera startup
from App Lab, and persistent brightness/contrast controls. Stopping and restarting
the app has also been checked with the same CAMSS module kept loaded.

## Public installation package

- On macOS: 27 automated tests covering RGB processing, controls, boot menus,
  source/platform checks, and installation/rollback behaviour in temporary test directories.
- The same tests pass on the Ventuno Q as a regular user.
- The driver source was built on `6.8.0-1080-qcom`; the module has the expected
  `F5A7796BFE69666C456ECFB` source version and matching kernel ABI.
- The aarch64 RGB library was built from the included C source.
- Both camera overlays were reapplied to the original board DTB. Delta checks
  for the sensor, CAMSS, CCI clock, and preservation of other nodes passed.
- The newly built module was **not loaded** during package validation. The
  existing installation was not replaced, and GRUB was not modified.

RC2 translates the documentation, app interface, detection labels, and operational
messages to English. Camera settings, driver source, and installation stages are
unchanged. The translated package is checked with the same automated test suite.

A complete installation from a fresh Ubuntu boot and a test on a **second board**
have not yet been performed. This is therefore a release candidate. GitHub Actions
checks source files and CPU processing; it does not replace camera or QNN hardware
tests. The selected QNN model variant has been checked; NPU execution has not been
profiled separately.
