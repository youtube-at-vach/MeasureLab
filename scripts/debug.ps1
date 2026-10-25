# Native Windows counterpart of debug.sh; no shell policy changes required.
$ErrorActionPreference = 'Stop'
$measurelabProfile = 'dev-fast'
$measurelabAppArgs = @()

for ($measurelabIndex = 0; $measurelabIndex -lt $args.Count; $measurelabIndex++) {
    $measurelabArg = $args[$measurelabIndex]
    if ($measurelabArg -ceq '--') {
        if ($measurelabIndex + 1 -lt $args.Count) {
            $measurelabAppArgs += $args[($measurelabIndex + 1)..($args.Count - 1)]
        }
        break
    } elseif ($measurelabArg -ceq '--audio') {
        continue
    } elseif ($measurelabArg -ceq '--release') {
        $measurelabProfile = 'release'
    } elseif ($measurelabArg -ceq '--full-debug') {
        $measurelabProfile = 'dev'
    } elseif ($measurelabArg -ceq '--help' -or $measurelabArg -ceq '-h') {
        Write-Output @'
Usage: ./scripts/pwsh.cmd -File ./scripts/debug.ps1 [launcher options] [application options]

Build and start MeasureLab with input and output stopped.
Launcher options: --audio, --full-debug, --release, --help, --
Application options: --compact, --gpu-smoke, --list-devices
--demo and --ui-smoke explicitly enable the qa feature.
Pass -- --help to build and check the application's CLI without opening a GUI.
'@
        exit 0
    } else {
        $measurelabAppArgs += $measurelabArg
    }
}

$measurelabCargoArgs = @('run', '--locked', '--profile', $measurelabProfile)
if ($measurelabAppArgs -ccontains '--demo' -or $measurelabAppArgs -ccontains '--ui-smoke') {
    $measurelabCargoArgs += @('--features', 'qa')
}
$measurelabCargoArgs += @('--') + $measurelabAppArgs
if (-not $env:RUST_BACKTRACE) { $env:RUST_BACKTRACE = '1' }
& (Join-Path $PSScriptRoot 'cargo.ps1') @measurelabCargoArgs
exit $LASTEXITCODE
