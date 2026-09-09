# Run from the repository root after building dist/onedir/MeasureLab.
[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$appVersion = & $Python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
if ($LASTEXITCODE -ne 0) { throw "Could not read the application version" }
if ($appVersion -notmatch '^(\d+\.\d+\.\d+)(?:(?:a|b|rc)\d+|\.dev\d+|\.post\d+)?$') {
    throw "Unsupported installer version: $appVersion"
}
$fileVersion = "$($Matches[1]).0"
if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME -ne "v$appVersion") {
    throw "Release tag $env:GITHUB_REF_NAME does not match pyproject.toml v$appVersion"
}
if (-not (Test-Path -LiteralPath $Iscc)) {
    throw "Inno Setup 6.3+ is required. Install Inno Setup 6 or pass -Iscc <path to ISCC.exe>."
}
$compilerVersion = (Get-Item -LiteralPath $Iscc).VersionInfo.FileVersion
if ([version]$compilerVersion -lt [version]"6.3.0" -or [version]$compilerVersion -ge [version]"7.0") {
    throw "Expected Inno Setup 6.3+ (6.x), found $compilerVersion"
}
Write-Host "Building MeasureLab $appVersion with Inno Setup $compilerVersion"

$sourceDir = (Resolve-Path "dist/onedir/MeasureLab").Path
foreach ($file in @("MeasureLab.exe", "_internal", "enable_asio.bat", "disable_asio.bat", "README_ASIO.txt")) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceDir $file))) {
        throw "Incomplete Windows bundle: missing $file"
    }
}
$outputDir = (New-Item -ItemType Directory -Force "dist/release").FullName
& $Iscc "/DAppVersion=$appVersion" "/DAppFileVersion=$fileVersion" "/DSourceDir=$sourceDir" "/DOutputDir=$outputDir" "packaging/windows/MeasureLab.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed: $LASTEXITCODE" }
$installer = Join-Path $outputDir "MeasureLab-v$appVersion-windows-x64-setup.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer was not created: $installer" }
if ($env:GITHUB_OUTPUT) { "installer=$installer" >> $env:GITHUB_OUTPUT }
