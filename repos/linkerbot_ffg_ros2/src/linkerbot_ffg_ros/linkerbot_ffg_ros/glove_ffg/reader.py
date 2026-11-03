"""FFG 手套读取器：组合串口传输和协议编解码，对外提供统一接口。"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from ..teleop.types import ForceCommand, GloveFrame, HandSide
from .constants import (
    CMD_ANGLE,
    CMD_ANGLE_COMPRESSED,
    CMD_FORCE,
    CMD_VERSION,
    COMPRESSED_MIN_VERSION,
    JOINT_COUNT,
    ANGLE_QUERY_PERIOD_SEC,
    JOINT_DATA_TIMEOUT_SEC,
    VERSION_QUERY_RETRY_COUNT,
    VERSION_QUERY_WAIT,
)
from .protocol import (
    decode_angles_compressed,
    decode_angles_float,
    decode_force_reply,
    decode_version,
    pack_angle_query,
    pack_force,
    pack_version_query,
)

from .transport import SerialTransport


def _parse_version_tuple(version: str) -> Optional[Tuple[int, int, int]]:
    parts = version.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


class GloveReader:
    def __init__(self) -> None:
        self._transport = SerialTransport()
        self.version: Optional[str] = None
        self.side: Optional[str] = None  # "left" | "right" | "unknown"
        self.joints_deg: List[float] = [0.0] * JOINT_COUNT
        self._has_joints = False
        self._use_compressed = False
        self._next_query_mono = 0.0
        self._joint_timestamp = 0.0
        self._joint_mono = 0.0
        self._decode_error_count = 0
        self._unknown_command_count = 0

    @property
    def is_open(self) -> bool:
        return self._transport.is_open

    @property
    def last_joint_mono(self) -> Optional[float]:
        """最近一次有效关节帧的 monotonic 时间；尚未收到则为 None。"""
        if not self._has_joints:
            return None
        return self._joint_mono

    @property
    def stats(self) -> dict[str, int]:
        """返回当前通信统计。"""
        return {
            "rx_bytes": self._transport.rx_bytes,
            "bad_frame_count": self._transport.bad_frame_count,
            "decode_error_count": self._decode_error_count,
            "unknown_command_count": self._unknown_command_count,
        }

    def open(self, port: str, baudrate: int) -> bool:
        ok = self._transport.open(port, baudrate)
        if not ok:
            return False
        self.version = None
        self.side = None
        self.joints_deg = [0.0] * JOINT_COUNT
        self._has_joints = False
        self._use_compressed = False
        self._next_query_mono = 0.0
        self._joint_mono = 0.0
        self._decode_error_count = 0
        self._unknown_command_count = 0
        return True

    def close(self) -> None:
        self._transport.close()
    def query_version(
        self,
        timeout: float = VERSION_QUERY_WAIT,
        retry: int = VERSION_QUERY_RETRY_COUNT,
    ) -> bool:
        """发 0x01 并等待版本应答。成功则更新 version/side。"""
        if not self.is_open:
            return False

        retry = max(1, retry)
        for _ in range(retry):
            if not self._transport.write(pack_version_query()):
                return False
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                self._ingest_frames()
                if self.version is not None and self.side in ("left", "right"):
                    return True
                time.sleep(0.003)
            self._ingest_frames()
            if self.version is not None and self.side in ("left", "right"):
                return True
        return self.version is not None and self.side in ("left", "right")
    def poll(self, send_angle_query: bool = True) -> None:
        """读串口更新内部状态；可选按频率发角度查询。"""
        self._ingest_frames()
        if not send_angle_query or not self.is_open:
            return
        now = time.monotonic()
        if now < self._next_query_mono:
            return
        self._next_query_mono = now + ANGLE_QUERY_PERIOD_SEC
        self._transport.write(pack_angle_query(compressed=self._use_compressed))
    def read(self) -> Optional[GloveFrame]:
        """返回最新手套帧；尚无有效角度或左右手未定时返回 None。"""
        self._ingest_frames()
        if not self._has_joints:
            return None
        if self._joint_mono <= 0.0 or time.monotonic() - self._joint_mono > JOINT_DATA_TIMEOUT_SEC:
            return None
        if self.side not in ("left", "right"):
            return None
        return GloveFrame(
            side=self.side,  # type: ignore[arg-type]
            joints_deg=list(self.joints_deg),
            timestamp=self._joint_timestamp,
            version=self.version,
            valid=True,
        )

    def send_force(self, values: List[float] | ForceCommand) -> bool:
        if isinstance(values, ForceCommand):
            force_values = list(values.values)
        else:
            force_values = list(values)
        if len(force_values) != 5:
            raise ValueError(f"force values must be length 5, got {len(force_values)}")
        return self._transport.write(pack_force(force_values))
    
    def _ingest_frames(self) -> None:
        for cmd, payload in self._transport.read_frames():
            self._handle_frame(cmd, payload)

    def _handle_frame(self, cmd: int, payload: bytes) -> None:
        try:
            if cmd == CMD_VERSION:
                version, side = decode_version(payload)
                self.version = version
                self.side = side
                parsed = _parse_version_tuple(version)
                self._use_compressed = (
                    parsed is not None and parsed >= COMPRESSED_MIN_VERSION
                )
                return

            if cmd == CMD_ANGLE:
                self.joints_deg = decode_angles_float(payload)
                self._has_joints = True
                self._joint_timestamp = time.time()
                self._joint_mono = time.monotonic()
                return

            if cmd == CMD_ANGLE_COMPRESSED:
                self.joints_deg = decode_angles_compressed(payload)
                self._has_joints = True
                self._joint_timestamp = time.time()
                self._joint_mono = time.monotonic()
                return

            if cmd == CMD_FORCE:
                decode_force_reply(payload)
                return

            self._unknown_command_count += 1
        except ValueError:
            self._decode_error_count += 1
