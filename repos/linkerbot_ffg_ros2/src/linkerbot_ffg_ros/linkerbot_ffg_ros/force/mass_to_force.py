"""
计算力反馈大小的公式
"""

from __future__ import annotations

import math


def mass_to_force(
    mass: float,
    *,
    max_force: int,
    trigger_mass: int = 200,
    mass_max: int = 2000,
    force_onset: int = 150,
) -> float:
    """把单指 mass(g)映射成 0~max_force 之间的力值。"""
    if not math.isfinite(mass):
        raise ValueError(f"mass 必须是有限值: {mass}")
    if mass < 0:
        raise ValueError(f"mass 不可为负: {mass}")
    if mass_max <= trigger_mass:
        raise ValueError("mass_max 必须大于 trigger_mass")
    if mass <= trigger_mass:
        return 0.0
    # max_force 小于 force_onset 时，输出为 max_force。
    peak = max(max_force, force_onset)
    ratio = (mass - trigger_mass) / (mass_max - trigger_mass)
    ratio = max(0.0, min(1.0, ratio))
    value = force_onset + ratio * (peak - force_onset)
    return min(value, float(max_force))
