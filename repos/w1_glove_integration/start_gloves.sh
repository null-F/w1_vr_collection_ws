#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/env.sh"
exec 9>"$LINKER_W1_ROOT/runtime/gloves.lock"
flock -n 9 || { echo 'Glove program is already running.' >&2; exit 1; }
# VR pose_server may run at the same time. Hand targets stay on the glove bridge.
preview=()
calibration=True
ffg_args=()
for arg in "$@"; do
    case "$arg" in
        --preview) preview=(--preview) ;;
        --reuse-calibration)
            if [[ "$W1_GLOVE_SDK" == legacy ]]; then
                test -s "$LINKER_W1_ROOT/runtime/calibration/glove/jointangle_data.tmp" || { echo 'No saved legacy calibration.' >&2; exit 1; }
            fi
            calibration=False
            ffg_args=(--reuse-calibration) ;;
        *) echo "Usage: $0 [--preview] [--reuse-calibration]" >&2; exit 2 ;;
    esac
done
if [[ "$W1_GLOVE_SDK" == ffg ]]; then
    python "$HERE/ffg_entry.py" --check
fi
bash "$HERE/prepare_glove_usb.sh"
ports_text=$(python "$HERE/glove_ports.py")
mapfile -t ports <<< "$ports_text"
ports_arg="['${ports[0]}','${ports[1]}']"
python "$HERE/w1_hand_bridge.py" "${preview[@]}" &
bridge_pid=$!
cleanup() { kill -TERM "$bridge_pid" 2>/dev/null || true; wait "$bridge_pid" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM
if [[ "$W1_GLOVE_SDK" == ffg ]]; then
    echo 'Follow the new SDK five-pose calibration prompts. Old .tmp calibration is not reused.'
    python "$HERE/ffg_entry.py" "${ffg_args[@]}"
else
    echo 'Follow the ORIGINAL glove calibration prompts. Physical follow starts after calibration succeeds.'
    python -m linkerhand_retarget.handretarget --ros-args \
        -p "calibration:=$calibration" -p "ports:=$ports_arg" -p baudrate:=2000000 -p auto_scan:=false \
        -r /cb_left_hand_control_cmd:=/linkerhand/glove/left/motor_cmd \
        -r /cb_right_hand_control_cmd:=/linkerhand/glove/right/motor_cmd
fi
