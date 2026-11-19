import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import operator_journal
import operator_state as state
import pedal_pose
import pedals
import patch_runtime
from mcap_bridge import Bridge


def test_physical_keys_bounce_repeat_and_hotplug():
    cfg = state.settings()
    assert (cfg['glove_key'], cfg['hold_key'], cfg['record_key']) == (30, 46, 18)
    actions = []
    keys = pedals.Keys(cfg, [46], actions.append)
    keys.event(46, 1)
    assert keys.press is None
    keys.event(46, 0)
    keys.event(46, 1)
    press = keys.press
    assert press
    for key in (30,18):
        for value in (1,1,2,0,1,0):
            keys.event(key, value)
    assert keys.press == press and actions == ['glove','record']
    keys.event(46, 0)
    assert keys.press is None


@dataclass
class Message:
    head: dict
    left_controller: dict
    right_controller: dict
    mode: str = 'controller'
    left_hand: dict = None
    right_hand: dict = None
    left_buttonState: dict = None
    right_buttonState: dict = None


def frame():
    pose = dict(position=dict(x=0,y=1,z=0), quaternion=dict(x=0,y=0,z=0,w=1))
    return Message(pose,pose,pose)


def test_invalid_tracking_never_enables():
    for key,value in [('mode','hand'), ('left_controller',None), ('right_hand',{}),
                      ('head',dict(position={},quaternion={})), ('right_controller',{'position':{},'quaternion':{}})]:
        msg = frame()
        setattr(msg, key, value)
        assert not pedal_pose.valid_pose(msg)
    assert pedal_pose.valid_pose(frame())


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'SIGNALS', tmp_path)
    monkeypatch.setattr(operator_journal, 'JOURNALS', tmp_path / 'history')
    monkeypatch.setattr(state, 'ready_session', lambda: 'glove-42')
    return tmp_path


def test_gate_release_watchdog_and_recording_isolation(isolated):
    native = NS(state=NS(calibration_mode=False, await_enable_rearm=False, teleop_on=False),
                auto_return_priority=False, config=NS(robot=NS(requires_motor_op_check=False)),
                error_monitor=NS(has_error=lambda:(False,0)), chassis_monitor=NS(is_enabled=lambda:True),
                joycon=NS(publish_stop=lambda:None))
    calls = []
    async def original(ws,msg):
        assert msg.left_buttonState == msg.right_buttonState
        native.state.teleop_on = msg.left_buttonState['Two']
        calls.append(native.state.teleop_on)
    native.handle_pose = original

    async def run():
        gate = pedal_pose.PoseGate(native)
        ws, msg = object(), frame()
        msg.left_buttonState = msg.right_buttonState = {'Two':True, 'ThumbstickPress':True}
        def pedal(press):
            state.publish('pedal.json', connected=True, press=press, since=time.monotonic())
        pedal('already-held')
        await gate.handle(ws,msg)
        assert calls == [False]
        pedal(None)
        await gate.handle(ws,msg)
        cursor = operator_journal.begin_episode()
        pedal('new')
        await gate.handle(ws,msg)
        assert calls[-1] and state.hand_enabled(time.time_ns())
        assert not state.hand_enabled(0)
        pedal(None)
        assert not state.hand_enabled(time.time_ns())
        await asyncio.sleep(.07)
        assert not native.state.teleop_on
        await gate.handle(ws,msg)
        pedal('again')
        await gate.handle(ws,msg)
        assert calls[-1]
        await asyncio.sleep(state.TTL + .08)
        assert not native.state.teleop_on and not state.hand_enabled(time.time_ns())
        pedal('held-on-reconnect')
        await gate.handle(object(), msg)
        assert not calls[-1]
        await gate.close()
        operator_journal.finish_episode(cursor,time.time_ns(), isolated)
        rows = [json.loads(line) for line in (isolated/'operator_events.jsonl').read_text().splitlines()]
        assert rows[0]['source']=='initial' and rows[-1]['source']=='end'
        assert [r['enabled'] for r in rows if r['source']=='follow'] == [True,False,True,False]
    asyncio.run(run())


def test_single_mode_discards_vr_buttons(monkeypatch):
    monkeypatch.setattr(patch_runtime, 'settings', lambda:{'mode':'single'})
    class Server:
        def __init__(self, *, message_dispatcher):
            self.dispatch = message_dispatcher
    module = NS(LowFreqServerManager=Server, decode_message=lambda msg:msg)
    patch_runtime.patch_low_frequency(module)
    async def forbidden(*args):
        raise AssertionError('Unexpected dispatch')
    server = Server(message_dispatcher=forbidden)
    asyncio.run(server.dispatch(None,patch_runtime.GloveControl('x'),None))
    asyncio.run(server.dispatch(None,patch_runtime.McapCancel(),None))
    bridge = object.__new__(Bridge)
    bridge.single = True
    bridge.observe(object(), True, True)


def test_glove_readiness_requires_live_processes_and_both_hand_streams(tmp_path, monkeypatch):
    import os
    pid = os.getpid()
    ticks = state.process_start(pid)
    monkeypatch.setattr(state,'SIGNALS',tmp_path)
    monkeypatch.setattr(state,'GLOVE',tmp_path / 'glove.json')
    glove = dict(phase='ready', session='current', pid=pid, manager_pid=pid,
                 pid_start=ticks, manager_start=ticks)
    state.GLOVE.write_text(json.dumps(glove))
    assert state.ready_session() is None
    state.publish('hands.json', session='previous')
    assert state.ready_session() is None
    state.publish('hands.json', session='current')
    assert state.ready_session() == 'current'
    state.GLOVE.write_text(json.dumps(dict(glove, pid_start='reused')))
    assert state.ready_session() is None
