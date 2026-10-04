#!/bin/sh
set -u

measurelab_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if "$measurelab_root/scripts/debug.sh" "$@"; then
    exit 0
else
    measurelab_status=$?
fi

printf '\nMeasureLab exited with status %s. See the output above.\n' "$measurelab_status" >&2
if [ -t 0 ]; then
    printf 'Press Enter to close this window: ' >&2
    read -r measurelab_reply || :
fi
exit "$measurelab_status"
