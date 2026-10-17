MeasureLab Rust prototype for Linux x86_64

AppImage:
  chmod +x MeasureLab-*.AppImage
  ./MeasureLab-v<VERSION>-linux-x86_64.AppImage

If FUSE mounting is unavailable, use the same AppImage with:
  ./MeasureLab-v<VERSION>-linux-x86_64.AppImage --appimage-extract-and-run

Alternatively, extract the tar.gz archive and run MeasureLab/AppRun.
The AppImage and tar.gz contain the same application and launcher.
No Python or Rust installation is needed to run them.

Official packages are built on Ubuntu 22.04 for glibc Linux x86_64.
This is a build baseline, not a guarantee for every Linux distribution.
musl/Alpine and ARM64 are not distribution targets of this package.

Runtime requirements:
  - glibc 2.35 or newer and libgcc_s.so.1
  - ALSA libasound.so.2 and the host's ALSA configuration/plugins
  - X11 or Wayland, with libxkbcommon and the matching client libraries
  - A working Vulkan or EGL/OpenGL driver supported by wgpu

On Ubuntu Desktop these are normally supplied by the system. On minimal
systems, install the corresponding runtime packages, not development tools.
ALSA, display libraries and GPU drivers are deliberately loaded from the
host. Bundling a different libasound or GPU driver can break device plugins
or rendering. No LD_LIBRARY_PATH override is applied by the launcher.

Start input/output explicitly in the application. The Linux audio/GPU,
measurement accuracy, device reconnect and long-duration acceptance tests
remain necessary. CI checks do not establish physical measurement accuracy.

Settings and measurement results are stored only when requested. Replacing
or deleting this package does not delete files saved outside its directory.
Avoid running the Python and Rust editions against the same settings file.

Check SHA256SUMS-linux-x86_64.txt before running downloaded files.
build-info.json records the source commit, compiler, features and payload
hashes. Checksums establish file identity, not publisher authentication.
The application license is in LICENSE. Python's final release is v0.9.1.
