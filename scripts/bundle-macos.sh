#!/bin/sh
set -eu
ras_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ras_root"
if [ "$(uname -s)" != Darwin ]; then
    echo "This script builds a macOS application bundle." >&2
    exit 1
fi
./scripts/cargo.sh build --release --locked
ras_bundle="$ras_root/dist/RAS.app"
mkdir -p "$ras_bundle/Contents/MacOS"
cp target/release/ras "$ras_bundle/Contents/MacOS/ras"
cat > "$ras_bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleName</key><string>RAS</string>
    <key>CFBundleDisplayName</key><string>RAS Audio Measurement Lab</string>
    <key>CFBundleIdentifier</key><string>dev.ras.oscilloscope</string>
    <key>CFBundleExecutable</key><string>ras</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSMicrophoneUsageDescription</key><string>オーディオ入力の波形と周波数スペクトルを表示するために使用します。</string>
</dict></plist>
PLIST
codesign --force --sign - "$ras_bundle"
echo "Built $ras_bundle"
