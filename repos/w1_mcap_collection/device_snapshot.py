"""Persistent metadata for the fixed W1 hardware; no per-episode ROS queries."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading

import yaml
import time
from pathlib import Path

from storage import atomic_json

PROFILE = 'dexforce-w1-pc1-linker-l6'
FIELDS = ('body_joint_names', 'head_calibration_raw', 'head_stereo')


def validated_snapshot(value):
    """Return only device metadata, rejecting incomplete or inconsistent captures."""
    if not isinstance(value, dict):
        raise ValueError('Device snapshot is not an object')
    names = value.get('body_joint_names')
    if (not isinstance(names, list) or not names
            or not all(isinstance(name, str) and name.strip() for name in names)
            or len(set(names)) != len(names)):
        raise ValueError('Device snapshot has no valid joint names')
    calibration = value.get('head_calibration_raw')
    if not isinstance(calibration, str) or not calibration.strip():
        raise ValueError('Device snapshot has no camera calibration')
    image = value.get('head_stereo')
    if not isinstance(image, dict):
        raise ValueError('Device snapshot has no image metadata')
    for field in ('width', 'height', 'per_eye_width', 'per_eye_height', 'observed_time_ns'):
        if type(image.get(field)) is not int or image[field] <= 0:
            raise ValueError(f'Device snapshot has invalid image {field}')
    if (image.get('topic') != '/camera/kfc_compressed'
            or image.get('message_type') != 'sensor_msgs/msg/CompressedImage'
            or image.get('layout') != 'left_right_side_by_side'
            or not isinstance(image.get('encoding'), str) or not image['encoding'].strip()
            or image['width'] != 2 * image['per_eye_width']
            or image['height'] != image['per_eye_height']):
        raise ValueError('Device snapshot image layout is inconsistent')
    return {field: copy.deepcopy(value[field]) for field in FIELDS}


def checksum(snapshot):
    data = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


class DeviceSnapshot:
    """Load once on startup, persist complete captures, and refresh only on request."""

    def __init__(self, path, capture):
        self.path = Path(path)
        self.capture = capture
        self._value = {}
        self._warnings = []
        self._metadata = {'source': 'unavailable', 'persistent': False,
                          'captured_wall_ns': None}
        try:
            record = json.loads(self.path.read_text())
            if (not isinstance(record, dict) or record.get('version') != 1
                    or record.get('profile') != PROFILE
                    or type(record.get('captured_wall_ns')) is not int
                    or record['captured_wall_ns'] <= 0):
                raise ValueError('Unsupported device snapshot cache')
            value = validated_snapshot(record.get('snapshot'))
            if checksum(value) != record.get('sha256'):
                raise ValueError('Device snapshot cache checksum mismatch')
            self._install(record, 'cache')
            return
        except (OSError, ValueError, TypeError):
            pass

        # A failed/partial first capture must not become a permanent cache.
        # Preserve available metadata and missing-data behavior for this service run.
        value = {}
        try:
            value = self.capture()
            self._save(value)
        except Exception as exc:
            self._value = copy.deepcopy(value) if isinstance(value, dict) else {}
            self._warnings = [f'Device snapshot not cached: {exc}']
            self._metadata = {'source': 'uncached', 'persistent': False,
                              'captured_wall_ns': time.time_ns()}

    def _install(self, record, source):
        self._value = copy.deepcopy(record['snapshot'])
        self._warnings = []
        self._metadata = {'source': source, 'persistent': True,
                          'captured_wall_ns': record['captured_wall_ns']}

    def _save(self, value):
        value = validated_snapshot(value)
        record = {'version': 1, 'profile': PROFILE, 'captured_wall_ns': time.time_ns(),
                  'snapshot': value, 'sha256': checksum(value)}
        atomic_json(self.path, record)
        self._install(record, 'capture')

    def refresh(self):
        """Replace the cache only after a complete new capture succeeds."""
        self._save(self.capture())
        return self.describe()

    def describe(self):
        return {'cache_path': str(self.path), **self._metadata,
                'warnings': list(self._warnings)}

    def for_episode(self):
        value = copy.deepcopy(self._value)
        value['snapshot_metadata'] = dict(self._metadata)
        return value, list(self._warnings)


class HeadCalibration:
    """Associate live stereo calibration with the episode, including changes and loss."""
    def __init__(self):
        self.lock = threading.Lock()
        self.path = self.metadata = None
        self.current = None
        self.reason = 'missing'
        self.last_raw = None
        self.observed_ns = self.last_seen = 0
        self.dirty = False
        self.camera_topics = []
        self.d2c_topics = []
        self.camera_values = {}

    def observe_camera_info(self, topic, parameters):
        with self.lock:
            self.camera_values[topic] = dict(parameters=copy.deepcopy(parameters), sha256=checksum(parameters),
                                              observed_wall_ns=time.time_ns(), last_seen=time.monotonic())
            self._update()

    def observe_d2c_extrinsics(self, topic, raw):
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('transform') != 'T_rgb_from_depth':
            raise ValueError('Invalid depth-to-RGB transform direction')
        for name, size in [('rotation_row_major', 9), ('translation_mm', 3)]:
            vector = value.get(name)
            if (not isinstance(vector, list) or len(vector) != size or
                    not all(type(v) in (int, float) and math.isfinite(v) for v in vector)):
                raise ValueError('Invalid depth-to-RGB ' + name)
        r = value['rotation_row_major']
        for i in range(3):
            for j in range(3):
                dot = sum(r[3*i+k] * r[3*j+k] for k in range(3))
                if abs(dot - int(i == j)) > 1e-3:
                    raise ValueError('Depth-to-RGB rotation is not orthonormal')
        determinant = (r[0]*(r[4]*r[8]-r[5]*r[7]) - r[1]*(r[3]*r[8]-r[5]*r[6])
                       + r[2]*(r[3]*r[7]-r[4]*r[6]))
        if abs(determinant - 1) > 1e-3:
            raise ValueError('Invalid depth-to-RGB rotation determinant')
        self.observe_camera_info(topic, value)

    @staticmethod
    def parse(raw):
        if not isinstance(raw, str) or len(raw) > 65536:
            raise ValueError('Invalid calibration payload size')
        data = yaml.safe_load(raw)
        if not isinstance(data, dict) or not isinstance(data.get('SN'), str) or not data['SN'].strip():
            raise ValueError('Missing stereo camera serial')
        for field, rows, cols in [('cam1_k',3,3), ('cam2_k',3,3), ('R_l_r',3,3), ('t_l_r',3,1),
                                  ('dist_1',1,None), ('dist_2',1,None), ('image_size',1,2)]:
            matrix = data[field]
            if (not isinstance(matrix,list) or len(matrix) != rows or
                    not all(isinstance(row,list) and (cols is None or len(row) == cols) and row and
                            all(type(v) in (float,int) and math.isfinite(v) for v in row) for row in matrix)):
                raise ValueError(f'Invalid calibration {field}')
        if (any(type(v) is not int or v <= 0 for v in data['image_size'][0])
                or any(data[k][i][i] <= 0 for k in ('cam1_k','cam2_k') for i in (0,1))):
            raise ValueError('Invalid camera dimensions or focal length')
        return {'sha256':checksum(data), 'serial':data['SN'], 'raw':raw}

    def observe(self, raw):
        with self.lock:
            self.observed_ns, self.last_seen = time.time_ns(), time.monotonic()
            if raw != self.last_raw:
                try:
                    self.current = self.parse(raw)
                    self.reason = 'available'
                except (KeyError, TypeError, ValueError, OverflowError, RecursionError, yaml.YAMLError):
                    self.current, self.reason = None, 'invalid'
                self.last_raw = raw
            self._update()

    def _expire(self):
        if self.last_seen and time.monotonic() - self.last_seen > 3:
            self.current, self.last_raw, self.reason = None, None, 'missing'

    def tick(self):
        with self.lock:
            self._expire()
            self._update()

    def attach(self, path, metadata):
        with self.lock:
            self.path, self.metadata = path, metadata
            if 'head_calibration' not in metadata:
                metadata.pop('head_calibration_raw', None)  # Ignore the fixed-device cache for this field.
                metadata['head_calibration'] = {'versions': {}, 'history': []}
            self._expire()
            self.dirty = True
            self._update(force=True)

    def _update(self, force=False):
        if self.metadata is None:
            return
        groups = (
            ('camera_info', 'sensor_msgs/msg/CameraInfo', self.camera_topics),
            ('orbbec_depth_to_rgb_extrinsics', 'std_msgs/msg/String', self.d2c_topics),
        )
        for group, message_type, topics in groups:
            for topic in topics:
                entry = self.metadata.setdefault(group, {}).setdefault(topic,
                    dict(message_type=message_type, versions={}, history=[]))
                current = self.camera_values.get(topic)
                if current and time.monotonic() - current['last_seen'] > 3:
                    current = None
                key = current['sha256'] if current else None
                status = 'available' if current else 'missing'
                previous = entry['history'][-1] if entry['history'] else {}
                if (status, key) != (previous.get('status'), previous.get('sha256')):
                    if current:
                        entry['versions'][key] = dict(sha256=key, parameters=current['parameters'])
                    entry['history'].append(dict(status=status, sha256=key, effective_wall_ns=time.time_ns(),
                                                 observed_wall_ns=current['observed_wall_ns'] if current else None))
                    self.dirty = True
        record = self.metadata['head_calibration']
        key = self.current['sha256'] if self.current else None
        state = (self.reason, key)
        previous = record['history'][-1] if record['history'] else {}
        if force or state != (previous.get('status'), previous.get('sha256')):
            if self.current:
                record['versions'][key] = self.current
                self.metadata.setdefault('head_calibration_raw', self.current['raw'])
            record['history'].append(dict(status=self.reason, sha256=key, effective_wall_ns=time.time_ns(),
                                          observed_wall_ns=self.observed_ns if self.current else None))
            self.dirty = True
        if self.dirty:
            # Keep pending changes in memory and retry on the next monitor tick on write failure.
            try:
                atomic_json(self.path, self.metadata)
            except OSError as exc:
                print('Calibration metadata write failed:', exc, flush=True)
                if force:
                    raise
            else:
                self.dirty = False

    def detach(self):
        with self.lock:
            try:
                if self.dirty:
                    atomic_json(self.path, self.metadata)
            finally:
                self.metadata = self.path = None
                self.dirty = False
