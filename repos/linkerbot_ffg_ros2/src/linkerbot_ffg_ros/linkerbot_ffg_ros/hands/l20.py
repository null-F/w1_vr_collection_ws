"""L20：手套 u[21] → 20 路电机。

电机下标（0 基）← 手套下标，及开/合端点，与 GLOVE_INDICES、MOTOR_OPEN、MOTOR_CLOSED 一致：
   0 ← u[2]   open=160 closed=  0    thumb_base
   1 ← u[6]   open=255 closed=  0    index_base
   2 ← u[10]  open=255 closed=  0    middle_base
   3 ← u[14]  open=255 closed=  0    ring_base
   4 ← u[18]  open=255 closed=  0    pinky_base
   5 ← u[1]   open=200 closed= 40    thumb_abd
   6 ← u[5]   open=126 closed=255    index_abd
   7 ← u[9]   open=126 closed=126    middle_abd      (恒定中位；不动)
   8 ← u[13]  open=126 closed= 64    ring_abd
   9 ← u[17]  open=126 closed=  0    pinky_abd
  10 ← u[1]   open=255 closed=  0    thumb_horizontal_abd
  11 ← u[0]   open=255 closed=255    reserved_11     (占位；恒 255)
  12 ← u[0]   open=255 closed=255    reserved_12     (占位；恒 255)
  13 ← u[0]   open=255 closed=255    reserved_13     (占位；恒 255)
  14 ← u[0]   open=255 closed=255    reserved_14     (占位；恒 255)
  15 ← u[4] 与 u[2]  open=255 closed=  0    thumb_tip
       （两路各映射成电机值，取较小的那个）
  16 ← u[8]   open=255 closed=  0    index_tip
  17 ← u[12]  open=255 closed=  0    middle_tip
  18 ← u[16]  open=255 closed=  0    ring_tip
  19 ← u[20]  open=255 closed=  0    pinky_tip
       16–19：对应指根（1–4）自身变化未到 4/5 时，
       指尖变化量 = 指根变化量的一半，
       指根变化量 = 指根原来的变化量 + 指尖原来的变化量；
       指根自身变化达到 4/5 后，指根和指尖都改回原来的手套值

motor = open + u * (closed - open)；无效通道 (active=False) 用 open。
open==closed 的通道等效常数输出（middle_abd 与 4 路 reserved）。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .o6 import u_to_motor
from .smoothing import DEFAULT_SMOOTH_ALPHA, DEFAULT_SMOOTH_MAX_STEP, MotorSmoother

ROBOT_NAME = "l20"
NUM_MOTORS = 20

#电机顺序对应的手套 u 下标（=cb_*_hand_control_cmd.position[] 顺序）
# reserved 位仍占一个索引，配合 open==closed=255 恒定输出。
GLOVE_INDICES: Tuple[int, ...] = (
    2, 6, 10, 14, 18,     # 0-4  五指 base
    1, 5, 9, 13, 17,      # 5-9  五指 abd
    1,                    # 10   thumb horizontal abd
    0, 0, 0, 0,           # 11-14 reserved（open==closed，取任意 u 均可）
    4, 8, 12, 16, 20,     # 15-19 五指 tip（15 再与 u[2] 的电机值取较小）
)

MOTOR_OPEN: Tuple[float, ...] = (
    160.0, 255.0, 255.0, 255.0, 255.0,   # 0-4  base
    200.0, 126.0, 126.0, 126   ,126,   # 5-9  abd
    255,                               # 10   thumb h-abd
    255.0, 255.0, 255.0, 255.0,          # 11-14 reserved
    255.0, 255.0, 255.0, 255.0, 255.0,   # 15-19 tip
)

MOTOR_CLOSED: Tuple[float, ...] = (
      0.0,   0.0,   0.0,   0.0,   0.0,   # 0-4  base
      40.0,  255.0, 126.0, 64, 0,   # 5-9  abd
      0,                               # 10   thumb h-abd
      255.0, 255.0, 255.0, 255.0,          # 11-14 reserved（=open, 恒定 255）
      0.0,   0.0,   0.0,   0.0,   0.0,   # 15-19 tip
)



# 兼容旧命名（O 系列用 MOTOR_FIST）
MOTOR_FIST = MOTOR_CLOSED

# 四指：指根自身变化未到 4/5 时，指尖变化量是指根的一半，指根再叠上指尖原来的变化量。
_TIP_BASE_SWITCH = 4.0 / 5.0
_TIP_FOLLOWS_BASE: Tuple[Tuple[int, int], ...] = (
    (16, 1),  # index
    (17, 2),  # middle
    (18, 3),  # ring
    (19, 4),  # pinky
)

JOINT_NAMES: List[str] = [
    "thumb_base",             # 0
    "index_base",             # 1
    "middle_base",            # 2
    "ring_base",              # 3
    "pinky_base",             # 4
    "thumb_abd",              # 5
    "index_abd",              # 6
    "middle_abd",             # 7
    "ring_abd",               # 8
    "pinky_abd",              # 9
    "thumb_horizontal_abd",   # 10
    "reserved_11",            # 11
    "reserved_12",            # 12
    "reserved_13",            # 13
    "reserved_14",            # 14
    "thumb_tip",              # 15
    "index_tip",              # 16
    "middle_tip",             # 17
    "ring_tip",               # 18
    "pinky_tip",              # 19
]


def map_u_to_motors(
    u: Sequence[float],
    active: Sequence[bool],
    *,
    motor_open: Sequence[float] = MOTOR_OPEN,
    motor_closed: Sequence[float] = MOTOR_CLOSED,
) -> List[float]:
    """u[21] + active[21] → 20 路电机值。"""
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
        sources = (2, 4) if motor_i == 15 else (glove_i,)
        values = [_motor_from_glove(u, active, i, open_v, closed_v) for i in sources]
        out.append(min(values) if motor_i == 15 else values[0])

    for tip_i, base_i in _TIP_FOLLOWS_BASE:
        out[tip_i], out[base_i] = _couple_tip_and_base(
            out[tip_i],
            out[base_i],
            float(motor_open[tip_i]),
            float(motor_closed[tip_i]),
            float(motor_open[base_i]),
            float(motor_closed[base_i]),
        )
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


def _couple_tip_and_base(
    tip: float,
    base: float,
    tip_open: float,
    tip_closed: float,
    base_open: float,
    base_closed: float,
) -> Tuple[float, float]:
    """指根自身未到 4/5：指尖变化量是指根的一半，指根再加上指尖原来的变化量。

    达到 4/5 后，指根和指尖都用各自原来的手套值。
    """
    base_span = base_closed - base_open
    if base_span == 0.0:
        return tip, base
    base_progress = (base - base_open) / base_span
    if base_progress >= _TIP_BASE_SWITCH:
        return tip, base
    if base_progress < 0.0:
        base_progress = 0.0
    base_delta = base_progress * abs(base_span)
    tip_delta = _closing_delta(tip, tip_open, tip_closed)
    tip_out = _motor_from_closing_delta(0.5 * base_delta, tip_open, tip_closed)
    base_out = _motor_from_closing_delta(base_delta + tip_delta, base_open, base_closed)
    return tip_out, base_out


def _closing_delta(value: float, open_v: float, closed_v: float) -> float:
    """从张开端沿闭合方向已经走过的电机量，限制在本路行程内。"""
    span = closed_v - open_v
    if span == 0.0:
        return 0.0
    progress = (value - open_v) / span
    if progress < 0.0:
        progress = 0.0
    elif progress > 1.0:
        progress = 1.0
    return progress * abs(span)


def _motor_from_closing_delta(delta: float, open_v: float, closed_v: float) -> float:
    """从张开端沿闭合方向走 delta，不超过闭合端。"""
    span = closed_v - open_v
    if span == 0.0:
        return open_v
    max_delta = abs(span)
    if delta < 0.0:
        delta = 0.0
    elif delta > max_delta:
        delta = max_delta
    if span < 0.0:
        return open_v - delta
    return open_v + delta


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
