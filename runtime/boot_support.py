"""Checks for this board's existing, proven boot entry; no DTB or kernel edits."""
import re
import shlex

from camera_control import KERNEL

ENTRY = 'ventuno-imx219-stability'
VERMAGIC = KERNEL + ' SMP preempt mod_unload modversions aarch64'
FRAGMENT = '# Ventuno IMX219 app v2\nGRUB_DEFAULT="ventuno-imx219-stability"\nGRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=5\n'


def modules(args, option):
    values = [x.split('=', 1)[1] for x in args if x.startswith(option + '=')]
    if len(values) != 1:
        raise ValueError(f'Precies één {option} verwacht.')
    return {x.replace('-', '_') for x in values[0].split(',')}


def check_arguments(args):
    if args.count('ventuno_imx219_stability=1') != 1:
        raise ValueError('De bestaande IMX219-stabiliteitsboot is vereist.')
    blocked = modules(args, 'module_blacklist')
    if 'camera_qcs8300' not in blocked or 'qcom_camss' in blocked:
        raise ValueError('Onverwachte kernel-blacklist voor de cameramodules.')
    if 'qcom_camss' not in modules(args, 'modprobe.blacklist'):
        raise ValueError('Automatisch laden van de originele CAMSS is niet onderdrukt.')


def menu_blocks(text):
    # GRUB's generated menu bodies end at the matching indentation level.
    # Keep every menu/submenu block byte-for-byte, including advanced Ubuntu entries.
    lines = text.splitlines(keepends=True)
    result = []
    for i, line in enumerate(lines):
        match = re.match(r'^(\s*)(?:menuentry|submenu)\s', line)
        if not match:
            continue
        indent = match[1]
        end = next((j for j in range(i + 1, len(lines)) if lines[j].rstrip('\r\n') == indent + '}'), None)
        if end is None:
            raise ValueError('Onvolledig GRUB-menu.')
        result.append(''.join(lines[i:end + 1]))
    return result


def camera_entry(text):
    matches = [b for b in menu_blocks(text) if re.search(
        r"--id\s+(['\"])" + ENTRY + r"\1(?:\s|$)", b.splitlines()[0])]
    if len(matches) != 1:
        raise ValueError('De bestaande ventuno-imx219-stability GRUB-optie ontbreekt of is dubbel.')
    block = matches[0]
    commands = [shlex.split(line) for line in block.splitlines()[1:-1] if line.strip()]
    linux = [x for x in commands if x[0] == 'linux']
    if len(linux) != 1 or linux[0][1] != f'/boot/vmlinuz-{KERNEL}':
        raise ValueError('De camera-optie kiest niet de geteste kernel.')
    if [x for x in commands if x[0] == 'initrd'] != [['initrd', f'/boot/initrd.img-{KERNEL}']]:
        raise ValueError('Onverwachte camera-initrd.')
    if [x for x in commands if x[0] == 'devicetree'] != [
            ['devicetree', f'/boot/ventuno-imx219-camss/camss-{KERNEL}.dtb']]:
        raise ValueError('Onverwachte camera-DTB.')
    check_arguments(linux[0][2:])
    return block


def validate_grub(before, after):
    camera_entry(before)
    camera_entry(after)
    if not any(re.match(r"^menuentry\s+(['\"])Ubuntu\1\s", b) for b in menu_blocks(after)):
        raise ValueError('De gewone Ubuntu-terugvaloptie ontbreekt.')
    if menu_blocks(before) != menu_blocks(after):
        raise ValueError('Een bestaand GRUB-menu zou veranderen; installatie gestopt.')
    # One assignment in the normal path; the other permitted assignment is GRUB's next_entry override.
    defaults = re.findall(r'^\s*set default=(.+)$', after, re.M)
    if defaults.count('"' + ENTRY + '"') != 1 or any(
            x not in {'"' + ENTRY + '"', '"${next_entry}"'} for x in defaults):
        raise ValueError('De bedoelde standaardboot kon niet eenduidig worden bevestigd.')
