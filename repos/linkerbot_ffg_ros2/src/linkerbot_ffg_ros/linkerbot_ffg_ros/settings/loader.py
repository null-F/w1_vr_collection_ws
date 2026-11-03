"""读 YAML,融合 CLI,输出 Settings。所有 YAML 结构知识都住在这一个文件里。
加载和解析配置"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal, Optional

import yaml

from .types import (
    ForceFeedbackSpec,
    HandSdk,
    LinkerZSpec,
    SerialSpec,
    Settings,
)

def default_config_path() -> Path:
    """安装后的 share/linkerbot_ffg_ros/config/default.yaml。"""
    try:
        from ament_index_python.packages import (
            PackageNotFoundError,
            get_package_share_directory,
        )
    except ImportError as e:
        raise FileNotFoundError(
            "未找到 ament_index_python。请先 source /opt/ros/jazzy/setup.bash"
            " 和本仓库的 install/setup.bash"
        ) from e
    try:
        share = Path(get_package_share_directory("linkerbot_ffg_ros"))
    except PackageNotFoundError as e:
        raise FileNotFoundError(
            "未找到包 linkerbot_ffg_ros。请先 source install/setup.bash"
        ) from e
    path = share / "config" / "default.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    return path

_CliForce = Literal["on", "off", None]
_VALID_HAND_SDKS = ("LinkerH", "LinkerZ")


def load_yaml(path: Optional[Path] = None) -> dict:
    """读 YAML,不存在或空则抛清楚的错误。"""
    p = Path(path) if path is not None else default_config_path()
    if not p.is_file():
        raise FileNotFoundError(f"配置文件不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"配置文件顶层必须是 mapping: {p}")
    return doc


def _get(doc: dict, path: str, default: Any = None) -> Any:
    """按 'a.b.c' 取嵌套 dict 值,任何一环缺失返回 default。"""
    cur: Any = doc
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _parse_bool(value: Any, field: str) -> bool:
    """解析配置开关。字符串 false 为关闭。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "on", "1"):
            return True
        if text in ("false", "no", "off", "0"):
            return False
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise ValueError(f"{field} 必须是布尔值, got {value!r}")


def _require_positive_finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{field} 必须是大于 0 的有限数, got {value!r}") from e
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} 必须是大于 0 的有限数, got {value!r}")
    return number


def _parse_baud(value: Any, field: str) -> int:
    try:
        baud = int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{field} 必须是正整数, got {value!r}") from e
    if baud <= 0:
        raise ValueError(f"{field} 必须是正整数, got {value!r}")
    return baud


def _clamp_max_force(value: int, hardware_limit: int) -> tuple[int, bool]:
    """返回 (clamped_value, was_clipped)。负数会 raise。"""
    if value < 0:
        raise ValueError(f"max_force 不可为负: {value}")
    if value > hardware_limit:
        return hardware_limit, True
    return value, False


def _normalize_hand_sdk(raw: Any) -> HandSdk:
    if raw is None:
        return "LinkerH"
    text = str(raw).strip()
    # 允许大小写变体
    lowered = text.lower()
    if lowered in ("linkerh", "h", "linkerhand", "ros2-sdk"):
        return "LinkerH"
    if lowered in ("linkerz", "z", "linkerbot", "zhu"):
        return "LinkerZ"
    if text in _VALID_HAND_SDKS:
        return text  # type: ignore[return-value]
    raise ValueError(
        f"system.hand_sdk 无效: {raw!r}，可选: {list(_VALID_HAND_SDKS)}"
    )


def _validate_force_feedback(*, trigger_mass: int) -> None:
    """检查 force_feedback.trigger_mass 不为负。"""
    if trigger_mass < 0:
        raise ValueError(
            f"force_feedback.trigger_mass 不可为负: {trigger_mass}"
        )


def _resolve_force(
    doc: dict,
    robot: str,
    *,
    cli_force: _CliForce,
    cli_force_max: Optional[int],
) -> ForceFeedbackSpec:
    """解析力反馈配置。"""
    fb = _get(doc, "force_feedback", {}) or {}
    trigger_mass = int(fb.get("trigger_mass", 200))
    mass_max = int(fb.get("mass_max", 2000))
    force_onset = int(fb.get("force_onset", 150))
    hardware_limit = int(fb.get("hardware_limit", 1000))
    _validate_force_feedback(trigger_mass=trigger_mass)

    by_robot = (fb.get("by_robot") or {})
    robot_spec = by_robot.get(robot) if isinstance(by_robot, dict) else None
    default_spec = fb.get("default") or {}
    global_enabled = fb.get("enabled")

    # enabled: by_robot.enabled > force_feedback.enabled > default.enabled > True
    if isinstance(robot_spec, dict) and "enabled" in robot_spec:
        base_enabled = _parse_bool(
            robot_spec["enabled"], f"force_feedback.by_robot.{robot}.enabled"
        )
        enabled_source = f"yaml.by_robot.{robot}.enabled"
    elif global_enabled is not None:
        base_enabled = _parse_bool(global_enabled, "force_feedback.enabled")
        enabled_source = "yaml.force_feedback.enabled"
    elif "enabled" in default_spec:
        base_enabled = _parse_bool(default_spec["enabled"], "force_feedback.default.enabled")
        enabled_source = "yaml.default.enabled"
    else:
        base_enabled = True
        enabled_source = "builtin default on"

    if isinstance(robot_spec, dict) and "max_force" in robot_spec:
        base_max = int(robot_spec["max_force"])
        max_source = f"yaml.by_robot.{robot}.max_force"
    else:
        base_max = int(default_spec.get("max_force", 500))
        max_source = "yaml.default.max_force"

    # CLI 覆盖
    if cli_force == "off":
        enabled = False
        max_force_raw = base_max
        source = "cli --no-force-feedback"
    elif cli_force == "on":
        enabled = True
        if cli_force_max is not None:
            max_force_raw = cli_force_max
            source = f"cli -F {cli_force_max}"
        else:
            max_force_raw = base_max
            source = f"cli -F (+ {max_source})"
    else:
        enabled = base_enabled
        max_force_raw = base_max
        source = f"{enabled_source}; {max_source}"

    max_force, clipped = _clamp_max_force(max_force_raw, hardware_limit)
    if clipped:
        source = f"{source} → clipped to hardware_limit={hardware_limit}"

    return ForceFeedbackSpec(
        enabled=enabled,
        max_force=max_force,
        trigger_mass=trigger_mass,
        mass_max=mass_max,
        force_onset=force_onset,
        hardware_limit=hardware_limit,
        source=source,
    )


def _resolve_serial(
    doc: dict,
    *,
    cli_port: Optional[str],
    cli_baud: Optional[int],
) -> SerialSpec:
    s = _get(doc, "serial", {}) or {}
    left = (s.get("left") or {})
    right = (s.get("right") or {})
    raw_bauds = s.get("baudrates")
    if raw_bauds in (None, "", "null"):
        baudrates = [2000000, 460800, 1000000, 921600]
    elif isinstance(raw_bauds, (list, tuple)) and raw_bauds:
        baudrates = [
            _parse_baud(item, "serial.baudrates") for item in raw_bauds
        ]
    else:
        raise ValueError(f"serial.baudrates 必须是非空列表, got {raw_bauds!r}")
    left_port = cli_port if cli_port else left.get("port")
    right_port = cli_port if cli_port else right.get("port")
    return SerialSpec(
        auto_scan=_parse_bool(s.get("auto_scan", True), "serial.auto_scan"),
        baudrates=baudrates,
        left_port=None if left_port in (None, "", "null") else str(left_port),
        left_baud=_parse_baud(
            cli_baud if cli_baud else left.get("baudrate", 2000000),
            "serial.left.baudrate",
        ),
        right_port=None if right_port in (None, "", "null") else str(right_port),
        right_baud=_parse_baud(
            cli_baud if cli_baud else right.get("baudrate", 2000000),
            "serial.right.baudrate",
        ),
    )


def _resolve_linker_z(doc: dict) -> LinkerZSpec:
    z = _get(doc, "linker_z", {}) or {}
    command_topic = str(z.get("command_topic") or "/linkerbot_hand/command/angles")
    raw_topics = z.get("topics") or {}
    topics: dict[str, str] = {}
    for side in ("left", "right"):
        t = raw_topics.get(side) if isinstance(raw_topics, dict) else None
        if t in (None, "", "null"):
            topics[side] = ""
        else:
            topics[side] = str(t)
    client_id = int(z.get("client_id", 1))
    if client_id <= 0:
        raise ValueError(f"linker_z.client_id 必须为正整数, got {client_id}")

    force_topics: dict[str, list[str]] = {}
    raw_force = z.get("force_topics") or {}
    if isinstance(raw_force, dict):
        for side in ("left", "right"):
            entry = raw_force.get(side)
            if entry in (None, "", "null"):
                continue
            if isinstance(entry, str):
                force_topics[side] = [entry]
            elif isinstance(entry, (list, tuple)):
                force_topics[side] = [str(x) for x in entry if x not in (None, "", "null")]
            else:
                raise ValueError(
                    f"linker_z.force_topics.{side} 须为字符串或列表, got {type(entry)}"
                )

    return LinkerZSpec(
        client_id=client_id,
        command_topic=command_topic,
        topics=topics,
        o30_swap_01=_parse_bool(z.get("o30_swap_01", False), "linker_z.o30_swap_01"),
        force_topics=force_topics,
        capabilities_topic=str(
            z.get("capabilities_topic") or "/linkerbot_hand/capabilities"
        ),
        discover_timeout_sec=float(z.get("discover_timeout_sec", 5.0)),
    )


def apply_discovered_robot(
    settings: Settings,
    yaml_doc: dict,
    robot: str,
    *,
    source: str,
    cli_force: _CliForce = None,
    cli_force_max: Optional[int] = None,
) -> Settings:
    """自动识别后写入 robot，并按新型号重算力反馈。"""
    from dataclasses import replace

    force = _resolve_force(
        yaml_doc,
        robot,
        cli_force=cli_force,
        cli_force_max=cli_force_max,
    )
    return replace(settings, robot=robot, force=force, robot_source=source)


def resolve_settings(
    yaml_doc: dict,
    *,
    cli_robot: Optional[str] = None,
    cli_hand_sdk: Optional[str] = None,
    cli_force: _CliForce = None,
    cli_force_max: Optional[int] = None,
    cli_rate: Optional[float] = None,
    cli_calib_dir: Optional[Path] = None,
    cli_port: Optional[str] = None,
    cli_baud: Optional[int] = None,
    cli_no_smooth: bool = False,
    cli_smooth_alpha: Optional[float] = None,
    cli_smooth_max_step: Optional[float] = None,
) -> Settings:
    """把 YAML + CLI 融合成 Settings。robot 可为 auto，由 teleop 再探测。"""
    if cli_robot is not None:
        robot = str(cli_robot).strip().lower()
        robot_source = f"cli --robot {robot}"
    else:
        robot = str(_get(yaml_doc, "system.robot") or "auto").strip().lower()
        robot_source = "yaml.system.robot"

    hand_sdk = _normalize_hand_sdk(
        cli_hand_sdk if cli_hand_sdk is not None else _get(yaml_doc, "system.hand_sdk")
    )

    teleop = _get(yaml_doc, "teleop", {}) or {}
    rate_hz = _require_positive_finite(
        cli_rate if cli_rate is not None else teleop.get("rate_hz", 30.0),
        "teleop.rate_hz",
    )
    smooth = False if cli_no_smooth else _parse_bool(teleop.get("smooth", True), "teleop.smooth")
    smooth_alpha = float(
        cli_smooth_alpha if cli_smooth_alpha is not None else teleop.get("smooth_alpha", 0.5)
    )
    smooth_max_step = float(
        cli_smooth_max_step
        if cli_smooth_max_step is not None
        else teleop.get("smooth_max_step", 20.0)
    )
    if not math.isfinite(smooth_alpha) or not (0.0 < smooth_alpha <= 1.0):
        raise ValueError(f"smooth_alpha 必须在 (0, 1] 内，收到 {smooth_alpha}")
    if not math.isfinite(smooth_max_step) or smooth_max_step <= 0.0:
        raise ValueError(f"smooth_max_step 必须大于 0，收到 {smooth_max_step}")

    calib_dir_raw = cli_calib_dir if cli_calib_dir else teleop.get("calib_dir")
    calib_dir: Optional[Path] = None
    if calib_dir_raw not in (None, "", "null"):
        calib_dir = Path(calib_dir_raw)

    # auto 时先用力反馈 default；识别后再 apply_discovered_robot 重算
    force_robot = "default" if robot == "auto" else robot
    force = _resolve_force(
        yaml_doc, force_robot,
        cli_force=cli_force,
        cli_force_max=cli_force_max,
    )
    serial = _resolve_serial(yaml_doc, cli_port=cli_port, cli_baud=cli_baud)
    linker_z = _resolve_linker_z(yaml_doc)

    return Settings(
        robot=robot,
        hand_sdk=hand_sdk,
        rate_hz=rate_hz,
        smooth=smooth,
        smooth_alpha=smooth_alpha,
        smooth_max_step=smooth_max_step,
        calib_dir=calib_dir,
        serial=serial,
        force=force,
        linker_z=linker_z,
        robot_source=robot_source,
    )
