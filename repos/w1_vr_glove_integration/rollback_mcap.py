#!/usr/bin/env python3
"""Detach MCAP recording overlay while retaining the validated X glove integration."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
HERE=Path(__file__).resolve().parent
if os.geteuid()!=0:raise SystemExit('Run with sudo')
meta=json.loads((HERE/'mcap_deployment.json').read_text())
state=json.loads(Path('/home/dexforce/linkerhand/runtime/mcap_recorder_state.json').read_text())
if state.get('active'):raise SystemExit('Stop and save the active recording before rollback')
for name in meta['before_files']:
 if hashlib.sha256((HERE/name).read_bytes()).hexdigest()!=meta['deployed_hashes'][name]:
  raise SystemExit('File changed after deployment; inspect before rollback: '+name)
for path,target in meta['unit_links'].items():
 p=Path(path)
 if not p.is_symlink() or p.resolve()!=Path(target):raise SystemExit('Unexpected unit link: '+path)
def ctl(*args):subprocess.run(['systemctl',*args],check=True)
ctl('stop','dexe-tele.service')
ctl('stop','linkerhand-w1-mcap.service')
ctl('disable','linkerhand-w1-mcap.service')
for path in meta['unit_links']:
 p=Path(path)
 if p.is_symlink():p.unlink()
for name in meta['before_files']:
 (HERE/name).write_bytes((Path(meta['backup'])/name).read_bytes())
ctl('daemon-reload')
subprocess.run(['runuser','-u','dexforce','--','bash','/home/dexforce/linkerhand/repos/w1_mcap_collection/record.sh','status'],check=True)
ctl('start','dexe-tele.service')
print('MCAP overlay detached; previous VR glove overlay and terminal collector restored. Data retained.')
