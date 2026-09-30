#!/usr/bin/env python3
"""Observe the original calibration; do not replace its control algorithm."""
import functools
import json
import urllib.request
import linkerhand_retarget.handretarget as original
from linkerhand_retarget.motion.linkerforce.retarget import Retarget


def emit(event, **fields):
    print('LINKERHAND_GLOVE_EVENT ' + json.dumps(dict(event=event, **fields), ensure_ascii=False), flush=True)


collect = Retarget._calibration_with_progress
@functools.wraps(collect)
def observed_collect(self, *args, **kwargs):
    stage = self._current_calibration_pose
    emit('stage', stage=stage)
    prompts = {'fist': '请双手握拳并保持。', 'opose': '请双手保持O型手势。',
               'original': '请双手五指张开并保持。'}
    # Readers already run in their own threads. Announce before collecting the
    # stable pose so network/TTS latency cannot label the previous pose as next.
    payload = {'type': 'text', 'params': {'text': prompts[stage]}, 'blocking': True}
    request = urllib.request.Request('http://192.168.20.21:8766/voice_agent/speak',
        json.dumps(payload, ensure_ascii=False).encode(),
        {'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with urllib.request.urlopen(request, timeout=25) as response:
        result = json.load(response)
    if result.get('code') != 0 or result.get('data', {}).get('status') != 'ok':
        raise RuntimeError('Calibration prompt could not be spoken: ' + str(result))
    return collect(self, *args, **kwargs)
Retarget._calibration_with_progress = observed_collect

process = Retarget.process
@functools.wraps(process)
def observed_process(self, *args, **kwargs):
    try:
        result = process(self, *args, **kwargs)
    except Exception:
        emit('failed')
        raise
    emit('ready' if result else 'failed')
    return result
Retarget.process = observed_process

if __name__ == '__main__':
    original.main()
