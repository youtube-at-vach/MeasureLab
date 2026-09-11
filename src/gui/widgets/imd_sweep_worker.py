"""Worker-owned IMD procedure and immutable result notifications."""

from dataclasses import asdict
from datetime import datetime, timezone
import math
import threading
import time
import uuid

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.imd_sweep import BandPlan, PowerAverage, snapshot_copy
from src.core.imd_sweep_acquisition import StepCapture, SweepAcquisition
from src.core.version import __version__


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class IMDSweepWorker(QThread):
    snapshot_ready = pyqtSignal(dict)
    progress = pyqtSignal(int, int)

    def __init__(self, module, settings):
        super().__init__()
        self.module = module
        self.settings = settings
        self.cancel = threading.Event()
        self.acquisition = None
        self.run_id = str(uuid.uuid4())
        self.snapshot = {
            "schema": "measurelab.imd_sweep",
            "schema_version": 1,
            "run_id": self.run_id,
            "app_version": __version__,
            "started_at": utc_now(),
            "ended_at": None,
            "status": "running",
            "reason": None,
            "complete": False,
            "quality": "valid",
            "planned_points": settings.steps,
            "acquired_points": 0,
            "warnings": [],
            "metadata": {},
            "steps": [],
        }
        self.started_monotonic = time.monotonic()

    def stop(self):
        self.cancel.set()

    def _publish(self):
        self.snapshot_ready.emit(snapshot_copy(self.snapshot))

    def _guard(self):
        if self.cancel.is_set():
            raise ValueError("cancelled")
        engine = self.module.audio_engine
        if not engine.is_active():
            raise ValueError("stream_stopped")
        if self.module.settings_generation != self.module_generation:
            raise ValueError("settings_changed")
        if (
            engine.settings_generation != self.acquisition.generation
            or engine.calibration.settings_generation != self.acquisition.calibration_generation
        ):
            raise ValueError("settings_changed")
        if self.acquisition.fatal:
            raise ValueError(self.acquisition.fatal)
        if engine.output_overload_events != self.acquisition.overload_events:
            raise ValueError("output_clipping")
        if engine.callback_error_count != self.acquisition.error_count:
            raise ValueError("callback_exception")

    def _preflight(self):
        engine = self.module.audio_engine
        self.plan = BandPlan(self.settings, float(engine.sample_rate))
        if not self.module.output_enabled or engine.mute_output:
            raise ValueError("output_disabled")
        for channel, mode in (
            (self.module.input_channel, engine.input_channel_mode),
            (self.module.output_channel, engine.output_channel_mode),
        ):
            if channel < 0 or channel >= (2 if mode == "stereo" else 1):
                raise ValueError("invalid_channel")
        cal = engine.calibration
        for value in (
            cal.input_sensitivity,
            cal.output_gain,
            cal.frequency_calibration,
            cal.frequency_calibration_1pps,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("invalid_calibration")
        calibrated = bool(cal.input_sensitivity_is_calibrated)
        self.sensitivity = float(cal.input_sensitivity) if calibrated else None
        self.snapshot["warnings"] = self.plan.warnings + ([] if calibrated else ["uncalibrated"])
        self.snapshot["metadata"] = {
            **self.plan.metadata(),
            "block_size": engine.block_size,
            "input_channel": self.module.input_channel,
            "output_channel": self.module.output_channel,
            "input_device": engine.input_device,
            "output_device": engine.output_device,
            "backend": "network" if engine.network_mode else "offline" if engine.offline_mode else "portaudio",
            "input_routing": engine.input_channel_mode,
            "output_routing": engine.output_channel_mode,
            "loopback": engine.loopback,
            "dithering": engine.dithering_enabled,
            "dithering_bit_depth": engine.dithering_bit_depth,
            "calibration": {
                "valid": calibrated,
                "input_sensitivity_Vpeak_per_FS": self.sensitivity,
                "profile": cal.last_profile,
                "output_gain": cal.output_gain,
            },
        }
        # Resolve device descriptions/host APIs off the callback thread.
        if not engine.offline_mode and not engine.network_mode:
            import sounddevice as sd

            self.snapshot["metadata"]["devices"] = {
                direction: dict(sd.query_devices(device, direction))
                for direction, device in (("input", engine.input_device), ("output", engine.output_device))
            }
            self.snapshot["metadata"]["host_apis"] = [dict(api) for api in sd.query_hostapis()]
        if self.cancel.is_set():
            raise ValueError("cancelled")
        module_generation = self.module.settings_generation
        calibration_generation = cal.settings_generation
        expected_rate = engine.sample_rate
        if not engine.ensure_stream_running():
            raise ValueError("stream_start_failed")
        if (
            self.module.settings_generation != module_generation
            or cal.settings_generation != calibration_generation
            or engine.sample_rate != expected_rate
            or engine.mute_output
        ):
            raise ValueError("settings_changed")
        actual_rate = getattr(getattr(engine, "stream", None), "samplerate", engine.sample_rate)
        if actual_rate != engine.sample_rate:
            raise ValueError("settings_changed")
        # Revalidate actual rate after stream negotiation before registering output.
        self.plan = BandPlan(self.settings, float(engine.sample_rate))
        self.snapshot["metadata"].update(self.plan.metadata())
        self.snapshot["warnings"] = self.plan.warnings + ([] if calibrated else ["uncalibrated"])
        self.module_generation = self.module.settings_generation
        self.acquisition = SweepAcquisition(
            engine,
            self.plan,
            self.module.input_channel,
            self.module.output_channel,
            engine.settings_generation,
            cal.settings_generation,
        )

    def _step(self, index, level):
        p = self.plan.profile
        amplitude = 10 ** (level / 20)
        a1, a2 = amplitude * p.ratio / (p.ratio + 1), amplitude / (p.ratio + 1)
        step = {
            "index": index,
            "command_dbfs": level,
            "A1": a1,
            "A2": a2,
            "theoretical_rms_FS": math.sqrt((a1 * a1 + a2 * a2) / 2),
            "started_seconds": time.monotonic() - self.started_monotonic,
            "ended_seconds": None,
            "sample_start": None,
            "sample_end": None,
            "record_count": 0,
            "validity": "invalid",
            "flags": list(self.snapshot["warnings"]),
            "input_peak": None,
            "output_clipping": None,
            "ratio": None,
            "percent": None,
            "relative_dB": None,
            "zero_numerator": False,
            "components": [
                {
                    "component_id": key,
                    "frequency": f,
                    "band_hz": self.plan.bands[key],
                    "level_rms_FS": None,
                    "level_dBFS": None,
                    "Vrms": None,
                    "dBV": None,
                    "ratio": None,
                    "percent": None,
                    "relative_dB": None,
                }
                for key, f in p.components.items()
            ],
        }
        capture = StepCapture(self.run_id, index, level, self.plan)
        average = PowerAverage(self.plan)
        self.acquisition.command = capture
        timeout = self.plan.n / self.plan.sample_rate + max(
            2, 4 * self.module.audio_engine.block_size / self.plan.sample_rate
        )
        deadline = time.monotonic() + timeout + (self.settings.fade_ms + self.settings.settling_ms) / 1000
        previous_end = None
        try:
            while average.count < self.settings.averages:
                self._guard()
                if capture.flags:
                    step["flags"].extend(sorted(capture.flags))
                    break
                if not capture.ready:
                    if time.monotonic() >= deadline:
                        raise ValueError("capture_timeout")
                    self.cancel.wait(0.002)
                    continue
                identity, record, slot, start, end = capture.ready.popleft()
                try:
                    if (
                        identity != capture.identity
                        or record != average.count
                        or (previous_end is not None and start != previous_end)
                    ):
                        raise ValueError("input_discontinuity")
                    step["record_count"] = record + 1
                    step["sample_start"] = start if step["sample_start"] is None else step["sample_start"]
                    step["sample_end"] = end
                    average.add(capture.buffers[slot])
                finally:
                    capture.free.append(slot)
                previous_end = end
                deadline = time.monotonic() + timeout
            # Let the engine finish its output overload check for the last callback.
            boundary = self.acquisition.sample_index
            while self.acquisition.sample_index <= boundary:
                self._guard()
                if time.monotonic() >= deadline:
                    raise ValueError("capture_timeout")
                self.cancel.wait(0.002)
            self._guard()
            if not capture.flags and average.count == self.settings.averages:
                result = average.result(self.sensitivity)
                flags = step["flags"] + result.pop("flags")
                if average.flags:
                    step["diagnostic"] = result
                else:
                    step.update(result)
                step["flags"] = flags
                step["validity"] = "invalid" if average.flags else "qualified" if flags else "valid"
            if not self.module.audio_engine.offline_mode:
                step["output_clipping"] = False
        except ValueError as exc:
            reason = str(exc)
            step["flags"].append(reason)
            if reason == "output_clipping":
                step["output_clipping"] = True
            raise
        except Exception:
            step["flags"].append("worker_exception")
            raise
        finally:
            if average.peak:
                step["input_peak"] = average.peak
            step["ended_seconds"] = time.monotonic() - self.started_monotonic
            self.snapshot["steps"].append(step)
            self.snapshot["acquired_points"] = len(self.snapshot["steps"])
            self._quality()
            self._publish()

    def _quality(self):
        qualities = [s["validity"] for s in self.snapshot["steps"]]
        self.snapshot["quality"] = (
            "invalid"
            if "invalid" in qualities
            else "qualified"
            if self.snapshot["warnings"] or "qualified" in qualities
            else "valid"
        )

    def run(self):
        engine = self.module.audio_engine
        callback_id = None
        try:
            self._preflight()
            callback_id = engine.register_callback(self.acquisition.callback)
            self.module.is_running = True
            self._publish()
            for index, level in enumerate(self.settings.levels):
                self._step(index, level)
                self.progress.emit(index + 1, self.settings.steps)
            self.snapshot["status"] = "completed"
            self.snapshot["complete"] = all(
                step["record_count"] == self.settings.averages for step in self.snapshot["steps"]
            )
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "worker_exception"
            self.snapshot["status"] = "cancelled" if reason == "cancelled" else "failed"
            self.snapshot["reason"] = reason
            self.snapshot["error_detail"] = str(exc)
            if not self.snapshot["metadata"]:
                self.snapshot["metadata"] = {
                    "requested_settings": {
                        key: None if isinstance(value, float) and not math.isfinite(value) else value
                        for key, value in asdict(self.settings).items()
                    }
                }
            if not self.snapshot["steps"]:
                self.snapshot["quality"] = "invalid"
        finally:
            if self.acquisition is not None:
                self.acquisition.stopping = True
                deadline = time.monotonic() + self.settings.fade_ms / 1000 + 0.5
                while not self.acquisition.silent and engine.is_active() and time.monotonic() < deadline:
                    time.sleep(0.002)
            if callback_id is not None:
                try:
                    engine.unregister_callback(callback_id)
                except Exception as exc:
                    self.snapshot.update(
                        status="failed", reason="stream_stop_failed", complete=False, error_detail=str(exc)
                    )
            self.module.is_running = False
            self.snapshot["ended_at"] = utc_now()
            self._publish()
