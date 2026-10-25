#!/usr/bin/env python3
"""Small local lease service. The app requests a camera, never root shell commands."""
import argparse
import grp
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid

from camera_control import boot_id, find_proof, stop_process
from module_loader import load
from picture_settings import PictureStore

SOCKET = '/dev/ventuno-imx219-control.sock'
STATE = Path('/var/lib/ventuno-imx219-v2')
TTL = 12


def stop_bridge(process):
    if process.poll() is not None:
        return True
    for sig, timeout in [(signal.SIGINT, 10), (signal.SIGTERM, 2)]:
        try:
            process.send_signal(sig)
            process.wait(timeout=timeout)
            return True
        except ProcessLookupError:
            return True
        except subprocess.TimeoutExpired:
            pass
    return False


class Leases:
    def __init__(self, clock=time.monotonic):
        self.clock, self.items = clock, {}

    def request(self, action, identity):
        if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity:
            raise ValueError('Invalid app session.')
        self.active()
        if action == 'lease':
            if identity not in self.items and len(self.items) >= 8:
                raise ValueError('Too many concurrent apps.')
            self.items[identity] = self.clock() + TTL
        elif action == 'release':
            self.items.pop(identity, None)
        else:
            raise ValueError('Unknown action.')

    def active(self):
        now = self.clock()
        self.items = {key: until for key, until in self.items.items() if until > now}
        return bool(self.items)


class Manager:
    def __init__(self, allowed_uid, root=STATE):
        self.allowed_uid, self.root = allowed_uid, root
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.leases = Leases()
        self.picture = PictureStore(self.root / 'picture-settings.json')
        self.worker, self.cancel = None, threading.Event()
        self.state, self.message = 'idle', 'Camera is waiting for the app.'
        self.failed = Path('/run/ventuno-imx219/failed.json')
        if self.failed.exists():
            self.state, self.message = 'error', 'A camera fault occurred earlier in this boot. Check the diagnostics; automatic retries are disabled.'

    def update(self, state, message):
        with self.lock:
            self.state, self.message = state, message
        print(message, flush=True)

    def request(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'action', 'session', 'values'}:
            raise ValueError('Invalid camera request.')
        action = payload.get('action')
        if 'values' in payload and action != 'picture_set':
            raise ValueError('This action does not accept picture settings.')
        with self.lock:
            if action == 'picture_set':
                self.leases.active()
                identity = payload.get('session')
                if not isinstance(identity, str) or identity not in self.leases.items:
                    raise ValueError('Start the camera app first.')
                self.picture.save(payload.get('values'))
            elif action not in {'status', 'picture_get'}:
                self.leases.request(action, payload.get('session'))
            return {'state': self.state, 'message': self.message, 'lease_seconds': TTL,
                    'active_apps': len(self.leases.items), 'boot_id': boot_id(),
                    'picture': self.picture.status()}

    def run_command(self, args, log_path, timeout):
        with log_path.open('ab') as log:
            process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if self.cancel.wait(.1) or time.monotonic() > deadline:
                    if not stop_process(process):
                        raise RuntimeError('The camera process will not stop. Use a second terminal; do not replace modules.')
                    if self.cancel.is_set():
                        return False
                    raise RuntimeError('The camera test timed out.')
            if process.returncode:
                raise RuntimeError(f'Camera test failed; see {log_path}.')
        return True

    def camera_worker(self):
        bridge = None
        try:
            self.update('starting', 'Preparing the camera…')
            load(Path(__file__).with_name('qcom-camss.ko'))
            if self.cancel.is_set():
                return
            proof = self.root / 'proof.json'
            try:
                find_proof(str(proof))
            except RuntimeError:
                self.update('starting', 'First start in this boot: capturing three Full HD test frames…')
                script = Path(__file__).with_name('capture_fhd_test.py')
                log = self.root / 'diagnostics' / 'bootstrap.log'
                before = set(log.parent.glob('ventunoq-imx219-fhd-test.*/result.json'))
                if not self.run_command([sys.executable, str(script), '--output-root', str(log.parent)], log, 35):
                    return
                created = set(log.parent.glob('ventunoq-imx219-fhd-test.*/result.json')) - before
                if len(created) != 1:
                    raise RuntimeError('The new Full HD test did not produce a unique result file.')
                proof_source = created.pop()
                find_proof(str(proof_source))
                proof.write_bytes(proof_source.read_bytes())
            if self.cancel.is_set():
                return
            self.update('starting', 'Starting the Full HD camera stream…')
            with (self.root / 'diagnostics/bridge.log').open('ab') as log:
                bridge = subprocess.Popen([sys.executable, str(Path(__file__).with_name('camera_bridge.py')),
                    '--duration', '0', '--preview-fps', '10', '--proof', str(proof),
                    '--output-root', str(self.root / 'diagnostics')], stdout=log, stderr=subprocess.STDOUT)
            # HTTP readiness is checked by the app. The manager only watches the child process.
            self.update('running', 'Camera is running; waiting for the first frame if necessary.')
            while not self.cancel.wait(.25):
                if bridge.poll() is not None:
                    raise RuntimeError('The camera bridge stopped unexpectedly; see bridge.log and result.json.')
        except Exception as exc:
            self.update('error', str(exc))
            self.failed.write_text(json.dumps({'boot_id': boot_id(), 'error': str(exc)}) + '\n')
        finally:
            if bridge is not None:
                if not stop_bridge(bridge):
                    self.update('error', 'The camera bridge will not stop. Stop issuing camera commands and check the diagnostics.')
                    self.failed.write_text(json.dumps({'boot_id': boot_id(), 'error': self.message}) + '\n')
                elif bridge.returncode not in {0, None} and not (
                        self.cancel.is_set() and bridge.returncode in {-signal.SIGINT, -signal.SIGTERM}):
                    self.update('error', 'The camera bridge reported an error during shutdown; check the diagnostics.')
                    self.failed.write_text(json.dumps({'boot_id': boot_id(), 'error': self.message}) + '\n')
            with self.lock:
                failed = self.state == 'error'
            if not failed:
                self.update('idle', 'Camera stopped. CAMSS stays loaded until shutdown.')

    def tick(self):
        with self.lock:
            wanted = self.leases.active() and not self.stop.is_set()
            active = self.worker is not None and self.worker.is_alive()
            if not wanted:
                self.cancel.set()
            elif not active and self.state != 'error':
                self.cancel = threading.Event()
                self.worker = threading.Thread(target=self.camera_worker, daemon=True)
                self.worker.start()


def server_for(manager, socket_path=SOCKET):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(2)
            try:
                _, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid not in {0, manager.allowed_uid}:
                    raise ValueError('This user does not have camera access.')
                line = self.rfile.readline(1025)
                if len(line) > 1024 or not line.endswith(b'\n'):
                    raise ValueError('The camera request is too large or incomplete.')
                reply = manager.request(json.loads(line))
            except (ValueError, OSError, TypeError) as exc:
                reply = {'state': 'error', 'message': str(exc)}
            try:
                self.wfile.write(json.dumps(reply).encode() + b'\n')
            except OSError:
                pass
    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    path = Path(socket_path)
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode) or path.lstat().st_uid != 0:
            raise RuntimeError('Unexpected file at the camera socket location.')
        path.unlink()
    server = Server(socket_path, Handler)
    os.chown(socket_path, 0, grp.getgrnam('video').gr_gid)
    os.chmod(socket_path, 0o660)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', type=int, required=True)
    args = parser.parse_args()
    os.umask(0o027)
    (STATE / 'diagnostics').mkdir(parents=True, exist_ok=True)
    manager = Manager(args.uid)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: manager.stop.set())
    server = server_for(manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while not manager.stop.wait(.25):
            manager.tick()
    finally:
        manager.tick()
        if manager.worker:
            manager.worker.join(timeout=14)
            if manager.worker.is_alive():
                manager.failed.write_text(json.dumps({'boot_id': boot_id(),
                    'error': 'The camera worker did not stop within the time limit.'}) + '\n')
        server.shutdown()
        server.server_close()
        Path(SOCKET).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
