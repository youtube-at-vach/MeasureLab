ASIO Support for MeasureLab
===========================

MeasureLab includes support for ASIO drivers, but it is disabled by default to ensure maximum compatibility with standard Windows audio drivers (WASAPI, MME, DirectSound).

Enabling ASIO
-------------
To enable ASIO support, you must switch the active PortAudio driver to the ASIO-enabled version. We have provided a script to do this automatically.

1.  Close MeasureLab if it is running.
2.  Navigate to the `scripts` folder in the MeasureLab directory (or the root folder if you are using the installed version where these scripts might be placed).
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
