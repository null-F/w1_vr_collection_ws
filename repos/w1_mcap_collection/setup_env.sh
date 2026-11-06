#!/usr/bin/env bash
# Run as dexforce on PC1, with the collector stopped. No service operations here.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VENV=${W1_MCAP_VENV:-/home/dexforce/linkerhand/runtime/venvs/mcap-collection}
export PYTHONDONTWRITEBYTECODE=1

if [[ -e "$VENV" ]]; then
    if [[ ! -f "$VENV/pyvenv.cfg" || ! -x "$VENV/bin/python" ]]; then
        echo "Incomplete collector environment: $VENV; inspect it before retrying." >&2
        exit 1
    fi
else
    /usr/bin/python3 -m venv --system-site-packages "$VENV"
fi

"$VENV/bin/python" - "$VENV" <<'PY'
import pathlib
import sys

target = pathlib.Path(sys.argv[1]).resolve()
config = dict(line.split('=', 1) for line in (target / 'pyvenv.cfg').read_text().splitlines() if '=' in line)
config = {key.strip(): value.strip().lower() for key, value in config.items()}
if pathlib.Path(sys.prefix).resolve() != target or sys.prefix == sys.base_prefix:
    raise SystemExit('Refusing pip outside the requested virtual environment')
if sys.version_info[:2] != (3, 10) or config.get('include-system-site-packages') != 'true':
    raise SystemExit('PC1 requires Python 3.10 and a venv created with --system-site-packages')
PY

# Optional pip arguments support a prepared offline wheel directory.
"$VENV/bin/python" -m pip install --disable-pip-version-check -r "$HERE/requirements.txt" "$@"
bash "$HERE/check_env.sh"
