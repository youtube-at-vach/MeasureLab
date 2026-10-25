# Native Windows counterpart of cargo.sh. Run through pwsh.cmd (PowerShell 7).
$ErrorActionPreference = 'Stop'
$measurelabRoot = Split-Path $PSScriptRoot -Parent
$measurelabCargo = Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1

if ($measurelabCargo) {
    $measurelabCargoPath = $measurelabCargo.Source
} else {
    $measurelabCargoPath = Join-Path $measurelabRoot '.tools/cargo/bin/cargo.exe'
    if (-not (Test-Path -LiteralPath $measurelabCargoPath -PathType Leaf)) {
        throw 'Rust is required. Follow guide/rust/WINDOWS.md to install it.'
    }
    $env:CARGO_HOME = Join-Path $measurelabRoot '.tools/cargo'
    $env:RUSTUP_HOME = Join-Path $measurelabRoot '.tools/rustup'
    $env:PATH = "$(Join-Path $env:CARGO_HOME 'bin');$env:PATH"
}

Push-Location -LiteralPath $measurelabRoot
try {
    & $measurelabCargoPath @args
    $measurelabExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $measurelabExitCode
