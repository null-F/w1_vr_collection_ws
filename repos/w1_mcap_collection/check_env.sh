#!/usr/bin/env bash
# Read-only dependency/plugin check: no ROS node, recording, or service changes.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/env.sh" --check-only
"$MCAP_PYTHON" - "$MCAP_PREFIX" <<'PY'
import ctypes
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys

if sys.prefix == sys.base_prefix or sys.version_info[:2] != (3, 10):
    raise SystemExit('Expected the dedicated PC1 Python 3.10 virtual environment')

modules = [
    'rclpy', 'yaml', 'PIL.Image', 'mcap.reader', 'sensor_msgs.msg',
    'std_msgs.msg', 'std_srvs.srv', 'rcl_interfaces.srv', 'rosbag2_py',
]
paths = {name: importlib.import_module(name).__file__ for name in modules}
version = importlib.metadata.version('mcap')
if version != '1.5.0':
    raise SystemExit(f'Expected mcap==1.5.0, found {version}')

# Registry discovery alone does not prove the shared library can load.
library = Path(sys.argv[1]) / 'lib/librosbag2_storage_mcap.so'
ctypes.CDLL(str(library))
import rosbag2_py
writers = sorted(rosbag2_py.get_registered_writers())
if 'mcap' not in writers:
    raise SystemExit(f'MCAP writer is not registered: {writers}')
print(json.dumps({'status': 'ok', 'python': sys.executable, 'mcap': version,
                  'plugin': str(library), 'writers': writers, 'modules': paths}, indent=2))
PY
