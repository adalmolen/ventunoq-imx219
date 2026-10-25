# SPDX-License-Identifier: GPL-2.0-only
"""Generate this board's DTB and clone its actual Ubuntu entry, without assumptions about UUIDs."""
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'boot'))
sys.path.insert(0, str(ROOT / 'runtime'))
from probe_support import KERNEL, cells, fdt_nodes, is_temporary_chosen_property, make_menu as probe_menu, validate_probe
from camss_support import validate_camss_delta
from boot_support import menu_blocks, check_arguments

ENTRY = 'ventuno-imx219-stability'
DTB = Path(f'/boot/ventuno-imx219-camss/camss-{KERNEL}.dtb')


def secure_boot(blob):
    var = Path('/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c')
    if var.exists():
        raw = var.read_bytes()
        if len(raw) < 5 or raw[4] not in (0, 1): raise ValueError('Secure Boot status is unknown.')
        enabled = raw[4] == 1
    else:
        raw = fdt_nodes(blob).get('/chosen', {}).get('linux,uefi-secure-boot')
        if raw is None or cells(raw) not in {(2,), (3,)}: raise ValueError('Secure Boot status is unknown.')
        enabled = cells(raw) == (3,)
    if enabled: raise ValueError('Secure Boot must be disabled for this experimental camera boot. Nothing has been changed.')
    lock = Path('/sys/kernel/security/lockdown')
    if lock.exists() and '[none]' not in lock.read_text(): raise ValueError('Kernel lockdown is active.')


def loader_module():
    locations = [Path('/boot/grub/arm64-efi'), Path('/usr/lib/grub/arm64-efi')]
    for path in locations:
        if not (path / 'command.lst').is_file(): continue
        for line in (path / 'command.lst').read_text().splitlines():
            match = re.fullmatch(r'devicetree:\s*([A-Za-z0-9_-]+)\s*', line)
            if match and any((folder / (match[1] + '.mod')).is_file() for folder in locations): return match[1]
    raise ValueError('The GRUB module for devicetree is missing.')


def make_menu(grub, loader):
    menu = probe_menu(grub, loader_module=loader)
    for old, new in [('Ventuno Q IMX219 Camera0 sensor test', 'Ventuno Q IMX219 Camera0'),
                     ("--id 'ventuno-imx219-probe'", f"--id '{ENTRY}'"),
                     (f'/ventuno-imx219-probe/probe-{KERNEL}.dtb', f'/ventuno-imx219-camss/camss-{KERNEL}.dtb'),
                     ('ventuno_imx219_probe=1', 'ventuno_imx219_stability=1')]:
        if menu.count(old) != 1: raise ValueError('Unexpected Ubuntu menu structure.')
        menu = menu.replace(old, new)
    lines = menu.splitlines()
    for i, line in enumerate(lines):
        if re.match(r'\s*linux\s', line):
            parts = line.split()
            args = parts[2:]
            if 'qcom_camss' in {name.replace('-', '_') for arg in args if arg.startswith('module_blacklist=') for name in arg.split('=', 1)[1].split(',')}:
                raise ValueError('The kernel also blocks explicit loading of CAMSS.')
            blacklists = [arg for arg in args if arg.startswith('modprobe.blacklist=')]
            if len(blacklists) > 1: raise ValueError('Duplicate modprobe.blacklist.')
            names = {name for arg in blacklists for name in arg.split('=', 1)[1].split(',') if name}
            names.add('qcom_camss')
            args = [arg for arg in args if not arg.startswith('modprobe.blacklist=')]
            args.append('modprobe.blacklist=' + ','.join(sorted(names)))
            check_arguments(args)
            lines[i] = '\tlinux ' + parts[1] + ' ' + ' '.join(args)
    return '\n'.join(lines) + '\n'


def generator(menu):
    delimiter = 'VENTUNO_IMX219_PUBLIC_MENU'
    if delimiter in menu: raise ValueError('Unexpected marker in the GRUB menu.')
    return (f'#!/bin/sh\n# ventunoq-imx219: {KERNEL}, Camera0\n'
            f'if [ -f /boot/vmlinuz-{KERNEL} ] && [ -f /boot/initrd.img-{KERNEL} ] && [ -f {DTB} ]; then\n'
            f"cat <<'{delimiter}'\n" + menu + delimiter + '\nfi\n')


def camera_blocks(text):
    return [block for block in menu_blocks(text) if re.search(r"--id\s+(['\"])" + ENTRY + r'\1(?:\s|$)', block.splitlines()[0])]


def validate_config(before, after, menu, default=False):
    old = [block for block in menu_blocks(before) if block not in camera_blocks(before)]
    new = [block for block in menu_blocks(after) if block not in camera_blocks(after)]
    if old != new: raise ValueError('An existing Ubuntu menu entry would change.')
    blocks = camera_blocks(after)
    if len(blocks) != 1 or blocks[0] != menu: raise ValueError('The new camera entry was not found with the expected contents.')
    if not any(re.match(r"^menuentry\s+(['\"])Ubuntu\1\s", block) for block in new):
        raise ValueError('The Ubuntu fallback entry is missing.')
    defaults = lambda text: re.findall(r'^\s*set default=(.+)$', text, re.M)
    if not default and defaults(before) != defaults(after): raise ValueError('The default boot selection would change unexpectedly.')
    if default and (defaults(after).count('"' + ENTRY + '"') != 1 or any(value not in {'"' + ENTRY + '"', '"${next_entry}"'} for value in defaults(after))):
        raise ValueError('The camera entry could not be confirmed as the unique default.')


def generate_dtb(blob, work, run):
    vendor = set((ROOT / 'boot/vendor-camera-nodes.txt').read_text().splitlines())
    base, probe, final = work / 'original.dtb', work / 'sensor.dtb', work / 'camera.dtb'
    base.write_bytes(blob)
    base.chmod(0o600)
    for name in ['probe', 'camss']:
        run(['dtc', '-@', '-I', 'dts', '-O', 'dtb', '-o', str(work / (name + '.dtbo')),
             str(ROOT / f'boot/ventunoq-imx219-camera0-{name}.dtso')])
    run(['fdtoverlay', '-i', str(base), '-o', str(probe), str(work / 'probe.dtbo')])
    validate_probe(blob, probe.read_bytes(), vendor)
    for prop in fdt_nodes(probe.read_bytes()).get('/chosen', {}):
        if is_temporary_chosen_property(prop): run(['fdtput', '-d', str(probe), '/chosen', prop])
    first = validate_probe(blob, probe.read_bytes(), vendor, sanitized=True)
    run(['fdtoverlay', '-i', str(probe), '-o', str(final), str(work / 'camss.dtbo')])
    second = validate_camss_delta(probe.read_bytes(), final.read_bytes(), vendor, sanitized=True)
    return final.read_bytes(), {'sensor': first, 'camss': second}
