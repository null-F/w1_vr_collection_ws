"""Saved whole-body/L6 ready return, executed on the PoseServer main loop."""
import asyncio
import json
import math
import threading
import time

import numpy as np
import operator_state as signals


def positions(values, names, label, low=None, high=None):
    if not isinstance(values, dict) or set(values) != set(names):
        raise ValueError(label + ': incomplete or unexpected joints')
    result = np.array([values[n] for n in names], dtype=float)
    if any(type(values[n]) not in (int, float) for n in names) or not np.isfinite(result).all():
        raise ValueError(label + ': non-finite positions')
    if low is not None and (np.any(result < low) or np.any(result > high)):
        raise ValueError(label + ': positions outside limits')
    return result


HAND_NAMES = ('T_MCP', 'T_CMC_YAW', 'IF_MCP_PITCH', 'MF_MCP_PITCH', 'RF_MCP_PITCH', 'LF_MCP_PITCH')


def load_target(path, body_names):
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or data.get('return_control', {}).get('enabled') is not True:
        raise ValueError('ready return disabled or unsupported schema')
    if data['body']['position_unit'] != 'rad':
        raise ValueError('body positions must be radians')
    body = positions(data['body']['joint_positions'], body_names, 'body')
    hands = {}
    for side in ('left', 'right'):
        hand = data['hands'][side]
        if hand['ee_name'] != 'Linker_L6' or hand['position_unit'] != 'dexe_l6_0_100':
            raise ValueError('ready return requires DexForce Linker_L6 hand units')
        hands[side] = positions(hand['joint_positions'], HAND_NAMES, side, 0, 100)
    return body, hands


def trajectory(start, target, min_duration=6.0, period=0.02):
    # Quintic time scaling: zero endpoint velocity/acceleration; peak ds/dt=1.875/T.
    delta = abs(target - start)
    limits = np.array([0.2] * (len(start) - 12) + [15.0] * 12)
    duration = max(min_duration, float(np.max(1.875 * delta / limits)))
    if duration > 60:
        raise ValueError('return exceeds maximum duration; inspect current posture')
    steps = max(2, math.ceil(duration / period) + 1)
    u = np.linspace(0, 1, steps)
    smooth = 10*u**3 - 15*u**4 + 6*u**5
    return start + smooth[:, None]*(target - start), duration/(steps - 1)


class Feedback:
    def __init__(self):
        from rclpy.node import Node
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import JointState
        from std_msgs.msg import String
        from end_effector_interfaces.msg import EEFeedback, EEJointControl
        self.node = Node('linkerhand_ready_feedback')
        self.lock, self.values = threading.Lock(), {}
        self.subscriptions = []
        for key, topic, typ in (
            ('body', '/feedback/joint', JointState),
            ('left', '/feedback/ee/left', EEFeedback),
            ('right', '/feedback/ee/right', EEFeedback),
            ('status', '/feedback/robot_status', String),
        ):
            self.subscriptions.append(self.node.create_subscription(
                typ, topic, lambda msg, k=key: self.receive(k, msg), qos_profile_sensor_data))
        self.publishers = {s: self.node.create_publisher(
            EEJointControl, f'/linkerhand/w1/ee/{s}/command', 1) for s in ('left', 'right')}
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def receive(self, key, message):
        with self.lock:
            self.values[key] = (time.monotonic(), message)

    def snapshot(self, body_names):
        with self.lock:
            values = dict(self.values)
        now = time.monotonic()
        if any(k not in values or not 0 <= now - values[k][0] < signals.TTL
               for k in ('body', 'left', 'right', 'status')):
            raise ValueError('ready feedback stale or missing')
        status = json.loads(values['status'][1].data)
        if status.get('safety_ready') is not True or status.get('health') != 'ok':
            raise ValueError('robot safety status not ready')
        body_msg = values['body'][1]
        if len(body_msg.name) != len(body_msg.position) or len(set(body_msg.name)) != len(body_msg.name):
            raise ValueError('invalid body feedback')
        body = positions(dict(zip(body_msg.name, body_msg.position)), body_names, 'body feedback')
        hands = {}
        for side in ('left', 'right'):
            msg = values[side][1]
            if msg.ee_name != 'Linker_L6' or msg.status != 0 or any(j.error_code or j.status for j in msg.joint_states):
                raise ValueError(side + ' hand fault or unexpected device')
            if len(msg.joint_states) != 6:
                raise ValueError(side + ' incomplete hand feedback')
            hands[side] = positions({j.name: j.position for j in msg.joint_states}, HAND_NAMES, side, 0, 100)
        return np.concatenate((body, hands['left'], hands['right']))

    def publish_hands(self, row, body_count):
        from end_effector_interfaces.msg import EEJointControl
        for index, side in enumerate(('left', 'right')):
            msg = EEJointControl()
            msg.header.stamp = self.node.get_clock().now().to_msg()
            msg.mode = 0
            msg.joint_names = list(HAND_NAMES)
            msg.values = row[body_count + index*6:body_count + (index+1)*6].tolist()
            self.publishers[side].publish(msg)

    def close(self):
        self.executor.shutdown(timeout_sec=2)
        self.thread.join(timeout=2)
        self.node.destroy_node()


class ReadyReturn:
    def __init__(self, gate):
        self.gate, self.pose = gate, gate.pose
        self.active, self.task, self.cancelled = False, None, False
        self.names = list(self.pose.config.robot.ros2_to_urdf_map)
        self.path = signals.ROOT / 'config/w1/ready_pose.json'
        self.feedback = Feedback()
        self.native_active = self.pose.auto_return_service.is_active
        self.pose.auto_return_service.is_active = lambda: self.active or self.native_active()
        # Router lambdas resolve the handler attribute for every incoming request.
        async def handle(ws, client_addr, **kwargs):
            return await self.pose._run_on_main_loop(self.request())
        self.pose.auto_return_service.handler.handle_return_to_position = handle
        print('LINKERHAND_READY_RETURN long-Y uses config/w1/ready_pose.json (body + both L6 hands)', flush=True)

    async def status(self, state, message='', code=None):
        from src.backend.core.protocols import RobotStatusMessage
        payload = dict(type='return_to_position_status', status=state, message=message)
        if code:
            payload['error_code'] = code
        await self.pose._send_low_freq_message(RobotStatusMessage(message=payload))

    async def request(self):
        async with self.gate.lock:
            if self.active or self.native_active():
                # Do not send a failure that clears the UI's pending flag for an active return.
                await self.status('started', 'Ready 回位正在执行')
                return
            try:
                body, hands = load_target(self.path, self.names)
                if not self.gate.permitted():
                    raise ValueError('robot control state does not permit ready return')
                target = np.concatenate((body, hands['left'], hands['right']))
                self.feedback.snapshot(self.names)
                self.check_body(body)
            except Exception as exc:
                await self.status('failed', str(exc), 'ready_not_available')
                return
            self.cancelled = False
            try:
                # Complete native release before claiming auto-return priority; otherwise
                # its early-return branch skips clearing the previous teleop caches.
                await self.gate.release()
                self.active = True
                self.pose.joycon.publish_stop()
                self.pose.state.teleop_on = False
                self.pose._reset_incremental_anchor()
                self.task = asyncio.create_task(self.run(target))
            except BaseException:
                self.active = False
                raise
        await self.status('started', '正在恢复 Ready 姿态')

    def check_body(self, body):
        solver = self.pose.dex_w1
        if solver.fcl_checker is None:
            raise ValueError('collision checker unavailable')
        model = solver.robot.model
        for index, urdf in enumerate(self.pose.config.robot.ros2_to_urdf_map.values()):
            joint = model.joints[model.getJointId(urdf)]
            if joint.nq != 1 or not model.lowerPositionLimit[joint.idx_q] <= body[index] <= model.upperPositionLimit[joint.idx_q]:
                raise ValueError('body joint outside limits: ' + self.names[index])
        hit, pairs, info = solver.check_collision(body)
        if hit or info.get('collision_check_skipped'):
            raise ValueError('return path collision or unchecked geometry: ' + str(pairs))

    def guard(self):
        if self.cancelled or time.monotonic() - self.gate.last_frame >= signals.TTL:
            raise ValueError('VR input disconnected or return cancelled')
        if self.pose.error_monitor.has_error()[0] or self.pose.chassis_monitor.is_enabled() is False:
            raise ValueError('robot fault or chassis disabled during return')
        if (self.pose.config.robot.requires_motor_op_check and not self.pose.error_monitor.is_all_motor_op(
                self.pose.error_monitor.get_latest_status() or {})):
            raise ValueError('motors not operational')
        return self.feedback.snapshot(self.names)

    def publish(self, row):
        self.pose.joint_controller.send_full_joint_position(dict(zip(self.names, row[:len(self.names)])), self.pose.state.frame_id)
        self.feedback.publish_hands(row, len(self.names))
        self.pose.state.frame_id += 1
        self.pose.last_sent_cmd = dict(zip(self.names, row[:len(self.names)]))

    def tracking_error(self, actual, expected, limits):
        errors = abs(actual - expected)
        index = int(np.argmax(errors / limits))
        labels = self.names + [side + '/' + name for side in ('left', 'right') for name in HAND_NAMES]
        unit = 'rad' if index < len(self.names) else 'L6_0_100'
        return f'{labels[index]}: error={errors[index]:.4f} {unit}, limit={limits[index]:.4f}'

    async def wait_for_tracking(self, previous, period, budget):
        """Hold the last safe command while lagging, without advancing trajectory time."""
        soft = np.array([0.12]*len(self.names) + [8.0]*12)
        hard = np.array([0.35]*len(self.names) + [25.0]*12)
        started = time.monotonic()
        waiting = False
        while True:
            actual = self.guard()
            error = abs(actual - previous)
            if np.any(error > hard):
                raise ValueError('return tracking error too large: ' + self.tracking_error(actual, previous, hard))
            self.check_body(actual[:len(self.names)])
            if np.all(error <= soft):
                return max(0.0, time.monotonic() - started) if waiting else 0.0
            if not waiting:
                print('LINKERHAND_READY_RETURN waiting for tracking: ' +
                      self.tracking_error(actual, previous, soft), flush=True)
                waiting = True
            if time.monotonic() - started >= min(5.0, budget):
                raise ValueError('return tracking did not recover: ' + self.tracking_error(actual, previous, soft))
            self.check_body(previous[:len(self.names)])
            self.publish(previous)
            await asyncio.sleep(period)

    async def run(self, target):
        success = False
        try:
            # Drain queued glove commands and permit stale VR enable acknowledgements to expire.
            await asyncio.sleep(signals.TTL + 0.05)
            start = self.guard()
            rows, period = trajectory(start, target)
            # Check every planned point before the first command, yielding to pose/health handling.
            for index, row in enumerate(rows):
                self.check_body(row[:len(self.names)])
                if index % 8 == 0:
                    self.guard()
                    await asyncio.sleep(0)
            tolerances = np.array([0.035]*len(self.names) + [3.0]*12)
            if np.any(abs(self.guard() - start) > tolerances):
                raise ValueError('robot moved during return preflight; retry')
            previous = start
            waiting_budget = 30.0
            for row in rows:
                waiting_budget -= await self.wait_for_tracking(previous, period, waiting_budget)
                self.check_body(row[:len(self.names)])
                self.publish(row)
                previous = row
                # Stretch the trajectory if computation is slow; never catch up with a burst.
                await asyncio.sleep(period)
            deadline, stable_since = time.monotonic() + 5, None
            while time.monotonic() < deadline:
                actual = self.guard()
                self.check_body(actual[:len(self.names)])
                self.check_body(target[:len(self.names)])
                if np.all(abs(actual - target) <= tolerances):
                    stable_since = stable_since or time.monotonic()
                    if time.monotonic() - stable_since >= 0.3:
                        success = True
                        break
                else:
                    stable_since = None
                self.publish(target)
                await asyncio.sleep(period)
            if not success:
                raise ValueError('ready position not reached before timeout')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.status('failed', str(exc), 'ready_return_failed')
            print('LINKERHAND_READY_RETURN failed: ' + str(exc), flush=True)
        finally:
            # Never restore an old pedal request; only a fresh C edge may re-enable follow.
            self.pose.state.teleop_on = False
            self.pose.state.await_enable_rearm = True
            self.pose._reset_incremental_anchor()
            self.pose.joycon.publish_stop()
            await self.gate.release()
            self.active = False
            self.task = None
        if success:
            await self.status('completed', '已恢复 Ready 姿态，请重新踩跟随踏板 开启跟随')

    async def close(self):
        self.cancelled = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self.feedback.close)
