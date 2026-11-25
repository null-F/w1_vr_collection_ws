#!/usr/bin/env python3
"""Own the PC2 F710 input/control pair; wait for USB, reinitialize after reconnect."""
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import time

JOY = '/opt/ros/humble/lib/joy/joy_node'
CONTROL = '/home/dexforce/w1/install/mobile_joy_control/lib/mobile_joy_control/mobile_joy_control'
PARAMS = '/home/dexforce/w1/install/mobile_joy_control/share/mobile_joy_control/config/params.yaml'
DEVICE_NAME = 'Logitech Cordless RumblePad 2'


def find_device(root=Path('/sys/class/input'), dev=Path('/dev/input')):
    matches = []
    for item in root.glob('js*'):
        try:
            if ((item/'device/id/vendor').read_text().strip() == '046d' and
                    (item/'device/id/product').read_text().strip() == 'c219'):
                device = dev/item.name
                stat = device.stat()
                matches.append((device, (str(item.resolve()), stat.st_rdev, stat.st_ctime_ns)))
        except OSError:
            continue
    return matches[0] if len(matches) == 1 else None


def neutral(device):
    """Only start a fresh control session with all buttons released/sticks centered."""
    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    axes, buttons = {}, {}
    try:
        end = time.monotonic()+.2
        while time.monotonic() < end:
            if not select.select([fd], [], [], .025)[0]:
                continue
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if not data:
                return False
            for offset in range(0, len(data), 8):
                _, value, kind, index = struct.unpack('IhBB', data[offset:offset+8])
                if kind & 127 == 1:
                    buttons[index] = value
                elif kind & 127 == 2:
                    axes[index] = value
        return len(buttons) == 12 and len(axes) == 6 and not any(buttons.values()) and all(abs(v) < 6500 for v in axes.values())
    finally:
        os.close(fd)


def commands():
    return [
        [JOY, '--ros-args', '-r', '__node:=pc2_joy_node', '-p', 'device_name:='+DEVICE_NAME,
         '-p', 'deadzone:=0.3', '-p', 'autorepeat_rate:=20.0'],
        [CONTROL, '--ros-args', '-r', '__node:=mobile_joy_control', '--params-file', PARAMS],
    ]


def stop_children(children):
    for process in children:
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    deadline = time.monotonic()+3
    for process in children:
        try:
            process.wait(timeout=max(.01, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)


def main():
    import rclpy
    from geometry_msgs.msg import Twist
    rclpy.init()
    node = rclpy.create_node('linkerhand_pc2_gamepad_supervisor')
    publisher = node.create_publisher(Twist, '/control/cmd_vel_joy', 1)
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    children, identity = [], None
    last_log = 0
    def halt():
        nonlocal children, identity
        if children:
            stop_children(children)
            # Explicit neutral output when this input source is withdrawn; never drive the base.
            for _ in range(3):
                if rclpy.ok():
                    publisher.publish(Twist())
                    rclpy.spin_once(node, timeout_sec=.05)
        children, identity = [], None
    try:
        print('PC2 gamepad supervisor ready; waiting for F710 DInput USB receiver', flush=True)
        while not stopping and rclpy.ok():
            device = find_device()
            key = device[1] if device else None
            if children and (key != identity or any(p.poll() is not None for p in children)):
                print('Receiver disconnected or child exited; stopping pair and requiring fresh initialization', flush=True)
                halt()
            if device and not children:
                try:
                    if neutral(device[0]):
                        # Track each successful spawn so a partial failure is cleaned up.
                        for command in commands():
                            children.append(subprocess.Popen(command, start_new_session=True))
                        identity = key
                        print('F710 connected: input + mapped control started; initialize sticks before enabling', flush=True)
                    elif time.monotonic()-last_log > 15:
                        print('Waiting: wake the gamepad, release all buttons and center both sticks', flush=True)
                        last_log = time.monotonic()
                except OSError as exc:
                    print('Gamepad startup retry: '+str(exc), flush=True)
                    halt()
            if not device and time.monotonic()-last_log > 15:
                print('Waiting for F710 DInput (046d:c219); receiver absent or mode differs (XInput is not enabled)', flush=True)
                last_log = time.monotonic()
            rclpy.spin_once(node, timeout_sec=.2)
    finally:
        halt()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
