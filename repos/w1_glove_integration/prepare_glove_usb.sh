#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/dexforce/linkerhand
MODULE="$ROOT/runtime/drivers/linux-5.15.148-ch341/ch341.ko"
HUB_RULE="$ROOT/repos/w1_glove_integration/60-linkerhand-glove-hub.rules"
test "$(uname -r)" = 5.15.148-rt-tegra || { echo 'Kernel changed; rebuild the glove driver for this kernel.' >&2; exit 1; }
# brltty-udev claims the CH340 gloves at boot before ch341 is loaded and leaves them hung (-110).
echo 'Blocking brltty-udev so it cannot claim the gloves.'
sudo systemctl mask --now brltty-udev.service
if ! cmp -s "$HUB_RULE" /etc/udev/rules.d/60-linkerhand-glove-hub.rules; then
    sudo install -m 0644 "$HUB_RULE" /etc/udev/rules.d/60-linkerhand-glove-hub.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=05e3 --attr-match=idProduct=0610
fi
if ! test -d /sys/module/ch341; then
    test -f "$MODULE" || { echo "Missing glove driver: $MODULE" >&2; exit 1; }
    sudo insmod "$MODULE"
fi
udevadm settle --timeout=30 || echo 'udev settle timed out; continuing because the glove driver step already finished.'
echo 'CH340/CH341 glove serial driver is ready.'
