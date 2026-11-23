"""Shared-hub selection and reset on a fake sysfs tree. No USB access."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import glove_ports  # noqa: E402


def device(root, name, vid, pid, cls='00', bus=1, dev=1):
    d = root / name
    d.mkdir()
    for key, value in dict(idVendor=vid, idProduct=pid, bDeviceClass=cls, busnum=bus, devnum=dev).items():
        (d / key).write_text(f'{value}\n')
    (root / f'{name}:1.0').mkdir()
    return d


def test_shared_hub_is_selected(tmp_path):
    hub = device(tmp_path, '1-2.1.3', '05e3', '0610', cls='09', dev=21)
    device(tmp_path, '1-2.1.3.2', '1a86', '7523')
    device(tmp_path, '1-2.1.3.3', '1a86', '7523')
    device(tmp_path, '1-2.2', '0403', '6010')
    assert glove_ports.glove_hub(tmp_path) == hub


def test_separate_ports_are_not_reset(tmp_path):
    device(tmp_path, '1-2.1.3', '05e3', '0610', cls='09')
    device(tmp_path, '1-2.1.3.2', '1a86', '7523')
    device(tmp_path, '1-3.2', '1a86', '7523')
    assert glove_ports.glove_hub(tmp_path) is None


def test_hub_with_other_devices_is_refused(tmp_path):
    device(tmp_path, '1-2.1.3', '05e3', '0610', cls='09')
    device(tmp_path, '1-2.1.3.2', '1a86', '7523')
    device(tmp_path, '1-2.1.3.3', '1a86', '7523')
    gamepad = device(tmp_path, '1-2.1.3.4', '046d', 'c21f')
    (gamepad / 'product').write_text('Wireless Gamepad F710\n')
    with pytest.raises(RuntimeError, match='1-2.1.3.4 046d:c21f Wireless Gamepad F710'):
        glove_ports.glove_hub(tmp_path)


def test_missing_glove_is_reported(tmp_path):
    device(tmp_path, '1-2.1.3', '05e3', '0610', cls='09')
    device(tmp_path, '1-2.1.3.2', '1a86', '7523')
    with pytest.raises(RuntimeError, match='found 1'):
        glove_ports.glove_hub(tmp_path)


def test_reset_waits_for_both_ports(tmp_path, monkeypatch):
    hub = device(tmp_path, '1-2.1.3', '05e3', '0610', cls='09', bus=1, dev=21)
    monkeypatch.setattr(glove_ports, 'glove_hub', lambda: hub)
    opened, resets = [], []
    monkeypatch.setattr(glove_ports.os, 'open', lambda path, flags: opened.append(str(path)) or 7)
    monkeypatch.setattr(glove_ports.os, 'close', lambda fd: None)
    monkeypatch.setattr(glove_ports.fcntl, 'ioctl', lambda fd, req, arg: resets.append(req))
    answers = iter([RuntimeError('not yet'), ['/dev/ttyUSB3', '/dev/ttyUSB4']])

    def ports():
        value = next(answers)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(glove_ports, 'checked_glove_ports', ports)
    monkeypatch.setattr(glove_ports.time, 'sleep', lambda _: None)
    assert glove_ports.reset_glove_hub() == ['/dev/ttyUSB3', '/dev/ttyUSB4']
    assert opened == ['/dev/bus/usb/001/021'] and resets == [21780]
