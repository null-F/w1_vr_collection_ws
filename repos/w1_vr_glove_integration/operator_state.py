"""PC1 operator mode and short-lived enable signals shared by the three services."""
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config/w1/pedals.json'
SIGNALS = Path('/run/linkerhand-w1-pedals')
GLOVE = ROOT / 'runtime/vr_glove/state.json'
TTL = 0.25


def settings():
    data = json.loads(CONFIG.read_text())
    if data['mode'] not in ('dual', 'single'):
        raise ValueError('Invalid operator mode in ' + str(CONFIG))
    return data


def read(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def publish(name, **fields):
    path = SIGNALS / name
    tmp = path.with_suffix(f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(dict(fields, monotonic=time.monotonic())))
    tmp.replace(path)


def fresh(name):
    data = read(SIGNALS / name)
    at = data.get('monotonic')
    if isinstance(at, (float, int)) and 0 <= time.monotonic() - at < TTL:
        return data
    return {}


def process_start(pid):
    try:
        fields = (Path('/proc') / str(int(pid)) / 'stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (ValueError, TypeError, OSError, IndexError):
        return None


def ready_session():
    glove = read(GLOVE)
    if glove.get('phase') == 'ready' and glove.get('pid_start') and glove.get('manager_start'):
        if (process_start(glove.get('pid')) == glove['pid_start'] and
                process_start(glove.get('manager_pid')) == glove['manager_start'] and
                fresh('hands.json').get('session') == glove.get('session')):
            return glove.get('session')
    return None


def hand_enabled(stamp_ns):
    pedal, vr = fresh('pedal.json'), fresh('vr.json')
    age = time.time_ns() - stamp_ns
    return bool(pedal.get('press') and pedal['press'] == vr.get('press') and
                vr.get('session') and vr['session'] == ready_session() and
                0 <= age < TTL * 1e9 and isinstance(vr.get('started_wall_ns'), int) and stamp_ns >= vr['started_wall_ns'])
