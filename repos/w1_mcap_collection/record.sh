#!/usr/bin/env bash
# start <task> | stop | cancel | status
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/env.sh"
exec "$MCAP_PYTHON" "$HERE/cli.py" "$@"
