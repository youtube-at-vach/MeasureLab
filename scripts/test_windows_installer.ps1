# Lifecycle integration test. Refuse to touch an existing Rust installation.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$SourceDir,
    [Parameter(Mandatory)][string]$Archive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'windows_shell_link.ps1')
$registryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{97AA1A5C-BB05-4DC8-A791-1259F0622CE5}_is1'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'MeasureLab (Rust).lnk'
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'MeasureLab (Rust).lnk'
if ((Test-Path $registryKey) -or (Test-Path -LiteralPath $shortcut) -or (Test-Path -LiteralPath $desktopShortcut)) {
    throw 'Use a disposable Windows account without MeasureLab (Rust) installed.'
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$SourceDir = (Resolve-Path -LiteralPath $SourceDir).Path
$Archive = (Resolve-Path -LiteralPath $Archive).Path
$testId = [guid]::NewGuid().ToString()
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempRoot "MeasureLab Installer Test $testId"
$installDir = Join-Path $testRoot 'アプリ'
$logDir = (New-Item -ItemType Directory -Force "dist/windows-installer-test/$testId").FullName
$originalAppData = $env:APPDATA
$uninstallCompleted = $false

function Invoke-TestProcess([string]$FilePath, [string[]]$Arguments, [string]$Name, [int]$Expected = 0) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $testRoot `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput "$logDir/$Name.stdout.log" `
        -RedirectStandardError "$logDir/$Name.stderr.log"
    if (-not $process.WaitForExit(180000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Timed out: $FilePath"
    }
    $process.Refresh()
    if ($process.ExitCode -ne $Expected) { throw "$Name exited with $($process.ExitCode), expected $Expected; see $logDir" }
}

function Assert-Payload([string]$Directory) {
    foreach ($file in Get-ChildItem -LiteralPath $SourceDir -File) {
        $installed = Join-Path $Directory $file.Name
        if (-not (Test-Path -LiteralPath $installed)) { throw "Missing payload: $installed" }
        if ((Get-FileHash -LiteralPath $installed).Hash -ne (Get-FileHash -LiteralPath $file.FullName).Hash) {
            throw "Payload differs: $installed"
        }
    }
}

function Assert-Startup([string]$Directory, [string]$Name) {
    $executable = Join-Path $Directory 'measurelab.exe'
    $originalPath = $env:PATH
    try {
        # Developer toolchain DLLs on PATH must not hide missing runtime files.
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        Invoke-TestProcess $executable @('--help') "$Name-help"
        if ((Get-Content "$logDir/$Name-help.stdout.log" -Raw) -notmatch 'MeasureLab') { throw 'Missing CLI help output.' }
        # A QA-enabled binary must never pass as a normal release.
        Invoke-TestProcess $executable @('--demo') "$Name-no-qa" 1
        if ((Get-Content "$logDir/$Name-no-qa.stderr.log" -Raw) -notmatch 'requires --features qa') {
            throw 'Distributed executable did not reject the QA-only demo.'
        }
    } finally {
        $env:PATH = $originalPath
    }
}

function Assert-Registration {
    if (-not (Test-Path $registryKey)) { throw 'Missing per-user uninstall registration.' }
    $registration = Get-ItemProperty $registryKey
    $expectedVersion = (Get-Content (Join-Path $SourceDir 'build-info.json') -Raw | ConvertFrom-Json).version
    if ($registration.DisplayVersion -ne $expectedVersion) { throw 'Incorrect installed version.' }
    foreach ($path in @($shortcut, $desktopShortcut)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Missing shortcut: $path" }
        $link = Get-ShellLinkProperties $path
        if ($link[0] -ne (Join-Path $installDir 'measurelab.exe') -or $link[1] -ne $installDir) {
            throw "Incorrect shortcut target or working directory: $path"
        }
    }
}

try {
    $env:APPDATA = Join-Path $testRoot 'AppData'
    $userData = (New-Item -ItemType Directory -Force (Join-Path $env:APPDATA 'MeasureLab')).FullName
    $settings = Join-Path $userData 'measurement-settings.json'
    Set-Content -LiteralPath $settings -Value '{"installer_test":"preserve"}'
    $settingsHash = (Get-FileHash -LiteralPath $settings).Hash
    $portable = Join-Path $testRoot '展開した ZIP'
    Expand-Archive -LiteralPath $Archive -DestinationPath $portable
    Assert-Payload (Join-Path $portable 'MeasureLab')
    Assert-Startup (Join-Path $portable 'MeasureLab') 'zip'

    $setupArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-')
    Invoke-TestProcess $Installer ($setupArgs + @('/TASKS=desktopicon', "/DIR=`"$installDir`"", "/LOG=`"$logDir/install.log`"")) 'install'
    Assert-Payload $installDir
    Assert-Registration
    Assert-Startup $installDir 'installed'
    $measurement = Join-Path $installDir 'measurements/keep.json'
    New-Item -ItemType Directory -Force (Split-Path $measurement) | Out-Null
    Set-Content -LiteralPath $measurement -Value '{"measurement":"preserve"}'
    $measurementHash = (Get-FileHash -LiteralPath $measurement).Hash
    # Repair/update must replace owned files and recover the previous directory/tasks.
    Set-Content -LiteralPath (Join-Path $installDir 'measurelab.exe') -Value 'damaged old executable'
    Invoke-TestProcess $Installer ($setupArgs + "/LOG=`"$logDir/reinstall.log`"") 'reinstall'
    Assert-Payload $installDir
    Assert-Registration
    Assert-Startup $installDir 'updated'
    if ((Get-FileHash -LiteralPath $settings).Hash -ne $settingsHash -or
        (Get-FileHash -LiteralPath $measurement).Hash -ne $measurementHash) { throw 'Update modified user data.' }
    Invoke-TestProcess (Join-Path $installDir 'unins000.exe') ($setupArgs + "/LOG=`"$logDir/uninstall.log`"") 'uninstall'
    $uninstallCompleted = $true
    if ((Test-Path $registryKey) -or (Test-Path -LiteralPath $shortcut) -or
        (Test-Path -LiteralPath $desktopShortcut) -or (Test-Path -LiteralPath (Join-Path $installDir 'measurelab.exe'))) {
        throw 'Uninstall left application registration, shortcuts or executable.'
    }
    if ((Get-FileHash -LiteralPath $settings).Hash -ne $settingsHash -or
        (Get-FileHash -LiteralPath $measurement).Hash -ne $measurementHash) { throw 'Uninstall modified user data.' }
    Write-Host "Installer lifecycle passed (ZIP, startup, no QA, Unicode paths, payload, repair, shortcuts, data preservation, uninstall). Logs: $logDir"
} finally {
    $env:APPDATA = $originalAppData
    $uninstaller = Join-Path $installDir 'unins000.exe'
    if (-not $uninstallCompleted -and (Test-Path -LiteralPath $uninstaller)) {
        try {
            Invoke-TestProcess $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'cleanup'
            $uninstallCompleted = $true
        } catch {
            Write-Warning "Cleanup uninstall failed; retain $testRoot for inspection: $($_.Exception.Message)"
        }
    }
    # Only delete the exact, generated child of the OS temp directory.
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTestRoot -ne (Join-Path $tempRoot "MeasureLab Installer Test $testId")) { throw 'Unsafe cleanup path.' }
    if (($uninstallCompleted -or -not (Test-Path -LiteralPath $uninstaller)) -and (Test-Path -LiteralPath $resolvedTestRoot)) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
