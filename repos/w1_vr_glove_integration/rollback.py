#!/usr/bin/env python3
"""Remove only this deployment's unit links/drop-ins, restoring baseline settings."""
import json
import os
from pathlib import Path
import subprocess
HERE=Path(__file__).resolve().parent
if os.geteuid()!=0:
    raise SystemExit('Run with sudo')
baseline=json.loads((HERE/'deployment_baseline.json').read_text())
links={
 '/etc/systemd/system/dexe-devices.service.d/50-linkerhand-hands.conf':HERE/'50-linkerhand-hands.conf',
 '/etc/systemd/system/dexe-tele.service.d/50-linkerhand-vr-glove.conf':HERE/'50-linkerhand-vr-glove.conf',
 '/etc/systemd/system/linkerhand-w1-glove-manager.service':HERE/'linkerhand-w1-glove-manager.service',
 '/etc/systemd/system/linkerhand-w1-glove-usb.service':HERE/'linkerhand-w1-glove-usb.service',
}
for path,target in links.items():
 p=Path(path)
 if p.exists() or p.is_symlink():
  if not p.is_symlink() or p.resolve()!=target:raise SystemExit('Unexpected file at '+path)
def ctl(*args):subprocess.run(['systemctl',*args],check=True)
ctl('stop','linkerhand-w1-glove-manager.service')
ctl('stop','dexe-tele.timer','dexe-tele.service','dexe-devices.service','linkerhand-w1-glove-usb.service')
ctl('disable','linkerhand-w1-glove-manager.service')
for path,target in links.items():
 p=Path(path)
 if p.is_symlink():p.unlink()
for p in [Path('/etc/systemd/system/dexe-devices.service.d'),Path('/etc/systemd/system/dexe-tele.service.d')]:
 if p.exists() and not list(p.iterdir()):p.rmdir()
ctl('daemon-reload')
for unit,state in baseline['units'].items():
 if state['enabled'] in ('enabled','disabled'):
  ctl('enable' if state['enabled']=='enabled' else 'disable',unit)
for unit in ['dexe-devices.service','dexe-tele.service']:
 if baseline['units'][unit]['active']=='active':ctl('start',unit)
print('Overlay detached. Original boot-enable states restored. Vendor source, data and calibration retained.')
