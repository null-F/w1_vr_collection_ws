#!/usr/bin/env python3
"""Select only USB devices physically identified as CH340/CH341 gloves."""
import os
from pathlib import Path


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
                if (vendor.read_text().strip().lower(), product.read_text().strip().lower()) == ('1a86', '7523'):
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


if __name__ == '__main__':
    try:
        print('\n'.join(checked_glove_ports()))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
