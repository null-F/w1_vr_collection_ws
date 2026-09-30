#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/env.sh"
exec 9>"$LINKER_W1_ROOT/runtime/hands.lock"
flock -n 9 || { echo 'Independent hand driver is already running.' >&2; exit 1; }
# VR pose_server may run at the same time. This driver only listens on
# /linkerhand/w1/ee/*/command, so Quest triggers do not move the hands.
for port in /dev/ttyUSB_485_1 /dev/ttyUSB_485_2; do
    test -r "$port" && test -w "$port" || { echo "Hand RS485 port unavailable: $port" >&2; exit 1; }
done
EE_BIN=/home/dexforce/w1/install/ee_devices/lib/ee_devices/ee_server
test -x "$EE_BIN"
mkdir -p "$LINKER_W1_ROOT/runtime/ee_driver/scripts"
cp "$HERE/config/ee_devices.json" "$LINKER_W1_ROOT/runtime/ee_driver/scripts/ee_devices.json"
echo 'Stopping only dexe-devices.service to release its hand serial ports; arm controller is unchanged.'
sudo systemctl stop dexe-devices.service
if pgrep -f '^/home/dexforce/w1/.*/ee_devices/(ee_server|ee_sim_server)( |$)' >/dev/null; then
    echo 'A vendor hand process is still running; refusing a second serial owner.' >&2
    exit 1
fi
cd "$LINKER_W1_ROOT/runtime/ee_driver"
echo 'Starting original L6 driver with independent left/right config and isolated command topics.'
# Factory speed is 0..100; 100 matches the original LinkerHand SDK speed 255.
exec "$EE_BIN" --ros-args \
    -r /control/ee/left:=/linkerhand/w1/ee/left/command \
    -r /control/ee/right:=/linkerhand/w1/ee/right/command \
    -p ee_left_server:speed:=100 -p ee_right_server:speed:=100
