"""Routing descriptions shared by the engine and its control surfaces.

Connections describe actual engine buses, not a free-form DSP graph. A source
may appear in several connections; backend ownership and clock remain explicit.
"""

from dataclasses import dataclass
from typing import Literal

import sounddevice as sd

MonitorSource = Literal["dut_output", "measurement_return", "output_mix"]


@dataclass(frozen=True)
class MonitorRoute:
    source: MonitorSource = "dut_output"
    device: int | None = None
    device_name: str = ""
    hostapi: int | None = None
    channels: int = 2
    gain_db: float = -20.0
    enabled: bool = False


@dataclass(frozen=True)
class MonitorStatus:
    route: MonitorRoute
    state: str
    reason: str = ""
    dropped_frames: int = 0
    missing_frames: int = 0
    buffered_frames: int = 0
    latency_seconds: float = 0.0


@dataclass(frozen=True)
class RoutingConnection:
    source: str
    destination: str
    processors: tuple[str, ...] = ()
    state: str = "waiting"
    reason: str = ""


@dataclass(frozen=True)
class RoutingSnapshot:
    backend: str
    clock: str
    sample_rate: float
    input_device: str
    output_device: str
    connections: tuple[RoutingConnection, ...]
    monitor: MonitorStatus
    output_destination: str
    output_editable: bool
    dut_name: str = ""
    dut_inputs: tuple[int, ...] = ()
    dut_returns: tuple[str, ...] = ()
    input_mode: str = "stereo"
    output_mode: str = "stereo"


def build_routing_snapshot(engine) -> RoutingSnapshot:
    """Adapt legacy backend ownership without maintaining a second route graph."""
    with engine.lock:
        offline, network = engine.offline_mode, engine.network_mode
        role = engine._exclusive_audio_role
        provider_status = engine._exclusive_status_provider
        reserved = engine._exclusive_owner is not None or engine._backend_transition
        client = engine.network_client
        sample_rate = engine.sample_rate
        active = bool(engine.is_active() and engine.callbacks)
        loopback, muted = engine._output_route
        input_device, output_device = engine.input_device, engine.output_device
        output_destination = engine.get_output_destination()
        input_mode, output_mode = engine.input_channel_mode, engine.output_channel_mode
    backend = "virtual" if offline else "remote_client" if network else role or "local"
    clock = "virtual_timer" if offline else "remote_device" if network else "physical_device"
    running = "playing" if active else "waiting"
    connections = []
    dut = engine.vst_dut
    dut_active = offline and dut.loaded
    monitor = engine.monitor.status(engine.monitor_unavailable_reason())

    def add(source, destination, processors=(), state=None, reason=""):
        connections.append(RoutingConnection(source, destination, processors, state or running, reason))

    def device_label(device, direction):
        try:
            if device is None:
                device = sd.default.device[direction]
                if device is None or device < 0:
                    return ""
            if isinstance(device, str):
                return device
            info = engine.list_devices()[device]
            return str(info["name"])
        except Exception:
            # Device discovery can fail independently of an existing route.
            return str(device)

    if backend == "remote_provider":
        try:
            details = provider_status() if provider_status is not None else {}
        except Exception as exc:
            details = {"state": "error", "last_error": str(exc)}
        connected = bool(details.get("client_address"))
        state = "error" if details.get("state") == "error" else "playing" if connected else "waiting"
        reason = str(details.get("last_error") or "")
        add("physical_input", "remote_client", state=state, reason=reason)
        playback = connected and details.get("duplex") and details.get("allow_output", True)
        playback_state = (
            "error"
            if state == "error"
            else "off"
            if not playback
            else "playing"
            if details.get("playback_active", False)
            else "waiting"
        )
        add("remote_client", "physical_output", state=playback_state, reason=reason)
        input_label = str(details.get("input_device_name") or "")
        output_label = str(details.get("output_device_name") or "")
    else:
        input_label = "" if offline else device_label(input_device, 0)
        output_label = "" if offline else device_label(output_device, 1)
        connected = bool(client is not None and client.connected) if network else True
        if network and not connected:
            running = "error"
        if offline or loopback:
            if dut_active:
                add(
                    "output_mix",
                    "dut_output",
                    ("dut_input_mapping", "bypass" if dut.bypassed else "vst_dut"),
                    "error" if dut.error else None,
                    dut.error,
                )
                if any(route.startswith("wet") for route in dut.return_routes):
                    add(
                        "dut_output",
                        "measurement_input",
                        ("return_mapping", "one_block_delay"),
                        "error" if dut.error else None,
                        dut.error,
                    )
                if any(route.startswith("dry") for route in dut.return_routes):
                    add(
                        "output_mix",
                        "measurement_input",
                        ("dry_reference", "return_mapping", "one_block_delay"),
                        "error" if dut.error else None,
                        dut.error,
                    )
                if all(route == "silence" for route in dut.return_routes):
                    add("silence", "measurement_input", ("one_block_delay",), "error" if dut.error else None, dut.error)
            else:
                add("output_mix", "measurement_input", ("one_block_delay",))
        else:
            add("remote_input" if network else "physical_input", "measurement_input", ("input_channels",))
        if not offline:
            duplex = bool(client is not None and client.duplex) if network else True
            state = "unavailable" if not duplex else "off" if muted else running
            add("output_mix", "remote_output" if network else "physical_output", ("output_channels",), state)
        else:
            add(
                monitor.route.source,
                "physical_monitor",
                ("monitor_buffer", "monitor_gain"),
                monitor.state,
                monitor.reason,
            )
    return RoutingSnapshot(
        backend,
        clock,
        sample_rate,
        input_label,
        output_label,
        tuple(connections),
        monitor,
        output_destination,
        not offline and not reserved,
        dut.name if dut_active else "",
        dut.input_routes if dut_active else (),
        dut.return_routes if dut_active else (),
        input_mode,
        output_mode,
    )
