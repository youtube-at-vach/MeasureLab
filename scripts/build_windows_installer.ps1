# Run from the repository root. The official distribution uses MSVC + static CRT.
[CmdletBinding()]
param(
    [ValidateSet('x86_64-pc-windows-msvc', 'x86_64-pc-windows-gnu')]
    [string]$Target = 'x86_64-pc-windows-msvc',
    [string]$Iscc = (Join-Path $PSScriptRoot '../.tools/inno-setup/ISCC.exe'),
    # The VM's experimental GNU configuration needs LLD for the final link.
    [string]$GnuLinker
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $IsWindows) { throw 'Build Windows packages on Windows with PowerShell 7.' }
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([IO.Path]::GetFullPath($PWD.Path) -ne $repoRoot) { throw 'Run this script from the repository root.' }
if (-not (Test-Path -LiteralPath $Iscc)) {
    throw 'Install Inno Setup 6 with ./scripts/install_inno_setup.ps1, or pass -Iscc <ISCC.exe>.'
}
$Iscc = (Resolve-Path -LiteralPath $Iscc).Path
$metadataText = & cargo metadata --locked --no-deps --format-version 1
if ($LASTEXITCODE -ne 0) { throw 'Could not read Cargo metadata.' }
$metadata = $metadataText | ConvertFrom-Json
$package = @($metadata.packages | Where-Object name -eq 'measurelab')
if ($package.Count -ne 1) { throw 'Expected exactly one measurelab Cargo package.' }
$version = $package[0].version
if ($version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$') {
    throw "Unsupported release version: $version"
}
$fileVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3]).0"
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -cne "v$version") {
    throw "Release tag $env:GITHUB_REF_NAME does not match Cargo.toml v$version."
}
$sourceSha = & git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the source commit.' }
$dirty = & git status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect source changes.' }
if ($env:GITHUB_ACTIONS -eq 'true' -and $dirty) { throw 'CI release builds require a clean checkout.' }

# A fresh staging directory on every invocation prevents stale payloads/checksums.
$runRoot = (New-Item -ItemType Directory (Join-Path $repoRoot "dist/windows/$([guid]::NewGuid())")).FullName
$sourceDir = (New-Item -ItemType Directory (Join-Path $runRoot 'MeasureLab')).FullName
$releaseDir = (New-Item -ItemType Directory (Join-Path $runRoot 'release')).FullName
$originalFlags = $env:RUSTFLAGS
$originalEncodedFlags = $env:CARGO_ENCODED_RUSTFLAGS
try {
    # Do not inherit target-cpu=native or flags that would change the distributed ABI.
    Remove-Item Env:RUSTFLAGS, Env:CARGO_ENCODED_RUSTFLAGS -ErrorAction SilentlyContinue
    if ($Target -eq 'x86_64-pc-windows-msvc') {
        $env:CARGO_ENCODED_RUSTFLAGS = "-C$([char]31)target-feature=+crt-static"
    }
    $buildArgs = @('rustc', '--release', '--locked', '--target', $Target,
        '--no-default-features', '--features', 'desktop', '--bin', 'measurelab')
    if ($GnuLinker) {
        if ($Target -ne 'x86_64-pc-windows-gnu') { throw '-GnuLinker only applies to GNU builds.' }
        $linker = (Resolve-Path -LiteralPath $GnuLinker).Path
        $buildArgs += @('--', '-C', 'linker-flavor=ld', '-C', "linker=$linker", '-C', 'link-self-contained=yes')
    }
    & cargo @buildArgs | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Cargo release build failed: $LASTEXITCODE" }
} finally {
    $env:RUSTFLAGS = $originalFlags
    $env:CARGO_ENCODED_RUSTFLAGS = $originalEncodedFlags
}
$binary = Join-Path $metadata.target_directory "$Target/release/measurelab.exe"
Copy-Item -LiteralPath $binary -Destination $sourceDir
Copy-Item -LiteralPath 'LICENSE', 'packaging/windows/README.txt' -Destination $sourceDir
$info = [Diagnostics.FileVersionInfo]::GetVersionInfo($binary)
if ($info.ProductVersion -cne $version) { throw "Executable version differs from Cargo: $($info.ProductVersion)" }
$rustVersion = & rustc --version
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify rustc version.' }
$buildInfo = [ordered]@{
    version = $version; tag = "v$version"; source_sha = $sourceSha; source_dirty = [bool]$dirty
    target = $Target; profile = 'release'; features = @('desktop'); rustc = $rustVersion
    crt_static = ($Target -eq 'x86_64-pc-windows-msvc'); authenticode_signed = $false
    executable_sha256 = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
}
$manifestName = "MeasureLab-v$version-windows-x64-build-info.json"
$buildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sourceDir 'build-info.json') -Encoding utf8NoBOM
Copy-Item -LiteralPath (Join-Path $sourceDir 'build-info.json') -Destination (Join-Path $releaseDir $manifestName)
& $Iscc "/DAppVersion=$version" "/DAppFileVersion=$fileVersion" "/DSourceDir=$sourceDir" "/DOutputDir=$releaseDir" 'packaging/windows/MeasureLab.iss' | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed: $LASTEXITCODE" }
$base = "MeasureLab-v$version-windows-x64"
$installer = Join-Path $releaseDir "$base-setup.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw 'Installer was not created.' }
$archive = Join-Path $releaseDir "$base.zip"
Compress-Archive -LiteralPath $sourceDir -DestinationPath $archive
$checksums = Join-Path $releaseDir 'SHA256SUMS-windows-x64.txt'
$assets = @(Get-ChildItem -LiteralPath $releaseDir -File | Sort-Object Name)
$assets | ForEach-Object {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.Name
} | Set-Content -LiteralPath $checksums -Encoding ascii
$result = [ordered]@{
    installer = $installer; archive = $archive; checksums = $checksums
    source_dir = $sourceDir; release_dir = $releaseDir; manifest = (Join-Path $releaseDir $manifestName)
}
if ($env:GITHUB_OUTPUT) {
    foreach ($key in $result.Keys) { "$key=$($result[$key])" >> $env:GITHUB_OUTPUT }
}
return [pscustomobject]$result
