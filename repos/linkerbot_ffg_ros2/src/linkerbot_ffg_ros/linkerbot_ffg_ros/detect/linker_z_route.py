"""按手部节点的 capabilities 话题确定左右手指令话题。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple

from .robot import normalize_robot_name


@dataclass(frozen=True)
class LinkerZHand:
    capabilities_topic: str
    model: str
    side: str


def command_topic_for_capabilities(capabilities_topic: str) -> str:
    """ /ns/linkerbot_hand/capabilities → /ns/linkerbot_hand/command/angles """
    topic = (capabilities_topic or "").rstrip("/")
    suffix = "/capabilities"
    if topic.endswith(suffix):
        topic = topic[: -len(suffix)]
    return f"{topic}/command/angles"


@dataclass(frozen=True)
class LinkerZBind:
    """手套和手部节点按侧对齐后的结果。

    routes 只包含有节点的手套侧。没有节点的手套在 missing_sides，不发布。
    有驱动但没有对应手套的侧在 idle_topics。
    """

    robot: Optional[str]
    routes: Dict[str, str]
    missing_sides: Tuple[str, ...]
    idle_topics: Dict[str, str]


def bind_linker_z_routes(
    active_sides: Sequence[str],
    hands: Iterable[LinkerZHand],
    explicit_topics: Optional[Dict[str, str]] = None,
) -> LinkerZBind:
    """按已连接手套绑定指令话题。

    某一侧没有节点时不抛错，调用方跳过该侧。
    同一侧多个节点、左右话题相同，或已绑定的两侧型号不同时抛出 ValueError。
    """
    explicit_topics = explicit_topics or {}
    grouped: Dict[str, Dict[Tuple[str, str], None]] = {"left": {}, "right": {}}
    for hand in hands:
        side = (hand.side or "").strip().lower()
        if side not in grouped:
            continue
        robot = normalize_robot_name(hand.model)
        topic = command_topic_for_capabilities(hand.capabilities_topic)
        grouped[side][(topic, robot)] = None

    active = [side for side in active_sides if side in grouped]
    routes: Dict[str, str] = {}
    models: list[str] = []
    missing: list[str] = []
    for side in active:
        matches = list(grouped.get(side) or {})
        if len(matches) == 0:
            missing.append(side)
            continue
        if len(matches) > 1:
            detail = ", ".join(sorted(topic for topic, _robot in matches))
            raise ValueError(f"[{side}] 有多个手部节点: {detail}")
        topic, robot = matches[0]
        explicit = (explicit_topics.get(side) or "").strip()
        if explicit and explicit != topic:
            raise ValueError(
                f"[{side}] 配置话题 {explicit} 与手部节点 {topic} 不一致"
            )
        routes[side] = explicit or topic
        models.append(robot)

    if len(set(routes.values())) != len(routes):
        detail = ", ".join(f"{side}={routes[side]}" for side in routes)
        raise ValueError(f"左右手指令话题相同，无法分开控制: {detail}")
    if len(set(models)) > 1:
        detail = ", ".join(
            f"{side}={model}" for side, model in zip(routes, models)
        )
        raise ValueError(f"左右手型号不一致: {detail}")

    idle_topics: Dict[str, str] = {}
    for side in ("left", "right"):
        if side in active:
            continue
        matches = list(grouped.get(side) or {})
        if not matches:
            continue
        idle_topics[side] = ", ".join(sorted(topic for topic, _robot in matches))
    robot = models[0] if models else None
    return LinkerZBind(
        robot=robot,
        routes=routes,
        missing_sides=tuple(missing),
        idle_topics=idle_topics,
    )


def discover_linker_z_hands(
    node,
    *,
    timeout_sec: float,
    extra_topics: Sequence[str] = (),
) -> list[LinkerZHand]:
    """订阅 capabilities，收集 (话题, 型号, 左右)。"""
    import rclpy
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from linkerbot_hand_msgs.msg import HandCapabilities

    found: Dict[Tuple[str, str, str], LinkerZHand] = {}
    subs = []
    subscribed: set[str] = set()

    def _on_capabilities(topic: str, msg) -> None:
        identity = getattr(msg, "identity", None)
        model = str(getattr(identity, "model", "") or "")
        side = str(getattr(identity, "side", "") or "").strip().lower()
        found[(topic, model, side)] = LinkerZHand(
            capabilities_topic=topic,
            model=model,
            side=side,
        )

    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )

    def _remember(topic: str) -> None:
        if not topic or topic in subscribed:
            return
        subs.append(
            node.create_subscription(
                HandCapabilities,
                topic,
                lambda msg, topic=topic: _on_capabilities(topic, msg),
                qos,
            )
        )
        subscribed.add(topic)

    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    try:
        while time.monotonic() < deadline:
            for topic in extra_topics:
                _remember(topic)
            try:
                graph = node.get_topic_names_and_types()
            except Exception:
                graph = []
            for name, types in graph:
                if "linkerbot_hand_msgs/msg/HandCapabilities" in types or (
                    name.endswith("/linkerbot_hand/capabilities")
                ):
                    _remember(name)
            rclpy.spin_once(node, timeout_sec=0.1)
        return list(found.values())
    finally:
        for sub in subs:
            try:
                node.destroy_subscription(sub)
            except Exception:
                pass
