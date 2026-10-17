#!/bin/sh
set -eu
measurelab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$measurelab_root"
if [ "$(uname -s)" != Darwin ]; then
    echo "This script builds a macOS application bundle." >&2
    exit 1
fi
if [ -x "$measurelab_root/.venv/bin/python" ]; then
    exec "$measurelab_root/.venv/bin/python" scripts/macos_package.py bundle "$@"
fi
exec python3 scripts/macos_package.py bundle "$@"
