"""FFG 串口传输：收发字节、缓存数据并提取完整协议帧。"""

from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

import serial

from .constants import FRAME_HEADER, MAX_FRAME_DATA_SIZE
from .protocol import try_parse_frame

FrameTuple = Tuple[int, bytes]


class SerialTransport:
    def __init__(self) -> None:
        self.serial_port: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._last_rx_mono = time.monotonic()
        self._rx_bytes = 0
        self._bad_frame_count = 0

    @property
    def is_open(self) -> bool:
        port = self.serial_port
        return bool(port is not None and port.is_open)

    def open(self, port: str, baudrate: int) -> bool:
        self.close()
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=0.001,
                write_timeout=0.05,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                exclusive=True,
            )
            self._buf.clear()
            self._last_rx_mono = time.monotonic()
            self._rx_bytes = 0
            self._bad_frame_count = 0
            return True
        except serial.SerialException:
            self.serial_port = None
            return False

    def close(self) -> None:
        port = self.serial_port
        self.serial_port = None
        self._buf.clear()
        if port is None:
            return
        try:
            cancel_read = getattr(port, "cancel_read", None)
            if cancel_read:
                cancel_read()
        except (OSError, serial.SerialException):
            pass
        try:
            if port.is_open:
                port.close()
        except (OSError, serial.SerialException):
            pass

    def write(self, data: bytes) -> bool:
        if not data or not self.is_open:
            return False
        assert self.serial_port is not None
        try:
            with self._lock:
                written = self.serial_port.write(data)
            return written == len(data)
        except (OSError, serial.SerialException):
            return False

    def read_frames(self) -> List[FrameTuple]:
        """读当前串口缓冲，返回解析成功的 (cmd, payload) 列表。"""
        self._pull_serial_into_buf()
        return self._extract_frames_from_buf()

    def seconds_since_rx(self) -> float:
        return time.monotonic() - self._last_rx_mono

    @property
    def rx_bytes(self) -> int:
        return self._rx_bytes

    @property
    def bad_frame_count(self) -> int:
        return self._bad_frame_count

    def _pull_serial_into_buf(self) -> None:
        if not self.is_open:
            return
        assert self.serial_port is not None
        try:
            waiting = self.serial_port.in_waiting
            if waiting <= 0:
                return
            chunk = self.serial_port.read(waiting)
        except (OSError, serial.SerialException):
            return
        if not chunk:
            return
        self._buf.extend(chunk)
        self._rx_bytes += len(chunk)
        self._last_rx_mono = time.monotonic()

    def _extract_frames_from_buf(self) -> List[FrameTuple]:
        frames: List[FrameTuple] = []
        while True:
            try:
                start = self._buf.index(FRAME_HEADER)
            except ValueError:
                self._buf.clear()
                break
            if start > 0:
                del self._buf[:start]

            if len(self._buf) < 4:
                break

            length = self._buf[2]
            if length > MAX_FRAME_DATA_SIZE:
                del self._buf[0]
                self._bad_frame_count += 1
                continue

            total = 3 + length + 1
            if len(self._buf) < total:
                break

            candidate = bytes(self._buf[:total])
            parsed = try_parse_frame(candidate)
            if parsed is None:
                del self._buf[0]
                self._bad_frame_count += 1
                continue

            del self._buf[:total]
            frames.append(parsed)
        return frames
