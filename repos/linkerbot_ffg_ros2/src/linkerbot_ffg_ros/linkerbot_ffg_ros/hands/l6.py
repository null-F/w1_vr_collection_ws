"""L6：与 O6 相同的 6 路映射，型号名是 l6。

通道约定（0 基下标）：
  motor[0] ← u[4]   thumb_tip
  motor[1] ← u[1]   thumb_root
  motor[2] ← u[8]   index_tip
  motor[3] ← u[12]  middle_tip
  motor[4] ← u[16]  ring_tip
  motor[5] ← u[20]  pinky_tip

张开：全 255；合上默认全 0。无效通道按张开 255。
"""

from .o6 import (
    GLOVE_INDICES,
    JOINT_NAMES,
    MOTOR_FIST,
    MOTOR_OPEN,
    NUM_MOTORS,
    map_u_to_motors,
    u_to_motor,
)

ROBOT_NAME = "l6"

__all__ = [
    "ROBOT_NAME",
    "NUM_MOTORS",
    "GLOVE_INDICES",
    "JOINT_NAMES",
    "MOTOR_OPEN",
    "MOTOR_FIST",
    "map_u_to_motors",
    "u_to_motor",
]
