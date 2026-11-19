"""Persist operator transitions while the ROS recorder is starting or closing a bag."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time

import operator_state as state

JOURNALS = state.ROOT / 'runtime/operator_history'


@contextmanager
def journal(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        yield file


def current_path():
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    return JOURNALS / (boot + '.jsonl')


def event(source, fields):
    try:
        with journal(current_path()) as file:
            row = dict(wall_ns=time.time_ns(), source=source, **fields)
            file.write((json.dumps(row, ensure_ascii=False) + '\n').encode())
    except OSError as exc:
        # In particular, logging failure must not prevent glove shutdown or native grip release.
        print('Operator event write failed:', source, exc, flush=True)


def begin_episode():
    path = current_path()
    with journal(path) as file:
        pedal, vr = state.fresh('pedal.json'), state.fresh('vr.json')
        glove = state.read(state.GLOVE)
        return {'path': str(path), 'offset': file.tell(), 'initial': {
            'wall_ns': time.time_ns(), 'glove_phase': glove.get('phase', 'unavailable'),
            'glove_stage': glove.get('stage'), 'glove_session': glove.get('session'),
            'pedal_connected': bool(pedal.get('connected')), 'pedal_held': bool(pedal.get('press')),
            'following': bool(pedal.get('press') and vr.get('press') == pedal['press']
                              and vr.get('session') == state.ready_session() and vr.get('session'))}}


def finish_episode(cursor, stopped_ns, episode):
    path = Path(cursor['path'])
    if path.parent != JOURNALS or not path.is_file():
        raise ValueError('Operator event journal is unavailable')
    tmp = episode / 'operator_events.jsonl.tmp'
    with journal(path) as file:
        end_offset = file.tell()
    if end_offset < cursor['offset']:
        raise ValueError('Operator event journal was truncated')
    with path.open('rb') as file, tmp.open('wb') as output:
        file.seek(cursor['offset'])
        initial = dict(source='initial', **cursor['initial'])
        output.write((json.dumps(initial) + '\n').encode())
        while file.tell() < end_offset:
            line = file.readline()
            if json.loads(line)['wall_ns'] <= stopped_ns:
                output.write(line)
        output.write((json.dumps(dict(source='end', wall_ns=stopped_ns)) + '\n').encode())
        output.flush()
        os.fsync(output.fileno())
    tmp.replace(episode / 'operator_events.jsonl')
