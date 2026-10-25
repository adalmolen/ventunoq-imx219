"""Load only the already tested module, once; never unload or replace a live driver."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from boot_support import VERMAGIC, check_arguments
from camera_control import KERNEL, SRCVERSION, kernel_faults, run, sensor_entity


def validate_module(path):
    expected = json.loads(Path(__file__).with_name('driver_expected.json').read_text())
    if (expected.get('srcversion') != SRCVERSION or path.is_symlink() or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected.get('sha256')):
        raise RuntimeError('The CAMSS file does not match the tested stability module.')
    for field, value in [('srcversion', SRCVERSION), ('vermagic', VERMAGIC)]:
        if run(['modinfo', '-F', field, str(path)]).strip() != value:
            raise RuntimeError(f'Unexpected CAMSS {field}.')


def check_board():
    if os.geteuid() != 0 or os.uname().sysname != 'Linux' or os.uname().release != KERNEL:
        raise RuntimeError(f'Requires root on the Ventuno Q with kernel {KERNEL}.')
    if os.uname().machine != 'aarch64':
        raise RuntimeError('This package supports only the aarch64 Ventuno Q.')
    compatible = Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
    if b'arduino,monza' not in compatible or b'qcom,qcs8300' not in compatible:
        raise RuntimeError('The expected Ventuno Q / QCS8300 was not found.')
    check_arguments(Path('/proc/cmdline').read_text().split())
    if Path('/sys/module/camera_qcs8300').exists():
        raise RuntimeError('The vendor camera driver is loaded; no module will be replaced.')
    for name in ['modinfo', 'modprobe', 'insmod', 'udevadm', 'media-ctl', 'v4l2-ctl', 'fuser', 'docker']:
        if not shutil.which(name):
            raise RuntimeError(f'Missing host tool: {name}.')
    faults = kernel_faults(run(['dmesg']))
    if faults:
        raise RuntimeError('The current boot already contains a kernel/camera fault: ' + faults[0])


def load(path):
    check_board()
    validate_module(path)
    loaded = Path('/sys/module/qcom_camss/srcversion')
    if loaded.exists():
        if loaded.read_text().strip() != SRCVERSION:
            raise RuntimeError('A different CAMSS module is loaded. Stop; do not replace a live module.')
        return
    run(['modprobe', 'i2c-qcom-cci'])
    run(['modprobe', 'imx219'])
    sensor_entity()
    dependencies = run(['modinfo', '-F', 'depends', str(path)]).strip().split(',')
    for name in filter(None, dependencies):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', name) or name.replace('-', '_') in {'qcom_camss', 'camera_qcs8300'}:
            raise RuntimeError('Unexpected CAMSS dependency.')
        run(['modprobe', name])
    if Path('/sys/module/qcom_camss').exists():
        raise RuntimeError('CAMSS was loaded during this operation; do not replace a live module.')
    print('Loading the verified CAMSS stability module.', flush=True)
    run(['insmod', str(path)], timeout=45)
    run(['udevadm', 'settle', '--timeout=10'], timeout=12)
    if not loaded.exists() or loaded.read_text().strip() != SRCVERSION:
        raise RuntimeError('The loaded CAMSS version could not be confirmed.')
    check_board()
