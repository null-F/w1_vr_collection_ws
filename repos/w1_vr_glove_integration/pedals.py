#!/usr/bin/env python3
"""Read one configured Linux evdev device on PC1. Learn mode only prints events."""
import argparse
import fcntl
import os
from pathlib import Path
import select
import struct
import subprocess
import threading
import time
import uuid

from operator_state import settings, publish, TTL
from operator_journal import event
from patch_runtime import send_toggle
from local_voice import Voice

HERE = Path(__file__).resolve().parent
EVENT = struct.Struct('@llHHi')
EV_KEY, SYN_DROPPED = 1, 3


def key_bitmap(fd):
    # EVIOCGKEY, Linux KEY_MAX = 0x2ff.
    bits = bytearray(96)
    fcntl.ioctl(fd, 0x80604518, bits, True)
    return {i for i in range(len(bits) * 8) if bits[i // 8] & (1 << (i % 8))}


def events(fd):
    data = os.read(fd, EVENT.size * 64)
    if not data or len(data) % EVENT.size:
        raise OSError('Lost input device')
    for _, _, kind, code, value in EVENT.iter_unpack(data):
        if kind == 0 and code == SYN_DROPPED:
            raise OSError('Dropped evdev events; reopen and require release')
        if kind == EV_KEY:
            yield code, value


class Keys:
    def __init__(self, config, down, action):
        self.mapping = {config['glove_key']: 'glove', config['hold_key']: 'hold',
                        config['record_key']: 'record'}
        if len(self.mapping) != 3 or not all(type(k) is int and 0 < k < 768 for k in self.mapping):
            raise ValueError('Configure three distinct Linux EV_KEY codes')
        self.debounce = config['debounce_ms'] / 1000
        if not 0 <= self.debounce <= 1:
            raise ValueError('Invalid debounce_ms')
        self.down = set(down)
        self.last = {}
        self.action = action
        self.press = None
        self.since = None

    def event(self, code, value):
        if code not in self.mapping or value not in (0, 1):
            return
        name = self.mapping[code]
        if value == 0:
            self.down.discard(code)
            if name == 'hold':
                self.press = self.since = None
            return
        if code in self.down:
            return
        self.down.add(code)
        now = time.monotonic()
        if name == 'hold':
            self.press, self.since = uuid.uuid4().hex, now
        elif now - self.last.get(code, -2) >= self.debounce:
            self.last[code] = now
            self.action(name)


class Actions:
    def __init__(self):
        self.locks = {key: threading.Lock() for key in ('glove', 'record')}
        self.voice = Voice()

    def __call__(self, name):
        if self.locks[name].acquire(blocking=False):
            threading.Thread(target=self.run, args=(name,), daemon=True).start()

    def run(self, name):
        try:
            if name == 'glove':
                result = send_toggle('pedal-' + uuid.uuid4().hex)
            else:
                import json
                result = subprocess.run(['bash', str(HERE / 'mcap_rpc.sh'), 'pedal'],
                                        capture_output=True, text=True, timeout=110)
                reply = json.loads(result.stdout)
                if not reply.get('success'):
                    raise RuntimeError(str(reply))
                result = reply['result']
                self.voice.say('数据采集已保存。' if result.get('save_status') == 'saved' else '数据采集已开启。')
            print(name, result, flush=True)
        except Exception as exc:
            print(name, 'failed', repr(exc), flush=True)
            if name == 'glove':
                self.voice.say('手套启动失败，请检查设备连接。')
            else:
                self.voice.say('请检查采集日志。')
        finally:
            self.locks[name].release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--learn', metavar='EVENT_DEVICE')
    args = parser.parse_args()
    if args.learn:
        with open(args.learn, 'rb', buffering=0) as device:
            print('EV_KEY: 1=press, 0=release, 2=repeat', flush=True)
            while True:
                for code, value in events(device.fileno()):
                    print(code, value, flush=True)
    config = settings()
    if config['mode'] == 'dual':
        return
    path = Path(config['device'])
    if not path.is_absolute() or path.parent not in (Path('/dev/input/by-id'), Path('/dev/input/by-path')):
        raise SystemExit('Set a stable pedal device symlink under /dev/input/by-id or by-path')
    actions = Actions()
    previous = None
    def report(connected, keys=None):
        nonlocal previous
        press = keys.press if keys else None
        publish('pedal.json', connected=connected, press=press, since=keys.since if keys else None)
        if (connected, press) != previous:
            event('pedal', dict(connected=connected, held=bool(press), press=press))
            previous = (connected, press)

    while True:
        try:
            with path.open('rb', buffering=0) as device:
                fd = device.fileno()
                fcntl.ioctl(fd, 0x40044590, 1)  # EVIOCGRAB: pedal letters stay out of the desktop.
                keys = Keys(config, key_bitmap(fd), actions)
                print('Pedal connected:', path, flush=True)
                report(True, keys)
                last_poll = time.monotonic()
                while True:
                    readable = select.select([fd], [], [], 0.04)[0]
                    now = time.monotonic()
                    if now - last_poll >= TTL:
                        raise OSError('Input loop paused; require release before rearming')
                    last_poll = now
                    if readable:
                        for code, value in events(fd):
                            keys.event(code, value)
                            if code == config['hold_key']:
                                report(True, keys)
                    report(True, keys)
        except OSError as exc:
            report(False)
            print('Pedal unavailable:', exc, flush=True)
            time.sleep(1)


if __name__ == '__main__':
    main()
