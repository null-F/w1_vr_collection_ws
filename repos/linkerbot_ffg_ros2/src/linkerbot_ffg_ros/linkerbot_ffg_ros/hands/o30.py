"""O30：u[21] 到 20 路电机的分段映射和四指后处理。"""

from __future__ import annotations

from typing import List, Mapping, Optional, Sequence, Tuple

from .o6 import u_to_motor
from .smoothing import DEFAULT_SMOOTH_ALPHA, DEFAULT_SMOOTH_MAX_STEP, MotorSmoother

ROBOT_NAME = "o30"
NUM_MOTORS = 20

# 当前 O30 的电机到手套通道对应关系。
GLOVE_INDICES: Tuple[int, ...] = (
    1, 1, 5, 9, 13, 17,
    2, 6, 10, 14, 18,
    7, 11, 15, 19,
    4, 8, 12, 16, 20,
)

MOTOR_OPEN: Tuple[float, ...] = (
    0.0, 0.0, 169.0, 169.0, 160.0, 160.0,
    0.0, 0.0, 0.0, 0.0, 0.0,
    0.0, 0.0, 0.0, 0.0,
    0.0, 0.0, 0.0, 0.0, 0.0,
)

MOTOR_CLOSED: Tuple[float, ...] = (
    255.0, 255.0, 0.0, 169.0, 255.0, 255.0,
    255.0, 255.0, 255.0, 255.0, 255.0,
    255.0, 255.0, 255.0, 255.0,
    255.0, 255.0, 255.0, 255.0, 255.0,
)

# 有对指中点的电机；None 表示该路不使用中点。
MOTOR_MID: Tuple[Optional[float], ...] = (
    None, 194.0, None, None, None, None,
    None, 217.0, 217.0, 217.0, 217.0,
    76.0, 98.0, 91.0, 105.0,
    None, None, None, None, None,
)

# 对指中点取自 pinch 姿态。
_MID_POSE_BY_MOTOR: Tuple[Optional[str], ...] = (
    None, "pinch", None, None, None, None,
    None, "pinch", "pinch", "pinch", "pinch",
    "pinch", "pinch", "pinch", "pinch",
    None, None, None, None, None,
)

MOTOR_FIST = MOTOR_CLOSED
JOINT_NAMES: List[str] = [f"joint{i + 1}" for i in range(NUM_MOTORS)]

# (指根电机, 指中电机, 指尖电机, 指根手套通道)
FOUR_FINGER_ROOT_MID_TIP: Tuple[Tuple[int, int, int, int], ...] = (
    (7, 11, 16, 6),
    (8, 12, 17, 10),
    (9, 13, 18, 14),
    (10, 14, 19, 18),
)

# 拇指指根 / 指尖：电机下标与手套通道
THUMB_ROOT_MOTOR = 6   # ← u[2]
THUMB_TIP_MOTOR = 15   # ← u[4]
THUMB_ROOT_GLOVE = 2
THUMB_TIP_GLOVE = 4
# 指根 u 未到该阈值前：根=max(u2,u4)，尖=u4/2；达到后用原值
THUMB_ROOT_HALF_U = 0.5


def _clamp_u(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def effective_thumb_root_tip_u(u: Sequence[float]) -> Tuple[float, float]:
    """拇指指根/指尖有效 u。

    指根 u[2] 未到一半：根 = max(u[2], u[4])，尖 = u[4] / 2。
    到达一半及之后：根 = u[2]，尖 = u[4]。
    """
    u_root = _clamp_u(u[THUMB_ROOT_GLOVE])
    u_tip = _clamp_u(u[THUMB_TIP_GLOVE])
    if u_root < THUMB_ROOT_HALF_U:
        return max(u_root, u_tip), 0.5 * u_tip
    return u_root, u_tip


def u_to_motor_via_mid(
    u: float,
    motor_open: float,
    motor_mid: float,
    motor_closed: float,
    u_mid: float,
) -> float:
    """按 open → 对指中点 → closed 三段线性插值。"""
    t = _clamp_u(u)
    mid = float(u_mid)
    if mid <= 1e-3 or mid >= 1.0 - 1e-3:
        return u_to_motor(t, motor_open, motor_closed)
    if t <= mid:
        return float(motor_open) + (t / mid) * (float(motor_mid) - float(motor_open))
    return float(motor_mid) + ((t - mid) / (1.0 - mid)) * (float(motor_closed) - float(motor_mid))


def u_mid_from_pose_joints(
    pose_joints_deg: Optional[Mapping[str, Sequence[float]]],
    base: Sequence[float],
    joint_range: Sequence[float],
    *,
    range_eps: float = 1e-3,
) -> List[Optional[float]]:
    """计算每个电机中点姿态在标定范围中的 u 位置。"""
    out: List[Optional[float]] = [None] * NUM_MOTORS
    pinch = (pose_joints_deg or {}).get("pinch") if pose_joints_deg else None
    if pinch is None or len(pinch) != 21:
        return out
    for motor_i, pose_key in enumerate(_MID_POSE_BY_MOTOR):
        if pose_key is None:
            continue
        glove_i = GLOVE_INDICES[motor_i]
        r = float(joint_range[glove_i])
        if abs(r) < range_eps:
            continue
        out[motor_i] = (float(pinch[glove_i]) - float(base[glove_i])) / r
    return out


def map_u_to_motors(
    u: Sequence[float],
    active: Sequence[bool],
    *,
    motor_open: Sequence[float] = MOTOR_OPEN,
    motor_closed: Sequence[float] = MOTOR_CLOSED,
    motor_mid: Sequence[Optional[float]] = MOTOR_MID,
    u_mid: Optional[Sequence[Optional[float]]] = None,
) -> List[float]:
    """第一阶段：把 21 路 u 映射为 20 路基础电机值。"""
    if len(u) != 21 or len(active) != 21:
        raise ValueError("u/active must be length 21")
    if len(motor_open) != NUM_MOTORS or len(motor_closed) != NUM_MOTORS:
        raise ValueError(f"motor_open/motor_closed must be length {NUM_MOTORS}")
    if len(motor_mid) != NUM_MOTORS:
        raise ValueError(f"motor_mid must be length {NUM_MOTORS}")
    mids = list(u_mid) if u_mid is not None else [None] * NUM_MOTORS
    if len(mids) != NUM_MOTORS:
        raise ValueError(f"u_mid must be length {NUM_MOTORS}")

    thumb_root_u, thumb_tip_u = effective_thumb_root_tip_u(u)

    out: List[float] = []
    for motor_i, glove_i in enumerate(GLOVE_INDICES):
        open_v = float(motor_open[motor_i])
        if not active[glove_i]:
            out.append(open_v)
            continue
        if motor_i == THUMB_ROOT_MOTOR:
            u_val = thumb_root_u
        elif motor_i == THUMB_TIP_MOTOR:
            u_val = thumb_tip_u
        else:
            u_val = float(u[glove_i])
        mid_v = motor_mid[motor_i]
        mid_u = mids[motor_i]
        if mid_v is None or mid_u is None:
            out.append(u_to_motor(u_val, open_v, motor_closed[motor_i]))
        else:
            out.append(
                u_to_motor_via_mid(
                    u_val, open_v, float(mid_v),
                    float(motor_closed[motor_i]), float(mid_u),
                )
            )
    return out


def postprocess_four_fingers(
    motors: Sequence[float],
    u: Sequence[float],
    u_mid: Sequence[Optional[float]],
) -> List[float]:
    """第三阶段：先改写指中，再按指根对指点改写指尖。"""
    if len(motors) != NUM_MOTORS or len(u) != 21 or len(u_mid) != NUM_MOTORS:
        raise ValueError("invalid O30 postprocess input length")
    source = [float(value) for value in motors]
    out = list(source)
    for root_motor, middle_motor, tip_motor, root_glove_i in FOUR_FINGER_ROOT_MID_TIP:
        # 指中使用改写前的原指根和原指尖。
        out[middle_motor] = 0.5 * (source[root_motor] + source[tip_motor])
        split = u_mid[root_motor]
        if split is not None and _clamp_u(u[root_glove_i]) < float(split):
            out[tip_motor] = 0.5 * out[middle_motor]
        else:
            out[tip_motor] = source[tip_motor]
    return out


__all__ = [
    "ROBOT_NAME", "NUM_MOTORS", "GLOVE_INDICES", "MOTOR_OPEN", "MOTOR_CLOSED",
    "MOTOR_MID", "MOTOR_FIST", "JOINT_NAMES", "u_to_motor_via_mid",
    "u_mid_from_pose_joints", "effective_thumb_root_tip_u", "map_u_to_motors",
    "postprocess_four_fingers", "MotorSmoother", "DEFAULT_SMOOTH_ALPHA",
    "DEFAULT_SMOOTH_MAX_STEP", "THUMB_ROOT_MOTOR", "THUMB_TIP_MOTOR",
    "THUMB_ROOT_GLOVE", "THUMB_TIP_GLOVE", "THUMB_ROOT_HALF_U",
]
