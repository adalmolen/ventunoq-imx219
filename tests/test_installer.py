# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_atomic_failure_preserves_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'config'
            p.write_bytes(b'original')
            with patch.object(installer.os, 'replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): installer.atomic(p, b'new')
            self.assertEqual(p.read_bytes(), b'original')
            self.assertEqual(list(p.parent.glob('.imx219-*')), [])

    def test_snapshot_restore_preserves_bytes_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'config'
            p.write_bytes(b'original\n');p.chmod(0o640)
            record = installer.remember(p)
            installer.atomic(p, b'changed')
            installer.restore(p, record)
            self.assertEqual(p.read_bytes(), b'original\n')
            self.assertEqual(p.stat().st_mode & 0o777, 0o640)
            installer.restore(p, None)
            self.assertFalse(p.exists())

    def test_refuses_symlink_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'link';p.symlink_to('/does-not-exist')
            with self.assertRaises(ValueError): installer.remember(p)

    def test_empty_next_entry_is_accepted_but_pending_choice_is_not(self):
        for result in ['', 'next_entry=\n', 'saved_entry=0\nnext_entry=\n']:
            with patch.object(installer, 'run', return_value=result): installer.check_next_entry()
        for result in ['next_entry=other', 'next_entry=\nnext_entry=']:
            with patch.object(installer, 'run', return_value=result), self.assertRaises(ValueError): installer.check_next_entry()

    def test_proof_is_same_boot_complete_frames_and_no_faults(self):
        data = {'passed': True, 'boot_id': 'fixture', 'kernel': installer.KERNEL,
                'loaded_srcversion': installer.release.SRCVERSION, 'frame_count': 3,
                'capture_process_stopped': True, 'new_kernel_faults': [],
                'format': {'width': 1920, 'height': 1080}}
        original = Path.read_text
        def read(path, *args, **kwargs):
            if str(path) == '/proc/sys/kernel/random/boot_id': return 'fixture\n'
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            installer.validate_proof(data)
            for key, value in [('boot_id', 'previous'), ('frame_count', 2), ('passed', False),
                               ('capture_process_stopped', False), ('new_kernel_faults', ['Oops:'])]:
                with self.subTest(key=key), self.assertRaises(ValueError): installer.validate_proof({**data, key: value})

    def test_wrong_platform_refused_before_commands(self):
        with patch.object(installer.os, 'uname', return_value=types.SimpleNamespace(sysname='Darwin', machine='arm64', release='test')):
            with patch.object(installer, 'run') as run, self.assertRaises(ValueError): installer.check_environment()
            run.assert_not_called()

    def test_existing_installation_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'existing';p.mkdir();(p/'keep').write_text('untouched')
            with patch.object(installer, 'check_environment'), patch.object(installer, 'built_artifacts', return_value=({}, None, None)), patch.object(installer, 'DEST', p), patch.object(installer, 'META', p/'not-installed.json'):
                with self.assertRaises(ValueError): installer.install()
            self.assertEqual((p/'keep').read_text(), 'untouched')


if __name__ == '__main__': unittest.main()

class InstallTransactionTests(unittest.TestCase):
    def exercise(self, fail=False):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            package = root / 'package'
            (package/'runtime').mkdir(parents=True)
            (package/'.build').mkdir()
            (package/'runtime/camera_manager.py').write_text('# protected runtime\n')
            (package/'runtime/ventuno-imx219-camera.service').write_text('ExecStart=manager --uid=@UID@\n')
            (package/'SHA256SUMS').write_text('fixture manifest\n')
            (package/'VERSION').write_text('test\n')
            module=package/'.build/module.ko';module.write_bytes(b'module')
            native=package/'.build/native.so';native.write_bytes(b'native')
            cfg=root/'grub.cfg';cfg.write_text('original Ubuntu\n');cfg.chmod(0o640)
            env=root/'grubenv';env.write_bytes(b'original environment')
            dtb=root/'boot/camera.dtb'
            menu='menuentry camera fixture\n'
            data={'directory':str(package/'.build'), 'source_fdt_sha256':installer.sha(b'firmware'),
                  'source_grub_sha256':installer.sha(cfg.read_bytes()),'dtb_sha256':installer.sha(b'dtb'),
                  'menu_sha256':installer.sha(menu.encode()),
                  'source_manifest_sha256':installer.sha((package/'SHA256SUMS').read_bytes())}
            (package/'.build/prepared.json').write_text(json.dumps(data))
            state=root/'state';dest=root/'opt'
            substitutions={'PACKAGE':package,'STATE':state,'DEST':dest,'META':state/'public-installation.json',
                           'CFG':cfg,'ENV':env,'CUSTOM':root/'custom','DEFAULT':root/'default','UNIT':root/'service','SOCKET':str(root/'control.sock')}
            for key,value in substitutions.items(): stack.enter_context(patch.object(installer,key,value))
            stack.enter_context(patch.object(installer.boot,'DTB',dtb))
            stack.enter_context(patch.object(installer,'check_environment'))
            stack.enter_context(patch.object(installer,'check_next_entry'))
            report={'module_sha256':installer.sha(b'module'),'native_sha256':installer.sha(b'native')}
            stack.enter_context(patch.object(installer,'built_artifacts',return_value=(report,module,native)))
            stack.enter_context(patch.object(installer.boot,'secure_boot'))
            stack.enter_context(patch.object(installer.boot,'generate_dtb',return_value=(b'dtb',{})))
            stack.enter_context(patch.object(installer.boot,'make_menu',return_value=menu))
            stack.enter_context(patch.object(installer.boot,'loader_module',return_value='fdt'))
            stack.enter_context(patch.dict(os.environ,{'SUDO_USER':'fixture'}))
            stack.enter_context(patch.object(installer.pwd,'getpwnam',return_value=types.SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())))
            stack.enter_context(patch.object(installer.grp,'getgrnam',return_value=types.SimpleNamespace(gr_gid=os.getgid())))
            stack.enter_context(patch.object(installer.os,'getgrouplist',return_value=[os.getgid()]))
            original=Path.read_bytes
            def read(path):
                return b'firmware' if str(path)=='/sys/firmware/fdt' else original(path)
            stack.enter_context(patch.object(Path,'read_bytes',read))
            stack.enter_context(patch.object(installer,'run',return_value=''))
            stack.enter_context(patch.object(installer,'status',return_value={'state':'idle'}))
            process=stack.enter_context(patch.object(installer.subprocess,'run'))
            if fail:
                stack.enter_context(patch.object(installer,'new_config',side_effect=ValueError('GRUB fixture failed')))
                with self.assertRaises(ValueError): installer.install()
                self.assertEqual(cfg.read_bytes(),b'original Ubuntu\n')
                self.assertEqual(cfg.stat().st_mode & 0o777,0o640)
                self.assertEqual(env.read_bytes(),b'original environment')
                for p in [dtb,substitutions['CUSTOM'],substitutions['UNIT'],substitutions['DEFAULT']]:self.assertFalse(p.exists())
                self.assertTrue(json.loads((state/'public-installation.json').read_text())['rolled_back'])
                self.assertTrue(process.called)
            else:
                stack.enter_context(patch.object(installer,'new_config',return_value=b'original Ubuntu\nnew camera\n'))
                installer.install()
                self.assertEqual(cfg.read_bytes(),b'original Ubuntu\nnew camera\n')
                self.assertEqual(env.read_bytes(),b'original environment')
                self.assertFalse(substitutions['DEFAULT'].exists())
                self.assertEqual((dest/'qcom-camss.ko').read_bytes(),b'module')
                self.assertEqual(json.loads((dest/'driver_expected.json').read_text())['sha256'],report['module_sha256'])
                self.assertEqual((dest/'camera_manager.py').stat().st_mode & 0o777,0o644)
                meta=json.loads((state/'public-installation.json').read_text())
                self.assertFalse(meta['rolled_back']);self.assertEqual(meta['stage'],'installed')
                self.assertIsNone(meta['before'][str(dtb)])
                self.assertFalse(process.called)

    def test_success_installs_protected_runtime_without_changing_default_or_grubenv(self):
        self.exercise()

    def test_grub_failure_restores_original_boot_files(self):
        self.exercise(fail=True)
