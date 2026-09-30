#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source /home/dexforce/linkerhand/repos/w1_mcap_collection/env.sh
exec "$MCAP_PYTHON" "$HERE/mcap_rpc.py" "$@"
