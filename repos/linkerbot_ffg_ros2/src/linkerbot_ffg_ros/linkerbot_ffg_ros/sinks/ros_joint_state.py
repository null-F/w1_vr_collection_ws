"""负责把 SDK 内部生成的机械手指令发JointCommand转换成ROS2 的sensor_msgs/JointState然后发布到/cb_left_hand_control_cmd
/cb_right_hand_control_cmd"""


from __future__ import annotations

from typing import Dict, Optional

from ..teleop.types import HandSide, JointCommand

TOPIC_BY_SIDE = {
    "left": "/cb_left_hand_control_cmd",
    "right": "/cb_right_hand_control_cmd",
}


class RosHandControlSink:
    """ROS2 JointState 输出。position 为电机指令， 0~255。"""

    def __init__(self, node, *, qos_depth: int = 10) -> None:
        # 导入 rclpy。
        from rclpy.node import Node
        from rclpy.qos import QoSProfile
        from sensor_msgs.msg import JointState

        if not isinstance(node, Node):
            raise TypeError("node must be an rclpy.node.Node")

        self._node = node
        self._JointState = JointState
        qos = QoSProfile(depth=qos_depth)
        self._pubs: Dict[str, object] = {}
        for side, topic in TOPIC_BY_SIDE.items():
            self._pubs[side] = node.create_publisher(JointState, topic, qos)
            node.get_logger().info(f"HandControlSink publish → {topic}")

    def topic_for(self, side: HandSide) -> str:
        return TOPIC_BY_SIDE[side]

    def publish(self, cmd: JointCommand) -> None:
        if cmd.side not in self._pubs:
            raise ValueError(f"unsupported side: {cmd.side}")
        msg = self._JointState()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        # position：电机指令，约 0~255。
        if cmd.joint_names:
            msg.name = list(cmd.joint_names)
        else:
            msg.name = [f"joint{i + 1}" for i in range(len(cmd.positions))]
        msg.position = [float(x) for x in cmd.positions]
        self._pubs[cmd.side].publish(msg)

    def close(self) -> None:
        self._pubs.clear()
