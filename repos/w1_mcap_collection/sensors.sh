#!/usr/bin/env bash
# PC1 sensor management, using the same ROS environment as the collector.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/env.sh"
exec "$MCAP_PYTHON" "$HERE/sensors.py" "$@"
