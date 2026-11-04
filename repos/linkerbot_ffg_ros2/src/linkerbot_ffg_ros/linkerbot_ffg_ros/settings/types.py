"""  定义配置的数据结构
YAML + CLI 融合后的运行时配置形状。

分层原则:
- teleop_node.py 只 import 本模块的 dataclass,不再关心 YAML 结构。
- 每个字段都记录了来源 (source),日志可辨。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional

HandSdk = Literal["LinkerH", "LinkerZ"]


@dataclass(frozen=True)
class ForceFeedbackSpec:
    """力反馈的最终决定。已经完成所有覆盖 + 硬钳。"""
    enabled: bool
    max_force: int              # 已经钳过 hardware_limit
    trigger_mass: int
    mass_max: int
    force_onset: int
    hardware_limit: int
    source: str                 # "yaml.by_robot.o30" / "cli -F 1000" / "yaml.default" / ...


@dataclass(frozen=True)
class SerialSpec:
    auto_scan: bool
    baudrates: list[int]
    left_port: Optional[str]
    left_baud: int
    right_port: Optional[str]
    right_baud: int


@dataclass(frozen=True)
class LinkerZSpec:
    """LinkerZ (zhu_0922) 出口参数。"""
    client_id: int
    command_topic: str
    topics: Dict[str, str]      # side → command topic；空字符串表示尚未绑定
    o30_swap_01: bool
    # side → 力话题列表；空则按 command 话题自动推导
    #   空则同时订 force_fns、force_fn、normal_force_resultant
    force_topics: Dict[str, List[str]]
    capabilities_topic: str
    discover_timeout_sec: float


@dataclass(frozen=True)
class Settings:
    robot: str                  # "auto" | "o6" | "l6" | ...
    hand_sdk: HandSdk
    rate_hz: float
    smooth: bool
    smooth_alpha: float
    smooth_max_step: float
    calib_dir: Optional[Path]
    serial: SerialSpec
    force: ForceFeedbackSpec
    linker_z: LinkerZSpec
    robot_source: str = "yaml"  # yaml / cli / auto(...)
