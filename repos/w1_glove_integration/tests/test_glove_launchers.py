"""Exercise production shell control flow with mocked external paths and Python.

Only temporary copies are executed. No USB, systemd, sudo, ROS or speech access.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('launcher,sdk,options,exit_code', [
    ('terminal', 'ffg', [], 0),
    ('terminal', 'ffg', ['--preview', '--reuse-calibration'], 0),
    ('terminal', 'ffg', [], 37),
    ('terminal', 'legacy', ['--preview', '--reuse-calibration'], 0),
    ('vr', 'ffg', [], 0),
    ('vr', 'ffg', [], 37),
    ('vr', 'legacy', [], 0),
])
def test_entry_selection_preview_and_bridge_cleanup(tmp_path, launcher, sdk, options, exit_code):
    integration = tmp_path / 'integration'
    integration.mkdir()
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    calibration = runtime / 'calibration/glove/jointangle_data.tmp'
    calibration.parent.mkdir(parents=True)
    calibration.write_text('legacy-test-only')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    (integration / 'env.sh').write_text(
        f'LINKER_W1_ROOT="{tmp_path}"\n'
        'W1_GLOVE_SDK="${W1_GLOVE_SDK:-ffg}"\n'
        f'export PATH="{bindir}:$PATH"\n'
    )
    (integration / 'prepare_glove_usb.sh').write_text('#!/bin/bash\nexit 0\n')
    log = tmp_path / 'calls.jsonl'
    bridge_pid = tmp_path / 'bridge.pid'
    fake = bindir / 'python'
    fake.write_text(f'#!{sys.executable}\n' + '''
import json, os, pathlib, signal, sys, time
args = sys.argv[1:]
path = pathlib.Path(args[0]).name
fd = os.open(os.environ['TEST_CALLS'], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (json.dumps(args) + '\\n').encode())
os.close(fd)
if path == 'glove_ports.py':
    print('/dev/qualifiedA\\n/dev/qualifiedB')
elif path == 'w1_hand_bridge.py':
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    pathlib.Path(os.environ['TEST_BRIDGE_PID']).write_text(str(os.getpid()))
    while True:
        time.sleep(.02)
elif '--check' not in args:
    deadline = time.monotonic() + 3
    while not pathlib.Path(os.environ['TEST_BRIDGE_PID']).exists():
        if time.monotonic() > deadline:
            sys.exit(99)
        time.sleep(.01)
    sys.exit(int(os.environ['TEST_SDK_EXIT']))
''')
    fake.chmod(0o755)
    if launcher == 'terminal':
        source = ROOT / 'repos/w1_glove_integration/start_gloves.sh'
        target = integration / 'start_gloves.sh'
        target.write_text(source.read_text())
    else:
        source = ROOT / 'repos/w1_vr_glove_integration/run_gloves.sh'
        target = tmp_path / 'run_gloves.sh'
        driver = tmp_path / 'ch341'
        driver.mkdir()
        target.write_text(source.read_text()
                          .replace('/home/dexforce/linkerhand/repos/w1_glove_integration', str(integration))
                          .replace('/sys/module/ch341', str(driver)))
    env = dict(os.environ, W1_GLOVE_SDK=sdk, TEST_CALLS=str(log),
               TEST_BRIDGE_PID=str(bridge_pid), TEST_SDK_EXIT=str(exit_code))
    result = subprocess.run(['bash', str(target), *options], env=env,
                            capture_output=True, text=True, timeout=6)
    assert result.returncode == exit_code, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    voices = [c for c in calls if Path(c[0]).name == 'local_voice.py']
    assert len(voices) == (1 if launcher == 'vr' else 0)
    if voices:
        assert voices[0][1:] == ['--check']
        assert calls.index(voices[0]) < next(i for i, c in enumerate(calls) if Path(c[0]).name == 'w1_hand_bridge.py')
    bridges = [c for c in calls if Path(c[0]).name == 'w1_hand_bridge.py']
    assert len(bridges) == 1
    assert ('--preview' in bridges[0]) == ('--preview' in options)
    pid = int(bridge_pid.read_text())
    assert not Path(f'/proc/{pid}').exists(), 'bridge must be reaped even on SDK failure'
    if sdk == 'ffg':
        ffg = [c for c in calls if Path(c[0]).name == 'ffg_entry.py']
        assert len(ffg) == 2 and ffg[0][1:] == ['--check']
        expected = ['--vr-events'] if launcher == 'vr' else (['--reuse-calibration'] if '--reuse-calibration' in options else [])
        assert ffg[1][1:] == expected
        assert not any('linkerhand_retarget.handretarget' in c or Path(c[0]).name == 'glove_entry.py' for c in calls)
    else:
        assert not any(Path(c[0]).name == 'ffg_entry.py' for c in calls)
        actual = next(c for c in calls if 'linkerhand_retarget.handretarget' in c or Path(c[0]).name == 'glove_entry.py')
        assert '/cb_left_hand_control_cmd:=/linkerhand/glove/left/motor_cmd' in actual
        assert '/cb_right_hand_control_cmd:=/linkerhand/glove/right/motor_cmd' in actual
        assert 'auto_scan:=false' in actual
        if launcher == 'terminal':
            assert 'calibration:=False' in actual
        else:
            assert 'calibration:=True' in actual


@pytest.mark.parametrize('selected,expected', [(None, 'ffg'), ('legacy', 'legacy'), ('bad', None)])
def test_actual_env_selects_one_sdk(tmp_path, selected, expected):
    source = (ROOT / 'repos/w1_glove_integration/env.sh').read_text()
    # Replace only the external source files and deployed root in a temp copy.
    # Execute the real SDK-selection logic unchanged.
    lines = [line if not line.startswith('source ') else ':' for line in source.splitlines()]
    text = '\n'.join(lines).replace('LINKER_W1_ROOT=/home/dexforce/linkerhand', f'LINKER_W1_ROOT="{tmp_path}"')
    target = tmp_path / 'env.sh'
    target.write_text(text)
    env = dict(os.environ)
    env.pop('W1_GLOVE_SDK', None)
    if selected is not None:
        env['W1_GLOVE_SDK'] = selected
    result = subprocess.run(['bash', '-c', 'set -e; source "$1"; printf "%s\\n%s\\n" "$W1_GLOVE_SDK" "$sdk_python"', 'test', str(target)],
                            env=env, capture_output=True, text=True, timeout=5)
    if expected is None:
        assert result.returncode != 0 and 'Unknown W1_GLOVE_SDK' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        selected_sdk, source_path = result.stdout.splitlines()
        assert selected_sdk == expected
        assert source_path.endswith('linkerbot_ffg_ros2/src/linkerbot_ffg_ros' if expected == 'ffg' else 'linkerhand_ros_teleop/src/linkerhand_retarget')
