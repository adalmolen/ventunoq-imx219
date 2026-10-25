#!/usr/bin/env python3
"""Expose Full HD RGB JPEGs from the existing RAW10 pipeline to App Lab."""
import argparse
import io
import ipaddress
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import threading
import time
from picture_settings import LiveLook

from camera_control import (CameraLock, configure, find_proof, kernel_faults, kernel_since,
                            preflight, run, stop_process, stream_command, user_home)


def docker_gateway():
    networks = json.loads(run(['docker', 'network', 'inspect', 'bridge']))
    for config in networks[0]['IPAM']['Config']:
        address = config.get('Gateway', '')
        if address and ipaddress.ip_address(address).version == 4:
            return address
    raise RuntimeError('Docker host gateway not found; use --bind with the correct host gateway address.')


class Frames:
    def __init__(self):
        self.lock = threading.Lock()
        self.raw = None
        self.jpeg = None
        self.received = 0
        self.rendered = 0
        self.started = time.monotonic()
        self.error = None


def handler_for(frames, fmt):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with frames.lock:
                jpeg = frames.jpeg
                state = {**fmt, 'received_frames': frames.received, 'rendered_frames': frames.rendered,
                         'received_fps': frames.received / max(.001, time.monotonic() - frames.started),
                         'error': frames.error, 'frame_id': jpeg[0] if jpeg else None}
            if self.path.split('?')[0] == '/status':
                payload = json.dumps(state).encode()
                code, mime = 200, 'application/json'
            elif self.path.split('?')[0] == '/frame.jpg':
                if jpeg is None or time.time() - jpeg[1] > 3 or state['error']:
                    payload, code, mime = b'No current camera frame yet', 503, 'text/plain'
                else:
                    payload, code, mime = jpeg[2], 200, 'image/jpeg'
            else:
                payload, code, mime = b'Not found', 404, 'text/plain'
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            if mime == 'image/jpeg':
                self.send_header('X-Frame-Id', str(jpeg[0]))
                self.send_header('X-Captured-At', str(jpeg[1]))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass
    return Handler


def reader(process, frames, size, stop):
    buffer = bytearray()
    last = time.monotonic()
    try:
        while not stop.is_set():
            ready, _, _ = select.select([process.stdout], [], [], .25)
            if ready:
                chunk = os.read(process.stdout.fileno(), 1048576)
                if not chunk:
                    raise RuntimeError('The RAW10 stream has stopped.')
                buffer.extend(chunk)
                while len(buffer) >= size:
                    data = bytes(buffer[:size])
                    del buffer[:size]
                    last = time.monotonic()
                    with frames.lock:
                        frames.received += 1
                        frames.raw = (frames.received, time.time(), data)
            if time.monotonic() - last > 5:
                raise RuntimeError('No complete camera frame received for five seconds.')
    except Exception as exc:
        if not stop.is_set():
            with frames.lock:
                frames.error = str(exc)
            stop.set()


def renderer(frames, fmt, lut, fps, stop, look):
    from PIL import Image
    from raw10_rgb import convert
    last_id = None
    try:
        while not stop.is_set():
            started = time.monotonic()
            with frames.lock:
                raw = frames.raw
            if raw is None or raw[0] == last_id:
                stop.wait(.02)
                continue
            rgb = convert(raw[2], fmt['width'], fmt['height'], fmt['bytes_per_line'], lut)
            out = io.BytesIO()
            active_look = look.refresh()
            active_look.apply_array(rgb).save(out, format='JPEG', quality=85)
            with frames.lock:
                frames.jpeg = (raw[0], raw[1], out.getvalue())
                fmt['picture_profile'] = active_look.profile
                fmt['picture_settings'] = look.status()
                frames.rendered += 1
            last_id = raw[0]
            stop.wait(max(0, 1 / fps - (time.monotonic() - started)))
    except Exception as exc:
        with frames.lock:
            frames.error = f'RGB conversion failed: {exc}'
        stop.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=30, help='Seconds; 0 for continuous capture. Test for 30 seconds first.')
    parser.add_argument('--proof', help='result.json from a successful FHD test in the same boot; discovered automatically by default')
    parser.add_argument('--bind', help='Host gateway address; defaults to the Docker bridge gateway, not a LAN address')
    parser.add_argument('--port', type=int, default=8088)
    parser.add_argument('--preview-fps', type=float, default=10)
    parser.add_argument('--output-root', type=Path, help='Existing diagnostics directory for the automatic camera service')
    parser.add_argument('--display-gain', type=float, default=3)
    args = parser.parse_args()
    if (not all(math.isfinite(v) for v in [args.duration, args.preview_fps, args.display_gain])
            or args.duration < 0 or not 0 < args.preview_fps <= 15
            or not 0 < args.display_gain <= 8 or not 1 <= args.port <= 65535):
        parser.error('Invalid duration, preview frame rate, or display gain.')
    try:
        from raw10_rgb import colour_lut
        import PIL.Image
    except ModuleNotFoundError:
        raise RuntimeError('Host dependencies are missing. Install python3-numpy and python3-pil.') from None
    info = preflight()
    proof = find_proof(args.proof)
    address = args.bind or docker_gateway()
    ipaddress.IPv4Address(address)
    output = Path(tempfile.mkdtemp(prefix='ventunoq-imx219-fhd-live.', dir=args.output_root or user_home()))
    output.chmod(0o755)
    profile = json.loads(Path(__file__).with_name('white_balance.json').read_text())
    gains = [profile['gains'][name] for name in ['R', 'G', 'B']]
    lut = colour_lut(gains, profile['black_level'], args.display_gain)
    from picture_look import Look, load, apply_exposure
    look = LiveLook(load(), Look)
    stop = threading.Event()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, lambda *_: stop.set())
    frames, process, server, threads = Frames(), None, None, []
    start_uptime = float(Path('/proc/uptime').read_text().split()[0])
    result = {**info, 'proof': str(proof), 'duration_requested': args.duration, 'display_gain': args.display_gain,
              'white_balance_gains': profile['gains'], 'picture_profile': look.look.profile, 'passed': False}
    duration_completed = False
    with CameraLock():
        try:
            fmt = configure(output)
            apply_exposure(fmt['sensor'], look.look.profile['exposure_lines'], run)
            fmt['exposure_lines'] = look.look.profile['exposure_lines']
            fmt['picture_profile'] = look.look.profile
            fmt['picture_settings'] = look.status()
            (output / 'controls-picture.txt').write_text(run(['v4l2-ctl', '-d', fmt['sensor'], '--list-ctrls']))
            result['format'] = fmt
            server = ThreadingHTTPServer((address, args.port), handler_for(frames, fmt))
            server.daemon_threads = True
            log = (output / 'stream-stderr.txt').open('wb')
            frames.started = time.monotonic()
            process = subprocess.Popen(stream_command(fmt['video'], '-'), stdout=subprocess.PIPE, stderr=log, bufsize=0)
            log.close()
            for target, target_args in [(server.serve_forever, ()),
                    (reader, (process, frames, fmt['size_image'], stop)),
                    (renderer, (frames, fmt, lut, args.preview_fps, stop, look))]:
                thread = threading.Thread(target=target, args=target_args, daemon=True)
                thread.start()
                threads.append(thread)
            started, next_report = time.monotonic(), time.monotonic()
            print(f'Camera bridge: http://{address}:{args.port}\nApp Lab source: http://msgpack-rpc-router:{args.port}\nDiagnostics: {output}', flush=True)
            while not stop.wait(.2):
                elapsed = time.monotonic() - started
                if args.duration and elapsed >= args.duration:
                    duration_completed = True
                    break
                if time.monotonic() >= next_report:
                    with frames.lock:
                        print(f'{frames.received} RAW frames; {frames.rendered} RGB previews; approximately {frames.received / max(.001, elapsed):.1f} received fps', flush=True)
                    next_report = time.monotonic() + 5
        except Exception as exc:
            frames.error = str(exc)
        finally:
            stop.set()
            stopped = stop_process(process) if process else True
            if server:
                if threads:
                    server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=1)
            logs = kernel_since(start_uptime)
            (output / 'kernel.log').write_text(logs)
            faults = kernel_faults(logs)
            result.update(capture_process_stopped=stopped, received_frames=frames.received,
                          rendered_frames=frames.rendered, elapsed_s=time.monotonic() - frames.started,
                          duration_completed=duration_completed, error=frames.error, new_kernel_faults=faults)
            result['passed'] = bool(stopped and frames.rendered and not frames.error and not faults
                                    and (args.duration == 0 or duration_completed))
            result['cancelled_before_first_frame'] = bool(args.duration == 0 and stopped and not frames.rendered
                                                         and not frames.error and not faults)
            (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'Bridge stopped. Passed: {result["passed"]}. Diagnostics: {output}. CAMSS stays loaded.', flush=True)
    if not result['capture_process_stopped']:
        print('The capture process will not stop. Use a second terminal; do not unload modules.', flush=True)
    return 0 if result['passed'] or result['cancelled_before_first_frame'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'ERROR: {exc}') from None
