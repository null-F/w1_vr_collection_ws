#!/usr/bin/env bash
# start <task> | stop | cancel | status
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1090
set +u
source /home/dexforce/.dex_env.sh
set -u
PID_FILE=/home/dexforce/linkerhand/runtime/mcap_recorder.pid
mkdir -p /home/dexforce/linkerhand/runtime/logs

ensure_serve() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        return 0
    fi
    nohup "$HERE/serve.sh" > /home/dexforce/linkerhand/runtime/logs/mcap_recorder.log 2>&1 &
    echo $! > "$PID_FILE"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if ros2 service list 2>/dev/null | grep -q '/w1_mcap_recorder/start_recording'; then
            return 0
        fi
        sleep 0.5
    done
    echo "recorder node did not come up; see runtime/logs/mcap_recorder.log" >&2
    exit 1
}

cmd=${1:-}
case "$cmd" in
    start)
        task=${2:-}
        if [[ -z "$task" ]]; then
            echo "Usage: $0 start <task_name>" >&2
            exit 2
        fi
        ensure_serve
        ros2 param set /w1_mcap_recorder task_name "$task" >/dev/null
        ros2 service call /w1_mcap_recorder/start_recording std_srvs/srv/Trigger {}
        ;;
    stop)
        ensure_serve
        ros2 service call /w1_mcap_recorder/stop_recording std_srvs/srv/Trigger {}
        ;;
    cancel)
        ensure_serve
        ros2 service call /w1_mcap_recorder/cancel_recording std_srvs/srv/Trigger {}
        ;;
    status)
        ensure_serve
        ros2 service call /w1_mcap_recorder/status std_srvs/srv/Trigger {}
        ;;
    *)
        echo "Usage: $0 start <task_name> | stop | cancel | status" >&2
        exit 2
        ;;
esac
