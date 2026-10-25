"""RGGB10 preview conversion with direct Bayer-phase bilinear interpolation."""
import numpy as np


def unpack(data, width, height, stride):
    if width % 4 or height % 2 or stride < width * 5 // 4 or len(data) != height * stride:
        raise ValueError('The RAW10 dimensions/stride do not match the frame.')
    groups = np.frombuffer(data, np.uint8).reshape(height, stride)[:, :width * 5 // 4].reshape(height, width // 4, 5)
    result = np.empty((height, width), np.uint16)
    for k in range(4):
        result[:, k::4] = (groups[:, :, k].astype(np.uint16) << 2) | ((groups[:, :, 4] >> (2 * k)) & 3)
    return result


def _mean(total, count):
    # Exact round-to-even behavior of the existing float32 bilinear decoder.
    return np.rint(total.astype(np.float32) / count).astype(np.uint16)


def demosaic(raw):
    height, width = raw.shape
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ValueError('Bilinear RGGB requires even dimensions of at least 2x2.')
    result = np.empty((height, width, 3), np.uint16)

    # Interpolate each Bayer phase directly. No full-image masks, padding or
    # weighted 3x3 scans are needed. uint32 sums also preserve uint16 extremes.
    red = raw[0::2, 0::2].astype(np.uint32)
    plane = result[:, :, 0]
    plane[0::2, 0::2] = red
    plane[0::2, 1:-1:2] = _mean(red[:, :-1] + red[:, 1:], 2)
    plane[1:-1:2, 0::2] = _mean(red[:-1, :] + red[1:, :], 2)
    plane[1:-1:2, 1:-1:2] = _mean(red[:-1, :-1] + red[:-1, 1:] + red[1:, :-1] + red[1:, 1:], 4)
    plane[-1, :-1] = plane[-2, :-1]
    plane[:, -1] = plane[:, -2]

    blue = raw[1::2, 1::2].astype(np.uint32)
    plane = result[:, :, 2]
    plane[1::2, 1::2] = blue
    plane[1::2, 2::2] = _mean(blue[:, :-1] + blue[:, 1:], 2)
    plane[2::2, 1::2] = _mean(blue[:-1, :] + blue[1:, :], 2)
    plane[2::2, 2::2] = _mean(blue[:-1, :-1] + blue[:-1, 1:] + blue[1:, :-1] + blue[1:, 1:], 4)
    plane[0, 1:] = plane[1, 1:]
    plane[:, 0] = plane[:, 1]

    # Green is measured on two phases. At red/blue sites average the available
    # axial neighbors. The outer two edges have three neighbors, corners two.
    plane = result[:, :, 1]
    plane[0::2, 1::2] = raw[0::2, 1::2]
    plane[1::2, 0::2] = raw[1::2, 0::2]
    total = raw[0::2, 1::2].astype(np.uint32) + raw[1::2, 0::2]
    total[:, 1:] += raw[0::2, 1:-1:2]
    total[1:, :] += raw[1:-1:2, 0::2]
    green = _mean(total, 4)
    green[0, 1:] = _mean(total[0, 1:], 3)
    green[1:, 0] = _mean(total[1:, 0], 3)
    green[0, 0] = _mean(total[0, 0], 2)
    plane[0::2, 0::2] = green
    total = raw[1::2, 0::2].astype(np.uint32) + raw[0::2, 1::2]
    total[:, :-1] += raw[1::2, 2::2]
    total[:-1, :] += raw[2::2, 1::2]
    green = _mean(total, 4)
    green[-1, :-1] = _mean(total[-1, :-1], 3)
    green[:-1, -1] = _mean(total[:-1, -1], 3)
    green[-1, -1] = _mean(total[-1, -1], 2)
    plane[1::2, 1::2] = green
    return result


def colour_lut(gains, black=64, display_gain=3.0):
    gains = np.asarray(gains, dtype=np.float32)
    if gains.shape != (3,) or not np.all(np.isfinite(gains)) or np.any(gains <= 0):
        raise ValueError('Invalid white balance gains.')
    if not 0 <= black < 1023 or not np.isfinite(display_gain) or display_gain <= 0:
        raise ValueError('Invalid black level or display gain.')
    linear = np.clip((np.arange(1024, dtype=np.float32)[:, None] - black) * gains[None, :] * display_gain / (1023 - black), 0, 1)
    encoded = np.where(linear <= .0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - .055)
    return np.rint(encoded * 255).astype(np.uint8)


def convert(data, width, height, stride, lut):
    rgb = demosaic(unpack(data, width, height, stride))
    result = np.empty_like(rgb, dtype=np.uint8)
    for channel in range(3):
        result[:, :, channel] = lut[rgb[:, :, channel], channel]
    return result
