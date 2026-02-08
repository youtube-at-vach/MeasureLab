ASIO Support for MeasureLab
===========================

MeasureLab uses the PortAudio library, which includes optional ASIO support.
However, **ASIO is disabled by default**.

This is **not a licensing restriction**, but a **stability and reliability decision**.
In practice, ASIO driver behavior varies widely, and when used through PortAudio,
it may cause crashes, hangs, or incorrect device reporting.

For this reason, ASIO support is considered **experimental** and must be enabled manually.

> **Note:**
> Enabling ASIO does **not** install or redistribute any ASIO drivers or the ASIO SDK.
> An ASIO driver must already be installed on your system.

Enabling ASIO
-------------
To enable ASIO support, switch the active PortAudio library to the ASIO-enabled version
using the provided script.

1. Close MeasureLab if it is running.
2. Open the MeasureLab folder (where `MeasureLab.exe` is located).
3. Double-click `enable_asio.bat`.
4. The script will back up the current PortAudio library and replace it with the ASIO-enabled version.
5. Restart MeasureLab. ASIO devices should now appear in the device list.

Disabling ASIO
--------------
If you experience problems or want to revert to the default configuration:

1. Close MeasureLab.
2. Double-click `disable_asio.bat`.
3. The original PortAudio library will be restored.
4. Restart MeasureLab.

Manual Method
-------------
If the scripts do not work, you can switch the libraries manually:

1. Navigate to `_internal/_sounddevice_data/portaudio-binaries/`.
2. Rename `libportaudio64bit.dll` to `libportaudio64bit.dll.bak`.
3. Copy `libportaudio64bit-asio.dll` and rename it to `libportaudio64bit.dll`.
