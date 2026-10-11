#!/bin/sh
set -eu
measurelab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if command -v cargo >/dev/null 2>&1; then
    exec cargo "$@"
fi
if [ -x "$measurelab_root/.tools/cargo/bin/cargo" ]; then
    export CARGO_HOME="$measurelab_root/.tools/cargo"
    export RUSTUP_HOME="$measurelab_root/.tools/rustup"
    export PATH="$measurelab_root/.tools/cargo/bin:$PATH"
    exec "$measurelab_root/.tools/cargo/bin/cargo" "$@"
fi
echo "Rust is required. Install from https://rustup.rs/" >&2
exit 1
