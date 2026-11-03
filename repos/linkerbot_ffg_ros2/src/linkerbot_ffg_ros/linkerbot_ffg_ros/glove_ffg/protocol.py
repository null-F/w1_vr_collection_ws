"""FFG 手套协议的帧组装、校验和 payload 编解码。"""

from __future__ import annotations

import math
import struct
from typing import List, Optional, Tuple

from .constants import (
    CMD_ANGLE,
    CMD_ANGLE_COMPRESSED,
    CMD_FORCE,
    CMD_VERSION,
    FRAME_HEADER,
    JOINT_COUNT,
    MAX_ANGLE_DEG,
    MAX_FRAME_DATA_SIZE,
    MIN_ANGLE_DEG,
)


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def pack_frame(cmd: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_FRAME_DATA_SIZE:
        raise ValueError(f" 发给手套的数据太长，长度为: {len(payload)}")
    header = struct.pack("BBB", FRAME_HEADER, cmd & 0xFF, len(payload))
    body = header + payload
    return body + struct.pack("B", checksum(body))


def pack_version_query() -> bytes:
    return pack_frame(CMD_VERSION)


def pack_angle_query(compressed: bool = False) -> bytes:
    cmd = CMD_ANGLE_COMPRESSED if compressed else CMD_ANGLE
    return pack_frame(cmd)


def pack_force(values: List[float]) -> bytes:
    if len(values) != 5:
        raise ValueError(f"错误！！手套受到的力反馈数据长度不是5,是 {len(values)}")

    checked: List[float] = []
    for value in values:
        try:
            force = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"force 必须是数值: {value}") from e
        if not math.isfinite(force):
            raise ValueError(f"force 必须是有限值: {force}")
        if force < 0:
            raise ValueError(f"force 不可为负: {force}")
        checked.append(force)

    payload = struct.pack("<5f", *checked)
    return pack_frame(CMD_FORCE, payload)

def try_parse_frame(raw: bytes) -> Optional[Tuple[int, bytes]]:
    """
    解析一整帧。
    成功返回 (cmd, payload)；失败返回 None。
    """
    if len(raw) < 4:
        return None
    if raw[0] != FRAME_HEADER:
        return None
    cmd = raw[1]
    length = raw[2]
    if length > MAX_FRAME_DATA_SIZE:
        return None
    total = 3 + length + 1
    if len(raw) < total:
        return None
    payload = raw[3 : 3 + length]
    expect = checksum(raw[: 3 + length])
    actual = raw[3 + length]
    if expect != actual:
        return None
    return cmd, payload

def decode_version(payload: bytes) -> Tuple[str, str]:
    """
    返回 (版本号, 手型号)
    side: "left" | "right" | "unknown"
    """
    if len(payload) < 5:
        raise ValueError(f"返回的版本数据太短: {len(payload)}")
    value = struct.unpack("<I", payload[:4])[0]
    value_str = f"{value:05d}"
    major = int(value_str[0])
    minor = int(value_str[1:3])
    sub = int(value_str[3:5])
    version = f"{major}.{minor}.{sub}"
    code = payload[4]
    if code == 0:
        side = "left"
    elif code == 1:
        side = "right"
    else:
        side = "unknown"
    return version, side

def decode_angles_float(payload: bytes) -> List[float]:
    """0x03：21 × float32 小端，单位：度。"""
    if len(payload) != JOINT_COUNT * 4:
        raise ValueError(
            f"浮点数角度数据的长度为{len(payload)}, 期望的长度为{JOINT_COUNT * 4}"
        )
    degrees: List[float] = []
    for i in range(JOINT_COUNT):
        val = struct.unpack("<f", payload[i * 4 : (i + 1) * 4])[0]
        if not math.isfinite(val):
            raise ValueError(f"non-finite angle at index {i}")
        if val < MIN_ANGLE_DEG or val > MAX_ANGLE_DEG:
            raise ValueError(f"angle out of range at index {i}: {val}")
        degrees.append(val)
    return degrees

def decode_angles_compressed(payload: bytes) -> List[float]:
    """0x05：21 × uint16 小端，值/100 = 度。单位：度。"""
    if len(payload) != JOINT_COUNT * 2:
        raise ValueError(
            f"该版本的字节长度为 {len(payload)}, 期望长度应该为{JOINT_COUNT * 2}"
        )
    degrees: List[float] = []
    for i in range(JOINT_COUNT):
        raw = struct.unpack("<H", payload[i * 2 : (i + 1) * 2])[0]
        val = raw / 100.0
        if val < MIN_ANGLE_DEG or val > MAX_ANGLE_DEG:
            raise ValueError(f"角度超过范围{i}: {val}")
        degrees.append(val)
    return degrees

def decode_force_reply(payload: bytes) -> List[int]:
    """0x04 应答：int16 小端（按协议文档）。"""
    if len(payload) % 2 != 0:
        raise ValueError(f"手套里的应答帧长度有误, 长度 {len(payload)}")
    values: List[int] = []
    for i in range(len(payload) // 2):
        values.append(struct.unpack("<h", payload[i * 2 : (i + 1) * 2])[0])
    return values
