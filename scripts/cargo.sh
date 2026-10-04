#!/bin/sh
set -eu
ras_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if command -v cargo >/dev/null 2>&1; then
    exec cargo "$@"
fi
if [ -x "$ras_root/.tools/cargo/bin/cargo" ]; then
    export CARGO_HOME="$ras_root/.tools/cargo"
    export RUSTUP_HOME="$ras_root/.tools/rustup"
    export PATH="$ras_root/.tools/cargo/bin:$PATH"
    exec "$ras_root/.tools/cargo/bin/cargo" "$@"
fi
echo "Rust is required. Install from https://rustup.rs/" >&2
exit 1
