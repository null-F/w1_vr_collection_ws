#!/usr/bin/env python3
"""Select only USB devices physically identified as CH340/CH341 gloves."""
import argparse
import fcntl
import os
from pathlib import Path
import time

GLOVE_ID = ('1a86', '7523')
USBDEVFS_RESET = ord('U') << 8 | 20
SYSFS_USB = Path('/sys/bus/usb/devices')


def _usb_id(path):
    return tuple((path / name).read_text().strip().lower() for name in ('idVendor', 'idProduct'))


def _product(path):
    try:
        return (path / 'product').read_text().strip()
    except OSError:
        return ''


def glove_ports():
    ports = []
    for entry in sorted(Path('/sys/class/tty').glob('*')):
        name = entry.name
        if not name.startswith(('ttyUSB', 'ttyCH341USB', 'ttyACM')):
            continue
        target = (entry / 'device').resolve()
        for parent in [target, *target.parents]:
            vendor, product = parent / 'idVendor', parent / 'idProduct'
            if vendor.exists() and product.exists():
                if (vendor.read_text().strip().lower(), product.read_text().strip().lower()) == GLOVE_ID:
                    ports.append('/dev/' + name)
                break
    return ports


def checked_glove_ports():
    ports = glove_ports()
    if len(ports) != 2:
        raise RuntimeError(f'Expected two CH340 glove serial ports; found {ports}. USB driver may be missing; do not scan robot serial ports.')
    for port in ports:
        if not os.access(port, os.R_OK | os.W_OK):
            raise RuntimeError(f'No read/write permission: {port}')
    return ports


def glove_hub(sysfs=SYSFS_USB):
    """Return the one hub that carries both gloves and nothing else."""
    gloves = [d for d in sysfs.iterdir() if ':' not in d.name and (d / 'idVendor').exists() and _usb_id(d) == GLOVE_ID]
    if len(gloves) != 2:
        raise RuntimeError(f'Expected two CH340 gloves on USB; found {len(gloves)}')
    hubs = {d.name.rsplit('.', 1)[0] for d in gloves if '.' in d.name}
    if len(hubs) != 1 or any('.' not in d.name for d in gloves):
        return None
    hub = sysfs / hubs.pop()
    if (hub / 'bDeviceClass').read_text().strip() != '09':
        return None
    children = [d for d in sysfs.glob(hub.name + '.*') if ':' not in d.name and d.name.count('.') == hub.name.count('.') + 1]
    others = sorted(set(children) - set(gloves))
    if others:
        names = ', '.join(f"{d.name} {':'.join(_usb_id(d))} {_product(d)}".strip() for d in others)
        raise RuntimeError(f'Glove hub {hub.name} also carries other USB devices ({names}); '
                           'move them to another port, refusing to reset it')
    return hub


def reset_glove_hub(timeout=8.0):
    """Reset the shared glove hub so each session gets a first open.

    Reopening a CH340 on this hub after closing it hangs with -110; resetting
    the stuck glove nodes themselves does not recover them.
    """
    hub = glove_hub()
    if hub is None:
        return checked_glove_ports()
    node = Path('/dev/bus/usb') / f"{int((hub / 'busnum').read_text()):03d}" / f"{int((hub / 'devnum').read_text()):03d}"
    fd = os.open(node, os.O_WRONLY)
    try:
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
    finally:
        os.close(fd)
    deadline = time.monotonic() + timeout
    while True:
        try:
            return checked_glove_ports()
        except RuntimeError:
            if time.monotonic() > deadline:
                raise
            time.sleep(.2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset-hub', action='store_true', help='Reset the hub shared by both gloves, then wait for both ports')
    args = parser.parse_args()
    try:
        print('\n'.join(reset_glove_hub() if args.reset_hub else checked_glove_ports()))
    except (RuntimeError, OSError) as exc:
        raise SystemExit(f'{exc}') from exc
