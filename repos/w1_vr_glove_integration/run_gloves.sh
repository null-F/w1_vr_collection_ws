#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
INTEGRATION=/home/dexforce/linkerhand/repos/w1_glove_integration
source "$INTEGRATION/env.sh"
exec 9>"$LINKER_W1_ROOT/runtime/gloves.lock"
flock -n 9 || { echo 'Glove program is already running.' >&2; exit 1; }
# Files/config check only; no sound device is opened here.
python "$HERE/local_voice.py" --check
if [[ "$W1_GLOVE_SDK" == ffg ]]; then
    python "$INTEGRATION/ffg_entry.py" --check
fi
test -d /sys/module/ch341 || { echo 'CH341 preparation service is not ready.' >&2; exit 1; }
ports_text=$(python "$INTEGRATION/glove_ports.py")
mapfile -t ports <<< "$ports_text"
ports_arg="['${ports[0]}','${ports[1]}']"
python "$INTEGRATION/w1_hand_bridge.py" &
bridge_pid=$!
cleanup() { kill -TERM "$bridge_pid" 2>/dev/null || true; wait "$bridge_pid" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM
if [[ "$W1_GLOVE_SDK" == ffg ]]; then
    python "$INTEGRATION/ffg_entry.py" --vr-events
else
    python "$HERE/glove_entry.py" --ros-args \
        -p calibration:=True -p "ports:=$ports_arg" -p baudrate:=2000000 -p auto_scan:=false \
        -r /cb_left_hand_control_cmd:=/linkerhand/glove/left/motor_cmd \
        -r /cb_right_hand_control_cmd:=/linkerhand/glove/right/motor_cmd
fi
