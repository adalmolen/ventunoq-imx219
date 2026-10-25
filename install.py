#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Staged installation: check, prepare, install, test-boot, verify, make-default."""
import argparse
import base64
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE / 'scripts'))
import boot_setup as boot
import package as release

KERNEL = boot.KERNEL
DEST = Path('/opt/ventuno-imx219-v2')
STATE = Path('/var/lib/ventuno-imx219-v2')
META = STATE / 'public-installation.json'
CFG = Path('/boot/grub/grub.cfg')
ENV = Path('/boot/grub/grubenv')
CUSTOM = Path('/etc/grub.d/43_ventuno_imx219_public')
DEFAULT = Path('/etc/default/grub.d/99-ventuno-imx219-public.cfg')
UNIT = Path('/etc/systemd/system/ventuno-imx219-camera.service')
SERVICE = 'ventuno-imx219-camera.service'
SOCKET = '/dev/ventuno-imx219-control.sock'
FRAGMENT = '# ventunoq-imx219\nGRUB_DEFAULT="ventuno-imx219-stability"\nGRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=5\n'


def run(args, timeout=45, cwd=None):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, cwd=cwd)
    if result.returncode: raise RuntimeError(f'{args[0]} failed: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout.strip()


def sha(data): return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.imx219-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def remember(path):
    if path.is_symlink(): raise ValueError(f'Unexpected symlink: {path}')
    if not path.exists(): return None
    stat = path.stat()
    return {'data': base64.b64encode(path.read_bytes()).decode(), 'mode': stat.st_mode & 0o777,
            'uid': stat.st_uid, 'gid': stat.st_gid}


def restore(path, record):
    if record is None: path.unlink(missing_ok=True)
    else:
        atomic(path, base64.b64decode(record['data']), record['mode'])
        os.chown(path, record['uid'], record['gid'])


def check_environment(build=False):
    info = os.uname()
    if info.sysname != 'Linux' or info.machine != 'aarch64' or info.release != KERNEL:
        raise ValueError(f'Only Ventuno Q aarch64 with kernel {KERNEL} is supported.')
    compatible = Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
    if not {b'arduino,monza', b'qcom,qcs8300'} <= set(compatible): raise ValueError('Unknown Ventuno Q board variant.')
    version = run(['dpkg-query', '-W', '-f=${Version}', f'linux-image-{KERNEL}'])
    if not version.startswith('6.8.0-1080.85'): raise ValueError('The kernel package does not match linux-qcom 6.8.0-1080.85.')
    commands = ['modinfo', 'modprobe', 'insmod', 'udevadm', 'media-ctl', 'v4l2-ctl', 'fuser',
                'dtc', 'fdtoverlay', 'fdtput', 'grub-mkconfig', 'grub-script-check', 'grub-reboot',
                'grub-editenv', 'systemctl', 'docker', 'arduino-app-cli']
    if build: commands += ['gcc-13', 'make', 'cc']
    missing = [name for name in commands if not shutil.which(name)]
    if missing: raise ValueError('Missing tools: ' + ', '.join(missing) + '. See README.md for dependencies.')
    stock = run(['modinfo', '-F', 'srcversion', 'qcom_camss'])
    if stock != '6836E35C0AA1F2FCD21FCBD': raise ValueError('The installed original CAMSS differs from the expected version; do not overwrite it.')
    if build:
        headers = Path(f'/lib/modules/{KERNEL}/build')
        if not (headers / 'Module.symvers').is_file() or (headers / 'include/config/kernel.release').read_text().strip() != KERNEL:
            raise ValueError('The matching kernel headers and Module.symvers are missing.')
    return {'kernel': KERNEL, 'kernel_package': version, 'architecture': 'aarch64', 'board': 'arduino,monza / qcom,qcs8300'}


def check_next_entry():
    entries = [line.partition('=')[2] for line in run(['grub-editenv', str(ENV), 'list']).splitlines() if line.partition('=')[0] == 'next_entry']
    if len(entries) > 1 or any(entries):
        raise ValueError('A one-time GRUB boot selection is already pending. Complete it first; see README.md.')


def built_artifacts():
    release.verify()
    report = json.loads((PACKAGE / '.build/build.json').read_text())
    module = PACKAGE / '.build/driver/qcom-camss.ko'
    native = PACKAGE / 'runtime/picture_native.so'
    if (report.get('kernel') != KERNEL or report.get('srcversion') != release.SRCVERSION
            or report.get('source_manifest_sha256') != release.sha(PACKAGE / 'SHA256SUMS')
            or release.sha(module) != report.get('module_sha256') or release.sha(native) != report.get('native_sha256')):
        raise ValueError('Build verification failed; run bash scripts/build.sh again.')
    for field, expected in [('name', 'qcom_camss'), ('srcversion', release.SRCVERSION),
                            ('vermagic', KERNEL + ' SMP preempt mod_unload modversions aarch64')]:
        if run(['modinfo', '-F', field, str(module)]) != expected: raise ValueError('The driver ABI or source version does not match.')
    blob = native.read_bytes()
    if blob[:6] != b'\x7fELF\x02\x01' or int.from_bytes(blob[18:20], 'little') != 183:
        raise ValueError('Invalid native aarch64 library.')
    return report, module, native


def prepare():
    check_environment()
    built_artifacts()
    blob = Path('/sys/firmware/fdt').read_bytes()
    boot.secure_boot(blob)
    check_next_entry()
    grub = CFG.read_text()
    if boot.camera_blocks(grub): raise ValueError('A camera boot entry already exists. This package requires a fresh installation; see README.md.')
    for path in [Path(f'/boot/vmlinuz-{KERNEL}'), Path(f'/boot/initrd.img-{KERNEL}')]:
        if not path.is_file(): raise ValueError(f'Missing boot file: {path}')
    work = Path(tempfile.mkdtemp(prefix='boot-', dir=PACKAGE / '.build'))
    dtb, validation = boot.generate_dtb(blob, work, run)
    menu = boot.make_menu(grub, boot.loader_module())
    (work / 'menu.cfg').write_text(menu)
    (work / 'generator.sh').write_text(boot.generator(menu))
    run(['grub-script-check', str(work / 'menu.cfg')])
    run(['sh', '-n', str(work / 'generator.sh')])
    data = {'directory': str(work), 'source_fdt_sha256': sha(blob), 'source_grub_sha256': sha(grub.encode()),
            'dtb_sha256': sha(dtb), 'menu_sha256': sha(menu.encode()), 'validation': validation,
            'source_manifest_sha256': release.sha(PACKAGE / 'SHA256SUMS')}
    atomic(PACKAGE / '.build/prepared.json', json.dumps(data, indent=2).encode(), 0o600)
    print('DTB and GRUB preview verified. The boot configuration and running drivers are unchanged.')
    print('Next step: sudo python3 install.py install')


def status():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(SOCKET)
        client.sendall(b'{"action":"status"}\n')
        response = bytearray()
        while not response.endswith(b'\n'):
            data = client.recv(4096)
            if not data or len(response) + len(data) > 8192: raise ValueError('Invalid response from the camera service.')
            response.extend(data)
    return json.loads(response)


def idle():
    if Path(SOCKET).exists():
        reply = status()
        if reply.get('state') != 'idle' or reply.get('active_apps') != 0:
            raise ValueError('Stop the camera app and wait 15 seconds. The camera is not idle.')


def metadata():
    if not META.is_file(): raise ValueError('No installation of this public package was found.')
    data = json.loads(META.read_text())
    if data.get('rolled_back'): raise ValueError('This installation has already been rolled back.')
    return data


def write_metadata(data): atomic(META, json.dumps(data, indent=2).encode(), 0o600)


def new_config(before, menu, default=False):
    fd, name = tempfile.mkstemp(prefix='ventuno-grub-', dir='/boot')
    os.close(fd)
    path = Path(name)
    try:
        run(['grub-mkconfig', '-o', str(path)], timeout=60)
        run(['grub-script-check', str(path)])
        candidate = path.read_text()
        boot.validate_config(before, candidate, menu, default=default)
        return candidate.encode()
    finally: path.unlink(missing_ok=True)


def install():
    check_environment()
    build, module, native = built_artifacts()
    if META.exists() or DEST.exists() or UNIT.exists() or CUSTOM.exists() or boot.DTB.exists() or DEFAULT.exists() or Path(SOCKET).exists() or STATE.exists():
        raise ValueError('A camera installation already exists. Nothing was overwritten; see Existing installations in README.md.')
    account_name = os.environ.get('SUDO_USER')
    if not account_name or account_name == 'root': raise ValueError('Run with sudo from your regular App Lab user account.')
    account = pwd.getpwnam(account_name)
    if grp.getgrnam('video').gr_gid not in os.getgrouplist(account_name, account.pw_gid):
        raise ValueError('The App Lab user is not in the video group. See README.md.')
    prepared = json.loads((PACKAGE / '.build/prepared.json').read_text())
    blob = Path('/sys/firmware/fdt').read_bytes()
    boot.secure_boot(blob)
    grub = CFG.read_text()
    if (prepared['source_fdt_sha256'] != sha(blob) or prepared['source_grub_sha256'] != sha(grub.encode())
            or prepared['source_manifest_sha256'] != release.sha(PACKAGE / 'SHA256SUMS')):
        raise ValueError('The boot configuration, GRUB, or package has changed. Run prepare again.')
    check_next_entry()
    work = Path(prepared['directory'])
    # Rebuild from the current live DTB and validate every allowed change again.
    verified = Path(tempfile.mkdtemp(prefix='recheck-', dir=PACKAGE / '.build'))
    dtb, validation = boot.generate_dtb(blob, verified, run)
    menu = boot.make_menu(grub, boot.loader_module())
    if sha(dtb) != prepared['dtb_sha256'] or sha(menu.encode()) != prepared['menu_sha256']:
        raise ValueError('The prepared boot files do not match the repeated verification.')
    managed = [CUSTOM, DEFAULT, UNIT, boot.DTB]
    record = {'version': (PACKAGE / 'VERSION').read_text().strip(), 'uid': account.pw_uid,
              'kernel': KERNEL, 'source_manifest_sha256': release.sha(PACKAGE / 'SHA256SUMS'),
              'before': {str(path): remember(path) for path in managed}, 'grub_before': remember(CFG),
              'grubenv_before': remember(ENV), 'menu': menu, 'rolled_back': False, 'stage': 'installed',
              'module_sha256': build['module_sha256'], 'native_sha256': build['native_sha256'], 'owned': {}}
    STATE.mkdir(mode=0o750)
    (STATE / 'diagnostics').mkdir(mode=0o750)
    DEST.mkdir(mode=0o755)
    write_metadata(record)
    try:
        for path in (PACKAGE / 'runtime').iterdir():
            if path.suffix in {'.py', '.json'}: atomic(DEST / path.name, path.read_bytes())
        atomic(DEST / 'qcom-camss.ko', module.read_bytes())
        atomic(DEST / 'picture_native.so', native.read_bytes())
        atomic(DEST / 'driver_expected.json', json.dumps({'schema': 1, 'srcversion': release.SRCVERSION,
               'sha256': build['module_sha256']}).encode())
        atomic(boot.DTB, dtb)
        atomic(CUSTOM, boot.generator(menu).encode(), 0o755)
        unit = (PACKAGE / 'runtime/ventuno-imx219-camera.service').read_text().replace('@UID@', str(account.pw_uid))
        atomic(UNIT, unit.encode())
        candidate = new_config(grub, menu)
        if CFG.read_text() != grub or remember(ENV) != record['grubenv_before']:
            raise ValueError('The boot configuration changed during installation.')
        atomic(CFG, candidate, record['grub_before']['mode'])
        record['owned'] = {str(path): release.sha(path) for path in managed if path.exists()}
        record['grub_installed_sha256'] = sha(candidate)
        write_metadata(record)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', SERVICE])
        for _ in range(30):
            if Path(SOCKET).exists(): break
            time.sleep(.1)
        reply = status()
        if reply.get('state') != 'idle': raise ValueError('The new camera service did not start in the idle state.')
    except BaseException:
        subprocess.run(['systemctl', 'disable', '--now', SERVICE], capture_output=True, timeout=25)
        for name, saved in record['before'].items(): restore(Path(name), saved)
        restore(CFG, record['grub_before'])
        subprocess.run(['systemctl', 'daemon-reload'], capture_output=True)
        record['rolled_back'] = True
        write_metadata(record)
        raise
    print('Installed. Ubuntu remains the default; no driver was replaced and no reboot was performed.')
    print('Next step: sudo python3 install.py test-boot, then sudo reboot')


def test_boot():
    data = metadata()
    idle()
    check_next_entry()
    if boot.camera_blocks(CFG.read_text()) != [data['menu']]: raise ValueError('The camera menu entry has changed.')
    run(['grub-reboot', boot.ENTRY])
    data['test_boot_requested'] = True
    write_metadata(data)
    print('One-time camera boot scheduled. Reboot manually with sudo reboot. Ubuntu remains available as a fallback.')


def verify():
    metadata()
    idle()
    boot.check_arguments(Path('/proc/cmdline').read_text().split())
    # Execute only protected installed code, with its own driver hash manifest.
    run([sys.executable, '-c', 'from pathlib import Path; from module_loader import load; load(Path("qcom-camss.ko"))'], timeout=60, cwd=DEST)
    diagnostics = STATE / 'diagnostics'
    before = set(diagnostics.glob('ventunoq-imx219-fhd-test.*/result.json'))
    print(run([sys.executable, str(DEST / 'capture_fhd_test.py'), '--output-root', str(diagnostics)], timeout=40))
    created = set(diagnostics.glob('ventunoq-imx219-fhd-test.*/result.json')) - before
    if len(created) != 1: raise ValueError('The new capture did not produce a unique result file.')
    proof = created.pop()
    validate_proof(json.loads(proof.read_text()))
    atomic(STATE / 'proof.json', proof.read_bytes())
    data = metadata()
    data['stage'] = 'verified'
    write_metadata(data)
    print('Three complete Full HD frames received. CAMSS stays loaded. You can now import and start the App Lab app.')


def validate_proof(data):
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if (data.get('passed') is not True or data.get('boot_id') != boot_id or data.get('kernel') != KERNEL
            or data.get('loaded_srcversion') != release.SRCVERSION or data.get('frame_count') != 3
            or data.get('capture_process_stopped') is not True or data.get('new_kernel_faults') != []
            or data.get('format', {}).get('width') != 1920 or data.get('format', {}).get('height') != 1080):
        raise ValueError('A successful new Full HD test from the current boot is required.')


def make_default():
    data = metadata()
    validate_proof(json.loads((STATE / 'proof.json').read_text()))
    boot.check_arguments(Path('/proc/cmdline').read_text().split())
    check_next_entry()
    if data['stage'] == 'default':
        print('The camera boot is already the default.')
        return
    if DEFAULT.exists(): raise ValueError('The default boot setting already exists and will be preserved.')
    previous = CFG.read_text()
    try:
        atomic(DEFAULT, FRAGMENT.encode())
        candidate = new_config(previous, data['menu'], default=True)
        if CFG.read_text() != previous: raise ValueError('GRUB changed during this operation.')
        atomic(CFG, candidate, data['grub_before']['mode'])
    except BaseException:
        DEFAULT.unlink(missing_ok=True)
        raise
    data['stage'] = 'default'
    data['owned'][str(DEFAULT)] = release.sha(DEFAULT)
    data['grub_installed_sha256'] = sha(candidate)
    write_metadata(data)
    print('The tested camera boot is now the default. Ubuntu remains available in the 5-second GRUB menu.')


def rollback():
    data = metadata()
    idle()
    check_next_entry()
    for name, expected in data['owned'].items():
        path = Path(name)
        if not path.exists() or release.sha(path) != expected:
            raise ValueError(f'An installed file has been modified: {name}. Investigate before proceeding.')
    previous_cfg = CFG.read_bytes()
    run(['systemctl', 'disable', '--now', SERVICE], timeout=25)
    try:
        for name, saved in data['before'].items(): restore(Path(name), saved)
        if sha(previous_cfg) == data['grub_installed_sha256']:
            restore(CFG, data['grub_before'])
        else:
            # Keep any newer Ubuntu kernels added since installation.
            temporary_fd, temporary_name = tempfile.mkstemp(prefix='ventuno-uninstall-', dir='/boot')
            os.close(temporary_fd)
            temporary = Path(temporary_name)
            try:
                run(['grub-mkconfig', '-o', str(temporary)], timeout=60)
                run(['grub-script-check', str(temporary)])
                text = temporary.read_text()
                if boot.camera_blocks(text) or not any("menuentry 'Ubuntu'" in line for line in text.splitlines()):
                    raise ValueError('No valid Ubuntu fallback configuration was found after removal.')
                atomic(CFG, temporary.read_bytes(), data['grub_before']['mode'])
            finally: temporary.unlink(missing_ok=True)
        run(['systemctl', 'daemon-reload'])
    except BaseException:
        print('Rollback is incomplete. Do not reboot; the backup is at ' + str(META), file=sys.stderr)
        raise
    data['rolled_back'] = True
    write_metadata(data)
    print('Camera service disabled and previous boot selection restored. No reboot performed; CAMSS stays loaded until shutdown.')
    print('The app and local diagnostics are retained. You can remove the app separately in App Lab.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'prepare', 'install', 'test-boot', 'verify', 'make-default', 'status', 'rollback'])
    parser.add_argument('--build', action='store_true', help='Also check the kernel headers and compiler.')
    args = parser.parse_args()
    if args.action == 'check':
        print(json.dumps(check_environment(args.build), indent=2))
        return
    if os.geteuid() != 0: raise ValueError('Use sudo python3 install.py ' + args.action)
    os.environ['PATH'] = '/usr/sbin:/usr/bin:/sbin:/bin'
    os.environ['LC_ALL'] = 'C'
    if args.action == 'status': print(json.dumps(status(), indent=2))
    else: globals()[args.action.replace('-', '_')]()


if __name__ == '__main__':
    try: main()
    except (RuntimeError, ValueError, OSError, KeyError, ImportError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'ERROR: {exc}') from None
