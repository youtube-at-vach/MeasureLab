"""Best-effort physical audition, independent of the measurement clock.

Only control-thread methods open/close PortAudio streams. Neither audio producer
nor consumer waits for a lock. Each activation owns a fresh bounded buffer, so
in-flight measurement blocks cannot cross a stop/reconfigure/start boundary.
"""

from dataclasses import replace
import math
import threading

import numpy as np
import sounddevice as sd

from src.core.routing import MonitorRoute, MonitorSource, MonitorStatus


class MonitorBuffer:
    def __init__(self, sample_rate: float, block_size: int):
        self.target = max(2, math.ceil(sample_rate * 0.1 / block_size)) * block_size
        self.capacity = 4 * self.target
        self.data = np.empty((self.capacity, 2), dtype=np.float32)
        self.lock = threading.Lock()
        self.read_pos = 0
        self.size = 0
        self.primed = False
        self.played = False
        self.dropped = 0
        self.missing = 0

    def put(self, data: np.ndarray) -> None:
        frames = len(data)
        if not self.lock.acquire(blocking=False):
            self.dropped += frames
            return
        try:
            if self.size + frames > self.capacity:
                # Retain only the newest target-sized window, including data
                # from this block. Never let accumulated latency grow unbounded.
                keep_new = min(frames, self.target)
                keep_old = self.target - keep_new
                discard_old = max(0, self.size - keep_old)
                self.read_pos = (self.read_pos + discard_old) % self.capacity
                self.size -= discard_old
                self.dropped += discard_old + frames - keep_new
                data = data[-keep_new:]
                frames = keep_new
            write_pos = (self.read_pos + self.size) % self.capacity
            first = min(frames, self.capacity - write_pos)
            self.data[write_pos : write_pos + first] = data[:first]
            if first < frames:
                self.data[: frames - first] = data[first:]
            self.size += frames
        finally:
            self.lock.release()

    def read_into(self, output: np.ndarray) -> None:
        output.fill(0)
        frames = len(output)
        if not self.lock.acquire(blocking=False):
            self.missing += frames
            return
        try:
            if not self.primed:
                if self.size < self.target:
                    return
                self.primed = True
            available = min(frames, self.size)
            first = min(available, self.capacity - self.read_pos)
            self._copy(output[:first], self.data[self.read_pos : self.read_pos + first])
            if first < available:
                self._copy(output[first:available], self.data[: available - first])
            self.read_pos = (self.read_pos + available) % self.capacity
            self.size -= available
            self.played |= available > 0
            if available < frames:
                self.missing += frames - available
                self.primed = False
        finally:
            self.lock.release()

    @staticmethod
    def _copy(output: np.ndarray, data: np.ndarray) -> None:
        if output.shape[1] == 2:
            np.copyto(output, data)
        else:
            np.add(data[:, 0], data[:, 1], out=output[:, 0])
            output *= 0.5


class MonitorSession:
    def __init__(self, route: MonitorRoute, sample_rate: float, block_size: int):
        self.source = route.source
        self.buffer = MonitorBuffer(sample_rate, block_size)
        self.accepting = True
        self.error = ""

    def fail(self, reason: str) -> None:
        # Called from audio threads too: immediately gate all further reads.
        # The control thread subsequently discards this entire session.
        self.accepting = False
        self.error = reason


class MonitorOutput:
    def __init__(self):
        self.route = MonitorRoute()
        self.session: MonitorSession | None = None
        self.stream = None
        self.error = ""
        self._gain = 0.1
        self._control_lock = threading.RLock()
        self._last_dropped = 0
        self._last_missing = 0

    def configure(
        self, *, source: MonitorSource | None = None, device: int | None = None, gain_db: float | None = None
    ) -> None:
        with self._control_lock:
            route = self.route
            if route.enabled and (source is not None or device is not None):
                raise RuntimeError("Turn off the monitor before changing its source or device.")
            if source is not None:
                if source not in ("dut_output", "measurement_return", "output_mix"):
                    raise ValueError("Unknown monitor source.")
                route = replace(route, source=source)
            if gain_db is not None:
                if not math.isfinite(gain_db) or not -60 <= gain_db <= 0:
                    raise ValueError("Monitor gain must be between -60 and 0 dB.")
                route = replace(route, gain_db=float(gain_db))
            if device is not None:
                if not isinstance(device, int) or isinstance(device, bool) or device < 0:
                    raise ValueError("Select a physical output device.")
                info = sd.query_devices(device)
                channels = min(2, int(info["max_output_channels"]))
                if channels < 1:
                    raise ValueError("Select a physical output device.")
                route = replace(
                    route, device=device, device_name=str(info["name"]), hostapi=int(info["hostapi"]), channels=channels
                )
            self.route = route
            self._gain = 10 ** (route.gain_db / 20)

    def enable(self, enabled: bool) -> None:
        with self._control_lock:
            self.stop()
            if self.stream is not None:
                # A driver that failed to close still owns its device. Keep
                # the handle for another explicit cleanup attempt, never open
                # a second stream or clear the cleanup error.
                self.route = replace(self.route, enabled=False)
                return
            self.route = replace(self.route, enabled=bool(enabled))
            self.error = ""
            self._last_dropped = self._last_missing = 0

    def start(self, sample_rate: float, block_size: int, *, extra_settings=None) -> None:
        with self._control_lock:
            if not self.route.enabled or self.stream is not None or self.error:
                return
            stream = None
            session = MonitorSession(self.route, sample_rate, block_size)
            try:
                route = self.route
                if route.device is None:
                    raise RuntimeError("Select a physical output device.")
                info = sd.query_devices(route.device)
                if (str(info["name"]), int(info["hostapi"])) != (route.device_name, route.hostapi):
                    raise RuntimeError("The selected monitor device is no longer available.")
                sd.check_output_settings(
                    device=route.device,
                    channels=route.channels,
                    dtype="float32",
                    samplerate=sample_rate,
                    extra_settings=extra_settings,
                )

                def callback(outdata, frames, time, status):
                    outdata.fill(0)
                    if not session.accepting:
                        return
                    try:
                        if status.output_underflow:
                            session.buffer.missing += frames
                        session.buffer.read_into(outdata)
                        outdata *= self._gain
                        np.clip(outdata, -1.0, 1.0, out=outdata)
                        if not session.accepting:
                            outdata.fill(0)
                    except Exception as exc:
                        outdata.fill(0)
                        session.fail(str(exc))

                stream = sd.OutputStream(
                    device=route.device,
                    samplerate=sample_rate,
                    channels=route.channels,
                    dtype="float32",
                    blocksize=block_size,
                    latency="high",
                    extra_settings=extra_settings,
                    dither_off=True,
                    callback=callback,
                )
                self.session = session
                stream.start()
                self.stream = stream
            except Exception as exc:
                session.fail(str(exc))
                self.error = str(exc)
                self.session = None
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        # Preserve the original open/start failure for the UI.
                        self.error += " (stream cleanup failed)"
                        self.stream = stream

    def submit(self, session: MonitorSession | None, source: np.ndarray) -> None:
        if session is None or session is not self.session or not session.accepting:
            return
        try:
            with np.errstate(over="ignore", invalid="ignore"):
                audio = np.asarray(source, dtype=np.float32)
            if not np.isfinite(audio).all():
                session.fail("Monitor source contains non-finite samples.")
                return
            session.buffer.put(audio)
        except Exception as exc:
            session.fail(str(exc))

    def stop(self) -> None:
        with self._control_lock:
            session, self.session = self.session, None
            if session is not None:
                session.accepting = False
                self._last_dropped = session.buffer.dropped
                self._last_missing = session.buffer.missing
                if session.error:
                    self.error = session.error
            stream, self.stream = self.stream, None
            if stream is not None:
                try:
                    stream.abort()
                except Exception as exc:
                    self.error = str(exc)
                finally:
                    try:
                        stream.close()
                    except Exception as exc:
                        self.error = str(exc)
                        self.stream = stream

    def poll(self) -> None:
        """Reap failed streams from a control thread, never an audio callback."""
        with self._control_lock:
            if self.session is not None and self.session.error:
                self.stop()
            elif self.stream is not None and self.session is not None:
                try:
                    active = self.stream.active
                except Exception as exc:
                    self.error = str(exc)
                    self.stop()
                else:
                    if not active:
                        self.error = "The physical monitor stream stopped unexpectedly."
                        self.stop()

    def status(self, unavailable: str = "") -> MonitorStatus:
        with self._control_lock:
            self.poll()
            latency = 0.0
            if self.stream is not None and self.session is not None:
                try:
                    latency = float(self.stream.latency)
                except Exception as exc:
                    self.error = str(exc)
                    self.stop()
            return self._status(unavailable, latency)

    def _status(self, unavailable: str, latency: float) -> MonitorStatus:
        route = self.route
        session = self.session
        if self.error:
            state, reason = "error", self.error
        elif not route.enabled:
            state, reason = "off", unavailable
        elif unavailable:
            state, reason = "unavailable", unavailable
        elif session is None or not session.buffer.played:
            state, reason = "waiting", ""
        else:
            state = "dropout" if session.buffer.dropped or session.buffer.missing else "playing"
            reason = ""
        return MonitorStatus(
            route,
            state,
            reason,
            session.buffer.dropped if session else self._last_dropped,
            session.buffer.missing if session else self._last_missing,
            session.buffer.size if session else 0,
            latency,
        )
