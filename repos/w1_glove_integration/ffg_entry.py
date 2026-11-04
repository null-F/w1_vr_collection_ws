#!/usr/bin/env python3
"""W1-only composition of the pinned FFG SDK; no hand driver or mapping fork.

The SDK reads/maps gloves. This adapter owns W1 device selection, topic isolation,
calibration events and lifecycle. LinkerZ and force feedback are not used here.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import time

from glove_ports import checked_glove_ports

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'repos/w1_vr_glove_integration'))
from local_voice import play_text

SDK_ROOT = ROOT / 'repos/linkerbot_ffg_ros2'
SIDES = ('left', 'right')
EVENT_PREFIX = 'LINKERHAND_GLOVE_EVENT '
REMAPS = [
    '--ros-args',
    '-r', '/cb_left_hand_control_cmd:=/linkerhand/glove/left/motor_cmd',
    '-r', '/cb_right_hand_control_cmd:=/linkerhand/glove/right/motor_cmd',
]


def load_sdk():
    """Prefer the vendored package, not an independently installed SDK version."""
    package_root = SDK_ROOT / 'src/linkerbot_ffg_ros'
    sys.path.insert(0, str(package_root))
    import linkerbot_ffg_ros
    if not Path(linkerbot_ffg_ros.__file__).resolve().is_relative_to(package_root):
        raise RuntimeError('A different linkerbot_ffg_ros package is already loaded')
    return json.loads((SDK_ROOT / 'UPSTREAM_VERSION.json').read_text())


def load_profile():
    from linkerbot_ffg_ros.settings import load_yaml, resolve_settings
    settings = resolve_settings(
        load_yaml(ROOT / 'config/w1/glove_ffg.yaml'),
        cli_calib_dir=ROOT / 'runtime/calibration/glove_ffg',
    )
    if settings.robot != 'l6' or settings.hand_sdk != 'LinkerH':
        raise ValueError('W1 requires robot=l6 and hand_sdk=LinkerH')
    if settings.force.enabled or settings.serial.auto_scan:
        raise ValueError('W1 requires force feedback and broad serial scanning OFF')
    return settings


def serial_targets(settings, ports):
    if len(ports) != 2 or len(set(ports)) != 2:
        raise ValueError('Exactly two distinct CH340 candidate ports are required')
    return replace(settings.serial, auto_scan=False,
                   left_port=ports[0], right_port=ports[1])


def scan_pair(settings):
    """Only open USB-qualified candidates; require a complete identified pair."""
    from linkerbot_ffg_ros.app.calibrate_glove import explicit_serial_targets
    from linkerbot_ffg_ros.glove_ffg import GloveReader
    serial = serial_targets(settings, checked_glove_ports())
    readers = []
    gloves = {}
    try:
        for port, baud in explicit_serial_targets(serial):
            reader = GloveReader()
            readers.append(reader)
            if not reader.open(port, baud) or not reader.query_version():
                raise RuntimeError(f'Cannot identify FFG glove: {port}@{baud}')
            if reader.side not in SIDES or reader.side in gloves:
                raise RuntimeError(f'Invalid/duplicate glove side: {reader.side} on {port}')
            gloves[reader.side] = (reader, port, baud)
        if set(gloves) != set(SIDES):
            raise RuntimeError('Both left and right gloves must be identified before calibration')
        return gloves
    except BaseException:
        with ExitStack() as cleanup:
            for reader in readers:
                cleanup.callback(reader.close)
        raise


def emit(event, **fields):
    print(EVENT_PREFIX + json.dumps(dict(event=event, **fields), ensure_ascii=False), flush=True)


def speak(text, cancel=None):
    """Play a packaged PC1 prompt. No PC2/cloud or runtime synthesis."""
    play_text(text, cancel)


def speak_while_polling(readers, text, speaker=None):
    """Keep synchronous SDK readers on their owner thread during local playback.

    A stopped/failed calibration cancels and reaps its audio subprocess before
    the next session can start; sampling only begins after successful playback.
    """
    finished = threading.Event()
    cancel = threading.Event()
    errors = []

    def announce():
        try:
            if speaker is None:
                speak(text, cancel)
            else:
                speaker(text)  # explicit test/embedding hook
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=announce, daemon=True, name='w1-calibration-voice')
    worker.start()
    try:
        while not finished.is_set():
            for reader in readers.values():
                reader.poll()
            finished.wait(1.0 / 30.0)
        if errors:
            raise errors[0]
    finally:
        cancel.set()
        worker.join(timeout=2)


@contextmanager
def calibration_events(enabled):
    """Observe the existing five-pose capture; preserve its stability algorithm."""
    from linkerbot_ffg_ros.app import calibrate_glove
    original = calibrate_glove.capture_pose_multi

    def observed(readers, pose, **kwargs):
        emit('stage', stage=pose.key)
        speak_while_polling(readers, '请双手' + pose.instruction + '，并保持。')
        return original(readers, pose, **kwargs)

    if enabled:
        calibrate_glove.capture_pose_multi = observed
    try:
        yield
    finally:
        calibrate_glove.capture_pose_multi = original


def build_mappers(paths, settings):
    """Validate both calibrations before creating any ROS command publisher."""
    from linkerbot_ffg_ros.calibration import load_calibration
    from linkerbot_ffg_ros.calibration.poses import pose_keys
    from linkerbot_ffg_ros.mappers.l6 import L6Mapper
    from linkerbot_ffg_ros.teleop.types import GloveFrame
    mappers = {}
    for side in SIDES:
        doc = load_calibration(paths[side])
        if doc['meta']['side'] != side:
            raise ValueError(f'Calibration side mismatch for {side}')
        if not set(pose_keys()).issubset(doc['poses']):
            raise ValueError(f'{side}: five-pose FFG calibration is required; recalibrate')
        mapper = L6Mapper.from_calibration_doc(
            doc, side=side, smooth=settings.smooth,
            smooth_alpha=settings.smooth_alpha, smooth_max_step=settings.smooth_max_step,
        )
        # Validate finite base/ranges without priming the output smoother.
        mapper.estimator.estimate(GloveFrame(
            side=side, joints_deg=list(mapper.estimator.base), timestamp=0.0,
        ))
        mappers[side] = mapper
    return mappers


def run(settings, *, reuse_calibration=False, vr_events=False):
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import ExternalShutdownException
    from linkerbot_ffg_ros.app.calibrate_glove import run_calibration
    from linkerbot_ffg_ros.calibration import find_latest_calibration
    from linkerbot_ffg_ros.sinks.ros_joint_state import RosHandControlSink
    from linkerbot_ffg_ros.teleop.pipeline import HandPipeline

    paths = None
    if reuse_calibration:
        paths = {side: find_latest_calibration(side, settings.calib_dir) for side in SIDES}
        build_mappers(paths, settings)  # fail before opening serial if cache is invalid

    gloves = {}
    node = None
    sink = None
    ros_started = False
    try:
        gloves = scan_pair(settings)
        if paths is None:
            with calibration_events(vr_events):
                paths = run_calibration(gloves, output=settings.calib_dir, close_on_exit=False)
        mappers = build_mappers(paths, settings)
        rclpy.init(args=REMAPS)
        ros_started = True
        node = Node('linkerhand_w1_ffg_teleop')
        sink = RosHandControlSink(node)
        pipelines = {side: HandPipeline(gloves[side][0], mappers[side], sink,
                                       logger=node.get_logger()) for side in SIDES}
        node.get_logger().info('W1 FFG: L6, isolated topics, force feedback OFF; '
                               f'{settings.rate_hz:g} Hz; calibration={settings.calib_dir}')
        seen = set()
        ready = False
        period = 1.0 / settings.rate_hz
        deadline = time.monotonic()
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.0)
            for side, pipeline in pipelines.items():
                if pipeline.tick() is not None:
                    seen.add(side)
            if not ready and seen == set(SIDES):
                ready = True
                if vr_events:
                    emit('ready')
            deadline = max(deadline + period, time.monotonic())
            while rclpy.ok() and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=max(0.0, deadline - time.monotonic()))
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # ExitStack attempts every close even if another resource's cleanup fails.
        with ExitStack() as cleanup:
            if ros_started:
                cleanup.callback(lambda: rclpy.shutdown() if rclpy.ok() else None)
            if node is not None:
                cleanup.callback(node.destroy_node)
            if sink is not None:
                cleanup.callback(sink.close)
            for reader, _, _ in gloves.values():
                cleanup.callback(reader.close)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check imports/profile only; no devices, ROS node or writes')
    parser.add_argument('--reuse-calibration', action='store_true')
    parser.add_argument('--vr-events', action='store_true')
    args = parser.parse_args(argv)
    try:
        version = load_sdk()
        settings = load_profile()
        import rclpy
        import numpy
        import serial
        from sensor_msgs.msg import JointState  # standard ROS messages only, no LinkerZ build
        from linkerbot_ffg_ros.glove_ffg import GloveReader
        from linkerbot_ffg_ros.mappers.l6 import L6Mapper
        from linkerbot_ffg_ros.app.calibrate_glove import run_calibration
        if int(numpy.__version__.split('.')[0]) >= 2:
            raise RuntimeError('Pinned FFG SDK requires numpy<2; use a separate compatible glove environment')
        if args.check:
            print(json.dumps({'sdk_commit': version['commit'], 'python': sys.version.split()[0],
                              'robot': settings.robot, 'hand_sdk': settings.hand_sdk,
                              'rate_hz': settings.rate_hz, 'force_feedback': settings.force.enabled,
                              'calib_dir': str(settings.calib_dir),
                              'note': 'Import/profile check only; not Humble or hardware acceptance'},
                             ensure_ascii=False, indent=2))
            return 0
        return run(settings, reuse_calibration=args.reuse_calibration, vr_events=args.vr_events)
    except Exception as exc:
        if args.vr_events:
            emit('failed', error=str(exc))
        print(f'W1 FFG startup/runtime failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
