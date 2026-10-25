# IMX219 on Arduino VENTUNO Q

An installation package for the **Raspberry Pi Camera Module 2 (Sony IMX219)** on
**Camera0 of the Arduino VENTUNO Q**. Includes a Full HD live preview, object
detection in Arduino App Lab, and brightness and contrast controls.

**Version 1.0.0-rc.2 — English public preview.** The camera pipeline and app have
been tested on one Ventuno Q. The complete installer has additional automated
tests, build checks, and device-tree validation. A full installation on a second,
fresh Ventuno Q has not yet been verified.

This is an independent community project. It targets the VENTUNO Q, not a
Raspberry Pi computer, and is not an official Arduino camera driver.

## Supported configuration

| Component | Support in this release |
| --- | --- |
| Board | VENTUNO Q with device-tree identifiers `arduino,monza` and `qcom,qcs8300` |
| Camera | Raspberry Pi Camera Module 2, Sony IMX219 |
| Connection | Camera0, suitable 15-to-22-pin CSI cable |
| Linux | Ubuntu 24.04; tested with 24.04.4 LTS, aarch64 |
| Kernel | **Only `6.8.0-1080-qcom`** |
| Ubuntu kernel source | `linux-qcom 6.8.0-1080.85` |
| Arduino App CLI | Tested with `0.14.0`, included with Arduino App Lab |
| Capture | 1920 × 1080, packed RGGB RAW10 (`pRAA`), approximately 30 RAW frames/s |
| Live preview | RGB/JPEG, up to 10 processed frames/s, depending on system load |
| Detection | YOLOX Small QNN, 640 × 640 model input, up to 5 analyses/s |

**Other board variants and kernels are rejected.** The VENTUNO Q name alone is
not sufficient to establish compatibility. The package does not install an older
kernel or automatically upgrade your operating system.
The RAW capture rate is different from the web preview and AI processing rates.

## Features

- Patched CAMSS driver with the complete source used to build it and separate patches.
- Camera configuration generated from **your board's own firmware DTB**.
- Dedicated camera boot entry with the normal Ubuntu entry retained as a fallback.
- Camera service that waits until the App Lab app requests the camera.
- App with an independent live preview, detection boxes, confidence threshold, and image saving.
- Brightness and contrast from 50–150%, saved automatically on the board.
- Rollback command and checksums for sources and downloads.

Model weights and Ubuntu/Arduino images are not included. App Lab manages the
model, so initial preparation may require internet access.

## Before you start

1. Make sure Arduino App Lab works on your Ventuno Q and you can open a terminal.
2. Connect the camera to Camera0 **with the power disconnected**. Check the contact
   orientation and use a suitable cable; 15/22-pin cables do not all have the same wiring.
3. Check `uname -r`. Continue only with `6.8.0-1080-qcom`.
4. Secure Boot must be disabled. The installer checks it but does not change it.
5. Use your regular App Lab user account. Use `sudo` only where shown.
6. Close other camera apps. Keep access to a display and GRUB for the first camera boot.

Use this package for a **fresh camera installation**. Earlier experimental
installations are preserved; see [Existing installations](#existing-installations).

## Installation

Run these commands on the **Ventuno Q**, not on your Mac or Windows PC.

### 1. Download

```bash
cd ~
git clone https://github.com/adalmolen/ventunoq-imx219.git
cd ventunoq-imx219
```

If `git` is missing, install it with `sudo apt-get install git`.
Alternatively, download the source archive from [Releases](https://github.com/adalmolen/ventunoq-imx219/releases)
and extract it on the board. Use the extracted directory's name in the following steps.

### 2. Prepare the installation

```bash
bash setup.sh
```

This installs dependencies, builds the driver and RGB processing library, and
validates the camera DTB and GRUB configuration. It then installs the camera
service and boot entry. Confirm the package installation if Ubuntu prompts you.

- No `apt upgrade`, operating system upgrade, or automatic reboot.
- The original CAMSS module under `/lib/modules` is preserved.
- The normal Ubuntu entry remains the default at this stage.
- The camera entry is selected **once** for the next boot.

Reboot manually:

```bash
sudo reboot
```

### 3. Finish after rebooting

```bash
cd ~/ventunoq-imx219
bash setup.sh --finish
```

If you extracted a release archive, use its directory name instead.

This loads the verified driver without unloading another CAMSS module. The
camera must then deliver **three complete Full HD frames** without new kernel
or camera faults. Only after this test succeeds does the installer make the
camera boot the default and import the App Lab app.
An existing app with the same name is preserved.

### 4. Start the app

Open Arduino App Lab and start **Ventuno IMX219 Object Detection**. Use
**Open in browser** or the URL shown by App Lab.

The app selects **YOLOX Small QNN**. Allow App Lab to prepare the model and
Bricks when needed. If a model error appears, check the Object Detection brick
and the model `ei:yolox-small-qnn-object-detection`.

From then on, you only need to start the app. After power-on, the camera service
starts idle and activates the camera when the app requests it. When the app
stops, the stream closes after the short lease expires. CAMSS stays loaded until shutdown.

## Picture and detection

**Picture** contains the Brightness and Contrast controls. They affect both the
live preview and the JPEG sent to the model; they are not browser filters.

- **100%** is the supplied, tuned picture profile.
- **Reset** returns both sliders to 100%.
- Values stay saved on the board after the app closes.
- Multiple browsers share the same camera settings.

White balance and the profile are starting values from one measured setup.
They do not provide automatic exposure, automatic white balance, or full colour
calibration. Exposure remains fixed at 1600 sensor lines in this release.

**Live preview** updates independently. **With detections** shows the image
that belongs to that particular analysis, so old boxes are not drawn over a new
live frame. Inference time and live preview age measure different parts of the
pipeline; performance varies with system load and network conditions.

Object detection uses the selected model's classes. A visible object may not be
recognised correctly.

## Status and troubleshooting

```bash
sudo python3 install.py status
sudo journalctl -b -u ventuno-imx219-camera.service -n 80 --no-pager
```

| Message or situation | Meaning or next step |
| --- | --- |
| `Camera is waiting for the app` / `idle` | Normal while the app is stopped. Start the supplied app. |
| Unsupported kernel or board variant | Stop; only the configuration listed above is supported. |
| The stability boot is required | You are still in normal Ubuntu. Follow the one-time camera boot step. |
| A one-time GRUB selection is pending | Inspect `sudo grub-editenv /boot/grub/grubenv list`. Complete the existing selection first. An empty `next_entry=` is allowed. |
| Camera is not idle | Stop the app and wait 15 seconds before a separate capture test or rollback. |
| `Connection refused` | Check the service status and journal. Make sure you are using the supplied app. |
| Camera fault in the current boot | The service will not retry indefinitely. Save the diagnostics and investigate the cause. |
| `Skipping BTF ... vmlinux` during a build | Debug information is unavailable; this message alone does not mean the module build failed. Check the final verification. |
| User is not in `video` | If necessary, add the App Lab user with `sudo usermod -aG video "$USER"`, then sign in again. |

After a camera fault, **do not use `rmmod`, `modprobe -r`, or replace CAMSS while
it is loaded**. A faulty stop/reload path previously caused hangs. This package
reuses the correct module once it is loaded.

The browser interface has no login layer and is intended for a trusted local
network. Do not expose its port directly to the internet. The host bridge binds
to the Docker host gateway only, not the LAN address.

### Rollback

Stop the app in App Lab and wait 15 seconds:

```bash
sudo python3 install.py rollback
```

This disables the camera service and restores the previous boot selection.
It does not reboot or unload a running module. The app, source files, and local
diagnostics are retained. You can remove the app separately in App Lab.
Reboot manually to use the original boot configuration.

If the camera boot fails, select **Ubuntu** in GRUB. After the camera entry is
made permanent, the menu is visible for five seconds. An early kernel panic may
require local GRUB recovery; do not rely solely on SSH.

### Existing installations

This package preserves earlier experimental installations and camera services.
There is no need to reinstall the development board where the camera already
works. Automatic migration from earlier individual test packages is outside the
scope of `1.0.0-rc.2`. Do not delete those files indiscriminately: use that version's
recovery procedure or start from a fresh, compatible Ubuntu installation.

## Individual steps

```bash
sudo bash scripts/install-dependencies.sh
bash scripts/build.sh
sudo python3 install.py prepare
sudo python3 install.py install
sudo python3 install.py test-boot
sudo reboot
# After signing in and returning to the package directory:
sudo python3 install.py verify
sudo python3 install.py make-default
arduino-app-cli app import dist/ventuno-imx219-app.zip
```

`prepare` only writes previews under `.build/`. `install` then adds the service.
`make-default` requires a successful test from the same boot.

## Files on the board

| Location | Contents |
| --- | --- |
| `/opt/ventuno-imx219-v2/` | Protected runtime, locally built driver, and RGB library |
| `/var/lib/ventuno-imx219-v2/` | Backup, capture test, diagnostics, and saved settings |
| `/var/lib/ventuno-imx219-v2/public-installation.json` | Protected rollback metadata for this package |
| `/var/lib/ventuno-imx219-v2/picture-settings.json` | Brightness and contrast |
| `/dev/ventuno-imx219-control.sock` | Local app/service connection |
| `/boot/ventuno-imx219-camss/` | Camera DTB generated for this board |
| `.build/` | Local build products and temporary boot data; do not publish |

Captures and diagnostics may contain camera images and local boot information.
Share only relevant, reviewed output when opening an issue. The release contains
no private sample recordings from the development environment.

## Development and source attribution

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for tests, source verification, and
release builds, and [docs/VALIDATION.md](docs/VALIDATION.md) for the validation scope.
Licences and source attribution are in [NOTICE.md](NOTICE.md).

References: [Arduino VENTUNO Q](https://docs.arduino.cc/hardware/ventuno-q),
[Arduino App CLI](https://github.com/arduino/arduino-app-cli),
[Linux CAMSS v6.8](https://github.com/torvalds/linux/tree/v6.8/drivers/media/platform/qcom/camss).
