#!/bin/sh
set -eu
measurelab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$measurelab_root"
if [ "$(uname -s)" != Darwin ]; then
    echo "This script builds a macOS application bundle." >&2
    exit 1
fi
./scripts/cargo.sh build --release --locked
measurelab_bundle="$measurelab_root/dist/MeasureLab.app"
mkdir -p "$measurelab_bundle/Contents/MacOS"
cp target/release/measurelab "$measurelab_bundle/Contents/MacOS/measurelab"
cat > "$measurelab_bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleName</key><string>MeasureLab</string>
    <key>CFBundleDisplayName</key><string>MeasureLab</string>
    <key>CFBundleIdentifier</key><string>dev.measurelab.app</string>
    <key>CFBundleExecutable</key><string>measurelab</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSMicrophoneUsageDescription</key><string>オーディオ入力の波形と周波数スペクトルを表示するために使用します。</string>
</dict></plist>
PLIST
codesign --force --sign - "$measurelab_bundle"
echo "Built $measurelab_bundle"
