@echo off
setlocal

set "PAUSE_ON_EXIT=1"
if /I "%~1"=="/silent" set "PAUSE_ON_EXIT="

rem Define the target directory relative to this script.
rem In a PyInstaller onedir build, scripts are at the root and internal data is in _internal.
set "TARGET_DIR=%~dp0_internal\_sounddevice_data\portaudio-binaries"

if not exist "%TARGET_DIR%" (
    echo Error: Could not find PortAudio binaries directory at:
    echo %TARGET_DIR%
    echo Make sure this script is in the root of the MeasureLab folder.
    call :maybe_pause
    exit /b 1
)

pushd "%TARGET_DIR%" || (
    echo Error: Could not access the PortAudio binaries directory.
    call :maybe_pause
    exit /b 1
)

echo Enabling ASIO support...

if not exist "libportaudio64bit.dll" (
    echo Error: Standard 64-bit PortAudio library not found.
    goto :error
)

if not exist "libportaudio64bit-asio.dll" (
    echo Error: ASIO-enabled 64-bit PortAudio library not found.
    goto :error
)

if not exist "libportaudio64bit.dll.bak" (
    echo Backing up standard 64-bit driver...
    copy /Y "libportaudio64bit.dll" "libportaudio64bit.dll.bak" >nul || goto :copy_error
)

echo Copying ASIO 64-bit driver...
copy /Y "libportaudio64bit-asio.dll" "libportaudio64bit.dll" >nul || goto :copy_error
echo 64-bit ASIO enabled.

echo.
echo Operation complete. Please restart MeasureLab to see ASIO devices.
popd
call :maybe_pause
exit /b 0

:copy_error
echo Error: Could not copy the PortAudio library.

:error
popd
call :maybe_pause
exit /b 1

:maybe_pause
if defined PAUSE_ON_EXIT pause
exit /b 0
