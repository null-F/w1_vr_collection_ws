"""保存、加载和管理手套标定结果。"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml

from .poses import PoseDef

def default_calibration_dir() -> Path:
    """新标定的默认目录。"""
    raw = os.environ.get("LINKERFORCE_CALIB_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path.home() / ".local" / "share" / "linkerbot_ffg_ros" / "calibration"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_calibration_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def default_calibration_path(
    side: str,
    stamp: Optional[str] = None,
    directory: Optional[Path] = None,
) -> Path:
    """默认文件名：glove_{side}_{stamp}.yaml"""
    directory = directory or default_calibration_dir()
    stamp = stamp or new_calibration_stamp()
    return Path(directory) / f"glove_{side}_{stamp}.yaml"


def _calibration_side(path: Path) -> Optional[str]:
    """从 glove_{side}_*.yaml 取出 left/right；认不出则返回 None。"""
    name = Path(path).name
    if not (name.startswith("glove_") and name.endswith(".yaml")):
        return None
    parts = name[len("glove_") : -len(".yaml")].split("_", 1)
    if not parts:
        return None
    side = parts[0]
    if side in ("left", "right"):
        return side
    return None


def prune_old_calibrations(keep: Sequence[Path]) -> List[Path]:
    """删除本轮已保存侧别的旧标定文件。"""
    if not keep:
        return []

    by_dir: Dict[Path, Dict[str, set[Path]]] = {}
    for p in keep:
        resolved = Path(p).resolve()
        side = _calibration_side(resolved)
        if side is None:
            continue
        by_dir.setdefault(resolved.parent, {}).setdefault(side, set()).add(resolved)

    removed: List[Path] = []
    for directory, keep_by_side in by_dir.items():
        if not directory.is_dir():
            continue
        for side, keep_set in keep_by_side.items():
            for f in directory.glob(f"glove_{side}_*.yaml"):
                if f.resolve() not in keep_set:
                    f.unlink(missing_ok=True)
                    removed.append(f)
    return removed


def build_document(
    *,
    side: str,
    glove_version: Optional[str],
    port: str,
    baudrate: int,
    poses: Dict[str, List[float]],
    pose_defs: List[PoseDef],
    capture_params: Optional[Dict[str, Any]] = None,
    joint_range: Optional[List[float]] = None,
    base: Optional[List[float]] = None,
    glove_max: Optional[List[float]] = None,
) -> Dict[str, Any]:
    pose_meta = {p.key: {"label": p.label, "instruction": p.instruction} for p in pose_defs}
    pose_block = {}
    for key, joints in poses.items():
        meta = pose_meta.get(key, {})
        pose_block[key] = {
            "label": meta.get("label", key),
            "instruction": meta.get("instruction", ""),
            "joints_deg": [float(x) for x in joints],
        }

    doc: Dict[str, Any] = {
        "format_version": 2,
        "kind": "glove_range_calibration",
        "meta": {
            "side": side,
            "glove_version": glove_version,
            "port": port,
            "baudrate": baudrate,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "joint_count": 21,
            "unit": "deg",
        },
        "capture": capture_params
        or {
            "stability_window": 30,
            "stability_threshold": 1.718873,  # deg
            "stable_seconds": 5.0,
            "sample_hz": 30.0,
            "aggregate": "weighted_mean",
        },
        "poses": pose_block,
    }
    if joint_range is not None:
        if len(joint_range) != 21:
            raise ValueError(f"joint_range must be length 21, got {len(joint_range)}")
        doc["joint_range"] = [float(x) for x in joint_range]
    if base is not None:
        if len(base) != 21:
            raise ValueError(f"base must be length 21, got {len(base)}")
        doc["base"] = [float(x) for x in base]
    if glove_max is not None:
        if len(glove_max) != 21:
            raise ValueError(f"glove_max must be length 21, got {len(glove_max)}")
        doc["glove_max"] = [float(x) for x in glove_max]
    return doc


def save_calibration(
    doc: Dict[str, Any],
    path: Optional[Path] = None,
    *,
    stamp: Optional[str] = None,
) -> Path:
    out_dir = default_calibration_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    if path is None:
        side = str(doc.get("meta", {}).get("side", "unknown"))
        path = default_calibration_path(side, stamp=stamp, directory=out_dir)
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_name = f.name
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name is not None:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
    return path


def find_latest_calibration(
    side: str,
    directory: Optional[Path] = None,
) -> Path:
    """在目录中找该 side 最新的 glove_{side}_*.yaml。"""
    directory = directory or default_calibration_dir()
    pattern = f"glove_{side}_*.yaml"
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"未找到标定文件: {directory / pattern}")
    return files[0]


def load_calibration(path: Path) -> Dict[str, Any]:
    """读取并校验标定 YAML 的基本结构。"""

    with Path(path).open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"标定文件顶层必须是 mapping: {path}")

    meta = doc.get("meta")
    if not isinstance(meta, dict):
        raise ValueError(f"标定文件缺少 meta mapping: {path}")
    side = meta.get("side")
    if side not in ("left", "right"):
        raise ValueError(f"标定文件 meta.side 必须是 left/right: {path}")
    if meta.get("joint_count", 21) != 21:
        raise ValueError(f"标定文件 joint_count 必须为 21: {path}")
    if meta.get("unit", "deg") != "deg":
        raise ValueError(f"{path} 不是角度制标定文件，请重新标定")

    poses = doc.get("poses")
    if not isinstance(poses, dict) or not poses:
        raise ValueError(f"标定文件 poses 必须是非空 mapping: {path}")
    for key, block in poses.items():
        if not isinstance(block, dict) or not isinstance(block.get("joints_deg"), list):
            raise ValueError(f"姿态 {key} 缺少 joints_deg: {path}")
        if len(block["joints_deg"]) != 21:
            raise ValueError(f"姿态 {key} 的 joints_deg 必须为长度 21: {path}")

    for name in ("base", "joint_range"):
        values = doc.get(name)
        if values is not None:
            if not isinstance(values, list) or len(values) != 21:
                raise ValueError(f"{name} 必须为长度 21: {path}")

    return doc
