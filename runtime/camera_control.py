"""Hardware operations for the existing Ventuno Q IMX219 stability test boot."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import time

SRCVERSION = 'F5A7796BFE69666C456ECFB'
KERNEL = '6.8.0-1080-qcom'
WIDTH, HEIGHT = 1920, 1080


def user_home():
    name = os.environ.get('SUDO_USER')
    return Path(pwd.getpwnam(name).pw_dir) if name else Path.home()


def run(args, timeout=12):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args[0]} mislukt: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def preflight():
    if os.uname().sysname != 'Linux' or os.uname().release != KERNEL:
        raise RuntimeError(f'Dit pakket vereist de geteste Ventuno-kernel {KERNEL}.')
    if os.geteuid() != 0:
        raise RuntimeError('Start dit hardwarecommando met sudo python3.')
    if 'ventuno_imx219_stability=1' not in Path('/proc/cmdline').read_text().split():
        raise RuntimeError('Start eerst de bestaande ventuno-imx219-stability-testboot.')
    loaded = Path('/sys/module/qcom_camss/srcversion')
    if not loaded.exists() or loaded.read_text().strip() != SRCVERSION:
        raise RuntimeError('De geteste CAMSS-stability-module is niet geladen. Er wordt niets verwisseld.')
    for command in ['media-ctl', 'v4l2-ctl', 'fuser']:
        if not shutil.which(command):
            raise RuntimeError(f'{command} ontbreekt; hostpakketten: v4l-utils en psmisc.')
    return {'boot_id': boot_id(), 'kernel': KERNEL, 'loaded_srcversion': SRCVERSION}


class CameraLock:
    def __enter__(self):
        self.file = open('/run/lock/ventuno-imx219-fhd.lock', 'a')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('Er loopt al een FHD-test of camerabrug.') from None
        return self

    def __exit__(self, *exc):
        self.file.close()


def parse_format(text):
    def number(pattern):
        match = re.search(pattern, text)
        if not match:
            raise ValueError('Onvolledige V4L2-formaatuitvoer')
        return int(match[1])
    wh = re.search(r'Width/Height\s*:\s*(\d+)/(\d+)', text)
    if not wh or tuple(map(int, wh.groups())) != (WIDTH, HEIGHT):
        raise ValueError('De driver heeft geen 1920x1080 ingesteld.')
    if not re.search(r"Pixel Format\s*:\s*'pRAA'", text):
        raise ValueError('De driver heeft geen pRAA / packed RGGB10 ingesteld.')
    if number(r'Number of planes\s*:\s*(\d+)') != 1:
        raise ValueError('Alleen een RAW10-vlak wordt ondersteund.')
    stride = number(r'Bytes per Line\s*:\s*(\d+)')
    size = number(r'Size Image\s*:\s*(\d+)')
    if stride < WIDTH * 5 // 4 or size != stride * HEIGHT:
        raise ValueError('Onverwachte stride of framegrootte.')
    return {'width': WIDTH, 'height': HEIGHT, 'pixel_format': 'pRAA',
            'bytes_per_line': stride, 'size_image': size}


def sensor_entity(driver=Path('/sys/bus/i2c/drivers/imx219')):
    """Find Camera0 by its device-tree path, independent of I2C bus numbering."""
    expected = '/soc@0/cci@ac13000/i2c-bus@0/sensor@10'
    matches = [entry.name for entry in driver.glob('*-0010')
               if entry.is_symlink() and re.fullmatch(r'[0-9]+-0010', entry.name)
               and (entry / 'of_node').resolve().as_posix().endswith(expected)]
    if len(matches) != 1:
        raise RuntimeError('Niet precies één gekoppelde IMX219 op Camera0 gevonden.')
    return 'imx219 ' + matches[0]


def configure(output):
    candidates = []
    for device in sorted(Path('/dev').glob('media*')):
        if not device.is_char_device():
            continue
        topology = run(['media-ctl', '-d', str(device), '-p'])
        if re.search(r'^driver\s+qcom-camss$', topology, re.M) and re.search(
                r'^bus info\s+platform:ac7a000\.isp$', topology, re.M):
            candidates.append(str(device))
    if len(candidates) != 1:
        raise RuntimeError('Niet precies een CAMSS voor ac7a000.isp gevonden.')
    media = candidates[0]
    video = run(['media-ctl', '-d', media, '-e', 'msm_vfe0_video0']).strip()
    sensor_name = sensor_entity()
    sensor = run(['media-ctl', '-d', media, '-e', sensor_name]).strip()
    if not Path(video).is_char_device() or not Path(sensor).is_char_device():
        raise RuntimeError('De bekende Camera0-route ontbreekt.')
    busy = subprocess.run(['fuser', video, sensor], capture_output=True, text=True)
    if busy.returncode != 1 or busy.stdout.strip():
        raise RuntimeError('Camera in gebruik of niet controleerbaar. Stop andere camera-apps eerst.\n' + busy.stdout + busy.stderr)
    run(['media-ctl', '-d', media, '-l',
         '"msm_csiphy0":1->"msm_csid0":0[1], "msm_csid0":1->"msm_vfe0_rdi0":0[1]'])
    pads = [f'"{sensor_name}":0', '"msm_csiphy0":0', '"msm_csiphy0":1',
            '"msm_csid0":0', '"msm_csid0":1', '"msm_vfe0_rdi0":0', '"msm_vfe0_rdi0":1']
    for pad in pads:
        run(['media-ctl', '-d', media, '-V', f'{pad}[fmt:SRGGB10_1X10/{WIDTH}x{HEIGHT} field:none]'])
    text = run(['v4l2-ctl', '-d', video,
                f'--set-fmt-video=width={WIDTH},height={HEIGHT},pixelformat=pRAA', '--get-fmt-video'])
    fmt = parse_format(text)
    run(['v4l2-ctl', '-d', sensor, '--set-ctrl=exposure=800'])
    controls = run(['v4l2-ctl', '-d', sensor, '--list-ctrls'])
    if not re.search(r'^\s*exposure\s+.*\bvalue=800\b', controls, re.M):
        raise RuntimeError('Belichting 800 kon niet worden bevestigd.')
    (output / 'format.txt').write_text(text)
    (output / 'controls.txt').write_text(controls)
    (output / 'topology.txt').write_text(run(['media-ctl', '-d', media, '-p']))
    return {**fmt, 'media': media, 'video': video, 'sensor': sensor, 'exposure_lines': 800}


def stream_command(video, destination, count=0, verbose=False):
    args = ['v4l2-ctl', '-d', video, '--stream-mmap=4', '--stream-poll',
            f'--stream-count={count}', f'--stream-to={destination}']
    if verbose:
        args.append('--verbose')
    return args


def stop_process(process):
    if process.poll() is not None:
        return True
    for sig, timeout in [(signal.SIGINT, 3), (signal.SIGTERM, 1)]:
        try:
            process.send_signal(sig)
        except ProcessLookupError:
            return True
        try:
            process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            pass
    return False


def kernel_since(uptime):
    lines = run(['dmesg']).splitlines()
    return '\n'.join(line for line in lines if (m := re.match(r'^\[\s*([\d.]+)\]', line))
                     and float(m[1]) >= uptime) + '\n'


def kernel_faults(text):
    pattern = r'Unable to handle kernel|Oops:|BUG:|blocked for more than|RCU.*stall|watchdog.*lockup|Synchronous External Abort|(?:camss|CSID|VFE|csiphy).*?(?:timed out|timeout|error|failed)'
    # Linux watchdog.c prints this when the optional hard-lockup detector's probe
    # returns -ENODEV. It is not a report that a CPU has locked up. Match only the
    # complete known message; additional crash text and other errors stay blocked.
    unavailable_detector = (r'(?:\[\s*\d+(?:\.\d+)?\]\s*)?'
                            r'watchdog: Delayed init of the lockup detector failed: -19\s*')
    return [line for line in text.splitlines() if re.search(pattern, line, re.I)
            and not re.fullmatch(unavailable_detector, line)
            and not ('module verification failed:' in line and 'signature' in line)]


def find_proof(explicit=None):
    paths = [Path(explicit)] if explicit else sorted(
        user_home().glob('ventunoq-imx219-fhd-test.*/result.json'),
        key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            data = json.loads(path.read_text())
            if (data.get('passed') is True and data.get('boot_id') == boot_id()
                    and data.get('loaded_srcversion') == SRCVERSION
                    and data.get('format', {}).get('width') == WIDTH
                    and data.get('format', {}).get('height') == HEIGHT):
                return path
        except (OSError, ValueError):
            continue
    raise RuntimeError('Eerst capture_fhd_test.py uitvoeren: een geslaagde FHD-test in deze boot ontbreekt.')
