"""根据标定姿态差分计算 21 路基准值和有效行程。"""

from __future__ import annotations

from typing import List, Mapping, Sequence

JOINT_COUNT = 21

# 每项为 (终点姿态, 起点姿态, 参与计算的通道索引)。
_RANGE_RULES = (
    ("open_full", "adduct", (1, 5, 9, 13, 17)),
    ("thumbs_up", "adduct", (6, 7, 8, 10, 11, 12, 14, 15, 16, 18, 19, 20)),
    ("thumb_flex", "thumbs_up", (0, 2, 3, 4)),
)


def _require_poses(poses: Mapping[str, Sequence[float]], required: set[str]) -> None:
    missing = sorted(required - set(poses.keys()))
    if missing:
        raise KeyError(f"缺少姿态: {missing}")
    for key in required:
        if len(poses[key]) != JOINT_COUNT:
            raise ValueError(f"姿态 {key} 必须为长度 {JOINT_COUNT}")


def _diff(a: Sequence[float], b: Sequence[float]) -> List[float]:
    if len(a) != JOINT_COUNT or len(b) != JOINT_COUNT:
        raise ValueError(f"姿态必须为长度 {JOINT_COUNT}")
    return [float(a[i]) - float(b[i]) for i in range(JOINT_COUNT)]


def compute_joint_range_vector(poses: Mapping[str, Sequence[float]]) -> List[float]:
    """按规则从五态差分填充新的 21 维数组。"""
    _require_poses(poses, {"open_full", "adduct", "thumbs_up", "thumb_flex"})

    out = [0.0] * JOINT_COUNT
    for left_key, right_key, indices in _RANGE_RULES:
        delta = _diff(poses[left_key], poses[right_key])
        for idx in indices:
            out[idx] = delta[idx]
    return out


def compute_base_vector(poses: Mapping[str, Sequence[float]]) -> List[float]:
    """BASE：五指并拢的 21 维。手套最大值 = base + joint_range。"""
    _require_poses(poses, {"adduct"})
    return [float(x) for x in poses["adduct"]]

