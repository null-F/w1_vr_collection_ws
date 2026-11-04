"""采集标定姿态，并通过滑动窗口判断姿态稳定性。"""

from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from ..glove_ffg.constants import JOINT_COUNT, STABILITY_THRESHOLD_DEG
from ..glove_ffg.reader import GloveReader
from .poses import PoseDef

DEFAULT_WINDOW = 30
DEFAULT_THRESHOLD = STABILITY_THRESHOLD_DEG
DEFAULT_STABLE_SECONDS = 5.0
DEFAULT_HZ = 30.0
DEFAULT_PREP_SECONDS = 3.0


def stability_metrics(
    samples: Sequence[Sequence[float]],
    tracked_joints: Optional[Iterable[int]] = None,
) -> Tuple[float, float]:
    if not samples:
        return 0.0, 0.0
    data = np.asarray(samples, dtype=float)
    if data.ndim != 2 or data.shape[0] == 0:
        return 0.0, 0.0

    if tracked_joints is None:
        indices = list(range(data.shape[1]))
    else:
        indices = [int(i) for i in tracked_joints if 0 <= int(i) < data.shape[1]]
    if not indices:
        return 0.0, 0.0

    filtered = data[:, indices]
    std = float(np.std(filtered, axis=0).mean())
    drift = float(np.abs(filtered[-1] - filtered[0]).mean())
    return std, drift


def is_stable(
    std: float,
    drift: float,
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    return std < threshold and drift < threshold


def weighted_average(samples: Sequence[Sequence[float]]) -> List[float]:
    """后帧权重更大。"""
    if not samples:
        return [0.0] * JOINT_COUNT

    n = len(samples)
    if n == 1:
        return list(samples[0])

    weights = np.arange(1, n + 1, dtype=float)
    weights /= weights.sum()
    data = np.asarray(samples, dtype=float)
    return np.average(data, axis=0, weights=weights).tolist()


def capture_pose(
    reader: GloveReader,
    pose: PoseDef,
    *,
    window: int = DEFAULT_WINDOW,
    threshold: float = DEFAULT_THRESHOLD,
    stable_seconds: float = DEFAULT_STABLE_SECONDS,
    hz: float = DEFAULT_HZ,
    tracked_joints: Optional[Iterable[int]] = None,
    progress_callback=None,
) -> List[float]:
    """单手采集。多手请用 capture_pose_multi。"""
    result = capture_pose_multi(
        {"_": reader},
        pose,
        window=window,
        threshold=threshold,
        stable_seconds=stable_seconds,
        hz=hz,
        tracked_joints=tracked_joints,
        progress_callback=progress_callback,
    )
    return result["_"]


def capture_pose_multi(
    readers: Dict[str, GloveReader],
    pose: PoseDef,
    *,
    window: int = DEFAULT_WINDOW,
    threshold: float = DEFAULT_THRESHOLD,
    stable_seconds: float = DEFAULT_STABLE_SECONDS,
    hz: float = DEFAULT_HZ,
    tracked_joints: Optional[Iterable[int]] = None,
    progress_callback=None,
) -> Dict[str, List[float]]:
    """多手同时采集：所有手都稳定满 stable_seconds 才完成。

    任一手不稳、断流或读到无效帧时，两侧都清零重来。
    """
    if not readers:
        raise ValueError("readers 为空")
    for side, reader in readers.items():
        if not reader.is_open:
            raise RuntimeError(f"手套未打开: side={side}")

    dt = 1.0 / max(hz, 1.0)
    sides = list(readers.keys())
    buffers: Dict[str, List[List[float]]] = {s: [] for s in sides}
    stability_samples: Dict[str, List[List[float]]] = {s: [] for s in sides}
    stable_start: Optional[float] = None
    collected = 0.0
    tracked = list(tracked_joints) if tracked_joints is not None else list(range(JOINT_COUNT))

    def _clear_stable_timer(*, drop_window: bool) -> None:
        """清掉稳定计时。断流时同时清掉滑动窗口。"""
        nonlocal buffers, stability_samples, stable_start, collected
        if drop_window:
            buffers = {s: [] for s in sides}
        stability_samples = {s: [] for s in sides}
        stable_start = None
        collected = 0.0

    while collected < stable_seconds:
        frames: Dict[str, List[float]] = {}
        missing = False
        for side, reader in readers.items():
            reader.poll()
            frame = reader.read()
            if frame is None or not frame.valid or len(frame.joints_deg) != JOINT_COUNT:
                missing = True
                break
            frames[side] = list(frame.joints_deg)

        if missing or len(frames) != len(readers):
            # 断流：清掉计时和窗口。
            _clear_stable_timer(drop_window=True)
            if progress_callback:
                progress_callback(0.0, None, None, "waiting_frame")
            time.sleep(dt)
            continue

        for side, joints in frames.items():
            buffers[side].append(joints)
            if len(buffers[side]) > window:
                buffers[side].pop(0)

        if any(len(buffers[s]) < window for s in sides):
            n_min = min(len(buffers[s]) for s in sides)
            if progress_callback:
                progress_callback(0.0, None, None, f"warming {n_min}/{window}")
            time.sleep(dt)
            continue

        metrics = {s: stability_metrics(buffers[s], tracked) for s in sides}
        all_stable = all(is_stable(v, d, threshold) for v, d in metrics.values())
        worst_std = max(v for v, _ in metrics.values())
        worst_drift = max(d for _, d in metrics.values())

        if all_stable:
            if stable_start is None:
                stable_start = time.monotonic()
            for side in sides:
                stability_samples[side].append(frames[side])
            collected = time.monotonic() - stable_start
            if progress_callback:
                progress_callback(
                    min(1.0, collected / stable_seconds),
                    worst_std,
                    worst_drift,
                    "stable",
                )
        else:
            # 姿势不稳：只清计时，保留窗口。
            _clear_stable_timer(drop_window=False)
            if progress_callback:
                progress_callback(0.0, worst_std, worst_drift, "unstable")

        time.sleep(dt)

    out: Dict[str, List[float]] = {}
    for side in sides:
        if not stability_samples[side]:
            raise RuntimeError(f"pose {pose.key}: side={side} 无稳定样本")
        out[side] = weighted_average(stability_samples[side])
    return out
