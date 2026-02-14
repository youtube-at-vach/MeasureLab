#!/bin/bash
set -e

# Define variables
APP_NAME="MeasureLab"
APP_DIR="AppDir"
LINUXDEPLOY="linuxdeploy-x86_64.AppImage"
APPIMAGETOOL="appimagetool-x86_64.AppImage"
RUNTIME="runtime-x86_64"

# Clean up previous build
rm -rf $APP_DIR $APP_NAME*.AppImage

# Download linuxdeploy if not present
if [ ! -f "$LINUXDEPLOY" ]; then
    wget https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-x86_64.AppImage -O "$LINUXDEPLOY"
    echo "c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d  $LINUXDEPLOY" | sha256sum -c -
    chmod +x $LINUXDEPLOY
fi

# Download appimagetool if not present (Workaround for CI download failure)
if [ ! -f "$APPIMAGETOOL" ]; then
    wget https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage -O "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
fi

# Download runtime manually (Workaround for CI download failure)
if [ ! -f "$RUNTIME" ]; then
    wget https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64 -O "$RUNTIME"
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

# Initialize AppDir with linuxdeploy (populate resources/libs)
# Use APPIMAGE_EXTRACT_AND_RUN=1 to run linuxdeploy without FUSE (needed for CI/Docker)
# Note: Removed "--output appimage" to avoid using the internal plugin which is failing to download runtime.
APPIMAGE_EXTRACT_AND_RUN=1 ./$LINUXDEPLOY --appdir $APP_DIR \
    --desktop-file $APP_DIR/usr/share/applications/audio-tools.desktop \
    --icon-file $APP_DIR/usr/share/icons/hicolor/256x256/apps/app_icon.png \
    --executable $APP_DIR/usr/bin/MeasureLab

# Build AppImage manually using pre-downloaded tools
echo "Building AppImage using manual appimagetool..."
# ARCH=x86_64 required for appimagetool to select correct runtime if not passed?
# We pass runtime explicitly.
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 ./$APPIMAGETOOL --runtime-file "$RUNTIME" "$APP_DIR" "${APP_NAME}-x86_64.AppImage"

echo "AppImage build complete!"
