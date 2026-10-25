@echo off
setlocal
if exist "%~dp0..\.tools\powershell\pwsh.exe" (
    "%~dp0..\.tools\powershell\pwsh.exe" -NoLogo -NoProfile %*
) else (
    where pwsh.exe >nul 2>nul
    if errorlevel 1 (
        echo PowerShell 7 is required. Follow guide/rust/WINDOWS.md. 1>&2
        exit /b 1
    )
    pwsh.exe -NoLogo -NoProfile %*
)
exit /b %errorlevel%
