"""Adapt controller grip *level* before the audited PoseServer parses each frame."""
import asyncio
from dataclasses import replace
import math
import time

import operator_state as signals
from operator_journal import event


def valid_pose(msg):
    if msg.mode not in (None, 'controller') or msg.left_hand is not None or msg.right_hand is not None:
        return False
    positions = []
    try:
        for pose in (msg.head, msg.left_controller, msg.right_controller):
            xyz = [pose['position'][k] for k in 'xyz']
            quat = [pose['quaternion'][k] for k in 'xyzw']
            if (not all(type(v) in (int, float) and math.isfinite(v) for v in xyz + quat)
                    or xyz[1] <= 0 or not 0.99 <= math.hypot(*quat) <= 1.01):
                return False
            positions.append(xyz)
        return all(math.dist(positions[0], wrist) < 1.2 for wrist in positions[1:])
    except (TypeError, KeyError, OverflowError):
        return False


def grips(msg, enabled):
    def buttons(original):
        values = dict(original or {}) if enabled else {}
        values.update(Two=enabled, ThumbstickPress=False)
        return values
    return replace(msg, left_buttonState=buttons(msg.left_buttonState),
                   right_buttonState=buttons(msg.right_buttonState))


class ReleaseSocket:
    """The native exit path sends a UI notification before clearing motion caches."""
    def __init__(self, ws):
        self.ws = ws

    async def send(self, value):
        try:
            await asyncio.wait_for(self.ws.send(value), timeout=0.05)
        except Exception:
            pass  # Also finish the native release sequence when the owner disconnected.


class PoseGate:
    def __init__(self, pose):
        self.pose = pose
        self.original = pose.handle_pose
        self.lock = asyncio.Lock()
        self.ws = self.frame = self.session = self.press = None
        self.last_frame = self.ready_since = 0
        self.started_wall_ns = None
        self.watch = None
        self.reported = object()

    def permitted(self):
        p = self.pose
        return (not p.state.calibration_mode and not p.state.await_enable_rearm
                and not (p.auto_return_priority and p.auto_return_service.is_active())
                and not p.error_monitor.has_error()[0] and p.chassis_monitor.is_enabled() is not False
                and (not p.config.robot.requires_motor_op_check or
                     p.error_monitor.is_all_motor_op(p.error_monitor.get_latest_status() or {})))

    def acknowledge(self, press):
        try:
            signals.publish('vr.json', press=press, session=self.session if press else None,
                            started_wall_ns=self.started_wall_ns)
        except FileNotFoundError:
            if press:
                raise
        if self.reported != press:
            event('follow', dict(enabled=bool(press), press=press, session=self.session))
            self.reported = press

    async def release(self):
        self.press = None
        self.session = None
        try:
            self.acknowledge(None)
        finally:
            if self.frame is not None and self.pose.state.teleop_on:
                self.pose.joycon.publish_stop()
                await self.original(ReleaseSocket(self.ws), grips(self.frame, False))

    async def handle(self, ws, msg):
        received = time.monotonic()
        async with self.lock:
            if time.monotonic() - received >= signals.TTL:
                return
            if self.ws is not ws and self.ws is not None and received - self.last_frame < signals.TTL:
                return
            if self.ws is not ws or received - self.last_frame >= signals.TTL:
                await self.release()
            self.ws, self.last_frame = ws, received
            if not valid_pose(msg):
                await self.release()
                return
            self.frame = msg
            if self.watch is None or self.watch.done():
                self.watch = asyncio.create_task(self.watchdog())
            try:
                session = signals.ready_session()
                pedal = signals.fresh('pedal.json')
                if not session or not pedal.get('connected') or not self.permitted():
                    await self.release()
                    # Pass real released frames to native auto-return rearm only after foot release.
                    if not pedal.get('press') and not self.pose.state.teleop_on:
                        await self.original(ws, grips(msg, False))
                    return
                if self.session != session:
                    await self.release()
                    self.session, self.ready_since = session, received
                press = pedal.get('press')
                enabled = bool(press and pedal['since'] >= self.ready_since)
                if self.press and press != self.press:
                    await self.release()
                    return
                await self.original(ws, grips(msg, enabled))
                if enabled and self.pose.state.teleop_on:
                    if not self.press:
                        self.started_wall_ns = time.time_ns()
                    if (time.monotonic() - received >= signals.TTL or
                            signals.fresh('pedal.json').get('press') != press or
                            signals.ready_session() != session or not self.permitted()):
                        await self.release()
                        return
                    self.press = press
                    self.acknowledge(press)
                elif enabled:
                    await self.release()  # Vendor rejected activation. Require a fresh press.
            except BaseException:
                await self.release()
                raise

    async def watchdog(self):
        while True:
            await asyncio.sleep(0.04)
            async with self.lock:
                if time.monotonic() - self.last_frame >= signals.TTL:
                    await self.release()
                    return
                if self.press and (signals.fresh('pedal.json').get('press') != self.press
                                   or signals.ready_session() != self.session or not self.permitted()):
                    await self.release()

    async def disconnect(self, ws):
        async with self.lock:
            if self.ws is ws:
                await self.release()
                self.ws = self.frame = None

    async def close(self):
        if self.watch:
            self.watch.cancel()
        await self.disconnect(self.ws)
