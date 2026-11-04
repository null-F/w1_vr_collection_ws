"""将手套角度相对标定范围归一化为与手型无关的动作进度。"""

from __future__ import annotations

import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..teleop.types import GloveChangeFrame, GloveFrame, HandSide

JOINT_COUNT = 21
DEFAULT_RANGE_EPS_DEG = 1e-3


def pose_joints_from_doc(doc: Mapping) -> Dict[str, List[float]]:
    """从标定 doc 抽出 {pose_key: joints_deg[21]}，缺 joints_deg 的姿态跳过。"""
    raw = doc.get("poses") or {}
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, List[float]] = {}
    for key, block in raw.items():
        if not isinstance(block, Mapping):
            continue
        joints = block.get("joints_deg")
        if joints is None:
            continue
        if len(joints) != JOINT_COUNT:
            raise ValueError(f"姿态 {key} 的 joints_deg 必须为长度 {JOINT_COUNT}")
        out[str(key)] = [float(x) for x in joints]
    return out


def clamp_to_calibration_range(
    current_deg: float,
    base: float,
    joint_range: float,
) -> float:
    """把当前角钳到 [base, base+joint_range] 两端点之间（含方向）。"""
    end = base + joint_range
    lo = min(base, end)
    hi = max(base, end)
    if current_deg < lo:
        return lo
    if current_deg > hi:
        return hi
    return current_deg


def normalize_glove_change(
    current_deg: Sequence[float],
    base: Sequence[float],
    joint_range: Sequence[float],
    *,
    range_eps: float = DEFAULT_RANGE_EPS_DEG,
) -> Tuple[List[float], List[bool], List[float], List[bool]]:
    """计算 u / active / 钳位后角度 / 是否钳位。

    有效通道：先将 current 钳到标定边界，再
        u = (clamped - base) / joint_range  → [0, 1]
    无效通道（|range| < eps）：u=0，clamped=current，clipped=False
    """
    if len(current_deg) != JOINT_COUNT:
        raise ValueError(f"current must be length {JOINT_COUNT}")
    if len(base) != JOINT_COUNT:
        raise ValueError(f"base must be length {JOINT_COUNT}")
    if len(joint_range) != JOINT_COUNT:
        raise ValueError(f"joint_range must be length {JOINT_COUNT}")

    u: List[float] = []
    active: List[bool] = []
    clamped: List[float] = []
    clipped: List[bool] = []

    for i in range(JOINT_COUNT):
        cur = float(current_deg[i])
        b = float(base[i])
        r = float(joint_range[i])
        if not (math.isfinite(cur) and math.isfinite(b) and math.isfinite(r)):
            raise ValueError(f"非有限标定数据或角度: index={i}")
        if abs(r) < range_eps:
            u.append(0.0)
            active.append(False)
            clamped.append(cur)
            clipped.append(False)
            continue

        c = clamp_to_calibration_range(cur, b, r)
        u.append((c - b) / r)
        active.append(True)
        clamped.append(c)
        clipped.append(c != cur)

    return u, active, clamped, clipped



def scale_u_to_motor(
    u: float,
    *,
    motor_open: float = 255.0,
    motor_fist: float = 0.0,
) -> float:
    """单通道：u=0 → motor_open，u=1 → motor_fist（可标定方向）。"""
    t = 0.0 if u < 0.0 else 1.0 if u > 1.0 else float(u)
    return float(motor_open) + t * (float(motor_fist) - float(motor_open))


def scale_u_to_motor_vector(
    u: Sequence[float],
    active: Sequence[bool],
    *,
    motor_open: float = 255.0,
    motor_fist: float = 0.0,
) -> List[float]:
    """21 路：无效通道保持 motor_open（视为未动）。"""
    if len(u) != JOINT_COUNT or len(active) != JOINT_COUNT:
        raise ValueError("u/active must be length 21")
    out: List[float] = []
    for i in range(JOINT_COUNT):
        if not active[i]:
            out.append(float(motor_open))
        else:
            out.append(scale_u_to_motor(u[i], motor_open=motor_open, motor_fist=motor_fist))
    return out

class GloveChangeEstimator:
    """持有某只手的 base/joint_range，把 GloveFrame 变成 GloveChangeFrame。"""

    def __init__(
        self,
        base: Sequence[float],
        joint_range: Sequence[float],
        *,
        side: Optional[HandSide] = None,
        range_eps: float = DEFAULT_RANGE_EPS_DEG,
        pose_joints_deg: Optional[Mapping[str, Sequence[float]]] = None,
    ) -> None:
        if len(base) != JOINT_COUNT or len(joint_range) != JOINT_COUNT:
            raise ValueError("base/joint_range must be length 21")
        self.base = [float(x) for x in base]
        self.joint_range = [float(x) for x in joint_range]
        self.side = side
        self.range_eps = range_eps
        self.pose_joints_deg: Dict[str, List[float]] = {}
        if pose_joints_deg:
            for key, values in pose_joints_deg.items():
                if len(values) != JOINT_COUNT:
                    raise ValueError(f"pose_joints_deg[{key}] must be length {JOINT_COUNT}")
                self.pose_joints_deg[str(key)] = [float(x) for x in values]

    @classmethod
    def from_calibration_doc(
        cls,
        doc: Mapping,
        *,
        range_eps: float = DEFAULT_RANGE_EPS_DEG,
    ) -> "GloveChangeEstimator":
        base = doc.get("base")
        joint_range = doc.get("joint_range")
        if base is None or joint_range is None:
            raise KeyError("标定文件缺少 base 或 joint_range，请重新标定")
        meta_side = (doc.get("meta") or {}).get("side")
        side: Optional[HandSide] = None
        if meta_side in ("left", "right"):
            side = meta_side  # type: ignore[assignment]
        return cls(
            base,
            joint_range,
            side=side,
            range_eps=range_eps,
            pose_joints_deg=pose_joints_from_doc(doc),
        )

    def estimate(self, frame: GloveFrame) -> GloveChangeFrame:
        if self.side is not None and frame.side != self.side:
            raise ValueError(f"side mismatch: estimator={self.side}, frame={frame.side}")
        u, active, clamped, clipped = normalize_glove_change(
            frame.joints_deg,
            self.base,
            self.joint_range,
            range_eps=self.range_eps,
        )
        return GloveChangeFrame(
            side=frame.side,
            u=u,
            active=active,
            timestamp=frame.timestamp,
            base=list(self.base),
            joint_range=list(self.joint_range),
            joints_clamped_deg=clamped,
            clipped=clipped,
        )
