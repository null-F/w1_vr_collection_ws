"""启动手套遥操。其余参数仍在 config/default.yaml。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _launch_setup(context, *_args, **_kwargs):
    arguments = []
    robot = LaunchConfiguration("robot").perform(context).strip()
    if robot:
        arguments.extend(["--robot", robot])
    hand_sdk = LaunchConfiguration("hand_sdk").perform(context).strip()
    if hand_sdk:
        arguments.extend(["--hand-sdk", hand_sdk])
    port = LaunchConfiguration("port").perform(context).strip()
    if port:
        arguments.extend(["--port", port])
    config = LaunchConfiguration("config").perform(context).strip()
    if config:
        arguments.extend(["--config", config])
    force_feedback = LaunchConfiguration("force_feedback").perform(context).strip()
    if force_feedback == "on":
        arguments.append("--force-feedback")
    elif force_feedback == "off":
        arguments.append("--no-force-feedback")
    elif force_feedback != "yaml":
        raise RuntimeError(
            "force_feedback 只能是 yaml、on 或 off，"
            f"收到 {force_feedback!r}"
        )
    return [
        Node(
            package="linkerbot_ffg_ros",
            executable="teleop",
            name="linkerbot_ffg_teleop",
            output="screen",
            arguments=arguments,
        )
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("robot", default_value=""),
            DeclareLaunchArgument("hand_sdk", default_value=""),
            DeclareLaunchArgument("port", default_value=""),
            DeclareLaunchArgument("force_feedback", default_value="yaml"),
            DeclareLaunchArgument("config", default_value=""),
            OpaqueFunction(function=_launch_setup),
        ]
    )
