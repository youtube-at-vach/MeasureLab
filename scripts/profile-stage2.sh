#!/bin/bash
# Capture reproducible UI logs and one-second process RSS samples. Build the
# qa binary first; environment variables select the duration, input and FFT.
set -eu

measurelab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$measurelab_root"

if [ "$#" -lt 1 ]; then
    echo 'Usage: ./scripts/profile-stage2.sh NAME [application options]' >&2
    exit 2
fi
measurelab_name=$1
shift
case "$measurelab_name" in
    *[!a-zA-Z0-9_-]*|'') echo 'NAME must contain only letters, numbers, _ or -' >&2; exit 2 ;;
esac
: "${MEASURELAB_PROFILE_SECONDS:=600}"
export MEASURELAB_PROFILE_SECONDS
measurelab_output="dist/stage2-qa/$measurelab_name"
mkdir -p dist/stage2-qa
measurelab_binary=${MEASURELAB_QA_BINARY:-target/release/measurelab}
"$measurelab_binary" "$@" > "$measurelab_output.log" 2>&1 &
measurelab_pid=$!
measurelab_awake_pid=
if [ "${MEASURELAB_PROFILE_KEEP_AWAKE:-0}" = 1 ] && command -v caffeinate >/dev/null 2>&1; then
    caffeinate -di -w "$measurelab_pid" &
    measurelab_awake_pid=$!
fi
trap 'kill "$measurelab_pid" ${measurelab_awake_pid:+"$measurelab_awake_pid"} 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'elapsed_seconds,rss_kib,cpu_percent,cpu_time\n' > "$measurelab_output-rss.csv"
measurelab_started=$SECONDS
while kill -0 "$measurelab_pid" 2>/dev/null; do
    measurelab_sample=$(ps -o rss= -o %cpu= -o time= -p "$measurelab_pid" || true)
    if [ -n "$measurelab_sample" ]; then
        read -r measurelab_rss measurelab_cpu measurelab_cpu_time <<< "$measurelab_sample"
        printf '%s,%s,%s,%s\n' "$((SECONDS - measurelab_started))" "$measurelab_rss" "$measurelab_cpu" "$measurelab_cpu_time" >> "$measurelab_output-rss.csv"
    fi
    sleep 1
done
measurelab_status=0
wait "$measurelab_pid" || measurelab_status=$?
if [ -n "$measurelab_awake_pid" ]; then
    kill "$measurelab_awake_pid" 2>/dev/null || true
fi
trap - EXIT
cat "$measurelab_output.log"
echo "RSS samples: $measurelab_output-rss.csv"
exit "$measurelab_status"
