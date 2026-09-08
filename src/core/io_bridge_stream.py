"""Bounded, stateful audio buffering used by the I/O Bridge.

The bridge deliberately keeps the PortAudio callbacks small: callbacks only
copy samples into or out of preallocated buffers.  Channel mapping and the
stateful linear converter run on a worker thread so a slow device never stalls
the measurement callback.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading
from typing import Any, Literal

import numpy as np
import sounddevice as sd


class BoundedAudioBuffer:
    """A bounded frame FIFO with non-blocking writes and zero-filled reads."""

    def __init__(self, capacity_frames: int, channels: int, *, dtype=np.float32) -> None:
        if capacity_frames < 1 or channels < 1:
            raise ValueError("audio buffer dimensions must be positive")
        self.capacity_frames = int(capacity_frames)
        self.channels = int(channels)
        self._data = np.zeros((self.capacity_frames, self.channels), dtype=dtype)
        self._read_index = 0
        self._write_index = 0
        self._size = 0
        self._dropped_frames = 0
        self._lock = threading.Lock()

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    def clear(self) -> None:
        with self._lock:
            self._read_index = 0
            self._write_index = 0
            self._size = 0

    def available_frames(self) -> int:
        with self._lock:
            return self._size

    def write(self, block: np.ndarray) -> bool:
        """Write a block without waiting; return False when old data was dropped."""
        array = np.asarray(block)
        if array.ndim == 1:
            array = array[:, None]
        if array.ndim != 2 or array.shape[1] != self.channels:
            raise ValueError(f"expected audio block with {self.channels} channels")
        frames = int(array.shape[0])
        if frames == 0:
            return True

        with self._lock:
            overflow = False
            if frames >= self.capacity_frames:
                # Keeping the newest samples is the safest recovery from a
                # stalled producer.  Never replay a stale block after a full
                # queue.
                array = array[-self.capacity_frames :]
                frames = self.capacity_frames
                self._read_index = 0
                self._write_index = 0
                self._size = 0
                overflow = True
                self._dropped_frames += int(array.shape[0])
            elif self._size + frames > self.capacity_frames:
                drop = self._size + frames - self.capacity_frames
                self._read_index = (self._read_index + drop) % self.capacity_frames
                self._size -= drop
                self._dropped_frames += drop
                overflow = True

            first = min(frames, self.capacity_frames - self._write_index)
            np.copyto(self._data[self._write_index : self._write_index + first], array[:first], casting="unsafe")
            if first < frames:
                np.copyto(self._data[: frames - first], array[first:], casting="unsafe")
            self._write_index = (self._write_index + frames) % self.capacity_frames
            self._size += frames
            np.nan_to_num(self._data, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
            return not overflow

    def read_into(self, destination: np.ndarray) -> int:
        """Read into an existing array and zero-fill any unavailable frames."""
        if destination.ndim != 2 or destination.shape[1] != self.channels:
            raise ValueError(f"expected destination with {self.channels} channels")
        frames = int(destination.shape[0])
        destination.fill(0)
        if frames == 0:
            return 0

        with self._lock:
            count = min(frames, self._size)
            first = min(count, self.capacity_frames - self._read_index)
            np.copyto(destination[:first], self._data[self._read_index : self._read_index + first], casting="unsafe")
            if first < count:
                np.copyto(destination[first:count], self._data[: count - first], casting="unsafe")
            self._read_index = (self._read_index + count) % self.capacity_frames
            self._size -= count
            return count


class StreamingLinearResampler:
    """A small stateful linear converter that never resets phase per block."""

    def __init__(self, source_rate: float, target_rate: float, channels: int) -> None:
        if source_rate <= 0 or target_rate <= 0 or channels < 1:
            raise ValueError("invalid resampler format")
        self.source_rate = float(source_rate)
        self.target_rate = float(target_rate)
        self.channels = int(channels)
        self.step = self.source_rate / self.target_rate
        self._pending: np.ndarray | None = None
        self._position = 0.0

    def reset(self) -> None:
        self._pending = None
        self._position = 0.0

    def process(self, block: np.ndarray) -> np.ndarray:
        array = np.asarray(block, dtype=np.float32)
        if array.ndim == 1:
            array = array[:, None]
        if array.ndim != 2 or array.shape[1] != self.channels:
            raise ValueError(f"expected block with {self.channels} channels")
        if array.shape[0] == 0:
            return np.empty((0, self.channels), dtype=np.float32)

        if self._pending is None:
            combined = np.array(array, dtype=np.float32, copy=True)
        else:
            combined = np.concatenate((self._pending, array), axis=0)

        limit = float(combined.shape[0] - 1)
        if self._position >= limit:
            self._pending = combined[-1:, :].copy()
            self._position = 0.0
            return np.empty((0, self.channels), dtype=np.float32)

        count = int(np.floor((limit - self._position) / self.step)) + 1
        positions = self._position + self.step * np.arange(count, dtype=np.float64)
        left = np.floor(positions).astype(np.intp)
        fraction = (positions - left).astype(np.float32)
        right = np.minimum(left + 1, combined.shape[0] - 1)
        result = combined[left] + (combined[right] - combined[left]) * fraction[:, None]

        self._pending = combined[-1:, :].copy()
        self._position = float(positions[-1] + self.step - limit)
        return np.asarray(result, dtype=np.float32)


def map_audio_channels(block: np.ndarray, channels: int, mode: str = "stereo") -> np.ndarray:
    """Map mono/stereo audio explicitly without summing channels accidentally."""
    array = np.asarray(block, dtype=np.float32)
    if array.ndim == 1:
        array = array[:, None]
    if array.ndim != 2:
        raise ValueError("audio block must be two-dimensional")
    channels = int(channels)
    if channels == 1:
        if mode == "right" and array.shape[1] >= 2:
            return array[:, 1:2].copy()
        if mode == "left" or array.shape[1] == 1:
            return array[:, :1].copy()
        return (0.5 * (array[:, :1] + array[:, 1:2])).astype(np.float32, copy=False)
    if channels != 2:
        raise ValueError("only mono and stereo bridge streams are supported")
    if array.shape[1] == 1:
        return np.repeat(array[:, :1], 2, axis=1)
    if mode == "left":
        return np.repeat(array[:, :1], 2, axis=1)
    if mode == "right":
        return np.repeat(array[:, 1:2], 2, axis=1)
    return array[:, :2].copy()


class IOBridgeStream:
    """Manage one auxiliary local input or output stream and its worker."""

    def __init__(
        self,
        direction: Literal["input", "output"],
        *,
        device,
        sample_rate: int,
        block_size: int,
        channels: int,
        source_rate: int,
        source_channels: int,
        channel_mode: str = "stereo",
        capacity_ms: int = 200,
        transform: Callable[[np.ndarray], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        extra_settings=None,
    ) -> None:
        if direction not in ("input", "output"):
            raise ValueError("direction must be input or output")
        self.direction = direction
        self.device = device
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.channels = int(channels)
        self.source_rate = int(source_rate)
        self.source_channels = int(source_channels)
        self.channel_mode = str(channel_mode)
        self.capacity_ms = int(capacity_ms)
        capacity = max(self.block_size * 4, round(self.sample_rate * self.capacity_ms / 1000))
        source_capacity = max(self.block_size * 4, round(self.source_rate * self.capacity_ms / 1000))
        self._source_buffer = BoundedAudioBuffer(source_capacity, self.source_channels)
        self._destination_buffer = BoundedAudioBuffer(capacity, self.channels)
        self._resampler = StreamingLinearResampler(self.source_rate, self.sample_rate, self.source_channels)
        self._worker_wakeup = threading.Event()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._stream: Any | None = None
        self._transform = transform
        self._on_error = on_error
        self._extra_settings = extra_settings
        self._scratch = np.zeros((max(self.block_size * 4, 4096), self.source_channels), dtype=np.float32)
        self._mapped_scratch = np.empty((max(self.block_size * 8, 8192), self.channels), dtype=np.float32)
        self.underrun_count = 0
        self.overrun_count = 0
        self.last_error: str | None = None
        self.logger = logging.getLogger(__name__)

    @property
    def active(self) -> bool:
        return self._stream is not None and bool(getattr(self._stream, "active", False))

    @property
    def buffered_frames(self) -> int:
        return self._destination_buffer.available_frames()

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stop_event.clear()
        self._resampler.reset()
        self._source_buffer.clear()
        self._destination_buffer.clear()
        self._worker = threading.Thread(target=self._worker_loop, name="IOBridgeConvert", daemon=True)
        self._worker.start()
        try:
            if self.direction == "output":
                self._stream = sd.OutputStream(
                    device=self.device,
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    channels=self.channels,
                    dtype="float32",
                    callback=self._output_callback,
                    extra_settings=self._extra_settings,
                )
            else:
                self._stream = sd.InputStream(
                    device=self.device,
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    channels=self.channels,
                    dtype="float32",
                    callback=self._input_callback,
                    extra_settings=self._extra_settings,
                )
            self._stream.start()
        except Exception as exc:
            self._report_error(f"failed to start bridge {self.direction} stream: {exc}")
            self.stop()
            raise

    def push(self, block: np.ndarray) -> bool:
        """Queue source samples.  This method is intended for audio callbacks."""
        try:
            accepted = self._source_buffer.write(block)
        except (TypeError, ValueError) as exc:
            self._report_error(f"invalid bridge audio block: {exc}")
            return False
        if not accepted:
            self.overrun_count += 1
        self._worker_wakeup.set()
        return accepted

    def read_into(self, destination: np.ndarray) -> int:
        count = self._destination_buffer.read_into(destination)
        if count < destination.shape[0]:
            self.underrun_count += 1
        return count

    def clear(self) -> None:
        self._source_buffer.clear()
        self._destination_buffer.clear()
        self._resampler.reset()

    def stop(self) -> None:
        self._stop_event.set()
        self._worker_wakeup.set()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                self.logger.warning("Failed to close bridge %s stream: %s", self.direction, exc)
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.0)
        self._worker = None
        self.clear()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            count = self._source_buffer.read_into(self._scratch)
            if count == 0:
                self._worker_wakeup.wait(0.01)
                self._worker_wakeup.clear()
                continue
            try:
                converted = self._resampler.process(self._scratch[:count])
                if converted.shape[0] == 0:
                    continue
                mapped = map_audio_channels(converted, self.channels, self.channel_mode)
                self._destination_buffer.write(mapped)
            except (TypeError, ValueError, FloatingPointError) as exc:
                self._report_error(f"bridge conversion failed: {exc}")
                self.clear()

    def _input_callback(self, indata, frames, _time_info, status) -> None:
        if status:
            self._report_error(f"bridge input status: {status}")
        if self._stop_event.is_set():
            return
        self.push(np.asarray(indata, dtype=np.float32)[: int(frames), : self.source_channels])

    def _output_callback(self, outdata, frames, _time_info, status) -> None:
        outdata.fill(0)
        if status:
            self._report_error(f"bridge output status: {status}")
        if self._stop_event.is_set():
            return
        self.read_into(outdata[: int(frames), : self.channels])
        np.nan_to_num(outdata, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        if self._transform is not None:
            self._transform(outdata)
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def _report_error(self, message: str) -> None:
        self.last_error = str(message)
        self.logger.warning(self.last_error)
        if self._on_error is not None:
            try:
                self._on_error(self.last_error)
            except Exception:
                self.logger.exception("Bridge error callback failed")
