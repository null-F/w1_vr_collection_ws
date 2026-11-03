"""No hardware, HTTP requests, service operations, or real ROS nodes."""
import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
import yaml

import ffg_entry as entry
import glove_ports
from w1_hand_bridge import convert_motor
from linkerbot_ffg_ros.calibration.poses import POSES, pose_keys
from linkerbot_ffg_ros.hands.l6 import GLOVE_INDICES
from linkerbot_ffg_ros.mappers.l6 import L6Mapper
from linkerbot_ffg_ros.teleop.types import GloveFrame


def calibration_doc(side):
    return {
        'meta': {'side': side, 'unit': 'deg', 'joint_count': 21},
        'poses': {key: {'joints_deg': [0.0] * 21} for key in pose_keys()},
        'base': [0.0] * 21, 'joint_range': [100.0] * 21,
    }


def write_calibrations(tmp_path):
    paths = {}
    for side in entry.SIDES:
        paths[side] = tmp_path / f'glove_{side}_test.yaml'
        paths[side].write_text(yaml.safe_dump(calibration_doc(side)))
    return paths


def test_upstream_is_pinned_and_unmodified():
    meta = entry.load_sdk()
    assert meta['commit'] == '6da23b796c14b4bed8eaadecdf193f8058fe67ed'
    for name, sha in meta['sha256'].items():
        assert hashlib.sha256((entry.SDK_ROOT / name).read_bytes()).hexdigest() == sha, name


def test_python_310_syntax_not_a_runtime_compatibility_claim():
    files = list((entry.SDK_ROOT / 'src/linkerbot_ffg_ros').rglob('*.py'))
    files += [Path(entry.__file__), Path(glove_ports.__file__)]
    for path in files:
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 10))


def test_w1_profile_is_not_upstream_default():
    settings = entry.load_profile()
    assert settings.robot == 'l6' and settings.hand_sdk == 'LinkerH'
    assert settings.rate_hz == 30 and settings.smooth
    assert settings.smooth_alpha == .5 and settings.smooth_max_step == 20
    assert not settings.force.enabled and not settings.serial.auto_scan
    assert settings.calib_dir == entry.ROOT / 'runtime/calibration/glove_ffg'
    assert settings.serial.left_port is None and settings.serial.right_port is None


@pytest.mark.parametrize('section,key,value', [
    ('system', 'robot', 'o6'), ('system', 'hand_sdk', 'LinkerZ'),
    ('force_feedback', 'enabled', True), ('serial', 'auto_scan', True),
])
def test_reject_unsafe_profile(monkeypatch, section, key, value):
    from linkerbot_ffg_ros import settings as sdk_settings
    doc = yaml.safe_load((entry.ROOT / 'config/w1/glove_ffg.yaml').read_text())
    doc[section][key] = value
    if section == 'force_feedback':
        doc[section]['default']['enabled'] = True
    monkeypatch.setattr(sdk_settings, 'load_yaml', lambda _: doc)
    with pytest.raises(ValueError, match='W1 requires'):
        entry.load_profile()


@pytest.mark.parametrize('ports', [[], ['/dev/a'], ['/dev/a', '/dev/a'], ['/dev/a', '/dev/b', '/dev/c']])
def test_serial_requires_exactly_two_distinct_candidates(ports):
    with pytest.raises(ValueError):
        entry.serial_targets(entry.load_profile(), ports)


def test_usb_whitelist_and_permissions(monkeypatch):
    monkeypatch.setattr(glove_ports, 'glove_ports', lambda: ['/dev/ttyUSB9'])
    with pytest.raises(RuntimeError, match='two CH340'):
        glove_ports.checked_glove_ports()
    ports = ['/dev/ttyUSB9', '/dev/ttyUSB8']
    monkeypatch.setattr(glove_ports, 'glove_ports', lambda: ports)
    monkeypatch.setattr(glove_ports.os, 'access', lambda *_: False)
    with pytest.raises(RuntimeError, match='permission'):
        glove_ports.checked_glove_ports()
    monkeypatch.setattr(glove_ports.os, 'access', lambda *_: True)
    assert glove_ports.checked_glove_ports() == ports


@pytest.mark.parametrize('side_names,fail_second,expected', [
    (['right', 'left'], False, None),
    (['left', 'left'], False, 'duplicate'),
    (['left', 'right'], True, 'identify'),
    (['unknown', 'right'], False, 'Invalid'),
])
def test_pair_detection_and_cleanup(monkeypatch, side_names, fail_second, expected):
    from linkerbot_ffg_ros import glove_ffg
    created = []
    class Reader:
        def __init__(self):
            self.index = len(created)
            self.side = side_names[self.index]
            self.closed = False
            created.append(self)
        def open(self, port, baud):
            self.port = port
            assert port in ('/dev/qualifiedA', '/dev/qualifiedB')
            assert baud == 2000000
            return True
        def query_version(self):
            return not (fail_second and self.index == 1)
        def close(self):
            self.closed = True
    monkeypatch.setattr(glove_ffg, 'GloveReader', Reader)
    monkeypatch.setattr(entry, 'checked_glove_ports', lambda: ['/dev/qualifiedA', '/dev/qualifiedB'])
    if expected:
        with pytest.raises(RuntimeError, match=expected):
            entry.scan_pair(entry.load_profile())
        assert all(r.closed for r in created)
    else:
        gloves = entry.scan_pair(entry.load_profile())
        assert gloves['right'][1] == '/dev/qualifiedA'
        assert gloves['left'][1] == '/dev/qualifiedB'
        assert not any(r.closed for r in created)


@pytest.mark.parametrize('side', entry.SIDES)
def test_new_l6_outputs_match_existing_w1_bridge_contract(side):
    mapper = L6Mapper.from_calibration_doc(calibration_doc(side), smooth=False)
    for closing, expected in ((0, 0), (50, 50), (100, 100)):
        frame = GloveFrame(side=side, joints_deg=[closing] * 21, timestamp=1.0)
        command = mapper.map(frame)
        assert command.robot_name == 'l6' and len(command.positions) == 6
        assert convert_motor(command.positions) == pytest.approx([expected] * 6)
    # Verify all six register positions, especially thumb bend vs thumb lateral.
    for motor, glove_index in enumerate(GLOVE_INDICES):
        joints = [0.0] * 21
        joints[glove_index] = 100.0
        command = mapper.map(GloveFrame(side=side, joints_deg=joints, timestamp=2.0))
        expected = [0.0] * 6
        expected[motor] = 100.0
        assert convert_motor(command.positions) == pytest.approx(expected)


@pytest.mark.parametrize('damage', ['old_format', 'wrong_side', 'missing_pose', 'nan_range'])
def test_reject_incompatible_calibration(tmp_path, damage):
    paths = write_calibrations(tmp_path)
    doc = calibration_doc('left')
    if damage == 'old_format':
        doc = {'calibrationoriginal': [0] * 21}
    elif damage == 'wrong_side':
        doc['meta']['side'] = 'right'
    elif damage == 'missing_pose':
        doc['poses'].pop('thumb_flex')
    else:
        doc['joint_range'][4] = float('nan')
    paths['left'].write_text(yaml.safe_dump(doc))
    with pytest.raises((ValueError, KeyError)):
        entry.build_mappers(paths, entry.load_profile())


def test_calibration_validation_does_not_prime_smoothing(tmp_path):
    mappers = entry.build_mappers(write_calibrations(tmp_path), entry.load_profile())
    for mapper in mappers.values():
        assert mapper.smoother._state is None


def test_five_stage_events_precede_sampling_and_restore_hook(monkeypatch):
    from linkerbot_ffg_ros.app import calibrate_glove
    events = []
    def capture(readers, pose, **kwargs):
        events.append(('sample', pose.key))
        return {'left': [0] * 21, 'right': [0] * 21}
    monkeypatch.setattr(calibrate_glove, 'capture_pose_multi', capture)
    monkeypatch.setattr(entry, 'emit', lambda event, **kw: events.append((event, kw['stage'])))
    monkeypatch.setattr(entry, 'speak_while_polling', lambda *a: events.append(('voice',)))
    with entry.calibration_events(True):
        for pose in POSES:
            calibrate_glove.capture_pose_multi({}, pose)
    assert calibrate_glove.capture_pose_multi is capture
    assert [e[1] for e in events if e[0] == 'stage'] == pose_keys()
    for index, pose in enumerate(POSES):
        assert events[index * 3:index * 3 + 3] == [('stage', pose.key), ('voice',), ('sample', pose.key)]


def test_speech_failure_does_not_sample_or_leave_hook(monkeypatch):
    from linkerbot_ffg_ros.app import calibrate_glove
    calls = []
    original = lambda *a, **kw: calls.append('sample')
    monkeypatch.setattr(calibrate_glove, 'capture_pose_multi', original)
    monkeypatch.setattr(entry, 'emit', lambda *a, **kw: None)
    def fail(*a):
        raise RuntimeError('voice failed')
    monkeypatch.setattr(entry, 'speak_while_polling', fail)
    with pytest.raises(RuntimeError, match='voice failed'), entry.calibration_events(True):
        calibrate_glove.capture_pose_multi({}, POSES[0])
    assert calls == [] and calibrate_glove.capture_pose_multi is original


def test_terminal_calibration_has_no_voice_hook():
    from linkerbot_ffg_ros.app import calibrate_glove
    original = calibrate_glove.capture_pose_multi
    with entry.calibration_events(False):
        assert calibrate_glove.capture_pose_multi is original


def test_speech_wait_keeps_serial_on_owner_thread():
    owner = threading.get_ident()
    polled = threading.Event()
    speaker_threads = []
    def speaker(text):
        speaker_threads.append(threading.get_ident())
        assert polled.wait(timeout=2)
    class Reader:
        def poll(self):
            assert threading.get_ident() == owner
            polled.set()
    entry.speak_while_polling({'left': Reader(), 'right': Reader()}, 'prompt', speaker)
    assert polled.is_set() and speaker_threads[0] != owner


def test_speech_error_propagates():
    def fail(text):
        raise RuntimeError('offline')
    with pytest.raises(RuntimeError, match='offline'):
        entry.speak_while_polling({}, 'prompt', fail)


def test_manager_accepts_all_new_stages_and_legacy(tmp_path):
    from glove_manager import Manager
    voice = SimpleNamespace(say=lambda *_: None, clear=lambda: None)
    manager = Manager(voice=voice, runtime=tmp_path)
    manager.proc = SimpleNamespace(pid=123)
    for stage in pose_keys() + ['fist', 'opose', 'original']:
        manager._event(manager.proc, {'event': 'stage', 'stage': stage})
        assert manager.phase == 'calibrating' and manager.stage == stage
    manager._event(manager.proc, {'event': 'ready'})
    assert manager.phase == 'following'


def test_preflight_opens_no_devices_or_ros_node(monkeypatch, capsys):
    rclpy = pytest.importorskip('rclpy')
    def forbidden(*a, **kw):
        pytest.fail('preflight must not touch devices or initialize ROS')
    monkeypatch.setattr(entry, 'checked_glove_ports', forbidden)
    monkeypatch.setattr(rclpy, 'init', forbidden)
    assert entry.main(['--check']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['hand_sdk'] == 'LinkerH' and output['force_feedback'] is False


@pytest.mark.parametrize('reuse', [False, True])
@pytest.mark.parametrize('fail_map', [False, True])
def test_composed_runtime_real_mapping_mock_hardware_and_ros(monkeypatch, tmp_path, reuse, fail_map):
    rclpy = pytest.importorskip('rclpy')
    import rclpy.node
    from builtin_interfaces.msg import Time
    from linkerbot_ffg_ros.app import calibrate_glove
    paths = write_calibrations(tmp_path)
    settings = replace(entry.load_profile(), calib_dir=tmp_path)
    observed = {'init': None, 'shutdown': 0, 'destroy': 0, 'events': [], 'messages': [], 'calibrations': 0}
    active = {'live': False, 'ticks': 0}
    class Reader:
        def __init__(self, side):
            self.side = side
            self.closed = False
        def poll(self, **kw):
            pass
        def read(self):
            values = [50.0] * 21
            if fail_map and self.side == 'right':
                values[0] = float('nan')
            return GloveFrame(side=self.side, joints_deg=values, timestamp=3.0)
        def close(self):
            self.closed = True
    readers = {side: Reader(side) for side in entry.SIDES}
    monkeypatch.setattr(entry, 'scan_pair', lambda _: {s: (r, '/dev/fake', 2000000) for s, r in readers.items()})
    def calibrate(*a, **kw):
        observed['calibrations'] += 1
        assert kw['output'] == tmp_path and kw['close_on_exit'] is False
        return paths
    monkeypatch.setattr(calibrate_glove, 'run_calibration', calibrate)
    monkeypatch.setattr(entry, 'emit', lambda event, **kw: observed['events'].append(event))
    def init(args):
        observed['init'] = args
        active['live'] = True
    def spin(node, timeout_sec):
        if timeout_sec == 0.0:
            active['ticks'] += 1
            if active['ticks'] >= 2:
                active['live'] = False
    def shutdown():
        observed['shutdown'] += 1
        active['live'] = False
    class Node:
        def __init__(self, name):
            pass
        def create_publisher(self, msg_type, topic, qos):
            def publish(message):
                observed['messages'].append((topic, message))
            return SimpleNamespace(publish=publish)
        def get_logger(self):
            return SimpleNamespace(info=lambda *_: None, error=lambda *_: None)
        def get_clock(self):
            return SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: Time(sec=3)))
        def destroy_node(self):
            observed['destroy'] += 1
    monkeypatch.setattr(rclpy, 'init', init)
    monkeypatch.setattr(rclpy, 'ok', lambda: active['live'])
    monkeypatch.setattr(rclpy, 'spin_once', spin)
    monkeypatch.setattr(rclpy, 'shutdown', shutdown)
    monkeypatch.setattr(rclpy.node, 'Node', Node)
    if fail_map:
        with pytest.raises(ValueError, match='非有限'):
            entry.run(settings, reuse_calibration=reuse, vr_events=True)
        assert 'ready' not in observed['events']
    else:
        assert entry.run(settings, reuse_calibration=reuse, vr_events=True) == 0
        assert observed['events'] == ['ready']
        assert {t for t, m in observed['messages']} == {'/cb_left_hand_control_cmd', '/cb_right_hand_control_cmd'}
        assert all(convert_motor(m.position) == pytest.approx([50] * 6) for t, m in observed['messages'])
    assert observed['init'] == entry.REMAPS
    assert all(r.closed for r in readers.values())
    assert observed['destroy'] == 1
    assert observed['calibrations'] == (0 if reuse else 1)


def test_main_emits_failed_on_runtime_error(monkeypatch, capsys):
    pytest.importorskip('rclpy')
    def fail(*a, **kw):
        raise RuntimeError('calibration rejected')
    monkeypatch.setattr(entry, 'run', fail)
    assert entry.main(['--vr-events']) == 1
    assert '"event": "failed"' in capsys.readouterr().out
