"""触觉话题订阅话题:/cb_*_hand_matrix_touch_mass → TouchMass 回调。

和 sinks/ros_joint_state.py 对称:
  ros_joint_state.py  = 出口(publish JointCommand)
  ros_touch_mass.py   = 入口(subscribe → dispatch TouchMass)

主 node 直接 subscribe;不再另起 executor/thread(与 0903 一致,
避免 lijing_0904 那种"额外 touch_node + daemon"的复杂度)。负责从 ROS 或其他外部系统接收数据，并转换成 SDK 内部的数据结构。
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional

from ..force.touch_force_mapper import parse_touch_json
from ..force.types import TouchMass
from ..teleop.types import HandSide

TOUCH_TOPICS: Dict[str, str] = {
    "left":  "/cb_left_hand_matrix_touch_mass",
    "right": "/cb_right_hand_matrix_touch_mass",
}


class RosTouchMassSource:
    """订阅两条 std_msgs/String (JSON) → 解析 → 分发 TouchMass。

    静默保护:某侧超过 silence_warn_sec 秒无消息,WARN 一次(不刷屏)。
    坏帧计数:每 fail_warn_every 条坏 JSON 才 WARN 一次。
    """

    def __init__(
        self,
        node,
        callback: Callable[[TouchMass], None],
        *,
        silence_warn_sec: float = 3.0,
        fail_warn_every: int = 10,
        qos_depth: int = 10,
    ) -> None:
        # 导入 rclpy。
        from rclpy.node import Node
        from rclpy.qos import QoSProfile
        from std_msgs.msg import String

        if not isinstance(node, Node):
            raise TypeError("node must be an rclpy.node.Node")

        self._node = node
        self._callback = callback
        self._silence_warn_sec = float(silence_warn_sec)
        self._fail_warn_every = max(1, int(fail_warn_every))

        self._last_rx: Dict[str, float] = {side: 0.0 for side in TOUCH_TOPICS}
        self._silence_warned: Dict[str, bool] = {side: False for side in TOUCH_TOPICS}
        self._fail_count: Dict[str, int] = {side: 0 for side in TOUCH_TOPICS}

        qos = QoSProfile(depth=qos_depth)
        self._subs = []
        for side, topic in TOUCH_TOPICS.items():
            sub = node.create_subscription(
                String,
                topic,
                self._make_cb(side),  # type: ignore[arg-type]
                qos,
            )
            self._subs.append(sub)
            node.get_logger().info(f"TouchMassSource subscribe ← {topic} [{side}]")

        # 每秒检查一次静默
        self._timer = node.create_timer(1.0, self._check_silence)

    # ---- 内部 ----

    def _make_cb(self, side: HandSide):
        def _cb(msg) -> None:
            self._last_rx[side] = time.time()
            self._silence_warned[side] = False  # 收到消息就复位
            try:
                touch = parse_touch_json(msg.data, side)
            except Exception as e:  # noqa: BLE001
                self._fail_count[side] += 1
                if self._fail_count[side] % self._fail_warn_every == 1:
                    self._node.get_logger().warn(
                        f"[{side}] 触觉 JSON 解析失败 (第 {self._fail_count[side]} 条): {e}"
                    )
                return
            try:
                self._callback(touch)
            except Exception as e:  # noqa: BLE001
                self._node.get_logger().error(f"[{side}] 触觉回调抛错: {e}")
        return _cb

    def _check_silence(self) -> None:
        now = time.time()
        for side, last in self._last_rx.items():
            if last == 0.0:
                # 从未收到过。启动后过了 silence_warn_sec 才 WARN 一次
                continue
            if self._silence_warned[side]:
                continue
            if now - last > self._silence_warn_sec:
                self._silence_warned[side] = True
                self._node.get_logger().warn(
                    f"[{side}] 触觉话题静默 {self._silence_warn_sec:.1f}s: 该型号"
                    f"若无触觉可加 --no-force-feedback 关闭力反馈"
                )

    def close(self) -> None:
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None
        self._subs = []
