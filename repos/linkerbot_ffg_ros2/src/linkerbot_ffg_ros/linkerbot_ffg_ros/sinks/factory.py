"""按 Settings.hand_sdk 创建 HandSink。"""

from __future__ import annotations

from typing import Any

from ..settings.types import Settings
from .ros_joint_state import RosHandControlSink
from .ros_linkerbot import RosLinkerbotSink


def create_hand_sink(settings: Settings, node: Any):
    """LinkerH → /cb_* JointState；LinkerZ → HandJointCommand RAW。"""
    if settings.hand_sdk == "LinkerH":
        return RosHandControlSink(node)
    if settings.hand_sdk == "LinkerZ":
        return RosLinkerbotSink(
            node,
            robot=settings.robot,
            linker_z=settings.linker_z,
        )
    raise ValueError(f"未知 hand_sdk: {settings.hand_sdk!r}")


def sink_topic_for(sink, side: str) -> str:
    """日志用：取 sink 对应该手的话题名。"""
    if hasattr(sink, "topic_for"):
        return sink.topic_for(side)  # type: ignore[no-any-return]
    return "?"
