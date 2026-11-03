"""
把传感器测到的“手指按压力度”（输入），
通过一套数学公式，换算成手套马达应该发出的“力的大小”（输出）。
"""

from __future__ import annotations

import json
from typing import Optional

from ..settings.types import ForceFeedbackSpec
from ..teleop.types import ForceCommand
from .mass_to_force import mass_to_force
from .types import TouchMass

FINGER_MASS_KEYS = ("thumb_mass", "index_mass", "middle_mass", "ring_mass", "little_mass")

#从手的 JSON 消息中提取mass信息
def parse_touch_json(json_str: str, side: str) -> TouchMass:
    """把触觉 JSON 解成五指质量。sensors 的 1 到 5 依次是拇指到小指；也接受 thumb_mass 到 little_mass。"""
    data = json.loads(json_str)
    sensors = data.get("sensors")
    if isinstance(sensors, dict):
        values = []
        for sensor_id in ("1", "2", "3", "4", "5"):
            sensor = sensors.get(sensor_id) or {}
            force = sensor.get("force") or {}
            raw = force.get("FnS", 0.0)
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                values.append(0.0)
    else:
        # thumb_mass、index_mass、middle_mass、ring_mass、little_mass。
        values = [float(data.get(key, 0.0)) for key in FINGER_MASS_KEYS]
    return TouchMass(side=side, values=values)  # type: ignore[arg-type]


class TouchForceMapper:
    """5 指触觉质量 → ForceCommand。曲线常量固定,唯一变量是 max_force。"""

    def __init__(self, spec: ForceFeedbackSpec) -> None:
        self.spec = spec

    def map(self, touch: TouchMass) -> ForceCommand:
        forces = [
            mass_to_force(
                m,
                max_force=self.spec.max_force,
                trigger_mass=self.spec.trigger_mass,
                mass_max=self.spec.mass_max,
                force_onset=self.spec.force_onset,
            )
            for m in touch.values
        ]
        return ForceCommand(side=touch.side, values=forces)

    def reset(self) -> None:
        # 无内部状态。
        return None

    @property
    def zero_command_for(self):
        """生成五指为 0 的力指令。"""
        def _factory(side) -> ForceCommand:
            return ForceCommand(side=side, values=[0.0] * 5)
        return _factory
