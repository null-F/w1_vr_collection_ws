#定义各模块之间传递的数据
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

HandSide = Literal["left", "right"]


@dataclass
class GloveFrame:
    """手套一帧：协议层解完后给映射用。"""
    side: HandSide
    joints_deg: List[float]          # 固定 21 路，单位：度（全 SDK 统一，不转弧度）
    timestamp: float                 # time.time() 或 monotonic
    version: Optional[str] = None    # 如 "2.1.5"
    valid: bool = True

    def __post_init__(self) -> None:
        if len(self.joints_deg) != 21:
            raise ValueError(f"joints_deg must be length 21, got {len(self.joints_deg)}")


@dataclass
class GloveChangeFrame:
    """手套相对标定的变化量（与手型无关）。

    超出 [base, base+joint_range] 时先钳到边界再归一化：
        u[i] ∈ [0, 1]（有效通道）
    active[i]=False：|joint_range| 过小，u=0。
    clipped[i]=True：该帧该通道发生了边界钳位。
    """
    side: HandSide
    u: List[float]                   # 固定 21，无量纲，有效通道在 [0,1]
    active: List[bool]               # 固定 21
    timestamp: float = 0.0
    base: Optional[List[float]] = None
    joint_range: Optional[List[float]] = None
    joints_clamped_deg: Optional[List[float]] = None  # 钳位后的度
    clipped: Optional[List[bool]] = None              # 是否钳位

    def __post_init__(self) -> None:
        if len(self.u) != 21:
            raise ValueError(f"u must be length 21, got {len(self.u)}")
        if len(self.active) != 21:
            raise ValueError(f"active must be length 21, got {len(self.active)}")
        if self.joints_clamped_deg is not None and len(self.joints_clamped_deg) != 21:
            raise ValueError("joints_clamped_deg must be length 21")
        if self.clipped is not None and len(self.clipped) != 21:
            raise ValueError("clipped must be length 21")


@dataclass
class JointCommand:
    """映射后发给机械手 / ROS 的指令。"""
    side: HandSide
    robot_name: str                  # 如 "o6" | "l10" | ...
    joint_names: List[str]
    positions: List[float]           # 与 joint_names 一一对应
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if len(self.joint_names) != len(self.positions):
            raise ValueError("joint_names and positions length mismatch")


@dataclass
class ForceCommand:
    """主机 → 手套力反馈（0x04），通常 5 指。"""
    side: HandSide
    values: List[float] = field(default_factory=lambda: [0.0] * 5)

    def __post_init__(self) -> None:
        if len(self.values) != 5:
            raise ValueError(f"force values must be length 5, got {len(self.values)}")