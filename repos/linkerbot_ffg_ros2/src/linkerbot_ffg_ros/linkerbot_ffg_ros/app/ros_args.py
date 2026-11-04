"""把 ROS 2 自动附加的参数从应用参数里拆出去。"""

from __future__ import annotations

import sys
from typing import Optional, Sequence


def non_ros_args(argv: Optional[Sequence[str]] = None) -> list[str]:
    """返回应用参数，不含程序名和 --ros-args。"""
    raw = list(sys.argv if argv is None else argv)
    try:
        from rclpy.utilities import remove_ros_args
    except ImportError:
        return raw[1:]
    return list(remove_ros_args(raw))[1:]
