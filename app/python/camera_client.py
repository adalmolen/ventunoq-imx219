"""Latest-frame cache and local camera lease, independent of slow AI calls."""
import json
import math
import socket
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener
import uuid


class CameraSource:
    def __init__(self, settings):
        self.url = settings['camera_url'].rstrip('/')
        self.managed = settings.get('manage_camera', True)
        self.socket_path = settings.get('control_socket', '/dev/ventuno-imx219-control.sock')
        self.interval = 1 / max(1, min(15, settings.get('preview_fps', 10)))
        self.session = str(uuid.uuid4())
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.frame, self.error = None, None
        self.control = {'state': 'starting' if self.managed else 'running', 'message': 'Connecting to the camera…'}
        self.opener = build_opener(ProxyHandler({}))
        self.threads = []

    def command(self, action, values=None):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(self.socket_path)
            payload = {'action': action, 'session': self.session}
            if values is not None:
                payload['values'] = values
            client.sendall(json.dumps(payload).encode() + b'\n')
            response = bytearray()
            while not response.endswith(b'\n'):
                data = client.recv(4096)
                if not data or len(response) + len(data) > 8192:
                    raise RuntimeError('Invalid response from the camera service.')
                response.extend(data)
        result = json.loads(response)
        if not isinstance(result, dict) or 'state' not in result:
            raise RuntimeError('Invalid response from the camera service.')
        return result

    def picture(self, values=None):
        result = self.command('picture_get' if values is None else 'picture_set', values)
        if 'picture' not in result:
            raise ValueError(result.get('message', 'The picture setting could not be saved.'))
        return result['picture']

    def lease_loop(self):
        while not self.stop.is_set():
            try:
                result = self.command('lease')
            except Exception as exc:
                result = {'state': 'error', 'message': 'Camera service is unavailable. Install the host package. ' + str(exc)}
            with self.lock:
                self.control = result
            self.stop.wait(3)

    def poll_once(self):
        with self.lock:
            control = dict(self.control)
        if control['state'] != 'running':
            return
        try:
            request = Request(self.url + '/frame.jpg', headers={'Cache-Control': 'no-cache'})
            with self.opener.open(request, timeout=2) as response:
                identity = response.headers.get('X-Frame-Id')
                captured = float(response.headers['X-Captured-At'])
                data = response.read(8 * 1024 * 1024 + 1)
            if identity is None or not data or len(data) > 8 * 1024 * 1024:
                raise ValueError('An incomplete camera frame was received.')
            if not math.isfinite(captured) or not -1 <= time.time() - captured <= 3:
                raise ValueError('No current camera frame was received.')
            with self.lock:
                self.frame, self.error = (identity, captured, data), None
        except Exception as exc:
            with self.lock:
                self.error = str(exc)

    def frame_loop(self):
        while not self.stop.is_set():
            started = time.monotonic()
            self.poll_once()
            self.stop.wait(max(.01, self.interval - (time.monotonic() - started)))

    def latest(self):
        with self.lock:
            frame = self.frame
            if self.error or self.control['state'] != 'running' or frame is None or time.time() - frame[1] > 3:
                return None
            return frame

    def status(self):
        frame = self.latest()
        with self.lock:
            return {'camera_status': 'live' if frame else self.control['state'],
                    'camera_message': ('Camera active' if frame else self.error or self.control['message']),
                    'preview_frame_id': frame[0] if frame else None,
                    'preview_age_ms': max(0, (time.time() - frame[1]) * 1000) if frame else None}

    def start(self):
        targets = [self.frame_loop] + ([self.lease_loop] if self.managed else [])
        for target in targets:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=2.5)
        if self.managed:
            try:
                self.command('release')
            except Exception:
                pass  # The host expires a lost lease after 12 seconds.
