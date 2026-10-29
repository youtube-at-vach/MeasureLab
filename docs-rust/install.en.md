# Install a binary

The Rust edition is in preparation. The [download selector](https://youtube-at-vach.github.io/MeasureLab/download/?edition=rust&lang=en) offers an explicit Rust choice, but downloads stay disabled until packages are published. The final Python v0.9.1 edition remains available through the Python choice. To try Rust now, [build from source](quickstart.md).

## Planned packages and acceptance limits

The first prototype will be a Prerelease, with GitHub Latest kept on Python v0.9.1. These are build targets, not guarantees for every OS version or device. Acceptance of the distributed executable through launch, physical I/O, stop, save, restart and restore remains incomplete.

| OS / CPU | Format | Build baseline and current verification |
| --- | --- | --- |
| Windows 10/11 x64 | Setup / ZIP | MSVC release. Previous VM startup used GNU/dev-fast and does not establish distributed-package physical I/O or save/restore acceptance |
| Linux x86_64 | AppImage / tar.gz | Ubuntu 22.04 baseline, glibc 2.35+. One AppImage startup and Intel GPU readback condition on Ubuntu 26.04.1/X11; physical I/O, save/restore and Wayland remain unverified |
| macOS Intel x86_64 | DMG | macOS 13.0+ build target. Limited development-build measurement records; Finder launch, first-run permissions and save/restore from a distributed DMG remain unverified |
| macOS Apple Silicon arm64 | DMG | macOS 13.0+ build target; physical DMG acceptance remains unverified |

Windows ARM64, Linux ARM64/musl (including Alpine) and a macOS Universal Binary are outside these package targets. Running a binary requires no Python or Rust development environment. Generator, Lock-in and synchronous comparison integration, comprehensive manual GUI operation and real-monitor DPI changes still require acceptance. See [features and known limitations](index.md).

## Verify a download

After publication, select the version, OS, CPU and format, then obtain the matching platform's `SHA256SUMS-<OS>-<CPU>.txt` and `*-build-info.json` from the same Release. Intel Mac and Windows ZIP filenames differ between Python and Rust. Rust uses:

* Intel Mac: `MeasureLab-v<version>-macos-x86_64.dmg`
* Windows ZIP: `MeasureLab-v<version>-windows-x64.zip`

Compare the downloaded file using `shasum -a 256 <filename>` on macOS, `sha256sum <filename>` on Linux, or `Get-FileHash <filename> -Algorithm SHA256` in Windows PowerShell. Match the version, source SHA and normal desktop configuration in build-info with the Release description. Checksums establish file identity, not publisher authentication.

## Windows

Setup installs for the current user without administrator privileges, separately from the Python edition. For ZIP, extract and run `MeasureLab/measurelab.exe`. The official MSVC package statically links the Visual C++ runtime.

The executable and Setup are not Authenticode signed. Windows may be unable to verify the publisher; check the source and checksum. Allow microphone access for desktop apps in Windows Settings when using real input. An audio device and a wgpu-compatible graphics backend are required.

## macOS

Choose `arm64` for Apple Silicon or `x86_64` for Intel. Open the DMG, copy `MeasureLab.app` to Applications, eject the DMG, then launch from Finder. The Python edition has the same application name; move it to another folder or rename it before installing Rust alongside it.

The app has an ad-hoc signature with Hardened Runtime and the audio-input entitlement, without Developer ID signing or Apple notarization. If Gatekeeper blocks it, verify the source and checksum, then use System Settings → Privacy & Security → Open Anyway if offered. Do not disable Gatekeeper globally.

Allow microphone access for MeasureLab when first starting real input. External Core Audio inputs also require this permission. After denial, enable MeasureLab under Privacy & Security → Microphone, quit and relaunch, then retry. Terminal launches can attribute permissions differently; package acceptance uses the installed app launched from Finder.

## Linux

Make the AppImage executable and launch it, replacing `<version>` with the downloaded version:

```sh
chmod +x MeasureLab-v<version>-linux-x86_64.AppImage
./MeasureLab-v<version>-linux-x86_64.AppImage
```

Without FUSE, add `--appimage-extract-and-run` or extract tar.gz and run `MeasureLab/AppRun`. Both formats contain the same application.

The host supplies glibc, ALSA configuration/plugins, X11/Wayland, xkbcommon and a wgpu-compatible GPU driver. Minimal systems need the corresponding runtime packages. The packages have no publisher signatures.

## Startup, saved data and updates

Input and output start stopped. Without a device, try acquisition, stop and save through [Software Loopback](quickstart.md). If a real device is missing, check OS permissions, connections and supported sample rates/channels. Starting Generator output and starting input are independent actions.

Input/output devices and sample rates, valid measurement conditions and calibration, layout, display preferences and language are saved automatically and restored on launch. Changes are checked about every two seconds and flushed on normal exit. Input and output stay stopped until explicitly started. Unavailable devices keep their saved conditions; another device is never selected as a substitute. Stop and release input/output before changing connections, then use **Refresh devices** to check the saved selection again.

| OS | Automatic preferences path |
| --- | --- |
| Windows | `%LOCALAPPDATA%\MeasureLab\startup-preferences.json` |
| macOS | `~/Library/Application Support/MeasureLab/startup-preferences.json` |
| Linux | `$XDG_CONFIG_HOME/MeasureLab/startup-preferences.json` (unset, empty or relative: `~/.config/MeasureLab/startup-preferences.json`) |

View the path and errors under **File / File paths & status… / STARTUP PREFERENCES**. Damaged or unsupported files are preserved while the app starts with defaults. To reset preferences, close the app, move this file aside, then relaunch. Python's `config.json` and files in the working directory are not imported automatically. Captured data, held results and cursors are excluded. Incomplete input settings retain the last valid measurement conditions; before the first valid selection, only display preferences are saved.

Settings use version 11 (reading versions 1–10); result JSON uses version 7 (reading versions 1–6). Restore settings while stopped; restoration alone never starts input or output. Choose file destinations under File and keep Python files separate. The default Windows settings path is `%APPDATA%\MeasureLab\measurement-settings.json`.

Scope/Spectrum support held JSON/CSV results and view PNGs; Lock-in/comparison support conditional JSON/CSV. Spectrogram/XY, cursors and long-duration recordings of all channels are outside result export. Updating or deleting the application preserves files saved outside its package. Save needed settings/results before updating, then restore them while stopped after relaunch.
