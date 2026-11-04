"""O6：从手套归一化 u[21] 选出 6 路，线性映射到电机 0~255。

通道约定（0 基下标）：
  motor[0] ← u[4]   thumb_tip
  motor[1] ← u[1]   thumb_root
  motor[2] ← u[8]   index_tip
  motor[3] ← u[12]  middle_tip
  motor[4] ← u[16]  ring_tip
  motor[5] ← u[20]  pinky_tip

张开：全 255；合上默认全 0：motor = 255 + u * (0 - 255) = (1-u)*255
无效通道（active=False）按张开 255。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .smoothing import DEFAULT_SMOOTH_ALPHA, DEFAULT_SMOOTH_MAX_STEP, MotorSmoother

ROBOT_NAME = "o6"
NUM_MOTORS = 6

# 电机顺序对应的手套 u 下标
GLOVE_INDICES: Tuple[int, ...] = (4, 1, 8, 12, 16, 20)

JOINT_NAMES: List[str] = [
    "thumb_tip",     # ← glove 4
    "thumb_root",    # ← glove 1
    "index_tip",     # ← glove 8
    "middle_tip",    # ← glove 12
    "ring_tip",      # ← glove 16
    "pinky_tip",     # ← glove 20
]

MOTOR_OPEN: Tuple[float, ...] = (255.0, 255.0, 255.0, 255.0, 255.0, 255.0)
MOTOR_FIST: Tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def u_to_motor(u: float, motor_open: float, motor_fist: float) -> float:
    t = 0.0 if u < 0.0 else 1.0 if u > 1.0 else float(u)
    return float(motor_open) + t * (float(motor_fist) - float(motor_open))


def map_u_to_motors(
    u: Sequence[float],
    active: Sequence[bool],
    *,
    motor_open: Sequence[float] = MOTOR_OPEN,
    motor_fist: Sequence[float] = MOTOR_FIST,
) -> List[float]:
    """u[21] + active[21] → 6 路电机值。"""
    if len(u) != 21 or len(active) != 21:
        raise ValueError("u/active must be length 21")
    if len(motor_open) != NUM_MOTORS or len(motor_fist) != NUM_MOTORS:
        raise ValueError(f"motor_open/fist must be length {NUM_MOTORS}")

    out: List[float] = []
    for motor_i, glove_i in enumerate(GLOVE_INDICES):
        open_v = float(motor_open[motor_i])
        fist_v = float(motor_fist[motor_i])
        if not active[glove_i]:
            out.append(open_v)
        else:
            out.append(u_to_motor(float(u[glove_i]), open_v, fist_v))
    return out

