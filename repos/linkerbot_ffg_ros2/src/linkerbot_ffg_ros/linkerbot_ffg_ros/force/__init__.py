"""力反馈算法:触觉质量 → 手套力值。

不依赖 ROS / serial,可脱机单测。
"""

from .mass_to_force import mass_to_force
from .touch_force_mapper import FINGER_MASS_KEYS, TouchForceMapper, parse_touch_json
from .types import TouchMass

__all__ = [
    "mass_to_force",
    "TouchMass",
    "TouchForceMapper",
    "parse_touch_json",
    "FINGER_MASS_KEYS",
]
