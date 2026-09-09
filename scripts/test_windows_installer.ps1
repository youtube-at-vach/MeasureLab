# Integration test for a disposable Windows runner; never overwrites an existing installation.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Installer)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$registryKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{27E62938-D88E-4BB1-A631-385CD8B85585}_is1"
$shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "MeasureLab.lnk"
if ((Test-Path $registryKey) -or (Test-Path -LiteralPath $shortcut)) {
    throw "Run this test on a disposable Windows account without MeasureLab installed."
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$testRoot = Join-Path ([IO.Path]::GetTempPath()) "MeasureLab Installer Test $([guid]::NewGuid())"
$installDir = Join-Path $testRoot "アプリ"
$logDir = (New-Item -ItemType Directory -Force "dist/installer-test").FullName
$originalAppData = $env:APPDATA

function Invoke-CheckedProcess([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru
    if (-not $process.WaitForExit(180000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Timed out: $FilePath"
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "$FilePath exited with code $($process.ExitCode)" }
}

function Assert-InstalledBundle {
    if (-not (Test-Path $registryKey)) { throw "Missing per-user uninstall registration" }
    if (-not (Test-Path -LiteralPath $shortcut)) { throw "Missing Start menu shortcut" }
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    $expectedTarget = Join-Path $installDir "MeasureLab.exe"
    # WScript.Shell can expose a valid shortcut path using its DOS 8.3 alias,
    # especially when the target contains non-ASCII characters. Compare the
    # referenced executable when the path strings use different spellings.
    $targetMatches = $link.TargetPath -eq $expectedTarget
    if (-not $targetMatches -and (Test-Path -LiteralPath $link.TargetPath)) {
        $targetMatches = (Get-FileHash -LiteralPath $link.TargetPath).Hash -eq
            (Get-FileHash -LiteralPath $expectedTarget).Hash
    }
    $workingDirectoryMatches = $link.WorkingDirectory -eq $installDir
    $workingDirectoryTarget = Join-Path $link.WorkingDirectory "MeasureLab.exe"
    if (-not $workingDirectoryMatches -and (Test-Path -LiteralPath $workingDirectoryTarget)) {
        $workingDirectoryMatches = (Get-FileHash -LiteralPath $workingDirectoryTarget).Hash -eq
            (Get-FileHash -LiteralPath $expectedTarget).Hash
    }
    if (-not $targetMatches -or -not $workingDirectoryMatches) {
        throw "Incorrect shortcut target ('$($link.TargetPath)') or working directory ('$($link.WorkingDirectory)'); expected '$expectedTarget' and '$installDir'"
    }
    $sourceDir = (Resolve-Path "dist/onedir/MeasureLab").Path
    foreach ($file in Get-ChildItem -LiteralPath $sourceDir -Recurse -File) {
        $relative = [IO.Path]::GetRelativePath($sourceDir, $file.FullName)
        $installed = Join-Path $installDir $relative
        if (-not (Test-Path -LiteralPath $installed)) { throw "Missing installed file: $relative" }
        if ((Get-FileHash -LiteralPath $installed).Hash -ne (Get-FileHash -LiteralPath $file.FullName).Hash) {
            throw "Installed payload differs: $relative"
        }
    }
}

try {
    # Isolate application self-test writes from the runner's real settings.
    $env:APPDATA = Join-Path $testRoot "AppData"
    $userData = New-Item -ItemType Directory -Force (Join-Path $env:APPDATA "MeasureLab")
    $sentinel = Join-Path $userData.FullName "installer-preservation-test.txt"
    Set-Content -LiteralPath $sentinel -Value "keep user data"
    $setupArgs = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=`"$installDir`"")
    Invoke-CheckedProcess $Installer ($setupArgs + "/LOG=`"$logDir/install.log`"") $testRoot
    Assert-InstalledBundle
    Invoke-CheckedProcess (Join-Path $installDir "MeasureLab.exe") @("--self-test") $installDir

    # Capture the real settings/calibration produced by startup, and preserve
    # user files beside the executable while replacing obsolete runtime files.
    $dataHashes = @{}
    foreach ($file in Get-ChildItem -LiteralPath $userData.FullName -Recurse -File) {
        $dataHashes[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash
    }
    $screenshot = Join-Path $installDir "screenshots\keep.txt"
    New-Item -ItemType Directory -Force (Split-Path $screenshot) | Out-Null
    Set-Content -LiteralPath $screenshot -Value "keep screenshot"
    $staleFile = Join-Path $installDir "_internal\obsolete-runtime.dll"
    Set-Content -LiteralPath $staleFile -Value "old runtime"
    # Omit /DIR on the second run: AppId must recover the existing location.
    Invoke-CheckedProcess $Installer @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/LOG=`"$logDir/reinstall.log`"") $testRoot
    Assert-InstalledBundle
    if (Test-Path -LiteralPath $staleFile) { throw "Obsolete runtime survived update" }
    foreach ($file in $dataHashes.Keys) {
        if ((Get-FileHash -LiteralPath $file).Hash -ne $dataHashes[$file]) { throw "Update modified user data: $file" }
    }
    Invoke-CheckedProcess (Join-Path $installDir "MeasureLab.exe") @("--self-test") $installDir
    $dataHashes = @{}
    foreach ($file in Get-ChildItem -LiteralPath $userData.FullName -Recurse -File) {
        $dataHashes[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash
    }
    Invoke-CheckedProcess (Join-Path $installDir "unins000.exe") @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$logDir/uninstall.log`"") $testRoot
    if ((Test-Path $registryKey) -or (Test-Path -LiteralPath $shortcut) -or
        (Test-Path -LiteralPath (Join-Path $installDir "MeasureLab.exe"))) {
        throw "Uninstall left application registration, shortcut or executable"
    }
    if (-not (Test-Path -LiteralPath $screenshot)) { throw "Uninstall removed screenshots" }
    foreach ($file in $dataHashes.Keys) {
        if ((Get-FileHash -LiteralPath $file).Hash -ne $dataHashes[$file]) { throw "Uninstall modified user data: $file" }
    }
    Write-Host "Installer test passed: install, payload hashes, shortcut, startup, reinstall and uninstall."
} finally {
    $env:APPDATA = $originalAppData
    # Retain logs in dist/installer-test; clean up registration even on failure.
    $uninstaller = Join-Path $installDir "unins000.exe"
    if (Test-Path -LiteralPath $uninstaller) {
        Invoke-CheckedProcess $uninstaller @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") $testRoot
    }
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
