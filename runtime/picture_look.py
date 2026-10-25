"""Fused native RGB processing; existing sensor setup and app API preserved."""
import json
import math
from pathlib import Path
import re

import ctypes
import numpy as np
from PIL import Image


DEFAULT = {'schema': 3, 'exposure_lines': 1600, 'linear_brightness': 3.5,
           'saturation': 1.25, 'red_tint': 1.06, 'blue_tint': .94,
           'contrast': 1.18, 'black_point': .012, 'noise_strength': 1.0, 'threads': 1}
LEGACY_KEYS = {'schema', 'exposure_lines', 'linear_brightness', 'saturation', 'red_tint', 'blue_tint'}


def validate(profile):
    if not isinstance(profile, dict) or type(profile.get('schema')) is not int:
        raise ValueError('Onbekend beeldprofiel.')
    if profile['schema'] == 1 and set(profile) == LEGACY_KEYS:
        # During update, new code can still read the existing v1 profile.
        profile = dict(DEFAULT, **profile)
        profile.update(schema=3, contrast=1, black_point=0, noise_strength=0)
    if set(profile) != set(DEFAULT) or profile['schema'] != 3:
        raise ValueError('Onbekend beeldprofiel.')
    bounds = {'exposure_lines': (4, 1600), 'linear_brightness': (1, 6),
              'saturation': (1, 1.8), 'red_tint': (.9, 1.1), 'blue_tint': (.9, 1.1),
              'contrast': (.5, 1.8), 'black_point': (0, .04), 'noise_strength': (0, 1), 'threads': (1, 2)}
    for name, (low, high) in bounds.items():
        value = profile[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Ongeldige beeldinstelling: {name}.')
    if type(profile['exposure_lines']) is not int or type(profile['threads']) is not int:
        raise ValueError('De belichting moet een geheel aantal lijnen zijn.')
    return dict(profile)


def load(path=None):
    return validate(json.loads((Path(path) if path else Path(__file__).with_name('picture_profile.json')).read_text()))


def apply_exposure(sensor, target, run):
    text = run(['v4l2-ctl', '-d', sensor, '--list-ctrls'])
    match = re.search(r'^\s*exposure\s+0x[0-9a-f]+\s+\([^)]*\)\s*:\s*([^\n]*)', text, re.M | re.I)
    values = {key: int(value) for key, value in re.findall(r'\b(min|max|step)=(-?\d+)\b', match[1])} if match else {}
    if (set(values) != {'min', 'max', 'step'} or values['step'] <= 0
            or not values['min'] <= target <= values['max']
            or (target - values['min']) % values['step']):
        raise RuntimeError('De beeldprofielbelichting past niet binnen het huidige sensorbereik.')
    run(['v4l2-ctl', '-d', sensor, f'--set-ctrl=exposure={target}'])
    actual = run(['v4l2-ctl', '-d', sensor, '--get-ctrl=exposure'])
    if not re.search(rf'^exposure:\s*{target}\s*$', actual, re.M):
        raise RuntimeError('De beeldprofielbelichting kon niet worden teruggelezen.')


def curve(value, tint, profile):
    x = value / 255
    linear = (x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4) * tint
    gain = profile['linear_brightness']
    linear = gain * linear / (1 + (gain - 1) * linear)
    x = linear * 12.92 if linear <= .0031308 else 1.055 * linear ** (1 / 2.4) - .055
    x = max(0.0, min(1.0, (x - profile['black_point']) / (1 - profile['black_point'])))
    # Gentle S curve: stronger black/white separation with preserved endpoints.
    if 0 < x < 1:
        low, high = x ** profile['contrast'], (1 - x) ** profile['contrast']
        x = low / (low + high)
    return round(x * 255)


class Look:
    def __init__(self, profile):
        self.profile = validate(profile)
        self.curves = (ctypes.c_uint8 * 768)(*[curve(value, tint, self.profile)
                       for tint in (self.profile['red_tint'], 1, self.profile['blue_tint'])
                       for value in range(256)])
        self.library = ctypes.CDLL(str(Path(__file__).with_name('picture_native.so')))
        self.process = self.library.picture_process
        self.process.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_void_p, ctypes.c_size_t,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.process.restype = ctypes.c_int

    def apply(self, image):
        if image.mode != 'RGB':
            raise ValueError('De beeldverwerking vereist RGB.')
        return self.apply_array(np.asarray(image))

    def apply_array(self, source):
        if not isinstance(source, np.ndarray) or source.ndim != 3 or source.shape[2] != 3:
            raise ValueError('Onverwachte RGB-buffer.')
        height, width = source.shape[:2]
        if source.dtype != np.uint8 or not source.flags.c_contiguous:
            raise ValueError('Onverwachte RGB-buffer.')
        output = np.empty_like(source)
        result = self.process(source.ctypes.data, source.nbytes, output.ctypes.data,
                              output.nbytes, width, height, self.curves, 768,
                              round(self.profile['saturation'] * 256),
                              round(self.profile['noise_strength'] * 256), self.profile['threads'])
        if result:
            raise RuntimeError(f'Native RGB-verwerking mislukt ({result}).')
        return Image.fromarray(output)
