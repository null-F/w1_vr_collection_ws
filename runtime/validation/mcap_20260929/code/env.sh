#!/usr/bin/env bash
set +u
source /home/dexforce/.dex_env.sh
set -u
MCAP_PREFIX=/home/dexforce/linkerhand/runtime/mcap_prefix/opt/ros/humble
export AMENT_PREFIX_PATH="$MCAP_PREFIX${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}"
export LD_LIBRARY_PATH="$MCAP_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROS_DOMAIN_ID="${W1_MCAP_DOMAIN_ID:-20}"
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.20.20</NetworkInterfaceAddress><AllowMulticast>spdp</AllowMulticast></General></Domain></CycloneDDS>'
export PYTHONDONTWRITEBYTECODE=1
export ROS_LOG_DIR="${W1_MCAP_RUNTIME:-/home/dexforce/linkerhand/runtime}/logs/ros"
MCAP_PYTHON="${W1_MCAP_VENV:-/home/dexforce/linkerhand/runtime/venvs/mcap-collection}/bin/python"
test -x "$MCAP_PYTHON" || { echo "Missing collector environment: $MCAP_PYTHON" >&2; return 1; }
mkdir -p "$ROS_LOG_DIR"
