"""L10（L20lite）：手套 u[21] → 10 路电机。

电机下标（0 基）← 手套下标，及开/合端点：
   0 ← u[2] 与 u[4]  open=255 closed=  0    拇指根部
       （两路各映射一次，变化量大的那路生效）
   1 ← u[1]   open=255 closed=  0    拇指侧摆
   2 ← u[6] 与 u[8]   open=255 closed=  0    食指根部
   3 ← u[10] 与 u[12] open=255 closed=  0    中指根部
   4 ← u[14] 与 u[16] open=255 closed=  0    无名指根部
   5 ← u[18] 与 u[20] open=255 closed=  0    小指根部
       （2–5 各两路映射一次，变化量大的那路生效）
   6 ← u[5]   open=  0 closed=255    食指侧摆        (反向)
   7 ← u[13]  open=  0 closed=255    无名指侧摆      (反向)
   8 ← u[17]  open=  0 closed=255    小指侧摆        (反向)
   9 ← u[1]   open=255 closed=  0    拇指旋转

motor = open + u * (closed - open)；无效通道 (active=False) 用 open。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .o6 import u_to_motor
from .smoothing import DEFAULT_SMOOTH_ALPHA, DEFAULT_SMOOTH_MAX_STEP, MotorSmoother

ROBOT_NAME = "l10"
NUM_MOTORS = 10

GLOVE_INDICES: Tuple[int, ...] = (
    4, 1,                 # 0-1  thumb base / horizontal abd（0 再与 u[2] 比变化量）
    8, 12, 16, 20,        # 2-5  four-finger base（再与 6/10/14/18 比变化量）
    5, 13, 17,            # 6-8  index / ring / pinky abd
    1,                    # 9    thumb rotation
)

MOTOR_OPEN: Tuple[float, ...] = (
    255.0, 200.0,
    255.0, 255.0, 255.0, 255.0,
    0.0, 0.0, 0.0,
    255.0,
)

MOTOR_CLOSED: Tuple[float, ...] = (
    0.0, 50.0,
    0.0, 0.0, 0.0, 0.0,
    255.0, 255.0, 255.0,
    80.0,
)

MOTOR_FIST = MOTOR_CLOSED

# 这些电机由两路手套共同决定，取变化量更大的那路。
_MAX_CHANGE_SOURCES: dict = {
    0: (2, 4),
    2: (6, 8),
    3: (10, 12),
    4: (14, 16),
    5: (18, 20),
}

JOINT_NAMES: List[str] = [
    "拇指根部",
    "拇指侧摆",
    "食指根部",
    "中指根部",
    "无名指根部",
    "小指根部",
    "食指侧摆",
    "无名指侧摆",
    "小指侧摆",
    "拇指旋转",
]


def map_u_to_motors(
    u: Sequence[float],
    active: Sequence[bool],
    *,
    motor_open: Sequence[float] = MOTOR_OPEN,
    motor_closed: Sequence[float] = MOTOR_CLOSED,
) -> List[float]:
    """u[21] + active[21] → 10 路电机值。"""
    if len(u) != 21 or len(active) != 21:
        raise ValueError("u/active must be length 21")
    if len(motor_open) != NUM_MOTORS or len(motor_closed) != NUM_MOTORS:
        raise ValueError(f"motor_open/closed must be length {NUM_MOTORS}")
    if len(GLOVE_INDICES) != NUM_MOTORS:
        raise ValueError("GLOVE_INDICES length mismatch")

    out: List[float] = []
    for motor_i, glove_i in enumerate(GLOVE_INDICES):
        open_v = float(motor_open[motor_i])
        closed_v = float(motor_closed[motor_i])
        sources = _MAX_CHANGE_SOURCES.get(motor_i, (glove_i,))
        values = [_motor_from_glove(u, active, i, open_v, closed_v) for i in sources]
        if len(values) > 1:
            out.append(max(values, key=lambda value: _closing_delta(value, open_v, closed_v)))
        else:
            out.append(values[0])
    return out


def _motor_from_glove(
    u: Sequence[float],
    active: Sequence[bool],
    glove_i: int,
    open_v: float,
    closed_v: float,
) -> float:
    if not active[glove_i]:
        return open_v
    return u_to_motor(float(u[glove_i]), open_v, closed_v)


def _closing_delta(value: float, open_v: float, closed_v: float) -> float:
    span = closed_v - open_v
    if span == 0.0:
        return 0.0
    progress = (value - open_v) / span
    if progress < 0.0:
        progress = 0.0
    elif progress > 1.0:
        progress = 1.0
    return progress * abs(span)


__all__ = [
    "ROBOT_NAME",
    "NUM_MOTORS",
    "GLOVE_INDICES",
    "MOTOR_OPEN",
    "MOTOR_CLOSED",
    "MOTOR_FIST",
    "JOINT_NAMES",
    "map_u_to_motors",
    "MotorSmoother",
    "DEFAULT_SMOOTH_ALPHA",
    "DEFAULT_SMOOTH_MAX_STEP",
]
