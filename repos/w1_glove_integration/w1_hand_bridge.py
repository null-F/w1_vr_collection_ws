#!/usr/bin/env python3
"""Forward original L6 glove targets using the DexForce message and position units."""
import argparse
import math
import os
from pathlib import Path
import sys
import time

JOINTS = ['T_MCP', 'T_CMC_YAW', 'IF_MCP_PITCH', 'MF_MCP_PITCH', 'RF_MCP_PITCH', 'LF_MCP_PITCH']


def convert_motor(values):
    if len(values) != 6 or any(not math.isfinite(v) or not 0 <= v <= 255 for v in values):
        raise ValueError('Expected six finite L6 motor values in [0,255]')
    # Inverse of the installed LinkerL6::setPosMapping; no motion filtering.
    return [(255.0 - float(v)) * 100.0 / 255.0 for v in values]


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'w1_vr_glove_integration'))
    from operator_state import settings, hand_enabled, publish, TTL
    single = settings()['mode'] == 'single'
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile
    from sensor_msgs.msg import JointState
    from end_effector_interfaces.msg import EEJointControl

    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='Publish only to preview topics; never to hand driver')
    args, ros_args = parser.parse_known_args()
    rclpy.init(args=ros_args)

    class Bridge(Node):
        def __init__(self):
            super().__init__('linkerhand_w1_l6_bridge')
            self.publishers_by_side = {}
            self.warn_at = {}
            self.session = os.environ.get('W1_GLOVE_SESSION')
            self.last_valid = {}
            self.heartbeat_at = 0.0
            for side in ['left', 'right']:
                topic = f'/linkerhand/{"preview" if args.preview else "w1"}/ee/{side}/command'
                self.publishers_by_side[side] = self.create_publisher(EEJointControl, topic, QoSProfile(depth=1))
                self.create_subscription(JointState, f'/linkerhand/glove/{side}/motor_cmd',
                                         lambda msg, s=side: self.on_glove(s, msg), QoSProfile(depth=1))
            self.get_logger().info('L6 format bridge ready; forwarding original glove targets without added motion limits. '
                                   + ('PREVIEW ONLY' if args.preview else 'Physical hand output is enabled by this launch.'))

        def on_glove(self, side, msg):
            try:
                values = convert_motor(list(msg.position))
            except (ValueError, TypeError) as exc:
                now = time.monotonic()
                if now - self.warn_at.get(side, -100) > 4:
                    self.get_logger().warning(f'{side}: invalid L6 target: {exc}')
                    self.warn_at[side] = now
                return
            if single:
                stamp = msg.header.stamp
                ns = stamp.sec * 10**9 + stamp.nanosec
                now = time.monotonic()
                if not self.session or not 0 <= time.time_ns() - ns < TTL * 1e9:
                    return
                self.last_valid[side] = now
                if (len(self.last_valid) == 2 and now - min(self.last_valid.values()) < TTL / 2
                        and now - self.heartbeat_at >= 0.03):
                    try:
                        publish('hands.json', session=self.session)
                    except FileNotFoundError:
                        return
                    self.heartbeat_at = now
                if not hand_enabled(ns):
                    return
            command = EEJointControl()
            command.header = msg.header
            command.mode = 0
            command.joint_names = list(JOINTS)
            command.values = values
            self.publishers_by_side[side].publish(command)

    node = Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
