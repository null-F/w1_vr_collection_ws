#!/usr/bin/env bash
# 给克隆仓库的人用。装好后的正式入口是 ros2 run / ros2 launch。
set -eo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Jazzy 的 setup.bash 会读取未定义的 AMENT_TRACE_SETUP_FILES，不能开 nounset。
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source "$ROOT/install/setup.bash"
set -u
exec ros2 run linkerbot_ffg_ros teleop "$@"
