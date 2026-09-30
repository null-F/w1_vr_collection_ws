#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path, expected in json.loads((HERE / 'vendor_hashes.json').read_text()).items():
    file = Path('/home/dexforce/w1/dexe_teleoperate') / path
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
        raise SystemExit('Vendor version changed; review LinkerHand VR overlay before startup: ' + path)
print('LinkerHand VR overlay: vendor hashes verified')
