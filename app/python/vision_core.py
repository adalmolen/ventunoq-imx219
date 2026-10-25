"""Camera client, model letterboxing and consistent frame/detection packets."""
import base64
import io
import math
import threading
import time

from PIL import Image


def letterbox(image, target):
    source_w, source_h = image.size
    width, height = target
    scale = min(width / source_w, height / source_h)
    resized_w, resized_h = max(1, round(source_w * scale)), max(1, round(source_h * scale))
    left, top = (width - resized_w) // 2, (height - resized_h) // 2
    canvas = Image.new('RGB', target, (114, 114, 114))
    canvas.paste(image.resize((resized_w, resized_h), Image.Resampling.LANCZOS), (left, top))
    return canvas, {'source_w': source_w, 'source_h': source_h, 'resized_w': resized_w,
                    'resized_h': resized_h, 'left': left, 'top': top}


def map_detections(result, geometry):
    if not isinstance(result, dict) or not isinstance(result.get('detection'), list):
        raise ValueError('The AI model did not return a valid detection result.')
    detections = []
    for detection in result['detection']:
        box = detection.get('bounding_box_xyxy')
        if not isinstance(box, (tuple, list)) or len(box) != 4:
            continue
        values = [float(v) for v in box]
        confidence = float(detection.get('confidence', 0)) / 100
        if not all(math.isfinite(v) for v in values + [confidence]):
            continue
        x1, y1, x2, y2 = values
        x1 = (x1 - geometry['left']) * geometry['source_w'] / geometry['resized_w']
        x2 = (x2 - geometry['left']) * geometry['source_w'] / geometry['resized_w']
        y1 = (y1 - geometry['top']) * geometry['source_h'] / geometry['resized_h']
        y2 = (y2 - geometry['top']) * geometry['source_h'] / geometry['resized_h']
        x1, x2 = [max(0, min(geometry['source_w'], x)) for x in (x1, x2)]
        y1, y2 = [max(0, min(geometry['source_h'], y)) for y in (y1, y2)]
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append({'label': str(detection.get('class_name', 'object')),
                           'confidence': max(0, min(1, confidence)), 'box': [x1, y1, x2, y2]})
    return detections


class VisionSession:
    def __init__(self, detector, model_size, settings, model_name, labels, source):
        if len(model_size) != 2 or any(not 1 <= value <= 4096 for value in model_size):
            raise ValueError('Invalid image dimensions in the model information.')
        self.detector, self.model_size = detector, tuple(model_size)
        self.source = source
        self.interval = 1 / max(.2, min(10, settings.get('max_inferences_per_second', 5)))
        self.lock = threading.Lock()
        self.threshold = float(settings.get('confidence', .5))
        self.enabled = True
        self.last_id = None
        self.generation = 0
        self.packet = {'status': 'waiting', 'message': 'Waiting for the IMX219 camera bridge…',
                       'model': model_name, 'model_size': list(model_size), 'labels': labels,
                       'image': None, 'detections': [], 'frame_id': None,
                       'captured_at': None, 'inference_ms': None}

    def snapshot(self, after_id=''):
        with self.lock:
            packet = {**self.packet, 'confidence': self.threshold, 'enabled': self.enabled,
                      'server_time': time.time()}
        packet.update(self.source.status())
        packet['result_age_ms'] = max(0, (time.time() - packet['captured_at']) * 1000) if packet['captured_at'] else None
        if after_id == packet['frame_id']:
            packet['image'] = None
        return packet

    def configure(self, values):
        with self.lock:
            threshold = float(values.get('confidence', self.threshold))
            if not math.isfinite(threshold) or not .1 <= threshold <= .95:
                raise ValueError('Choose a detection threshold between 10% and 95%.')
            enabled = values.get('enabled', self.enabled)
            if not isinstance(enabled, bool):
                raise ValueError('enabled must be true or false.')
            self.threshold, self.enabled = threshold, enabled
            self.generation += 1
            self.packet = {**self.packet, 'detections': [], 'status': 'waiting' if enabled else 'paused',
                           'message': 'Applying the new setting' if enabled else 'Detection paused; live preview remains active'}
            self.last_id = None
        return {'confidence': threshold, 'enabled': enabled}

    def step(self):
        started = time.monotonic()
        try:
            with self.lock:
                threshold, enabled, generation = self.threshold, self.enabled, self.generation
            if not enabled:
                time.sleep(.1)
                return
            item = self.source.latest()
            if item is None:
                raise ValueError(self.source.status()['camera_message'])
            frame_id, captured, image_bytes = item
            if frame_id == self.last_id:
                time.sleep(.05)
                return
            with Image.open(io.BytesIO(image_bytes)) as source:
                if source.size != (1920, 1080):
                    raise ValueError(f'Expected 1920×1080; received {source.size}.')
                image = source.convert('RGB')
            inference_ms, detections = None, []
            if enabled:
                model_image, geometry = letterbox(image, self.model_size)
                before = time.monotonic()
                # Explicit PNG bytes preserve the preprocessed model dimensions and format.
                buffer = io.BytesIO()
                model_image.save(buffer, format='PNG', compress_level=1)
                result = self.detector.detect(buffer.getvalue(), image_type='png', confidence=threshold)
                inference_ms = (time.monotonic() - before) * 1000
                detections = map_detections(result, geometry)
            update = {'status': 'live' if enabled else 'paused',
                      'message': 'Object detection is active' if enabled else 'Detection paused; camera remains active',
                      'image': 'data:image/jpeg;base64,' + base64.b64encode(image_bytes).decode('ascii'),
                      'width': 1920, 'height': 1080, 'frame_id': frame_id, 'captured_at': captured,
                      'inference_ms': inference_ms, 'detections': detections}
            with self.lock:
                if generation == self.generation:
                    self.packet = {**self.packet, **update}
                    self.last_id = frame_id
        except Exception as exc:
            with self.lock:
                if generation == self.generation:
                    self.packet = {**self.packet, 'status': 'waiting', 'detections': [],
                                   'message': f'No current frame or AI result: {exc}'}
                    # Recovery may process the same most-recent frame.
                    self.last_id = None
        time.sleep(max(.02, self.interval - (time.monotonic() - started)))
