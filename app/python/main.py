"""Arduino App Lab app: camera lifetime, responsive preview and object detection."""
import atexit
import json
from pathlib import Path
import time

from arduino.app_bricks.object_detection import ObjectDetection
from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App
from fastapi import HTTPException
from fastapi.responses import Response

from camera_client import CameraSource
from vision_core import VisionSession

settings = json.loads(Path(__file__).with_name('settings.json').read_text())
source = CameraSource(settings)
atexit.register(source.close)
source.start()
detector = ObjectDetection(confidence=settings['confidence'])
model = detector.get_model_info()
if model is None:
    raise RuntimeError('De Object Detection-brick heeft geen modelinformatie geleverd.')
session = VisionSession(detector, (model.image_input_width, model.image_input_height), settings,
                        getattr(model, 'name', 'Object Detection'), getattr(model, 'labels', []), source=source)
ui = WebUI()


def configure(payload: dict):
    try:
        return session.configure(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def frame(after_id: str = ''):
    item = source.latest()
    headers = {'Cache-Control': 'no-store'}
    if item is None:
        return Response(status_code=503, headers=headers)
    identity, captured, data = item
    headers.update({'X-Frame-Id': identity, 'X-Frame-Age-Ms': str(max(0, (time.time() - captured) * 1000))})
    return Response(content=data if identity != after_id else None,
                    status_code=200 if identity != after_id else 204, media_type='image/jpeg', headers=headers)


def result(after_id: str = ''):
    return session.snapshot(after_id)


def picture():
    try:
        return source.picture()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def picture_configure(payload: dict):
    try:
        return source.picture(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


ui.expose_api('GET', '/api/frame.jpg', frame)
ui.expose_api('GET', '/api/result', result)
ui.expose_api('POST', '/api/settings', configure)
ui.expose_api('GET', '/api/picture', picture)
ui.expose_api('POST', '/api/picture', picture_configure)

print('IMX219-app v2: automatische camera, zelfstandig livebeeld en aparte herkenningsbeelden.', flush=True)
try:
    App.run(user_loop=session.step)
finally:
    source.close()
