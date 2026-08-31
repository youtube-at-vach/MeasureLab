from __future__ import annotations

import base64
import json
import subprocess

from src.core.windows_firewall import (
    FirewallOperationResult,
    FirewallState,
    TCP_RULE_NAME,
    UDP_RULE_NAME,
    WindowsFirewallManager,
)


def _runner_for(payload: dict[str, object], *, returncode: int = 0, stderr: str = ""):
    def runner(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=json.dumps(payload),
            stderr=stderr,
        )

    return runner


def _manager(payload: dict[str, object]) -> WindowsFirewallManager:
    return WindowsFirewallManager(
        platform_name="win32",
        frozen=True,
        executable="/opt/MeasureLab/MeasureLab.exe",
        command_runner=_runner_for(payload),
    )


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "active_tcp": False,
        "active_udp": False,
        "persistent_tcp": False,
        "persistent_udp": False,
        "active_blocks": 0,
        "persistent_blocks": 0,
        "network_categories": ["Private"],
    }
    payload.update(overrides)
    return payload


def _decode_script(command: list[str]) -> str:
    encoded = command[command.index("-EncodedCommand") + 1]
    return base64.b64decode(encoded).decode("utf-16-le")


def test_firewall_management_is_limited_to_packaged_windows_builds():
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("PowerShell should not run")

    source_build = WindowsFirewallManager(
        platform_name="win32",
        frozen=False,
        command_runner=runner,
    )
    non_windows = WindowsFirewallManager(
        platform_name="darwin",
        frozen=True,
        command_runner=runner,
    )

    assert source_build.assess("0.0.0.0", 40100).state == FirewallState.NOT_REQUIRED
    assert non_windows.assess("0.0.0.0", 40100).state == FirewallState.NOT_REQUIRED
    assert calls == []


def test_loopback_provider_does_not_need_a_firewall_rule():
    manager = WindowsFirewallManager(platform_name="win32", frozen=True)

    assert manager.assess("127.0.0.1", 40100).state == FirewallState.NOT_REQUIRED
    assert manager.assess("localhost", 40100).state == FirewallState.NOT_REQUIRED


def test_assessment_reports_effective_rules_as_ready():
    manager = _manager(_payload(active_tcp=True, active_udp=True, persistent_tcp=True, persistent_udp=True))

    assert manager.assess("0.0.0.0", 40100).state == FirewallState.READY


def test_assessment_detects_public_network_before_prompting_for_rules():
    manager = _manager(_payload(network_categories=["Public"]))

    assert manager.assess("0.0.0.0", 40100).state == FirewallState.PUBLIC_NETWORK


def test_assessment_detects_local_block_rule_created_by_windows_prompt():
    manager = _manager(_payload(persistent_blocks=2))

    assert manager.assess("0.0.0.0", 40100).state == FirewallState.CONFLICTING_BLOCK


def test_assessment_distinguishes_managed_policy_from_missing_rules():
    managed = _manager(_payload(active_blocks=1))
    installed_but_ineffective = _manager(_payload(persistent_tcp=True, persistent_udp=True))
    missing = _manager(_payload())

    assert managed.assess("0.0.0.0", 40100).state == FirewallState.MANAGED_POLICY
    assert installed_but_ineffective.assess("0.0.0.0", 40100).state == FirewallState.MANAGED_POLICY
    assert missing.assess("0.0.0.0", 40100).state == FirewallState.NEEDS_PERMISSION


def test_assessment_fails_closed_when_powershell_query_fails():
    manager = WindowsFirewallManager(
        platform_name="win32",
        frozen=True,
        executable="/opt/MeasureLab/MeasureLab.exe",
        command_runner=_runner_for({}, returncode=1, stderr="query denied"),
    )

    result = manager.assess("0.0.0.0", 40100)

    assert result.state == FirewallState.UNAVAILABLE
    assert result.detail == "query denied"


def test_assessment_uses_fixed_names_current_program_and_selected_port():
    captured: list[list[str]] = []

    def runner(command, **_kwargs):
        captured.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout=json.dumps(_payload()), stderr="")

    manager = WindowsFirewallManager(
        platform_name="win32",
        frozen=True,
        executable="/opt/Measure'Lab/MeasureLab.exe",
        command_runner=runner,
    )

    manager.assess("192.168.1.25", 41234)
    script = _decode_script(captured[0])

    assert TCP_RULE_NAME in script
    assert UDP_RULE_NAME in script
    assert "$providerPort = 41234" in script
    assert "$expectedLocalAddress = '192.168.1.25'" in script
    assert "/opt/Measure''Lab/MeasureLab.exe" in script


def test_rule_update_is_scoped_to_program_port_profiles_and_local_subnet(monkeypatch):
    manager = WindowsFirewallManager(
        platform_name="win32",
        frozen=True,
        executable="/opt/MeasureLab/MeasureLab.exe",
    )
    captured = {}

    def elevated(script: str, *, parent_window: int = 0):
        captured["script"] = script
        captured["parent_window"] = parent_window
        return FirewallOperationResult(success=True)

    monkeypatch.setattr(manager, "_run_elevated", elevated)

    result = manager.ensure_rules("192.168.1.25", 40100, parent_window=123)
    script = str(captured["script"])

    assert result.success
    assert captured["parent_window"] == 123
    assert "Profile = @('Private', 'Domain')" in script
    assert "RemoteAddress = 'LocalSubnet'" in script
    assert "$common.LocalAddress = '192.168.1.25'" in script
    assert "-Protocol TCP" in script
    assert "-Protocol UDP" in script
    assert "LocalPort = $providerPort" in script
    assert "EdgeTraversalPolicy = 'Block'" in script
    assert "Remove-NetFirewallRule -InputObject $rule" in script
