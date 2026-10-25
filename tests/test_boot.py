# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import boot_setup as boot

UUID = '11111111-2222-4333-8444-555555555555'
ORIGINAL = f'''set default="0"
menuentry 'Ubuntu' --class ubuntu --id 'ubuntu-fixture' {{
    load_video
    insmod gzio
    insmod part_gpt
    insmod ext2
    search --no-floppy --fs-uuid --set=root {UUID}
    savedefault
    linux /boot/vmlinuz-{boot.KERNEL} root=UUID={UUID} ro console=ttyMSM0,115200n8
    initrd /boot/initrd.img-{boot.KERNEL}
}}
submenu 'Advanced options for Ubuntu' {{
}}
'''


class BootTests(unittest.TestCase):
    def test_uses_this_boards_root_and_retains_ubuntu(self):
        menu = boot.make_menu(ORIGINAL, 'fdt')
        self.assertIn('root=UUID=' + UUID, menu)
        self.assertIn('--set=root ' + UUID, menu)
        self.assertIn('modprobe.blacklist=qcom_camss', menu)
        self.assertIn('module_blacklist=camera_qcs8300', menu)
        self.assertIn('ventuno_imx219_stability=1', menu)
        self.assertNotIn('savedefault', menu)
        boot.validate_config(ORIGINAL, ORIGINAL + menu, menu)

    def test_separate_boot_partition(self):
        original = ORIGINAL.replace('/boot/vmlinuz', '/vmlinuz').replace('/boot/initrd', '/initrd')
        menu = boot.make_menu(original, 'fdt')
        self.assertIn('devicetree /ventuno-imx219-camss/camss-', menu)
        self.assertIn('initrd /initrd.img-', menu)

    def test_refuses_unexpected_kernel_and_existing_tree(self):
        for original in [ORIGINAL.replace(boot.KERNEL, '6.8.0-9999-qcom'),
                         ORIGINAL.replace('    initrd', '    devicetree /other.dtb\n    initrd'),
                         ORIGINAL.replace(' ro console', ' ro module_blacklist=qcom_camss console')]:
            with self.assertRaises(ValueError): boot.make_menu(original, 'fdt')

    def test_refuses_changes_to_ubuntu_or_default_or_duplicate_entry(self):
        menu = boot.make_menu(ORIGINAL, 'fdt')
        for after in [(ORIGINAL + menu).replace('115200n8', '9600n8', 1),
                      (ORIGINAL + menu).replace('set default="0"', 'set default="1"'),
                      ORIGINAL + menu + menu]:
            with self.assertRaises(ValueError): boot.validate_config(ORIGINAL, after, menu)
        after = (ORIGINAL + menu).replace('set default="0"', 'set default="ventuno-imx219-stability"')
        boot.validate_config(ORIGINAL, after, menu, default=True)

    def test_generator_is_conditional_and_quoted(self):
        text = boot.generator(boot.make_menu(ORIGINAL, 'fdt'))
        self.assertIn("cat <<'VENTUNO_IMX219_PUBLIC_MENU'", text)
        self.assertIn(f'[ -f /boot/vmlinuz-{boot.KERNEL} ]', text)
        with self.assertRaises(ValueError): boot.generator('VENTUNO_IMX219_PUBLIC_MENU')


if __name__ == '__main__': unittest.main()
