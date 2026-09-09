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

function Get-ShellLinkProperties([string]$Path) {
    if (-not ([System.Management.Automation.PSTypeName]"MeasureLab.ShellLinkReader").Type) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace MeasureLab
{
    [ComImport]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW
    {
        [PreserveSig] int GetPath(StringBuilder pszFile, int cch, IntPtr pfd, uint fFlags);
        [PreserveSig] int GetIDList(out IntPtr ppidl);
        [PreserveSig] int SetIDList(IntPtr pidl);
        [PreserveSig] int GetDescription(StringBuilder pszName, int cch);
        [PreserveSig] int SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        [PreserveSig] int GetWorkingDirectory(StringBuilder pszDir, int cch);
        [PreserveSig] int SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        [PreserveSig] int GetArguments(StringBuilder pszArgs, int cch);
        [PreserveSig] int SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        [PreserveSig] int GetHotkey(out short pwHotkey);
        [PreserveSig] int SetHotkey(short wHotkey);
        [PreserveSig] int GetShowCmd(out int piShowCmd);
        [PreserveSig] int SetShowCmd(int iShowCmd);
        [PreserveSig] int GetIconLocation(StringBuilder pszIconPath, int cch, out int piIcon);
        [PreserveSig] int SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        [PreserveSig] int SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
        [PreserveSig] int Resolve(IntPtr hwnd, uint fFlags);
        [PreserveSig] int SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport]
    [Guid("0000010B-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPersistFile
    {
        [PreserveSig] int GetClassID(out Guid pClassID);
        [PreserveSig] int IsDirty();
        [PreserveSig] int Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        [PreserveSig] int Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
        [PreserveSig] int SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        [PreserveSig] int GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
    }

    public static class ShellLinkReader
    {
        private static readonly Guid ShellLinkClassId =
            new Guid("00021401-0000-0000-C000-000000000046");

        public static string[] Read(string path)
        {
            object linkObject = Activator.CreateInstance(
                Type.GetTypeFromCLSID(ShellLinkClassId, true));
            try
            {
                var link = (IShellLinkW)linkObject;
                var persistFile = (IPersistFile)linkObject;
                Check(persistFile.Load(path, 0));

                var target = new StringBuilder(32768);
                Check(link.GetPath(target, target.Capacity, IntPtr.Zero, 0));
                var workingDirectory = new StringBuilder(32768);
                Check(link.GetWorkingDirectory(
                    workingDirectory, workingDirectory.Capacity));
                return new[] { target.ToString(), workingDirectory.ToString() };
            }
            finally
            {
                Marshal.FinalReleaseComObject(linkObject);
            }
        }

        private static void Check(int result)
        {
            if (result < 0)
            {
                Marshal.ThrowExceptionForHR(result);
            }
        }
    }
}
'@
    }
    return [MeasureLab.ShellLinkReader]::Read($Path)
}

function Assert-InstalledBundle {
    if (-not (Test-Path $registryKey)) { throw "Missing per-user uninstall registration" }
    if (-not (Test-Path -LiteralPath $shortcut)) { throw "Missing Start menu shortcut" }
    $expectedTarget = Join-Path $installDir "MeasureLab.exe"
    # WScript.Shell may convert non-ASCII paths to '?' through its ANSI
    # automation interface. Read the link with the native Unicode API instead.
    $linkProperties = Get-ShellLinkProperties $shortcut
    $targetMatches = $linkProperties[0] -eq $expectedTarget
    $workingDirectoryMatches = $linkProperties[1] -eq $installDir
    if (-not $targetMatches -or -not $workingDirectoryMatches) {
        throw "Incorrect shortcut target ('$($linkProperties[0])') or working directory ('$($linkProperties[1])'); expected '$expectedTarget' and '$installDir'"
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
