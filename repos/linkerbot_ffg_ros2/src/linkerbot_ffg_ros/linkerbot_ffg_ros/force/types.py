"""force/ 内部使用的数据结构。

与 teleop/types.py 里的 ForceCommand 对称:
  - ForceCommand 是"主机 → 手套"的力指令(出口)
  - TouchMass    是"灵巧手 → 主机"的触觉输入(入口)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..teleop.types import HandSide


@dataclass
class TouchMass:
    """一帧五指触觉质量。量程0~2000。

    顺序固定为 [thumb, index, middle, ring, little],与[拇指, 食指, 中指, 无名指, 小指]一致。
    """
    side: HandSide
    values: List[float] = field(default_factory=lambda: [0.0] * 5)
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if len(self.values) != 5:
            raise ValueError(f"TouchMass.values 长度必须为 5, got {len(self.values)}")
