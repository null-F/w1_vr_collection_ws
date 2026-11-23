#!/usr/bin/env python3
"""Start vendor chassis sensors or check their live streams on PC1."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rosidl_runtime_py.utilities import get_message
import yaml

HERE = Path(__file__).resolve().parent
GROUPS = [
    ('dexe_sensors_launch', 'orbbec_nodes.launch.py',
     {'/orbbec_front_camera', '/orbbec_rear_camera'}),
    ('lidar_sensor', 'dual_udp_lidar.launch', {'/bluesea_node'}),
    ('dexe_sensor_process', 'front_p2c.launch.py', {'/front_rgbd_to_pointcloud'}),
    ('dexe_sensor_process', 'rear_p2c.launch.py', {'/rear_rgbd_to_pointcloud'}),
]


def spin_for(node, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.05)


def check(node, seconds):
    config = yaml.safe_load((HERE / 'topics.yaml').read_text())
    targets = [t for t in config['continuous'] if t.startswith(('/orbbec/', '/laser_scan/'))]
    graph = dict(node.get_topic_names_and_types())
    records = {t: {'count': 0, 'max_gap_sec': 0} for t in targets}
    subscriptions = []
    for topic in targets:
        row = records[topic]
        row['publishers'] = len(node.get_publishers_info_by_topic(topic))
        types = graph.get(topic, [])
        if len(types) != 1:
            row['error'] = 'Missing or ambiguous message type'
            continue
        last = [None]
        def receive(raw, row=row, last=last):
            now = time.monotonic()
            if last[0] is not None:
                row['max_gap_sec'] = max(row['max_gap_sec'], now - last[0])
            last[0] = now
            row['count'] += 1
        subscriptions.append(node.create_subscription(
            get_message(types[0]), topic, receive, qos_profile_sensor_data, raw=True))
    started = time.monotonic()
    spin_for(node, seconds)
    duration = time.monotonic() - started
    for row in records.values():
        row['hz'] = round(row['count'] / duration, 2)
        row['max_gap_sec'] = round(row['max_gap_sec'], 3) if row['count'] > 1 else None
    good = all(row['count'] > 0 for row in records.values())
    print(json.dumps({'all_streams_received': good, 'seconds': duration,
                      'topics': records}, ensure_ascii=False, indent=2))
    return 0 if good else 1


def serve(node):
    runtime = Path(os.environ.get('W1_MCAP_RUNTIME', '/home/dexforce/linkerhand/runtime'))
    runtime.mkdir(parents=True, exist_ok=True)
    children = []
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    with (runtime / 'chassis_sensors.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        present = {'/' + name.strip('/') for name in node.get_node_names()}
        # Complete discovery before starting any group, including partial external groups.
        for package, launch, names in GROUPS:
            if present & names and not names <= present:
                raise RuntimeError(f'Partial external sensor group {launch}: {present & names}')
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, stop)
        try:
            for package, launch, names in GROUPS:
                if stopping:
                    return 0
                if names <= present:
                    print('Using existing sensor group:', launch, flush=True)
                    continue
                print('Starting sensor group:', launch, flush=True)
                children.append(subprocess.Popen(
                    ['ros2', 'launch', package, launch], start_new_session=True))
            while not stopping:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError('Sensor launch process exited; inspect service logs')
                time.sleep(0.1)
            return 0
        finally:
            # Signal only dedicated groups created by this supervisor. Reused nodes keep running.
            for child in children:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGINT)
            deadline = time.monotonic() + 10
            for child in children:
                try:
                    child.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['serve', 'check'])
    parser.add_argument('--seconds', type=float, default=15)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('--seconds must be between 1 and 300')
    rclpy.init(args=[])
    node = Node('w1_collection_chassis_sensors', enable_rosout=False)
    try:
        spin_for(node, 4)
        return check(node, args.seconds) if args.command == 'check' else serve(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
