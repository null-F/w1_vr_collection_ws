import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from storage import atomic_json,process_identity,identity_alive

ROOT=Path(__file__).resolve().parents[1]
DUMMY="import signal,time,pathlib,sys\nsignal.signal(signal.SIGINT,lambda s,f:sys.exit(0))\npathlib.Path(sys.argv[1]).write_text('ready')\nwhile True:time.sleep(.05)\n"


def wait_for(fn, seconds=6):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if fn():return
        time.sleep(.05)
    raise AssertionError('deadline expired')


def test_worker_closes_child_on_signal(tmp_path):
    dummy=tmp_path/'dummy.py';dummy.write_text(DUMMY)
    atomic_json(tmp_path/'parent.json',{'owner':process_identity(os.getpid())})
    p=subprocess.Popen([sys.executable,str(ROOT/'record_worker.py'),'--parent',str(tmp_path/'parent.json'),'--result',str(tmp_path/'result.json'),'--child-state',str(tmp_path/'child.json'),'--grace','2','--',sys.executable,str(dummy),str(tmp_path/'ready')])
    try:
        wait_for(lambda:(tmp_path/'ready').exists());p.send_signal(signal.SIGTERM);p.wait(timeout=6)
        r=json.loads((tmp_path/'result.json').read_text());assert r['reason']=='signal' and r['returncode']==0 and not r['forced']
        assert not identity_alive(json.loads((tmp_path/'child.json').read_text()))
    finally:
        if p.poll() is None:p.kill();p.wait()


def test_worker_closes_child_when_parent_is_killed(tmp_path):
    dummy=tmp_path/'dummy.py';dummy.write_text(DUMMY)
    helper=tmp_path/'parent.py'
    helper.write_text("import sys,subprocess,time,os\nfrom pathlib import Path\nfrom storage import atomic_json,process_identity\np=Path(sys.argv[1]);atomic_json(p/'parent.json',{'owner':process_identity(os.getpid())})\nsubprocess.Popen([sys.executable,sys.argv[2],'--parent',str(p/'parent.json'),'--result',str(p/'result.json'),'--child-state',str(p/'child.json'),'--grace','2','--',sys.executable,str(p/'dummy.py'),str(p/'ready')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)\nwhile True:time.sleep(.1)\n")
    parent=subprocess.Popen([sys.executable,str(helper),str(tmp_path),str(ROOT/'record_worker.py')])
    try:
        wait_for(lambda:(tmp_path/'ready').exists());parent.kill();parent.wait()
        wait_for(lambda:(tmp_path/'result.json').exists())
        result=json.loads((tmp_path/'result.json').read_text());assert result['reason']=='parent_lost' and result['returncode']==0
        assert not identity_alive(json.loads((tmp_path/'child.json').read_text()))
    finally:
        if parent.poll() is None:parent.kill();parent.wait()
