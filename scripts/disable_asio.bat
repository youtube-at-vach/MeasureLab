@echo off
setlocal

rem Define the target directory relative to this script
set "TARGET_DIR=_internal\_sounddevice_data\portaudio-binaries"

if not exist "%TARGET_DIR%" (
    echo Error: Could not find PortAudio binaries directory at:
    echo %TARGET_DIR%
    echo Make sure this script is in the root of the MeasureLab folder.
    pause
    exit /b 1
)

pushd "%TARGET_DIR%"

echo Disabling ASIO support (restoring standard drivers)...

rem Process 64-bit DLL
if exist "libportaudio64bit.dll.bak" (
    echo Restoring standard 64-bit driver...
    copy /Y "libportaudio64bit.dll.bak" "libportaudio64bit.dll" >nul
    del "libportaudio64bit.dll.bak"
    echo 64-bit standard driver restored.
) else (
    echo No 64-bit backup found. ASIO might not be enabled or backup is missing.
)

echo.
echo Operation complete. Please restart MeasureLab used standard drivers.
popd
pause
