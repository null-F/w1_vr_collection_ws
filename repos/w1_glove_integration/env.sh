#!/usr/bin/env bash
LINKER_W1_ROOT=/home/dexforce/linkerhand
set +u
source /opt/ros/humble/setup.bash
source /home/dexforce/w1/install/setup.bash
source "${W1_GLOVE_VENV:-$LINKER_W1_ROOT/runtime/venvs/glove-humble}/bin/activate"
set -u
export ROS_DOMAIN_ID=20
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_LOCALHOST_ONLY=0
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.20.20</NetworkInterfaceAddress><AllowMulticast>spdp</AllowMulticast></General></Domain></CycloneDDS>'
export PYTHONDONTWRITEBYTECODE=1
export ROS_LOG_DIR="$LINKER_W1_ROOT/runtime/logs/ros"
# Keep the old SDK available only by explicit selection; never auto-fallback.
W1_GLOVE_SDK="${W1_GLOVE_SDK:-ffg}"
case "$W1_GLOVE_SDK" in
    ffg) sdk_python="$LINKER_W1_ROOT/repos/linkerbot_ffg_ros2/src/linkerbot_ffg_ros" ;;
    legacy) sdk_python="$LINKER_W1_ROOT/repos/linkerhand_ros_teleop/src/linkerhand_retarget" ;;
    *) echo "Unknown W1_GLOVE_SDK: $W1_GLOVE_SDK (expected ffg or legacy)" >&2; return 2 ;;
esac
export W1_GLOVE_SDK
export PYTHONPATH="$sdk_python:${PYTHONPATH:-}"
mkdir -p "$ROS_LOG_DIR"
