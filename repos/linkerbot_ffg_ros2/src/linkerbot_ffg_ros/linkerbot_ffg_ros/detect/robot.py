"""自动识别灵巧手型号。

LinkerZ: 订 /linkerbot_hand/capabilities → identity.model
LinkerH: 只读运行中驱动上报的 /cb_{side}_hand_info → hand_joint
读不到 hand_joint 时要求调用方写明 robot，不扫描本机路径。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from ..teleop.registry import canonicalize_robot_name


def normalize_robot_name(raw: str) -> str:
    """把各种写法归一成 registry 里的 key；失败抛 ValueError。"""
    return canonicalize_robot_name(raw)


def _hand_joint_name(data: dict) -> Optional[str]:
    joint = data.get("hand_joint") or data.get("handJoint") or data.get("joint")
    if not joint:
        return None
    text = str(joint).strip()
    return text or None


@dataclass(frozen=True)
class LinkerHModel:
    """LinkerH 从 hand_info 得到的型号。"""

    robot: str
    raw: str
    source: str
    info_sides: Tuple[str, ...]
    # 已连接手套没有 hand_info 时，型号来自这些对侧。
    borrowed_from: Tuple[str, ...]


def linker_h_reported_sides(got: dict) -> Tuple[str, ...]:
    """哪些侧的 hand_info 里带了 hand_joint。不校验型号名。"""
    sides = []
    for side in ("left", "right"):
        data = got.get(side)
        if isinstance(data, dict) and _hand_joint_name(data):
            sides.append(side)
    return tuple(sides)


def linker_h_robot_from_payloads(
    got: dict,
    active_sides: Sequence[str] = ("left", "right"),
) -> LinkerHModel:
    """从两侧 hand_info JSON 决定型号。

    已连接手套里有 hand_joint 的侧必须型号一致，用该型号。
    已连接手套都没有，才借用对侧型号，并记在 borrowed_from。
    没有任何 hand_joint，或用来决定型号的两侧不一致时抛 ValueError。
    """
    found: list[tuple[str, str, str]] = []
    for side in ("left", "right"):
        data = got.get(side)
        if not isinstance(data, dict):
            continue
        joint_s = _hand_joint_name(data)
        if not joint_s:
            continue
        found.append((side, joint_s, normalize_robot_name(joint_s)))
    if not found:
        raise ValueError(f"/cb_*_hand_info 消息里没有 hand_joint: {got}")

    active = {side for side in active_sides if side in ("left", "right")}
    chosen = [item for item in found if item[0] in active]
    borrowed = [item for item in found if item[0] not in active]
    if not chosen:
        chosen = borrowed
        borrowed_from = tuple(side for side, _joint, _robot in borrowed)
    else:
        borrowed_from = ()

    robots = {robot for _side, _joint, robot in chosen}
    if len(robots) > 1:
        detail = ", ".join(f"{side}={joint}" for side, joint, _robot in chosen)
        raise ValueError(
            f"左右手型号不一致: {detail}。"
            "请在 system.robot 或 --robot 中写明型号"
        )
    robot = chosen[0][2]
    raw = ", ".join(f"{side}={joint}" for side, joint, _robot in chosen)
    topics = ", ".join(f"/cb_{side}_hand_info" for side, _joint, _robot in chosen)
    if borrowed_from:
        src = (
            f"已连接手套没有 hand_info，型号来自 {raw}\n"
            f"  topic: {topics}"
        )
    else:
        src = (
            f"ROS hand_joint {raw}  (驱动实时上报)\n"
            f"  topic: {topics}"
        )
    return LinkerHModel(
        robot=robot,
        raw=raw,
        source=src,
        info_sides=tuple(side for side, _joint, _robot in found),
        borrowed_from=borrowed_from,
    )


def collect_linker_h_payloads(
    node,
    *,
    timeout_sec: float = 2.0,
) -> dict:
    """订左右 /cb_*_hand_info，直到两侧都有 hand_joint 或超时。返回 side → JSON。"""
    import time

    import rclpy
    from std_msgs.msg import String

    sides = ("left", "right")
    got: dict[str, dict] = {}

    def _make_cb(side: str):
        def _cb(msg) -> None:
            try:
                data = json.loads(msg.data)
            except Exception:  # noqa: BLE001
                return
            if isinstance(data, dict):
                got[side] = data
        return _cb

    subs = []
    for side in sides:
        topic = f"/cb_{side}_hand_info"
        subs.append(
            node.create_subscription(String, topic, _make_cb(side), 10)
        )
    try:
        deadline = time.monotonic() + max(0.3, float(timeout_sec))
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if all(side in got and _hand_joint_name(got[side]) for side in sides):
                break
        return got
    finally:
        for sub in subs:
            try:
                node.destroy_subscription(sub)
            except Exception:  # noqa: BLE001
                pass


def discover_robot_linker_h_from_info(
    node,
    *,
    timeout_sec: float = 2.0,
    active_sides: Sequence[str] = ("left", "right"),
) -> Tuple[str, str, str]:
    """订左右 /cb_*_hand_info，读 JSON hand_joint。返回 (robot, raw_joint, source)。"""
    got = collect_linker_h_payloads(node, timeout_sec=timeout_sec)
    if not got:
        raise TimeoutError(
            f"等待 /cb_*_hand_info 超时 ({timeout_sec}s)。请先启动 LinkerH 驱动"
        )
    found = linker_h_robot_from_payloads(got, active_sides=active_sides)
    return found.robot, found.raw, found.source


def discover_robot_linker_h(
    *,
    node=None,
    timeout_sec: float = 2.0,
    active_sides: Sequence[str] = ("left", "right"),
) -> Tuple[str, str]:
    """LinkerH 自动识别。只读 /cb_*_hand_info。返回 (robot, source_说明)。"""
    if node is None:
        raise RuntimeError(
            "LinkerH 自动识别需要已启动的驱动话题 /cb_*_hand_info。"
            "请在 system.robot 或 --robot 中写明型号："
            "o6 / l6 / l10 / l20lite / o30 / l20"
        )
    try:
        robot, _joint, src = discover_robot_linker_h_from_info(
            node, timeout_sec=timeout_sec, active_sides=active_sides
        )
        return robot, src
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"LinkerH 手型识别失败: {e}。"
            "请在 system.robot 或 --robot 中写明型号："
            "o6 / l6 / l10 / l20lite / o30 / l20"
        ) from e


def discover_robot_linker_z(
    node,
    *,
    capabilities_topic: str = "/linkerbot_hand/capabilities",
    timeout_sec: float = 5.0,
) -> Tuple[str, str]:
    """订 capabilities，读 identity.model。返回 (robot, source_说明)。"""
    import time

    import rclpy
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from linkerbot_hand_msgs.msg import HandCapabilities

    got = []

    def _cb(msg) -> None:
        got.append(msg)

    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    sub = node.create_subscription(HandCapabilities, capabilities_topic, _cb, qos)
    try:
        deadline = time.monotonic() + max(0.5, float(timeout_sec))
        while time.monotonic() < deadline and not got:
            rclpy.spin_once(node, timeout_sec=0.1)
        if not got:
            raise TimeoutError(
                f"等待 {capabilities_topic} 超时 ({timeout_sec}s)。"
                f"请确认 LinkerZ 驱动已 activate，并已 source linkerbot_hand_msgs"
            )
        model = str(getattr(got[0].identity, "model", "") or "")
        side = str(getattr(got[0].identity, "side", "") or "")
        robot = normalize_robot_name(model)
        src = (
            f"LinkerZ {capabilities_topic} model={model!r} side={side!r}\n"
            f"  → 内部型号 robot={robot}"
        )
        return robot, src
    finally:
        try:
            node.destroy_subscription(sub)
        except Exception:  # noqa: BLE001
            pass


def discover_robot(
    hand_sdk: str,
    *,
    node=None,
    capabilities_topic: str = "/linkerbot_hand/capabilities",
    timeout_sec: float = 5.0,
    active_sides: Sequence[str] = ("left", "right"),
) -> Tuple[str, str]:
    """按 hand_sdk 自动识别。返回 (robot, source)。"""
    sdk = (hand_sdk or "").strip()
    if sdk == "LinkerZ":
        if node is None:
            raise ValueError("LinkerZ 自动识别需要 rclpy Node")
        return discover_robot_linker_z(
            node,
            capabilities_topic=capabilities_topic,
            timeout_sec=timeout_sec,
        )
    if sdk == "LinkerH":
        return discover_robot_linker_h(
            node=node,
            timeout_sec=min(timeout_sec, 3.0),
            active_sides=active_sides,
        )
    raise ValueError(f"未知 hand_sdk: {hand_sdk!r}")


def print_robot_discovery(
    *,
    hand_sdk: str,
    robot: str,
    source: str,
    raw_hint: Optional[str] = None,
) -> None:
    """终端醒目打印识别结果。"""
    line = "=" * 56
    print(f"\n{line}")
    print("【手型识别】")
    print(f"  SDK后端 : {hand_sdk}")
    print(f"  识别结果 : robot={robot}" + (f"  (原始={raw_hint})" if raw_hint else ""))
    print("  数据来源 :")
    for ln in str(source).splitlines():
        print(f"    {ln}" if ln.strip() else "")
    print(line + "\n")
