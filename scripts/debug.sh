#!/bin/bash
set -e

measurelab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$measurelab_root"

measurelab_demo=true
measurelab_release=false
measurelab_qa=false
measurelab_app_args=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --audio) measurelab_demo=false ;;
        --release) measurelab_release=true ;;
        --help|-h)
            cat <<'HELP'
Usage: ./scripts/debug.sh [launcher options] [application options]

Build and start MeasureLab with an internal demo signal by default.
The debug build keeps symbols and enables Rust panic backtraces.

Launcher options:
  --audio     Select audio input; press Start input in the application
  --release   Use the optimized release build for performance checks
  --help, -h  Show this help without building
  --          Pass all remaining arguments directly to the application

Application options include:
  --compact      Start in a smaller window with stacked plots
  --low-latency  Disable VSync
  --ui-smoke     Capture the test UI and exit (automatically enables qa)
  --gpu-smoke    Validate GPU plots with offscreen readback and exit
  --list-devices List audio input devices and exit
  --audio-smoke  Capture the default audio input for two seconds and exit

Examples:
  ./scripts/debug.sh
  ./scripts/debug.sh --audio
  ./scripts/debug.sh --compact
  ./scripts/debug.sh --release --compact
  ./scripts/debug.sh --ui-smoke
HELP
            exit 0
            ;;
        --)
            shift
            measurelab_app_args+=("$@")
            break
            ;;
        *) measurelab_app_args+=("$1") ;;
    esac
    shift
done

for measurelab_arg in "${measurelab_app_args[@]}"; do
    if [ "$measurelab_arg" = --ui-smoke ]; then
        measurelab_qa=true
    fi
done

measurelab_cargo_args=(run --locked)
if [ "$measurelab_release" = true ]; then
    measurelab_cargo_args+=(--release)
fi
if [ "$measurelab_qa" = true ]; then
    measurelab_cargo_args+=(--features qa)
fi
measurelab_cargo_args+=(--)
if [ "$measurelab_demo" = true ]; then
    measurelab_cargo_args+=(--demo)
fi

export RUST_BACKTRACE="${RUST_BACKTRACE:-1}"
exec ./scripts/cargo.sh "${measurelab_cargo_args[@]}" "${measurelab_app_args[@]}"
