#!/usr/bin/env python3
"""Keep the vendor IMU driver running; reuse an already running instance."""
import os
from pathlib import Path
import signal
import subprocess
import time

DRIVER = '/home/dexforce/w1/install/imu/lib/imu/talker'


def running():
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if os.readlink(entry / 'exe') == DRIVER:
                return True
        except OSError:
            pass
    return False


def main():
    stopping = False
    child = None

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            if child is not None and child.poll() is not None:
                print(f'IMU exited: {child.returncode}; retrying', flush=True)
                child = None
            if child is None and Path('/dev/ttyIMU').exists() and not running():
                print('Starting vendor IMU driver', flush=True)
                child = subprocess.Popen([DRIVER])
            time.sleep(2)
    finally:
        # Never stop a driver started by the vendor or an operator.
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
