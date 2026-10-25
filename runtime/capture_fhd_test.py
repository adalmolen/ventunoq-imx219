#!/usr/bin/env python3
"""Capture exactly three Full HD RAW10 frames without changing kernel modules."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

from camera_control import (CameraLock, configure, kernel_faults, kernel_since,
                            preflight, stop_process, stream_command, user_home)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, help='Existing diagnostics directory for the automatic camera service')
    args = parser.parse_args()
    info = preflight()
    output = Path(tempfile.mkdtemp(prefix='ventunoq-imx219-fhd-test.', dir=args.output_root or user_home()))
    output.chmod(0o755)
    start = float(Path('/proc/uptime').read_text().split()[0])
    result = {**info, 'passed': False, 'output': str(output)}
    process = None
    try:
        with CameraLock():
            fmt = configure(output)
            result['format'] = fmt
            print(json.dumps(fmt, indent=2), flush=True)
            with (output / 'stream.txt').open('wb') as log:
                process = subprocess.Popen(stream_command(fmt['video'], str(output / 'frames.raw'), 3, True),
                                           stdout=log, stderr=subprocess.STDOUT)
                try:
                    code = process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    stopped = stop_process(process)
                    result['capture_process_stopped'] = stopped
                    raise RuntimeError('Capture timed out. ' + ('Process stopped.' if stopped else
                        'The process will not stop. Use a second terminal; do not unload modules.')) from None
            raw = (output / 'frames.raw').read_bytes()
            expected = 3 * fmt['size_image']
            result.update(returncode=code, bytes_received=len(raw), bytes_expected=expected,
                          raw_sha256=hashlib.sha256(raw).hexdigest(),
                          frame_count=len(raw) // fmt['size_image'], requested_frame_count=3)
            print((output / 'stream.txt').read_text(), flush=True)
            if code != 0 or len(raw) != expected:
                raise RuntimeError(f'Three complete frames were not received: {len(raw)}/{expected} bytes; exit code {code}.')
            controls = subprocess.run(['v4l2-ctl', '-d', fmt['sensor'], '--list-ctrls'],
                                      capture_output=True, text=True, check=True).stdout
            (output / 'controls-after.txt').write_text(controls)
            result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
        print(f'ERROR: {exc}', flush=True)
    finally:
        if process is not None and process.poll() is None and 'capture_process_stopped' not in result:
            result['capture_process_stopped'] = stop_process(process)
        if process is not None and process.poll() is not None:
            result['capture_process_stopped'] = True
        try:
            logs = kernel_since(start)
            (output / 'kernel.log').write_text(logs)
            result['new_kernel_faults'] = kernel_faults(logs)
            if result['new_kernel_faults']:
                result.update(passed=False, error='New camera fault in kernel.log; do not start the camera bridge yet.')
        except Exception as exc:
            result.update(passed=False, diagnostic_error=str(exc))
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'Passed: {result["passed"]}\nFiles: {output}\nThe module stays loaded.', flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'ERROR: {exc}') from None
