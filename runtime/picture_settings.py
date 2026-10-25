"""Bounded, persistent picture controls; no sensor or module operations."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

SETTINGS_PATH = Path('/var/lib/ventuno-imx219-v2/picture-settings.json')
DEFAULTS = {'brightness': 100, 'contrast': 100}


def validate(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError('Geef helderheid en contrast op.')
    if any(type(value) is not int or not 50 <= value <= 150 for value in values.values()):
        raise ValueError('Kies gehele percentages tussen 50 en 150.')
    return dict(values)


def read(path):
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return dict(DEFAULTS)
    if (not isinstance(data, dict) or type(data.get('schema')) is not int
            or data['schema'] != 1 or set(data) != {'schema', *DEFAULTS}):
        raise ValueError('Ongeldige opgeslagen beeldinstellingen.')
    return validate({key: data[key] for key in DEFAULTS})


def describe(values):
    values = validate(values)
    revision = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]
    return {**values, 'revision': revision, 'defaults': dict(DEFAULTS), 'min': 50, 'max': 150}


class PictureStore:
    def __init__(self, path=SETTINGS_PATH):
        self.path = Path(path)
        self.values = read(self.path)

    def status(self):
        return describe(self.values)

    def save(self, values):
        candidate = validate(values)
        if candidate == self.values:
            return self.status()
        # One atomic replacement: readers see either the old or new complete file.
        fd, temporary = tempfile.mkstemp(prefix='.picture-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o640)
                stream.write(json.dumps({'schema': 1, **candidate}) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.values = candidate
        return self.status()


class LiveLook:
    def __init__(self, base, factory, path=SETTINGS_PATH):
        self.base, self.factory, self.path = dict(base), factory, Path(path)
        self.values, self.look, self.error = None, None, None
        self.refresh()
        if self.look is None:
            raise ValueError(self.error)

    def refresh(self):
        try:
            values = read(self.path)
            if values != self.values:
                profile = dict(self.base)
                profile['linear_brightness'] *= values['brightness'] / 100
                profile['contrast'] *= values['contrast'] / 100
                candidate = self.factory(profile)
                self.look, self.values = candidate, values
            self.error = None
        except (OSError, ValueError) as exc:
            # A bad settings file must not interrupt a working capture stream.
            self.error = str(exc)
        return self.look

    def status(self):
        return {**describe(self.values), 'error': self.error}
