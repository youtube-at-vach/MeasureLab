"""Shared network-audio state and callback-compatible status objects."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(slots=True)
class NetworkStatusFlags:
    """Small subset of ``sounddevice.CallbackFlags`` used by MeasureLab.

    Network loss is deliberately represented as an XRUN-like condition so
    measurement widgets that already reject PortAudio discontinuities also
    reject damaged network blocks.
    """

    input_underflow: bool = False
    input_overflow: bool = False
    output_underflow: bool = False
    output_overflow: bool = False
    priming_output: bool = False

    def __bool__(self) -> bool:
        return any(
            (
                self.input_underflow,
                self.input_overflow,
                self.output_underflow,
                self.output_overflow,
                self.priming_output,
            )
        )

    def __str__(self) -> str:
        names = [
            name.replace("_", " ")
            for name in (
                "input_underflow",
                "input_overflow",
                "output_underflow",
                "output_overflow",
                "priming_output",
            )
            if getattr(self, name)
        ]
        return ", ".join(names) if names else "no flags"


@dataclass(slots=True)
class NetworkStreamTime:
    """PortAudio-compatible timing values derived from remote sample time."""

    inputBufferAdcTime: float
    outputBufferDacTime: float
    currentTime: float


class NetworkAudioStats:
    """Thread-safe network health counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "disconnected"
        self.rx_packets = 0
        self.tx_packets = 0
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.lost_packets = 0
        self.lost_frames = 0
        self.late_packets = 0
        self.duplicate_packets = 0
        self.corrupt_packets = 0
        self.remote_input_xruns = 0
        self.remote_output_xruns = 0
        self.local_queue_overflows = 0
        self.jitter_frames = 0
        self.buffered_frames = 0
        self.last_error: str | None = None

    def set_state(self, state: str, error: str | None = None) -> None:
        with self._lock:
            self.state = state
            if error is not None:
                self.last_error = str(error)

    def record_rx(self, size: int) -> None:
        with self._lock:
            self.rx_packets += 1
            self.rx_bytes += max(0, int(size))

    def record_tx(self, size: int) -> None:
        with self._lock:
            self.tx_packets += 1
            self.tx_bytes += max(0, int(size))

    def record_duplicate(self) -> None:
        with self._lock:
            self.duplicate_packets += 1

    def record_late(self) -> None:
        with self._lock:
            self.late_packets += 1

    def record_corrupt(self, error: str) -> None:
        with self._lock:
            self.corrupt_packets += 1
            self.last_error = str(error)

    def record_queue_overflow(self, frames: int) -> None:
        with self._lock:
            self.local_queue_overflows += 1
            self.lost_frames += max(0, int(frames))

    def record_loss(self, frames: int) -> None:
        with self._lock:
            self.lost_packets += 1
            self.lost_frames += max(0, int(frames))

    def record_remote_xrun(self, *, input_xrun: bool = False, output_xrun: bool = False) -> None:
        with self._lock:
            self.remote_input_xruns += int(bool(input_xrun))
            self.remote_output_xruns += int(bool(output_xrun))

    def set_buffered_frames(self, frames: int) -> None:
        with self._lock:
            self.buffered_frames = max(0, int(frames))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "state": self.state,
                "rx_packets": self.rx_packets,
                "tx_packets": self.tx_packets,
                "rx_bytes": self.rx_bytes,
                "tx_bytes": self.tx_bytes,
                "lost_packets": self.lost_packets,
                "lost_frames": self.lost_frames,
                "late_packets": self.late_packets,
                "duplicate_packets": self.duplicate_packets,
                "corrupt_packets": self.corrupt_packets,
                "remote_input_xruns": self.remote_input_xruns,
                "remote_output_xruns": self.remote_output_xruns,
                "local_queue_overflows": self.local_queue_overflows,
                "jitter_frames": self.jitter_frames,
                "buffered_frames": self.buffered_frames,
                "last_error": self.last_error,
            }

    def acknowledge_integrity_errors(self) -> None:
        """Clear latched incident counters without changing connection state."""
        with self._lock:
            self.lost_packets = 0
            self.lost_frames = 0
            self.late_packets = 0
            self.duplicate_packets = 0
            self.corrupt_packets = 0
            self.remote_input_xruns = 0
            self.remote_output_xruns = 0
            self.local_queue_overflows = 0
            if self.state != "error":
                self.last_error = None
