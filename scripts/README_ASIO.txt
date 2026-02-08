ASIO Support for MeasureLab
===========================

MeasureLab uses the PortAudio library, which supports ASIO.
However, **ASIO support is intentionally not enabled by default** due to licensing considerations.
For the same reason, MeasureLab does **not** redistribute any ASIO drivers or the ASIO SDK.

If you wish to use ASIO with MeasureLab, you can enable it manually using the provided script.

> **Note:**
> This process does **not** install or redistribute ASIO drivers.

Enabling ASIO
-------------
To enable ASIO support, you must switch the active PortAudio driver to the ASIO-enabled version. We have provided a script to do this automatically.

1.  Close MeasureLab if it is running.
2.  Navigate to the main MeasureLab folder (where MeasureLab.exe is located).
3.  Double-click `enable_asio.bat`.
4.  The script will backup your current drivers and replace them with the ASIO-enabled versions.
5.  Restart MeasureLab. You should now see ASIO devices in the device list.

Disabling ASIO
--------------
If you encounter issues or want to revert to the standard drivers:

1.  Close MeasureLab.
2.  Double-click `disable_asio.bat`.
3.  The script will restore your original drivers.
4.  Restart MeasureLab.

Manual Method
-------------
If the scripts do not work, you can manually replace the files:

1.  Go to `_internal/_sounddevice_data/portaudio-binaries/`.
2.  Rename `libportaudio64bit.dll` to `libportaudio64bit.dll.bak`.
3.  Copy `libportaudio64bit-asio.dll` and rename the copy to `libportaudio64bit.dll`.
