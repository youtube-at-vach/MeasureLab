MeasureLab - Rust edition for Windows x64

Run measurelab.exe, or install with the accompanying setup executable.
Python and a Rust development environment are not required to run the app.
The official MSVC package statically links the Visual C++ runtime.
Windows 10/11 x64 and a working wgpu graphics backend are required.

The installer operates for the current user without administrator privileges.
It installs separately from the final Python edition of MeasureLab.
Input and Generator output start stopped. Start them explicitly in the app.
For real input, allow microphone access for desktop apps in Windows Settings.

Settings: %APPDATA%\MeasureLab\measurement-settings.json
Saved measurements and settings are preserved on update and uninstall.
The ZIP uses the same per-user settings location as the installed app.

This Rust prototype still requires Windows audio and measurement acceptance.
A successful build or installer test does not verify physical I/O accuracy.
The executable and installer are not Authenticode signed; SHA-256 checksums
identify the downloaded files but do not provide Windows publisher trust.

Manual: https://youtube-at-vach.github.io/MeasureLab/rust/
Source and known issues: https://github.com/youtube-at-vach/MeasureLab
License: The Unlicense (see LICENSE).
Build version, target and source revision: build-info.json
