"""Offline checks only: fake PulseAudio clients, no speaker/ROS/PC2 connections."""
import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import wave

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'repos/w1_vr_glove_integration'))
sys.path.insert(0, str(ROOT / 'repos/w1_glove_integration'))
sys.path.insert(0, str(ROOT / 'repos/linkerbot_ffg_ros2/src/linkerbot_ffg_ros'))
import local_voice as voice


def wait_for(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for test worker')


@pytest.fixture
def bank(tmp_path, monkeypatch):
    for key in ('W1_VOICE_CONFIG', 'W1_VOICE_PULSE_SERVER', 'W1_VOICE_SINK'):
        monkeypatch.delenv(key, raising=False)
    assets = tmp_path / 'audio'
    assets.mkdir()
    entries = {}
    catalog = {'test_a': '测试甲。', 'test_b': '测试乙。'}
    for key, text in catalog.items():
        path = assets / (key + '.wav')
        with wave.open(str(path), 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b'\x01\x00' * 400)
        entries[key] = {'file': path.name, 'text': text,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = assets / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 2, 'prompts': entries}))
    catalog_path = tmp_path / 'catalog.json'
    catalog_path.write_text(json.dumps(catalog))
    config = tmp_path / 'voice.json'
    config.write_text(json.dumps({'assets': str(assets), 'server': 'unix:/run/user/{uid}/pulse/native',
                                 'sink': 'alsa_output.usb-test', 'lock_wait_seconds': 2,
                                 'playback_grace_seconds': .3, 'probe_timeout_seconds': .5}))
    log = tmp_path / 'commands.jsonl'
    monkeypatch.setenv('TEST_VOICE_LOG', str(log))
    script = f'#!{sys.executable}\n' + r'''
import json, os, pathlib, signal, sys, time
kind = pathlib.Path(sys.argv[0]).name
mode = os.environ.get('TEST_VOICE_MODE', 'normal')
def log(event):
    fd = os.open(os.environ['TEST_VOICE_LOG'], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.write(fd, (json.dumps({'kind':kind, 'event':event, 'pid':os.getpid(), 'args':sys.argv[1:], 'time':time.monotonic()}) + '\n').encode())
    os.close(fd)
log('start')
if kind == 'pactl':
    if mode == 'probe_hang':
        time.sleep(10)
    if mode == 'probe_fail':
        print('Connection failure: Access denied', file=sys.stderr)
        sys.exit(9)
    sink = 'alsa_output.platform-sound.analog-stereo' if mode == 'missing_sink' else 'alsa_output.usb-test'
    print(f'4\t{sink}\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tSUSPENDED')
else:
    if mode == 'play_fail':
        print('Failed to create playback stream', file=sys.stderr)
        sys.exit(8)
    if mode == 'ignore_term':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if mode in ('hang', 'ignore_term'):
        time.sleep(10)
    else:
        time.sleep(float(os.environ.get('TEST_VOICE_DELAY', '.03')))
log('end')
'''
    player = tmp_path / 'paplay'
    probe = tmp_path / 'pactl'
    for executable in (player, probe):
        executable.write_text(script)
        executable.chmod(0o755)
    lock = tmp_path / 'runtime/playback.lock'
    def build():
        return voice.LocalPlayer(config=config, catalog=catalog_path, lock_path=lock,
                                 executable=player, probe_executable=probe)
    def records():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return SimpleNamespace(assets=assets, config=config, catalog=catalog_path,
                           manifest=manifest, player=player, probe=probe, lock=lock,
                           build=build, records=records, log=log)


def test_check_neither_executes_nor_opens_audio(bank, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected child process')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    report = bank.build().check()
    assert report['prompts'] == 2 and report['sink'] == 'alsa_output.usb-test'
    assert not bank.lock.exists() and bank.records() == []


def test_packaged_bank_has_all_real_prompts_and_nonzero_audio():
    # Executables are deliberately inert labels: static validation must not run them.
    player = voice.LocalPlayer(executable='unused-paplay', probe_executable='unused-pactl')
    assert player.check()['prompts'] == 20
    from linkerbot_ffg_ros.calibration.poses import POSES
    for pose in POSES:
        assert '请双手' + pose.instruction + '，并保持。' in player.by_text
    for filename in ('glove_manager.py', 'glove_entry.py', 'mcap_bridge.py'):
        tree = ast.parse((ROOT / 'repos/w1_vr_glove_integration' / filename).read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'say' and isinstance(node.args[0], ast.Constant)):
                assert node.args[0].value in player.by_text
    for key in player.catalog:
        path, duration = player.validate(key)
        with wave.open(str(path), 'rb') as audio:
            assert any(audio.readframes(audio.getnframes())), 'placeholder/silent audio is not acceptable'
        assert 0 < duration < 20
    for text in ('已取消手套标定。', '已停止手套遥操。', '请双手握拳并保持。',
                 '请双手保持O型手势。', '请双手五指张开并保持。'):
        assert text in player.by_text


def test_every_new_runtime_source_has_python310_syntax():
    for name in ('local_voice.py', 'generate_voice_assets.py', 'glove_manager.py',
                 'glove_entry.py', 'mcap_bridge.py'):
        ast.parse((ROOT / 'repos/w1_vr_glove_integration' / name).read_text(), feature_version=(3, 10))


@pytest.mark.parametrize('field,value', [('server', 'tcp:192.168.20.21'),
    ('server', 'unix:/tmp/pulse tcp:host'), ('sink', 'default'), ('sink', '@DEFAULT_SINK@'),
    ('sink', '12'), ('sink', 'name; echo unsafe'), ('lock_wait_seconds', 0),
    ('playback_grace_seconds', float('nan')), ('probe_timeout_seconds', -1)])
def test_reject_unpinned_or_unbounded_config(bank, field, value):
    settings = json.loads(bank.config.read_text())
    settings[field] = value
    bank.config.write_text(json.dumps(settings))
    with pytest.raises(voice.VoiceError):
        bank.build()


@pytest.mark.parametrize('damage', ['missing', 'checksum', 'text', 'filename', 'truncated', 'format'])
def test_bad_assets_fail_before_any_process(bank, damage):
    path = bank.assets / 'test_a.wav'
    manifest = json.loads(bank.manifest.read_text())
    if damage == 'missing':
        path.unlink()
    elif damage == 'checksum':
        path.write_bytes(path.read_bytes() + b'corruption')
    elif damage in ('text', 'filename'):
        manifest['prompts']['test_a']['text' if damage == 'text' else 'file'] = 'wrong'
    elif damage == 'truncated':
        path.write_bytes(path.read_bytes()[:-4])
        manifest['prompts']['test_a']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        with wave.open(str(path), 'wb') as audio:
            audio.setparams((1, 1, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b'\x01' * 400)
        manifest['prompts']['test_a']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    bank.manifest.write_text(json.dumps(manifest))
    with pytest.raises((voice.VoiceError, FileNotFoundError)):
        bank.build().play('测试甲。')
    assert bank.records() == []


def test_unknown_text_has_no_cloud_fallback(bank):
    with pytest.raises(voice.VoiceError, match='No packaged audio'):
        bank.build().play('随便说一句动态文本')
    assert bank.records() == []


def test_probe_is_readonly_and_playback_pins_real_local_sink(bank, monkeypatch):
    monkeypatch.setenv('PULSE_SERVER', 'tcp:192.168.20.21')
    monkeypatch.setenv('PULSE_SINK', 'alsa_output.platform-sound.analog-stereo')
    player = bank.build()
    assert player.check_output()['present']
    assert {r['kind'] for r in bank.records()} == {'pactl'}
    player.play('测试甲。')
    commands = [r for r in bank.records() if r['event'] == 'start']
    for command in commands:
        assert f'--server=unix:/run/user/{os.getuid()}/pulse/native' in command['args']
    assert commands[0]['args'][-3:] == ['list', 'short', 'sinks']
    playback = commands[-1]['args']
    assert '--device=alsa_output.usb-test' in playback and '--playback' in playback
    assert not any('--volume' in arg or '--record' in arg for arg in playback)


@pytest.mark.parametrize('mode', ['missing_sink', 'probe_fail', 'probe_hang'])
def test_unavailable_output_never_plays_on_default(bank, monkeypatch, mode):
    monkeypatch.setenv('TEST_VOICE_MODE', mode)
    with pytest.raises(voice.VoiceError):
        bank.build().play('测试甲。')
    assert {r['kind'] for r in bank.records()} == {'pactl'}
    for record in bank.records():
        assert not Path(f"/proc/{record['pid']}").exists()


def test_player_failure_releases_lock_for_next_prompt(bank, monkeypatch):
    monkeypatch.setenv('TEST_VOICE_MODE', 'play_fail')
    with pytest.raises(voice.VoiceError, match='paplay failed'):
        bank.build().play('测试甲。')
    monkeypatch.setenv('TEST_VOICE_MODE', 'normal')
    bank.build().play('测试乙。')
    assert bank.records()[-1]['event'] == 'end'


@pytest.mark.parametrize('mode', ['hang', 'ignore_term'])
def test_player_timeout_reaps_child(bank, monkeypatch, mode):
    monkeypatch.setenv('TEST_VOICE_MODE', mode)
    with pytest.raises(voice.VoiceError, match='timed out'):
        bank.build().play('测试甲。')
    for row in bank.records():
        assert not Path(f"/proc/{row['pid']}").exists()


@pytest.mark.parametrize('mode,kind', [('hang', 'paplay'), ('probe_hang', 'pactl')])
def test_cancellation_reaps_active_probe_or_audio(bank, monkeypatch, mode, kind):
    monkeypatch.setenv('TEST_VOICE_MODE', mode)
    cancel = threading.Event()
    errors = []
    def play():
        try:
            bank.build().play('测试甲。', cancel)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=play)
    worker.start()
    try:
        wait_for(lambda: any(r['kind'] == kind for r in bank.records()))
        cancel.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], voice.PlaybackCancelled)
        for row in bank.records():
            assert not Path(f"/proc/{row['pid']}").exists()
    finally:
        cancel.set()
        worker.join(timeout=2)


def test_cross_process_lock_serializes_all_prompts(bank):
    command = [sys.executable, '-c',
               "import sys;sys.path.insert(0,sys.argv[1]);from local_voice import LocalPlayer;"
               "LocalPlayer(config=sys.argv[2],catalog=sys.argv[3],lock_path=sys.argv[4],"
               "executable=sys.argv[5],probe_executable=sys.argv[6]).play('测试甲。')",
               str(ROOT / 'repos/w1_vr_glove_integration'), str(bank.config), str(bank.catalog),
               str(bank.lock), str(bank.player), str(bank.probe)]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    try:
        for proc in processes:
            out, err = proc.communicate(timeout=5)
            assert proc.returncode == 0, out + err
        assert [(r['kind'], r['event']) for r in bank.records()] == [
            ('pactl', 'start'), ('pactl', 'end'), ('paplay', 'start'), ('paplay', 'end')] * 3
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def test_waiting_for_playback_lock_is_cancellable(bank):
    owner = bank.build()
    cancel = threading.Event()
    errors = []
    def waiter():
        try:
            bank.build().play('测试甲。', cancel)
        except Exception as exc:
            errors.append(exc)
    with owner._locked(threading.Event(), time.monotonic() + 2):
        worker = threading.Thread(target=waiter)
        worker.start()
        time.sleep(.04)
        cancel.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
    assert isinstance(errors[0], voice.PlaybackCancelled) and bank.records() == []


def test_expired_deadline_cannot_start_audio(bank):
    with pytest.raises(voice.VoiceError, match='Timed out'):
        bank.build().play('测试甲。', deadline=time.monotonic() - 1)
    assert bank.records() == []


def test_status_queue_clear_cancels_active_and_drops_old_prompts():
    started = threading.Event()
    cancelled = threading.Event()
    spoken = []
    def player(text, cancel, **_):
        spoken.append(text)
        if text == 'old':
            started.set()
            assert cancel.wait(timeout=2)
            cancelled.set()
            raise voice.PlaybackCancelled('test')
    speaker = voice.Voice(player)
    try:
        speaker.say('old')
        assert started.wait(timeout=1)
        speaker.say('queued-old')
        speaker.clear()
        speaker.say('new')
        assert cancelled.wait(timeout=1)
        wait_for(lambda: spoken == ['old', 'new'])
    finally:
        speaker.close()
    assert not speaker.worker.is_alive()


def test_status_queue_is_bounded_and_discards_expired_items():
    started = threading.Event()
    release = threading.Event()
    spoken = []
    def player(text, cancel, **_):
        spoken.append(text)
        started.set()
        release.wait(timeout=2)
    speaker = voice.Voice(player, ttl=.05, capacity=2)
    try:
        speaker.say('active')
        assert started.wait(timeout=1)
        for text in ('stale-a', 'stale-b', 'stale-c'):
            speaker.say(text)
        with speaker.condition:
            assert len(speaker.pending) == 2
        time.sleep(.07)
        release.set()
        wait_for(lambda: not speaker.pending and speaker.active is None)
        assert spoken == ['active']
    finally:
        release.set()
        speaker.close()


def test_status_player_failure_does_not_kill_queue(capsys):
    done = threading.Event()
    def player(text, *_, **__):
        if text == 'bad':
            raise voice.VoiceError('no audio device')
        done.set()
    speaker = voice.Voice(player)
    try:
        speaker.say('bad')
        speaker.say('good')
        assert done.wait(timeout=1)
    finally:
        speaker.close()
    assert 'VOICE_FAILED bad' in capsys.readouterr().out


def test_interrupted_ffg_poll_cancels_speech_before_return(monkeypatch):
    import ffg_entry
    entered = threading.Event()
    exited = threading.Event()
    def play(text, cancel):
        entered.set()
        try:
            assert cancel.wait(timeout=2)
            raise voice.PlaybackCancelled('test')
        finally:
            exited.set()
    monkeypatch.setattr(ffg_entry, 'speak', play)
    class Reader:
        def poll(self):
            assert entered.wait(timeout=1)
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        ffg_entry.speak_while_polling({'left': Reader()}, 'prompt')
    assert exited.is_set()


def test_legacy_calibration_uses_local_playback_before_capture(monkeypatch):
    import runpy
    import types
    events = []
    class Retarget:
        _current_calibration_pose = 'fist'
        def _calibration_with_progress(self):
            events.append('sample')
        def process(self):
            return True
    fake_retarget = types.ModuleType('linkerhand_retarget.motion.linkerforce.retarget')
    fake_retarget.Retarget = Retarget
    fake_original = types.ModuleType('linkerhand_retarget.handretarget')
    monkeypatch.setitem(sys.modules, 'linkerhand_retarget', types.ModuleType('linkerhand_retarget'))
    monkeypatch.setitem(sys.modules, 'linkerhand_retarget.handretarget', fake_original)
    monkeypatch.setitem(sys.modules, 'linkerhand_retarget.motion.linkerforce.retarget', fake_retarget)
    monkeypatch.setattr(voice, 'play_text', lambda text: events.append(text))
    runpy.run_path(str(ROOT / 'repos/w1_vr_glove_integration/glove_entry.py'))
    Retarget()._calibration_with_progress()
    assert events == ['请双手握拳并保持。', 'sample']


def test_mcap_start_and_save_do_not_wait_for_audio(monkeypatch, tmp_path):
    import mcap_bridge
    monkeypatch.setattr(mcap_bridge, 'OWNER', tmp_path / 'owner.json')
    # RPC is an immediate fake. Keep its scheduling local too: this test checks
    # the independent speech worker, not cross-thread event-loop wakeup sockets.
    async def immediate(function, *args):
        return function(*args)
    monkeypatch.setattr(mcap_bridge.asyncio, 'to_thread', immediate)
    started = threading.Event()
    stopped = threading.Event()
    calls = []
    def play(text, cancel, **_):
        started.set()
        cancel.wait(timeout=3)
        stopped.set()
    speaker = voice.Voice(play)
    def runner(command):
        calls.append(command)
        return {'episode_dir': '/test-only', 'save_status': 'saved'}
    async def exercise():
        async def broadcast(message):
            pass
        bridge = mcap_bridge.Bridge(SimpleNamespace(broadcast_callback=broadcast),
                                   lambda **kw: kw, runner=runner, voice=speaker)
        bridge.observe(object(), True, True)
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.01)
            assert started.is_set() and bridge.phase == 'recording' and calls == ['start']
            assert not stopped.is_set()
            await asyncio.wait_for(bridge.close(), timeout=2)
            assert 'stop' in calls and bridge.phase == 'idle'
            assert stopped.is_set()
        finally:
            speaker.close()
            if bridge.worker and not bridge.worker.done():
                bridge.worker.cancel()
                try:
                    await bridge.worker
                except asyncio.CancelledError:
                    pass
    asyncio.run(exercise())


def test_runtime_contains_no_cloud_or_microphone_controls():
    for name in ('local_voice.py', 'glove_manager.py', 'glove_entry.py'):
        text = (ROOT / 'repos/w1_vr_glove_integration' / name).read_text()
        assert '192.168.20.21' not in text and 'voice_agent/speak' not in text
        for forbidden in ('module-tunnel', 'set-default-source', 'set-sink-volume',
                          'VA_VAD_RMS_THRESHOLD', 'charging_text', 'urllib.request'):
            assert forbidden not in text
