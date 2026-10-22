#!/usr/bin/env bash
set -Eeuo pipefail

measurelab_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$measurelab_root"

measurelab_verify=false
measurelab_install_os_deps=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --verify) measurelab_verify=true ;;
        --install-os-deps) measurelab_install_os_deps=true ;;
        --help|-h)
            cat <<'HELP'
Usage: ./scripts/setup_dev_env.sh [--install-os-deps] [--verify]

Set up Rust, Node.js, documentation Python, and lint tools locally in
.tools/ and .venv/, then build the desktop application. Reruns reuse these
directories. Shell profiles, Git identity, and OS defaults are not changed.

  --install-os-deps  Check Xcode tools on macOS; install native libraries
                     with apt-get on Linux (may prompt for sudo)
  --verify           Run Rust fmt/Clippy/tests/release build, website tests
                     and build, MkDocs, Ruff, Markdown lint, and actionlint
  --help, -h         Show this help without installing anything

Prerequisites: Git, curl, tar, SHA-256 tools, and OS compiler tools.
macOS: install Xcode Command Line Tools with xcode-select --install.
Linux: see guide/rust/SETUP.md for native build/runtime libraries.

After setup: source .tools/env.sh
Start MeasureLab: ./scripts/debug.sh
Start the internal QA demo: ./scripts/debug.sh --demo
HELP
            exit 0
            ;;
        *) printf 'Unknown option: %s\nUse --help for usage.\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

trap 'printf "Setup failed at line %s; resolve the error above and rerun.\n" "$LINENO" >&2' ERR

measurelab_tools="$measurelab_root/.tools"
measurelab_os=$(uname -s)
measurelab_arch=$(uname -m)
measurelab_rust_version=1.99.0
measurelab_node_version=24.21.0
measurelab_uv_version=0.12.23
measurelab_python_version=3.13
measurelab_markdownlint_version=0.23.3
measurelab_actionlint_version=1.7.12

case "$measurelab_os/$measurelab_arch" in
    Darwin/x86_64) measurelab_node_platform=darwin-x64; measurelab_uv_target=x86_64-apple-darwin; measurelab_actionlint_platform=darwin_amd64 ;;
    Darwin/arm64) measurelab_node_platform=darwin-arm64; measurelab_uv_target=aarch64-apple-darwin; measurelab_actionlint_platform=darwin_arm64 ;;
    Linux/x86_64) measurelab_node_platform=linux-x64; measurelab_uv_target=x86_64-unknown-linux-gnu; measurelab_actionlint_platform=linux_amd64 ;;
    Linux/aarch64|Linux/arm64) measurelab_node_platform=linux-arm64; measurelab_uv_target=aarch64-unknown-linux-gnu; measurelab_actionlint_platform=linux_arm64 ;;
    *) printf 'Unsupported platform: %s/%s. See guide/rust/SETUP.md.\n' "$measurelab_os" "$measurelab_arch" >&2; exit 1 ;;
esac

for measurelab_command in git curl tar awk; do
    if ! command -v "$measurelab_command" >/dev/null 2>&1; then
        printf 'Required command is missing: %s\n' "$measurelab_command" >&2
        exit 1
    fi
done
if command -v shasum >/dev/null 2>&1; then
    measurelab_sha256=(shasum -a 256)
elif command -v sha256sum >/dev/null 2>&1; then
    measurelab_sha256=(sha256sum)
else
    printf 'Install shasum or sha256sum before running setup.\n' >&2
    exit 1
fi
if [ "$measurelab_os" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then
    printf 'Run xcode-select --install, complete installation, then rerun setup.\n' >&2
    exit 1
fi

measurelab_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

if [ "$measurelab_install_os_deps" = true ]; then
    if [ "$measurelab_os" = Darwin ]; then
        printf 'macOS uses the installed Xcode Command Line Tools.\n'
    elif command -v apt-get >/dev/null 2>&1; then
        measurelab_as_root apt-get update
        measurelab_as_root apt-get install -y build-essential pkg-config \
            libasound2-dev libxkbcommon-dev libwayland-dev libx11-dev \
            libxrandr-dev libxi-dev libxcursor-dev
    else
        printf 'Install native libraries for your distribution manually; see guide/rust/SETUP.md.\n' >&2
        exit 1
    fi
fi

mkdir -p "$measurelab_tools/bin" "$measurelab_tools/downloads"
export CARGO_HOME="$measurelab_tools/cargo"
export RUSTUP_HOME="$measurelab_tools/rustup"
export UV_PYTHON_INSTALL_DIR="$measurelab_tools/python"
export UV_PYTHON_BIN_DIR="$measurelab_tools/bin"
export UV_CACHE_DIR="$measurelab_tools/uv-cache"
export PATH="$measurelab_tools/bin:$measurelab_tools/node/bin:$CARGO_HOME/bin:$PATH"

measurelab_download() {
    curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
        --retry 3 "$1" -o "$2.part"
    mv "$2.part" "$2"
}

measurelab_check_archive() {
    local measurelab_archive=$1 measurelab_manifest=$2
    awk -v name="$measurelab_archive" '
        $2 == name || $2 == "*" name { print $1 "  " name; found = 1 }
        END { if (!found) exit 1 }
    ' "$measurelab_tools/downloads/$measurelab_manifest" > "$measurelab_tools/downloads/check.sha256"
    (cd "$measurelab_tools/downloads" && "${measurelab_sha256[@]}" -c check.sha256)
}

printf 'Setting up Rust %s in .tools/\n' "$measurelab_rust_version"
if [ ! -x "$CARGO_HOME/bin/rustup" ]; then
    measurelab_download https://sh.rustup.rs "$measurelab_tools/downloads/rustup-init.sh"
    sh "$measurelab_tools/downloads/rustup-init.sh" -y --no-modify-path \
        --profile minimal --default-toolchain "$measurelab_rust_version" \
        --component rustfmt --component clippy
else
    "$CARGO_HOME/bin/rustup" toolchain install "$measurelab_rust_version" \
        --profile minimal --component rustfmt --component clippy
    "$CARGO_HOME/bin/rustup" default "$measurelab_rust_version"
fi

printf 'Setting up Node.js %s in .tools/\n' "$measurelab_node_version"
if [ ! -x "$measurelab_tools/node/bin/node" ] || \
    [ "$("$measurelab_tools/node/bin/node" --version)" != "v$measurelab_node_version" ]; then
    if [ -e "$measurelab_tools/node" ] && [ ! -L "$measurelab_tools/node" ]; then
        printf '.tools/node exists and is not a symlink; move it aside before setup.\n' >&2
        exit 1
    fi
    measurelab_node_archive="node-v$measurelab_node_version-$measurelab_node_platform.tar.gz"
    measurelab_download "https://nodejs.org/dist/v$measurelab_node_version/$measurelab_node_archive" "$measurelab_tools/downloads/$measurelab_node_archive"
    measurelab_download "https://nodejs.org/dist/v$measurelab_node_version/SHASUMS256.txt" "$measurelab_tools/downloads/node-SHASUMS256.txt"
    measurelab_check_archive "$measurelab_node_archive" node-SHASUMS256.txt
    tar -xzf "$measurelab_tools/downloads/$measurelab_node_archive" -C "$measurelab_tools"
    ln -sfn "node-v$measurelab_node_version-$measurelab_node_platform" "$measurelab_tools/node"
fi

printf 'Setting up uv %s and documentation Python %s\n' "$measurelab_uv_version" "$measurelab_python_version"
if [ ! -x "$measurelab_tools/bin/uv" ] || \
    [[ "$("$measurelab_tools/bin/uv" --version)" != "uv $measurelab_uv_version "* ]]; then
    measurelab_uv_archive="uv-$measurelab_uv_target.tar.gz"
    measurelab_download "https://github.com/astral-sh/uv/releases/download/$measurelab_uv_version/$measurelab_uv_archive" "$measurelab_tools/downloads/$measurelab_uv_archive"
    measurelab_download "https://github.com/astral-sh/uv/releases/download/$measurelab_uv_version/$measurelab_uv_archive.sha256" "$measurelab_tools/downloads/uv.sha256"
    # uv publishes a single-archive checksum; normalize it to a manifest.
    printf '%s  %s\n' "$(awk 'NR == 1 { print $1 }' "$measurelab_tools/downloads/uv.sha256")" "$measurelab_uv_archive" > "$measurelab_tools/downloads/uv-SHASUMS256.txt"
    measurelab_check_archive "$measurelab_uv_archive" uv-SHASUMS256.txt
    mkdir -p "$measurelab_tools/uv-$measurelab_uv_version"
    tar -xzf "$measurelab_tools/downloads/$measurelab_uv_archive" -C "$measurelab_tools/uv-$measurelab_uv_version"
    ln -sfn "../uv-$measurelab_uv_version/uv-$measurelab_uv_target/uv" "$measurelab_tools/bin/uv"
    ln -sfn "../uv-$measurelab_uv_version/uv-$measurelab_uv_target/uvx" "$measurelab_tools/bin/uvx"
fi
uv python install "$measurelab_python_version"
if [ -e .venv ]; then
    if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c \
        'import sys; assert sys.prefix != sys.base_prefix and sys.version_info >= (3, 12)' ; then
        printf 'Existing .venv is unusable or older than Python 3.12. Move it aside, then rerun.\n' >&2
        exit 1
    fi
    .venv/bin/python -m ensurepip --upgrade
else
    uv venv --seed --python "$measurelab_python_version" .venv
fi
.venv/bin/python -m pip install -r requirements-docs.txt ruff
.venv/bin/python -m pip check

printf 'Installing website dependencies and Markdown lint\n'
npm --prefix download-site ci
npm --prefix "$measurelab_tools/lint" install --save-dev --save-exact "markdownlint-cli2@$measurelab_markdownlint_version"
ln -sfn ../lint/node_modules/.bin/markdownlint-cli2 "$measurelab_tools/bin/markdownlint-cli2"

printf 'Setting up actionlint %s\n' "$measurelab_actionlint_version"
if [ ! -x "$measurelab_tools/bin/actionlint" ] || \
    [ "$("$measurelab_tools/bin/actionlint" -version | head -n 1)" != "$measurelab_actionlint_version" ]; then
    measurelab_actionlint_archive="actionlint_${measurelab_actionlint_version}_${measurelab_actionlint_platform}.tar.gz"
    measurelab_download "https://github.com/rhysd/actionlint/releases/download/v$measurelab_actionlint_version/$measurelab_actionlint_archive" "$measurelab_tools/downloads/$measurelab_actionlint_archive"
    measurelab_download "https://github.com/rhysd/actionlint/releases/download/v$measurelab_actionlint_version/actionlint_${measurelab_actionlint_version}_checksums.txt" "$measurelab_tools/downloads/actionlint-checksums.txt"
    measurelab_check_archive "$measurelab_actionlint_archive" actionlint-checksums.txt
    mkdir -p "$measurelab_tools/actionlint-$measurelab_actionlint_version"
    tar -xzf "$measurelab_tools/downloads/$measurelab_actionlint_archive" -C "$measurelab_tools/actionlint-$measurelab_actionlint_version"
    ln -sfn "../actionlint-$measurelab_actionlint_version/actionlint" "$measurelab_tools/bin/actionlint"
fi

# Bash %q also produces sourceable path quoting for zsh, including spaces.
# Keep variables literal until env.sh is sourced by the user's shell.
# shellcheck disable=SC2016
{
    printf '# Generated by scripts/setup_dev_env.sh; source from bash or zsh.\n'
    printf 'export CARGO_HOME=%q\n' "$CARGO_HOME"
    printf 'export RUSTUP_HOME=%q\n' "$RUSTUP_HOME"
    printf 'export UV_PYTHON_INSTALL_DIR=%q\n' "$UV_PYTHON_INSTALL_DIR"
    printf 'export UV_PYTHON_BIN_DIR=%q\n' "$UV_PYTHON_BIN_DIR"
    printf 'export UV_CACHE_DIR=%q\n' "$UV_CACHE_DIR"
    printf 'export PATH=%q:"$PATH"\n' "$measurelab_root/.venv/bin:$measurelab_tools/bin:$measurelab_tools/node/bin:$CARGO_HOME/bin"
} > "$measurelab_tools/env.sh"
# shellcheck source=/dev/null
source "$measurelab_tools/env.sh"

if [ "$measurelab_verify" = true ]; then
    printf 'Verifying Rust, website, documentation, and lint tools\n'
    ./scripts/cargo.sh fmt --all -- --check
    ./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
    ./scripts/cargo.sh test --locked --no-default-features
    ./scripts/cargo.sh test --locked
    ./scripts/cargo.sh test --locked --all-targets --all-features
    ./scripts/cargo.sh test --locked --doc --all-features
    ./scripts/cargo.sh build --release --locked
    npm --prefix download-site test
    ./.venv/bin/ruff check .
    ./.venv/bin/ruff format --check .
    ./.venv/bin/python -m unittest discover -s scripts -p 'test_ci_changes.py'
    ./.venv/bin/python -m unittest discover -s scripts -p 'test_i18n.py'
    ./.venv/bin/python scripts/i18n.py check
    markdownlint-cli2 '**/*.md' '#node_modules'
    actionlint
    ./.venv/bin/python scripts/build_pages.py
else
    printf 'Building the desktop application\n'
    ./scripts/cargo.sh build --profile dev-fast --locked
fi

if ! .venv/bin/python -c 'import mkdocs, material, mkdocs_static_i18n; from py_mini_racer import MiniRacer' > "$measurelab_tools/doc-runtime.log" 2>&1; then
    printf '\nDocumentation Python packages are missing; MkDocs is not ready.\n' >&2
    printf 'Reinstall requirements-docs.txt or follow guide/rust/SETUP.md.\n' >&2
    printf 'Details: .tools/doc-runtime.log\n' >&2
    exit 1
fi

printf '\nDevelopment environment setup completed.\n'
printf 'Activate tools: source .tools/env.sh\n'
printf 'Start MeasureLab: ./scripts/debug.sh\n'
printf 'Internal QA demo: ./scripts/debug.sh --demo\n'
printf 'Full checks: ./scripts/setup_dev_env.sh --verify\n'
