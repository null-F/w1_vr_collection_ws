#!/usr/bin/env bash
set -euo pipefail
source /home/dexforce/linkerhand/repos/w1_glove_integration/env.sh
exec 9>"$LINKER_W1_ROOT/runtime/hands.lock"
flock -n 9 || { echo 'Independent hand driver is already running.' >&2; exit 1; }
for port in /dev/ttyUSB_485_1 /dev/ttyUSB_485_2; do
    test -r "$port" && test -w "$port" || { echo "Hand RS485 port unavailable: $port" >&2; exit 1; }
done
mkdir -p "$LINKER_W1_ROOT/runtime/ee_driver/scripts"
cp "$LINKER_W1_ROOT/repos/w1_glove_integration/config/ee_devices.json" "$LINKER_W1_ROOT/runtime/ee_driver/scripts/ee_devices.json"
cd "$LINKER_W1_ROOT/runtime/ee_driver"
exec /home/dexforce/w1/install/ee_devices/lib/ee_devices/ee_server --ros-args \
    -r /control/ee/left:=/linkerhand/w1/ee/left/command \
    -r /control/ee/right:=/linkerhand/w1/ee/right/command \
    -p ee_left_server:speed:=100 -p ee_right_server:speed:=100
