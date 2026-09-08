"""Controller for the persistent MeasureLab I/O Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging
import math
import threading
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from src.core.io_bridge_stream import IOBridgeStream

if TYPE_CHECKING:
    from src.core.audio_engine import AudioEngine


class IOBridgeRoute(StrEnum):
    """The two routes supported by the first I/O Bridge release."""

    PHYSICAL = "physical"
    REMOTE_OUTPUT = "remote_output"


class IOBridgeState(StrEnum):
    OFF = "off"
    STARTING = "starting"
    ON = "on"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class IOBridgeRouteAvailability:
    route: IOBridgeRoute
    available: bool
    reason: str | None = None
    input_label: str = ""
    output_label: str = ""


@dataclass(frozen=True, slots=True)
class IOBridgeSnapshot:
    """Read-only status returned to all UI consumers."""

    route: IOBridgeRoute
    state: IOBridgeState
    gain_db: float
    reason: str | None
    input_label: str
    output_label: str
    muted: bool
    buffered_frames: int
    dropped_frames: int
    underrun_count: int
    overrun_count: int
    generation: int

    @property
    def active(self) -> bool:
        return self.state is IOBridgeState.ON

    def as_dict(self) -> dict[str, object]:
        return {
            "route": self.route.value,
            "state": self.state.value,
            "gain_db": self.gain_db,
            "reason": self.reason,
            "input_label": self.input_label,
            "output_label": self.output_label,
            "muted": self.muted,
            "buffered_frames": self.buffered_frames,
            "dropped_frames": self.dropped_frames,
            "underrun_count": self.underrun_count,
            "overrun_count": self.overrun_count,
            "generation": self.generation,
        }


class IOBridgeController:
    """Own one bridge route and its auxiliary stream resources.

    The controller is intentionally independent of Qt.  GUI code calls the
    public methods from the event loop, while audio callbacks only call
    ``push_physical_input`` and ``fill_remote_output``.
    """

    MIN_GAIN_DB = -60.0
    MAX_GAIN_DB = 0.0
    DEFAULT_GAIN_DB = -20.0
    RAMP_MS = 10.0

    def __init__(self, audio_engine: AudioEngine) -> None:
        self.audio_engine = audio_engine
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._fade_done = threading.Event()
        self._local_config_cache: dict[str, object] = {}
        self._route = IOBridgeRoute.PHYSICAL
        self._state = IOBridgeState.OFF
        self._reason: str | None = None
        self._generation = 0
        self._physical_stream: IOBridgeStream | None = None
        self._remote_input_stream: IOBridgeStream | None = None
        self._master_started_by_bridge = False
        self._gain_db = self.DEFAULT_GAIN_DB
        self._gain_current = 0.0
        self._gain_target = self._db_to_linear(self.DEFAULT_GAIN_DB)
        self._gain_ramp_remaining = 0
        self._gain_curve = np.empty(max(4096, int(getattr(audio_engine, "block_size", 1024) * 8)), dtype=np.float32)

    @staticmethod
    def _db_to_linear(value: float) -> float:
        return float(10.0 ** (float(value) / 20.0))

    @staticmethod
    def _route_from_value(route: IOBridgeRoute | str) -> IOBridgeRoute:
        if isinstance(route, IOBridgeRoute):
            return route
        value = str(route).strip().lower()
        aliases = {
            "physical": IOBridgeRoute.PHYSICAL,
            "physical_output": IOBridgeRoute.PHYSICAL,
            "remote": IOBridgeRoute.REMOTE_OUTPUT,
            "remote_output": IOBridgeRoute.REMOTE_OUTPUT,
        }
        try:
            return aliases[value]
        except KeyError as exc:
            raise ValueError(f"unsupported I/O Bridge route: {route!r}") from exc

    @property
    def route(self) -> IOBridgeRoute:
        with self._lock:
            return self._route

    @property
    def gain_db(self) -> float:
        with self._lock:
            return self._gain_db

    def set_route(self, route: IOBridgeRoute | str) -> None:
        selected = self._route_from_value(route)
        with self._lock:
            if self._state in (IOBridgeState.STARTING, IOBridgeState.ON, IOBridgeState.STOPPING):
                raise RuntimeError("stop I/O Bridge before changing the output route")
            self._route = selected
            self._reason = None

    def set_gain_db(self, gain_db: float) -> float:
        try:
            value = float(gain_db)
        except (TypeError, ValueError) as exc:
            raise ValueError("I/O Bridge gain must be a finite number") from exc
        if not math.isfinite(value):
            raise ValueError("I/O Bridge gain must be finite")
        value = float(np.clip(value, self.MIN_GAIN_DB, self.MAX_GAIN_DB))
        with self._lock:
            self._gain_db = value
            self._gain_target = self._db_to_linear(value)
            self._gain_ramp_remaining = self._ramp_frames()
        return value

    def _ramp_frames(self) -> int:
        rate = self.audio_engine.sample_rate
        if self._route is IOBridgeRoute.PHYSICAL:
            rate = self._local_config_cache.get("sample_rate", rate)
        return max(1, round(float(rate) * self.RAMP_MS / 1000.0))

    def _local_audio_config(self) -> dict[str, object]:
        if self.is_active() and self._local_config_cache:
            return dict(self._local_config_cache)
        getter = getattr(self.audio_engine, "get_local_audio_config", None)
        if callable(getter):
            self._local_config_cache = dict(getter())
            return dict(self._local_config_cache)
        return {
            "input_device": self.audio_engine.input_device,
            "output_device": self.audio_engine.output_device,
            "sample_rate": self.audio_engine.sample_rate,
            "block_size": self.audio_engine.block_size,
            "input_channels": self.audio_engine.input_channel_mode,
            "output_channels": self.audio_engine.output_channel_mode,
        }

    def _extra_settings(self, local: dict[str, object], direction: str):
        getter = getattr(self.audio_engine, "get_bridge_device_settings", None)
        return getter(local.get(direction + "_device"), direction) if getter else None

    @staticmethod
    def _mode_channels(mode: object) -> int:
        return 1 if str(mode) in {"left", "right"} else 2

    def _physical_availability(self) -> IOBridgeRouteAvailability:
        if getattr(self.audio_engine, "network_mode", False):
            if getattr(self.audio_engine, "loopback", False):
                return IOBridgeRouteAvailability(
                    IOBridgeRoute.PHYSICAL,
                    False,
                    "Physical output is disabled while Remote Audio I/O loopback is enabled.",
                )
            client = getattr(self.audio_engine, "network_client", None)
            if client is None or not getattr(client, "connected", False):
                return IOBridgeRouteAvailability(
                    IOBridgeRoute.PHYSICAL,
                    False,
                    "Connect Remote Audio I/O before monitoring its input.",
                )
            local = self._local_audio_config()
            return IOBridgeRouteAvailability(
                IOBridgeRoute.PHYSICAL,
                True,
                input_label="Remote Input",
                output_label=str(local.get("output_device") or "Physical Output"),
            )
        if getattr(self.audio_engine, "offline_mode", False):
            dut = getattr(self.audio_engine, "vst_dut", None)
            if not getattr(dut, "loaded", False):
                return IOBridgeRouteAvailability(
                    IOBridgeRoute.PHYSICAL,
                    False,
                    "Load a VST3 DUT in Offline mode before using Physical output.",
                )
            local = self._local_audio_config()
            return IOBridgeRouteAvailability(
                IOBridgeRoute.PHYSICAL,
                True,
                input_label="Analysis Input (VST3 DUT)",
                output_label=str(local.get("output_device") or "Physical Output"),
            )
        return IOBridgeRouteAvailability(
            IOBridgeRoute.PHYSICAL,
            False,
            "Physical monitoring is available for Offline/VST3 or Remote Audio I/O.",
        )

    def _remote_availability(self) -> IOBridgeRouteAvailability:
        client = getattr(self.audio_engine, "network_client", None)
        if (
            not getattr(self.audio_engine, "network_mode", False)
            or client is None
            or not getattr(client, "connected", False)
        ):
            return IOBridgeRouteAvailability(
                IOBridgeRoute.REMOTE_OUTPUT,
                False,
                "Connect to a Remote Audio I/O provider with output enabled.",
            )
        if not getattr(client, "duplex", False):
            return IOBridgeRouteAvailability(
                IOBridgeRoute.REMOTE_OUTPUT,
                False,
                "The connected Remote Audio I/O provider does not allow output.",
            )
        if getattr(self.audio_engine, "loopback", False):
            return IOBridgeRouteAvailability(
                IOBridgeRoute.REMOTE_OUTPUT,
                False,
                "Remote output is disabled while Remote Audio I/O loopback is enabled.",
            )
        local = self._local_audio_config()
        return IOBridgeRouteAvailability(
            IOBridgeRoute.REMOTE_OUTPUT,
            True,
            input_label=str(local.get("input_device") or "Physical Input"),
            output_label=str(getattr(client, "output_device_name", "Remote Output") or "Remote Output"),
        )

    def _has_output_callbacks(self) -> bool:
        """Return whether an existing callback owns the mixed output path."""
        with self.audio_engine.lock:
            intents = getattr(self.audio_engine, "_callback_output_intents", {})
            return any(intent != "analysis" for intent in intents.values())

    def available_routes(self) -> dict[IOBridgeRoute, IOBridgeRouteAvailability]:
        return {
            IOBridgeRoute.PHYSICAL: self._physical_availability(),
            IOBridgeRoute.REMOTE_OUTPUT: self._remote_availability(),
        }

    def route_availability(self, route: IOBridgeRoute | str) -> IOBridgeRouteAvailability:
        selected = self._route_from_value(route)
        return self.available_routes()[selected]

    def is_active(self) -> bool:
        return self._state in (IOBridgeState.STARTING, IOBridgeState.ON, IOBridgeState.STOPPING)

    def is_physical_active(self) -> bool:
        return self._route is IOBridgeRoute.PHYSICAL and self._state in (IOBridgeState.STARTING, IOBridgeState.ON)

    def is_remote_output_active(self) -> bool:
        return self._route is IOBridgeRoute.REMOTE_OUTPUT and self._state in (
            IOBridgeState.STARTING,
            IOBridgeState.ON,
            IOBridgeState.STOPPING,
        )

    def should_suppress_master_output(self) -> bool:
        """Return whether generated module output must not reach Remote output."""
        return self.is_remote_output_active()

    def start(self, route: IOBridgeRoute | str | None = None, *, background: bool = False) -> bool:
        selected = self._route if route is None else self._route_from_value(route)
        with self._lock:
            if self._state is IOBridgeState.ON:
                return True
            if self._state in (IOBridgeState.STARTING, IOBridgeState.STOPPING):
                return False
            if route is not None:
                self._route = selected
            availability = self.route_availability(selected)
            if getattr(self.audio_engine, "_exclusive_owner", None) is not None or getattr(
                self.audio_engine, "_backend_transition", False
            ):
                availability = IOBridgeRouteAvailability(selected, False, "Audio engine is reserved or changing.")
            if selected is IOBridgeRoute.REMOTE_OUTPUT and availability.available and self._has_output_callbacks():
                availability = IOBridgeRouteAvailability(
                    selected,
                    False,
                    "Stop output-producing measurements before using Remote Output.",
                    availability.input_label,
                    availability.output_label,
                )
            if not availability.available:
                self._state = IOBridgeState.ERROR
                self._reason = availability.reason
                self._generation += 1
                return False
            self._state = IOBridgeState.STARTING
            self._reason = None
            self._generation += 1
            generation = self._generation
            self._gain_current = 0.0
            self._gain_target = self._db_to_linear(self._gain_db)
            self._gain_ramp_remaining = self._ramp_frames()

        if background:
            threading.Thread(
                target=self._open_resources, args=(selected, generation), name="IOBridgeStart", daemon=True
            ).start()
            return True
        return self._open_resources(selected, generation)

    def _open_resources(self, selected: IOBridgeRoute, generation: int) -> bool:
        with self._lifecycle_lock:
            with self._lock:
                if generation != self._generation:
                    return False
            return self._open_resources_locked(selected, generation)

    def _open_resources_locked(self, selected: IOBridgeRoute, generation: int) -> bool:
        physical_stream: IOBridgeStream | None = None
        remote_input_stream: IOBridgeStream | None = None
        master_started = False
        try:
            local = self._local_audio_config()
            local_rate = int(cast(Any, local.get("sample_rate") or self.audio_engine.sample_rate))
            local_block = int(cast(Any, local.get("block_size") or self.audio_engine.block_size))
            local_out_mode = str(local.get("output_channels") or "stereo")
            local_in_mode = str(local.get("input_channels") or "stereo")
            if selected is IOBridgeRoute.PHYSICAL:
                source_channels = (
                    2
                    if getattr(self.audio_engine, "offline_mode", False)
                    else self._mode_channels(self.audio_engine.input_channel_mode)
                )
                physical_stream = IOBridgeStream(
                    "output",
                    device=local.get("output_device"),
                    sample_rate=local_rate,
                    block_size=local_block,
                    channels=self._mode_channels(local_out_mode),
                    source_rate=int(self.audio_engine.sample_rate),
                    source_channels=source_channels,
                    hardware_channels=2 if local_out_mode == "right" else self._mode_channels(local_out_mode),
                    channel_mode=local_out_mode,
                    transform=self._apply_gain,
                    on_error=self._on_stream_error,
                    extra_settings=self._extra_settings(local, "output"),
                )
                physical_stream.start()
            else:
                client = self.audio_engine.network_client
                assert client is not None
                local_input_channels = 1 if local_in_mode == "left" else 2
                remote_input_stream = IOBridgeStream(
                    "input",
                    device=local.get("input_device"),
                    sample_rate=local_rate,
                    block_size=local_block,
                    channels=int(getattr(client, "output_channels", 2)),
                    target_rate=int(self.audio_engine.sample_rate),
                    hardware_channels=local_input_channels,
                    source_rate=local_rate,
                    source_channels=local_input_channels,
                    channel_mode=local_in_mode,
                    on_error=self._on_stream_error,
                    extra_settings=self._extra_settings(local, "input"),
                )
                remote_input_stream.start()

            with self._lock:
                if generation != self._generation:
                    raise RuntimeError("I/O Bridge start was cancelled")
            had_master_stream = self.audio_engine.stream is not None
            master_started = bool(self.audio_engine.ensure_stream_running())
            if not master_started:
                raise RuntimeError("Audio engine stream failed to start")
            master_started = not had_master_stream
            with self._lock:
                if generation != self._generation:
                    raise RuntimeError("I/O Bridge start was cancelled")
                self._physical_stream = physical_stream
                self._remote_input_stream = remote_input_stream
                self._master_started_by_bridge = master_started
                self._state = IOBridgeState.ON
            return True
        except Exception as exc:
            if physical_stream is not None:
                physical_stream.stop()
            if remote_input_stream is not None:
                remote_input_stream.stop()
            if master_started and not self.audio_engine.callbacks and not self.audio_engine.pipewire_jack_resident:
                try:
                    self.audio_engine.stop_stream(owner=self)
                except Exception:
                    self.logger.exception("Failed to close master stream after bridge start failure")
            with self._lock:
                if generation == self._generation:
                    self._state = IOBridgeState.ERROR
                    self._reason = str(exc)
                    self._physical_stream = None
                    self._remote_input_stream = None
                    self._master_started_by_bridge = False
            self.logger.warning("I/O Bridge failed to start: %s", exc)
            return False

    def stop(self, reason: str | None = None, *, background: bool = False) -> None:
        with self._lock:
            if self._state is IOBridgeState.OFF:
                return
            self._generation += 1
            generation = self._generation
            self._state = IOBridgeState.STOPPING
            physical = self._physical_stream
            remote_input = self._remote_input_stream
            self._gain_target = 0.0
            self._gain_ramp_remaining = self._ramp_frames()
            self._fade_done.clear()
            self._master_started_by_bridge = False

        def teardown() -> None:
            with self._lifecycle_lock:
                if physical is not None or remote_input is not None:
                    self._fade_done.wait(0.1)
                self._physical_stream = None
                self._remote_input_stream = None
                if physical is not None:
                    physical.stop()
                if remote_input is not None:
                    remote_input.stop()
                if not self.audio_engine.callbacks and not self.audio_engine.pipewire_jack_resident:
                    try:
                        self.audio_engine.stop_stream(owner=self)
                    except Exception:
                        self.logger.exception("Failed to close master stream when stopping I/O Bridge")
                with self._lock:
                    if generation == self._generation:
                        self._state = IOBridgeState.OFF
                        self._reason = reason

        if background:
            threading.Thread(target=teardown, name="IOBridgeStop", daemon=True).start()
        else:
            teardown()

    def fail(self, reason: str) -> None:
        """Latch an asynchronous stream failure and release resources."""
        with self._lock:
            if self._state in (IOBridgeState.OFF, IOBridgeState.ERROR):
                if self._state is IOBridgeState.ERROR and self._reason is None:
                    self._reason = str(reason)
                return
            self._generation += 1
            generation = self._generation
            self._state = IOBridgeState.ERROR
            self._reason = str(reason)
            physical = self._physical_stream
            remote_input = self._remote_input_stream
            self._physical_stream = None
            self._remote_input_stream = None
            self._master_started_by_bridge = False

        # Stream callbacks must not wait for device close operations.  The
        # teardown happens on a short-lived worker when fail() is called from a
        # PortAudio callback.
        def teardown() -> None:
            with self._lifecycle_lock:
                if physical is not None:
                    physical.stop()
                if remote_input is not None:
                    remote_input.stop()
                if (
                    generation == self._generation
                    and not self.audio_engine.callbacks
                    and not self.audio_engine.pipewire_jack_resident
                ):
                    try:
                        self.audio_engine.stop_stream(owner=self)
                    except Exception:
                        self.logger.exception("Failed to close master stream after I/O Bridge failure")

        threading.Thread(target=teardown, name="IOBridgeStop", daemon=True).start()

    def reset_error(self) -> None:
        with self._lock:
            if self._state is IOBridgeState.ERROR:
                self._state = IOBridgeState.OFF
                self._reason = None

    def push_physical_input(self, block: np.ndarray) -> None:
        stream = self._physical_stream
        active = self._route is IOBridgeRoute.PHYSICAL and self._state in (IOBridgeState.STARTING, IOBridgeState.ON)
        if active and stream is not None:
            stream.push(block)

    def fill_remote_output(self, destination: np.ndarray) -> None:
        stream = self._remote_input_stream
        active = self._route is IOBridgeRoute.REMOTE_OUTPUT and self._state in (
            IOBridgeState.STARTING,
            IOBridgeState.ON,
            IOBridgeState.STOPPING,
        )
        destination.fill(0)
        if active and stream is not None:
            stream.read_into(destination)
        self._apply_gain(destination)
        np.nan_to_num(destination, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        np.clip(destination, -1.0, 1.0, out=destination)

    def _apply_gain(self, block: np.ndarray) -> None:
        block = np.asarray(block)
        frames = int(block.shape[0])
        if not self._lock.acquire(blocking=False):
            block *= 0.0 if self.audio_engine.mute_output else self._gain_current
            return
        try:
            muted = bool(getattr(self.audio_engine, "mute_output", False))
            current = self._gain_current
            target = 0.0 if muted or self._state is IOBridgeState.STOPPING else self._gain_target
            remaining = self._gain_ramp_remaining
            if frames > self._gain_curve.shape[0]:
                self._gain_curve = np.empty(frames, dtype=np.float32)
            curve = self._gain_curve[:frames]
            if remaining > 0:
                ramp_count = min(frames, remaining)
                curve[:ramp_count] = current + (target - current) * (
                    np.arange(1, ramp_count + 1, dtype=np.float32) / remaining
                )
                if ramp_count < frames:
                    curve[ramp_count:] = target
                self._gain_current = float(curve[-1])
                self._gain_ramp_remaining = max(0, remaining - frames)
            else:
                curve.fill(target)
                self._gain_current = target
            block *= curve[:, None]
            if self._state is IOBridgeState.STOPPING and self._gain_ramp_remaining == 0:
                self._fade_done.set()
        finally:
            self._lock.release()

    def snapshot(self) -> IOBridgeSnapshot:
        with self._lock:
            stream = self._physical_stream or self._remote_input_stream
            dropped = 0
            buffered = 0
            underruns = 0
            overruns = 0
            if stream is not None:
                buffered = stream.buffered_frames
                underruns = stream.underrun_count
                overruns = stream.overrun_count
                dropped = stream._source_buffer.dropped_frames + stream._destination_buffer.dropped_frames
            availability = self.available_routes().get(self._route)
            return IOBridgeSnapshot(
                route=self._route,
                state=self._state,
                gain_db=self._gain_db,
                reason=self._reason,
                input_label=availability.input_label if availability is not None else "",
                output_label=availability.output_label if availability is not None else "",
                muted=bool(getattr(self.audio_engine, "mute_output", False)),
                buffered_frames=buffered,
                dropped_frames=dropped,
                underrun_count=underruns,
                overrun_count=overruns,
                generation=self._generation,
            )

    get_snapshot = snapshot

    def _on_stream_error(self, message: str) -> None:
        self.fail(message)


# Short aliases keep integrations readable while retaining the explicit public
# names used by the implementation plan.
BridgeRoute = IOBridgeRoute
BridgeState = IOBridgeState
