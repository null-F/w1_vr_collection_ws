"""按 hand_sdk 创建触觉/力反馈输入源。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from ..force.types import TouchMass
from ..settings.types import Settings
from .ros_linkerbot_force import (
    RosLinkerbotForceSource,
    resolve_force_topics_for_side,
)
from .ros_touch_mass import RosTouchMassSource


def create_touch_source(
    settings: Settings,
    node: Any,
    callback: Callable[[TouchMass], None],
    *,
    sides: Optional[Sequence[str]] = None,
):
    """LinkerH → /cb_*_touch_mass；
    LinkerZ → 先听三路力话题，选定后只保留一路。
    """
    if settings.hand_sdk == "LinkerH":
        return RosTouchMassSource(node, callback)

    if settings.hand_sdk == "LinkerZ":
        z = settings.linker_z
        active = list(sides) if sides else ["left", "right"]
        topics_by_side: Dict[str, List] = {}
        for side in active:
            override = (z.force_topics or {}).get(side)
            cmd = (z.topics.get(side) or "").strip()
            if not cmd:
                continue
            topics_by_side[side] = resolve_force_topics_for_side(
                node,
                cmd,
                override=override or None,
            )
        return RosLinkerbotForceSource(node, callback, topics_by_side=topics_by_side)

    raise ValueError(f"未知 hand_sdk: {settings.hand_sdk!r}")
