#!/usr/bin/env python3
"""L6 motor units -> DexForce EE commands; no arm, CAN or serial ownership."""
import argparse
import math
import time

JOINTS = ['T_MCP', 'T_CMC_YAW', 'IF_MCP_PITCH', 'MF_MCP_PITCH', 'RF_MCP_PITCH', 'LF_MCP_PITCH']


def convert_motor(values):
    if len(values) != 6 or any(not math.isfinite(v) or not 0 <= v <= 255 for v in values):
        raise ValueError('Expected six finite L6 motor values in [0,255]')
    # Inverse of the installed LinkerL6::setPosMapping, which writes
    # round((100-value)/100*255) to six consecutive device registers.
    return [(255.0 - float(v)) * 100.0 / 255.0 for v in values]


def main():
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile
    from sensor_msgs.msg import JointState
    from end_effector_interfaces.msg import EEJointControl, EEFeedback

    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='Publish only to preview topics; never to hand driver')
    args, ros_args = parser.parse_known_args()
    rclpy.init(args=ros_args)

    class Bridge(Node):
        def __init__(self):
            super().__init__('linkerhand_w1_l6_bridge')
            self.state = {s: {'target': None, 'received': 0.0, 'source_id': None, 'feedback': None,
                              'feedback_at': 0.0, 'output': None, 'active': False, 'latched': False}
                          for s in ['left', 'right']}
            self.publishers_by_side = {}
            self.warn_at = {}
            self.last_tick = time.monotonic()
            for side in self.state:
                topic = f'/linkerhand/{"preview" if args.preview else "w1"}/ee/{side}/command'
                self.publishers_by_side[side] = self.create_publisher(EEJointControl, topic, QoSProfile(depth=1))
                self.create_subscription(JointState, f'/linkerhand/glove/{side}/motor_cmd',
                                         lambda msg, s=side: self.on_glove(s, msg), QoSProfile(depth=1))
                self.create_subscription(EEFeedback, f'/feedback/ee/{side}',
                                         lambda msg, s=side: self.on_feedback(s, msg), QoSProfile(depth=1))
            self.create_timer(1 / 30, self.tick)
            self.get_logger().info('L6 adapter ready; waiting for calibrated fresh glove frames. '
                                   + ('PREVIEW ONLY' if args.preview else 'Physical hand output is enabled by this launch.'))

        def warn(self, key, message):
            now = time.monotonic()
            if now - self.warn_at.get(key, -100) > 4:
                self.get_logger().warning(message)
                self.warn_at[key] = now

        def on_glove(self, side, msg):
            st = self.state[side]
            try:
                session, sequence, received_at = msg.header.frame_id.split(':')
                age = time.monotonic() - float(received_at)
                if not session or int(sequence) < 1 or not 0 <= age <= 0.3:
                    raise ValueError('Glove frame is stale or from a different monotonic clock')
                source_id = (session, int(sequence))
                if source_id == st['source_id']:
                    return
                target = convert_motor(list(msg.position))
            except (ValueError, TypeError) as exc:
                self.warn(side + 'input', f'{side}: rejected input: {exc}')
                return
            st.update(target=target, received=float(received_at), source_id=source_id)

        def on_feedback(self, side, msg):
            st = self.state[side]
            joints = {j.name: j for j in msg.joint_states}
            valid = (msg.ee_name == 'Linker_L6' and msg.status in (0, 1)
                     and all(name in joints and joints[name].error_code == 0
                             and math.isfinite(joints[name].position)
                             and 0 <= joints[name].position <= 100 for name in JOINTS))
            if valid:
                st['feedback'] = [joints[name].position for name in JOINTS]
                st['feedback_at'] = time.monotonic()
            else:
                st['feedback_at'] = 0.0
                self.warn(side + 'feedback', f'{side}: hand feedback not ready (model={msg.ee_name}, status={msg.status}); no new targets')

        def tick(self):
            now = time.monotonic()
            dt = min(now - self.last_tick, 0.1)
            self.last_tick = now
            for side, st in self.state.items():
                if st['latched'] or st['target'] is None:
                    continue
                reason = None
                if now - st['received'] > 0.3:
                    reason = 'glove data expired'
                elif not args.preview and now - st['feedback_at'] > 1.5:
                    reason = 'valid L6 feedback unavailable'
                pub = self.publishers_by_side[side]
                if not args.preview:
                    if self.count_publishers(pub.topic_name) != 1:
                        reason = 'multiple command publishers'
                    elif self.count_subscribers(pub.topic_name) == 0:
                        reason = 'isolated hand driver not started'
                if reason:
                    if st['active']:
                        st['latched'] = True
                        self.get_logger().error(f'{side}: {reason}; follow paused. Restart glove command to re-engage.')
                    else:
                        self.warn(side + 'wait', f'{side}: waiting: {reason}')
                    continue
                if st['output'] is None:
                    st['output'] = list(st['target'] if args.preview else st['feedback'])
                step = 40.0 * dt
                st['output'] = [old + max(-step, min(step, target - old))
                                for old, target in zip(st['output'], st['target'])]
                msg = EEJointControl()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.mode = 0
                msg.joint_names = list(JOINTS)
                msg.values = list(st['output'])
                pub.publish(msg)
                st['active'] = True

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
