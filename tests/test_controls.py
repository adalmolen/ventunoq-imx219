import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HOST = Path(__file__).resolve().parents[1] / 'runtime'
sys.path.insert(0, str(HOST))
from picture_settings import DEFAULTS, LiveLook, PictureStore, describe, read, validate


class ControlsTests(unittest.TestCase):
    def test_rejects_invalid_and_partial_values(self):
        for values in [None, {}, {'brightness': 100}, {'brightness': True, 'contrast': 100},
                       {'brightness': 100.0, 'contrast': 100}, {'brightness': 151, 'contrast': 100},
                       {'brightness': 100, 'contrast': 49}, {'brightness': 100, 'contrast': 100, 'exposure': 1}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate(values)

    def test_persistence_and_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'settings.json'
            store = PictureStore(path)
            self.assertEqual(store.values, DEFAULTS)
            result = store.save({'brightness': 123, 'contrast': 87})
            self.assertNotEqual(result['revision'], describe(DEFAULTS)['revision'])
            self.assertEqual(PictureStore(path).values, {'brightness': 123, 'contrast': 87})
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            PictureStore(path).save(DEFAULTS)
            self.assertEqual(read(path), DEFAULTS)

    def test_failed_write_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'settings.json'
            store = PictureStore(path)
            store.save({'brightness': 110, 'contrast': 90})
            original = path.read_bytes()
            with patch('picture_settings.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): store.save(DEFAULTS)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(store.values, {'brightness': 110, 'contrast': 90})
            self.assertEqual(list(Path(d).glob('.picture-*')), [])

    def test_live_swap_preserves_sensor_and_base_and_survives_bad_file(self):
        class FakeLook:
            def __init__(self, profile): self.profile = profile
        base = {'exposure_lines': 1600, 'linear_brightness': 3.5, 'contrast': 1.18, 'threads': 1}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'settings.json'
            runtime = LiveLook(base, FakeLook, path)
            first = runtime.look
            store = PictureStore(path)
            store.save({'brightness': 150, 'contrast': 50})
            second = runtime.refresh()
            self.assertIsNot(first, second)
            self.assertEqual(second.profile, {**base, 'linear_brightness': 5.25, 'contrast': .59})
            self.assertEqual(first.profile, base)
            self.assertEqual(base['linear_brightness'], 3.5)
            path.write_text('{broken')
            self.assertIs(runtime.refresh(), second)
            self.assertIsNotNone(runtime.error)
            store.save(DEFAULTS)
            self.assertEqual(runtime.refresh().profile, base)
            self.assertIsNone(runtime.error)

    def test_manager_requires_live_session_and_rejects_extra_fields(self):
        # The manager imports hardware helpers, but request() never touches hardware.
        with patch.dict(sys.modules, {'module_loader': types.SimpleNamespace(load=lambda _: None)}):
            import camera_manager
        with tempfile.TemporaryDirectory() as d:
            manager = camera_manager.Manager(1000, Path(d))
            identity = 'd08a3b11-540f-465c-8fda-ac1c48de0067'
            with self.assertRaises(ValueError):
                manager.request({'action': 'picture_set', 'session': identity, 'values': DEFAULTS})
            with patch.object(camera_manager, 'boot_id', return_value='test-boot'):
                manager.request({'action': 'lease', 'session': identity})
                reply = manager.request({'action': 'picture_set', 'session': identity,
                                         'values': {'brightness': 120, 'contrast': 80}})
                self.assertEqual(reply['picture']['brightness'], 120)
                self.assertEqual(manager.request({'action': 'picture_get'})['picture']['contrast'], 80)
            for payload in [{'action': 'status', 'values': DEFAULTS}, {'action': 'lease', 'session': identity, 'values': DEFAULTS},
                            {'action': 'picture_get', 'command': 'whoami'}]:
                with self.assertRaises(ValueError): manager.request(payload)

    def test_profile_range_extremes_keep_valid_monotonic_curves(self):
        from picture_look import DEFAULT, curve, validate as validate_profile
        for brightness in [50, 100, 150]:
            for contrast in [50, 100, 150]:
                profile = validate_profile({**DEFAULT, 'linear_brightness': 3.5 * brightness / 100,
                                             'contrast': 1.18 * contrast / 100})
                values = [curve(i, 1, profile) for i in range(256)]
                self.assertEqual(values, sorted(values))
                self.assertEqual(values[0], 0)
                self.assertEqual(values[-1], 255)
        p = {**DEFAULT, 'linear_brightness': 5.25}
        self.assertGreater(curve(80, 1, p), curve(80, 1, DEFAULT))


if __name__ == '__main__': unittest.main()
