"""锁住当前手套帧的帧头、校验和、侧别和角度长度检查。"""

import pytest

from linkerbot_ffg_ros.glove_ffg.protocol import (
    decode_angles_compressed,
    decode_angles_float,
    decode_version,
    pack_version_query,
    try_parse_frame,
)


def test_version_query_frame_parses():
    frame = pack_version_query()
    assert frame[0] == 0x5D
    assert frame[1] == 0x01
    assert frame[2] == 0
    assert try_parse_frame(frame) == (0x01, b"")


def test_bad_checksum_is_rejected():
    frame = bytearray(pack_version_query())
    frame[-1] ^= 0xFF
    assert try_parse_frame(bytes(frame)) is None


def test_version_payload_decodes_side():
    assert decode_version(b"\x00\x00\x00\x00\x00")[1] == "left"
    assert decode_version(b"\x00\x00\x00\x00\x01")[1] == "right"


def test_angle_payload_wrong_length():
    with pytest.raises(ValueError):
        decode_angles_float(b"")
    with pytest.raises(ValueError):
        decode_angles_compressed(b"\x00" * 4)
