"""LinkerForce / LinkerH 关节向量 → LinkerZ 公共向量。

LinkerForce mapper 输出已是各型号在 LinkerH 协议下的 raw 0~255。
接 LinkerZ 时多数型号按下标直通；L20 为 20→16 重排；O30 可选交换 0/1。
"""

from __future__ import annotations

from typing import List, Sequence

from ..teleop.registry import mapper_spec

# LinkerH/LF L20(20) → LinkerZ L20(16)
# H: [0:5] roots, [5:10] abds, [10] thumb 横摆, [11:15] reserved, [15:20] tips
# Z: thumb(rotation,roll,root,tip), index(abd,root,tip), ... pinky(abd,root,tip)
_L20_H_TO_Z: tuple[int, ...] = (
    10,  # 0 thumb_rotation ← H 横摆
    5,   # 1 thumb_roll     ← H 侧摆
    0,   # 2 thumb_root
    15,  # 3 thumb_tip
    6,   # 4 index_abd
    1,   # 5 index_root
    16,  # 6 index_tip
    7,   # 7 middle_abd
    2,   # 8 middle_root
    17,  # 9 middle_tip
    8,   # 10 ring_abd
    3,   # 11 ring_root
    18,  # 12 ring_tip
    9,   # 13 pinky_abd
    4,   # 14 pinky_root
    19,  # 15 pinky_tip
)


def expected_z_dims(robot: str) -> int:
    return mapper_spec(robot).n_out


def positions_to_raw(positions: Sequence[float]) -> List[float]:
    """钳到 0~255 并 round 成 raw float（HandJointCommand.values）。"""
    if not positions:
        raise ValueError("position is empty")
    out: List[float] = []
    for value in positions:
        v = float(value)
        if v < 0.0:
            v = 0.0
        elif v > 255.0:
            v = 255.0
        out.append(float(round(v)))
    return out


def remap_for_linker_z(
    robot: str,
    positions: Sequence[float],
    *,
    o30_swap_01: bool = False,
) -> List[float]:
    """把 LinkerForce/LinkerH 向量变成 LinkerZ set_angles 公共向量（仍为 raw）。"""
    spec = mapper_spec(robot)
    key = (robot or "").strip().lower()
    if len(positions) != spec.n_in:
        raise ValueError(
            f"{key}: expected {spec.n_in} LinkerH positions, got {len(positions)}"
        )

    raw = positions_to_raw(positions)

    if spec.kind == "identity":
        return raw

    if spec.kind == "o30":
        if o30_swap_01:
            out = list(raw)
            out[0], out[1] = out[1], out[0]
            return out
        return raw

    if spec.kind == "l20":
        return [raw[i] for i in _L20_H_TO_Z]

    raise KeyError(f"未实现的 LinkerZ remap: {spec.kind}")
