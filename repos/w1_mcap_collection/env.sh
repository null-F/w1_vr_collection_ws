#!/usr/bin/env bash
# VR already initializes the vendor ROS environment at service startup. Reuse
# that inherited environment; standalone or incomplete environments still load it.
if [[ "${ROS_DISTRO:-}" != humble ||
      "${RMW_IMPLEMENTATION:-}" != rmw_cyclonedds_cpp ||
      ":${COLCON_PREFIX_PATH:-}:" != *":/home/dexforce/w1/install:"* ||
      ":${AMENT_PREFIX_PATH:-}:" != *":/opt/ros/humble:"* ||
      ":${AMENT_PREFIX_PATH:-}:" != *":/home/dexforce/w1/install/"* ||
      -z "${PYTHONPATH:-}" || -z "${LD_LIBRARY_PATH:-}" ]]; then
    set +u
    source /home/dexforce/.dex_env.sh
    set -u
fi
MCAP_PREFIX=/home/dexforce/linkerhand/runtime/mcap_prefix/opt/ros/humble
export AMENT_PREFIX_PATH="$MCAP_PREFIX${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}"
export LD_LIBRARY_PATH="$MCAP_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROS_DOMAIN_ID="${W1_MCAP_DOMAIN_ID:-20}"
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.20.20</NetworkInterfaceAddress><AllowMulticast>spdp</AllowMulticast></General></Domain></CycloneDDS>'
export PYTHONDONTWRITEBYTECODE=1
export ROS_LOG_DIR="${W1_MCAP_RUNTIME:-/home/dexforce/linkerhand/runtime}/logs/ros"
MCAP_PYTHON="${W1_MCAP_VENV:-/home/dexforce/linkerhand/runtime/venvs/mcap-collection}/bin/python"
test -x "$MCAP_PYTHON" || { echo "Missing collector environment: $MCAP_PYTHON" >&2; return 1; }
# Environment checks must not create runtime files or start the recorder.
if [[ "${1:-}" != "--check-only" ]]; then
    mkdir -p "$ROS_LOG_DIR"
fi
