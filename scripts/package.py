#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify sources and create reproducible, source-only release artifacts."""
import argparse
import hashlib
import gzip
import json
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
KERNEL = '6.8.0-1080-qcom'
SRCVERSION = 'F5A7796BFE69666C456ECFB'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def files():
    roots = ['runtime', 'app', 'driver', 'boot', 'scripts', 'tests', 'docs', '.github', 'LICENSES']
    result = [ROOT / name for name in ['README.md', 'LICENSE', 'NOTICE.md', 'VERSION', 'install.py', 'setup.sh', '.gitignore'] if (ROOT / name).is_file()]
    for name in roots:
        for path in (ROOT / name).rglob('*'):
            if (path.is_file() and '__pycache__' not in path.parts and not path.name.startswith('._')
                    and path.suffix not in {'.so', '.pyc', '.o', '.ko', '.cmd', '.raw', '.png', '.jpg', '.jpeg'}
                    and path.name != '.DS_Store'):
                result.append(path)
    return sorted(result)


def verify():
    listed = {}
    for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or name in listed or not re.fullmatch('[a-f0-9]{64}', expected):
            raise ValueError('Invalid source manifest.')
        listed[name] = expected
    actual = {str(path.relative_to(ROOT)): sha(path) for path in files()}
    if listed != actual:
        raise ValueError('Source verification failed. Use an unmodified release or generate a new manifest after editing.')
    for path in files():
        if path.is_symlink(): raise ValueError('Symlinks are not allowed in releases.')
        text = path.read_text()
        patterns = [r'github_pat_[A-Za-z0-9_]{20,}', r'gh[pousr]_[A-Za-z0-9]{20,}',
                    '/U' + r'sers/[^/\s]+/', r'\b192\.168\.\d+\.\d+\b',
                    r'-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----']
        if any(re.search(pattern, text) for pattern in patterns):
            raise ValueError(f'Possible private data in {path.relative_to(ROOT)}.')
    print(f'Source verification passed: {len(actual)} files.')


def app_zip():
    out = ROOT / 'dist/ventuno-imx219-app.zip'
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / 'app').rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and not path.name.startswith('._'):
                info = zipfile.ZipInfo(str(path.relative_to(ROOT / 'app')), date_time=(2026, 10, 25, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
    print(out)
    return out


def record_build():
    verify()
    module = ROOT / '.build/driver/qcom-camss.ko'
    native = ROOT / 'runtime/picture_native.so'
    def info(field):
        return subprocess.check_output(['modinfo', '-F', field, str(module)], text=True).strip()
    magic = KERNEL + ' SMP preempt mod_unload modversions aarch64'
    if info('srcversion') != SRCVERSION or info('vermagic') != magic or info('name') != 'qcom_camss':
        raise ValueError('The built driver has an unexpected source version or ABI.')
    blob = native.read_bytes()
    if blob[:6] != b'\x7fELF\x02\x01' or int.from_bytes(blob[18:20], 'little') != 183:
        raise ValueError('The image library is not an aarch64 ELF file.')
    data = {'schema': 1, 'kernel': KERNEL, 'srcversion': SRCVERSION, 'vermagic': magic,
            'module_sha256': sha(module), 'native_sha256': sha(native),
            'source_manifest_sha256': sha(ROOT / 'SHA256SUMS')}
    (ROOT / '.build/build.json').write_text(json.dumps(data, indent=2) + '\n')
    print('Driver and native image library verified; build.json written.')


def release():
    verify()
    version = (ROOT / 'VERSION').read_text().strip()
    app = app_zip()
    out = ROOT / f'dist/ventunoq-imx219-{version}.tar.gz'
    with out.open('wb') as output, gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for path in files() + [ROOT / 'SHA256SUMS']:
            info = archive.gettarinfo(str(path), arcname=f'ventunoq-imx219-{version}/' + str(path.relative_to(ROOT)))
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = 1792886400
            info.mode = 0o755 if path.suffix == '.sh' else 0o644
            info.pax_headers = {}
            with path.open('rb') as stream: archive.addfile(info, stream)
    (ROOT / 'dist/SHA256SUMS').write_text('\n'.join(f'{sha(path)}  {path.name}' for path in [out, app]) + '\n')
    print(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['manifest', 'verify', 'app', 'record-build', 'release'])
    action = parser.parse_args().action
    if action == 'manifest':
        (ROOT / 'SHA256SUMS').write_text(''.join(f'{sha(path)}  {path.relative_to(ROOT)}\n' for path in files()))
    elif action == 'verify': verify()
    elif action == 'app': app_zip()
    elif action == 'record-build': record_build()
    else: release()
