"""Persistent metadata for the fixed W1 hardware; no per-episode ROS queries."""
from __future__ import annotations

import copy
import hashlib
import json
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
