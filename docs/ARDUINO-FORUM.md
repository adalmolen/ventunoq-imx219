# Suggested Arduino forum announcement

Title: IMX219 Camera Module 2 on VENTUNO Q: Full HD preview and App Lab object detection

Hi everyone,

I have been working on using a Raspberry Pi Camera Module 2 (Sony IMX219) on
Camera0 of the Arduino VENTUNO Q, connected with a suitable 15-to-22-pin CSI cable.
The project now provides a Full HD live preview and object detection through
Arduino App Lab, using YOLOX Small QNN.

The package includes a patched CAMSS driver, board-specific device-tree generation,
a camera service that starts capture when the app requests it, and a web interface
with detection boxes, image saving, and persistent brightness/contrast controls.

The source, installation guide, and English release downloads are available here:

- Repository and installation guide: https://github.com/adalmolen/ventunoq-imx219
- English release: https://github.com/adalmolen/ventunoq-imx219/releases/tag/v1.0.0-rc.2

This is an independent community project and currently a **release candidate**.
It supports only the checked `arduino,monza` / `qcom,qcs8300` board variant with
Ubuntu kernel **6.8.0-1080-qcom**. The camera pipeline works on my development board;
the complete new installer has not yet been tested on a second, fresh board.
Please read the compatibility and recovery notes before trying it.

The project is GPL-2.0, with the existing BSD-3-Clause device-tree overlays retaining
their licence. Feedback, test reports, and contributions are welcome!
