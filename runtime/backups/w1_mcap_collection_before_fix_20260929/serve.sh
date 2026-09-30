#!/usr/bin/env bash
# Resident recorder. Source the robot DDS env, then stay in the foreground.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1090
set +u
source /home/dexforce/.dex_env.sh
set -u
MCAP_PREFIX=/home/dexforce/linkerhand/runtime/mcap_prefix/opt/ros/humble
if [[ -d "$MCAP_PREFIX/lib" ]]; then
    export AMENT_PREFIX_PATH="$MCAP_PREFIX${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}"
    export LD_LIBRARY_PATH="$MCAP_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec python3 "$HERE/recorder.py" serve "$@"
