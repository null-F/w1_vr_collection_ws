#!/usr/bin/env python3
"""Observe the original calibration; do not replace its control algorithm."""
import functools
import json
from local_voice import play_text
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
    # Complete local playback before collecting the pose; no cloud request.
    play_text(prompts[stage])
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
