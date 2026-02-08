@echo off
setlocal

rem Define the target directory relative to this script
rem In a PyInstaller onedir build, scripts are usually at the root, and internal data is in _internal
set "TARGET_DIR=_internal\_sounddevice_data\portaudio-binaries"

if not exist "%TARGET_DIR%" (
    echo Error: Could not find PortAudio binaries directory at:
    echo %TARGET_DIR%
    echo Make sure this script is in the root of the MeasureLab folder.
    pause
    exit /b 1
)

pushd "%TARGET_DIR%"

echo Enabling ASIO support...

rem Process 64-bit DLL if it exists
if exist "libportaudio64bit.dll" (
    if not exist "libportaudio64bit.dll.bak" (
        echo Backing up standard 64-bit driver...
        copy "libportaudio64bit.dll" "libportaudio64bit.dll.bak" >nul
    )
    
    if exist "libportaudio64bit-asio.dll" (
        echo Copying ASIO 64-bit driver...
        copy /Y "libportaudio64bit-asio.dll" "libportaudio64bit.dll" >nul
        echo 64-bit ASIO enabled.
    ) else (
        echo Warning: libportaudio64bit-asio.dll not found.
    )
)



echo.
echo Operation complete. Please restart MeasureLab to see ASIO devices.
popd
pause
