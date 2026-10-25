# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from camera_control import sensor_entity


class RuntimeTests(unittest.TestCase):
    def test_finds_sensor_without_fixed_i2c_bus_number(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            driver = root/'driver';driver.mkdir()
            ofnode = root/'fdt/soc@0/cci@ac13000/i2c-bus@0/sensor@10';ofnode.mkdir(parents=True)
            device = root/'devices/camera';device.mkdir(parents=True)
            (device/'of_node').symlink_to(ofnode)
            (driver/'23-0010').symlink_to(device)
            self.assertEqual(sensor_entity(driver), 'imx219 23-0010')
            (driver/'14-0010').symlink_to(device)
            with self.assertRaises(RuntimeError): sensor_entity(driver)

    def test_refuses_missing_sensor_or_different_camera_port(self):
        with tempfile.TemporaryDirectory() as directory:
            driver = Path(directory)
            with self.assertRaises(RuntimeError): sensor_entity(driver)
            device=driver/'wrong';device.mkdir()
            (device/'of_node').symlink_to(driver/'fdt/soc@0/cci@ac14000/i2c-bus@0/sensor@10')
            (driver/'14-0010').symlink_to(device)
            with self.assertRaises(RuntimeError): sensor_entity(driver)


if __name__ == '__main__': unittest.main()
