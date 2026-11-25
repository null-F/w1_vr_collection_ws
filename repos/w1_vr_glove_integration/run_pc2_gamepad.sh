#!/usr/bin/env bash
set -eo pipefail
source /home/dexforce/.dex_env.sh
source /home/dexforce/w1/install/setup.bash
set -u
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /usr/bin/python3 "$HERE/pc2_gamepad.py"
