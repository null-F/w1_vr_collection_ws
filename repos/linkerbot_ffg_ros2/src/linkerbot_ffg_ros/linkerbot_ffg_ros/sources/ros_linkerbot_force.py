"""LinkerZ 触觉入口 → TouchMass。

未指定话题时，每侧先同时订阅 force_fns、force_fn、normal_force_resultant。
有效帧是 meta.valid 为真且 meta.stale 为假。
优先级是 fns、fn、resultant。最高优先级一有有效帧就选定；较低优先级先等 0.5 秒。
选定后只保留这一路订阅，本次运行不再更换。
无效或过期帧不往下传，也不刷新接收时间。

YAML linker_z.force_topics 若显式给出，则只在列出的话题里做同一次选定。

驱动须 force_hz>0，例: ros2 param set /linkerbot_hand force_hz 30.0
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..force.types import TouchMass
from ..teleop.types import HandSide


def command_topic_to_state_prefix(command_topic: str) -> str:
    """ /xxx/command/angles → /xxx """
    t = (command_topic or "").rstrip("/")
    marker = "/command/"
    if marker in t:
        return t.split(marker, 1)[0]
    if t.endswith("/command"):
        return t[: -len("/command")]
    return "/linkerbot_hand"


def _pad5(values: Sequence[float]) -> List[float]:
    out = [float(v) for v in values[:5]]
    while len(out) < 5:
        out.append(0.0)
    return out


def resultant_to_masses(msg) -> List[float]:
    return _pad5(getattr(msg, "normal_force_resultant", []) or [])


def force_field_to_masses(msg) -> List[float]:
    """HandForceField → 五指质量。

    - force_fns: raw 长度 1 → 取 raw[0]
    - force_fn: 点阵 → 对 raw 求和
    """
    sensors = getattr(msg, "sensors", None) or []
    values: List[float] = []
    for sensor in sensors[:5]:
        raw = getattr(sensor, "raw", None) or []
        present = bool(getattr(sensor, "present", True))
        if not present or not raw:
            values.append(0.0)
            continue
        if len(raw) == 1:
            values.append(float(raw[0]))
        else:
            values.append(float(sum(float(x) for x in raw)))
    return _pad5(values)


# 越靠前越优先。较低优先级在选定前的等待时间。
SOURCE_PRIORITY = ("fns", "fn", "resultant")
SOURCE_HOLD_SEC = 0.5


def frame_is_fresh(msg) -> bool:
    """整帧是一次新测量：valid 为真，且 stale 为假。缺 meta 时不算。"""
    meta = getattr(msg, "meta", None)
    if meta is None:
        return False
    if not bool(getattr(meta, "valid", False)):
        return False
    if bool(getattr(meta, "stale", True)):
        return False
    return True


def default_force_topics(command_topic: str) -> List[Tuple[str, str]]:
    """由指令话题推出三路力话题，启动时全部订阅。"""
    prefix = command_topic_to_state_prefix(command_topic)
    return [
        (f"{prefix}/state/force_fns", "fns"),
        (f"{prefix}/state/force_fn", "fn"),
        (f"{prefix}/state/normal_force_resultant", "resultant"),
    ]


def resolve_force_topics_for_side(
    _node,
    command_topic: str,
    *,
    override: Optional[Sequence[str]] = None,
) -> List[Tuple[str, str]]:
    """返回 [(topic, mode), ...]。override 非空则只用这些话题。"""
    if override:
        out: List[Tuple[str, str]] = []
        for topic in override:
            t = str(topic)
            if t.endswith("force_fns"):
                out.append((t, "fns"))
            elif t.endswith("normal_force_resultant"):
                out.append((t, "resultant"))
            elif t.endswith("force_fn"):
                out.append((t, "fn"))
            else:
                out.append((t, "custom"))
        return out
    return default_force_topics(command_topic)


class ForceSourceArbiter:
    """一侧只选定一次力源。选定后不再更换。"""

    def __init__(
        self,
        modes: Sequence[str],
        *,
        hold_sec: float = SOURCE_HOLD_SEC,
    ) -> None:
        allowed = {str(mode) for mode in modes if str(mode) in SOURCE_PRIORITY}
        self._allowed = tuple(mode for mode in SOURCE_PRIORITY if mode in allowed)
        self._hold_sec = float(hold_sec)
        self._first_fresh: Dict[str, float] = {}
        self._active: Optional[str] = None
        self.just_locked = False

    @property
    def active(self) -> Optional[str]:
        return self._active

    def observe(self, mode: str, now: float) -> bool:
        """记下有效帧。已选定则只接受这一路；未选定则可能在这一帧完成选定。"""
        self.just_locked = False
        mode = str(mode)
        now = float(now)
        if mode not in self._allowed:
            return False
        if self._active is not None:
            return mode == self._active
        self._first_fresh.setdefault(mode, now)
        self._try_lock(now)
        return self._active == mode

    def poll(self, now: float) -> Optional[str]:
        """等待时间到了就选定。返回这一次新选定的话题，已经选定则返回 None。"""
        self.just_locked = False
        if self._active is not None:
            return None
        self._try_lock(float(now))
        if self.just_locked:
            return self._active
        return None

    def _try_lock(self, now: float) -> None:
        if self._active is not None or not self._first_fresh or not self._allowed:
            return
        best = next(
            mode
            for mode in self._allowed
            if mode in self._first_fresh
        )
        if best == self._allowed[0] or now - min(self._first_fresh.values()) >= self._hold_sec:
            self._active = best
            self.just_locked = True


class RosLinkerbotForceSource:
    """先听候选力话题，选定一路后只保留该订阅。"""

    def __init__(
        self,
        node,
        callback: Callable[[TouchMass], None],
        *,
        topics_by_side: Dict[str, Sequence[Tuple[str, str]]],
        silence_warn_sec: float = 3.0,
        qos_depth: int = 10,
    ) -> None:
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from linkerbot_hand_msgs.msg import HandForceField, HandNormalForceResultant

        if not isinstance(node, Node):
            raise TypeError("node must be an rclpy.node.Node")

        self._node = node
        self._callback = callback
        self._silence_warn_sec = float(silence_warn_sec)
        self._last_rx: Dict[str, float] = {}
        self._silence_warned: Dict[str, bool] = {}
        self._started_mono = time.monotonic()
        self._subs: List[Tuple[str, str, object]] = []
        self._chosen: Dict[str, str] = {}
        self._arbiters: Dict[str, ForceSourceArbiter] = {}

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=qos_depth,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )

        for side, items in topics_by_side.items():
            side_key = str(side)
            self._last_rx[side_key] = 0.0
            self._silence_warned[side_key] = False
            self._arbiters[side_key] = ForceSourceArbiter(())
            subscribed: List[str] = []
            for topic, mode in items:
                topic = str(topic)
                mode = str(mode)
                if mode in ("fns", "fn") or topic.endswith(("force_fns", "force_fn")):
                    if mode not in SOURCE_PRIORITY:
                        mode = "fns" if topic.endswith("force_fns") else "fn"
                    msg_type = HandForceField
                    converter = force_field_to_masses
                elif mode == "resultant" or topic.endswith("normal_force_resultant"):
                    mode = "resultant"
                    msg_type = HandNormalForceResultant
                    converter = resultant_to_masses
                else:
                    node.get_logger().warn(
                        f"[{side_key}] 未知 LinkerZ 力话题，跳过: {topic} ({mode})"
                    )
                    continue
                sub = node.create_subscription(
                    msg_type,
                    topic,
                    self._make_cb(side_key, mode, converter),
                    qos,
                )
                self._subs.append((side_key, mode, sub))
                subscribed.append(mode)
                how = {
                    "fns": "五指标量 force_fns",
                    "resultant": "五指合力 normal_force_resultant",
                    "fn": "点阵 force_fn → 每指求和",
                }.get(mode, mode)
                node.get_logger().info(
                    f"LinkerbotForceSource[{side_key}] ← {topic}  [{how}]"
                )
            self._arbiters[side_key] = ForceSourceArbiter(subscribed)
            self._chosen[side_key] = ",".join(subscribed) if subscribed else "?"

        self._timer = node.create_timer(1.0, self._check_silence)
        self._lock_timer = node.create_timer(0.1, self._poll_lock)

    def _make_cb(self, side: HandSide, mode: str, converter):
        def _cb(msg) -> None:
            if not frame_is_fresh(msg):
                return
            try:
                values = converter(msg)
                touch = TouchMass(side=side, values=values)  # type: ignore[arg-type]
            except Exception as e:  # noqa: BLE001
                self._node.get_logger().warn(f"[{side}] LinkerZ 力解析失败: {e}")
                return
            side_key = str(side)
            arbiter = self._arbiters[side_key]
            if not arbiter.observe(mode, time.monotonic()):
                return
            if arbiter.just_locked:
                self._retain_locked(side_key, mode)
            self._last_rx[side] = time.time()
            self._silence_warned[side] = False
            try:
                self._callback(touch)
            except Exception as e:  # noqa: BLE001
                self._node.get_logger().error(f"[{side}] 力反馈回调抛错: {e}")

        return _cb

    def _poll_lock(self) -> None:
        now = time.monotonic()
        for side, arbiter in self._arbiters.items():
            locked = arbiter.poll(now)
            if locked is not None:
                self._retain_locked(side, locked)

    def _retain_locked(self, side: str, mode: str) -> None:
        """选定后拆掉同侧其他力话题订阅。"""
        self._chosen[side] = mode
        kept = []
        for item in self._subs:
            item_side, item_mode, sub = item
            if item_side == side and item_mode != mode:
                try:
                    self._node.destroy_subscription(sub)
                except Exception:  # noqa: BLE001
                    pass
                continue
            kept.append(item)
        self._subs = kept
        self._node.get_logger().info(f"[{side}] LinkerZ 力源选定为 {mode}")

    def _check_silence(self) -> None:
        now = time.time()
        mono = time.monotonic()
        for side, last in self._last_rx.items():
            if self._silence_warned[side]:
                continue
            chosen = self._chosen.get(side, "?")
            if last == 0.0:
                if mono - self._started_mono < self._silence_warn_sec:
                    continue
                self._silence_warned[side] = True
                self._node.get_logger().warn(
                    f"[{side}] LinkerZ 力话题启动后 {self._silence_warn_sec:.0f}s 无数据 "
                    f"(chosen={chosen})。请确认 force_hz>0 且驱动已 activate。"
                )
                continue
            if now - last > self._silence_warn_sec:
                self._silence_warned[side] = True
                self._node.get_logger().warn(
                    f"[{side}] LinkerZ 力话题静默 {self._silence_warn_sec:.1f}s "
                    f"(chosen={chosen})"
                )

    def close(self) -> None:
        for timer_name in ("_timer", "_lock_timer"):
            timer = getattr(self, timer_name, None)
            if timer is None:
                continue
            try:
                timer.cancel()
            except Exception:
                pass
            setattr(self, timer_name, None)
        self._subs = []
