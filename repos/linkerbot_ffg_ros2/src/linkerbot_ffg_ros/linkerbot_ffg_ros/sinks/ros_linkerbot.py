"""LinkerZ 出口：JointCommand → linkerbot_hand_msgs/HandJointCommand (RAW)。

发到 /linkerbot_hand/command/angles（或 YAML 按手指定的话题）。
关节顺序由 sinks.remap.remap_for_linker_z 按型号处理。
"""

from __future__ import annotations

from typing import Dict

from ..settings.types import LinkerZSpec
from ..teleop.types import HandSide, JointCommand
from .remap import expected_z_dims, remap_for_linker_z

_UINT64_MAX = (1 << 64) - 1


class RosLinkerbotSink:
    """ROS2 HandJointCommand 输出；positions 为协议 raw 0~255。"""

    def __init__(
        self,
        node,
        *,
        robot: str,
        linker_z: LinkerZSpec,
    ) -> None:
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from linkerbot_hand_msgs.msg import HandJointCommand

        if not isinstance(node, Node):
            raise TypeError("node must be an rclpy.node.Node")

        self._node = node
        self._robot = (robot or "").strip().lower()
        self._spec = linker_z
        self._HandJointCommand = HandJointCommand
        self._expected_out = expected_z_dims(self._robot)
        self._sequence = 0

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self._pubs: Dict[str, object] = {}
        for side in ("left", "right"):
            topic = (linker_z.topics.get(side) or "").strip()
            if not topic:
                continue
            self._pubs[side] = node.create_publisher(HandJointCommand, topic, qos)
            node.get_logger().info(
                f"LinkerbotSink[{side}] robot={self._robot} "
                f"→ {topic} (RAW, out_dims={self._expected_out}"
                f"{', o30_swap_01' if linker_z.o30_swap_01 and self._robot == 'o30' else ''})"
            )

    def topic_for(self, side: HandSide) -> str:
        return (self._spec.topics.get(side) or "").strip()

    def publish(self, cmd: JointCommand) -> None:
        if cmd.side not in ("left", "right"):
            raise ValueError(f"unsupported side: {cmd.side}")
        if cmd.side not in self._pubs:
            return
        try:
            values = remap_for_linker_z(
                self._robot,
                cmd.positions,
                o30_swap_01=self._spec.o30_swap_01,
            )
        except (KeyError, ValueError) as e:
            self._node.get_logger().error(f"[{cmd.side}] LinkerZ remap 失败: {e}")
            return
        if len(values) != self._expected_out:
            self._node.get_logger().error(
                f"[{cmd.side}] LinkerZ 路数不对: got {len(values)}, "
                f"expected {self._expected_out}"
            )
            return

        self._sequence = self._sequence + 1 if self._sequence < _UINT64_MAX else 1
        msg = self._HandJointCommand()
        msg.client_id = self._spec.client_id
        msg.user_sequence = self._sequence
        msg.publisher_stamp = self._node.get_clock().now().to_msg()
        msg.representation = self._HandJointCommand.REPRESENTATION_RAW
        msg.values = values
        self._pubs[cmd.side].publish(msg)

    def close(self) -> None:
        self._pubs.clear()
