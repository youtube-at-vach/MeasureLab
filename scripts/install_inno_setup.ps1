# Install the pinned compiler locally; do not alter PATH or file associations.
[CmdletBinding()]
param([string]$Destination = (Join-Path $PSScriptRoot '../.tools/inno-setup'))

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Destination = [IO.Path]::GetFullPath($Destination)
$compiler = Join-Path $Destination 'ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $downloadDir = (New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot '../.tools/downloads')).FullName
    $setup = Join-Path $downloadDir 'innosetup-6.7.3.exe'
    $url = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe'
    $sha256 = '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
    if (-not (Test-Path -LiteralPath $setup)) { Invoke-WebRequest $url -OutFile $setup }
    if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha256) {
        throw "Inno Setup download checksum mismatch: $setup"
    }
    $process = Start-Process -FilePath $setup -WindowStyle Hidden -PassThru -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/CURRENTUSER',
        '/NOICONS', '/TASKS=', "/DIR=`"$Destination`""
    )
    if (-not $process.WaitForExit(180000)) { throw 'Inno Setup installation timed out' }
    if ($process.ExitCode -ne 0) { throw "Inno Setup installation failed: $($process.ExitCode)" }
}
if (-not (Test-Path -LiteralPath $compiler)) { throw "Inno Setup compiler not found: $compiler" }
return $compiler
