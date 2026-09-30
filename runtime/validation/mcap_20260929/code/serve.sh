#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/env.sh"
exec "$MCAP_PYTHON" "$HERE/recorder.py" serve "$@"
