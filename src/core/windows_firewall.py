"""Windows Firewall integration for the Remote Audio I/O provider.

The main MeasureLab process always remains unelevated.  Read-only checks use
the built-in NetSecurity PowerShell module, while the narrowly scoped rule
update is launched through the Windows ``runas`` verb so Windows owns the UAC
consent UI.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
import ipaddress
import json
import os
import subprocess
import sys
import textwrap
from typing import Callable


TCP_RULE_NAME = "MeasureLab.RemoteAudio.Provider.TCP"
UDP_RULE_NAME = "MeasureLab.RemoteAudio.Provider.UDP"


class FirewallState(str, Enum):
    """Result of checking the rules required by the provider."""

    NOT_REQUIRED = "not_required"
    READY = "ready"
    NEEDS_PERMISSION = "needs_permission"
    CONFLICTING_BLOCK = "conflicting_block"
    PUBLIC_NETWORK = "public_network"
    MANAGED_POLICY = "managed_policy"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FirewallAssessment:
    state: FirewallState
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FirewallOperationResult:
    success: bool
    canceled: bool = False
    detail: str = ""


def _powershell_quote(value: str) -> str:
    """Return a PowerShell single-quoted literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _encoded_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _is_loopback_bind(bind_host: str) -> bool:
    value = str(bind_host).strip().casefold()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


class WindowsFirewallManager:
    """Inspect and configure MeasureLab's Windows Firewall rules."""

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        frozen: bool | None = None,
        executable: str | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.platform_name = sys.platform if platform_name is None else platform_name
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        self.executable = os.path.abspath(sys.executable if executable is None else executable)
        self._command_runner = subprocess.run if command_runner is None else command_runner

    @property
    def supported(self) -> bool:
        """Only manage the packaged Windows executable, never python.exe."""
        return self.platform_name == "win32" and self.frozen

    @staticmethod
    def requires_permission(bind_host: str) -> bool:
        return not _is_loopback_bind(bind_host)

    @staticmethod
    def _validate_port(port: int) -> int:
        value = int(port)
        if not 1 <= value <= 65535:
            raise ValueError("invalid firewall port")
        return value

    @staticmethod
    def _local_address(bind_host: str) -> str | None:
        value = str(bind_host).strip()
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return None
        if address.version != 4 or address.is_unspecified:
            return None
        return str(address)

    @staticmethod
    def _powershell_path() -> str:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        return os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")

    def _base_command(self, script: str) -> list[str]:
        return [
            self._powershell_path(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            _encoded_powershell(script),
        ]

    def _assessment_script(self, bind_host: str, port: int) -> str:
        app = _powershell_quote(self.executable)
        tcp_name = _powershell_quote(TCP_RULE_NAME)
        udp_name = _powershell_quote(UDP_RULE_NAME)
        expected_local_address = _powershell_quote(self._local_address(bind_host) or "Any")
        return textwrap.dedent(
            f"""
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            $ErrorActionPreference = 'Stop'
            $appPath = {app}
            $providerPort = {port}
            $expectedLocalAddress = {expected_local_address}

            function Test-MeasureLabRule([string]$store, [string]$name, [string]$protocol) {{
                $rules = @(Get-NetFirewallRule -PolicyStore $store -Name $name -ErrorAction SilentlyContinue)
                foreach ($rule in $rules) {{
                    $application = Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $rule
                    $portFilter = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule
                    $addressFilter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule
                    $protocolValue = [string]$portFilter.Protocol
                    $profileValue = [string]$rule.Profile
                    $protocolMatches = $protocolValue -ieq $protocol
                    if ($protocol -eq 'TCP') {{ $protocolMatches = $protocolMatches -or $protocolValue -eq '6' }}
                    if ($protocol -eq 'UDP') {{ $protocolMatches = $protocolMatches -or $protocolValue -eq '17' }}
                    if (
                        ([string]$rule.Enabled -ieq 'True') -and
                        ([string]$rule.Direction -ieq 'Inbound') -and
                        ([string]$rule.Action -ieq 'Allow') -and
                        ([string]$application.Program -ieq $appPath) -and
                        $protocolMatches -and
                        ([string]$portFilter.LocalPort -eq [string]$providerPort) -and
                        ([string]$addressFilter.LocalAddress -ieq $expectedLocalAddress) -and
                        ([string]$addressFilter.RemoteAddress -ieq 'LocalSubnet') -and
                        ($profileValue -match 'Private') -and
                        ($profileValue -match 'Domain') -and
                        ($profileValue -notmatch 'Public') -and
                        ([string]$rule.EdgeTraversalPolicy -ieq 'Block')
                    ) {{
                        return $true
                    }}
                }}
                return $false
            }}

            function Get-MeasureLabBlockCount([string]$store) {{
                $count = 0
                $blockRules = @(Get-NetFirewallRule -PolicyStore $store -Direction Inbound -Action Block `
                    -ErrorAction SilentlyContinue)
                foreach ($rule in $blockRules) {{
                    $application = Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $rule
                    if ([string]$application.Program -ieq $appPath) {{ $count += 1 }}
                }}
                return $count
            }}

            $categories = @()
            try {{
                $categories = @(Get-NetConnectionProfile -ErrorAction Stop | ForEach-Object {{
                    [string]$_.NetworkCategory
                }} | Sort-Object -Unique)
            }} catch {{
                $categories = @()
            }}

            [PSCustomObject]@{{
                active_tcp = (Test-MeasureLabRule 'ActiveStore' {tcp_name} 'TCP')
                active_udp = (Test-MeasureLabRule 'ActiveStore' {udp_name} 'UDP')
                persistent_tcp = (Test-MeasureLabRule 'PersistentStore' {tcp_name} 'TCP')
                persistent_udp = (Test-MeasureLabRule 'PersistentStore' {udp_name} 'UDP')
                active_blocks = (Get-MeasureLabBlockCount 'ActiveStore')
                persistent_blocks = (Get-MeasureLabBlockCount 'PersistentStore')
                network_categories = $categories
            }} | ConvertTo-Json -Compress
            """
        ).strip()

    def assess(self, bind_host: str, port: int) -> FirewallAssessment:
        """Return whether the provider can rely on an effective managed rule."""
        if not self.supported or not self.requires_permission(bind_host):
            return FirewallAssessment(FirewallState.NOT_REQUIRED)
        try:
            checked_port = self._validate_port(port)
            completed = self._command_runner(
                self._base_command(self._assessment_script(bind_host, checked_port)),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "Windows Firewall query failed").strip()
                return FirewallAssessment(FirewallState.UNAVAILABLE, detail[:500])
            payload = json.loads(completed.stdout.strip())
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return FirewallAssessment(FirewallState.UNAVAILABLE, str(exc)[:500])

        categories_value = payload.get("network_categories", [])
        if isinstance(categories_value, str):
            categories = {categories_value.casefold()}
        elif isinstance(categories_value, list):
            categories = {str(value).casefold() for value in categories_value}
        else:
            categories = set()
        if categories and categories <= {"public"}:
            return FirewallAssessment(FirewallState.PUBLIC_NETWORK)
        active_blocks = int(payload.get("active_blocks", 0) or 0)
        persistent_blocks = int(payload.get("persistent_blocks", 0) or 0)
        if persistent_blocks > 0:
            return FirewallAssessment(FirewallState.CONFLICTING_BLOCK)
        if active_blocks > 0:
            return FirewallAssessment(FirewallState.MANAGED_POLICY)
        if bool(payload.get("active_tcp")) and bool(payload.get("active_udp")):
            return FirewallAssessment(FirewallState.READY)
        if bool(payload.get("persistent_tcp")) and bool(payload.get("persistent_udp")):
            return FirewallAssessment(FirewallState.MANAGED_POLICY)
        return FirewallAssessment(FirewallState.NEEDS_PERMISSION)

    def _ensure_script(self, bind_host: str, port: int) -> str:
        app = _powershell_quote(self.executable)
        tcp_name = _powershell_quote(TCP_RULE_NAME)
        udp_name = _powershell_quote(UDP_RULE_NAME)
        local_address = self._local_address(bind_host)
        local_address_statement = ""
        if local_address is not None:
            local_address_statement = f"$common.LocalAddress = {_powershell_quote(local_address)}"
        return textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            $appPath = {app}
            $providerPort = {port}
            $managedNames = @({tcp_name}, {udp_name})

            try {{
                $localBlocks = @(Get-NetFirewallRule -PolicyStore PersistentStore -Direction Inbound -Action Block `
                    -ErrorAction SilentlyContinue)
                foreach ($rule in $localBlocks) {{
                    $application = Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $rule
                    if ([string]$application.Program -ieq $appPath) {{
                        Remove-NetFirewallRule -InputObject $rule -Confirm:$false
                    }}
                }}

                foreach ($name in $managedNames) {{
                    Remove-NetFirewallRule -PolicyStore PersistentStore -Name $name -ErrorAction SilentlyContinue `
                        -Confirm:$false
                }}

                $common = @{{
                    PolicyStore = 'PersistentStore'
                    Direction = 'Inbound'
                    Action = 'Allow'
                    Enabled = 'True'
                    Profile = @('Private', 'Domain')
                    Program = $appPath
                    LocalPort = $providerPort
                    RemoteAddress = 'LocalSubnet'
                    EdgeTraversalPolicy = 'Block'
                    Group = 'MeasureLab'
                    Description = 'Allows Remote Audio I/O provider traffic from the local subnet.'
                }}
                {local_address_statement}

                New-NetFirewallRule @common -Name {tcp_name} `
                    -DisplayName 'MeasureLab Remote Audio Provider (TCP)' -Protocol TCP | Out-Null
                New-NetFirewallRule @common -Name {udp_name} `
                    -DisplayName 'MeasureLab Remote Audio Provider (UDP)' -Protocol UDP | Out-Null
                exit 0
            }} catch {{
                exit 1
            }}
            """
        ).strip()

    def ensure_rules(self, bind_host: str, port: int, *, parent_window: int = 0) -> FirewallOperationResult:
        """Request UAC consent and install/update the two managed rules."""
        if not self.supported or not self.requires_permission(bind_host):
            return FirewallOperationResult(success=True)
        try:
            checked_port = self._validate_port(port)
            return self._run_elevated(self._ensure_script(bind_host, checked_port), parent_window=parent_window)
        except (OSError, TypeError, ValueError) as exc:
            return FirewallOperationResult(success=False, detail=str(exc)[:500])

    def _run_elevated(self, script: str, *, parent_window: int = 0) -> FirewallOperationResult:
        """Run a PowerShell command through ShellExecuteEx and wait for it."""
        if self.platform_name != "win32":
            return FirewallOperationResult(success=False, detail="Windows elevation is unavailable")

        class ShellExecuteInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", wintypes.LPVOID),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        win_dll = getattr(ctypes, "WinDLL", None)
        get_last_error = getattr(ctypes, "get_last_error", lambda: 0)
        if win_dll is None:
            return FirewallOperationResult(success=False, detail="Windows elevation API is unavailable")
        shell32 = win_dll("shell32", use_last_error=True)
        kernel32 = win_dll("kernel32", use_last_error=True)
        shell_execute = shell32.ShellExecuteExW
        shell_execute.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
        shell_execute.restype = wintypes.BOOL
        wait_for_single_object = kernel32.WaitForSingleObject
        wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait_for_single_object.restype = wintypes.DWORD
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        get_exit_code.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        command = self._base_command(script)
        parameters = subprocess.list2cmdline(command[1:])
        info = ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        info.hwnd = parent_window or None
        info.lpVerb = "runas"
        info.lpFile = command[0]
        info.lpParameters = parameters
        info.nShow = 0  # SW_HIDE; the UAC consent UI remains visible.

        if not shell_execute(ctypes.byref(info)):
            error_code = get_last_error()
            if error_code == 1223:  # ERROR_CANCELLED
                return FirewallOperationResult(success=False, canceled=True, detail="UAC request was canceled")
            return FirewallOperationResult(
                success=False,
                detail=f"Unable to request Windows administrator approval (error {error_code})",
            )
        try:
            wait_for_single_object(info.hProcess, 0xFFFFFFFF)
            exit_code = wintypes.DWORD()
            if not get_exit_code(info.hProcess, ctypes.byref(exit_code)):
                return FirewallOperationResult(success=False, detail="Unable to read firewall helper result")
            if exit_code.value != 0:
                return FirewallOperationResult(
                    success=False,
                    detail=f"Windows Firewall rule update failed (exit code {exit_code.value})",
                )
            return FirewallOperationResult(success=True)
        finally:
            close_handle(info.hProcess)
