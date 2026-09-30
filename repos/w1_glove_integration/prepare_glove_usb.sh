#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/dexforce/linkerhand
MODULE="$ROOT/runtime/drivers/linux-5.15.148-ch341/ch341.ko"
test "$(uname -r)" = 5.15.148-rt-tegra || { echo 'Kernel changed; rebuild the glove driver for this kernel.' >&2; exit 1; }
echo 'Temporarily blocking brltty-udev for this boot so replugging does not reclaim the gloves.'
sudo systemctl mask --runtime --now brltty-udev.service
if ! test -d /sys/module/ch341; then
    test -f "$MODULE" || { echo "Missing glove driver: $MODULE" >&2; exit 1; }
    sudo insmod "$MODULE"
fi
udevadm settle --timeout=30 || echo 'udev settle timed out; continuing because the glove driver step already finished.'
echo 'CH340/CH341 glove serial driver is ready.'
