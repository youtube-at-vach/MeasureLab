MeasureLab Rust prototype for macOS

Choose the DMG matching your Mac: arm64 for Apple Silicon, x86_64 for Intel.
The package deployment target is macOS 13.0. This is a build baseline;
acceptance on every macOS version and device remains in progress.

Open the DMG and drag MeasureLab.app to Applications, then eject the DMG.
If the Python edition is already installed, keep it under a different name
or in a different folder before copying the Rust edition. Both are named
MeasureLab.app. No Python or Rust installation is needed to run this app.

This prototype has an ad-hoc signature with the Hardened Runtime and audio
input entitlement. It is not Developer ID signed or notarized by Apple.
Gatekeeper may block the downloaded app. After verifying its origin and
checksum, use System Settings > Privacy & Security > Open Anyway if offered.
Do not disable Gatekeeper globally. Distribution with Developer ID signing
and notarization remains pending.

When starting real audio input, allow MeasureLab to access the microphone.
macOS also treats external Core Audio inputs as microphone access. If access
was denied, enable MeasureLab under System Settings > Privacy & Security >
Microphone and relaunch the app. Permission is granted by the user; the DMG
and signature do not grant it automatically. A terminal launch can attribute
permission to the terminal, so use the installed app for this check.

The normal desktop build excludes QA-only demos. Start input and output
explicitly. Physical audio/GPU, measurement accuracy, save/restore, device
reconnect and long-duration acceptance remain necessary. Package checks do
not establish measurement accuracy or first-run permission behavior.

Settings and measurement results are saved only when requested. Replacing
or deleting the app does not delete files saved outside its bundle. Avoid
using the same settings file with the Python and Rust editions.

Check the matching SHA256SUMS-macos-<ARCH>.txt before installing the DMG.
The external *-build-info.json records the source commit, compiler, features
and hashes of the final signed app. The embedded build-info.json contains
the same build identity without the final hashes, to avoid a signing cycle.
Checksums establish file identity, not publisher authentication.
The application license is in LICENSE. Python's final release is v0.9.1.
