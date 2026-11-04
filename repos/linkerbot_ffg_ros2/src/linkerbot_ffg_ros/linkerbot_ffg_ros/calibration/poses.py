"""手套标定姿态定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class PoseDef:
    key: str
    label: str
    instruction: str


POSES: Tuple[PoseDef, ...] = (
    PoseDef(
        key="open_full",
        label="完全张开",
        instruction="五指尽量完全张开，伸直",
    ),
    PoseDef(
        key="adduct",
        label="五指并拢",
        instruction="五指并拢伸直，拇指靠向食指",
    ),
    PoseDef(
        key="thumbs_up",
        label="点赞",
        instruction="四指握拳，拇指竖起点赞",
    ),
    PoseDef(
        key="pinch",
        label="五指聚拢捏",
        instruction="五指指尖聚拢，捏在一起",
    ),
    PoseDef(
        key="thumb_flex",
        label="拇指指尖弯向拇指根",
        instruction="四指放松张开，拇指指尖尽力弯向拇指根",
    ),
)


def pose_keys() -> List[str]:
    return [p.key for p in POSES]
