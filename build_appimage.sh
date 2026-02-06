#!/bin/bash
set -e

# Define variables
APP_NAME="MeasureLab"
APP_DIR="AppDir"
LINUXDEPLOY="linuxdeploy-x86_64.AppImage"

# Clean up previous build
rm -rf $APP_DIR $APP_NAME*.AppImage

# Download linuxdeploy if not present
# TODO: Check for new versions occasionally at https://github.com/linuxdeploy/linuxdeploy/releases
if [ ! -f "$LINUXDEPLOY" ]; then
    wget https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-x86_64.AppImage -O "$LINUXDEPLOY"
    echo "c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d  $LINUXDEPLOY" | sha256sum -c -
    chmod +x $LINUXDEPLOY
fi

# Create AppDir structure
mkdir -p $APP_DIR/usr/bin
mkdir -p $APP_DIR/usr/share/icons/hicolor/256x256/apps
mkdir -p $APP_DIR/usr/share/applications

# Copy application binary
cp dist/MeasureLab $APP_DIR/usr/bin/

# Copy icon and desktop file
cp app_icon.png $APP_DIR/usr/share/icons/hicolor/256x256/apps/app_icon.png
cp audio-tools.desktop $APP_DIR/usr/share/applications/

# Update desktop file Exec path
sed -i 's/Exec=main_gui/Exec=MeasureLab/g' $APP_DIR/usr/share/applications/audio-tools.desktop

# Initialize AppDir with linuxdeploy
# Use APPIMAGE_EXTRACT_AND_RUN=1 to run linuxdeploy without FUSE (needed for CI/Docker)
APPIMAGE_EXTRACT_AND_RUN=1 ./$LINUXDEPLOY --appdir $APP_DIR --output appimage \
    --desktop-file $APP_DIR/usr/share/applications/audio-tools.desktop \
    --icon-file $APP_DIR/usr/share/icons/hicolor/256x256/apps/app_icon.png \
    --executable $APP_DIR/usr/bin/MeasureLab

echo "AppImage build complete!"
